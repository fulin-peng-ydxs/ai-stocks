from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from backend.api import stocks


def test_intraday_route_reuses_stocks_view_permission() -> None:
    route = next(
        item for item in stocks.router.routes if item.path == "/api/stocks/{code}/intraday"
    )
    dependencies = [dependency.call for dependency in route.dependant.dependencies]

    assert len(dependencies) == 1
    assert getattr(dependencies[0], "resource_code", None) == "stocks:view"


def test_intraday_api_returns_business_status_without_transformation(monkeypatch) -> None:
    payload = {
        "code": "002251.SZ",
        "name": "步步高",
        "trade_date": "2026-09-10",
        "frequency": "1m",
        "status": "out_of_range",
        "source": None,
        "fetched_at": None,
        "supported_start": "2026-09-01",
        "supported_end": "2026-09-10",
        "pre_close": None,
        "points": [],
    }

    class Service:
        @staticmethod
        def get(_code, _trade_date):
            return payload

    monkeypatch.setattr(stocks, "IntradayQuoteService", Service)
    response = stocks.stock_intraday("002251.SZ", date(2026, 8, 1))

    assert response.data == payload


def test_intraday_api_translates_temporary_failure_to_503(monkeypatch) -> None:
    class Service:
        @staticmethod
        def get(_code, _trade_date):
            raise stocks.IntradayServiceUnavailable("分时数据暂时不可用")

    monkeypatch.setattr(stocks, "IntradayQuoteService", Service)
    with pytest.raises(HTTPException) as exc_info:
        stocks.stock_intraday("002251.SZ", date(2026, 9, 10))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "分时数据暂时不可用"
