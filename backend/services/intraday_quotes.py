"""个股近期 1 分钟分时：本地范围门禁、Redis 窗口缓存和跨进程源站单飞。"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime

import pandas as pd
import redis

from backend.common.logging import get_logger
from backend.config import get_settings
from backend.datasource.akshare_source import AKShareSource
from backend.storage import get_read_client, get_redis_client

log = get_logger("services.intraday_quotes")

_CACHE_PREFIX = "market:intraday:1m"
_CACHE_VERSION = 2
_MAX_CACHE_BYTES = 2 * 1024 * 1024
_EXPECTED_SESSION_TIMES = frozenset(
    pd.date_range("2000-01-01 09:31", periods=120, freq="min").strftime("%H:%M")
) | frozenset(
    pd.date_range("2000-01-01 13:01", periods=120, freq="min").strftime("%H:%M")
)
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class IntradayServiceUnavailable(RuntimeError):
    """Redis 或免费行情源暂时不可用。"""


class IntradayQuoteService:
    def __init__(
        self,
        market=None,
        redis_client=None,
        source_factory: Callable[[], AKShareSource] = AKShareSource,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.market = market or get_read_client()
        self.redis = redis_client or get_redis_client().client
        self.source_factory = source_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.config = get_settings().intraday

    def get(self, code: str, trade_date: date) -> dict:
        metadata = self._local_metadata(code, trade_date)
        if metadata["status"] != "ready":
            return self._response(metadata)
        if not self.config.enabled:
            raise IntradayServiceUnavailable("分时行情功能当前未启用")

        try:
            window = self._load_or_fetch_window(code)
        except (redis.RedisError, OSError) as exc:
            log.warning("分时 Redis 不可用 code=%s error=%s", code, type(exc).__name__)
            raise IntradayServiceUnavailable("分时缓存服务暂时不可用，请稍后重试") from exc

        selected = [row for row in window["rows"] if row[0][:10] == str(trade_date)]
        if not selected:
            metadata["status"] = "no_data"
            metadata["source"] = window.get("source")
            metadata["fetched_at"] = window.get("fetched_at")
            return self._response(metadata)

        points = self._points(selected)
        metadata.update(
            status="ready" if self._is_complete(points) else "partial",
            source=window.get("source"),
            fetched_at=window.get("fetched_at"),
            points=points,
        )
        return self._response(metadata)

    def _local_metadata(self, code: str, trade_date: date) -> dict:
        name_df = self.market.query_df("SELECT name FROM stock_basic WHERE code = ?", [code])
        name = None if name_df.empty else str(name_df.iloc[0]["name"])
        dates_df = self.market.query_df(
            "SELECT DISTINCT trade_date FROM daily_bar ORDER BY trade_date DESC LIMIT ?",
            [int(self.config.supported_trade_days)],
        )
        dates = sorted(pd.Timestamp(value).date() for value in dates_df.get("trade_date", []))
        metadata = {
            "code": code,
            "name": name,
            "trade_date": str(trade_date),
            "frequency": "1m",
            "status": "ready",
            "source": None,
            "fetched_at": None,
            "supported_start": str(dates[0]) if dates else None,
            "supported_end": str(dates[-1]) if dates else None,
            "pre_close": None,
            "turnover_rate": None,
            "points": [],
        }
        if name is None:
            metadata["status"] = "no_data"
            return metadata
        if trade_date not in dates:
            metadata["status"] = "out_of_range"
            return metadata
        bar_df = self.market.query_df(
            "SELECT pre_close, turnover_rate FROM daily_bar "
            "WHERE code = ? AND trade_date = ? LIMIT 1",
            [code, trade_date],
        )
        if bar_df.empty:
            metadata["status"] = "no_data"
            return metadata
        value = bar_df.iloc[0]["pre_close"]
        metadata["pre_close"] = None if value is None or pd.isna(value) else float(value)
        turnover = bar_df.iloc[0]["turnover_rate"]
        metadata["turnover_rate"] = (
            None if turnover is None or pd.isna(turnover) else float(turnover)
        )
        return metadata

    def _load_or_fetch_window(self, code: str) -> dict:
        cached = self._read_provider_caches(code)
        ready = self._pick_window(cached)
        if ready is not None or len(cached) == 2:
            log.info("分时缓存命中 code=%s source=%s", code, ready and ready.get("source"))
            return ready or self._empty_window(cached)
        negative = self.redis.get(self._negative_key(code))
        if negative:
            raise IntradayServiceUnavailable("免费分时源暂时不可用，请稍后重试")

        log.info("分时缓存未命中 code=%s", code)
        token = uuid.uuid4().hex
        lock_key = self._stock_lock_key(code)
        # 最坏路径会串行等待并请求两个源、每源两次；锁必须覆盖全链路，
        # 否则在全局源锁拥堵时可能过期，使同股第二个请求重复抓源。
        per_attempt = (
            self.config.lock_wait_sec
            + self.config.request_timeout_sec
            + self.config.source_min_interval_sec
            + 1
        )
        lock_ttl = max(60, math.ceil(per_attempt * 4 + 30))
        if not self.redis.set(lock_key, token, nx=True, ex=lock_ttl):
            return self._wait_for_stock(code)

        try:
            cached = self._read_provider_caches(code)
            ready = self._pick_window(cached)
            if ready is not None or len(cached) == 2:
                return ready or self._empty_window(cached)
            return self._fetch_missing(code, cached)
        finally:
            self._release_lock(lock_key, token)

    def _fetch_missing(self, code: str, cached: dict[str, dict]) -> dict:
        source = self.source_factory()
        errors: list[str] = []
        for provider in ("sina", "eastmoney"):
            if provider in cached:
                continue
            started = self.monotonic()
            try:
                frame = self._fetch_provider(source, code, provider)
                window = self._frame_to_window(frame, provider)
                self._write_cache(code, provider, window)
                cached[provider] = window
                log.info(
                    "分时源请求成功 code=%s source=%s rows=%d elapsed_ms=%d",
                    code,
                    provider,
                    len(window["rows"]),
                    round((self.monotonic() - started) * 1000),
                )
                if window["rows"]:
                    return window
            except (redis.RedisError, IntradayServiceUnavailable):
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider}:{type(exc).__name__}")
                log.warning(
                    "分时源请求失败 code=%s source=%s elapsed_ms=%d reason=%s",
                    code,
                    provider,
                    round((self.monotonic() - started) * 1000),
                    type(exc).__name__,
                )
        ready = self._pick_window(cached)
        if ready is not None:
            return ready
        if errors:
            self.redis.set(
                self._negative_key(code), ",".join(errors), ex=self.config.negative_ttl_sec
            )
            raise IntradayServiceUnavailable("免费分时源暂时不可用，请稍后重试")
        return self._empty_window(cached)

    def _fetch_provider(self, source: AKShareSource, code: str, provider: str) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(2):
            token = self._acquire_global_source_lock()
            try:
                self._wait_source_interval()
                return source.get_intraday_1m(code, provider)
            except redis.RedisError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            finally:
                self._release_lock(self._global_lock_key(), token)
            if attempt == 0:
                self.sleep(min(1.0, self.config.source_min_interval_sec))
        assert last_error is not None
        raise last_error

    def _acquire_global_source_lock(self) -> str:
        token = uuid.uuid4().hex
        deadline = self.monotonic() + self.config.lock_wait_sec
        ttl = max(30, math.ceil(self.config.request_timeout_sec * 2 + 10))
        while self.monotonic() < deadline:
            if self.redis.set(self._global_lock_key(), token, nx=True, ex=ttl):
                return token
            self.sleep(0.1)
        raise IntradayServiceUnavailable("分钟行情源正在繁忙，请稍后重试")

    def _wait_source_interval(self) -> None:
        seconds, micros = self.redis.time()
        now = float(seconds) + float(micros) / 1_000_000
        last_raw = self.redis.get(self._last_start_key())
        last = float(last_raw) if last_raw else 0.0
        wait = self.config.source_min_interval_sec - (now - last)
        if wait > 0:
            self.sleep(wait)
            seconds, micros = self.redis.time()
            now = float(seconds) + float(micros) / 1_000_000
        self.redis.set(self._last_start_key(), f"{now:.6f}", ex=86_400)

    def _wait_for_stock(self, code: str) -> dict:
        log.info("分时缓存锁等待 code=%s", code)
        deadline = self.monotonic() + self.config.lock_wait_sec
        while self.monotonic() < deadline:
            cached = self._read_provider_caches(code)
            ready = self._pick_window(cached)
            if ready is not None or len(cached) == 2:
                return ready or self._empty_window(cached)
            if self.redis.get(self._negative_key(code)):
                raise IntradayServiceUnavailable("免费分时源暂时不可用，请稍后重试")
            self.sleep(0.1)
        raise IntradayServiceUnavailable("分钟行情加载超时，请稍后重试")

    def _read_provider_caches(self, code: str) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for provider in ("sina", "eastmoney"):
            raw = self.redis.get(self._cache_key(provider, code))
            if not raw:
                continue
            try:
                payload = json.loads(raw)
                if payload.get("v") == _CACHE_VERSION and isinstance(payload.get("rows"), list):
                    result[provider] = payload
            except (TypeError, ValueError):
                log.warning("忽略损坏的分时缓存 code=%s source=%s", code, provider)
        return result

    def _write_cache(self, code: str, provider: str, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw.encode("utf-8")) > _MAX_CACHE_BYTES:
            raise ValueError("分钟行情缓存载荷超过安全上限")
        ttl = self.config.cache_ttl_sec if payload["rows"] else self.config.negative_ttl_sec
        self.redis.set(self._cache_key(provider, code), raw, ex=ttl)

    @staticmethod
    def _frame_to_window(frame: pd.DataFrame, provider: str) -> dict:
        rows: list[list] = []
        if frame is not None and not frame.empty:
            for row in frame.itertuples(index=False):
                rows.append(
                    [
                        pd.Timestamp(row.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                        float(row.open),
                        float(row.high),
                        float(row.low),
                        float(row.close),
                        float(row.volume),
                        float(row.amount),
                    ]
                )
        return {
            "v": _CACHE_VERSION,
            "source": provider,
            "fetched_at": datetime.now(UTC).isoformat(),
            "rows": rows,
        }

    @staticmethod
    def _pick_window(cached: dict[str, dict]) -> dict | None:
        for provider in ("sina", "eastmoney"):
            window = cached.get(provider)
            if window and window.get("rows"):
                return window
        return None

    @staticmethod
    def _empty_window(cached: dict[str, dict]) -> dict:
        newest = max(
            cached.values(), key=lambda item: str(item.get("fetched_at") or ""), default={}
        )
        return {
            "v": _CACHE_VERSION,
            "source": newest.get("source"),
            "fetched_at": newest.get("fetched_at"),
            "rows": [],
        }

    @staticmethod
    def _points(rows: list[list]) -> list[dict]:
        amount_sum = 0.0
        volume_sum = 0.0
        points: list[dict] = []
        for timestamp, open_, high, low, close, volume, amount in rows:
            volume_lots = float(volume)
            amount_value = float(amount)
            volume_sum += max(volume_lots, 0.0)
            amount_sum += max(amount_value, 0.0)
            average = amount_sum / (volume_sum * 100) if volume_sum > 0 else None
            points.append(
                {
                    "time": timestamp[11:16],
                    "open": round(float(open_), 4),
                    "high": round(float(high), 4),
                    "low": round(float(low), 4),
                    "close": round(float(close), 4),
                    "volume": round(volume_lots, 2),
                    "amount": round(amount_value, 2),
                    "average_price": None if average is None else round(average, 4),
                }
            )
        return points

    @staticmethod
    def _is_complete(points: list[dict]) -> bool:
        return _EXPECTED_SESSION_TIMES.issubset({point["time"] for point in points})

    @staticmethod
    def _response(metadata: dict) -> dict:
        return metadata

    def _release_lock(self, key: str, token: str) -> None:
        self.redis.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)

    @staticmethod
    def _cache_key(provider: str, code: str) -> str:
        return f"{_CACHE_PREFIX}:window:{provider}:{code}"

    @staticmethod
    def _negative_key(code: str) -> str:
        return f"{_CACHE_PREFIX}:negative:{code}"

    @staticmethod
    def _stock_lock_key(code: str) -> str:
        return f"{_CACHE_PREFIX}:lock:stock:{code}"

    @staticmethod
    def _global_lock_key() -> str:
        return f"{_CACHE_PREFIX}:lock:source"

    @staticmethod
    def _last_start_key() -> str:
        return f"{_CACHE_PREFIX}:source:last-start"
