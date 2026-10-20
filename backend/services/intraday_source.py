"""数据管理专用分时取源：串行保护和有限重试，不缓存未入库行情。"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd
import redis

from backend.common.logging import get_logger
from backend.config import get_settings
from backend.datasource.akshare_source import AKShareSource
from backend.services.intraday_contract import candidate_rank, sanitize_minutes
from backend.services.intraday_quotes import IntradayServiceUnavailable
from backend.storage import get_redis_client

log = get_logger("services.intraday_source")
_SOURCE_PREFIX = "market:intraday:1m"
_EASTMONEY_FAILURE_LIMIT = 3
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class IntradaySourceCoolingDown(IntradayServiceUnavailable):
    """备用源熔断期间跳过请求，交由采集保留候选及重试资格。"""


class IntradaySourceService:
    """仅供采集、修复及数据管理的显式探活调用。"""

    def __init__(
        self,
        redis_client=None,
        source_factory: Callable[[], AKShareSource] = AKShareSource,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        ctx=None,
    ) -> None:
        self.ctx = ctx
        self.redis = redis_client if redis_client is not None else get_redis_client().client
        self.source_factory = source_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.config = get_settings().intraday
        self._reported_cooldown_until = None

    def _task_log(self, message: str, level: str = "info") -> None:
        # 请求前立即落日志，避免较长的锁等待/超时期间页面没有反馈。
        if self.ctx is not None:
            self.ctx.log(message, level)
            self.ctx.flush()

    def _pause(self, seconds: float) -> None:
        if self.ctx is None:
            self.sleep(seconds)
            return
        remaining = seconds
        while remaining > 0:
            self.ctx.check_cancel()
            step = min(0.1, remaining)
            self.sleep(step)
            remaining -= step

    def fetch_window(self, code: str, dates: list[str]) -> dict:
        """每股取一次近期候选，按目标日完整性决定备用源；不读取旧源窗口缓存。"""
        if self.ctx:
            self.ctx.check_cancel()
        if self.redis.get(self._negative_key(code)):
            raise IntradayServiceUnavailable("分时采集源暂时不可用，请稍后重试")
        windows: dict[str, dict] = {}
        source = self.source_factory()
        errors: list[str] = []
        for provider in ("sina", "eastmoney"):
            started = self.monotonic()
            try:
                frame = self._fetch_provider(source, code, provider)
                window = self._frame_to_window(frame, provider)
                windows[provider] = window
                if self.ctx is not None:
                    complete = sum(
                        candidate_rank([r for r in window["rows"] if r[0][:10] == day], provider)[0]
                        for day in dates
                    )
                    self._task_log(
                        f"{code} {'新浪' if provider == 'sina' else '东财'}返回 {len(window['rows'])} 个有效分钟点，"
                        f"目标日完整 {complete}/{len(dates)} 日"
                    )
                log.info(
                    "分时源请求成功 code=%s source=%s rows=%d elapsed_ms=%d",
                    code,
                    provider,
                    len(window["rows"]),
                    round((self.monotonic() - started) * 1000),
                )
                if self._targets_complete(windows, dates):
                    return self._with_candidates(self._pick_window(windows, dates), windows)
            except IntradaySourceCoolingDown:
                errors.append("eastmoney:暂时熔断，稍后重试")
            except (redis.RedisError, IntradayServiceUnavailable):
                raise
            except Exception as exc:  # noqa: BLE001
                if self.ctx:
                    self.ctx.check_cancel()
                errors.append(f"{provider}:{type(exc).__name__}")
                self._task_log(
                    f"{code} {'新浪' if provider == 'sina' else '东财'}取源失败：{type(exc).__name__}；"
                    + (
                        "转备用源" if provider == "sina" else "保留已取得的数据，未完整日期等待重试"
                    ),
                    "warn",
                )
                log.warning(
                    "分时源请求失败 code=%s source=%s elapsed_ms=%d reason=%s",
                    code,
                    provider,
                    round((self.monotonic() - started) * 1000),
                    type(exc).__name__,
                )
        ready = self._pick_window(windows, dates)
        if ready is not None:
            return {**self._with_candidates(ready, windows), "errors": errors}
        if errors:
            self.redis.set(
                self._negative_key(code), ",".join(errors), ex=self.config.negative_ttl_sec
            )
            raise IntradayServiceUnavailable("分时采集源暂时不可用，请稍后重试")
        return self._with_candidates(self._empty_window(windows), windows)

    def _fetch_provider(self, source: AKShareSource, code: str, provider: str) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(2):
            if self.ctx:
                self.ctx.check_cancel()
            if provider == "sina":
                self._task_log(f"{code} 新浪：等待串行保护")
            token = self._acquire_global_source_lock()
            state = None
            probe = False
            try:
                if provider == "eastmoney":
                    state, now = self._eastmoney_state()
                    until = state.get("open_until", 0)
                    if until > now:
                        if self._reported_cooldown_until != until:
                            self._task_log(
                                f"东财暂时熔断，约 {math.ceil(until - now)} 秒后恢复探测；"
                                "本轮继续保存新浪数据，未完整日期保留重试资格",
                                "warn",
                            )
                            self._reported_cooldown_until = until
                        raise IntradaySourceCoolingDown("东财暂时熔断，稍后重试")
                    probe = bool(until)
                    if probe:
                        self._task_log(f"{code} 东财熔断到期，执行一次恢复探测")
                self._task_log(
                    f"{code} {'新浪' if provider == 'sina' else '东财'}"
                    + ("恢复探测" if probe else f"请求 {attempt + 1}/2")
                    + "：等待串行限流并取源"
                )
                self._wait_source_interval()
                frame = source.get_intraday_1m(code, provider)
                if provider == "eastmoney":
                    # 有效空响应说明接口已连通，但不能作为停牌或完整覆盖证据。
                    self.redis.set(self._eastmoney_state_key(), '{"failures":0}', ex=86_400)
                    self._reported_cooldown_until = None
                    if probe:
                        self._task_log(f"{code} 东财恢复探测成功，恢复备用源采集")
                return frame
            except (redis.RedisError, IntradayServiceUnavailable):
                raise
            except Exception as exc:
                if self.ctx:
                    self.ctx.check_cancel()
                last_error = exc
                if provider == "eastmoney" and (attempt == 1 or probe):
                    self._record_eastmoney_failure(state)
                if probe:
                    # 半开仅允许一个真实请求；失败后立即重新熔断，不追加退避请求。
                    raise
                if attempt == 0:
                    self._task_log(f"{code} 本次请求失败：{type(exc).__name__}，退避后重试", "warn")
            finally:
                self._release_lock(self._global_lock_key(), token)
            if attempt == 0:
                self._pause(min(1.0, self.config.source_min_interval_sec))
        assert last_error is not None
        raise last_error

    def _eastmoney_state(self) -> tuple[dict, float]:
        """调用方持有全局源锁；以 Redis 时钟共享失败计数及半开探测资格。"""
        raw = self.redis.get(self._eastmoney_state_key())
        state = json.loads(raw) if raw else {}
        seconds, micros = self.redis.time()
        return state, float(seconds) + float(micros) / 1_000_000

    def _record_eastmoney_failure(self, state: dict) -> None:
        # 到达阈值后饱和计数，长时间故障不会累积无意义的大整数。
        failures = min(_EASTMONEY_FAILURE_LIMIT, state.get("failures", 0) + 1)
        updated = {"failures": failures}
        if failures >= _EASTMONEY_FAILURE_LIMIT:
            seconds, micros = self.redis.time()
            updated["open_until"] = (
                float(seconds) + float(micros) / 1_000_000 + self.config.negative_ttl_sec
            )
        self.redis.set(self._eastmoney_state_key(), json.dumps(updated), ex=86_400)
        if "open_until" in updated:
            self._task_log(
                f"东财连续 {failures} 次取源失败，暂时熔断 {self.config.negative_ttl_sec} 秒；"
                "到期单次探测，期间保留新浪候选和未完整日期",
                "warn",
            )
            self._reported_cooldown_until = updated["open_until"]

    @staticmethod
    def _eastmoney_state_key() -> str:
        return f"{_SOURCE_PREFIX}:source:eastmoney:circuit"

    def _acquire_global_source_lock(self) -> str:
        token = uuid.uuid4().hex
        deadline = self.monotonic() + self.config.lock_wait_sec
        ttl = max(
            30,
            math.ceil(
                self.config.request_timeout_sec * 2 + self.config.source_min_interval_sec + 10
            ),
        )
        while self.monotonic() < deadline:
            if self.redis.set(self._global_lock_key(), token, nx=True, ex=ttl):
                return token
            self._pause(0.1)
        raise IntradayServiceUnavailable("分钟行情源正在繁忙，请稍后重试")

    def _wait_source_interval(self) -> None:
        seconds, micros = self.redis.time()
        now = float(seconds) + float(micros) / 1_000_000
        last_raw = self.redis.get(self._last_start_key())
        last = float(last_raw) if last_raw else 0.0
        wait = self.config.source_min_interval_sec - (now - last)
        if wait > 0:
            self._pause(wait)
            seconds, micros = self.redis.time()
            now = float(seconds) + float(micros) / 1_000_000
        self.redis.set(self._last_start_key(), f"{now:.6f}", ex=86_400)

    @staticmethod
    def _frame_to_window(frame: pd.DataFrame, provider: str) -> dict:
        day_diagnostics = {}
        if frame is not None and not frame.empty:
            for day, group in frame.groupby(
                pd.to_datetime(frame.timestamp, errors="coerce").dt.strftime("%Y-%m-%d")
            ):
                _, day_diagnostics[day] = sanitize_minutes(group)
        frame, diagnostics = sanitize_minutes(frame)
        rows: list[list] = []
        if frame is not None and not frame.empty:
            for row in frame.itertuples(index=False):
                rows.append(
                    [
                        pd.Timestamp(row.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                        None if pd.isna(row.open) else float(row.open),
                        float(row.high),
                        float(row.low),
                        float(row.close),
                        float(row.volume),
                        float(row.amount),
                    ]
                )
        return {
            "diagnostics": diagnostics,
            "day_diagnostics": day_diagnostics,
            "source": provider,
            "fetched_at": datetime.now(UTC).isoformat(),
            "rows": rows,
        }

    @staticmethod
    def _targets_complete(windows: dict, dates=None) -> bool:
        if not dates:
            return any(w.get("rows") for w in windows.values())
        return all(
            any(
                candidate_rank([r for r in w["rows"] if r[0][:10] == day], p)[0]
                for p, w in windows.items()
            )
            for day in dates
        )

    @staticmethod
    def _with_candidates(window: dict, windows: dict) -> dict:
        return {**window, "candidates": list(windows.values())}

    @staticmethod
    def _pick_window(windows: dict[str, dict], dates=None) -> dict | None:
        candidates = list(windows.values())
        if dates:
            candidates = [
                {**w, "rows": [r for r in w["rows"] if r[0][:10] in dates]} for w in candidates
            ]
        candidates = [w for w in candidates if w.get("rows")]
        return max(candidates, key=lambda w: candidate_rank(w["rows"], w["source"]), default=None)

    @staticmethod
    def _empty_window(windows: dict[str, dict]) -> dict:
        newest = max(
            windows.values(), key=lambda item: str(item.get("fetched_at") or ""), default={}
        )
        return {
            "source": newest.get("source"),
            "fetched_at": newest.get("fetched_at"),
            "rows": [],
        }

    def _release_lock(self, key: str, token: str) -> None:
        self.redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)

    @staticmethod
    def _negative_key(code: str) -> str:
        return f"{_SOURCE_PREFIX}:negative:{code}"

    @staticmethod
    def _global_lock_key() -> str:
        return f"{_SOURCE_PREFIX}:lock:source"

    @staticmethod
    def _last_start_key() -> str:
        return f"{_SOURCE_PREFIX}:source:last-start"
