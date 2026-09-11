from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
import redis

from backend.services.intraday_quotes import IntradayQuoteService, IntradayServiceUnavailable


class _Market:
    def __init__(self, *, has_stock: bool = True, has_bar: bool = True) -> None:
        self.has_stock = has_stock
        self.has_bar = has_bar
        self.latest = date(2026, 9, 10)

    def query_df(self, sql: str, params=None) -> pd.DataFrame:
        if "FROM stock_basic" in sql:
            return pd.DataFrame({"name": ["步步高"]}) if self.has_stock else pd.DataFrame()
        if "SELECT DISTINCT trade_date" in sql:
            return pd.DataFrame(
                {"trade_date": [self.latest - timedelta(days=index) for index in range(8)]}
            )
        if "SELECT pre_close" in sql:
            return (
                pd.DataFrame({"pre_close": [3.55], "turnover_rate": [6.8]})
                if self.has_bar else pd.DataFrame()
            )
        raise AssertionError(sql)


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires: dict[str, float] = {}
        self.lock = threading.Lock()
        self.fail = False
        self.set_ttls: dict[str, float] = {}

    def _purge(self, key: str) -> None:
        expires = self.expires.get(key)
        if expires is not None and expires <= time.time():
            self.values.pop(key, None)
            self.expires.pop(key, None)

    def get(self, key: str):
        if self.fail:
            raise redis.ConnectionError("down")
        with self.lock:
            self._purge(key)
            return self.values.get(key)

    def set(self, key: str, value, nx: bool = False, ex=None):
        if self.fail:
            raise redis.ConnectionError("down")
        with self.lock:
            self._purge(key)
            if nx and key in self.values:
                return False
            self.values[key] = str(value)
            if ex is not None:
                self.expires[key] = time.time() + float(ex)
                self.set_ttls[key] = float(ex)
            return True

    def eval(self, _script: str, _keys: int, key: str, token: str):
        if self.fail:
            raise redis.ConnectionError("down")
        with self.lock:
            if self.values.get(key) != token:
                return 0
            self.values.pop(key, None)
            self.expires.pop(key, None)
            return 1

    @staticmethod
    def time():
        now = time.time()
        return int(now), int((now % 1) * 1_000_000)


def _frame(trade_date: date = date(2026, 9, 10), rows: int = 240) -> pd.DataFrame:
    morning = pd.date_range(f"{trade_date} 09:31", periods=min(rows, 120), freq="min")
    afternoon_count = max(0, rows - len(morning))
    afternoon = pd.date_range(f"{trade_date} 13:01", periods=afternoon_count, freq="min")
    timestamps = morning.append(afternoon)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [3.60 + index * 0.001 for index in range(rows)],
            "high": [3.62 + index * 0.001 for index in range(rows)],
            "low": [3.59 + index * 0.001 for index in range(rows)],
            "close": [3.61 + index * 0.001 for index in range(rows)],
            "volume": [10] * rows,
            "amount": [(3.60 + index * 0.001) * 1000 for index in range(rows)],
        }
    )


class _Source:
    def __init__(
        self, calls: list[str], frame: pd.DataFrame | None = None, delay: float = 0
    ) -> None:
        self.calls = calls
        self.frame = _frame() if frame is None else frame
        self.delay = delay

    def get_intraday_1m(self, _code: str, provider: str) -> pd.DataFrame:
        self.calls.append(provider)
        if self.delay:
            time.sleep(self.delay)
        return self.frame.copy()


def _service(redis_client=None, source_factory=None, market=None) -> IntradayQuoteService:
    service = IntradayQuoteService(
        market=market or _Market(),
        redis_client=redis_client or _Redis(),
        source_factory=source_factory or (lambda: _Source([])),
    )
    service.config = SimpleNamespace(
        enabled=True,
        supported_trade_days=8,
        cache_ttl_sec=43_200,
        negative_ttl_sec=60,
        source_min_interval_sec=0.01,
        request_timeout_sec=0.2,
        lock_wait_sec=1.0,
    )
    return service


def test_out_of_range_and_missing_daily_bar_never_call_source() -> None:
    calls: list[str] = []
    service = _service(source_factory=lambda: _Source(calls))

    old = service.get("002251.SZ", date(2026, 8, 1))
    assert old["status"] == "out_of_range"
    assert old["supported_end"] == "2026-09-10"

    missing = _service(market=_Market(has_bar=False), source_factory=lambda: _Source(calls)).get(
        "002251.SZ", date(2026, 9, 10)
    )
    assert missing["status"] == "no_data"
    assert calls == []


def test_first_fetch_maps_points_and_followup_date_uses_same_window_cache() -> None:
    calls: list[str] = []
    cache = _Redis()
    frames = pd.concat([_frame(date(2026, 9, 9)), _frame(date(2026, 9, 10))], ignore_index=True)
    service = _service(cache, lambda: _Source(calls, frames))

    current = service.get("002251.SZ", date(2026, 9, 10))
    previous = service.get("002251.SZ", date(2026, 9, 9))

    assert current["status"] == "ready"
    assert current["source"] == "sina"
    assert current["pre_close"] == 3.55
    assert current["turnover_rate"] == 6.8
    assert current["points"][0]["volume"] == 10
    assert current["points"][1]["average_price"] == pytest.approx(3.6005)
    assert previous["status"] == "ready"
    assert calls == ["sina"]
    raw = cache.get("market:intraday:1m:window:sina:002251.SZ")
    assert raw is not None and json.loads(raw)["v"] == 2
    assert "average_price" not in raw


def test_legacy_share_unit_cache_is_ignored_and_replaced_with_lot_unit_cache() -> None:
    calls: list[str] = []
    cache = _Redis()
    key = "market:intraday:1m:window:sina:002251.SZ"
    cache.set(
        key,
        json.dumps({"v": 1, "source": "sina", "fetched_at": "2026-09-10T00:00:00Z", "rows": []}),
        ex=43_200,
    )
    service = _service(cache, lambda: _Source(calls))

    result = service.get("002251.SZ", date(2026, 9, 10))

    assert result["status"] == "ready"
    assert result["points"][0]["volume"] == 10
    assert calls == ["sina"]
    assert json.loads(cache.get(key))["v"] == 2


def test_partial_points_are_preserved_without_fill() -> None:
    calls: list[str] = []
    service = _service(source_factory=lambda: _Source(calls, _frame(rows=3)))
    result = service.get("002251.SZ", date(2026, 9, 10))

    assert result["status"] == "partial"
    assert len(result["points"]) == 3
    assert [point["time"] for point in result["points"]] == ["09:31", "09:32", "09:33"]


def test_missing_single_interior_minute_is_partial() -> None:
    calls: list[str] = []
    frame = _frame().drop(index=80).reset_index(drop=True)
    service = _service(source_factory=lambda: _Source(calls, frame))

    result = service.get("002251.SZ", date(2026, 9, 10))

    assert result["status"] == "partial"
    assert len(result["points"]) == 239


def test_same_stock_concurrency_only_fetches_once() -> None:
    calls: list[str] = []
    cache = _Redis()
    service = _service(cache, lambda: _Source(calls, delay=0.05))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.get("002251.SZ", date(2026, 9, 10)), range(4)))

    assert all(result["status"] == "ready" for result in results)
    assert calls == ["sina"]


def test_stock_lock_ttl_covers_bounded_two_source_retry_path() -> None:
    cache = _Redis()
    service = _service(cache, lambda: _Source([]))
    service.config.lock_wait_sec = 20
    service.config.request_timeout_sec = 15
    service.config.source_min_interval_sec = 2

    service.get("002251.SZ", date(2026, 9, 10))

    assert cache.set_ttls["market:intraday:1m:lock:stock:002251.SZ"] >= 182


def test_redis_failure_is_closed_before_source_access() -> None:
    calls: list[str] = []
    cache = _Redis()
    cache.fail = True
    service = _service(cache, lambda: _Source(calls))

    with pytest.raises(IntradayServiceUnavailable, match="缓存服务"):
        service.get("002251.SZ", date(2026, 9, 10))
    assert calls == []


def test_failed_sources_are_negative_cached() -> None:
    calls: list[str] = []

    class FailingSource:
        def get_intraday_1m(self, _code: str, provider: str) -> pd.DataFrame:
            calls.append(provider)
            raise TimeoutError(provider)

    cache = _Redis()
    service = _service(cache, FailingSource)
    with pytest.raises(IntradayServiceUnavailable):
        service.get("002251.SZ", date(2026, 9, 10))
    first_count = len(calls)
    with pytest.raises(IntradayServiceUnavailable):
        service.get("002251.SZ", date(2026, 9, 10))

    assert calls == ["sina", "sina", "eastmoney", "eastmoney"]
    assert len(calls) == first_count


def test_clean_empty_responses_use_short_cache_and_return_no_data() -> None:
    calls: list[str] = []
    cache = _Redis()
    service = _service(cache, lambda: _Source(calls, pd.DataFrame()))

    result = service.get("002251.SZ", date(2026, 9, 10))

    assert result["status"] == "no_data"
    assert calls == ["sina", "eastmoney"]
    assert cache.set_ttls["market:intraday:1m:window:sina:002251.SZ"] == 60
    assert cache.set_ttls["market:intraday:1m:window:eastmoney:002251.SZ"] == 60


def test_different_stocks_share_global_concurrency_gate() -> None:
    cache = _Redis()
    active = 0
    maximum = 0
    starts: list[float] = []
    tracker = threading.Lock()

    class TrackingSource:
        def get_intraday_1m(self, _code: str, _provider: str) -> pd.DataFrame:
            nonlocal active, maximum
            with tracker:
                active += 1
                maximum = max(maximum, active)
                starts.append(time.monotonic())
            time.sleep(0.03)
            with tracker:
                active -= 1
            return _frame()

    service = _service(cache, TrackingSource)
    service.config.source_min_interval_sec = 0.02
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda code: service.get(code, date(2026, 9, 10)),
                ["002251.SZ", "600000.SH"],
            )
        )

    assert maximum == 1
    assert len(starts) == 2
    assert starts[1] - starts[0] >= 0.019
