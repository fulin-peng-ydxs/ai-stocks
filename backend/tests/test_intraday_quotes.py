from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import pandas as pd
import pytest
import redis

from backend.services.intraday_quotes import IntradayQuoteService


class _Market:
    def __init__(self, *, has_stock=True, has_bar=True, rows=0) -> None:
        self.has_stock = has_stock
        self.has_bar = has_bar
        self.latest = date(2026, 9, 10)
        self.rows = rows
        self.queries = []

    def query_df(self, sql: str, params=None) -> pd.DataFrame:
        self.queries.append(sql)
        if "FROM stock_intraday_bar" in sql:
            return _frame(rows=self.rows)
        if "FROM stock_intraday_coverage" in sql:
            if "min(trade_date)" in sql:
                return pd.DataFrame({"lo": [None], "hi": [None]})
            return (
                pd.DataFrame(
                    [
                        {
                            "status": "ready" if self.rows == 240 else "partial",
                            "source": "sina",
                            "fetched_at": pd.Timestamp("2026-09-10 08:00"),
                            "revision": "revision-one",
                        }
                    ]
                )
                if self.rows
                else pd.DataFrame()
            )
        if "FROM stock_basic" in sql:
            return pd.DataFrame({"name": ["步步高"]}) if self.has_stock else pd.DataFrame()
        if "FROM trade_calendar" in sql:
            return pd.DataFrame(
                {"trade_date": [self.latest - timedelta(days=index) for index in range(8)]}
            )
        if "SELECT pre_close" in sql:
            return (
                pd.DataFrame({"pre_close": [3.55], "turnover_rate": [6.8]})
                if self.has_bar
                else pd.DataFrame()
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

    def get_intraday_1m(self, _code: str, provider: str, *, timeout_sec=None) -> pd.DataFrame:
        self.calls.append(provider)
        if self.delay:
            time.sleep(self.delay)
        return self.frame.copy()


def test_missing_archive_never_uses_source_window_or_negative_cache() -> None:
    cache = _Redis()
    # 即使 Redis 中仍有旧版源窗口或失败缓存，查询也只承认 DB 事实。
    cache.set("market:intraday:1m:window:sina:002251.SZ", "legacy source response")
    cache.set("market:intraday:1m:negative:002251.SZ", "source offline")
    market = _Market()
    service = IntradayQuoteService(market=market, redis_client=cache)
    for day in (date(2026, 9, 10), date(2026, 8, 1)):
        result = service.get("002251.SZ", day)
        assert result["status"] == "no_data" and result["points"] == []
        assert not result["archived"]
        assert result["supported_start"] is None and result["supported_end"] is None
    assert not any("trade_calendar" in sql for sql in market.queries)
    assert not hasattr(service, "fetch_window")


def test_db_read_populates_cache_and_hit_avoids_minute_detail_read() -> None:
    market, cache = _Market(rows=240), _Redis()
    service = IntradayQuoteService(market=market, redis_client=cache)
    first = service.get("002251.SZ", date(2026, 9, 10))
    again = service.get("002251.SZ", date(2026, 9, 10))
    assert first == again
    assert first["status"] == "ready" and first["archived"]
    assert first["pre_close"] == 3.55 and first["turnover_rate"] == 6.8
    assert first["points"][0]["volume"] == 10
    assert first["points"][1]["average_price"] == pytest.approx(3.6005)
    assert sum("FROM stock_intraday_bar" in sql for sql in market.queries) == 1
    assert any(":archive:" in key for key in cache.values)


@pytest.mark.parametrize("rows", [0, 3, 240])
def test_redis_failure_never_blocks_database_query(rows) -> None:
    cache = _Redis()
    cache.fail = True
    result = IntradayQuoteService(market=_Market(rows=rows), redis_client=cache).get(
        "002251.SZ", date(2026, 9, 10)
    )
    assert result["status"] == ("no_data" if rows == 0 else "partial" if rows == 3 else "ready")
    assert len(result["points"]) == rows


def test_partial_archive_keeps_real_points_without_fetch_or_fill() -> None:
    result = IntradayQuoteService(market=_Market(rows=3), redis_client=_Redis()).get(
        "002251.SZ", date(2026, 9, 10)
    )
    assert result["status"] == "partial"
    assert [point["time"] for point in result["points"]] == ["09:31", "09:32", "09:33"]


def test_missing_daily_metadata_does_not_hide_archived_minutes() -> None:
    result = IntradayQuoteService(
        market=_Market(rows=240, has_bar=False), redis_client=_Redis()
    ).get("002251.SZ", date(2026, 9, 10))
    assert result["status"] == "ready" and result["pre_close"] is None
