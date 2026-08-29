"""个股走势关联板块 T1：当前态 DDL、目录与升级/回滚脚本。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from backend.storage.catalog import build_catalog
from backend.storage.ddl import M_STOCK_BOARD_CORRELATION_TABLES, init_db, list_tables
from backend.storage.duckdb_client import DuckDBClient

ROOT = Path(__file__).resolve().parents[2]
CREATE_SQL = ROOT / "agent-works/stock-board-correlation/create-stock-board-correlation.sql"
ROLLBACK_SQL = ROOT / "agent-works/stock-board-correlation/rollback-stock-board-correlation.sql"
EXPECTED_TABLES = {"stock_board_correlation", "stock_board_correlation_state"}


def test_init_db_creates_correlation_tables_idempotently():
    with DuckDBClient(db_path=":memory:") as client:
        first = init_db(client)
        second = init_db(client)

        assert EXPECTED_TABLES <= set(first)
        assert EXPECTED_TABLES <= set(second)
        assert set(M_STOCK_BOARD_CORRELATION_TABLES) == EXPECTED_TABLES
        assert EXPECTED_TABLES <= set(list_tables(client))

        champion_info = client.query_df("PRAGMA table_info('stock_board_correlation')")
        state_info = client.query_df("PRAGMA table_info('stock_board_correlation_state')")
        assert set(champion_info.loc[champion_info["pk"] > 0, "name"]) == {
            "code",
            "board_type",
        }
        assert list(state_info.loc[state_info["pk"] > 0, "name"]) == ["code"]
        assert {
            "has_industry_champion",
            "has_concept_champion",
            "algorithm_version",
        } <= set(state_info["name"])


def test_read_only_init_skips_ddl_and_keeps_existing_tables(tmp_path):
    db_path = tmp_path / "correlation-read-only.duckdb"
    with DuckDBClient(db_path=db_path) as writer:
        init_db(writer)

    with DuckDBClient(db_path=db_path, read_only=True) as reader:
        assert init_db(reader) == []
        assert EXPECTED_TABLES <= set(list_tables(reader))


def _valid_champion_values() -> tuple:
    return (
        "600000.SH",
        "industry",
        "881001",
        0.6,
        0.5,
        0.75,
        20,
        60,
        "high",
        "000001.SH",
        False,
        "2026-08-28",
        "2026-08-29 16:00:00",
        "v1",
    )


@pytest.mark.parametrize(
    ("column", "invalid_value"),
    [
        ("board_type", "theme"),
        ("score", float("nan")),
        ("corr_20", 1.01),
        ("sample_20", 14),
        ("sample_60", 39),
        ("confidence", "unknown"),
    ],
)
def test_correlation_table_rejects_invalid_champion(column, invalid_value):
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(M_STOCK_BOARD_CORRELATION_TABLES["stock_board_correlation"])
        columns = [
            "code",
            "board_type",
            "board_code",
            "score",
            "corr_20",
            "corr_60",
            "sample_20",
            "sample_60",
            "confidence",
            "benchmark_code",
            "benchmark_fallback",
            "as_of_date",
            "computed_at",
            "algorithm_version",
        ]
        values = list(_valid_champion_values())
        values[columns.index(column)] = invalid_value

        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                f"INSERT INTO stock_board_correlation ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
    finally:
        connection.close()


def test_correlation_tables_are_registered_in_catalog():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        client.execute(
            "INSERT INTO daily_bar (code, trade_date, close) "
            "VALUES ('600000.SH', DATE '2026-08-28', 10.0)"
        )
        client.execute(
            "INSERT INTO stock_board_correlation VALUES "
            "('600000.SH', 'industry', '881001', 0.6, 0.5, 0.75, 20, 60, 'high', "
            "'000001.SH', false, DATE '2026-08-28', TIMESTAMP '2026-08-29 16:00:00', 'v1')"
        )
        client.execute(
            "INSERT INTO stock_board_correlation_state VALUES "
            "('600000.SH', DATE '2026-08-28', TIMESTAMP '2026-08-29 16:00:00', "
            "'v1', '000001.SH', false, true, false)"
        )
        catalog = {item["table"]: item for item in build_catalog(client)}

        assert EXPECTED_TABLES <= set(catalog)
        assert catalog["stock_board_correlation"]["latest_time"].startswith("2026-08-28")
        assert catalog["stock_board_correlation"]["fresh"] is True
        assert catalog["stock_board_correlation_state"]["fresh"] is True
        assert catalog["stock_board_correlation"]["relations"]
        assert catalog["stock_board_correlation_state"]["fields"]


def test_upgrade_is_idempotent_and_rollback_only_drops_derived_tables():
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)")
        create_sql = CREATE_SQL.read_text(encoding="utf-8")
        connection.execute(create_sql)
        connection.execute(create_sql)
        assert EXPECTED_TABLES <= {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }

        connection.execute(ROLLBACK_SQL.read_text(encoding="utf-8"))
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        assert "keep_me" in remaining
        assert not EXPECTED_TABLES & remaining
    finally:
        connection.close()
