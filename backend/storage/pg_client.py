"""PostgreSQL 连接层（多租户混合持久层 stage1：资产/权限/审计/字典库）。

设计要点（对齐 [duckdb_client.py] 的 execute/query_df 习惯，但面向并发写）：
- psycopg3 + 连接池（psycopg_pool.ConnectionPool），契合 FastAPI 同步端点跑线程池的现状；
  每个请求线程从池借连接，绕开 DuckDB「单写进程 + 全局写锁」对并发写的限制。
- 提供 execute / query_df / transaction；query_df 返回 pandas DataFrame（与领域引擎一致）。
- 连接串/密码走环境变量（见 backend.config.Settings.pg_conninfo），不入库不入码不入日志。
- 占位符用 psycopg 风格 %s（区别于 DuckDB 的 ?）；上层资产仓库 SQL 据此书写。
- 行情/参考数据仍在 DuckDB；本客户端只承载用户私有资产与平台元数据。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pandas as pd
import psycopg
from psycopg_pool import ConnectionPool

from backend.common.exceptions import AIStocksError, StorageError
from backend.common.logging import get_logger
from backend.config import get_settings

log = get_logger("storage.postgres")


class PostgresClient:
    """PostgreSQL 连接池客户端封装。"""

    def __init__(
        self,
        conninfo: str | None = None,
        *,
        min_size: int | None = None,
        max_size: int | None = None,
    ):
        s = get_settings()
        self.conninfo = conninfo or s.pg_conninfo()
        self._min = min_size if min_size is not None else s.postgres.pool_min
        self._max = max_size if max_size is not None else s.postgres.pool_max
        self._pool: ConnectionPool | None = None

    @property
    def pool(self) -> ConnectionPool:
        """惰性创建连接池。失败抛 StorageError（密码不进异常信息）。"""
        if self._pool is None:
            try:
                self._pool = ConnectionPool(
                    self.conninfo,
                    min_size=self._min,
                    max_size=self._max,
                    timeout=10,  # 借连接最长等待，避免 PG 不可达时长时间挂起
                    open=True,
                )
                log.info("PostgreSQL pool opened (min=%s max=%s)", self._min, self._max)
            except Exception as e:
                raise StorageError(f"PostgreSQL 连接失败: {e}") from e
        return self._pool

    def execute(self, sql: str, params: list[Any] | None = None) -> int:
        """执行单条 DDL/DML，自动提交，返回受影响行数（-1 表示不可知）。"""
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(sql, params or [])
                return cur.rowcount
        except Exception as e:
            raise StorageError(f"SQL 执行失败: {e}\nSQL: {sql[:200]}") from e

    def query_df(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        """查询并返回 pandas DataFrame（无结果集返回空 DataFrame）。"""
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute(sql, params or [])
                if cur.description is None:
                    return pd.DataFrame()
                cols = [d.name for d in cur.description]
                rows = cur.fetchall()
            return pd.DataFrame(rows, columns=cols)
        except Exception as e:
            raise StorageError(f"查询失败: {e}\nSQL: {sql[:200]}") from e

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """事务作用域：块内多语句原子提交，异常自动回滚。

        用法：
            with client.transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute(...); cur.execute(...)
        """
        try:
            with self.pool.connection() as conn, conn.transaction():
                yield conn
        except AIStocksError:
            raise
        except Exception as e:
            raise StorageError(f"事务执行失败: {e}") from e

    @contextmanager
    def cursor_in(self, conn: psycopg.Connection | None = None) -> Iterator[psycopg.Cursor]:
        """产出游标：conn 非空则并入调用方事务（不另开），否则自建事务自动提交。

        供仓库写方法可选并入外部事务——让"业务写入 + perm_ver 自增"能在**同一 PG 事务**里原子提交
        （多租户 RBAC：权威失效与业务同生共死，不被 Redis 或跨事务窗口拖成 fail-open）。
        用法：`with self.pg.cursor_in(conn) as cur: cur.execute(...); cur.execute(...)`
        """
        if conn is not None:
            with conn.cursor() as cur:
                yield cur
        else:
            with self.transaction() as own, own.cursor() as cur:
                yield cur

    def ping(self) -> bool:
        """连通性自检（启动期调用）。"""
        df = self.query_df("SELECT 1 AS ok")
        return not df.empty and int(df.iloc[0]["ok"]) == 1

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            log.info("PostgreSQL pool closed")


_client: PostgresClient | None = None


def get_pg_client() -> PostgresClient:
    """模块级单例客户端。"""
    global _client
    if _client is None:
        _client = PostgresClient()
    return _client
