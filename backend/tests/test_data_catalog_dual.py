"""双库数据资产目录：发现、生命周期、字段漂移和按需统计契约。"""

from __future__ import annotations

import re

import pytest

import backend.storage.catalog as catalog_mod
from backend.storage.catalog import (
    build_catalog,
    build_catalog_payload,
    catalog_contract_report,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.schema_contract import load_contract

LADDER_DUCK_TABLES = {
    "limit_ladder_snapshot_state",
    "limit_ladder_snapshot",
    "limit_ladder_snapshot_stock",
    "limit_ladder_snapshot_concept",
    "limit_ladder_snapshot_aggregate",
    "limit_ladder_snapshot_window_metric",
    "limit_ladder_invalidation_outbox",
}
ST_REFERENCE_TABLES = {
    "stock_st_status_daily",
    "stock_st_status_history",
    "stock_st_status_refresh_state",
    "stock_st_status_date_revision",
}
LADDER_PG_TABLES = {"limit_ladder_task_ledger", "limit_ladder_audit_outbox"}


@pytest.fixture()
def catalog_env(pg, monkeypatch):
    """固定为当前已迁移路由，避免测试结果受机器 marker 存量影响。"""
    monkeypatch.setattr(catalog_mod, "_source_routing", lambda _pg: ("postgres", "postgres"))
    with DuckDBClient(db_path=":memory:") as duck:
        init_db(duck)
        yield duck, pg


def test_dual_catalog_discovers_all_current_and_legacy_tables(catalog_env):
    duck, pg = catalog_env
    payload = build_catalog_payload(
        client=duck, pg_client=pg, database="all", include_legacy=True
    )
    tables = payload["tables"]
    active = [item for item in tables if item["lifecycle"] == "active"]
    legacy = [item for item in tables if item["lifecycle"] == "legacy_readonly"]

    assert payload["summary"]["duckdb"]["active_tables"] == 36
    assert payload["summary"]["duckdb"]["legacy_tables"] == 29
    assert payload["summary"]["duckdb"]["unregistered_tables"] == 0
    # PG 新增生命周期表等结构后，发现结果仍须完整覆盖独立机器契约。
    expected_pg = set(load_contract()["postgres"]["tables"])
    assert {item["table"] for item in tables if item["database"] == "postgres"} == expected_pg
    assert payload["summary"]["postgres"]["active_tables"] == len(expected_pg)
    assert payload["summary"]["postgres"]["legacy_tables"] == 0
    assert payload["summary"]["postgres"]["unregistered_tables"] == 0
    assert len(active) == 36 + len(expected_pg)
    assert len(legacy) == 29
    assert all(item["metadata_complete"] for item in active)
    assert len({item["key"] for item in tables}) == 65 + len(expected_pg)

    duck_ladder = {
        item["table"] for item in tables
        if item["database"] == "duckdb" and item["category"] == "连板天梯"
    }
    pg_ladder = {
        item["table"] for item in tables
        if item["database"] == "postgres" and "连板" in item["name_cn"]
    }
    assert duck_ladder == LADDER_DUCK_TABLES
    assert pg_ladder == LADDER_PG_TABLES
    assert {
        item["table"]
        for item in tables
        if item["database"] == "duckdb"
        and item["category"] == "行情参考"
        and item["table"].startswith("stock_st_status_")
    } == ST_REFERENCE_TABLES


def test_runtime_and_config_tables_follow_existing_storage_routes():
    for table in ("async_task", "task_log", "scheduled_job", "scheduled_job_dependency", "scheduled_trigger_event"):
        assert catalog_mod._lifecycle("duckdb", table, {table}, "duckdb", "postgres") == (
            "active",
            "duckdb",
        )
        assert catalog_mod._lifecycle("postgres", table, {table}, "duckdb", "postgres") == (
            "legacy_readonly",
            "duckdb",
        )

    for table in ("app_config", "layout_preset", "layout_page_config", "layout_field_policy"):
        assert catalog_mod._lifecycle("duckdb", table, {table}, "postgres", "duckdb") == (
            "active",
            "duckdb",
        )
        assert catalog_mod._lifecycle("postgres", table, {table}, "postgres", "duckdb") == (
            "legacy_readonly",
            "duckdb",
        )


def test_catalog_fields_come_from_schema_and_cover_known_drift(catalog_env):
    duck, pg = catalog_env
    rows = build_catalog(
        duck, pg_client=pg, database="duckdb", include_legacy=False
    )
    by_table = {item["table"]: item for item in rows}

    quality_fields = {item["name"] for item in by_table["data_quality_issue"]["fields"]}
    board_fields = {item["name"] for item in by_table["board_dict"]["fields"]}
    fund_fields = {item["name"] for item in by_table["board_fund_flow"]["fields"]}
    assert {"fix_task_id", "ignore_scope", "ignore_active"} <= quality_fields
    assert {"source", "member_history_start_date", "last_seen_at", "updated_at"} <= board_fields
    assert "net_ratio" in fund_fields
    assert all(
        {
            "nullable", "default", "primary_key", "references", "name_source",
            "description_source", "metadata_complete",
        } <= set(field)
        for item in rows for field in item["fields"]
    )


def test_catalog_contract_is_complete_and_policies_are_explicit(catalog_env):
    duck, pg = catalog_env
    tables = build_catalog_payload(
        client=duck,
        pg_client=pg,
        database="all",
        include_legacy=True,
    )["tables"]
    report = catalog_contract_report(tables)

    assert report["ok"] is True
    assert report["field_count"] == report["field_metadata_complete"]
    assert all(item["freshness_policy"] for item in tables)
    assert all(item["quality_policy"] for item in tables)
    assert all(
        field["name_source"] != "fallback" and field["description_source"] != "fallback"
        for item in tables for field in item["fields"]
    )


def test_new_ddl_table_without_business_metadata_is_rejected(catalog_env, monkeypatch):
    duck, pg = catalog_env
    duck.execute("CREATE TABLE future_asset (id BIGINT PRIMARY KEY, trade_date DATE)")
    expected_duck, expected_pg = catalog_mod._duck_table_sets()
    monkeypatch.setattr(
        catalog_mod,
        "_duck_table_sets",
        lambda: (expected_duck | {"future_asset"}, expected_pg),
    )

    tables = build_catalog_payload(
        client=duck,
        pg_client=pg,
        database="all",
        include_legacy=True,
    )["tables"]
    future = next(item for item in tables if item["table"] == "future_asset")
    report = catalog_contract_report(tables)

    assert future["lifecycle"] == "unregistered"
    assert future["metadata_complete"] is False
    assert "缺少表级业务元数据" in future["metadata_issues"]
    assert report["ok"] is False
    assert any("future_asset 业务元数据不完整" in item for item in report["violations"])


def test_manual_physical_table_outside_ddl_is_rejected(catalog_env):
    duck, pg = catalog_env
    duck.execute("CREATE TABLE manual_asset (id BIGINT PRIMARY KEY)")

    tables = build_catalog_payload(
        client=duck,
        pg_client=pg,
        database="all",
        include_legacy=True,
    )["tables"]
    report = catalog_contract_report(tables)

    assert report["ok"] is False
    assert any("未纳入 DDL" in item and "manual_asset" in item for item in report["violations"])


def test_not_applicable_quality_is_not_reported_as_zero(catalog_env):
    duck, pg = catalog_env
    rows = build_catalog(duck, pg_client=pg, database="duckdb")
    by_table = {item["table"]: item for item in rows}

    assert by_table["stock_basic"]["quality_policy"]["mode"] == "not_applicable"
    assert by_table["stock_basic"]["open_issues"] is None
    assert by_table["daily_bar"]["quality_policy"]["mode"] == "issue_types"
    assert by_table["daily_bar"]["open_issues"] == 0
    assert set(by_table["stock_st_status_daily"]["quality_policy"]["issue_types"]) == {
        "st_status_missing",
        "st_status_approximate",
        "st_status_mismatch",
    }
    assert by_table["stock_st_status_refresh_state"]["fresh"] is None


def test_ladder_child_latest_date_requires_own_valid_snapshot_rows(catalog_env):
    duck, pg = catalog_env
    duck.execute(
        "INSERT INTO daily_bar (code,trade_date,close) VALUES "
        "('600000.SH',DATE '2024-01-03',10)"
    )
    duck.execute(
        "INSERT INTO limit_ladder_snapshot "
        "(snapshot_id,trade_date,rule_version,computed_at,stock_count,has_approx_st,"
        "coverage_json,window_metadata_json,source_version) VALUES "
        "('snap-1',DATE '2024-01-03','v1',TIMESTAMP '2024-01-03 16:00:00',1,false,'{}','{}','v1')"
    )
    duck.execute(
        "INSERT INTO limit_ladder_snapshot_state "
        "(trade_date,status,current_snapshot_id,rule_version,updated_at) VALUES "
        "(DATE '2024-01-03','valid','snap-1','v1',TIMESTAMP '2024-01-03 16:01:00')"
    )
    duck.execute(
        "INSERT INTO limit_ladder_snapshot_stock "
        "(snapshot_id,code,name,board,price_limit_pct,is_st,st_quality,st_source,"
        "is_one_word,consecutive_days,amount,industry_name,source_version) VALUES "
        "('snap-1','600000.SH','浦发银行','main',0.1,false,'accurate','source',"
        "false,2,1000,'银行','v1')"
    )

    rows = build_catalog(duck, pg_client=pg, database="duckdb")
    by_table = {item["table"]: item for item in rows}
    assert by_table["limit_ladder_snapshot"]["latest_time"].startswith("2024-01-03")
    assert by_table["limit_ladder_snapshot_stock"]["latest_time"].startswith("2024-01-03")
    assert by_table["limit_ladder_snapshot_stock"]["fresh"] is True
    assert by_table["limit_ladder_snapshot_concept"]["latest_time"] is None
    assert by_table["limit_ladder_snapshot_concept"]["fresh"] is False


def test_estimated_mode_avoids_full_counts_and_exact_counts_only_target(
    catalog_env, monkeypatch
):
    duck, pg = catalog_env
    duck.execute(
        "INSERT INTO daily_bar (code,trade_date,close) VALUES "
        "('600000.SH',DATE '2024-01-03',10),('000001.SZ',DATE '2024-01-03',11)"
    )
    queries: list[str] = []
    original = duck.query_df

    def traced_query(sql, params=None):
        queries.append(sql)
        return original(sql, params)

    monkeypatch.setattr(duck, "query_df", traced_query)
    build_catalog_payload(client=duck, pg_client=pg, database="duckdb")
    assert not any(
        re.search(
            r'SELECT\s+count\(\*\)\s+AS\s+n\s+FROM\s+"', sql, re.IGNORECASE
        )
        for sql in queries
    )

    queries.clear()
    payload = build_catalog_payload(
        client=duck,
        pg_client=pg,
        database="duckdb",
        table="daily_bar",
        count_mode="exact",
    )
    exact_queries = [sql for sql in queries if 'SELECT count(*) AS n FROM "' in sql]
    assert exact_queries == ['SELECT count(*) AS n FROM "daily_bar"']
    assert payload["tables"][0]["row_count"] == 2
    assert payload["tables"][0]["row_count_mode"] == "exact"
    assert payload["tables"][0]["measured_at"]


@pytest.mark.parametrize(
    ("database", "table", "count_mode"),
    [
        ("sqlite", None, "estimated"),
        ("all", "daily_bar", "exact"),
        ("duckdb", "main.daily_bar", "exact"),
        ("duckdb", 'daily_bar";DROP TABLE stock_basic;--', "exact"),
        ("duckdb", "not_a_real_table", "estimated"),
    ],
)
def test_catalog_rejects_invalid_database_table_and_exact_scope(
    catalog_env, database, table, count_mode
):
    duck, pg = catalog_env
    with pytest.raises(ValueError):
        build_catalog_payload(
            client=duck,
            pg_client=pg,
            database=database,
            table=table,
            count_mode=count_mode,
        )


def test_catalog_fails_closed_when_postgres_discovery_fails(catalog_env):
    duck, _pg = catalog_env

    class BrokenPg:
        def query_df(self, _sql, _params=None):
            raise RuntimeError("catalog unavailable")

    with pytest.raises(RuntimeError, match="catalog unavailable"):
        build_catalog_payload(client=duck, pg_client=BrokenPg(), database="all")
