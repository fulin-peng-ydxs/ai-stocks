"""全历史日线缺口：存续边界、真实停牌、规模扫描与统一复检。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services.data_report import DataIntegrityReport
from backend.services.data_verify import DataVerifier
from backend.services.history_quality import HistoryQualityService
from backend.services.ingest import IngestionService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market():
    with DuckDBClient(":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO trade_calendar(trade_date,is_open) SELECT DATE '2017-01-02'+i::INTEGER,true FROM range(5) t(i)"
        )
        c.execute(
            "INSERT INTO stock_basic(code,list_date,delist_date) VALUES ('A.SH','2017-01-02',NULL),('B.SZ','2017-01-03','2017-01-06'),('C.BJ','2017-01-02',NULL)"
        )
        c.execute(
            "INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH','2017-01-04',10),('A.SH','2017-01-06',10),('B.SZ','2017-01-04',10)"
        )
        yield c


def test_missing_includes_leading_and_delisted_but_excludes_confirmed_suspension(market):
    q = HistoryQualityService(market)
    assert q.dates("A.SH") == [date(2017, 1, 2), date(2017, 1, 3), date(2017, 1, 5)]
    assert q.dates("B.SZ") == [date(2017, 1, 3), date(2017, 1, 5)]
    assert q.dates("C.BJ") == []
    market.execute("INSERT INTO stock_suspension(code,trade_date) VALUES ('A.SH','2017-01-03')")
    assert len(q.dates("A.SH")) == 2
    v = DataVerifier(market, quiet=True)
    v.check_history_coverage()
    assert not v.results[-1][1] and "缺 4 " in v.results[-1][2]


def test_ledger_identity_recheck_and_other_stock_preserved(market):
    q = HistoryQualityService(market)
    r = DataIntegrityReport(market)
    r._upsert_scan_issues(q.issues(), ("history_data_gap",))
    iid = market.query_df("SELECT id FROM data_quality_issue WHERE code='A.SH'").iloc[0, 0]
    for day in q.dates("A.SH"):
        market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('A.SH',?,10)", [day])
    assert r.recheck_clean("history_data_gap", "A.SH", None)
    r._upsert_scan_issues(q.issues(), ("history_data_gap",))
    assert (
        market.query_df("SELECT status FROM data_quality_issue WHERE id=?", [int(iid)]).iloc[0, 0]
        == "resolved"
    )
    assert not r.recheck_clean("history_data_gap", "B.SZ", None)


@pytest.mark.parametrize("status,expected", [(None, 0), (1, 0), (0, 3)])
def test_empty_source_never_implies_suspension(market, status, expected):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing.ingest_one_daily = lambda *a, **kw: 0
    ing._bao_source = lambda: SimpleNamespace()
    ing._fetch_st_status_rows = lambda *a, **kw: (
        "baostock",
        pd.DataFrame()
        if status is None
        else pd.DataFrame(
            {"trade_date": HistoryQualityService(market).dates("A.SH"), "trade_status": status}
        ),
    )
    result = ing.reconcile_gaps("A.SH", full_history=True)
    assert result["confirmed"] == expected
    assert len(HistoryQualityService(market).dates("A.SH")) == 3 - expected


def test_scale_240000_expected_dates_aggregate_and_real_repair(market):
    market.execute("DELETE FROM daily_bar")
    market.execute("DELETE FROM stock_basic")
    market.execute("DELETE FROM trade_calendar")
    market.execute(
        "INSERT INTO trade_calendar(trade_date,is_open) SELECT DATE '2017-01-01'+i::INTEGER,true FROM range(2400) t(i)"
    )
    market.execute(
        "INSERT INTO stock_basic(code,list_date) SELECT i::VARCHAR||'.SH',DATE '2017-01-01' FROM range(100) t(i)"
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT code,DATE '2017-01-01'+2399,10 FROM stock_basic"
    )
    q = HistoryQualityService(market)
    assert int(q.aggregate().missing_days.sum()) == 239900
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT '0.SH',trade_date,10 FROM trade_calendar WHERE trade_date<DATE '2017-01-01'+2399"
    )
    assert q.aggregate(["0.SH"]).empty
    assert len(q.aggregate()) == 99


def test_conflicting_status_does_not_confirm_suspension(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing.ingest_one_daily = lambda *a, **kw: 0
    ing._bao_source = lambda: SimpleNamespace()
    ing._fetch_st_status_rows = lambda *a, **kw: (
        "baostock",
        pd.DataFrame({"trade_date": ["2017-01-02", "2017-01-02"], "trade_status": [0, 1]}),
    )
    assert ing.reconcile_gaps("A.SH", full_history=True)["confirmed"] == 0


def test_suspension_confirmed_inside_ingestion_is_counted(market):
    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    def collect(*args, **kwargs):
        DataIntegrityReport(market).confirm_suspension('A.SH', HistoryQualityService(market).dates('A.SH'))
        return 0
    ing.ingest_one_daily = collect
    result = ing.reconcile_gaps('A.SH', full_history=True)
    assert result['confirmed'] == 3
    assert IngestionService.reconcile_note(result) == '确认停牌 3 天'
