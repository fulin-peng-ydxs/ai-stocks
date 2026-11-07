"""数据管理专用分时取源：共享限流和有限重试，不缓存未入库行情。"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd
import redis

from backend.common.logging import get_logger
from backend.config.request_snapshot import get_request_settings as get_effective_settings
from backend.datasource import request_policy as source_requests
from backend.datasource.akshare_source import AKShareSource
from backend.datasource.base import thread_cancel_scope
from backend.services.intraday_contract import (
    INTRADAY_PROVIDERS,
    PROVIDER_LABELS,
    candidate_rank,
    rows_for_day,
    sanitize_minutes,
)
from backend.services.intraday_evidence import SOURCE_REQUEST_LIMIT, window_evidence
from backend.services.intraday_quotes import IntradayServiceUnavailable
from backend.services.intraday_subjects import providers_for
from backend.storage import get_redis_client

log = get_logger("services.intraday_source")


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
        self._reported_request_policy = None
        self.last_observations = {}
        self.last_windows = {}

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

    def fetch_window(
        self, code: str, dates: list[str], *, allow_fallback: bool = False, providers=None
    ) -> dict:
        """常规采集按标的主源取数；质检修复按目标日完整性尝试备用源。"""
        self.last_observations = {}
        self.last_windows = {}
        if self.ctx:
            self.ctx.check_cancel()
        target_range = f"{min(dates)}～{max(dates)}（{len(dates)} 日）" if dates else "未指定"
        windows: dict[str, dict] = self.last_windows
        source = self.source_factory()
        errors: list[str] = []
        allowed = providers_for(code, allow_fallback)
        providers = providers or allowed
        if any(p not in allowed for p in providers):
            raise ValueError("常规采集仅允许标的主源，备用源仅供质检修复")
        for provider_index, provider in enumerate(providers):
            started = self.monotonic()
            try:
                if provider == "ths":
                    frame, year_errors = self._fetch_ths_years(source, code, dates)
                    errors.extend(year_errors)
                else:
                    frame = self._fetch_provider(source, code, provider)
                    year_errors = []
                window = frame if isinstance(frame, dict) else self._frame_to_window(frame, provider)
                window["code"] = code
                windows[provider] = window
                self.last_observations[provider] = {
                    "outcome": "error" if year_errors else "ok" if window["rows"] else "empty",
                    "evidence": window_evidence(window),
                    "error": "；".join(year_errors),
                }
                if self.ctx is not None:
                    complete = sum(
                        candidate_rank(rows_for_day(window, day), provider, code)[0]
                        for day in dates
                    )
                    self._task_log(
                        f"{code} {PROVIDER_LABELS[provider]}返回 {len(window['rows'])} 个有效分钟点，"
                        f"实际范围 {window['raw_first'] or '无'}～{window['raw_last'] or '无'}；"
                        f"目标日完整 {complete}/{len(dates)} 日"
                    )
                log.info(
                    "分时源请求成功 code=%s source=%s rows=%d elapsed_ms=%d",
                    code,
                    provider,
                    len(window["rows"]),
                    round((self.monotonic() - started) * 1000),
                )
                if self._targets_complete(windows, dates, code):
                    for skipped in providers[provider_index + 1:]:
                        self._task_log(f"{code} {PROVIDER_LABELS[skipped]}：跳过；"
                                       "前序来源的整日候选已覆盖全部目标日")
                    return {**self._with_candidates(self._pick_window(windows, dates), windows),
                            "errors": errors}
            except (redis.RedisError, IntradayServiceUnavailable):
                raise
            except Exception as exc:  # noqa: BLE001
                if self.ctx:
                    self.ctx.check_cancel()
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                errors.append(f"{provider}:{error}")
                self.last_observations[provider] = {
                    "outcome": "error", "error": error,
                }
                self._task_log(
                    f"{code} {PROVIDER_LABELS[provider]}取源失败，目标日期 {target_range}："
                    f"{error}；"
                    + (
                        "继续下一个备用源" if provider_index + 1 < len(providers)
                        else "保留已取得的数据，未完整日期交由质检修复"
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
            # 显式采集/修复每次按系统请求策略执行，不因此前失败抑制后续任务。
            raise IntradayServiceUnavailable("分时取源失败：" + "；".join(errors))
        return self._with_candidates(self._empty_window(windows), windows)

    def _fetch_ths_years(self, source, code, dates):
        """年度未补齐时追加近期窗口；逐日选整日候选，不拼接两窗口的分钟。"""
        errors, years = [], []
        for year in [*sorted({int(day[:4]) for day in dates}), "last10000"]:
            if year == "last10000":
                if self._targets_complete(self.last_windows, dates, code):
                    break
                self._task_log(f"{code} 同花顺年度窗口未补齐目标日，追加近期分钟窗口")
            try:
                frame = self._fetch_provider(source, code, "ths", request_year=year)
                # 每个响应只转换一次，取消或后续窗口失败也保留前序有效候选。
                part = self._frame_to_window(frame, "ths")
                if year != "last10000":
                    years.append(year)
                previous = self.last_windows.get("ths")
                if previous is not None:
                    # 近期首日可能截断；同日选择覆盖更好的完整候选，避免覆盖倒退。
                    groups = {}
                    for window in (previous, part):
                        # 全部被拒用的日期也保留诊断，不能合并时静默消失。
                        by_day = {day: [] for day in window["day_diagnostics"]}
                        for row in window["rows"]:
                            by_day.setdefault(row[0][:10], []).append(row)
                        for day, rows in by_day.items():
                            old = groups.get(day)
                            if old is None or candidate_rank(rows, "ths", code) > candidate_rank(
                                old[0], "ths", code
                            ):
                                groups[day] = (rows, window["day_diagnostics"].get(day, {}))
                    part["rows"] = [row for day in sorted(groups) for row in groups[day][0]]
                    part["day_diagnostics"] = {day: value[1] for day, value in groups.items()}
                    part["raw_count"] += previous["raw_count"]
                    for key, choose in (("raw_first", min), ("raw_last", max)):
                        values = [v for v in (previous.get(key), part.get(key)) if v]
                        part[key] = choose(values) if values else None
                    part["diagnostics"] = {
                        key: previous["diagnostics"].get(key, 0) + part["diagnostics"].get(key, 0)
                        for key in set(previous["diagnostics"]) | set(part["diagnostics"])
                    }
                self.last_windows["ths"] = {**part, "code": code, "request_years": years.copy()}
            except (redis.RedisError, IntradayServiceUnavailable):
                raise
            except Exception as exc:  # noqa: BLE001 -- 按年份保留候选与失败，取消必须穿透
                if self.ctx:
                    self.ctx.check_cancel()
                reason = f"ths/{year}:{type(exc).__name__}: {str(exc)[:200]}"
                errors.append(reason)
                self._task_log(f"{code} 同花顺 {year} 窗口请求失败：{reason}；保留其他窗口候选", "warn")
        if "ths" not in self.last_windows:
            raise ValueError("同花顺年度及近期窗口均请求失败：" + "；".join(errors))
        return self.last_windows["ths"], errors

    @source_requests.request_budgeted
    def _fetch_provider(
        self, source: AKShareSource, code: str, provider: str, *, request_year=None
    ) -> pd.DataFrame:
        if provider not in INTRADAY_PROVIDERS:
            raise ValueError(f"不支持的分时数据源: {provider}")
        # 每次取源重新合并系统覆盖层，长任务下一只股票/备用源即可使用页面新配置。
        policy = source_requests.request_policy(provider, get_effective_settings())
        attempts = policy.attempts  # 一次取源固定总尝试预算；下一次取源读取新配置。
        signature = (policy.rate, policy.timeout, attempts, policy.backoff)
        if signature != self._reported_request_policy:
            self._task_log(
                f"系统请求配置：限流 {policy.rate:g} 次/秒，"
                f"超时 {policy.timeout:g} 秒，最多尝试 {attempts} 次，"
                f"指数退避起始 {policy.backoff:g} 秒；按实际来源共享限流"
            )
            self._reported_request_policy = signature
        last_error: Exception | None = None
        for attempt in range(attempts):
            policy = source_requests.request_policy(provider, get_effective_settings())
            if self.ctx:
                self.ctx.check_cancel()
            self._task_log(f"{code} {PROVIDER_LABELS[provider]}：等待来源限流")
            try:
                self._task_log(f"{code} {PROVIDER_LABELS[provider]}请求 {attempt + 1}/{attempts}")
                kwargs = {"request_year": request_year} if provider == "ths" else {}
                with thread_cancel_scope(self.ctx.check_cancel if self.ctx else None), source_requests.http_policy_scope(provider, policy, client=self.redis):
                    frame = source.get_intraday_1m(
                        code, provider, timeout_sec=policy.timeout, **kwargs
                    )
                return frame
            except (redis.RedisError, IntradayServiceUnavailable):
                raise
            except Exception as exc:  # 来源故障有限重试并保留具体错误
                if self.ctx:
                    self.ctx.check_cancel()
                if getattr(exc, "request_attempts_exhausted", False):
                    raise
                last_error = exc
                if attempt < attempts - 1:
                    self._task_log(
                        f"{code} {PROVIDER_LABELS[provider]}请求 {attempt + 1}/{attempts} 失败："
                        f"{type(exc).__name__}: {str(exc)[:300]}；退避后重试", "warn",
                    )
            if attempt < attempts - 1:
                from backend.datasource.observability import record
                record(semantic_retries=1)
                self._pause(policy.backoff * 2 ** attempt)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _frame_to_window(frame: pd.DataFrame, provider: str) -> dict:
        day_diagnostics = {}
        raw_count = len(frame) if frame is not None else 0
        timestamps = (pd.to_datetime(frame.timestamp, errors="coerce").dropna()
                      if raw_count else pd.Series(dtype="datetime64[ns]"))
        raw_first = timestamps.min().strftime("%Y-%m-%d %H:%M:%S") if len(timestamps) else None
        raw_last = timestamps.max().strftime("%Y-%m-%d %H:%M:%S") if len(timestamps) else None
        frame, diagnostics = sanitize_minutes(frame, day_diagnostics=day_diagnostics)
        rows: list[list] = []
        if frame is not None and not frame.empty:
            # 年度响应可含数万点；沿用清洗结果逐列转换，避免逐分钟构造Timestamp。
            # 所有数值仍为float，开盘占位仍为None，行序与逐日诊断保持一致。
            values = frame[["open", "high", "low", "close", "volume", "amount"]]
            values = values.astype(float).astype(object).where(values.notna(), None)
            values.insert(0, "timestamp", frame.timestamp.dt.strftime("%Y-%m-%d %H:%M:%S"))
            rows = values.to_numpy().tolist()
        return {
            "request_years": frame.attrs.get("request_years", []) if frame is not None else [],
            "raw_count": raw_count, "raw_first": raw_first, "raw_last": raw_last,
            "request_limit": SOURCE_REQUEST_LIMIT if provider == "sina" else None,
            "diagnostics": diagnostics,
            "day_diagnostics": day_diagnostics,
            "source": provider,
            "fetched_at": datetime.now(UTC).isoformat(),
            "rows": rows,
        }

    @staticmethod
    def _targets_complete(windows: dict, dates=None, code=None) -> bool:
        if not dates:
            return any(w.get("rows") for w in windows.values())
        return all(
            any(
                candidate_rank(rows_for_day(w, day), p, code)[0]
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
        return max(candidates, key=lambda w: candidate_rank(w["rows"], w["source"], w.get("code")), default=None)

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
