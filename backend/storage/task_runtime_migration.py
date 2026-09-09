"""Forward/reverse migration for task and scheduler runtime state.

Forward migration copies the complete DuckDB history in one PostgreSQL transaction and writes
the activation marker last.  The old DuckDB tables remain untouched as a frozen rollback source.
Reverse migration requires an exact confirmation marker and replaces those four DuckDB tables
from PostgreSQL in one DuckDB transaction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from psycopg.types.json import Jsonb

from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.task_runtime import (
    TASK_RUNTIME_MIGRATION_MARKER,
    reset_task_runtime_backend_cache,
)

_LOCAL_TZ = ZoneInfo("Asia/Shanghai")

_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "scheduled_job": (
        "id", "name", "task_type", "params", "freq_type", "freq_config", "trigger_mode",
        "dependency_job_id", "dependency_condition", "dependency_delay", "retry_config",
        "trading_day_only", "enabled", "last_run_at", "last_task_id", "created_at", "updated_at",
    ),
    "async_task": (
        "id", "task_type", "params", "status", "progress", "message", "result",
        "trigger_source", "job_id", "job_name", "chain_id", "parent_task_id",
        "trigger_event_id", "retry_count", "execution_attempt", "cancel_requested_at",
        "created_at", "updated_at",
    ),
    "task_log": ("id", "task_id", "seq", "ts", "level", "message"),
    "scheduled_trigger_event": (
        "id", "chain_id", "source_task_id", "source_attempt", "source_status", "target_job_id",
        "trigger_kind", "trigger_condition", "retry_count", "due_at", "dispatched_at", "status",
        "task_id", "job_snapshot", "message", "created_at", "updated_at",
    ),
}

_JSON_COLUMNS = {
    ("async_task", "params"),
    ("async_task", "result"),
    ("scheduled_job", "params"),
    ("scheduled_job", "freq_config"),
    ("scheduled_job", "dependency_delay"),
    ("scheduled_job", "retry_config"),
    ("scheduled_trigger_event", "job_snapshot"),
}

_TIME_COLUMNS = {
    ("scheduled_job", "last_run_at"),
    ("scheduled_job", "created_at"),
    ("scheduled_job", "updated_at"),
    ("async_task", "cancel_requested_at"),
    ("async_task", "created_at"),
    ("async_task", "updated_at"),
    ("task_log", "ts"),
    ("scheduled_trigger_event", "due_at"),
    ("scheduled_trigger_event", "dispatched_at"),
    ("scheduled_trigger_event", "created_at"),
    ("scheduled_trigger_event", "updated_at"),
}


def _none_if_na(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _json_value(value: Any, *, table: str, column: str) -> Any:
    value = _none_if_na(value)
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError) as e:
        raise ValueError(f"{table}.{column} 包含非法 JSON") from e
    if not isinstance(parsed, (dict, list)):
        raise TypeError(f"{table}.{column} 必须是 JSON 对象或数组")
    return parsed


def _to_utc(value: Any) -> datetime | None:
    value = _none_if_na(value)
    if value is None:
        return None
    stamp = pd.Timestamp(value).to_pydatetime()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_LOCAL_TZ)
    return stamp.astimezone(UTC)


def _to_duck_time(value: Any) -> datetime | None:
    value = _none_if_na(value)
    if value is None:
        return None
    stamp = pd.Timestamp(value).to_pydatetime()
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(_LOCAL_TZ).replace(tzinfo=None)
    return stamp


def _duck_frames(duck: DuckDBClient) -> dict[str, pd.DataFrame]:
    return {
        table: duck.query_df(f"SELECT {','.join(columns)} FROM {table}")
        for table, columns in _TABLE_COLUMNS.items()
    }


def _validate_frames(frames: dict[str, pd.DataFrame]) -> None:
    tasks = set(frames["async_task"]["id"].astype(str))
    logs = frames["task_log"]
    orphan_logs = set(logs["task_id"].astype(str)) - tasks if not logs.empty else set()
    if orphan_logs:
        raise ValueError(f"task_log 存在 {len(orphan_logs)} 个孤儿 task_id")
    active = frames["async_task"]
    if not active.empty:
        active = active[active["status"].isin(["pending", "running"])]
    if not active.empty:
        raise ValueError("仍有 pending/running 任务，必须先通过 start.sh 安全停服")
    for table, frame in frames.items():
        for column in _TABLE_COLUMNS[table]:
            if (table, column) in _JSON_COLUMNS:
                for value in frame[column].tolist():
                    _json_value(value, table=table, column=column)


def _pg_counts(pg: PostgresClient) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _TABLE_COLUMNS:
        exists = pg.query_df("SELECT to_regclass(%s) AS name", [f"public.{table}"])
        counts[table] = (
            0
            if exists.empty or exists.iloc[0]["name"] is None
            else int(pg.query_df(f"SELECT count(*) AS n FROM {table}").iloc[0]["n"])
        )
    return counts


def inspect_task_runtime_migration(
    *, duck: DuckDBClient | None = None, pg: PostgresClient | None = None
) -> dict[str, Any]:
    duck = duck or get_client()
    pg = pg or get_pg_client()
    init_db(duck)
    frames = _duck_frames(duck)
    _validate_frames(frames)
    marker_table = pg.query_df("SELECT to_regclass('public.storage_migration') AS name")
    marker = (
        pg.query_df(
            "SELECT state, applied_at, details FROM storage_migration WHERE marker=%s",
            [TASK_RUNTIME_MIGRATION_MARKER],
        )
        if not marker_table.empty and marker_table.iloc[0]["name"] is not None
        else pd.DataFrame()
    )
    return {
        "marker": TASK_RUNTIME_MIGRATION_MARKER,
        "state": None if marker.empty else str(marker.iloc[0]["state"]),
        "duckdb_counts": {table: len(frame) for table, frame in frames.items()},
        "postgres_counts": _pg_counts(pg),
    }


def migrate_task_runtime_to_postgres(
    *, duck: DuckDBClient | None = None, pg: PostgresClient | None = None
) -> dict[str, Any]:
    from backend.storage.pg_ddl import init_pg_db

    duck = duck or get_client()
    pg = pg or get_pg_client()
    init_db(duck)
    frames = _duck_frames(duck)
    _validate_frames(frames)
    init_pg_db(pg)
    target_counts = _pg_counts(pg)
    marker = pg.query_df(
        "SELECT state FROM storage_migration WHERE marker=%s",
        [TASK_RUNTIME_MIGRATION_MARKER],
    )
    if not marker.empty and str(marker.iloc[0]["state"]) == "applied":
        raise ValueError("任务运行态迁移已经完成，拒绝重复写入")
    if any(target_counts.values()):
        raise ValueError(f"PostgreSQL 任务运行表不是空表，拒绝覆盖: {target_counts}")

    with pg.transaction() as conn, conn.cursor() as cur:
        for table in ("scheduled_job", "async_task", "task_log", "scheduled_trigger_event"):
            columns = _TABLE_COLUMNS[table]
            rows: list[list[Any]] = []
            for record in frames[table].to_dict("records"):
                values: list[Any] = []
                for column in columns:
                    value = record[column]
                    if (table, column) in _JSON_COLUMNS:
                        parsed = _json_value(value, table=table, column=column)
                        value = None if parsed is None else Jsonb(parsed)
                    elif (table, column) in _TIME_COLUMNS:
                        value = _to_utc(value)
                    else:
                        value = _none_if_na(value)
                        if hasattr(value, "item"):
                            value = value.item()
                    values.append(value)
                rows.append(values)
            if rows:
                placeholders = ",".join(["%s"] * len(columns))
                cur.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                    rows,
                )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('task_log','id'), "
            "GREATEST(COALESCE((SELECT max(id) FROM task_log), 0), 1), "
            "EXISTS (SELECT 1 FROM task_log))"
        )
        counts = {table: len(frame) for table, frame in frames.items()}
        cur.execute(
            "INSERT INTO storage_migration (marker, state, details, applied_at, updated_at) "
            "VALUES (%s, 'applied', %s, now(), now()) "
            "ON CONFLICT (marker) DO UPDATE SET state='applied', details=EXCLUDED.details, "
            "applied_at=now(), updated_at=now()",
            [TASK_RUNTIME_MIGRATION_MARKER, Jsonb({"counts": counts, "source_timezone": "Asia/Shanghai"})],
        )
    reset_task_runtime_backend_cache()
    report = inspect_task_runtime_migration(duck=duck, pg=pg)
    if report["duckdb_counts"] != report["postgres_counts"]:
        raise RuntimeError(f"迁移后数量核对失败: {report}")
    return report


def rollback_task_runtime_to_duckdb(
    *,
    confirm_marker: str,
    duck: DuckDBClient | None = None,
    pg: PostgresClient | None = None,
) -> dict[str, Any]:
    if confirm_marker != TASK_RUNTIME_MIGRATION_MARKER:
        raise ValueError(f"确认标记必须精确等于 {TASK_RUNTIME_MIGRATION_MARKER}")
    duck = duck or get_client()
    pg = pg or get_pg_client()
    marker = pg.query_df(
        "SELECT state FROM storage_migration WHERE marker=%s",
        [TASK_RUNTIME_MIGRATION_MARKER],
    )
    if marker.empty or str(marker.iloc[0]["state"]) != "applied":
        raise ValueError("PostgreSQL 任务运行态迁移标记不是 applied，拒绝回滚")
    frames = {
        table: pg.query_df(f"SELECT {','.join(columns)} FROM {table}")
        for table, columns in _TABLE_COLUMNS.items()
    }
    _validate_frames(frames)
    init_db(duck)
    with duck.transaction():
        for table in ("scheduled_trigger_event", "task_log", "async_task", "scheduled_job"):
            duck.execute(f"DELETE FROM {table}")
        for table in ("scheduled_job", "async_task", "task_log", "scheduled_trigger_event"):
            columns = _TABLE_COLUMNS[table]
            rows: list[tuple[Any, ...]] = []
            for record in frames[table].to_dict("records"):
                values: list[Any] = []
                for column in columns:
                    value = record[column]
                    if (table, column) in _JSON_COLUMNS:
                        parsed = _json_value(value, table=table, column=column)
                        value = None if parsed is None else json.dumps(parsed, ensure_ascii=False)
                    elif (table, column) in _TIME_COLUMNS:
                        value = _to_duck_time(value)
                    else:
                        value = _none_if_na(value)
                        if hasattr(value, "item"):
                            value = value.item()
                    values.append(value)
                rows.append(tuple(values))
            if rows:
                duck.executemany(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES "
                    f"({','.join(['?'] * len(columns))})",
                    rows,
                )
        max_id = int(frames["task_log"]["id"].max()) if not frames["task_log"].empty else 0
        duck.execute(f"ALTER SEQUENCE seq_task_log RESTART WITH {max_id + 1}")
    # DuckDB 已成为回退后的唯一运行态事实源；PG 四表必须与 marker 在同一事务内清空，
    # 避免后续重新正向迁移被旧副本阻塞，也避免 rolled_back 状态下出现双事实源。
    with pg.transaction() as conn, conn.cursor() as cur:
        for table in ("scheduled_trigger_event", "task_log", "async_task", "scheduled_job"):
            cur.execute(f"DELETE FROM {table}")
        cur.execute(
            "UPDATE storage_migration SET state='rolled_back', updated_at=now() WHERE marker=%s",
            [TASK_RUNTIME_MIGRATION_MARKER],
        )
    reset_task_runtime_backend_cache()
    return {
        "marker": TASK_RUNTIME_MIGRATION_MARKER,
        "state": "rolled_back",
        "duckdb_counts": {table: len(frame) for table, frame in frames.items()},
    }
