"""股票分析页市场基准：共享口径、股票权限域和参数边界。"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.stocks import router
from backend.auth.context import AuthContext, reset_context, set_context
from backend.common.exceptions import ForbiddenError


class _StubBenchmarkService:
    calls: ClassVar[list[tuple[str, object, int]]] = []

    def __init__(self, _client):
        pass

    def get_lookback(self, code, end, lookback):
        self.calls.append((code, end, lookback))
        return [{
            "trade_date": "2026-08-07",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 10,
            "amount": 1000.0,
        }]

    @staticmethod
    def name(code):
        return "中证 500" if code == "000905.SH" else code


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    _StubBenchmarkService.calls = []
    monkeypatch.setattr("backend.api.stocks.get_client", lambda: object())
    monkeypatch.setattr("backend.api.stocks.MarketBenchmarkService", _StubBenchmarkService)
    app = FastAPI()
    app.include_router(router)
    for route in app.routes:
        for dependency in getattr(getattr(route, "dependant", None), "dependencies", []):
            call = getattr(dependency, "call", None)
            if getattr(call, "resource_code", None) in {"stocks:view", "stocks:trade-eval"}:
                app.dependency_overrides[call] = lambda: None
    return TestClient(app)


def test_stock_benchmark_route_uses_shared_service_and_stocks_shape(monkeypatch):
    response = _client(monkeypatch).get(
        "/api/stocks/benchmarks/000905.SH/bars",
        params={"lookback": 61, "end": "2026-08-07"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["index_code"] == "000905.SH"
    assert data["name"] == "中证 500"
    assert data["bars"] == [{
        "date": "2026-08-07",
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10,
        "amount": 1000.0,
        "pre_close": None,
        "turnover_rate": None,
    }]
    assert _StubBenchmarkService.calls == [("000905.SH", date(2026, 8, 7), 61)]


@pytest.mark.parametrize("lookback", [1, 6001])
def test_stock_benchmark_route_rejects_invalid_lookback(monkeypatch, lookback):
    response = _client(monkeypatch).get(
        "/api/stocks/benchmarks/000905.SH/bars",
        params={"lookback": lookback, "end": "2026-08-07"},
    )

    assert response.status_code == 422
    assert _StubBenchmarkService.calls == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/stocks?trade_date=2026-02-30",
        "/api/stocks/000001.SZ/bars?end=2026-02-30",
        "/api/stocks/benchmarks/000905.SH/bars?end=2026-02-30",
        "/api/stocks/000001.SZ/signal?date=2026-02-30",
        "/api/stocks/000001.SZ/trade-eval?profile_id=private:test&date=2026-02-30",
    ],
)
def test_stock_routes_reject_invalid_dates_before_business_queries(monkeypatch, path):
    response = _client(monkeypatch).get(path)

    assert response.status_code == 422
    assert _StubBenchmarkService.calls == []


def test_stock_benchmark_route_keeps_stocks_view_guard():
    route = next(
        item for item in router.routes
        if item.path == "/api/stocks/benchmarks/{index_code}/bars"
    )
    dependency = next(
        dep.call for dep in route.dependant.dependencies
        if getattr(dep.call, "resource_code", None) == "stocks:view"
    )
    token = set_context(AuthContext(
        user_id="pytest_user",
        tenant_id="pytest_tenant",
        resources=frozenset(),
    ))
    try:
        with pytest.raises(ForbiddenError):
            dependency()
    finally:
        reset_context(token)
