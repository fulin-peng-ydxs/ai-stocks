"""测试共享夹具（混合持久层 stage1·T2）。

资产域测试统一用：真实 PG（独立测试归属，用前用后清理；PG 不可用则 skip）+ 行情内存 DuckDB。
- pg     ：PostgresClient，已 init_pg_db，按 TEST_OWNER 清理
- market ：内存 DuckDB，已 init_db（行情/指标定义库）
- 测试归属：TEST_TENANT / TEST_OWNER，避免污染真实数据
"""

from __future__ import annotations

import os

import pytest

# stage2·T5：鉴权中间件对 /api/** 默认 deny，测试需可签发 token。
# 在模块导入期（早于各测试模块 import）设默认 JWT 密钥；个别用例仍可用 monkeypatch 覆盖/删除。
os.environ.setdefault("AI_STOCKS_JWT_SECRET", "pytest-jwt-secret-0123456789-abcdefghij")

from backend.common.exceptions import StorageError
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_client import PostgresClient
from backend.storage.pg_ddl import _ASSET_TABLES, init_pg_db

TEST_TENANT = "pytest"
TEST_OWNER = "pytest_owner"


def clean_owner(pg: PostgresClient, owner: str = TEST_OWNER) -> None:
    """清理某归属者在全部资产表的数据（测试隔离）。"""
    for t in _ASSET_TABLES:
        try:
            pg.execute(f"DELETE FROM {t} WHERE owner_user_id=%s", [owner])
        except StorageError:
            pass


@pytest.fixture()
def pg():
    client = PostgresClient()
    try:
        if not client.ping():
            pytest.skip("PostgreSQL 未就绪")
    except StorageError:
        pytest.skip("PostgreSQL 未就绪")
    init_pg_db(client)
    clean_owner(client)
    yield client
    clean_owner(client)
    client.close()


@pytest.fixture()
def market():
    c = DuckDBClient(db_path=":memory:")
    init_db(c)
    yield c
    c.close()


@pytest.fixture()
def redis_cli():
    """Redis 客户端（认证短状态测试用）；Redis 不可用则 skip。

    测试用 uuid 化的 account/jti/email/cid，键均带 TTL 自动过期，不污染真实数据。
    """
    from backend.storage.redis_client import get_redis_client

    c = get_redis_client()
    try:
        if not c.ping():
            pytest.skip("Redis 未就绪")
    except StorageError:
        pytest.skip("Redis 未就绪")
    return c


@pytest.fixture()
def app_cfg(pg):
    """平台配置仓库（PG，无归属）。app_config 是全局表，测试前快照、测试后还原，避免污染真实配置。"""
    from backend.storage.app_config import AppConfigRepo

    snap = pg.query_df("SELECT key, value, updated_at FROM app_config")
    yield AppConfigRepo(pg)
    pg.execute("DELETE FROM app_config")
    for _, r in snap.iterrows():
        pg.execute("INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s)",
                   [r["key"], r["value"], r["updated_at"]])
