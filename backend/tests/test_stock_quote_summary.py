"""个股详情行情摘要的日期对齐与量比口径。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.stocks import router
from backend.services.stock_quote_summary import StockQuoteSummaryService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _seed_stock(client: DuckDBClient, volumes: list[int]) -> None:
    client.execute(
        "INSERT INTO stock_basic "
        "(code,name,board,industry,total_share,float_share) VALUES "
        "('600000.SH','浦发银行','主板','银行',10000000000,8000000000)"
    )
    start = date(2026, 9, 1)
    for index, volume in enumerate(volumes):
        trade_date = start + timedelta(days=index)
        close = 10 + index
        client.execute(
            "INSERT INTO daily_bar "
            "(code,trade_date,open,high,low,close,pre_close,volume,amount,turnover_rate) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                "600000.SH", trade_date, close - 0.2, close + 0.3, close - 0.5,
                close, close - 1, volume, volume * close, 1.25,
            ],
        )
    latest = start + timedelta(days=len(volumes) - 1)
    client.execute("INSERT INTO stock_share_capital_daily(code,trade_date,total_share,float_share) VALUES (?,?,?,?)",
                   ["600000.SH", latest, 10_000_000_000, 8_000_000_000])
    client.execute(
        "INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) VALUES (?,?,?,?)",
        ["600000.SH", latest, 8_000_000_000, 10_000_000_000],
    )
    client.execute(
        "INSERT INTO stock_st_status_daily "
        "(code,trade_date,is_st,source,quality,captured_at,updated_at) "
        "VALUES (?, ?, FALSE, 'test', 'accurate', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ["600000.SH", latest],
    )


def test_quote_summary_aligns_latest_market_facts_and_excludes_today_from_volume_ratio():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_stock(market, [100, 200, 300, 400, 500, 600])

        result = StockQuoteSummaryService(market).get("600000.sh")

        assert result["code"] == "600000.SH"
        assert result["trade_date"] == "2026-09-06"
        assert result["close"] == 15.0
        assert result["volume_ratio"] == 2.0
        assert result["total_mv"] == 10_000_000_000
        assert result["float_mv"] == 8_000_000_000
        assert result["total_share"] == 10_000_000_000
        assert result["float_share"] == 8_000_000_000
        assert result["is_st"] is False
        assert result["pe_ttm"] is None


def test_quote_summary_keeps_ratio_and_valuation_empty_when_history_is_insufficient():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        # 停牌或异常零成交量不计入五个有效历史交易日。
        _seed_stock(market, [0, 100, 200, 300, 400, 500])
        market.execute("DELETE FROM daily_metrics")

        result = StockQuoteSummaryService(market).get("600000.SH")

        assert result["volume_ratio"] is None
        assert result["total_mv"] is None
        assert result["float_mv"] is None


def test_quote_summary_rejects_invalid_code_and_returns_empty_shape_for_unknown_stock():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        with pytest.raises(ValueError, match="股票代码格式非法"):
            StockQuoteSummaryService(market).get("600000")

        result = StockQuoteSummaryService(market).get("600001.SH")
        assert result["code"] == "600001.SH"
        assert result["trade_date"] is None
        assert result["close"] is None


def _api_client(monkeypatch, market: DuckDBClient) -> TestClient:
    monkeypatch.setattr("backend.api.stocks.get_client", lambda: market)
    app = FastAPI()
    app.include_router(router)
    for item in router.routes:
        for dependency in item.dependant.dependencies:
            if getattr(dependency.call, "resource_code", None) == "stocks:view":
                app.dependency_overrides[dependency.call] = lambda: None
    return TestClient(app)


def test_quote_summary_api_returns_contract_and_rejects_invalid_code(monkeypatch):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_stock(market, [100, 200, 300, 400, 500, 600])
        client = _api_client(monkeypatch, market)

        response = client.get("/api/stocks/600000.SH/quote-summary")
        assert response.status_code == 200
        assert response.json()["data"]["volume_ratio"] == 2.0

        invalid = client.get("/api/stocks/600000/quote-summary")
        assert invalid.status_code == 400
        assert "股票代码格式非法" in invalid.json()["detail"]


@pytest.mark.parametrize("adjust", ["", "qfq", "hfq"])
def test_bars_market_values_align_by_date_without_adjustment_or_gap_filling(monkeypatch, adjust):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_stock(market, [100, 200, 300, 400, 500, 600])
        market.execute("UPDATE daily_bar SET adj_factor = 2, adj_factor_clean = 2")
        market.execute(
            "UPDATE daily_bar SET adj_factor = 1, adj_factor_clean = 1 "
            "WHERE trade_date < DATE '2026-09-06'"
        )
        market.execute(
            "INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) VALUES "
            "('600000.SH','2026-09-04',5000000,9000000),"
            "('600001.SH','2026-09-05',90000000000,100000000000)"
        )
        client = _api_client(monkeypatch, market)
        params = {
            "adjust": adjust, "lookback": 3, "end": "2026-09-06",
            "include_market_values": True,
        }
        response = client.get("/api/stocks/600000.SH/bars", params=params)
        assert response.status_code == 200
        bars = response.json()["data"]["bars"]
        assert [(bar["date"], bar["total_mv"], bar["float_mv"]) for bar in bars] == [
            ("2026-09-04", 9_000_000, 5_000_000),
            ("2026-09-05", None, None),
            ("2026-09-06", 10_000_000_000, 8_000_000_000),
        ]
        assert bars[0]["total_share"] is None
        assert bars[-1]["total_share"] == 10_000_000_000
        assert bars[-1]["float_share"] == 8_000_000_000
        assert bars[0]["close"] == {"": 13, "qfq": 6.5, "hfq": 13}[adjust]
        # 历史截止日不带未来最新市值，普通消费者也不增加字段。
        params["end"] = "2026-09-05"
        historical = client.get("/api/stocks/600000.SH/bars", params=params)
        assert historical.json()["data"]["bars"][-1]["total_mv"] is None
        params.pop("include_market_values")
        legacy = client.get("/api/stocks/600000.SH/bars", params=params)
        assert all("total_mv" not in bar for bar in legacy.json()["data"]["bars"])


@pytest.mark.parametrize("lookback", [0, -1, 6001])
def test_bars_rejects_unbounded_market_value_windows_before_query(monkeypatch, lookback):
    client = _api_client(monkeypatch, object())
    response = client.get(
        "/api/stocks/600000.SH/bars",
        params={"include_market_values": True, "lookback": lookback},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("basis", ["point_in_time", "historical"])
def test_bars_market_values_6000_row_real_api_regression(monkeypatch, basis):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.execute("INSERT INTO stock_basic (code,name) VALUES ('600000.SH','测试股')")
        market.execute(
            "INSERT INTO daily_bar (code,trade_date,open,high,low,close,pre_close,volume,"
            "amount,turnover_rate,adj_factor) "
            "SELECT '600000.SH', DATE '2000-01-01' + CAST(i AS INTEGER),"
            "10,11,9,10,9,100,1000,1,1 FROM range(6001) t(i)"
        )
        market.execute(
            "INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) SELECT code,trade_date,5000000,9000000 FROM daily_bar "
            "WHERE trade_date <> DATE '2000-01-01' + 3000"
        )
        queries: list[list[object]] = []
        query_df = market.query_df

        def tracked_query(sql, params=None):
            if "unnest(?::DATE[])" in sql:
                queries.append(params)
            return query_df(sql, params)

        monkeypatch.setattr(market, "query_df", tracked_query)
        response = _api_client(monkeypatch, market).get(
            "/api/stocks/600000.SH/bars",
            params={"include_market_values": True, "lookback": 6000, "capital_basis": basis},
        )
        assert response.status_code == 200
        bars = response.json()["data"]["bars"]
        assert len(bars) == 6000
        assert len(queries) == 1
        assert len(queries[0][1]) == 6000
        assert bars[0]["date"] == "2000-01-02"
        assert bars[2999]["total_mv"] is None
        assert bars[-1]["total_mv"] == 9_000_000
