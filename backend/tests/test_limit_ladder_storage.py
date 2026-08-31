"""T2: limit-ladder DuckDB schema and PostgreSQL task ledger contracts."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from backend.common.exceptions import StorageError
from backend.storage.audit_repository import AuditRepository
from backend.storage.ddl import M_LIMIT_LADDER_TABLES, init_db, list_tables
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.limit_ladder_task_repository import (
    LimitLadderTaskCommand,
    LimitLadderTaskRepository,
)
from backend.storage.pg_ddl import init_pg_db


def test_limit_ladder_duckdb_schema_is_idempotent_and_accepts_empty_snapshot():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        init_db(client)
        assert set(M_LIMIT_LADDER_TABLES).issubset(list_tables(client))
        client.execute(
            "INSERT INTO limit_ladder_snapshot "
            "(snapshot_id,trade_date,rule_version,computed_at,stock_count,has_approx_st,"
            "coverage_json,source_version) VALUES "
            "('empty',DATE '2026-08-28','v1',current_timestamp,0,false,'{}','fixture')"
        )
        assert int(client.query_df(
            "SELECT stock_count FROM limit_ladder_snapshot WHERE snapshot_id='empty'"
        ).iloc[0]["stock_count"]) == 0


def _prepare_t16_snapshot_table(client: DuckDBClient) -> None:
    client.execute(
        "CREATE TABLE limit_ladder_snapshot ("
        "snapshot_id VARCHAR PRIMARY KEY,trade_date DATE NOT NULL,"
        "rule_version VARCHAR NOT NULL,computed_at TIMESTAMP NOT NULL,"
        "stock_count INTEGER NOT NULL CHECK (stock_count >= 0),"
        "has_approx_st BOOLEAN NOT NULL,coverage_json VARCHAR NOT NULL,"
        "source_version VARCHAR NOT NULL)"
    )
    client.execute(
        "CREATE INDEX idx_limit_ladder_snapshot_date "
        "ON limit_ladder_snapshot (trade_date, computed_at)"
    )
    client.execute(
        "INSERT INTO limit_ladder_snapshot "
        "(snapshot_id,trade_date,rule_version,computed_at,stock_count,has_approx_st,"
        "coverage_json,source_version) VALUES "
        "('legacy',DATE '2026-08-28','v1',current_timestamp,0,false,'{}','fixture')"
    )


def _assert_t17_snapshot_column_contract(client: DuckDBClient) -> None:
    row = client.query_df(
        "SELECT window_metadata_json FROM limit_ladder_snapshot "
        "WHERE snapshot_id='legacy'"
    ).iloc[0]
    assert row["window_metadata_json"] == "{}"
    column = client.query_df(
        "SELECT is_nullable,column_default FROM information_schema.columns "
        "WHERE table_schema='main' AND table_name='limit_ladder_snapshot' "
        "AND column_name='window_metadata_json'"
    ).iloc[0]
    assert column["is_nullable"] == "NO"
    assert column["column_default"] == "'{}'"
    with pytest.raises(StorageError):
        client.execute(
            "UPDATE limit_ladder_snapshot SET window_metadata_json=NULL "
            "WHERE snapshot_id='legacy'"
        )


def test_init_db_upgrades_t16_snapshot_metadata_column_idempotently():
    with DuckDBClient(db_path=":memory:") as client:
        _prepare_t16_snapshot_table(client)
        init_db(client)
        init_db(client)
        _assert_t17_snapshot_column_contract(client)


def test_schema_sql_upgrades_t16_snapshot_metadata_column_idempotently():
    schema_sql = (
        Path(__file__).parents[2]
        / "agent-works"
        / "limit-up-ladder"
        / "limit-ladder-schema.sql"
    ).read_text(encoding="utf-8")
    with DuckDBClient(db_path=":memory:") as client:
        _prepare_t16_snapshot_table(client)
        client.execute(schema_sql)
        client.execute(schema_sql)
        _assert_t17_snapshot_column_contract(client)


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        (
            "stock_st_status_daily",
            "code,trade_date,is_st,source,quality,captured_at,updated_at",
            "'A.SH',DATE '2026-08-28',false,'fixture','unknown',current_timestamp,current_timestamp",
        ),
        (
            "limit_ladder_snapshot_state",
            "trade_date,status,rule_version,updated_at",
            "DATE '2026-08-28','unknown','v1',current_timestamp",
        ),
        (
            "limit_ladder_snapshot_aggregate",
            "snapshot_id,group_type,group_key,group_name,stock_count",
            "'s1','other','k','n',1",
        ),
    ],
)
def test_limit_ladder_duckdb_rejects_invalid_enums(table, columns, values):
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        with pytest.raises(StorageError):
            client.execute(f"INSERT INTO {table} ({columns}) VALUES ({values})")


def test_limit_ladder_task_ledger_releases_date_after_every_terminal_status(pg):
    init_pg_db(pg)
    repository = LimitLadderTaskRepository(pg)
    suffix = uuid4().hex
    trade_date = date(
        2100 + int(suffix[:2], 16) % 100,
        1 + int(suffix[2:4], 16) % 12,
        1 + int(suffix[4:6], 16) % 28,
    )
    command_ids = [f"pytest_ll_{suffix}_{index}" for index in range(4)]
    try:
        for index, terminal_status in enumerate(("succeeded", "failed", "interrupted")):
            command = LimitLadderTaskCommand(
                command_id=command_ids[index],
                trade_date=trade_date,
                source="auto_first_load",
                actor_kind="system",
                actor_account="system:limit-ladder",
                rule_version="test-v1",
            )
            repository.create_requested(command)
            assert repository.transition(
                command_id=command.command_id,
                status=terminal_status,
                task_id=f"task_{suffix}_{index}",
            )

        active = LimitLadderTaskCommand(
            command_id=command_ids[3],
            trade_date=trade_date,
            source="admin_recompute",
            actor_kind="user",
            tenant_id=f"tenant_{suffix}",
            actor_user_id=f"user_{suffix}",
            actor_account=f"account_{suffix}",
            rule_version="test-v1",
        )
        repository.create_requested(active)
        with pytest.raises(StorageError):
            repository.create_requested(
                LimitLadderTaskCommand(
                    command_id=f"pytest_ll_conflict_{suffix}",
                    trade_date=trade_date,
                    source="auto_invalid_refresh",
                    actor_kind="system",
                    actor_account="system:limit-ladder",
                    rule_version="test-v1",
                )
            )
        row = repository.get_active_for_date(trade_date)
        assert row is not None and row["command_id"] == active.command_id
        events = pg.query_df(
            "SELECT command_id,event_type,source_event_key FROM limit_ladder_audit_outbox "
            "WHERE command_id = ANY(%s)",
            [command_ids],
        )
        assert len(events) == 7
        assert events["source_event_key"].is_unique
    finally:
        all_ids = [*command_ids, f"pytest_ll_conflict_{suffix}"]
        pg.execute("DELETE FROM limit_ladder_audit_outbox WHERE command_id = ANY(%s)", [all_ids])
        pg.execute("DELETE FROM limit_ladder_task_ledger WHERE command_id = ANY(%s)", [all_ids])


def test_audit_log_source_event_key_is_optional_but_unique(pg):
    init_pg_db(pg)
    suffix = uuid4().hex
    ids = [f"pytest_audit_{suffix}_{index}" for index in range(3)]
    key = f"pytest-event:{suffix}"
    try:
        pg.execute(
            "INSERT INTO audit_log "
            "(id,event_category,event_type,action,result,status) "
            "VALUES (%s,'task','task','legacy','success','completed')",
            [ids[0]],
        )
        pg.execute(
            "INSERT INTO audit_log "
            "(id,event_category,event_type,action,result,status,source_event_key) "
            "VALUES (%s,'task','task','new','success','completed',%s)",
            [ids[1], key],
        )
        with pytest.raises(StorageError):
            pg.execute(
                "INSERT INTO audit_log "
                "(id,event_category,event_type,action,result,status,source_event_key) "
                "VALUES (%s,'task','task','duplicate','success','completed',%s)",
                [ids[2], key],
            )
    finally:
        pg.execute("DELETE FROM audit_log WHERE id = ANY(%s)", [ids])


def test_audit_repository_returns_existing_id_for_replayed_source_event(pg):
    init_pg_db(pg)
    suffix = uuid4().hex
    key = f"pytest-replay:{suffix}"
    try:
        repository = AuditRepository(pg)
        first = repository.record(
            event_category="task",
            event_type="task",
            action="limit_ladder_requested",
            result="success",
            status="completed",
            source_event_key=key,
        )
        second = repository.record(
            event_category="task",
            event_type="task",
            action="limit_ladder_requested",
            result="success",
            status="completed",
            source_event_key=key,
        )
        assert first is not None and second == first
        assert int(pg.query_df(
            "SELECT count(*) AS n FROM audit_log WHERE source_event_key=%s",
            [key],
        ).iloc[0]["n"]) == 1
    finally:
        pg.execute("DELETE FROM audit_log WHERE source_event_key=%s", [key])
