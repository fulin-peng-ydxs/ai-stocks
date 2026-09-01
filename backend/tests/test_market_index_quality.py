"""配置市场指数的质检、恢复、鲜活度和报告口径回归。"""

from __future__ import annotations

from datetime import date

import pytest

from backend.services.async_task import _recover_one
from backend.services.data_report import DataIntegrityReport
from backend.services.market_benchmark import configured_benchmark_codes
from backend.storage.catalog import build_catalog
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture()
def client(tmp_path):
    c = DuckDBClient(db_path=str(tmp_path / "market-index-quality.duckdb"))
    init_db(c)
    yield c
    c.close()


def _seed_complete_indices(c: DuckDBClient) -> list[date]:
    days = [date(2024, 1, d) for d in (2, 3, 4, 5)]
    for d in days:
        c.execute("INSERT INTO trade_calendar (trade_date, is_open) VALUES (?, true)", [d])
    c.execute(
        "INSERT INTO daily_bar (code, trade_date, close) VALUES ('A.SH', ?, 10)",
        [days[-1]],
    )
    for code in configured_benchmark_codes():
        for d in days:
            c.execute(
                "INSERT INTO index_bar "
                "(index_code, trade_date, open, high, low, close, volume, amount) "
                "VALUES (?, ?, 100, 102, 99, 101, 1000, 2000)",
                [code, d],
            )
    return days


def test_scan_market_indices_detects_and_converges_all_issue_types(client):
    days = _seed_complete_indices(client)
    client.execute(
        "DELETE FROM index_bar WHERE index_code='000300.SH' AND trade_date=?", [days[2]]
    )
    client.execute(
        "DELETE FROM index_bar WHERE index_code='000001.SH' AND trade_date=?", [days[3]]
    )
    client.execute(
        "UPDATE index_bar SET high=90, low=99 "
        "WHERE index_code='000688.SH' AND trade_date=?",
        [days[1]],
    )

    rep = DataIntegrityReport(client)
    first = rep.scan_market_index_quality()
    assert first == {"index_gap": 1, "index_gap_daily": 2, "index_invalid": 1}
    ids_before = client.query_df(
        "SELECT issue_type, code, trade_date, id FROM data_quality_issue "
        "WHERE status='open' AND issue_type LIKE 'market_index_%' ORDER BY id"
    )["id"].tolist()
    rep.scan_market_index_quality()
    ids_after = client.query_df(
        "SELECT id FROM data_quality_issue "
        "WHERE status='open' AND issue_type LIKE 'market_index_%' ORDER BY id"
    )["id"].tolist()
    assert ids_after == ids_before

    client.execute(
        "INSERT INTO index_bar "
        "(index_code, trade_date, open, high, low, close, volume, amount) "
        "VALUES ('000300.SH', ?, 100, 102, 99, 101, 1000, 2000), "
        "('000001.SH', ?, 100, 102, 99, 101, 1000, 2000)",
        [days[2], days[3]],
    )
    client.execute(
        "UPDATE index_bar SET high=102, low=99 "
        "WHERE index_code='000688.SH' AND trade_date=?",
        [days[1]],
    )
    assert rep.scan_market_index_quality() == {
        "index_gap": 0, "index_gap_daily": 0, "index_invalid": 0,
    }
    assert int(client.query_df(
        "SELECT count(*) AS n FROM data_quality_issue "
        "WHERE status='open' AND issue_type LIKE 'market_index_%'"
    ).iloc[0]["n"]) == 0


@pytest.mark.parametrize(
    ("issue_type", "problem_day"),
    [
        ("market_index_gap", date(2024, 1, 5)),
        ("market_index_gap_daily", date(2024, 1, 4)),
        ("market_index_invalid", date(2024, 1, 3)),
    ],
)
def test_market_index_fix_reingests_and_resolves(client, issue_type, problem_day):
    days = _seed_complete_indices(client)
    code = "000300.SH"
    if issue_type == "market_index_invalid":
        client.execute(
            "UPDATE index_bar SET close=-1 WHERE index_code=? AND trade_date=?",
            [code, problem_day],
        )
    else:
        client.execute(
            "DELETE FROM index_bar WHERE index_code=? AND trade_date=?",
            [code, problem_day],
        )
    rep = DataIntegrityReport(client)
    rep.scan_market_index_quality()
    issue_id = int(client.query_df(
        "SELECT id FROM data_quality_issue "
        "WHERE code=? AND issue_type=? AND trade_date=? AND status='open'",
        [code, issue_type, problem_day],
    ).iloc[0]["id"])
    calls: list[tuple] = []

    class _Ingest:
        def ingest_indices(self, start, end, ctx=None, codes=None):
            calls.append((codes[0], start, end))
            target_days = [d for d in days if start <= d <= end]
            for d in target_days:
                client.execute(
                    "INSERT INTO index_bar "
                    "(index_code, trade_date, open, high, low, close, volume, amount) "
                    "VALUES (?, ?, 100, 102, 99, 101, 1000, 2000) "
                    "ON CONFLICT (index_code, trade_date) DO UPDATE SET "
                    "open=excluded.open, high=excluded.high, low=excluded.low, "
                    "close=excluded.close, volume=excluded.volume, amount=excluded.amount",
                    [codes[0], d],
                )
            return len(target_days)

    class _Ctx:
        tid = "fix_market_index"

        def __init__(self):
            self.logs: list[str] = []

        def log(self, message, level="info"):
            self.logs.append(message)

    clean, _, _ = _recover_one(client, rep, _Ingest(), _Ctx(), issue_id)
    assert clean is True
    assert calls
    assert client.query_df(
        "SELECT status FROM data_quality_issue WHERE id=?", [issue_id]
    ).iloc[0]["status"] == "resolved"
    assert rep.recheck_clean(issue_type, code, problem_day) is True


def test_catalog_market_index_freshness_requires_every_configured_index(client):
    days = _seed_complete_indices(client)
    catalog = {item["table"]: item for item in build_catalog(client)}
    assert catalog["index_bar"]["fresh"] is True

    client.execute(
        "DELETE FROM index_bar WHERE index_code='399006.SZ' AND trade_date=?", [days[-1]]
    )
    DataIntegrityReport(client).scan_market_index_quality()
    catalog = {item["table"]: item for item in build_catalog(client)}
    assert catalog["index_bar"]["fresh"] is False
    assert catalog["index_bar"]["open_issues"] >= 1


def test_index_coverage_limits_rows_to_requested_window(client):
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) VALUES "
        "(DATE '2024-01-02', true), (DATE '2024-01-03', true)"
    )
    client.execute(
        "INSERT INTO index_bar (index_code, trade_date, close) VALUES "
        "('000300.SH', DATE '2023-12-29', 100), "
        "('000300.SH', DATE '2024-01-02', 101), "
        "('000300.SH', DATE '2024-01-03', 102)"
    )
    result = DataIntegrityReport(client).index_coverage(date(2024, 1, 2), date(2024, 1, 3))
    assert result["calendar_open_days"] == 2
    assert result["indices"][0]["days"] == 2
    assert result["indices"][0]["coverage"] == 1.0
