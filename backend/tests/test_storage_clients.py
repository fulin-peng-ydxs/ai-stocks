"""混合持久层 stage1：PostgreSQL / Redis 客户端与连接配置测试。

约定：PG/Redis 未就绪的环境（如 CI 无外部服务）下，连接类用例自动 skip，
不阻断其他测试；连接配置组装（不连接）用例始终运行。
"""

from __future__ import annotations

import pytest

from backend.common.exceptions import StorageError
from backend.config import get_settings
from backend.storage.pg_client import PostgresClient
from backend.storage.redis_client import RedisClient


# ── 连接配置组装（不连接，始终运行）──


def test_pg_conninfo_default():
    s = get_settings()
    info = s.pg_conninfo()
    assert "dbname=" in info and "host=" in info and "port=" in info


def test_pg_conninfo_dsn_env_override(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_PG_DSN", "postgresql://u:p@h:5/db")
    assert get_settings().pg_conninfo() == "postgresql://u:p@h:5/db"


def test_pg_password_env_only(monkeypatch):
    """密码只来自环境变量，不出现在 YAML/默认串里。"""
    monkeypatch.delenv("AI_STOCKS_PG_DSN", raising=False)
    monkeypatch.setenv("AI_STOCKS_PG_PASSWORD", "secret123")
    info = get_settings().pg_conninfo()
    assert "password=secret123" in info


def test_redis_url_default(monkeypatch):
    # 验证 YAML 默认组装，不能把调用方的隔离 Redis 覆盖误当成默认值。
    from backend.config.settings import Settings
    monkeypatch.delenv("AI_STOCKS_REDIS_URL", raising=False)
    url = Settings().redis_url()
    assert url.startswith("redis://") and ":6379/" in url


def test_redis_url_env_override(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_REDIS_URL", "redis://h:1/2")
    assert get_settings().redis_url() == "redis://h:1/2"


# ── 连接类用例（服务不可用则 skip）──


@pytest.fixture()
def pg():
    client = PostgresClient()
    try:
        if not client.ping():
            pytest.skip("PostgreSQL 未就绪")
    except StorageError:
        pytest.skip("PostgreSQL 未就绪")
    yield client
    client.close()


@pytest.fixture()
def rds():
    client = RedisClient()
    try:
        if not client.ping():
            pytest.skip("Redis 未就绪")
    except StorageError:
        pytest.skip("Redis 未就绪")
    yield client
    client.close()


def test_pg_execute_query_roundtrip(pg):
    # 注意：连接池每次借不同连接，TEMP TABLE 是连接级的不可跨调用，故用普通表 + 清理。
    pg.execute("DROP TABLE IF EXISTS _t_stage1")
    pg.execute("CREATE TABLE _t_stage1 (id INT, name TEXT)")
    try:
        pg.execute("INSERT INTO _t_stage1 VALUES (%s, %s)", [1, "a"])
        df = pg.query_df("SELECT id, name FROM _t_stage1 WHERE id=%s", [1])
        assert len(df) == 1 and df.iloc[0]["name"] == "a"
    finally:
        pg.execute("DROP TABLE IF EXISTS _t_stage1")


def test_pg_transaction_rollback(pg):
    pg.execute("CREATE TABLE IF NOT EXISTS _t_stage1_tx (id INT)")
    pg.execute("DELETE FROM _t_stage1_tx")
    with pytest.raises(StorageError):
        with pg.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO _t_stage1_tx VALUES (1)")
                cur.execute("INSERT INTO _t_stage1_tx VALUES ('x')")  # 类型错→回滚
    df = pg.query_df("SELECT count(*) AS n FROM _t_stage1_tx")
    assert int(df.iloc[0]["n"]) == 0
    pg.execute("DROP TABLE _t_stage1_tx")


def test_redis_ping(rds):
    assert rds.ping() is True
