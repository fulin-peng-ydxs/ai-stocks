"""数据库专项共用夹具：每例独立空库或完整新装，普通客户端隔离由执行器兜底。"""

import os

import pytest

from backend.devtools.database_gate import ADMIN_DSN_ENV, temporary_database
from backend.storage import database_lifecycle as lifecycle
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def databases(monkeypatch):
    """提供未初始化的独立双库，用于目标声明、旧结构导入及故障恢复。"""
    admin = os.environ.get(ADMIN_DSN_ENV)
    if not admin:
        pytest.fail(f"必须通过 database gate 或设置 {ADMIN_DSN_ENV}，数据库门禁禁止跳过")
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_ADMIN_PASSWORD", "isolated-gate-password")
    monkeypatch.setenv("AI_STOCKS_TASK_STORAGE_BACKEND", "auto")
    with temporary_database(admin) as pg, DuckDBClient(":memory:") as duck:
        from backend.auth import perm_resolver
        from backend.storage import duckdb_client, pg_client

        # 间接仓储也绑定本用例双库；结束时恢复默认隔离连接，不污染运行态缓存。
        monkeypatch.setattr(pg_client, "_client", pg)
        monkeypatch.setattr(duckdb_client, "_client", duck)
        monkeypatch.setattr(perm_resolver, "clear_perms_cache", lambda _users: None)
        yield duck, pg


@pytest.fixture
def installed(databases):
    """提供走正式生命周期初始化且已验收的新装双库。"""
    duck, pg = databases
    report = lifecycle.initialize_database(duck, pg, mode="init")
    assert report["ok"], report
    return duck, pg
