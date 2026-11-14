"""配置存储迁移：DuckDB → PostgreSQL。

仅迁移配置类平台表：layout_preset、layout_page_config、layout_field_policy 和旧 app_config
缺失项。行情/研究数据仍留 DuckDB；用户浏览器 localStorage 迁移不在本命令范围内。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.common.logging import get_logger
from backend.common.timeutil import shanghai_now_naive
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_ddl import (
    DDL_APP_CONFIG,
    DDL_LAYOUT_FIELD_POLICY,
    DDL_LAYOUT_PAGE_CONFIG,
    DDL_LAYOUT_PRESET,
)

log = get_logger("services.migrate_config_storage")

CONFIG_STORAGE_MARKER = "migration.config_storage_pg_v1"

_LAYOUT_TABLES: dict[str, list[str]] = {
    "layout_preset": [
        "key",
        "name",
        "description",
        "config",
        "enabled",
        "is_builtin",
        "schema_version",
        "created_at",
        "updated_at",
    ],
    "layout_page_config": ["page_key", "preset_key", "config", "schema_version", "updated_at"],
    "layout_field_policy": ["component_kind", "field", "allowed_layers", "updated_at"],
}
_TABLE_DDL = {
    "app_config": DDL_APP_CONFIG,
    "layout_preset": DDL_LAYOUT_PRESET,
    "layout_page_config": DDL_LAYOUT_PAGE_CONFIG,
    "layout_field_policy": DDL_LAYOUT_FIELD_POLICY,
}
_CONFLICT_KEYS = {
    "layout_preset": ["key"],
    "layout_page_config": ["page_key"],
    "layout_field_policy": ["component_kind", "field"],
}


def _to_pg_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _rows(df: pd.DataFrame, columns: list[str]) -> list[tuple[Any, ...]]:
    return [tuple(_to_pg_value(row[col]) for col in columns) for _, row in df.iterrows()]


def _key_tuple(row: Any, keys: list[str]) -> tuple[str, ...]:
    return tuple(str(row[key]) for key in keys)


def _source_df(duck: DuckDBClient, table: str, columns: list[str]) -> pd.DataFrame:
    return duck.query_df(f"SELECT {', '.join(columns)} FROM {table}")


def _existing_keys(pg: PostgresClient, table: str, keys: list[str]) -> set[tuple[str, ...]]:
    df = pg.query_df(f"SELECT {', '.join(keys)} FROM {table}")
    return {_key_tuple(row, keys) for _, row in df.iterrows()}


def _ensure_pg_tables(pg: PostgresClient) -> None:
    for ddl in _TABLE_DDL.values():
        pg.execute(ddl)


def _table_report(duck: DuckDBClient, pg: PostgresClient, table: str, columns: list[str]) -> dict:
    df = _source_df(duck, table, columns)
    keys = _CONFLICT_KEYS[table]
    source_keys = [_key_tuple(row, keys) for _, row in df.iterrows()]
    existing = _existing_keys(pg, table, keys)
    missing = [key for key in source_keys if key not in existing]
    conflicts = [key for key in source_keys if key in existing]
    return {
        "duck": len(df),
        "pg_before": len(existing),
        "pending": len(missing),
        "conflicts": len(conflicts),
        "source_keys": ["|".join(key) for key in source_keys],
        "missing_keys": ["|".join(key) for key in missing],
        "conflict_keys": ["|".join(key) for key in conflicts],
        "conflict_policy": "upsert_update",
        "migrated": 0,
        "problems": [],
    }


def _app_config_report(duck: DuckDBClient, pg: PostgresClient) -> dict:
    df = _app_config_source_df(duck)
    pg_keys_df = pg.query_df("SELECT key FROM app_config")
    existing = set(pg_keys_df["key"].tolist()) if not pg_keys_df.empty else set()
    source_keys = [str(row["key"]) for _, row in df.iterrows()]
    missing = [key for key in source_keys if key not in existing]
    conflicts = [key for key in source_keys if key in existing]
    return {
        "duck": len(df),
        "pg_before": len(existing),
        "pending": len(missing),
        "conflicts": len(conflicts),
        "source_keys": source_keys,
        "missing_keys": missing,
        "conflict_keys": conflicts,
        "conflict_policy": "insert_missing_only",
        "migrated": 0,
        "problems": [],
    }


def _upsert_layout(cur, table: str, df: pd.DataFrame, columns: list[str]) -> int:
    if df.empty:
        return 0
    keys = _CONFLICT_KEYS[table]
    placeholders = ", ".join(["%s"] * len(columns))
    updates = [col for col in columns if col not in keys]
    set_sql = ", ".join(f"{col}=EXCLUDED.{col}" for col in updates)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {set_sql}"
    )
    cur.executemany(sql, _rows(df, columns))
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(df)


def _insert_missing_app_config(cur, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = _rows(df, ["key", "value", "updated_at"])
    cur.executemany(
        "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s) "
        "ON CONFLICT (key) DO NOTHING",
        rows,
    )
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def _app_config_source_df(duck: DuckDBClient) -> pd.DataFrame:
    from backend.storage.app_config import protect_serialized_config_value

    df = duck.query_df("SELECT key, value, updated_at FROM app_config")
    if df.empty:
        return df
    df = df.copy()
    df["value"] = [
        protect_serialized_config_value(str(row["key"]), row["value"])
        for _, row in df.iterrows()
    ]
    return df[df["value"].notna()]


def _marker_exists(pg: PostgresClient) -> bool:
    df = pg.query_df("SELECT 1 FROM app_config WHERE key=%s", [CONFIG_STORAGE_MARKER])
    return not df.empty


def config_storage_backend(pg: PostgresClient | None = None) -> str:
    """返回平台布局配置的真实读路由，供运行服务与资产目录共同消费。"""
    return "postgres" if _marker_exists(pg or get_pg_client()) else "duckdb"


def migrate_config_storage(
    *,
    dry_run: bool = False,
    force: bool = False,
    duck: DuckDBClient | None = None,
    pg: PostgresClient | None = None,
) -> dict:
    """迁移配置存储。默认实迁；dry_run=True 只返回报告不写 PG。"""
    duck = duck or get_client()
    pg = pg or get_pg_client()
    _ensure_pg_tables(pg)

    marker_exists = _marker_exists(pg)
    report: dict[str, Any] = {
        "_global": {
            "dry_run": dry_run,
            "force": force,
            "marker": CONFIG_STORAGE_MARKER,
            "marker_exists": marker_exists,
            "skipped": bool(marker_exists and not force),
            "problems": [],
        }
    }
    for table, columns in _LAYOUT_TABLES.items():
        report[table] = _table_report(duck, pg, table, columns)
    report["app_config"] = _app_config_report(duck, pg)

    if marker_exists and not force:
        log.info("配置存储迁移已跳过：marker 已存在 %s", CONFIG_STORAGE_MARKER)
        return report
    if dry_run:
        log.info("配置存储迁移 dry-run 完成")
        return report

    with pg.transaction() as conn, conn.cursor() as cur:
        for table, columns in _LAYOUT_TABLES.items():
            src = _source_df(duck, table, columns)
            report[table]["migrated"] = _upsert_layout(cur, table, src, columns)
        app_df = _app_config_source_df(duck)
        report["app_config"]["migrated"] = _insert_missing_app_config(cur, app_df)
        # 明确保留旧三主题 seed marker：若旧库已有，app_config 缺失补迁会带过来；此处只补本次迁移 marker。
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [
                CONFIG_STORAGE_MARKER,
                '{"applied":true,"source":"migrate-config-storage"}',
                shanghai_now_naive(),
            ],
        )

    for table, keys in _CONFLICT_KEYS.items():
        report[table]["pg_after"] = len(_existing_keys(pg, table, keys))
    report["app_config"]["pg_after"] = int(
        pg.query_df("SELECT count(*) AS n FROM app_config").iloc[0]["n"]
    )
    report["_global"]["marker_exists_after"] = _marker_exists(pg)
    log.info("配置存储迁移完成：dry_run=%s force=%s", dry_run, force)
    return report
