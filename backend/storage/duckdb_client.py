"""DuckDB 连接层（SDD §2.2：单文件、嵌入式、列存、与 pandas 零拷贝互通）。

设计要点：
- 单文件单写多读，契合"每日批量写 + 大量分析读"。
- 提供 execute/query_df 便捷方法；query_df 直接返回 pandas DataFrame。
- 上下文管理器 + 模块级单例（get_client）两种用法。
- 连接惰性创建；首次访问自动建好 data/ 目录。

注意：DuckDB 默认单连接即可满足本系统（单用户本地 EOD）。
后续 Repository 层基于此封装点时安全查询。
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import duckdb
import pandas as pd

from backend.common.exceptions import StorageError
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
            except Exception as e:  # noqa: BLE001
                raise StorageError(f"DuckDB 连接失败: {e}") from e
        return self._conn

    def execute(self, sql: str, params: list[Any] | None = None) -> duckdb.DuckDBPyConnection:
        """执行 SQL（DDL/DML）。"""
        try:
            with self._lock:
                return self.conn.execute(sql, params or [])
        except Exception as e:  # noqa: BLE001
            self._conn = None  # 连接状态已污染，下次访问自动重建
            raise StorageError(f"SQL 执行失败: {e}\nSQL: {sql[:200]}") from e

    def query_df(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        """查询并返回 pandas DataFrame（DuckDB 与 pandas 零拷贝互通）。"""
        try:
            with self._lock:
                return self.conn.execute(sql, params or []).df()
        except Exception as e:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                pass

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

    @contextmanager
    def transaction(self) -> Iterator[DuckDBClient]:
        """多语句原子事务上下文管理器（进程内 RLock 跨 BEGIN..COMMIT）。

        背景：现有 execute()/query_df() 按调用各自持 RLock——多语句 BEGIN..COMMIT 块之间
        会被其他线程 SQL 插入（同一连接交替执行，破坏事务原子性）。本助手在整个事务块内持
        RLock，保证候选保存事务①/应用/丢弃事务②③等多语句块原子执行。

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
            except Exception as e:  # noqa: BLE001
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                self._conn = None  # 事务异常后连接状态不确定，下次访问重建
                raise StorageError(
                    f"事务失败已回滚: {e}"
                    + (f"（写锁占用: {e}）" if _LOCK_CONFLICT_RE.search(str(e)) else "")
                ) from e

    # 上下文管理器
    def __enter__(self) -> DuckDBClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


_client: DuckDBClient | None = None


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
