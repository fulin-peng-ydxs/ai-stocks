"""Task/scheduler runtime storage routing and PostgreSQL compatibility client.

The runtime services historically use DuckDB's ``?`` placeholders and a small
``execute/query_df/transaction`` surface.  This adapter keeps that surface while
moving operational state to PostgreSQL.  Market data never flows through it.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pandas as pd
from psycopg.types.json import Jsonb

from backend.common.exceptions import ConfigError, StorageError
from backend.storage.duckdb_client import get_client as get_duckdb_client
from backend.storage.pg_client import PostgresClient, get_pg_client

TASK_RUNTIME_MIGRATION_MARKER = "migration.task_runtime_pg_v1"
_BACKENDS = {"auto", "duckdb", "postgres"}
_TASK_CREATE_LOCK_NAME = "ai-stocks-task-writer-slot-v1"
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _qmark_to_percent(sql: str) -> str:
    """Convert DuckDB placeholders without touching quoted question marks."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote is not None:
            out.append(ch)
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 1
                else:
                    quote = None
        elif ch in {"'", '"'}:
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _adapt_param(value: Any) -> Any:
    """Adapt typed values; JSONB callers pass dict/list instead of guessing from text."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=_LOCAL_TZ)
    if isinstance(value, (dict, list)):
        return Jsonb(value)
    return value


def runtime_json_param(client: Any, value: Any) -> Any:
    """Return typed JSONB for PG or canonical JSON text for legacy DuckDB."""
    payload = json.dumps(value, ensure_ascii=False, default=str)
    if getattr(client, "backend", None) == "postgres":
        return json.loads(payload)
    return payload


class PostgresTaskRuntimeClient:
    """PostgreSQL pool facade compatible with task/scheduler service SQL."""

    backend: ClassVar[str] = "postgres"

    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()
        self._local = threading.local()

    def _params(self, params: Sequence[Any] | None) -> list[Any]:
        return [_adapt_param(value) for value in (params or [])]

    def execute(self, sql: str, params: list[Any] | None = None) -> int:
        statement = _qmark_to_percent(sql)
        values = self._params(params)
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return self.pg.execute(statement, values)
        try:
            with conn.cursor() as cur:
                cur.execute(statement, values)
                return cur.rowcount
        except Exception as e:
            raise StorageError(f"SQL 执行失败: {e}\nSQL: {statement[:200]}") from e

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        statement = _qmark_to_percent(sql)
        values = [self._params(row) for row in rows]
        conn = getattr(self._local, "conn", None)
        if conn is None:
            with self.pg.transaction() as own, own.cursor() as cur:
                cur.executemany(statement, values)
                return cur.rowcount
        try:
            with conn.cursor() as cur:
                cur.executemany(statement, values)
                return cur.rowcount
        except Exception as e:
            raise StorageError(f"批量 SQL 执行失败: {e}\nSQL: {statement[:200]}") from e

    def query_df(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        statement = _qmark_to_percent(sql)
        values = self._params(params)
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return self.pg.query_df(statement, values)
        try:
            with conn.cursor() as cur:
                cur.execute(statement, values)
                if cur.description is None:
                    return pd.DataFrame()
                columns = [item.name for item in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=columns)
        except Exception as e:
            raise StorageError(f"查询失败: {e}\nSQL: {statement[:200]}") from e

    @contextmanager
    def transaction(self) -> Iterator[PostgresTaskRuntimeClient]:
        current = getattr(self._local, "conn", None)
        if current is not None:
            yield self
            return
        with self.pg.transaction() as conn:
            self._local.conn = conn
            try:
                yield self
            finally:
                self._local.conn = None

    @contextmanager
    def task_create_transaction(self) -> Iterator[PostgresTaskRuntimeClient]:
        """Serialize slot check + task insert across backend processes."""
        with self.transaction():
            conn = self._local.conn
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    [_TASK_CREATE_LOCK_NAME],
                )
            yield self

    def claim_due_events(self, *, now: Any, limit: int = 50) -> pd.DataFrame:
        """Atomically claim due events with row locks; safe across schedulers."""
        sql = """
            WITH candidates AS (
                SELECT id
                FROM scheduled_trigger_event
                WHERE status='waiting' AND due_at<=%s
                ORDER BY due_at, created_at, dispatch_order, id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE scheduled_trigger_event AS event
            SET status='dispatching', message='正在创建下游任务', updated_at=%s
            FROM candidates
            WHERE event.id=candidates.id
            RETURNING event.*
        """
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute(sql, [now, int(limit), now])
            columns = [item.name for item in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)


_pg_runtime_client: PostgresTaskRuntimeClient | None = None
_backend_cache: str | None = None
_lock = threading.Lock()


def reset_task_runtime_backend_cache() -> None:
    global _backend_cache
    _backend_cache = None


def task_runtime_backend(
    *, refresh: bool = False, pg_client: PostgresClient | None = None
) -> str:
    """Resolve runtime backend; auto switches only after the committed marker exists."""
    global _backend_cache
    configured = os.environ.get("AI_STOCKS_TASK_STORAGE_BACKEND", "auto").strip().lower()
    if configured not in _BACKENDS:
        raise ConfigError(
            "AI_STOCKS_TASK_STORAGE_BACKEND 仅支持 auto、duckdb、postgres"
        )
    if _backend_cache is not None and not refresh:
        resolved = _backend_cache
    else:
        pg = pg_client or get_pg_client()
        try:
            row = pg.query_df(
                "SELECT marker FROM storage_migration WHERE marker=%s AND state='applied'",
                [TASK_RUNTIME_MIGRATION_MARKER],
            )
        except StorageError as e:
            raise ConfigError(
                "无法读取任务运行态迁移标记，拒绝在 DuckDB/PostgreSQL 之间猜测切换"
            ) from e
        resolved = "postgres" if not row.empty else "duckdb"
        _backend_cache = resolved
    if configured == "postgres" and resolved != "postgres":
        raise ConfigError(
            f"任务运行态尚未完成迁移，缺少标记 {TASK_RUNTIME_MIGRATION_MARKER}"
        )
    if configured == "duckdb" and resolved == "postgres":
        raise ConfigError(
            f"任务运行态迁移标记 {TASK_RUNTIME_MIGRATION_MARKER} 仍为 applied，"
            "拒绝切回已冻结的 DuckDB 旧表；请先执行受控回退"
        )
    return resolved


def get_task_runtime_client():
    global _pg_runtime_client
    if task_runtime_backend() == "duckdb":
        return get_duckdb_client()
    if _pg_runtime_client is None:
        with _lock:
            if _pg_runtime_client is None:
                _pg_runtime_client = PostgresTaskRuntimeClient()
    return _pg_runtime_client


def is_postgres_task_runtime(client: Any) -> bool:
    return getattr(client, "backend", None) == "postgres"
