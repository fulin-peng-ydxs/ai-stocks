"""个股指标序列 API：字段裁剪、边界、严格 JSON 与权限契约。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.stocks import router
from backend.auth.context import AuthContext, reset_context, set_context
from backend.common.exceptions import ForbiddenError


class _StubEngine:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls: list[tuple[str, object, int | None]] = []

    def compute_series(
        self,
        code: str,
        end_date=None,
        lookback: int | None = None,
    ) -> pd.DataFrame:
        self.calls.append((code, end_date, lookback))
        return self.frame.copy()


def _client(monkeypatch: pytest.MonkeyPatch, engine: _StubEngine) -> TestClient:
    monkeypatch.setattr("backend.api.stocks.get_client", lambda: object())
    monkeypatch.setattr("backend.indicators.engine.IndicatorEngine", lambda _client: engine)
    app = FastAPI()
    app.include_router(router)
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dependency in getattr(dependant, "dependencies", []):
            call = getattr(dependency, "call", None)
            if getattr(call, "resource_code", None) == "stocks:view":
                app.dependency_overrides[call] = lambda: None
    return TestClient(app)


def _data(response) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    return body["data"]


def test_indicators_without_fields_keeps_full_legacy_row(monkeypatch):
    engine = _StubEngine(pd.DataFrame([{
        "code": "600000.SH",
        "trade_date": pd.Timestamp("2026-07-22"),
        "ma20": np.float64(10.5),
        "param_hash": "legacy-hash",
    }]))
    data = _data(_client(monkeypatch, engine).get("/api/stocks/600000.SH/indicators"))

    assert data == {
        "code": "600000.SH",
        "indicators": [{
            "code": "600000.SH",
            "trade_date": "2026-07-22",
            "ma20": 10.5,
            "param_hash": "legacy-hash",
        }],
    }
    assert engine.calls == [("600000.SH", None, 580)]


def test_indicators_fields_are_deduplicated_and_non_finite_values_become_null(monkeypatch):
    engine = _StubEngine(pd.DataFrame([
        {
            "code": "600000.SH",
            "trade_date": pd.Timestamp("2026-07-21"),
            "macd_diff": np.float64(np.nan),
            "macd_dea": np.float64(-np.inf),
            "macd_hist": np.float64(0.25),
            "macd_golden_cross": pd.NA,
            "macd_dead_cross": np.bool_(False),
        },
        {
            "code": "600000.SH",
            "trade_date": pd.Timestamp("2026-07-22"),
            "macd_diff": np.float64(np.inf),
            "macd_dea": np.float64(-0.15),
            "macd_hist": pd.NA,
            "macd_golden_cross": np.bool_(True),
            "macd_dead_cross": pd.NA,
        },
    ]))
    response = _client(monkeypatch, engine).get(
        "/api/stocks/600000.SH/indicators",
        params={
            "lookback": 2,
            "fields": (
                "macd_diff,macd_dea,macd_hist,,macd_golden_cross,"
                "macd_diff,macd_dead_cross"
            ),
        },
    )

    assert _data(response)["indicators"] == [
        {
            "trade_date": "2026-07-21",
            "macd_diff": None,
            "macd_dea": None,
            "macd_hist": 0.25,
            "macd_golden_cross": None,
            "macd_dead_cross": False,
        },
        {
            "trade_date": "2026-07-22",
            "macd_diff": None,
            "macd_dea": -0.15,
            "macd_hist": None,
            "macd_golden_cross": True,
            "macd_dead_cross": None,
        },
    ]
    assert engine.calls == [("600000.SH", None, 522)]


@pytest.mark.parametrize(("lookback", "engine_lookback"), [(1, 521), (6000, 6520)])
def test_indicators_lookback_boundaries(monkeypatch, lookback, engine_lookback):
    engine = _StubEngine(pd.DataFrame())
    data = _data(_client(monkeypatch, engine).get(
        "/api/stocks/600000.SH/indicators",
        params={"lookback": lookback},
    ))

    assert data == {"code": "600000.SH", "indicators": []}
    assert engine.calls == [("600000.SH", None, engine_lookback)]


@pytest.mark.parametrize("lookback", [0, 6001])
def test_indicators_rejects_out_of_range_lookback(monkeypatch, lookback):
    engine = _StubEngine(pd.DataFrame())
    response = _client(monkeypatch, engine).get(
        "/api/stocks/600000.SH/indicators",
        params={"lookback": lookback},
    )

    assert response.status_code == 422
    assert engine.calls == []


def test_indicators_passes_historical_end_date_to_engine(monkeypatch):
    engine = _StubEngine(pd.DataFrame())
    data = _data(_client(monkeypatch, engine).get(
        "/api/stocks/600000.SH/indicators",
        params={"lookback": 120, "end": "2026-06-30"},
    ))

    assert data == {"code": "600000.SH", "indicators": []}
    assert engine.calls == [("600000.SH", pd.Timestamp("2026-06-30").date(), 640)]


def test_indicators_rejects_unknown_field_before_compute(monkeypatch):
    engine = _StubEngine(pd.DataFrame())
    response = _client(monkeypatch, engine).get(
        "/api/stocks/600000.SH/indicators",
        params={"fields": "macd_diff,param_hash,close,drop table indicator_def"},
    )

    assert response.status_code == 400
    assert "param_hash, close, drop table indicator_def" in response.json()["detail"]
    assert engine.calls == []


def test_indicators_empty_field_list_returns_trade_date_only(monkeypatch):
    engine = _StubEngine(pd.DataFrame([{
        "code": "600000.SH",
        "trade_date": pd.Timestamp("2026-07-22"),
        "ma20": 10.5,
    }]))
    data = _data(_client(monkeypatch, engine).get(
        "/api/stocks/600000.SH/indicators",
        params={"fields": ",, ,"},
    ))

    assert data["indicators"] == [{"trade_date": "2026-07-22"}]


def test_indicators_route_keeps_stocks_view_guard():
    route = next(
        item
        for item in router.routes
        if item.path == "/api/stocks/{code}/indicators"
    )
    dependency = next(
        dep.call
        for dep in route.dependant.dependencies
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
