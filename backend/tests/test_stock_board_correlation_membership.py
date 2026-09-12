"""个股走势关联板块 T2：累计归属服务、接口与权限契约。"""

from __future__ import annotations

from datetime import date

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
    client.execute(
        "INSERT INTO stock_st_status_daily "
        "(code,trade_date,is_st,source,source_ref,quality,captured_at,updated_at) VALUES "
        "('600000.SH',DATE '2026-08-28',FALSE,'baostock',"
        "'query_history_k_data_plus:isST','accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
        "('600000.SH',DATE '2026-08-29',FALSE,'baostock',"
        "'query_history_k_data_plus:isST','accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
        "('000001.SZ',DATE '2026-08-28',FALSE,'baostock',"
        "'query_history_k_data_plus:isST','accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
        "('000001.SZ',DATE '2026-08-29',FALSE,'baostock',"
        "'query_history_k_data_plus:isST','accurate',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
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


def test_membership_as_of_keeps_legacy_null_and_filters_explicit_future_first_seen():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        market.execute(
            "UPDATE board_member SET first_seen_date=DATE '2026-08-29' "
            "WHERE board_code='301002' AND code='600000.SH'"
        )

        before = StockBoardCorrelationService(market).get_memberships(
            ["600000.SH"], date(2026, 8, 28)
        )["600000.SH"]
        on_date = StockBoardCorrelationService(market).get_memberships(
            ["600000.SH"], date(2026, 8, 29)
        )["600000.SH"]

        assert {item["board_code"] for item in before["concepts"]} == {"301001"}
        assert {item["board_code"] for item in on_date["concepts"]} == {"301001", "301002"}
        # 未回填 first_seen_date 的存量行业关系在任意历史日期继续参与。
        assert {item["board_code"] for item in before["industries"]} == {"881001", "881002"}


def test_membership_options_and_member_codes_share_valid_point_in_time_scope():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        market.execute(
            "UPDATE board_member SET first_seen_date=DATE '2026-08-29' "
            "WHERE board_code='301002' AND code='600000.SH'"
        )
        service = StockBoardCorrelationService(market)

        options = service.list_membership_options()

        assert [(item["board_type"], item["name"], item["board_code"]) for item in options] == [
            ("industry", "银行", "881001"),
            ("industry", "银行", "881002"),
            ("concept", "中特估", "301001"),
            ("concept", "金融科技", "301002"),
        ]
        assert service.member_codes_for_board(None) is None
        assert service.member_codes_for_board("unknown") == set()
        assert service.member_codes_for_board("301002", date(2026, 8, 28)) == set()
        assert service.member_codes_for_board("301002", date(2026, 8, 29)) == {"600000.SH"}
def test_membership_large_batch_avoids_duckdb_window_parameter_internal_error():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        codes = [f"{700000 + index}.SH" for index in range(1024)]
        market.execute(
            "INSERT INTO board_dict (board_code,name,board_type,member_snapshot_at) "
            "VALUES ('large-industry','大批量行业','industry',"
            "TIMESTAMP '2026-08-28 18:00:00')"
        )
        market.conn.executemany(
            "INSERT INTO stock_basic (code,name,board) VALUES (?,?,'主板')",
            [(code, f"大批量股票{index}") for index, code in enumerate(codes)],
        )
        market.conn.executemany(
            "INSERT INTO board_member (board_code,code) VALUES ('large-industry',?)",
            [(code,) for code in codes],
        )
        counting = _CountingClient(market)

        result = StockBoardCorrelationService(counting).get_memberships(codes)  # type: ignore[arg-type]

        assert counting.queries == 1
        assert len(result) == len(codes)
        assert result[codes[-1]]["membership_updated_at"] == "2026-08-28T18:00:00"
        assert result[codes[-1]]["industries"] == [
            {"board_code": "large-industry", "name": "大批量行业", "board_type": "industry"}
        ]


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
        assert data["related_boards"] is None

        invalid = client.get("/api/stocks/600000/related-boards")
        assert invalid.status_code == 400
        assert "股票代码格式非法" in invalid.json()["detail"]


def test_membership_options_and_stock_list_filter_api(monkeypatch):
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        market.execute(
            "UPDATE board_member SET first_seen_date=DATE '2026-08-29' "
            "WHERE board_code='301002' AND code='600000.SH'"
        )
        monkeypatch.setattr(
            StockBoardCorrelationService,
            "attach_related_boards",
            lambda _self, _rows, _business_dates=None: None,
        )
        client = _api_client(monkeypatch, market)

        options = client.get("/api/stocks/membership-options")
        assert options.status_code == 200
        assert len(options.json()["data"]["list"]) == 4

        before = client.get(
            "/api/stocks?trade_date=2026-08-28&membership_board_code=301002"
        )
        on_date = client.get(
            "/api/stocks?trade_date=2026-08-29&membership_board_code=301002"
        )
        unknown = client.get(
            "/api/stocks?trade_date=2026-08-29&membership_board_code=unknown"
        )

        assert before.json()["data"]["total"] == 0
        assert [row["code"] for row in on_date.json()["data"]["list"]] == ["600000.SH"]
        assert unknown.json()["data"]["total"] == 0


def test_related_boards_route_exposes_stocks_view_and_returns_401_403(monkeypatch):
    paths = (
        "/api/stocks/{code}/related-boards",
        "/api/stocks/{code}/quote-summary",
        "/api/stocks/membership-options",
    )
    for path in paths:
        route_item = next(item for item in router.routes if item.path == path)
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
    assert client.get("/api/stocks/600000.SH/quote-summary").status_code == 401
    assert client.get("/api/stocks/membership-options").status_code == 401

    context = AuthContext(
        user_id="pytest_user",
        tenant_id="pytest_tenant",
        resources=frozenset(),
    )
    monkeypatch.setattr("backend.auth.deps.get_current_context", lambda: context)
    assert client.get("/api/stocks/600000.SH/related-boards").status_code == 403
    assert client.get("/api/stocks/600000.SH/quote-summary").status_code == 403
    assert client.get("/api/stocks/membership-options").status_code == 403


def test_related_boards_api_fail_closed_when_as_of_behind_latest(monkeypatch):
    """单股接口未传业务日期时，默认以最新交易日参与保护：冠军 as_of 落后 → as_of_mismatch。

    与列表页口径一致；防止把旧冠军装饰成"当天"。空 daily_bar 时该守卫不触发（退化为直接返回最近结果）。
    """
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        # daily_bar 最新交易日 = 08-31；冠军结果 as_of 仍 = 08-28（落后）→ 应 as_of_mismatch。
        market.execute(
            "INSERT INTO daily_bar (code, trade_date) VALUES ('600000.SH', DATE '2026-08-31')"
        )
        market.execute(
            "INSERT INTO stock_board_correlation_state "
            "(code,as_of_date,computed_at,algorithm_version,benchmark_code,benchmark_fallback,"
            "has_industry_champion,has_concept_champion) VALUES "
            "('600000.SH',DATE '2026-08-28',TIMESTAMP '2026-08-28 18:00:00',"
            "'stock-board-correlation-v2','399001.SZ',false,true,true)"
        )
        market.execute(
            "INSERT INTO stock_board_correlation "
            "(code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,confidence,"
            "benchmark_code,benchmark_fallback,as_of_date,computed_at,algorithm_version) VALUES "
            "('600000.SH','industry','881002',0.82,0.86,0.76,20,58,'high','399001.SZ',false,"
            "DATE '2026-08-28',TIMESTAMP '2026-08-28 18:00:00','stock-board-correlation-v2'),"
            "('600000.SH','concept','301002',0.51,0.55,0.45,18,50,'medium','399001.SZ',false,"
            "DATE '2026-08-28',TIMESTAMP '2026-08-28 18:00:00','stock-board-correlation-v2')"
        )
        client = _api_client(monkeypatch, market)

        response = client.get("/api/stocks/600000.SH/related-boards")
        assert response.status_code == 200
        data = response.json()["data"]
        rb = data["related_boards"]
        assert rb["as_of_date"] is None
        assert rb["unavailable_reason"] == "as_of_mismatch"
        assert rb["industry"] is None
        assert rb["concept"] is None


def test_membership_market_change_uses_exact_business_date_without_fallback():
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        _seed_memberships(market)
        market.execute(
            "INSERT INTO board_bar (board_code,trade_date,close) VALUES "
            "('881002',DATE '2026-08-28',100),"
            "('881002',DATE '2026-08-29',102),"
            "('301002',DATE '2026-08-28',95)"
        )

        result = StockBoardCorrelationService(market).get_membership_with_market(
            "600000.SH", date(2026, 8, 29)
        )

        assert result["trade_date"] == "2026-08-29"
        industries = {item["board_code"]: item["pct_chg"] for item in result["industries"]}
        concepts = {item["board_code"]: item["pct_chg"] for item in result["concepts"]}
        assert industries["881002"] == 2.0
        assert industries["881001"] is None
        assert concepts["301002"] is None


def test_resolve_data_family_maxima_exposes_three_families():
    """resolve_data_family_maxima 返回个股/板块指数/宽基指数三者各自最新交易日。"""
    with DuckDBClient(db_path=":memory:") as market:
        init_db(market)
        market.execute(
            "INSERT INTO daily_bar (code, trade_date) VALUES ('600000.SH', DATE '2026-08-31')"
        )
        market.execute(
            "INSERT INTO board_bar (board_code, trade_date, close) "
            "VALUES ('881001', DATE '2026-08-28', 1.0)"
        )
        market.execute(
            "INSERT INTO index_bar (index_code, trade_date, close) "
            "VALUES ('000001', DATE '2026-08-28', 1.0)"
        )
        svc = StockBoardCorrelationService(market)
        assert svc.resolve_data_family_maxima() == {
            "daily_bar": date(2026, 8, 31),
            "board_bar": date(2026, 8, 28),
            "index_bar": date(2026, 8, 28),
        }
