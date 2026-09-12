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


def test_quote_summary_api_returns_contract_and_rejects_invalid_code(monkeypatch):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_stock(market, [100, 200, 300, 400, 500, 600])
        monkeypatch.setattr("backend.api.stocks.get_client", lambda: market)
        app = FastAPI()
        app.include_router(router)
        route_item = next(
            item for item in router.routes
            if item.path == "/api/stocks/{code}/quote-summary"
        )
        dependency = next(
            dep.call
            for dep in route_item.dependant.dependencies
            if getattr(dep.call, "resource_code", None) == "stocks:view"
        )
        app.dependency_overrides[dependency] = lambda: None
        client = TestClient(app)

        response = client.get("/api/stocks/600000.SH/quote-summary")
        assert response.status_code == 200
        assert response.json()["data"]["volume_ratio"] == 2.0

        invalid = client.get("/api/stocks/600000/quote-summary")
        assert invalid.status_code == 400
        assert "股票代码格式非法" in invalid.json()["detail"]
