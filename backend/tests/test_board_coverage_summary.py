"""板块概览保留真实覆盖，仅以有效人工确认免除对应缺失的补采提示。"""

from datetime import date

import pytest

from backend.api.data_admin import _board_stage
from backend.services.data_report import DataIntegrityReport


@pytest.fixture
def coverage_market(market):
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600001.SH','2026-10-20',10)"
    )
    market.execute(
        "INSERT INTO board_dict(board_code,name,board_type,has_members,has_bar,member_snapshot_at) "
        "VALUES ('A','甲','concept',true,true,'2026-10-20'),"
        "('B','乙','industry',true,true,'2026-10-20')"
    )
    market.execute(
        "INSERT INTO board_bar(board_code,trade_date,close) VALUES "
        "('A','2026-10-20',100),('B','2026-10-20',100)"
    )
    market.execute(
        "INSERT INTO board_fund_flow(board_code,snapshot_date,period) VALUES "
        "('A','2026-10-16','即时'),('B','2026-10-16','即时')"
    )
    return market


def _ignore(market, code, *, scope="occurrence", day="2026-10-20", active=True,
            issue_type="board_fund_missing", status="ignored"):
    market.execute(
        "INSERT INTO data_quality_issue "
        "(id,code,trade_date,issue_type,status,ignore_scope,ignore_active) "
        "VALUES (nextval('seq_quality_issue'),?,?,?,?,?,?)",
        [code, day, issue_type, status, scope, active],
    )


def test_overview_uses_current_confirmation_without_faking_data(coverage_market):
    _ignore(coverage_market, "A")
    _ignore(coverage_market, "B", scope="object", day="2026-10-13")
    result = _board_stage(coverage_market)
    assert result is not None
    assert result["fund_target"] == 2 and result["fund_ready"] == 0
    assert result["latest_fund_date"] == "2026-10-16"
    assert result["coverage_handling"]["fund"] == {"ignored": 2, "pending": 0}
    assert result["coverage_handling"]["bar"] == {"ignored": 0, "pending": 0}
    coverage_market.execute("UPDATE data_quality_issue SET ignore_active=false WHERE code='A'")
    assert _board_stage(coverage_market)["coverage_handling"]["fund"] == {
        "ignored": 1, "pending": 1,
    }


@pytest.mark.parametrize("override", [
    {"day": "2026-10-19"},
    {"active": False},
    {"status": "resolved"},
    {"issue_type": "board_fund_stale"},
])
def test_wrong_date_inactive_or_unrelated_confirmation_cannot_hide_missing(
    coverage_market, override
):
    _ignore(coverage_market, "A", **override)
    _ignore(coverage_market, "OTHER", scope="object")
    _ignore(coverage_market, None, issue_type="board_fund_stale", scope="object")
    assert _board_stage(coverage_market)["coverage_handling"]["fund"] == {
        "ignored": 0, "pending": 2,
    }


def test_read_only_summary_preserves_ignore_lifecycle_and_legacy_rules(coverage_market):
    _ignore(coverage_market, "A", scope=None, active=None, day="2026-10-13")
    _ignore(coverage_market, "B", day="2026-10-19")
    before = coverage_market.query_df("SELECT * FROM data_quality_issue ORDER BY id")
    assert _board_stage(coverage_market)["coverage_handling"]["fund"] == {
        "ignored": 1, "pending": 1,
    }
    assert before.equals(coverage_market.query_df("SELECT * FROM data_quality_issue ORDER BY id"))


def test_repaired_data_and_future_snapshots_do_not_count_as_confirmed_missing(coverage_market):
    _ignore(coverage_market, "A", scope="object")
    _ignore(coverage_market, "B", scope="object")
    coverage_market.execute(
        "INSERT INTO board_fund_flow(board_code,snapshot_date,period) VALUES "
        "('A','2026-10-20','即时'),('B','2026-10-21','即时')"
    )
    result = _board_stage(coverage_market)
    assert result["fund_ready"] == 1
    assert result["coverage_handling"]["fund"] == {"ignored": 1, "pending": 0}


def test_index_and_member_confirmations_share_matching_rules(coverage_market, monkeypatch):
    monkeypatch.setattr("backend.services.data_report._shanghai_today", lambda: date(2026, 10, 22))
    coverage_market.execute("DELETE FROM board_bar WHERE board_code='A'")
    coverage_market.execute("UPDATE board_dict SET member_snapshot_at=NULL WHERE board_code='B'")
    _ignore(coverage_market, "A", issue_type="board_index_gap_daily")
    _ignore(coverage_market, "A", issue_type="board_index_gap", scope="object")
    _ignore(coverage_market, "B", issue_type="board_member_incomplete", day="2026-10-22")
    result = _board_stage(coverage_market)
    assert result["bar_ready"] == result["member_ready"] == 1
    assert result["coverage_handling"]["bar"] == {"ignored": 1, "pending": 0}
    assert result["coverage_handling"]["member"] == {"ignored": 1, "pending": 0}


@pytest.mark.parametrize("undeclared_board", [False, True])
def test_empty_or_undeclared_universe_has_no_missing_or_confirmed_counts(market, undeclared_board):
    if undeclared_board:
        market.execute(
            "INSERT INTO board_dict(board_code,name,board_type,has_members,has_bar) "
            "VALUES ('UNKNOWN','未声明能力','concept',NULL,NULL)"
        )
    result = DataIntegrityReport(market).board_coverage_summary(None, None)
    for dimension in ("member", "bar", "fund"):
        assert result[f"{dimension}_ready"] == result[f"{dimension}_target"] == 0
        assert result["coverage_handling"][dimension] == {"ignored": 0, "pending": 0}
