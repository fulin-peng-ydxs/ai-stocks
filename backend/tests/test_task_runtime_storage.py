from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from backend.common.exceptions import ConfigError, StorageError
from backend.storage import task_runtime
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


def test_auto_backend_fails_closed_when_marker_cannot_be_read(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "auto")
    monkeypatch.setattr(task_runtime, "get_pg_client", lambda: _UnavailableMarkerPg())
    task_runtime.reset_task_runtime_backend_cache()
    with pytest.raises(ConfigError, match="拒绝.*猜测切换"):
        task_runtime.task_runtime_backend(refresh=True)
    task_runtime.reset_task_runtime_backend_cache()
