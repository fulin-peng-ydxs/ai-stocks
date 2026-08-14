"""配置存储迁移命令（DuckDB → PG，config-storage-pg-migration T5）。"""

from __future__ import annotations

import json

import pytest

import backend.services.migrate_config_storage as mcs
from backend.common.exceptions import StorageError
from backend.services.migrate_config_storage import CONFIG_STORAGE_MARKER, migrate_config_storage
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.pg_ddl import (
    DDL_APP_CONFIG,
    DDL_LAYOUT_FIELD_POLICY,
    DDL_LAYOUT_PAGE_CONFIG,
    DDL_LAYOUT_PRESET,
)


@pytest.fixture()
def duck(tmp_path):
    c = DuckDBClient(db_path=str(tmp_path / "config-storage.duckdb"))
    init_db(c)
    c.execute(
        "INSERT INTO layout_preset "
        "(key, name, description, config, enabled, is_builtin, schema_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ["duck-preset", "旧库预设", "from duck", '{"density":"compact"}', True, False, 1],
    )
    c.execute(
        "INSERT INTO layout_page_config (page_key, preset_key, config, schema_version, updated_at) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        ["board", "duck-preset", '{"density":"comfortable"}', 1],
    )
    c.execute(
        "INSERT INTO layout_field_policy (component_kind, field, allowed_layers, updated_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        ["data-table", "pageSize", '["page"]'],
    )
    c.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        ["auth.login_rate_per_min", "30"],
    )
    c.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        ["migration.layout_presets_three_theme_v1", '{"applied":true}'],
    )
    c.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        ["ths_board.login_cookie", json.dumps("legacy-sensitive-cookie")],
    )
    yield c
    c.close()


@pytest.fixture()
def pg_config_snapshot(pg):
    tables = ["layout_preset", "layout_page_config", "layout_field_policy", "app_config"]
    for ddl in (DDL_APP_CONFIG, DDL_LAYOUT_PRESET, DDL_LAYOUT_PAGE_CONFIG, DDL_LAYOUT_FIELD_POLICY):
        pg.execute(ddl)
    snapshots = {table: pg.query_df(f"SELECT * FROM {table}") for table in tables}
    for table in ["layout_field_policy", "layout_page_config", "layout_preset", "app_config"]:
        pg.execute(f"DELETE FROM {table}")
    yield pg
    for table in ["layout_field_policy", "layout_page_config", "layout_preset", "app_config"]:
        pg.execute(f"DELETE FROM {table}")
    for table, df in snapshots.items():
        if df.empty:
            continue
        columns = list(df.columns)
        placeholders = ",".join(["%s"] * len(columns))
        for _, r in df.iterrows():
            pg.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                [r[col] for col in columns],
            )


def test_migrate_config_storage_dry_run_does_not_write(duck, pg_config_snapshot):
    pg = pg_config_snapshot
    report = migrate_config_storage(dry_run=True, duck=duck, pg=pg)

    assert report["_global"]["dry_run"] is True
    assert report["layout_preset"]["duck"] == 1
    assert report["layout_preset"]["pending"] == 1
    assert "ths_board.login_cookie" in report["app_config"]["source_keys"]
    assert "ths_board.login_cookie" in report["app_config"]["missing_keys"]
    assert pg.query_df("SELECT 1 FROM layout_preset WHERE key=%s", ["duck-preset"]).empty
    assert pg.query_df("SELECT 1 FROM app_config WHERE key=%s", [CONFIG_STORAGE_MARKER]).empty


def test_migrate_config_storage_apply_migrates_layout_and_missing_app_config(duck, pg_config_snapshot):
    pg = pg_config_snapshot
    pg.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP)",
        ["auth.login_rate_per_min", "99"],
    )

    report = migrate_config_storage(duck=duck, pg=pg)

    assert report["_global"]["marker_exists_after"] is True
    assert report["layout_preset"]["migrated"] == 1
    preset = pg.query_df("SELECT name, config FROM layout_preset WHERE key=%s", ["duck-preset"]).iloc[0]
    assert preset["name"] == "旧库预设"
    assert preset["config"] == '{"density":"compact"}'
    page = pg.query_df("SELECT preset_key, config FROM layout_page_config WHERE page_key=%s", ["board"]).iloc[0]
    assert page["preset_key"] == "duck-preset"
    policy = pg.query_df(
        "SELECT allowed_layers FROM layout_field_policy WHERE component_kind=%s AND field=%s",
        ["data-table", "pageSize"],
    ).iloc[0]
    assert policy["allowed_layers"] == '["page"]'
    # app_config 只补缺失，不覆盖 PG 现有运行期配置。
    app_value = pg.query_df(
        "SELECT value FROM app_config WHERE key=%s",
        ["auth.login_rate_per_min"],
    ).iloc[0]["value"]
    assert app_value == "99"
    assert not pg.query_df(
        "SELECT 1 FROM app_config WHERE key=%s",
        ["migration.layout_presets_three_theme_v1"],
    ).empty
    from backend.security.config_crypto import decrypt_config_value, is_encrypted_config_value

    stored = pg.query_df(
        "SELECT value FROM app_config WHERE key=%s", ["ths_board.login_cookie"]
    ).iloc[0]["value"]
    encrypted = json.loads(stored)
    assert is_encrypted_config_value(encrypted)
    assert decrypt_config_value(encrypted) == "legacy-sensitive-cookie"


def test_migrate_config_storage_marker_skips_unless_force(duck, pg_config_snapshot):
    pg = pg_config_snapshot
    migrate_config_storage(duck=duck, pg=pg)
    duck.execute(
        "UPDATE layout_preset SET name=? WHERE key=?",
        ["force-updated", "duck-preset"],
    )

    skipped = migrate_config_storage(duck=duck, pg=pg)
    assert skipped["_global"]["skipped"] is True
    assert pg.query_df(
        "SELECT name FROM layout_preset WHERE key=%s",
        ["duck-preset"],
    ).iloc[0]["name"] == "旧库预设"

    forced = migrate_config_storage(force=True, duck=duck, pg=pg)
    assert forced["_global"]["skipped"] is False
    assert pg.query_df(
        "SELECT name FROM layout_preset WHERE key=%s",
        ["duck-preset"],
    ).iloc[0]["name"] == "force-updated"


def test_migrate_config_storage_rolls_back_on_failure(duck, pg_config_snapshot, monkeypatch):
    pg = pg_config_snapshot

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mcs, "_insert_missing_app_config", boom)
    with pytest.raises(StorageError, match="boom"):
        migrate_config_storage(duck=duck, pg=pg)

    assert pg.query_df("SELECT 1 FROM layout_preset WHERE key=%s", ["duck-preset"]).empty
    assert pg.query_df("SELECT 1 FROM app_config WHERE key=%s", [CONFIG_STORAGE_MARKER]).empty
