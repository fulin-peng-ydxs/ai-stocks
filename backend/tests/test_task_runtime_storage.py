from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from backend.common.exceptions import ConfigError, ConflictError, StorageError
from backend.services.async_task import ConcurrentTaskError
from backend.storage import task_runtime, task_runtime_migration
from backend.storage.task_runtime import (
    TASK_RUNTIME_MIGRATION_MARKER,
    PostgresTaskRuntimeClient,
    _qmark_to_percent,
    runtime_json_param,
)
from backend.storage.task_runtime_migration import _json_value, _to_duck_time, _to_utc


def test_qmark_conversion_preserves_quoted_question_marks():
    sql = "SELECT '?' AS literal, \"?\" AS ident FROM task WHERE id=? AND note='it''s ?'"
    assert _qmark_to_percent(sql) == (
        "SELECT '?' AS literal, \"?\" AS ident FROM task WHERE id=%s AND note='it''s ?'"
    )


def test_duck_naive_timestamp_round_trips_as_shanghai_time():
    local = datetime(2026, 9, 9, 8, 30)  # noqa: DTZ001 - 模拟 DuckDB 历史 naive 时间
    utc_value = _to_utc(local)
    assert utc_value.tzinfo is UTC
    assert utc_value.hour == 0
    assert _to_duck_time(utc_value) == local


def test_migration_json_validation_rejects_scalar_and_invalid_json():
    assert _json_value('{"ok": true}', table="async_task", column="params") == {"ok": True}
    with pytest.raises(TypeError):
        _json_value("1", table="async_task", column="params")
    with pytest.raises(ValueError):
        _json_value("{broken", table="async_task", column="params")


class _CapturePg:
    def __init__(self):
        self.values = []

    def execute(self, _sql, params):
        self.values = params
        return 1


def test_runtime_json_is_typed_without_misclassifying_json_looking_text():
    pg = _CapturePg()
    runtime = PostgresTaskRuntimeClient(pg)  # type: ignore[arg-type]
    runtime.execute(
        "SELECT ?, ?",
        ['{"this_is":"a log message"}', runtime_json_param(runtime, {"real": "json"})],
    )
    assert pg.values[0] == '{"this_is":"a log message"}'
    assert pg.values[1].obj == {"real": "json"}


def test_runtime_json_normalizes_non_json_scalars_for_postgres():
    runtime = PostgresTaskRuntimeClient(_CapturePg())  # type: ignore[arg-type]
    value = runtime_json_param(runtime, {"at": datetime(2026, 9, 9, 8, 30)})  # noqa: DTZ001
    assert value == {"at": "2026-09-09 08:30:00"}


def test_concurrent_task_error_crosses_postgres_transaction_boundary():
    assert issubclass(ConcurrentTaskError, ConflictError)


def test_queue_deadline_is_absolute_and_inclusive():
    from backend.config.settings import LimitLadderConfig
    from backend.services.limit_ladder_task_policy import (
        LimitLadderQueueTimeoutError, check_queue_deadline,
    )

    deadline = datetime.now(UTC)
    check_queue_deadline(deadline.isoformat(), now=deadline - timedelta(microseconds=1))
    with pytest.raises(LimitLadderQueueTimeoutError):
        check_queue_deadline(deadline.isoformat(), now=deadline)
    assert LimitLadderConfig().queue_timeout_sec == 900
    with pytest.raises(ValueError):
        LimitLadderConfig(queue_timeout_sec=0)


def test_writer_admission_honors_oldest_ladder_and_releases_expired_queue(pg, market, monkeypatch):
    """真实 PG SQL 与创建事务，临时表遮蔽运行表，不能改动共享任务。"""
    from backend.services.async_task import AsyncTaskService
    from backend.services.limit_ladder_task_policy import LimitLadderQueueTimeoutError

    runtime = PostgresTaskRuntimeClient(pg)
    tasks = AsyncTaskService(runtime, market_client=market)
    monkeypatch.setattr(tasks, "_run", lambda *args: None)
    monkeypatch.setattr(tasks, "_audit_task", lambda **kwargs: None)
    now = datetime.now(UTC)
    with runtime.transaction():
        runtime.execute("CREATE TEMP TABLE async_task ON COMMIT DROP AS SELECT * FROM public.async_task WITH NO DATA")
        runtime.execute("CREATE TEMP TABLE limit_ladder_task_ledger ON COMMIT DROP AS SELECT * FROM public.limit_ladder_task_ledger WITH NO DATA")
        resumable = tasks.create("fix", {})
        tasks._set(resumable, status="interrupted")
        for command_id, created in [("oldest", now - timedelta(minutes=2)), ("newer", now - timedelta(minutes=1)), ("expired", now - timedelta(days=2))]:
            runtime.execute(
                "INSERT INTO limit_ladder_task_ledger (command_id,status,created_at) VALUES (?,?,?)",
                [command_id, "requested", created],
            )
        with pytest.raises(ConcurrentTaskError) as conflict:
            tasks.create("fix", {})
        assert conflict.value.queued and conflict.value.running_id == "oldest"
        assert conflict.value.conflict_details == {"running_id": None, "waiting_command_id": "oldest"}
        with pytest.raises(ConcurrentTaskError):
            tasks.resume(resumable)
        # 只写 PG 的任务仍可并行，不会因为天梯等待而被阻塞。
        assert tasks.create("audit_cleanup", {})
        with pytest.raises(ConcurrentTaskError):
            tasks.create("limit_ladder_recompute", {}, trigger_event_id="newer")
        deadline = (now + timedelta(minutes=10)).isoformat()
        first = tasks.create("limit_ladder_recompute", {"queue_deadline_at": deadline}, trigger_event_id="oldest")
        # 已按时接受的命令先走幂等，不会因一次迟到重放被误判超时。
        assert tasks.create("limit_ladder_recompute", {"queue_deadline_at": now.isoformat()}, trigger_event_id="oldest") == first
        tasks._set(first, status="done")
        second = tasks.create("limit_ladder_recompute", {"queue_deadline_at": deadline}, trigger_event_id="newer")
        tasks._set(second, status="done")
        with pytest.raises(LimitLadderQueueTimeoutError):
            tasks.create("limit_ladder_recompute", {"queue_deadline_at": now.isoformat()}, trigger_event_id="expired")
        # 已派发请求不再预留名额；未清理的过期账本也不能卡住其它写任务。
        assert tasks.create("fix", {})


class _MarkerPg:
    def __init__(self, applied: bool):
        self.applied = applied

    def query_df(self, _sql, _params):
        return pd.DataFrame(
            [{"marker": TASK_RUNTIME_MIGRATION_MARKER}] if self.applied else [],
            columns=["marker"],
        )


class _UnavailableMarkerPg:
    @staticmethod
    def query_df(_sql, _params):
        raise StorageError("postgres unavailable")


def test_auto_backend_uses_committed_marker(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "auto")
    monkeypatch.setattr(task_runtime, "get_pg_client", lambda: _MarkerPg(True))
    task_runtime.reset_task_runtime_backend_cache()
    assert task_runtime.task_runtime_backend(refresh=True) == "postgres"
    task_runtime.reset_task_runtime_backend_cache()


def test_explicit_postgres_fails_closed_without_marker(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "postgres")
    monkeypatch.setattr(task_runtime, "get_pg_client", lambda: _MarkerPg(False))
    task_runtime.reset_task_runtime_backend_cache()
    with pytest.raises(ConfigError, match="缺少标记"):
        task_runtime.task_runtime_backend(refresh=True)
    task_runtime.reset_task_runtime_backend_cache()


def test_explicit_duckdb_fails_closed_while_postgres_marker_is_applied(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "duckdb")
    monkeypatch.setattr(task_runtime, "get_pg_client", lambda: _MarkerPg(True))
    task_runtime.reset_task_runtime_backend_cache()
    with pytest.raises(ConfigError, match="拒绝切回.*DuckDB"):
        task_runtime.task_runtime_backend(refresh=True)
    task_runtime.reset_task_runtime_backend_cache()


def test_explicit_duckdb_is_allowed_before_migration(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "duckdb")
    monkeypatch.setattr(task_runtime, "get_pg_client", lambda: _MarkerPg(False))
    task_runtime.reset_task_runtime_backend_cache()
    assert task_runtime.task_runtime_backend(refresh=True) == "duckdb"
    task_runtime.reset_task_runtime_backend_cache()


def test_auto_backend_fails_closed_when_marker_cannot_be_read(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "auto")
    monkeypatch.setattr(task_runtime, "get_pg_client", lambda: _UnavailableMarkerPg())
    task_runtime.reset_task_runtime_backend_cache()
    with pytest.raises(ConfigError, match="拒绝.*猜测切换"):
        task_runtime.task_runtime_backend(refresh=True)
    task_runtime.reset_task_runtime_backend_cache()


def test_migration_status_does_not_initialize_duckdb(monkeypatch):
    frames = {
        table: pd.DataFrame(columns=columns)
        for table, columns in task_runtime_migration._TABLE_COLUMNS.items()
    }
    monkeypatch.setattr(task_runtime_migration, "_duck_frames", lambda _duck: frames)
    monkeypatch.setattr(task_runtime_migration, "_validate_frames", lambda _frames: None)
    monkeypatch.setattr(
        task_runtime_migration,
        "_pg_counts",
        lambda _pg: {table: 0 for table in frames},
    )
    monkeypatch.setattr(
        task_runtime_migration,
        "init_db",
        lambda _duck: pytest.fail("status/dry-run 不得执行 DuckDB 初始化"),
    )

    class MarkerlessPg:
        @staticmethod
        def query_df(_sql, _params=None):
            return pd.DataFrame([{"name": None}])

    report = task_runtime_migration.inspect_task_runtime_migration(
        duck=object(), pg=MarkerlessPg()
    )
    assert report["state"] is None


@pytest.mark.parametrize('checkpoint,expected', [
    ({'phase': '分时采集', 'phase_done': 56, 'phase_total': 100,
      'intraday_scope': {'codes': ['a'] * 100}, 'intraday_done': ['a'],
      'intraday_failed': {'b': 'offline'}}, '已成功完成 1/100 只，1 只失败待重试'),
    ({'phase_done': 0, 'phase_total': 10}, '已处理 0/10 项'),
    ({'done': 3, 'total': 8}, '已处理 3/8 项'),
    ({'done': 3}, '已处理 3 项（总数未记录）'),
    ({'phase': '读取数据'}, '未记录处理计数'),
])
def test_resume_log_counts_are_compatible_without_placeholder(checkpoint, expected):
    from backend.services.async_task import _resume_message

    task_type = 'intraday_ingest' if 'intraday_scope' in checkpoint else 'backfill'
    message = _resume_message(task_type, checkpoint)
    assert expected in message
    assert 'None' not in message and '?' not in message
