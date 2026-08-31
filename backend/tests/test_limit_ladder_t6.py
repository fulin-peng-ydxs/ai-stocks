"""T6: stable limit-ladder query/status/filter/export API contract."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import limit_ladder as api_module
from backend.auth.context import AuthContext, reset_context, set_context
from backend.common.exceptions import ForbiddenError
from backend.services.limit_ladder_calculator import LimitLadderCalculator
from backend.services.limit_ladder_query import LimitLadderFilters, LimitLadderQueryService
from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService
from backend.storage.repository import MarketRepository


class _FakeRepository:
    def get_active_for_date(self, trade_date):
        return None


class _FakeTasks:
    def get(self, task_id):
        return None


@dataclass
class _TaskResult:
    command_id: str = "command-1"
    task_id: str = "task-1"
    status: str = "requested"
    reused: bool = False


class _FakeCoordinator:
    def __init__(self):
        self.repository = _FakeRepository()
        self.tasks = _FakeTasks()
        self.calls = []

    def ensure_date_task(self, trade_date, **kwargs):
        self.calls.append((trade_date, kwargs))
        return _TaskResult()


def _seed_ladder(market):
    trade_date = date(2022, 8, 28)
    dates = [trade_date - timedelta(days=offset) for offset in reversed(range(10))]
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": dates, "is_open": True})
    )
    MarketRepository(market).upsert_stock_basic(
        pd.DataFrame(
            [
                ["600001.SH", "甲软件", "主板", dates[0], "软件", 0.10],
                ["600002.SH", "乙科技", "主板", dates[-3], "半导体", 0.10],
            ],
            columns=["code", "name", "board", "list_date", "industry", "price_limit_pct"],
        )
    )
    bars = []
    for code, first, close, pre_close in (
        ("600001.SH", dates[0], 11.0, 10.0),
        ("600002.SH", dates[-3], 11.0, 10.0),
    ):
        for day in dates:
            if day < first:
                continue
            bars.append(
                {
                    "code": code,
                    "trade_date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "pre_close": pre_close,
                    "volume": 100,
                    "amount": 2000 if code == "600002.SH" else 1000,
                    "adj_factor": 1.0,
                    "turnover_rate": 1.0,
                    "is_st": False,
                    "is_suspended": False,
                    "is_one_word": code == "600002.SH",
                }
            )
    MarketRepository(market).upsert_daily_bar(pd.DataFrame(bars))
    market.execute(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES "
        "('C001','人工智能','concept'),('C002','机器人','concept'),"
        "('I900','数字服务','industry')"
    )
    market.execute(
        "INSERT INTO board_member (board_code,code) VALUES "
        "('C001','600001.SH'),('C001','600002.SH'),('C002','600001.SH')"
    )
    market.execute(
        """
        INSERT INTO stock_board_correlation (
            code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,
            confidence,benchmark_code,benchmark_fallback,as_of_date,computed_at,algorithm_version
        ) VALUES
          ('600001.SH','concept','C002',0.8,0.8,0.8,20,60,'high','000300.SH',false,?,current_timestamp,'v1'),
          ('600001.SH','industry','I900',0.7,0.7,0.7,20,60,'high','000300.SH',false,?,current_timestamp,'v1')
        """,
        [trade_date, trade_date],
    )
    outcome = LimitLadderSnapshotService(market).materialize(trade_date, task_id="task-ok")
    assert outcome.status == "valid"
    return trade_date


def test_query_keeps_stock_level_short_history_and_separates_concepts(market):
    trade_date = _seed_ladder(market)
    service = LimitLadderQueryService(market, coordinator=_FakeCoordinator())

    data = service.query(trade_date, LimitLadderFilters(window=10, ignore_st=False))

    assert data["business_code"] == "READY"
    assert data["requested_window_trade_days"] == 10
    assert "window_start_date" not in data
    stocks = [stock for layer in data["layers"] for stock in layer["stocks"]]
    short = next(stock for stock in stocks if stock["code"] == "600002.SH")
    assert short["actual_trade_days"] == 3
    assert short["window_start_date"] == (trade_date - timedelta(days=2)).isoformat()
    assert short["window_return_pct"] == 0.0
    software = next(stock for stock in stocks if stock["code"] == "600001.SH")
    assert software["window_return_pct"] == 0.0
    assert {item["board_name"] for item in software["snapshot_concepts"]} == {"人工智能", "机器人"}
    assert software["latest_related_concept"] == {
        "board_code": "C002",
        "board_name": "机器人",
        "as_of_date": trade_date.isoformat(),
    }
    assert software["latest_related_industry"] == {
        "board_code": "I900",
        "board_name": "数字服务",
        "as_of_date": trade_date.isoformat(),
    }
    assert data["hotspots"]["industry"] == [
        {"group_key": "I900", "group_name": "数字服务", "stock_count": 1},
        {"group_key": "__unclassified__", "group_name": "未分类", "stock_count": 1},
    ]
    assert data["hotspots"]["concept"] == [
        {"group_key": "__unclassified__", "group_name": "未分类", "stock_count": 1},
        {"group_key": "C002", "group_name": "机器人", "stock_count": 1},
    ]
    assert sum(item["stock_count"] for item in data["hotspots"]["concept"]) == 2
    assert sum(item["stock_count"] for item in data["hotspots"]["industry"]) == 2


def test_filters_summary_hotspots_and_csv_share_one_visible_collection(market):
    trade_date = _seed_ladder(market)
    service = LimitLadderQueryService(market, coordinator=_FakeCoordinator())
    filters = LimitLadderFilters(
        window=10,
        boards=("main",),
        ignore_st=False,
        keyword="甲",
        hotspot_type="concept",
        hotspot_key="C002",
    )
    data = service.query(trade_date, filters)
    assert data["summary"]["stock_count"] == 1
    assert [stock["code"] for layer in data["layers"] for stock in layer["stocks"]] == [
        "600001.SH"
    ]
    assert data["hotspots"]["concept"] == [
        {"group_key": "C002", "group_name": "机器人", "stock_count": 1},
    ]

    industry_data = service.query(
        trade_date,
        LimitLadderFilters(
            window=10,
            boards=("main",),
            ignore_st=False,
            keyword="甲",
            hotspot_type="industry",
            hotspot_key="I900",
        ),
    )
    assert industry_data["summary"]["stock_count"] == 1
    assert industry_data["hotspots"]["industry"] == [
        {"group_key": "I900", "group_name": "数字服务", "stock_count": 1},
    ]

    filename, payload = service.export_csv(trade_date, filters)
    assert filename == "limit-ladder-2022-08-28-10d.csv"
    assert payload.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert [row["代码"] for row in rows] == ["600001.SH"]
    assert rows[0]["快照概念"] == "人工智能、机器人"
    assert rows[0]["窗口累计涨幅"] == "0.0"
    assert rows[0]["最新相关概念"] == "机器人"
    assert rows[0]["相关概念截止日"] == "2022-08-28"


def test_window_return_prefers_clean_adjustment_factor(market):
    trade_date = _seed_ladder(market)
    market.execute(
        """
        UPDATE daily_bar
        SET adj_factor=9,adj_factor_clean=2
        WHERE code='600001.SH'
          AND trade_date=(SELECT min(trade_date) FROM daily_bar WHERE code='600001.SH')
        """
    )
    market.execute(
        """
        UPDATE daily_bar
        SET adj_factor=1,adj_factor_clean=2
        WHERE code='600001.SH'
          AND trade_date=(SELECT max(trade_date) FROM daily_bar WHERE code='600001.SH')
        """
    )

    data = LimitLadderQueryService(market, coordinator=_FakeCoordinator()).query(
        trade_date, LimitLadderFilters(window=10, ignore_st=False)
    )
    software = next(
        stock
        for layer in data["layers"]
        for stock in layer["stocks"]
        if stock["code"] == "600001.SH"
    )
    assert software["window_return_pct"] == 0.0


def test_csv_export_escapes_spreadsheet_formulas(market):
    trade_date = _seed_ladder(market)
    snapshot_id = market.query_df(
        "SELECT current_snapshot_id FROM limit_ladder_snapshot_state WHERE trade_date=?",
        [trade_date],
    ).iloc[0]["current_snapshot_id"]
    market.execute(
        "UPDATE limit_ladder_snapshot_stock SET name='=cmd',industry_name=' @industry' "
        "WHERE snapshot_id=? AND code='600001.SH'",
        [snapshot_id],
    )
    market.execute(
        "UPDATE limit_ladder_snapshot_concept SET board_name='+concept' "
        "WHERE snapshot_id=? AND code='600001.SH'",
        [snapshot_id],
    )
    _, payload = LimitLadderQueryService(
        market, coordinator=_FakeCoordinator()
    ).export_csv(trade_date, LimitLadderFilters(ignore_st=False))
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    row = next(item for item in rows if item["代码"] == "600001.SH")
    assert row["名称"] == "'=cmd"
    assert row["快照行业"] == "' @industry"
    assert row["快照概念"].startswith("'+concept")


def test_missing_snapshot_uses_only_unified_first_load_entry(market):
    trade_date = date(2026, 8, 28)
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": [trade_date], "is_open": [True]})
    )
    coordinator = _FakeCoordinator()
    data = LimitLadderQueryService(market, coordinator=coordinator).query(
        trade_date, LimitLadderFilters()
    )
    assert data["business_code"] == "SNAPSHOT_PENDING"
    assert data["snapshot_status"] == "calculating"
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0][1]["source"] == "auto_first_load"


def test_orphaned_calculating_state_rebuilds_once_and_reuses_active_task(market):
    trade_date = date(2026, 8, 28)
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": [trade_date], "is_open": [True]})
    )
    market.execute(
        """
        INSERT INTO limit_ladder_snapshot_state (
            trade_date,status,current_snapshot_id,task_id,rule_version,updated_at
        ) VALUES (?, 'calculating', NULL, 'orphan-task', 'v1', current_timestamp)
        """,
        [trade_date],
    )

    class RecoveringRepository:
        active = None

        def get_active_for_date(self, selected_date):
            return self.active

    class RecoveringCoordinator(_FakeCoordinator):
        def __init__(self):
            super().__init__()
            self.repository = RecoveringRepository()

        def ensure_date_task(self, selected_date, **kwargs):
            result = super().ensure_date_task(selected_date, **kwargs)
            self.repository.active = {
                "command_id": result.command_id,
                "task_id": result.task_id,
                "status": result.status,
                "source": kwargs["source"],
            }
            return result

    coordinator = RecoveringCoordinator()
    service = LimitLadderQueryService(market, coordinator=coordinator)

    first = service.query(trade_date, LimitLadderFilters())
    second = service.query(trade_date, LimitLadderFilters())

    assert first["business_code"] == "SNAPSHOT_PENDING"
    assert first["task"]["task_id"] == "task-1"
    assert second["task"]["task_id"] == "task-1"
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0][1]["source"] == "auto_first_load"


def test_orphaned_recalculating_state_preserves_snapshot_and_rebuilds_refresh(market):
    trade_date = _seed_ladder(market)
    state = market.query_df(
        "SELECT current_snapshot_id FROM limit_ladder_snapshot_state WHERE trade_date=?",
        [trade_date],
    ).iloc[0]
    market.execute(
        "UPDATE limit_ladder_snapshot_state "
        "SET status='recalculating',task_id='orphan-task' WHERE trade_date=?",
        [trade_date],
    )
    coordinator = _FakeCoordinator()

    data = LimitLadderQueryService(market, coordinator=coordinator).query(
        trade_date, LimitLadderFilters(ignore_st=False)
    )

    assert data["business_code"] == "SNAPSHOT_STALE"
    assert data["current_snapshot_id"] == state["current_snapshot_id"]
    assert data["snapshot"]["snapshot_id"] == state["current_snapshot_id"]
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0][1]["source"] == "auto_invalid_refresh"


def test_invalid_snapshot_remains_readable_and_uses_refresh_entry(market):
    trade_date = _seed_ladder(market)
    LimitLadderSnapshotService(market).invalidate_dates([trade_date], reason="daily_bar_changed")
    coordinator = _FakeCoordinator()

    data = LimitLadderQueryService(market, coordinator=coordinator).query(
        trade_date, LimitLadderFilters(ignore_st=False)
    )

    assert data["business_code"] == "SNAPSHOT_STALE"
    assert data["snapshot_status"] == "recalculating"
    assert data["stored_snapshot_status"] == "invalid"
    assert data["snapshot"]["stock_count"] == 2
    assert data["coverage"]["reason_codes"] == []
    assert coordinator.calls[0][1]["source"] == "auto_invalid_refresh"


def test_dynamic_enrichment_failures_do_not_mask_published_snapshot(market, monkeypatch):
    trade_date = _seed_ladder(market)

    def fail_window(*args, **kwargs):
        raise RuntimeError("window unavailable")

    monkeypatch.setattr(LimitLadderCalculator, "calculate_window_metrics", fail_window)
    market.execute("DROP TABLE stock_board_correlation")
    data = LimitLadderQueryService(market, coordinator=_FakeCoordinator()).query(
        trade_date, LimitLadderFilters(ignore_st=False)
    )
    assert data["snapshot"]["stock_count"] == 2
    assert data["dynamic_window_status"] == "degraded"
    assert data["related_board_status"] == "degraded"
    assert data["related_concept_status"] == "degraded"
    assert sum(layer["stock_count"] for layer in data["layers"]) == 2


def test_dynamic_window_fallback_failure_still_returns_published_snapshot(market, monkeypatch):
    trade_date = _seed_ladder(market)

    def fail(*args, **kwargs):
        raise RuntimeError("window storage unavailable")

    monkeypatch.setattr(LimitLadderCalculator, "calculate_window_metrics", fail)
    monkeypatch.setattr(LimitLadderCalculator, "_calendar_through", fail)
    data = LimitLadderQueryService(market, coordinator=_FakeCoordinator()).query(
        trade_date, LimitLadderFilters(ignore_st=False)
    )
    assert data["snapshot"]["stock_count"] == 2
    assert data["dynamic_window_status"] == "degraded"
    assert data["requested_window_start_date"] is None
    assert data["requested_window_trade_days"] == 0


def test_non_trading_day_uses_date_only_nearest_trade_date(market):
    previous = date(2026, 8, 28)
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": [previous], "is_open": [True]})
    )
    data = LimitLadderQueryService(market, coordinator=_FakeCoordinator()).status(
        date(2026, 8, 30)
    )
    assert data["nearest_previous_trade_date"] == "2026-08-28"


@pytest.mark.parametrize(
    ("status", "snapshot_id", "business_code"),
    [
        ("calculating", None, "SNAPSHOT_PENDING"),
        ("recalculating", "snap-old", "SNAPSHOT_STALE"),
        ("invalid", None, "SNAPSHOT_NOT_READY"),
        ("failed", None, "SNAPSHOT_FAILED"),
        ("failed", "snap-old", "SNAPSHOT_STALE"),
    ],
)
def test_status_exposes_each_public_state(market, status, snapshot_id, business_code):
    trade_date = date(2026, 8, 28)
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": [trade_date], "is_open": [True]})
    )
    market.execute(
        """
        INSERT INTO limit_ladder_snapshot_state (
            trade_date,status,current_snapshot_id,rule_version,updated_at
        ) VALUES (?,?,?,?,current_timestamp)
        """,
        [trade_date, status, snapshot_id, "v1"],
    )
    data = LimitLadderQueryService(market, coordinator=_FakeCoordinator()).status(trade_date)
    assert data["snapshot_status"] == status
    assert data["business_code"] == business_code


def test_api_contract_has_200_400_and_precise_permission(monkeypatch):
    class _StubQuery:
        def query(self, trade_date, filters, **kwargs):
            return {
                "trade_date": trade_date.isoformat(),
                "window": filters.window,
                "boards": list(filters.boards),
            }

    monkeypatch.setattr(api_module, "LimitLadderQueryService", _StubQuery)
    app = FastAPI()
    app.include_router(api_module.router)
    for route in app.routes:
        for dependency in getattr(getattr(route, "dependant", None), "dependencies", []):
            call = getattr(dependency, "call", None)
            if getattr(call, "resource_code", None):
                app.dependency_overrides[call] = lambda: None
    client = TestClient(app)
    assert client.get("/api/limit-ladder/2026-08-28?window=10").status_code == 200
    assert client.get("/api/limit-ladder/not-a-date").status_code == 400
    assert client.get("/api/limit-ladder/2026-08-28?window=12").status_code == 400
    assert client.get("/api/limit-ladder/2026-08-28?boards=unknown").status_code == 400
    comma_boards = client.get("/api/limit-ladder/2026-08-28?boards=main,gem")
    assert comma_boards.status_code == 200
    assert comma_boards.json()["data"]["boards"] == ["main", "gem"]
    repeated_boards = client.get(
        "/api/limit-ladder/2026-08-28?boards=main&boards=star"
    )
    assert repeated_boards.status_code == 200
    assert repeated_boards.json()["data"]["boards"] == ["main", "star"]

    route = next(
        route for route in api_module.router.routes if route.path == "/api/limit-ladder/{trade_date}"
    )
    guard = next(dependency.call for dependency in route.dependant.dependencies)
    token = set_context(AuthContext(user_id="u", tenant_id="t", resources=frozenset()))
    try:
        with pytest.raises(ForbiddenError) as exc:
            guard()
        assert exc.value.http_status == 403
    finally:
        reset_context(token)


def test_recompute_route_keeps_system_only_permission_metadata():
    route = next(
        route
        for route in api_module.router.routes
        if route.path == "/api/limit-ladder/{trade_date}/recompute"
    )
    guard = next(dependency.call for dependency in route.dependant.dependencies)
    assert guard.resource_code == "limit-ladder:recompute"
    assert guard.require_system_perm is True
