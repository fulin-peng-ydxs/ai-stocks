"""Explicit result-maintenance task contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES, ScheduledJobService
from backend.services.async_task import (
    TASK_TYPES,
    WRITE_TASK_TYPES,
    AsyncTaskService,
    _h_limit_ladder_invalidate,
)
from backend.services.result_maintenance import (
    normalize_ladder_invalidation_params,
    normalize_score_invalidation_params,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market(tmp_path):
    with DuckDBClient(db_path=tmp_path / "result-maintenance.duckdb") as client:
        init_db(client)
        for trade_date in (date(2026, 8, 27), date(2026, 8, 28)):
            client.execute(
                "INSERT INTO trade_calendar (trade_date,is_open) VALUES (?,true)",
                [trade_date],
            )
        yield client


class _Ctx:
    def __init__(self, client):
        self.svc = SimpleNamespace(c=client)
        self.logs: list[str] = []

    def log(self, message, level="info"):
        self.logs.append(message)

    def progress(self, *_args, **_kwargs):
        return None


def test_three_result_actions_are_schedulable_without_default_jobs(market):
    assert "recompute" in SCHEDULABLE_TASK_TYPES
    assert "stock_board_correlation" in SCHEDULABLE_TASK_TYPES
    assert "limit_ladder_invalidate" in SCHEDULABLE_TASK_TYPES
    assert "limit_ladder_invalidate" in TASK_TYPES
    assert "limit_ladder_invalidate" in WRITE_TASK_TYPES
    jobs = ScheduledJobService(market).list()
    assert not any(job["task_type"] in {
        "recompute", "stock_board_correlation", "limit_ladder_invalidate",
    } for job in jobs)

    created = ScheduledJobService(market).create(
        name="天梯固定日失效",
        task_type="limit_ladder_invalidate",
        params={"target_mode": "fixed", "trade_date": "2026-08-28"},
        freq_type="daily",
        freq_config={"time": "18:30"},
        trading_day_only=True,
        enabled=False,
    )
    assert created["params"] == {
        "target_mode": "fixed", "trade_date": "2026-08-28",
    }
    with pytest.raises(ValueError, match="目标范围非法"):
        ScheduledJobService(market).create(
            name="非法天梯全量失效",
            task_type="limit_ladder_invalidate",
            params={"target_mode": "all"},
            freq_type="daily",
            freq_config={"time": "18:30"},
            trading_day_only=True,
            enabled=False,
        )


def test_result_target_params_are_explicit_and_strict():
    assert normalize_score_invalidation_params({}) == {
        "target_mode": "latest", "trade_date": None,
    }
    with pytest.raises(ValueError, match="目标范围非法"):
        normalize_ladder_invalidation_params({"target_mode": "all"})
    assert normalize_score_invalidation_params({
        "target_mode": "fixed", "trade_date": "2026-08-28",
    }) == {"target_mode": "fixed", "trade_date": "2026-08-28"}
    with pytest.raises(ValueError, match="固定日期不能为空"):
        normalize_ladder_invalidation_params({"target_mode": "fixed"})
    with pytest.raises(ValueError, match="不支持参数"):
        normalize_score_invalidation_params({"source_task_output": True})


def test_fixed_result_target_must_be_registered_open_trade_date(market):
    from backend.services.result_maintenance import resolve_target_date

    with pytest.raises(ValueError, match="不是已登记的交易日"):
        resolve_target_date(
            {"target_mode": "fixed", "trade_date": "2026-08-29"},
            market,
        )


def test_ladder_invalidation_task_only_marks_existing_snapshots_invalid(market):
    first = date(2026, 8, 27)
    second = date(2026, 8, 28)
    for trade_date, snapshot_id in ((first, "snap-1"), (second, "snap-2")):
        market.execute(
            "INSERT INTO limit_ladder_snapshot_state "
            "(trade_date,status,current_snapshot_id,rule_version,updated_at) "
            "VALUES (?,'valid',?,'v1',current_timestamp)",
            [trade_date, snapshot_id],
        )

    result = _h_limit_ladder_invalidate(
        {"target_mode": "fixed", "trade_date": first.isoformat()},
        _Ctx(market),
    )

    assert result["invalidated_count"] == 2
    states = market.query_df(
        "SELECT status,current_snapshot_id,invalid_reason "
        "FROM limit_ladder_snapshot_state ORDER BY trade_date"
    ).to_dict("records")
    assert [row["status"] for row in states] == ["invalid", "invalid"]
    assert [row["current_snapshot_id"] for row in states] == ["snap-1", "snap-2"]
    assert all(row["invalid_reason"] == "explicit_result_maintenance" for row in states)


def test_async_create_normalizes_result_maintenance_params(market, monkeypatch):
    monkeypatch.setattr(AsyncTaskService, "_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(AsyncTaskService, "_audit_task", staticmethod(lambda **kwargs: None))
    task_id = AsyncTaskService(market).create("limit_ladder_invalidate", {})
    assert AsyncTaskService(market).get(task_id)["params"] == {
        "target_mode": "latest", "trade_date": None,
    }
