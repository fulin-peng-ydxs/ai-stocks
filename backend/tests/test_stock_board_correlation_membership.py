"""个股走势关联板块 T2：累计归属服务、接口与权限契约。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.api.stocks import router
from backend.auth.context import AuthContext
from backend.common.exceptions import AIStocksError
from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.services.stock_codes import normalize_stock_codes
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


class _CountingClient:
    def __init__(self, delegate: DuckDBClient):
        self.delegate = delegate
        self.queries = 0

    def query_df(self, sql, params=None):
        self.queries += 1
        return self.delegate.query_df(sql, params)


def _seed_memberships(client: DuckDBClient) -> None:
    client.execute(
        "INSERT INTO stock_basic (code, name, board, industry) VALUES "
        "('600000.SH', '浦发银行', '主板', '银行业'), "
        "('000001.SZ', '平安银行', '主板', '银行业')"
    )
    client.execute(
        "INSERT INTO board_dict "
        "(board_code, name, board_type, member_snapshot_at) VALUES "
        "('881002', '银行', 'industry', TIMESTAMP '2026-08-28 18:00:00'), "
        "('881001', '银行', 'industry', TIMESTAMP '2026-08-27 18:00:00'), "
        "('301002', '金融科技', 'concept', TIMESTAMP '2026-08-29 18:00:00'), "
        "('301001', '中特估', 'concept', TIMESTAMP '2026-08-26 18:00:00'), "
        "('999001', '非法类型', 'theme', TIMESTAMP '2026-08-30 18:00:00')"
    )
    client.execute(
        "INSERT INTO board_member (board_code, code) VALUES "
        "('881002', '600000.SH'), ('881001', '600000.SH'), "
        "('301002', '600000.SH'), ('301001', '600000.SH'), "
        "('999001', '600000.SH'), ('missing', '600000.SH'), "
        "('881002', '300999.SZ')"
    )


def test_stock_code_helper_normalizes_and_stably_deduplicates():
    assert normalize_stock_codes([" 600000.sh ", "000001.SZ", "600000.SH"]) == [
        "600000.SH",
        "000001.SZ",
    ]
    with pytest.raises(ValueError, match="股票代码格式非法"):
        normalize_stock_codes(["600000"])


def test_membership_batch_is_one_query_and_filters_invalid_relations():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        counting = _CountingClient(market)
        service = StockBoardCorrelationService(counting)  # type: ignore[arg-type]

        result = service.get_memberships(["600000.sh", "000001.SZ", "600000.SH"])

        assert counting.queries == 1
        assert list(result) == ["600000.SH", "000001.SZ"]
        assert result["600000.SH"] == {
            "code": "600000.SH",
            "membership_scope": "cumulative",
            "membership_updated_at": "2026-08-29T18:00:00",
            "industries": [
                {"board_code": "881001", "name": "银行", "board_type": "industry"},
                {"board_code": "881002", "name": "银行", "board_type": "industry"},
            ],
            "concepts": [
                {"board_code": "301001", "name": "中特估", "board_type": "concept"},
                {"board_code": "301002", "name": "金融科技", "board_type": "concept"},
            ],
        }
        assert result["000001.SZ"]["industries"] == []
        assert result["000001.SZ"]["concepts"] == []
        assert result["000001.SZ"]["membership_updated_at"] is None


def test_empty_membership_batch_does_not_query():
    counting = _CountingClient(DuckDBClient(db_path=":memory:"))
    assert StockBoardCorrelationService(counting).get_memberships([]) == {}  # type: ignore[arg-type]
    assert counting.queries == 0


def test_missing_stock_does_not_consume_orphan_membership():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        result = StockBoardCorrelationService(market).get_membership("300999.SZ")

        assert result["industries"] == []
        assert result["concepts"] == []
        assert result["membership_updated_at"] is None


def _api_client(monkeypatch: pytest.MonkeyPatch, market: DuckDBClient) -> TestClient:
    monkeypatch.setattr("backend.api.stocks.get_client", lambda: market)
    app = FastAPI()
    app.include_router(router)
    for route_item in app.routes:
        for dependency in getattr(getattr(route_item, "dependant", None), "dependencies", []):
            call = getattr(dependency, "call", None)
            if getattr(call, "resource_code", None) == "stocks:view":
                app.dependency_overrides[call] = lambda: None
    return TestClient(app)


def test_related_boards_api_returns_membership_and_rejects_invalid_code(monkeypatch):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        client = _api_client(monkeypatch, market)

        response = client.get("/api/stocks/600000.sh/related-boards")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["code"] == "600000.SH"
        assert data["membership_scope"] == "cumulative"
        assert len(data["industries"]) == 2
        assert len(data["concepts"]) == 2

        invalid = client.get("/api/stocks/600000/related-boards")
        assert invalid.status_code == 400
        assert "股票代码格式非法" in invalid.json()["detail"]


def test_related_boards_route_exposes_stocks_view_and_returns_401_403(monkeypatch):
    route_item = next(
        item for item in router.routes if item.path == "/api/stocks/{code}/related-boards"
    )
    dependency = next(
        dep.call
        for dep in route_item.dependant.dependencies
        if getattr(dep.call, "resource_code", None) == "stocks:view"
    )
    assert dependency.resource_code == "stocks:view"

    app = FastAPI()

    @app.exception_handler(AIStocksError)
    async def handle_error(_, exc: AIStocksError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "msg": exc.msg, "data": None},
        )

    app.include_router(router)
    client = TestClient(app)

    monkeypatch.setattr("backend.auth.deps.get_current_context", lambda: None)
    assert client.get("/api/stocks/600000.SH/related-boards").status_code == 401

    context = AuthContext(
        user_id="pytest_user",
        tenant_id="pytest_tenant",
        resources=frozenset(),
    )
    monkeypatch.setattr("backend.auth.deps.get_current_context", lambda: context)
    assert client.get("/api/stocks/600000.SH/related-boards").status_code == 403
