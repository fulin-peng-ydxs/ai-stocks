"""视觉预设启停边界：使用独立内存库，不初始化或修改项目 PG/DuckDB。"""

import duckdb
import pytest

from backend.storage.layout_config import LayoutConfigRepo, LayoutConfigValidationError


class MemoryPresetStorage:
    """让仓储真实执行预设 SQL；仅转换 PG 占位符，不模拟查询结果。"""

    def __init__(self):
        self.connection = duckdb.connect(":memory:")
        self.connection.execute(
            "CREATE TABLE layout_preset (key VARCHAR PRIMARY KEY, name VARCHAR, "
            "description VARCHAR, config VARCHAR, enabled BOOLEAN, is_builtin BOOLEAN, "
            "schema_version INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP)"
        )

    def execute(self, sql, params=None):
        return self.connection.execute(sql.replace("%s", "?"), params or [])

    def query_df(self, sql, params=None):
        return self.execute(sql, params).fetchdf()


@pytest.fixture
def repo(monkeypatch):
    storage = MemoryPresetStorage()
    instance = object.__new__(LayoutConfigRepo)
    instance.pg = storage
    monkeypatch.setattr(instance, "_config_storage_migrated", lambda: True)
    monkeypatch.setattr(instance, "_ensure_platform_layout_write_ready", lambda: None)
    monkeypatch.setattr(instance, "_should_read_duckdb_layout", lambda table: False)
    yield instance
    storage.connection.close()


def test_default_preset_rejects_disable_without_changing_tokens(repo):
    config = {"values": {"tokens.light.primary": "#345678"}}
    repo.upsert_preset("balanced", "默认", config=config, is_builtin=True)
    with pytest.raises(LayoutConfigValidationError, match="不能停用"):
        repo.upsert_preset("balanced", "默认", config=config, enabled=False)
    assert repo.get_preset("balanced")["enabled"] is True
    assert repo.get_preset("balanced")["config"]["values"] == config["values"]


def test_custom_preset_disable_filters_runtime_catalog_and_preserves_config(repo):
    config = {"values": {"tokens.shared.controlRadius": 12}}
    repo.upsert_preset("status-custom", "自定义", config=config)
    assert [row["key"] for row in repo.list_presets()] == ["status-custom"]
    repo.upsert_preset("status-custom", "自定义", config=config, enabled=False)
    assert repo.list_presets() == []
    assert repo.list_presets(include_disabled=True)[0]["config"]["values"] == config["values"]
    repo.upsert_preset("status-custom", "自定义", config=config, enabled=True)
    assert repo.list_presets()[0]["enabled"] is True


def test_legacy_default_status_repair_is_narrow_and_idempotent(repo):
    config = {"values": {"tokens.shared.cardRadius": 16}}
    repo.upsert_preset("balanced", "保留名称", config=config, is_builtin=True)
    repo.upsert_preset("status-custom", "自定义", config=config, enabled=False)
    repo.pg.execute("UPDATE layout_preset SET enabled=false WHERE key='balanced'")
    repo._ensure_default_preset_enabled()
    repaired = repo.get_preset("balanced")
    assert repaired["enabled"] is True
    assert repaired["name"] == "保留名称"
    assert repaired["config"]["values"] == config["values"]
    assert repo.get_preset("status-custom")["enabled"] is False
    repo._ensure_default_preset_enabled()
    assert repo.get_preset("balanced")["updated_at"] == repaired["updated_at"]


def test_legacy_status_repair_does_not_write_before_storage_migration(repo, monkeypatch):
    repo.upsert_preset("balanced", "默认", is_builtin=True)
    repo.pg.execute("UPDATE layout_preset SET enabled=false WHERE key='balanced'")
    monkeypatch.setattr(repo, "_config_storage_migrated", lambda: False)
    repo._ensure_default_preset_enabled()
    assert repo.get_preset("balanced")["enabled"] is False
