"""摘牌日为排他边界；元数据修正同时收敛日线、ST 和分时，保留历史事实。"""

from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError, StorageError
from backend.services import eod_dates
from backend.services.async_task import TaskCancelled
from backend.services.data_report import DataIntegrityReport
from backend.services.ingest import IngestionService
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.manual_delisting import apply_delisting
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository

CODE = "301139.SZ"
DAY = date(2024, 1, 4)


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    market = DuckDBClient(tmp_path / "lifecycle.duckdb")
    init_db(market)
    monkeypatch.setattr(eod_dates, "shanghai_now", lambda: datetime(
        2024, 1, 4, 22, tzinfo=eod_dates.SHANGHAI))
    market.execute("INSERT INTO trade_calendar VALUES "
                   "('2024-01-02',true),('2024-01-03',true),('2024-01-04',true)")
    market.execute("INSERT INTO stock_basic(code,name,board,list_date) VALUES "
                   "('301139.SZ','退市样本','创业板','2024-01-02'),"
                   "('600000.SH','其他股票','主板','2024-01-04')")
    market.execute("INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,"
                   "volume,amount,adj_factor,is_st) VALUES "
                   "('301139.SZ','2024-01-02',10,10,10,10,10,100,1000,1,false),"
                   "('301139.SZ','2024-01-03',10,10,10,10,10,100,1000,1,false),"
                   "('600000.SH','2024-01-04',10,10,10,10,10,100,1000,1,false)")
    market.execute("INSERT INTO stock_st_status_daily "
                   "SELECT code,trade_date,false,'baostock',NULL,'accurate',"
                   "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP FROM daily_bar")
    market.execute("INSERT INTO stock_share_capital_daily "
                   "(code,trade_date,total_share,float_share,total_source,float_source,"
                   "total_effective_date,float_effective_date) "
                   "SELECT code,trade_date,100,80,'fixture','fixture',trade_date,trade_date "
                   "FROM daily_bar")
    market.execute("INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv) "
                   "SELECT code,trade_date,1000,800 FROM daily_bar")
    market.execute("INSERT INTO stock_intraday_monitor(code,monitoring_start) "
                   "VALUES ('301139.SZ','2024-01-02')")
    DataIntegrityReport(market).scan_quality_issues(codes=[CODE])
    yield market
    market.close()


def _open(market, code=CODE):
    return market.query_df("SELECT issue_type,trade_date FROM data_quality_issue "
                           "WHERE code=? AND status='open'", [code])


def _issue_id(market):
    return int(market.query_df("SELECT id FROM data_quality_issue "
                               "WHERE code=? AND issue_type='stale'", [CODE]).iloc[0, 0])


def _service(market, snapshot):
    source = SimpleNamespace(name="baostock", get_basic_dates=lambda: snapshot,
                             get_industry=lambda: pd.DataFrame(columns=["code", "industry"]))
    ing = IngestionService.__new__(IngestionService)
    ing.c, ing.repo = market, MarketRepository(market)
    ing.s = SimpleNamespace(universe=SimpleNamespace(
        include_bse=False, boards=["主板", "创业板", "科创板"]))
    ing._source_for = lambda _: source
    return ing, source


def _snapshot(delist=DAY):
    return pd.DataFrame([{"code": CODE, "name": "退市样本", "list_date": date(2024, 1, 2),
                          "delist_date": delist}])


def test_manual_delisting_rechecks_all_domains_and_revoke_restores_gaps(lifecycle):
    iid = _issue_id(lifecycle)
    before = lifecycle.query_df("SELECT * FROM daily_bar ORDER BY code,trade_date")
    args = {"issue_id": iid, "delist_date": str(DAY), "reason": "已核对摘牌公告"}
    result = apply_delisting(lifecycle, args, SimpleNamespace(tid="manual-lifecycle"))
    assert result["resolved"] == 4  # stale/history/ST/当日分时；历史分时缺口继续保留。
    remaining = _open(lifecycle)
    assert set(remaining.issue_type) == {"intraday_gap"}
    assert set(remaining.trade_date.dt.date) == {date(2024, 1, 2), date(2024, 1, 3)}
    ing, _ = _service(lifecycle, _snapshot())
    assert CODE not in ing._stock_basic_from_db(as_of=DAY).code.tolist()
    assert CODE in ing._stock_basic_from_db(as_of=date(2024, 1, 3)).code.tolist()
    assert IntradayArchiveService(lifecycle)._coverage_facts([CODE]).trade_date.max().date() < DAY
    pd.testing.assert_frame_equal(before, lifecycle.query_df(
        "SELECT * FROM daily_bar ORDER BY code,trade_date"))
    apply_delisting(lifecycle, {**args, "delist_date": None, "reason": "撤销人工覆盖"},
                    SimpleNamespace(tid="revoke-lifecycle"))
    assert {"stale", "history_data_gap", "st_status_missing"}.issubset(_open(lifecycle).issue_type)
    assert DAY in _open(lifecycle).query("issue_type=='intraday_gap'").trade_date.dt.date.tolist()


def test_manual_delisting_rolls_back_metadata_when_recheck_fails(lifecycle, monkeypatch):
    before = lifecycle.query_df("SELECT * FROM data_quality_issue ORDER BY id")
    monkeypatch.setattr(IntradayArchiveService, "sync", lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("scan unavailable")))
    with pytest.raises(StorageError, match="scan unavailable"):
        apply_delisting(lifecycle, {"issue_id": _issue_id(lifecycle), "delist_date": str(DAY),
                                   "reason": "公告"}, SimpleNamespace(tid="rollback"))
    assert pd.isna(lifecycle.query_df("SELECT delist_date FROM stock_basic WHERE code=?",
                                     [CODE]).iloc[0, 0])
    assert lifecycle.query_df("SELECT * FROM data_update_log WHERE source='manual:delist_date'").empty
    pd.testing.assert_frame_equal(before, lifecycle.query_df(
        "SELECT * FROM data_quality_issue ORDER BY id"))


def test_automatic_refresh_rechecks_changed_lifecycle_only(lifecycle, monkeypatch):
    other = _open(lifecycle, "600000.SH").copy()
    calls = []
    original = IntradayArchiveService.sync
    def sync(service, codes=None, **kwargs):
        calls.append(codes)
        return original(service, codes, **kwargs)
    monkeypatch.setattr(IntradayArchiveService, "sync", sync)
    ing, _ = _service(lifecycle, _snapshot())
    assert ing.enrich_basic_dates() == 1
    assert calls == [[CODE]]
    assert not {"stale", "history_data_gap", "st_status_missing"} & set(_open(lifecycle).issue_type)
    assert DAY not in _open(lifecycle).trade_date.dt.date.tolist()
    calls.clear()
    assert ing.enrich_basic_dates() == 1
    assert calls == []  # 幂等刷新不增加全市场分钟扫描。
    pd.testing.assert_frame_equal(other, _open(lifecycle, "600000.SH"))


def test_automatic_refresh_respects_manual_date(lifecycle, monkeypatch):
    apply_delisting(lifecycle, {"issue_id": _issue_id(lifecycle), "delist_date": str(DAY),
                               "reason": "公告"}, SimpleNamespace(tid="protected"))
    calls = []
    monkeypatch.setattr(IntradayArchiveService, "sync", lambda *a, **kw: calls.append(kw))
    ing, _ = _service(lifecycle, _snapshot(None))
    ing.enrich_basic_dates()
    row = lifecycle.query_df("SELECT delist_date,delist_date_reported FROM stock_basic "
                             "WHERE code=?", [CODE]).iloc[0]
    assert row.delist_date.date() == DAY and pd.isna(row.delist_date_reported)
    assert calls == []


@pytest.mark.parametrize("failure", ["empty", "network", "cancel"])
def test_failed_refresh_preserves_dates_and_issues(lifecycle, failure):
    before = lifecycle.query_df("SELECT * FROM stock_basic ORDER BY code")
    issues = lifecycle.query_df("SELECT * FROM data_quality_issue ORDER BY id")
    ing, source = _service(lifecycle, pd.DataFrame() if failure == "empty" else _snapshot())
    if failure == "network":
        source.get_basic_dates = lambda: (_ for _ in ()).throw(DataSourceError("network error"))
    if failure == "cancel":
        source.get_industry = lambda: (_ for _ in ()).throw(TaskCancelled())
    with pytest.raises(TaskCancelled if failure == "cancel" else DataSourceError):
        ing.enrich_basic_dates()
    pd.testing.assert_frame_equal(before, lifecycle.query_df("SELECT * FROM stock_basic ORDER BY code"))
    pd.testing.assert_frame_equal(issues, lifecycle.query_df("SELECT * FROM data_quality_issue ORDER BY id"))


def test_st_refresh_does_not_request_or_require_delisting_day(lifecycle):
    lifecycle.execute("UPDATE stock_basic SET delist_date=? WHERE code=?", [DAY, CODE])
    ing, _ = _service(lifecycle, _snapshot())
    requests = []
    def fetch(code, start, end, **kwargs):
        requests.append((code, start, end))
        return SimpleNamespace(name="baostock"), pd.DataFrame([
            {"trade_date": day, "is_st": False, "trade_status": 1}
            for day in [date(2024, 1, 2), date(2024, 1, 3)]])
    ing._fetch_st_status_rows = fetch
    result = ing.refresh_st_status(codes=[CODE])
    assert result["fail"] == 0 and result["publication_status"] == "ready"
    assert requests == [(CODE, date(2024, 1, 2), date(2024, 1, 3))]
    assert lifecycle.query_df("SELECT * FROM stock_st_status_daily WHERE code=? AND trade_date=?",
                             [CODE, DAY]).empty


def test_full_market_refresh_limits_minute_recheck_to_changed_stock(lifecycle, monkeypatch):
    # 代表性名册规模：真实读取、合并、落库及收尾入口，只有一只股票变更存续期。
    records = pd.DataFrame([
        {"code": f"{600001 + i}.SH", "name": "规模样本", "list_date": DAY,
         "delist_date": None, "board": "主板"} for i in range(5000)
    ])
    MarketRepository(lifecycle).upsert_stock_basic(records)
    snapshot = pd.concat([records.drop(columns=["board"]), _snapshot()], ignore_index=True)
    ing, _ = _service(lifecycle, snapshot)
    calls = []
    original = IntradayArchiveService.sync
    def sync(service, codes=None, **kwargs):
        calls.append(codes)
        return original(service, codes, **kwargs)
    monkeypatch.setattr(IntradayArchiveService, "sync", sync)
    assert ing.enrich_basic_dates() == 5001
    assert calls == [[CODE]]
    assert len(lifecycle.query_df("SELECT code FROM stock_basic")) == 5002
    assert lifecycle.query_df("SELECT delist_date FROM stock_basic WHERE code=?",
                              [CODE]).iloc[0, 0].date() == DAY
