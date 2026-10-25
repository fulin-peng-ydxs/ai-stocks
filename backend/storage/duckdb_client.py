"""DuckDB 连接层（单写连接 + 同进程逻辑只读连接池）。

设计要点：
- 单文件保留一个专用写连接；查询可借用多个独立连接并发执行。
- 提供 execute/query_df 便捷方法；query_df 直接返回 pandas DataFrame。
- 上下文管理器 + 模块级单例（get_client）两种用法。
- 连接惰性创建；首次访问自动建好 data/ 目录。

注意：DuckDB 不能在同一进程内混用 read_only=true/false 打开同一文件。默认服务中读池连接
与写连接使用相同物理配置，再通过 statement type 校验实现逻辑只读；只读 E2E 模式下所有连接
统一 read_only=true。
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Self
from uuid import uuid4

import duckdb
import pandas as pd

from backend.common.exceptions import ServiceUnavailableError, StorageError
from backend.common.logging import get_logger
from backend.config import get_settings

log = get_logger("storage.duckdb")

# 写锁冲突异常消息关键字（跨进程文件锁，实测 DuckDB 1.5.3 抛
# "IO Error: Could not set lock on file ...: Conflicting lock is held"）。
# transaction() 异常归类用它区分「写锁占用」与普通事务错误 → 调用方返回 duckdb_write_unavailable。
_LOCK_CONFLICT_RE = re.compile(r"lock|conflicting|cannot open|another client|busy", re.IGNORECASE)


class DuckDBClient:
    """DuckDB 单文件客户端封装。"""

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False):
        if db_path is None:
            db_path = get_settings().duckdb_path()
        self.db_path = Path(db_path)
        self.read_only = read_only
        self._conn: duckdb.DuckDBPyConnection | None = None
        # DuckDB 连接非线程安全：FastAPI 同步端点跑在线程池，并发请求会同时
        # 操作同一连接而崩（实测并发 status+quality 必有一个 500）。用可重入锁
        # 串行化所有 SQL（本地查询毫秒级，串行无感），保证连接同一时刻仅一个线程使用。
        self._lock = threading.RLock()

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._conn = duckdb.connect(
                    database=str(self.db_path), read_only=self.read_only
                )
                log.info("DuckDB connected: %s (read_only=%s)", self.db_path, self.read_only)
            except Exception as e:
                raise StorageError(f"DuckDB 连接失败: {e}") from e
        return self._conn

    def execute(self, sql: str, params: list[Any] | None = None) -> duckdb.DuckDBPyConnection:
        """执行 SQL（DDL/DML）。"""
        try:
            started = time.perf_counter()
            with self._lock:
                executing = time.perf_counter()
                result = self.conn.execute(sql, params or [])
            self._record_writer_timing(sql, started, executing)
            return result
        except Exception as e:
            self._conn = None  # 连接状态已污染，下次访问自动重建
            raise StorageError(f"SQL 执行失败: {e}\nSQL: {sql[:200]}") from e

    def executemany(
        self, sql: str, rows: list[list[Any]] | list[tuple[Any, ...]]
    ) -> duckdb.DuckDBPyConnection:
        """批量执行同一条 DML；任务日志写入避免逐行分配临时视图。"""
        try:
            started = time.perf_counter()
            with self._lock:
                executing = time.perf_counter()
                result = self.conn.executemany(sql, rows)
            self._record_writer_timing(sql, started, executing)
            return result
        except Exception as e:
            self._conn = None
            raise StorageError(f"批量 SQL 执行失败: {e}\nSQL: {sql[:200]}") from e

    def query_df(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        """查询并返回 pandas DataFrame（DuckDB 与 pandas 零拷贝互通）。"""
        try:
            started = time.perf_counter()
            with self._lock:
                executing = time.perf_counter()
                result = self.conn.execute(sql, params or []).df()
            self._record_writer_timing(sql, started, executing)
            return result
        except Exception as e:
            self._conn = None  # 连接状态已污染，下次访问自动重建
            raise StorageError(f"查询失败: {e}\nSQL: {sql[:200]}") from e

    def register_df(self, name: str, df: pd.DataFrame) -> None:
        """把 DataFrame 注册为临时视图，便于 INSERT ... SELECT 幂等写入。"""
        with self._lock:
            self.conn.register(name, df)

    def unregister(self, name: str) -> None:
        # 必须同样持锁：DuckDB 连接非线程安全，未加锁的 unregister 会与其它线程
        # 正在执行的 SQL 同时操作同一连接，导致进程级卡死/崩溃。
        with self._lock:
            try:
                self.conn.unregister(name)
            except Exception as e:  # noqa: BLE001
                log.debug("DuckDB temporary view already unavailable: %s", e)

    @contextmanager
    def temp_view(self, df: pd.DataFrame, prefix: str = "tmp") -> Iterator[str]:
        """注册一个**进程内唯一名**的临时视图，离开作用域自动注销（register/unregister 均持锁）。

        固定视图名 + 共享单连接下，并发请求会互相覆盖/注销对方的视图（数据竞争）；
        唯一名彻底避免该冲突。用法：`with c.temp_view(df) as v: c.execute(f"... FROM {v}")`。
        """
        name = f"_{prefix}_{uuid4().hex}"
        self.register_df(name, df)
        try:
            yield name
        finally:
            self.unregister(name)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            log.info("DuckDB connection closed")

    @staticmethod
    def _record_writer_timing(sql, started, executing):
        from backend.datasource.observability import record
        ended = time.perf_counter()
        waiting, execution = executing - started, ended - executing
        record(db_wait_seconds=waiting, db_execute_seconds=execution, db_queries=1)
        if (ended - started) * 1000 >= get_settings().duckdb.slow_query_ms:
            log.warning("DuckDB slow query role=writer lock_wait_ms=%.1f execute_ms=%.1f sql=%s",
                        waiting * 1000, execution * 1000, " ".join(sql.split())[:240])

    @staticmethod
    def _log_if_slow(sql: str, started: float, *, role: str) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        threshold = get_settings().duckdb.slow_query_ms
        if elapsed_ms >= threshold:
            compact_sql = " ".join(sql.split())[:240]
            log.warning(
                "DuckDB slow query role=%s elapsed_ms=%.1f sql=%s",
                role,
                elapsed_ms,
                compact_sql,
            )

    @contextmanager
    def transaction(self) -> Iterator[DuckDBClient]:
        """多语句原子事务上下文管理器（进程内 RLock 跨 BEGIN..COMMIT）。

        背景：现有 execute()/query_df() 按调用各自持 RLock——多语句 BEGIN..COMMIT 块之间
        会被其他线程 SQL 插入（同一连接交替执行，破坏事务原子性）。本助手在整个事务块内持
        RLock，保证多语句写块（如板块成分落库 + member_count 刷新）原子执行。

        - 成功：COMMIT（异常则 ROLLBACK 并释放连接）。
        - 写锁冲突（跨进程，如 CLI 采集持文件锁）：connect/execute 立即抛 IOException 被包进
          StorageError，此处按消息关键字归类为软失败（见 lock_keyword 判定），调用方据此返回
          `duckdb_write_unavailable` 语义。连接恢复无需额外处理：冲突仅发生在 connect 阶段、
          `_conn` 保持 None，锁释放后重试即自动重建（2026-08-09 实测）。
        """
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                yield self
                self.conn.execute("COMMIT")
            except Exception as e:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception as rollback_error:  # noqa: BLE001
                    log.debug("DuckDB rollback failed after transaction error: %s", rollback_error)
                self._conn = None  # 事务异常后连接状态不确定，下次访问重建
                raise StorageError(
                    f"事务失败已回滚: {e}"
                    + (f"（写锁占用: {e}）" if _LOCK_CONFLICT_RE.search(str(e)) else "")
                ) from e

    # 上下文管理器
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class DuckDBReadPool:
    """同进程 DuckDB 查询连接池；连接只允许执行单条只读语句。"""

    _READ_STATEMENT_TYPES: ClassVar[set[duckdb.StatementType]] = {
        duckdb.StatementType.SELECT,
        duckdb.StatementType.EXPLAIN,
    }

    def __init__(
        self,
        db_path: str | Path,
        *,
        size: int,
        acquire_timeout_sec: float,
        read_only: bool,
    ):
        self.db_path = Path(db_path)
        self.size = max(0, int(size))
        self.acquire_timeout_sec = float(acquire_timeout_sec)
        self.read_only = read_only
        self._available: queue.LifoQueue[duckdb.DuckDBPyConnection] = queue.LifoQueue()
        self._all: list[duckdb.DuckDBPyConnection] = []
        self._init_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._active = 0
        self._timeouts = 0
        self._queries = 0
        self._closed = False

    def _ensure_open(self) -> None:
        if self._all or self.size == 0:
            return
        with self._init_lock:
            if self._all or self.size == 0:
                return
            if self._closed:
                raise ServiceUnavailableError("DuckDB 读连接池已关闭")
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            created: list[duckdb.DuckDBPyConnection] = []
            try:
                for _ in range(self.size):
                    conn = duckdb.connect(database=str(self.db_path), read_only=self.read_only)
                    created.append(conn)
                    self._available.put(conn)
                self._all.extend(created)
                log.info(
                    "DuckDB read pool opened: %s (size=%d read_only=%s)",
                    self.db_path,
                    self.size,
                    self.read_only,
                )
            except Exception as e:
                for conn in created:
                    conn.close()
                while not self._available.empty():
                    try:
                        self._available.get_nowait()
                    except queue.Empty:
                        break
                raise StorageError(f"DuckDB 读连接池创建失败: {e}") from e

    @contextmanager
    def connection(
        self, *, timeout_sec: float | None = None
    ) -> Iterator[duckdb.DuckDBPyConnection]:
        self._ensure_open()
        if self.size == 0:
            raise ServiceUnavailableError("DuckDB 读连接池已禁用")
        timeout = self.acquire_timeout_sec if timeout_sec is None else max(0.0, timeout_sec)
        try:
            conn = self._available.get(timeout=timeout)
        except queue.Empty as e:
            with self._stats_lock:
                self._timeouts += 1
            raise ServiceUnavailableError("DuckDB 查询繁忙，请稍后重试") from e
        with self._stats_lock:
            self._active += 1
        try:
            yield conn
        finally:
            with self._stats_lock:
                self._active -= 1
            if not self._closed:
                self._available.put(conn)

    @classmethod
    def _validate_read_sql(cls, conn: duckdb.DuckDBPyConnection, sql: str) -> None:
        try:
            statements = conn.extract_statements(sql)
        except Exception as e:
            raise StorageError(f"DuckDB 查询语句解析失败: {e}") from e
        if len(statements) != 1:
            raise StorageError("DuckDB 读连接仅允许执行一条 SQL")
        if statements[0].type not in cls._READ_STATEMENT_TYPES:
            raise StorageError(
                f"DuckDB 读连接禁止执行 {statements[0].type.name} 语句"
            )

    def query_df(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        timeout_sec: float | None = None,
    ) -> pd.DataFrame:
        started = time.perf_counter()
        with self.connection(timeout_sec=timeout_sec) as conn:
            result = self.query_df_on_connection(conn, sql, params, started=started)
        return result

    def query_df_on_connection(
        self,
        conn: duckdb.DuckDBPyConnection,
        sql: str,
        params: list[Any] | None = None,
        *,
        started: float | None = None,
    ) -> pd.DataFrame:
        """在已借出的连接上查询；用于让临时视图与其消费 SQL 保持同一会话。"""
        query_started = time.perf_counter() if started is None else started
        self._validate_read_sql(conn, sql)
        try:
            result = conn.execute(sql, params or []).df()
        except Exception as e:
            raise StorageError(f"查询失败: {e}\nSQL: {sql[:200]}") from e
        with self._stats_lock:
            self._queries += 1
        DuckDBClient._log_if_slow(sql, query_started, role="reader")
        return result

    def stats(self) -> dict[str, int | float | bool]:
        with self._stats_lock:
            return {
                "enabled": self.size > 0,
                "size": self.size,
                "active": self._active,
                "idle": self._available.qsize() if self._all else 0,
                "queries": self._queries,
                "timeouts": self._timeouts,
                "acquire_timeout_sec": self.acquire_timeout_sec,
            }

    def close(self) -> None:
        with self._init_lock:
            self._closed = True
            for conn in self._all:
                try:
                    conn.close()
                except Exception as e:  # noqa: BLE001
                    log.debug("DuckDB read connection close failed: %s", e)
            self._all.clear()
            while not self._available.empty():
                try:
                    self._available.get_nowait()
                except queue.Empty:
                    break
            log.info("DuckDB read pool closed")


class DuckDBReadClient:
    """只暴露查询能力的薄门面，避免业务误把读池当写连接。"""

    def __init__(self, pool: DuckDBReadPool, fallback: DuckDBClient):
        self._pool = pool
        self._fallback = fallback
        self._local = threading.local()

    @property
    def read_only(self) -> bool:
        """门面始终逻辑只读，不随池连接为兼容写连接而使用的物理模式变化。"""
        return True

    @property
    def db_path(self) -> Path:
        return self._fallback.db_path

    def query_df(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        timeout_sec: float | None = None,
    ) -> pd.DataFrame:
        if self._pool.size == 0:
            return self._fallback.query_df(sql, params)
        pinned = getattr(self._local, "connection", None)
        if pinned is not None:
            return self._pool.query_df_on_connection(pinned, sql, params)
        return self._pool.query_df(sql, params, timeout_sec=timeout_sec)

    @contextmanager
    def temp_view(self, df: pd.DataFrame, prefix: str = "tmp") -> Iterator[str]:
        """在一个借用连接内注册临时视图，并把作用域内查询固定到该连接。"""
        if self._pool.size == 0:
            with self._fallback.temp_view(df, prefix) as name:
                yield name
            return

        name = f"_{prefix}_{uuid4().hex}"
        pinned = getattr(self._local, "connection", None)
        if pinned is not None:
            pinned.register(name, df)
            try:
                yield name
            finally:
                try:
                    pinned.unregister(name)
                except Exception as e:  # noqa: BLE001
                    log.debug("DuckDB reader temporary view already unavailable: %s", e)
            return

        with self._pool.connection() as conn:
            conn.register(name, df)
            self._local.connection = conn
            try:
                yield name
            finally:
                self._local.connection = None
                try:
                    conn.unregister(name)
                except Exception as e:  # noqa: BLE001
                    log.debug("DuckDB reader temporary view already unavailable: %s", e)

    def stats(self) -> dict[str, int | float | bool]:
        return self._pool.stats()


_client: DuckDBClient | None = None
_read_pool: DuckDBReadPool | None = None
_read_client: DuckDBReadClient | None = None
_singleton_lock = threading.Lock()


def get_client() -> DuckDBClient:
    """模块级单例客户端（默认读写；`AI_STOCKS_DUCKDB_READ_ONLY=1` 时只读）。

    只读用于 E2E/多进程并存：被测后端以只读启动后不再持有 DuckDB 写锁，受控夹具进程
    才能短暂以写连接种子数据。DuckDB 写锁本就互斥，生产单进程服务保持默认读写。
    """
    global _client
    if _client is None:
        read_only = os.environ.get("AI_STOCKS_DUCKDB_READ_ONLY") == "1"
        _client = DuckDBClient(read_only=read_only)
    return _client


def get_write_client() -> DuckDBClient:
    """显式取得专用写连接；get_client 保留为兼容别名。"""
    return get_client()


def _configured_pool_size() -> int:
    raw = os.environ.get("AI_STOCKS_DUCKDB_READ_POOL_SIZE")
    if raw is None:
        return get_settings().duckdb.read_pool_size
    try:
        return max(0, min(int(raw), 32))
    except ValueError as e:
        raise StorageError("AI_STOCKS_DUCKDB_READ_POOL_SIZE 必须是 0~32 的整数") from e


def get_read_client() -> DuckDBReadClient:
    """取得进程内逻辑只读客户端；环境变量池大小为 0 时安全回退到写连接串行查询。"""
    global _read_client, _read_pool
    if _read_client is None:
        with _singleton_lock:
            if _read_client is None:
                writer = get_write_client()
                s = get_settings()
                _read_pool = DuckDBReadPool(
                    writer.db_path,
                    size=_configured_pool_size(),
                    acquire_timeout_sec=s.duckdb.read_acquire_timeout_sec,
                    read_only=writer.read_only,
                )
                _read_client = DuckDBReadClient(_read_pool, writer)
    return _read_client


def is_managed_duckdb_client(client: Any) -> bool:
    """Return whether a client belongs to this process's configured DuckDB singletons."""
    return client is _client or client is _read_client


def close_duckdb_clients() -> None:
    """按读池在前、写连接在后的顺序关闭 DuckDB 资源。"""
    global _client, _read_client, _read_pool
    if _read_pool is not None:
        _read_pool.close()
    if _client is not None:
        _client.close()
    _read_client = None
    _read_pool = None
    _client = None
