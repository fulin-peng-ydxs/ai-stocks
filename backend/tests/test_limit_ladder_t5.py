"""T5: date-task coordination, restart reconciliation and task-center contracts."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from backend.auth.context import AuthContext
from backend.scheduler.scheduler import SCHEDULABLE_TASK_TYPES
from backend.services import async_task as async_task_module
from backend.services.async_task import TASK_CAPABILITIES, TASK_TYPES, AsyncTaskService
from backend.services.limit_ladder_task_coordinator import LimitLadderTaskCoordinator
from backend.storage.limit_ladder_task_repository import (
    LimitLadderTaskCommand,
    LimitLadderTaskRepository,
)
from backend.storage.repository import MarketRepository


class _FakeTasks:
    def __init__(self):
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def create(self, task_type: str, params: dict, **metadata) -> str:
        with self._lock:
            self.calls.append({"task_type": task_type, "params": params, **metadata})
            return f"fake-task-{len(self.calls)}"


class _FailingTasks:
    def create(self, *args, **kwargs) -> str:
        raise RuntimeError("forced DuckDB task creation failure")


class _FakeAudit:
    def __init__(self):
        self.events: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record(self, **event) -> str:
        key = str(event["source_event_key"])
        with self._lock:
            self.events.setdefault(key, event)
        return f"audit-{key}"


class _FakeUsers:
    def get_by_id(self, user_id: str) -> dict:
        return {"id": user_id, "tenant_id": "pytest-ladder", "account": "pg-admin"}


def _trade_date() -> date:
    suffix = uuid4().hex
    return date(
        2200 + int(suffix[:2], 16) % 100,
        1 + int(suffix[2:4], 16) % 12,
        1 + int(suffix[4:6], 16) % 28,
    )


def _cleanup(pg, command_ids: list[str]) -> None:
    if not command_ids:
        return
    keys = [f"{command_id}:{status}" for command_id in command_ids for status in (
        "requested", "running", "succeeded", "failed", "interrupted",
    )]
    pg.execute("DELETE FROM audit_log WHERE source_event_key = ANY(%s)", [keys])
    pg.execute(
        "DELETE FROM limit_ladder_audit_outbox WHERE command_id = ANY(%s)",
        [command_ids],
    )
    pg.execute(
        "DELETE FROM limit_ladder_task_ledger WHERE command_id = ANY(%s)",
        [command_ids],
    )


@pytest.mark.parametrize(
    ("first_source", "second_source"),
    [
        ("auto_first_load", "auto_first_load"),
        ("admin_recompute", "admin_recompute"),
        ("auto_first_load", "admin_recompute"),
        ("admin_recompute", "auto_first_load"),
    ],
)
def test_all_source_orderings_share_one_active_date_task(pg, first_source, second_source):
    repository = LimitLadderTaskRepository(pg)
    tasks = _FakeTasks()
    audit = _FakeAudit()
    coordinator = LimitLadderTaskCoordinator(
        repository=repository,
        task_service=tasks,
        audit_repository=audit,
        user_repository=_FakeUsers(),
    )
    trade_date = _trade_date()
    auth = AuthContext(
        user_id="pytest-admin",
        tenant_id="pytest-ladder",
        is_system=True,
    )
    barrier = threading.Barrier(2)

    def ensure(source):
        barrier.wait()
        return coordinator.ensure_date_task(
            trade_date,
            source=source,
            auth_context=auth if source == "admin_recompute" else None,
        )

    command_ids: list[str] = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(ensure, (first_source, second_source)))
        command_ids = list({result.command_id for result in results})
        assert len(command_ids) == 1
        assert sum(result.reused for result in results) == 1
        assert len(tasks.calls) == 1
        assert tasks.calls[0]["task_type"] == "limit_ladder_recompute"
        assert tasks.calls[0]["trigger_event_id"] == command_ids[0]
        active = repository.get_active_for_date(trade_date)
        assert active is not None and active["command_id"] == command_ids[0]
        assert list(audit.events) == [f"{command_ids[0]}:requested"]
    finally:
        if not command_ids:
            rows = pg.query_df(
                "SELECT command_id FROM limit_ladder_task_ledger WHERE trade_date=%s",
                [trade_date],
            )
            command_ids = rows["command_id"].astype(str).tolist()
        _cleanup(pg, command_ids)


def test_task_creation_failure_releases_date_for_next_command(pg):
    repository = LimitLadderTaskRepository(pg)
    trade_date = _trade_date()
    failed_id = successful_id = None
    try:
        failed = LimitLadderTaskCoordinator(
            repository=repository,
            task_service=_FailingTasks(),
            audit_repository=_FakeAudit(),
            user_repository=_FakeUsers(),
        )
        with pytest.raises(RuntimeError, match="forced DuckDB task creation failure"):
            failed.ensure_date_task(trade_date, source="auto_first_load")
        failed_row = pg.query_df(
            "SELECT command_id,status FROM limit_ladder_task_ledger WHERE trade_date=%s",
            [trade_date],
        ).iloc[0]
        failed_id = str(failed_row["command_id"])
        assert failed_row["status"] == "failed"

        successful = LimitLadderTaskCoordinator(
            repository=repository,
            task_service=_FakeTasks(),
            audit_repository=_FakeAudit(),
            user_repository=_FakeUsers(),
        ).ensure_date_task(trade_date, source="auto_invalid_refresh")
        successful_id = successful.command_id
        assert successful_id != failed_id
    finally:
        _cleanup(pg, [item for item in (failed_id, successful_id) if item])


def test_admin_identity_and_request_metadata_are_server_captured(pg, monkeypatch):
    repository = LimitLadderTaskRepository(pg)
    trade_date = _trade_date()
    command_id = None
    request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/limit-ladder/recompute"),
        client=SimpleNamespace(host="socket-ip"),
        headers={"x-forwarded-for": "spoofed-ip"},
    )
    monkeypatch.setattr(
        "backend.services.limit_ladder_task_coordinator.trusted_client_ip",
        lambda incoming: "trusted-server-ip" if incoming is request else None,
    )
    try:
        result = LimitLadderTaskCoordinator(
            repository=repository,
            task_service=_FakeTasks(),
            audit_repository=_FakeAudit(),
            user_repository=_FakeUsers(),
        ).ensure_date_task(
            trade_date,
            source="admin_recompute",
            auth_context=AuthContext(
                user_id="pytest-admin",
                tenant_id="pytest-ladder",
                is_system=True,
            ),
            request=request,
        )
        command_id = result.command_id
        row = repository.get(command_id)
        assert row is not None
        assert row["actor_kind"] == "user"
        assert row["actor_user_id"] == "pytest-admin"
        assert row["actor_account"] == "pg-admin"
        assert row["request_ip"] == "trusted-server-ip"
        assert row["request_method"] == "POST"
        assert row["request_path"] == "/api/limit-ladder/recompute"
        assert len(str(row["request_id"])) == 32
    finally:
        _cleanup(pg, [command_id] if command_id else [])


def test_outbox_replays_admin_and_system_identity_to_audit_log(pg, monkeypatch):
    repository = LimitLadderTaskRepository(pg)
    command_ids: list[str] = []
    request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/limit-ladder/recompute"),
        client=SimpleNamespace(host="server-ip"),
        headers={},
    )
    monkeypatch.setattr(
        "backend.services.limit_ladder_task_coordinator.trusted_client_ip",
        lambda incoming: incoming.client.host,
    )
    coordinator = LimitLadderTaskCoordinator(
        repository=repository,
        task_service=_FakeTasks(),
        user_repository=_FakeUsers(),
    )
    try:
        admin = coordinator.ensure_date_task(
            _trade_date(),
            source="admin_recompute",
            auth_context=AuthContext(
                user_id="pytest-admin",
                tenant_id="pytest-ladder",
                is_system=True,
            ),
            request=request,
        )
        command_ids.append(admin.command_id)
        assert coordinator.mark_running(admin.command_id, "task-admin")
        assert coordinator.mark_terminal(
            admin.command_id,
            status="succeeded",
            task_id="task-admin",
            summary={"snapshot_status": "valid"},
        )
        system = coordinator.ensure_date_task(_trade_date(), source="auto_first_load")
        command_ids.append(system.command_id)

        rows = pg.query_df(
            "SELECT source_event_key,tenant_id,actor_user_id,actor_account,ip,method,path,context "
            "FROM audit_log WHERE source_event_key = ANY(%s) ORDER BY source_event_key",
            [[
                f"{admin.command_id}:requested",
                f"{admin.command_id}:running",
                f"{admin.command_id}:succeeded",
                f"{system.command_id}:requested",
            ]],
        )
        assert len(rows) == 4
        assert rows["source_event_key"].is_unique
        admin_rows = rows[rows["source_event_key"].str.startswith(admin.command_id)]
        assert set(admin_rows["tenant_id"]) == {"pytest-ladder"}
        assert set(admin_rows["actor_user_id"]) == {"pytest-admin"}
        assert set(admin_rows["actor_account"]) == {"pg-admin"}
        assert set(admin_rows["ip"]) == {"server-ip"}
        assert set(admin_rows["method"]) == {"POST"}
        assert set(admin_rows["path"]) == {"/api/limit-ladder/recompute"}
        system_row = rows[rows["source_event_key"] == f"{system.command_id}:requested"].iloc[0]
        assert system_row["actor_account"] == "system:limit-ladder"
        assert pd.isna(system_row["tenant_id"])
        assert pd.isna(system_row["actor_user_id"])
    finally:
        _cleanup(pg, command_ids)


def test_restart_reconciliation_maps_duck_task_to_interrupted(pg, market):
    repository = LimitLadderTaskRepository(pg)
    trade_date = _trade_date()
    command_id = f"pytest_ll_restart_{uuid4().hex}"
    task_id = f"task_limit_ladder_recompute_{uuid4().hex}"
    try:
        repository.create_requested(LimitLadderTaskCommand(
            command_id=command_id,
            trade_date=trade_date,
            source="auto_first_load",
            actor_kind="system",
            actor_account="system:limit-ladder",
            rule_version="test-v1",
        ))
        now = datetime.now(UTC)
        market.execute(
            "INSERT INTO async_task "
            "(id,task_type,params,status,progress,message,trigger_event_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                task_id,
                "limit_ladder_recompute",
                "{}",
                "running",
                0.5,
                "running",
                command_id,
                now,
                now,
            ],
        )
        tasks = AsyncTaskService(market)
        assert tasks.reconcile()["interrupted"] == 1
        audit = _FakeAudit()
        result = LimitLadderTaskCoordinator(
            repository=repository,
            task_service=tasks,
            audit_repository=audit,
            user_repository=_FakeUsers(),
        ).reconcile(startup_at=datetime.now(UTC))
        row = repository.get(command_id)
        assert result["locked"] is True
        assert row is not None and row["status"] == "interrupted"
        assert row["task_id"] == task_id
        assert set(audit.events) == {
            f"{command_id}:requested",
            f"{command_id}:interrupted",
        }
    finally:
        _cleanup(pg, [command_id])


def test_limit_ladder_handler_materializes_and_closes_pg_command(market, monkeypatch):
    trade_date = date(2026, 8, 28)
    days = [trade_date - timedelta(days=offset) for offset in range(4, -1, -1)]
    repository = MarketRepository(market)
    repository.upsert_trade_calendar(pd.DataFrame({"trade_date": days, "is_open": True}))
    repository.upsert_stock_basic(pd.DataFrame([{
        "code": "600001.SH",
        "name": "测试股票",
        "board": "主板",
        "list_date": date(2020, 1, 1),
        "industry": "软件",
        "price_limit_pct": 0.10,
    }]))
    repository.upsert_daily_bar(pd.DataFrame([{
        "code": "600001.SH",
        "trade_date": trade_date,
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "pre_close": 10.0,
        "volume": 100,
        "amount": 1000.0,
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
        "is_st": False,
        "is_suspended": False,
    }]))
    transitions: list[tuple[str, dict]] = []

    class FakeCoordinator:
        repository = SimpleNamespace(get=lambda command_id: {
            "command_id": command_id,
            "trade_date": trade_date,
        })

        def __init__(self, **kwargs):
            pass

        def mark_running(self, command_id, task_id):
            transitions.append(("running", {"command_id": command_id, "task_id": task_id}))
            return True

        def mark_terminal(self, command_id, **fields):
            transitions.append((fields["status"], {"command_id": command_id, **fields}))
            return True

    monkeypatch.setattr(
        "backend.services.limit_ladder_task_coordinator.LimitLadderTaskCoordinator",
        FakeCoordinator,
    )
    phases: list[dict] = []
    context = SimpleNamespace(
        tid="task-handler",
        svc=SimpleNamespace(c=market),
        set_phase=lambda phase, **data: phases.append({"phase": phase, **data}),
        log=lambda *args, **kwargs: None,
        progress=lambda *args, **kwargs: None,
    )
    result = async_task_module._h_limit_ladder_recompute(
        {"command_id": "command-handler", "trade_date": trade_date.isoformat()},
        context,
    )
    assert result["snapshot_status"] == "valid"
    assert [status for status, _ in transitions] == ["running", "succeeded"]
    assert transitions[-1][1]["summary"]["coverage"]["reason_codes"] == []
    assert phases[-1]["phase_done"] == 3


def test_limit_ladder_is_internal_non_resumable_task_type():
    assert "limit_ladder_recompute" in TASK_TYPES
    assert TASK_CAPABILITIES["limit_ladder_recompute"] == {
        "can_cancel": False,
        "can_resume": False,
        "cancel_mode": "none",
        "resume_granularity": None,
        "cancel_message": "单日快照采用原子切换，不支持中途终止或续跑",
    }
    assert "limit_ladder_recompute" not in SCHEDULABLE_TASK_TYPES
