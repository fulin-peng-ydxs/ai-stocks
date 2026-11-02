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
from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.services.stock_st_status import StockSTStatusFact, StockSTStatusService
from backend.storage.limit_ladder_task_repository import (
    LimitLadderTaskCommand,
    LimitLadderTaskRepository,
)
from backend.storage.repository import MarketRepository


@pytest.fixture(autouse=True)
def isolate_ladder_reconciliation_and_outbox(monkeypatch):
    """对账与审计只能消费当前用例创建的命令，不能收敛共享开发库真实任务。"""
    command_ids = set()
    create_requested = LimitLadderTaskRepository.create_requested

    def create(self, command):
        create_requested(self, command)
        command_ids.add(command.command_id)

    def active(self):
        return self.pg.query_df(
            "SELECT * FROM limit_ladder_task_ledger WHERE command_id=ANY(%s) "
            "AND status IN ('requested','running') ORDER BY created_at,command_id",
            [list(command_ids)],
        ).to_dict("records")

    def pending(self, *, limit=100):
        return self.pg.query_df(
            "SELECT * FROM limit_ladder_audit_outbox WHERE command_id=ANY(%s) "
            "AND status='pending' AND (next_retry_at IS NULL OR next_retry_at<=now()) "
            "ORDER BY created_at LIMIT %s", [list(command_ids), limit],
        ).to_dict("records")

    monkeypatch.setattr(LimitLadderTaskRepository, "create_requested", create)
    monkeypatch.setattr(LimitLadderTaskRepository, "list_active", active)
    monkeypatch.setattr(LimitLadderTaskRepository, "list_pending_outbox", pending)


class _FakeTasks:
    def __init__(self):
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def create(self, task_type: str, params: dict, **metadata) -> str:
        with self._lock:
            for index, call in enumerate(self.calls, 1):
                if metadata.get("trigger_event_id") == call.get("trigger_event_id"):
                    return f"fake-task-{index}"
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


def test_busy_request_survives_restart_and_dispatches_once_when_write_slot_frees(
    pg, market, monkeypatch,
):
    """真实创建入口检查写互斥，PG 请求持久化跨过孤儿时限，释放后只派发一次。"""
    repository = LimitLadderTaskRepository(pg)
    tasks = AsyncTaskService(market)
    monkeypatch.setattr(tasks, "_run", lambda *args: None)
    monkeypatch.setattr(tasks, "_audit_task", lambda **kwargs: None)
    trade_date = _trade_date()
    blocker = tasks.create("fix", {})
    command_ids = []
    audit = _FakeAudit()
    coordinator = LimitLadderTaskCoordinator(
        repository=repository, task_service=tasks, audit_repository=audit,
        user_repository=_FakeUsers(),
    )
    try:
        first = coordinator.ensure_date_task(trade_date, source="auto_first_load")
        command_ids.append(first.command_id)
        assert first.task_id is None and first.status == "requested"
        again = coordinator.ensure_date_task(trade_date, source="auto_first_load")
        assert again.reused and again.command_id == first.command_id
        assert repository.get(first.command_id)["last_error"] is None
        assert list(audit.events) == [f"{first.command_id}:requested"]
        # 隔离本次临时命令，禁止对账共享开发库中其它真实请求。
        monkeypatch.setattr(repository, "list_active", lambda: [
            row for cid in command_ids if (row := repository.get(cid))["status"]
            in {"requested", "running"}
        ])
        restarted = LimitLadderTaskCoordinator(
            repository=repository, task_service=tasks, audit_repository=audit,
            user_repository=_FakeUsers(),
        )
        future = datetime.now(UTC) + timedelta(hours=1)
        restarted.reconcile(startup_at=future, now=future)
        assert repository.get(first.command_id)["status"] == "requested"
        assert tasks._running_write() == (blocker, "fix")
        tasks._set(blocker, status="done")
        restarted.reconcile(now=future)
        restarted.reconcile(now=future)
        rows = market.query_df(
            "SELECT id,trigger_source FROM async_task WHERE trigger_event_id=?",
            [first.command_id],
        )
        assert len(rows) == 1 and rows.iloc[0]["trigger_source"] == "system"
        row = repository.get(first.command_id)
        assert row["status"] == "running" and row["task_id"] == rows.iloc[0]["id"]
        assert f"{first.command_id}:failed" not in audit.events
    finally:
        _cleanup(pg, command_ids)


def test_queued_request_reports_real_dispatch_error_as_failed(pg, market, monkeypatch):
    repository = LimitLadderTaskRepository(pg)
    tasks = AsyncTaskService(market)
    audit = _FakeAudit()
    coordinator = LimitLadderTaskCoordinator(
        repository=repository, task_service=tasks, audit_repository=audit,
        user_repository=_FakeUsers(),
    )
    command_id = f"pytest_ll_dispatch_{uuid4().hex}"
    try:
        repository.create_requested(LimitLadderTaskCommand(
            command_id=command_id, trade_date=_trade_date(), source="admin_recompute",
            actor_kind="user", actor_account="pg-admin", tenant_id="pytest-ladder",
            actor_user_id="pytest-admin", rule_version="test-v1",
        ))
        monkeypatch.setattr(repository, "list_active", lambda: [repository.get(command_id)])
        monkeypatch.setattr(tasks, "create", _FailingTasks().create)
        coordinator.reconcile()
        row = repository.get(command_id)
        assert row["status"] == "failed"
        assert "forced DuckDB task creation failure" in row["last_error"]
        assert f"{command_id}:failed" in audit.events
    finally:
        _cleanup(pg, [command_id])


def test_waiting_expires_without_late_execution_and_explicit_retry_gets_new_command(
    pg, market, monkeypatch,
):
    from backend.services.limit_ladder_task_policy import QUEUE_TIMEOUT_REASON

    repository = LimitLadderTaskRepository(pg)
    tasks = AsyncTaskService(market)
    monkeypatch.setattr(tasks, "_run", lambda *args: None)
    monkeypatch.setattr(tasks, "_audit_task", lambda **kwargs: None)
    blocker = tasks.create("fix", {})
    coordinator = LimitLadderTaskCoordinator(
        repository=repository, task_service=tasks, audit_repository=_FakeAudit(),
        user_repository=_FakeUsers(),
    )
    command_ids = []
    trade_date = _trade_date()
    try:
        first = coordinator.ensure_date_task(trade_date, source="auto_first_load")
        command_ids.append(first.command_id)
        pg.execute(
            "UPDATE limit_ladder_task_ledger SET created_at=%s WHERE command_id=%s",
            [datetime.now(UTC) - timedelta(days=2), first.command_id],
        )
        monkeypatch.setattr(repository, "list_active", lambda: [
            row for cid in command_ids if (row := repository.get(cid))["status"]
            in {"requested", "running"}
        ])
        coordinator.reconcile()
        expired = repository.get(first.command_id)
        assert expired["status"] == "failed"
        assert expired["last_error"] == QUEUE_TIMEOUT_REASON
        assert repository.get_active_for_date(trade_date) is None
        tasks._set(blocker, status="done")
        coordinator.reconcile()
        assert market.query_df(
            "SELECT id FROM async_task WHERE trigger_event_id=?", [first.command_id],
        ).empty
        retried = coordinator.ensure_date_task(trade_date, source="auto_first_load")
        command_ids.append(retried.command_id)
        assert retried.command_id != first.command_id and retried.task_id is not None
    finally:
        _cleanup(pg, command_ids)


def test_ensure_date_task_replaces_terminal_duck_task_in_active_pg_slot(pg, market):
    repository = LimitLadderTaskRepository(pg)
    trade_date = _trade_date()
    old_command_id = f"pytest_ll_terminal_{uuid4().hex}"
    old_task_id = f"task_limit_ladder_recompute_{uuid4().hex}"
    command_ids = [old_command_id]

    class PersistedTasks(_FakeTasks):
        def __init__(self):
            super().__init__()
            self.c = market

    try:
        repository.create_requested(LimitLadderTaskCommand(
            command_id=old_command_id,
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
                old_task_id,
                "limit_ladder_recompute",
                "{}",
                "interrupted",
                1.0,
                "服务重启中断",
                old_command_id,
                now,
                now,
            ],
        )
        tasks = PersistedTasks()
        result = LimitLadderTaskCoordinator(
            repository=repository,
            task_service=tasks,
            audit_repository=_FakeAudit(),
            user_repository=_FakeUsers(),
        ).ensure_date_task(trade_date, source="auto_first_load")
        command_ids.append(result.command_id)

        assert result.command_id != old_command_id
        assert result.reused is False
        assert repository.get(old_command_id)["status"] == "interrupted"
        assert len(tasks.calls) == 1
    finally:
        _cleanup(pg, command_ids)


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
        market.execute(
            """
            INSERT INTO limit_ladder_snapshot_state (
                trade_date,status,current_snapshot_id,task_id,rule_version,updated_at
            ) VALUES (?, 'calculating', NULL, ?, 'test-v1', current_timestamp)
            """,
            [trade_date, task_id],
        )
        tasks = AsyncTaskService(market)
        restart = tasks.reconcile()
        assert restart["interrupted"] == 1
        assert restart["limit_ladder_states_recovered"] == 1
        snapshot_state = market.query_df(
            "SELECT status,current_snapshot_id,failure_summary "
            "FROM limit_ladder_snapshot_state WHERE trade_date=?",
            [trade_date],
        ).iloc[0]
        assert snapshot_state["status"] == "failed"
        assert pd.isna(snapshot_state["current_snapshot_id"])
        assert "服务重启中断" in snapshot_state["failure_summary"]
        # 模拟异步任务恢复与 PG 对账之间再次出现的跨存储状态漂移；协调器必须兜底收敛。
        market.execute(
            "UPDATE limit_ladder_snapshot_state "
            "SET status='calculating',failure_summary=NULL WHERE trade_date=?",
            [trade_date],
        )
        audit = _FakeAudit()
        result = LimitLadderTaskCoordinator(
            repository=repository,
            task_service=tasks,
            audit_repository=audit,
            user_repository=_FakeUsers(),
        ).reconcile(startup_at=datetime.now(UTC))
        row = repository.get(command_id)
        assert result["locked"] is True
        assert result["snapshot_recovered"] == 1
        assert row is not None and row["status"] == "interrupted"
        assert row["task_id"] == task_id
        assert set(audit.events) == {
            f"{command_id}:requested",
            f"{command_id}:interrupted",
        }
        assert market.query_df(
            "SELECT status FROM limit_ladder_snapshot_state WHERE trade_date=?",
            [trade_date],
        ).iloc[0]["status"] == "failed"
    finally:
        _cleanup(pg, [command_id])


def test_restart_reconciliation_preserves_last_snapshot_pointer(market):
    trade_date = _trade_date()
    task_id = f"task_limit_ladder_recompute_{uuid4().hex}"
    now = datetime.now(UTC)
    market.execute(
        "INSERT INTO async_task "
        "(id,task_type,params,status,progress,message,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [task_id, "limit_ladder_recompute", "{}", "running", 0.5, "running", now, now],
    )
    market.execute(
        """
        INSERT INTO limit_ladder_snapshot_state (
            trade_date,status,current_snapshot_id,task_id,rule_version,updated_at
        ) VALUES (?, 'recalculating', 'snap-old', ?, 'test-v1', current_timestamp)
        """,
        [trade_date, task_id],
    )

    result = AsyncTaskService(market).reconcile()

    state = market.query_df(
        "SELECT status,current_snapshot_id,task_id,failure_summary "
        "FROM limit_ladder_snapshot_state WHERE trade_date=?",
        [trade_date],
    ).iloc[0]
    assert result["limit_ladder_states_recovered"] == 1
    assert state["status"] == "failed"
    assert state["current_snapshot_id"] == "snap-old"
    assert state["task_id"] == task_id
    assert "服务重启中断" in state["failure_summary"]


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
    StockSTStatusService(market).upsert_facts([
        StockSTStatusFact(
            code="600001.SH",
            trade_date=trade_date,
            status=PointInTimeSTStatus(
                is_st=False,
                source="test_fixture",
                source_ref="test_limit_ladder_t5",
                quality=STStatusQuality.ACCURATE,
            ),
        )
    ], change_reason="test_fixture", captured_at=datetime.now(UTC))
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
            if fields["status"] == "succeeded":
                raise RuntimeError("temporary pg failure")
            return True

    monkeypatch.setattr(
        "backend.services.limit_ladder_task_coordinator.LimitLadderTaskCoordinator",
        FakeCoordinator,
    )
    phases: list[dict] = []
    context = SimpleNamespace(
        tid="task-handler",
        svc=SimpleNamespace(c=object(), market=market),
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
    assert [phase["phase_done"] for phase in phases] == [0, 1, 2, 3]
    assert phases[-1]["phase_done"] == 3


def test_reconcile_maps_done_task_from_snapshot_outcome():
    from backend.services.limit_ladder_task_coordinator import LimitLadderTaskCoordinator

    assert LimitLadderTaskCoordinator._duck_status({
        "status": "done",
        "result": {"snapshot_status": "valid"},
    }) == "succeeded"
    assert LimitLadderTaskCoordinator._duck_status({
        "status": "done",
        "result": {"ok": False, "snapshot_status": "invalid"},
    }) == "failed"


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
