"""采集收尾与主动质检共用规则：范围隔离、幂等、异常和批处理规模。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.config import get_settings
from backend.services.async_task import TaskCancelled
from backend.services.collection_quality import checked_collection, include_collection_scope
from backend.services.data_report import DataIntegrityReport
from backend.services.ingest import IngestionService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


@pytest.fixture
def market(monkeypatch, tmp_path):
    settings = get_settings().model_copy(deep=True)
    monkeypatch.setattr("backend.config.get_effective_settings", lambda: settings)
    monkeypatch.setattr("backend.config.settings.get_effective_settings", lambda: settings)
    with DuckDBClient(str(tmp_path / "market.duckdb")) as c:
        init_db(c)
        c.execute("INSERT INTO trade_calendar VALUES ('2024-01-02',true),('2024-01-03',true)")
        c.execute("INSERT INTO stock_basic(code,name,board,list_date) VALUES "
                  "('600001.SH','甲','主板','2024-01-02'),('600002.SH','乙','主板','2024-01-02')")
        c.execute("INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,volume,amount) "
                  "SELECT code,d,10,10,10,10,10,100,2000 FROM stock_basic "
                  "CROSS JOIN (VALUES (DATE '2024-01-02'),(DATE '2024-01-03')) t(d)")
        yield c


def ledger(c):
    return c.query_df("SELECT id,code,issue_type,trade_date,status,detail FROM data_quality_issue ORDER BY id")


def test_stock_scope_keeps_other_ids_and_uses_same_full_rules(market):
    rep = DataIntegrityReport(market)
    rep.scan_quality_issues(include_intraday=False)
    before = ledger(market)
    other = before[before.code == "600002.SH"]
    market.execute("UPDATE daily_bar SET amount=1000 WHERE code='600001.SH'")
    scoped = rep.scan_quality_issues(codes=["600001.SH"], include_intraday=False)
    assert scoped["price_volume_mismatch_rows"] == 0
    pd.testing.assert_frame_equal(ledger(market).query("code == '600002.SH'"), other)
    assert set(ledger(market).query("issue_type == 'price_volume_mismatch' and code == '600001.SH'").status) == {"resolved"}
    # 新一轮仍有问题的记录原地更新，ID 不变化。
    keep = ledger(market).query("status == 'open'").id.tolist()
    rep.scan_quality_issues(codes=["600001.SH"], include_intraday=False)
    assert ledger(market).query("status == 'open'").id.tolist() == keep
    full = rep.scan_quality_issues(include_intraday=False)
    assert full["price_volume_mismatch_rows"] == len(other.query("issue_type == 'price_volume_mismatch'"))


def test_empty_scope_is_noop_and_scan_failure_keeps_old_ledger(market, monkeypatch):
    rep = DataIntegrityReport(market)
    rep.scan_quality_issues(include_intraday=False)
    before = ledger(market)
    rep.scan_quality_issues(codes=[], include_intraday=False)
    pd.testing.assert_frame_equal(ledger(market), before)
    monkeypatch.setattr(rep, "_collect_st_status_issues", lambda codes: (_ for _ in ()).throw(RuntimeError("scan failed")))
    with pytest.raises(RuntimeError, match="scan failed"):
        rep.scan_quality_issues(codes=["600001.SH"], include_intraday=False)
    pd.testing.assert_frame_equal(ledger(market), before)


def test_scoped_frame_matches_full_and_does_not_pollute_full_cache(market):
    rep = DataIntegrityReport(market)
    full, latest = rep._coverage_frame()
    scoped, same_latest = rep._coverage_frame(codes=["600001.SH"])
    pd.testing.assert_frame_equal(scoped.reset_index(drop=True), full[full.code == "600001.SH"].reset_index(drop=True))
    again, _ = rep._coverage_frame()
    assert len(again) == 2 and latest == same_latest


def test_index_collection_partial_source_failure_checks_local_facts_only(market):
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = market, MarketRepository(market)
    def fetch(code, start, end):
        if code == "000300.SH":
            raise RuntimeError("network failed")
        return pd.DataFrame([{"index_code": code, "trade_date": end, "open": 10,
                              "high": 11, "low": 9, "close": 10}])
    svc.src = SimpleNamespace(name="fake", get_index_bar=fetch)
    svc.ingest_indices(date(2024, 1, 2), date(2024, 1, 3), codes=["000001.SH", "000300.SH"])
    gaps = ledger(market).query("issue_type == 'market_index_gap'")
    assert gaps.code.tolist() == ["000300.SH"]
    assert not ledger(market).code.isin(["000688.SH", "600001.SH"]).any()
    assert "network failed" not in " ".join(ledger(market).detail)
    before = ledger(market)
    DataIntegrityReport(market).scan_market_index_quality(codes=[])
    pd.testing.assert_frame_equal(ledger(market), before)
    # 主动质检仍扫描所有配置指数。
    assert DataIntegrityReport(market).scan_market_index_quality()["index_gap"] > 1


def test_board_scope_keeps_unrelated_and_source_level_issues(market):
    market.execute("INSERT INTO board_dict(board_code,name,board_type,has_bar,has_members) VALUES "
                   "('B1','板一','concept',true,true),('B2','板二','industry',true,true)")
    market.execute("INSERT INTO board_fund_flow(board_code,snapshot_date,period) VALUES ('B2','2024-01-02','即时')")
    rep = DataIntegrityReport(market)
    rep.scan_board_quality()
    before = ledger(market)
    rep.scan_board_quality(codes=["B1"])
    pd.testing.assert_frame_equal(ledger(market).query("code != 'B1' or code.isnull()"), before.query("code != 'B1' or code.isnull()"))
    assert ledger(market).query("issue_type == 'board_fund_stale'").status.tolist() == ["open"]
    rep.scan_board_quality(codes=[])
    pd.testing.assert_frame_equal(ledger(market), before)


class BatchCollector:
    def __init__(self, client):
        self.c = client

    @checked_collection
    def collect(self, codes, ctx=None, fail=False):
        for code in codes:
            self.stage([code])
        if fail:
            raise RuntimeError("fatal source error")
        return {"fail": 1}  # 部分失败正常返回，也要按计划检查本地事实。

    @checked_collection
    def stage(self, codes):
        include_collection_scope(self, "stock", codes)
        return 0


def test_nested_batches_scan_once_and_partial_result_has_quality(market, monkeypatch):
    original = DataIntegrityReport.scan_quality_issues
    calls = []
    def scan(report, **kwargs):
        calls.append(kwargs)
        return original(report, **kwargs)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", scan)
    result = BatchCollector(market).collect(["600001.SH", "600002.SH"])
    assert calls == [{"codes": ["600001.SH", "600002.SH"], "include_intraday": False}]
    assert result["fail"] == 1 and result["quality"]["stock"]["price_volume_mismatch_rows"] == 4


def test_cancel_or_fatal_error_never_reports_successful_quality(market):
    collector = BatchCollector(market)
    with pytest.raises(RuntimeError, match="fatal source error"):
        collector.collect(["600001.SH"], fail=True)
    def cancel():
        raise TaskCancelled()
    with pytest.raises(TaskCancelled):
        collector.collect(["600001.SH"], ctx=SimpleNamespace(check_cancel=cancel))
    assert ledger(market).empty
    assert collector._collection_quality_batch is None
    assert collector.collect(["600002.SH"])["quality"]["stock"]["price_volume_mismatch_rows"] == 2


def test_quality_failure_propagates_without_rolling_back_collection(market, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("quality unavailable")
    monkeypatch.setattr(DataIntegrityReport, "scan_market_index_quality", fail)
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = market, MarketRepository(market)
    svc.src = SimpleNamespace(name="fake", get_index_bar=lambda code, start, end: pd.DataFrame([
        {"index_code": code, "trade_date": end, "open": 10, "high": 11, "low": 9, "close": 10}]))
    with pytest.raises(RuntimeError, match="quality unavailable"):
        svc.ingest_indices(date(2024, 1, 2), date(2024, 1, 3), codes=["000001.SH"])
    assert market.query_df("SELECT count(*) FROM index_bar").iloc[0, 0] == 1
    assert svc._collection_quality_batch is None


def test_scoped_scan_representative_history_volume(market):
    # 96 只 × 1000 个交易日；真实 SQL 扫描、规则计算与台账更新，不用 Mock 扫描替代。
    market.execute("DELETE FROM daily_bar")
    market.execute("DELETE FROM stock_basic")
    market.execute("DELETE FROM trade_calendar")
    market.execute("INSERT INTO trade_calendar SELECT DATE '2020-01-01' + i::INTEGER,true FROM range(1000) t(i)")
    market.execute("INSERT INTO stock_basic(code,board,list_date) SELECT (600000+i)::VARCHAR||'.SH','主板',DATE '2020-01-01' FROM range(96) t(i)")
    market.execute("INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,volume,amount) "
                   "SELECT code,trade_date,10,10,10,10,10,100,2000 FROM stock_basic CROSS JOIN trade_calendar")
    result = DataIntegrityReport(market).scan_quality_issues(codes=["600000.SH"], include_intraday=False)
    assert result["price_volume_mismatch_rows"] == 1000
    assert set(ledger(market).code) == {"600000.SH"}


def test_backfill_real_collection_to_ledger_with_batch_scale(market, monkeypatch):
    """真实批次入口，96股×100日只替换源响应；清洗、ST、因子、股本及台账均实际执行。"""
    from backend.services import ingest as module

    market.execute("DELETE FROM daily_bar")
    market.execute("DELETE FROM stock_basic")
    market.execute("DELETE FROM trade_calendar")
    days = list(pd.bdate_range("2024-01-02", periods=100).date)
    codes = [f"{600000 + i}.SH" for i in range(96)]
    calls = []

    class Transport:
        name = "fake"

        def supports(self, capability):
            return True

        def get_trade_calendar(self, start, end):
            return pd.DataFrame({"trade_date": days, "is_open": True})

        def get_stock_list(self):
            return pd.DataFrame({"code": codes, "code6": [c[:6] for c in codes], "name": codes})

        def get_index_bar(self, code, start, end):
            return pd.DataFrame({"index_code": code, "trade_date": days, "open": 10,
                                 "high": 10, "low": 10, "close": 10})

        def get_daily_bar(self, code, start, end):
            calls.append(code)
            return pd.DataFrame({"code": code, "trade_date": days, "open": 10,
                                 "high": 10, "low": 10, "close": 10, "pre_close": 10,
                                 "volume": 100, "amount": 2000, "adj_factor": 1, "turnover_rate": 1})

        def get_st_status(self, code, start, end):
            return pd.DataFrame({"code": code, "trade_date": days, "is_st": False, "trade_status": 1})

    service = IngestionService.__new__(IngestionService)
    service.c, service.repo = market, MarketRepository(market)
    service.s = get_settings().model_copy(deep=True)
    service.src = Transport()
    service._bao = None
    monkeypatch.setattr(service, "_history_window", lambda *args: (days[0], days[-1]))
    monkeypatch.setattr(module, "get_source", lambda name: Transport())
    result = service.backfill(codes=codes, concurrency=4)
    assert result["ok"] == 96 and result["fail"] == 0 and result["rows"] == 9600
    assert sorted(calls) == codes
    assert result["quality"]["stock"]["price_volume_mismatch_rows"] == 9600
    assert result["quality"]["stock"]["st_status_missing_rows"] == 0
    assert market.query_df("SELECT count(*) FROM daily_bar WHERE adj_factor_clean IS NOT NULL").iloc[0, 0] == 9600
    assert set(ledger(market).query("issue_type == 'capital_gap'").code) == set(codes)
    # 已覆盖的重跑跳过网络，但仍对本次完整计划质检并复用原问题 ID。
    before = ledger(market).id.tolist()
    resumed = service.backfill(codes=codes, concurrency=4)
    assert resumed["skip"] == 96 and len(calls) == 96
    assert ledger(market).id.tolist() == before


@pytest.mark.parametrize("codes,expect_scan", [(None, False), (["600001.SH"], True)])
def test_daily_quality_reuses_completed_full_scopes(market, monkeypatch, codes, expect_scan):
    from backend.services.intraday_archive import IntradayArchiveService
    from backend.services.pipeline import DailyPipeline

    stock = {"intraday": None, "stale_rows": 0}
    index, board = {"index_gap": 0}, {"fund_missing": 0}
    monkeypatch.setattr(IngestionService, "__init__", lambda *args: None)
    monkeypatch.setattr(IngestionService, "update", lambda *args, **kwargs: {
        "quality": {"stock": stock, "market_index": index}, "quality_scopes": {"stock": None}})
    monkeypatch.setattr(IngestionService, "ingest_board", lambda *args, **kwargs: {
        "quality": {"board": board}})
    scans = []
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", lambda *args: scans.append("stock") or {})
    def unexpected(*args, **kwargs):
        raise AssertionError("本轮已检查的全量范围不应再次扫描")
    monkeypatch.setattr(DataIntegrityReport, "scan_market_index_quality", unexpected)
    monkeypatch.setattr(DataIntegrityReport, "scan_board_quality", unexpected)
    monkeypatch.setattr(IntradayArchiveService, "sync", lambda *args: {"intraday_gap": 0})
    result = DailyPipeline(market).run(codes=codes)
    assert result["ok"] and bool(scans) == expect_scan
    assert stock == {"intraday": None, "stale_rows": 0}


def test_daily_quality_only_scans_remaining_stock_objects(market, monkeypatch):
    from backend.services.pipeline import DailyPipeline

    report = DataIntegrityReport(market)
    checked = report.scan_quality_issues(codes=["600001.SH"], include_intraday=False)
    monkeypatch.setattr(IngestionService, "__init__", lambda *args: None)
    monkeypatch.setattr(IngestionService, "update", lambda *args, **kwargs: {
        "quality": {"stock": checked, "market_index": {}},
        "quality_scopes": {"stock": ["600001.SH"]},
    })
    monkeypatch.setattr(IngestionService, "ingest_board", lambda *args, **kwargs: {"quality": {"board": {}}})
    original = DataIntegrityReport.scan_quality_issues
    calls = []
    def scan(rep, **kwargs):
        calls.append(kwargs)
        return original(rep, **kwargs)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", scan)
    result = DailyPipeline(market).run()
    assert result["ok"]
    assert calls == [{"codes": ["600002.SH"], "include_intraday": False}]
    quality = next(step["detail"] for step in result["steps"] if step["step"] == "数据质检")
    assert quality["price_volume_mismatch_rows"] == 4


@pytest.mark.parametrize("handler", ["_h_backfill", "_h_ingest_date", "_h_enrich_basic"])
def test_legacy_collection_partial_failure_is_resumable_failure(monkeypatch, handler):
    from backend.services import async_task

    result = {"fail": 1, "quality": {"stock": {}}, "quality_scopes": {"stock": ["600001.SH"]}}
    service = SimpleNamespace(backfill=lambda **kwargs: result,
                              ingest_date=lambda *args, **kwargs: result,
                              enrich_basic_dates=lambda **kwargs: 1,
                              ingest_delisted=lambda **kwargs: result)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: service)
    ctx = SimpleNamespace(log=lambda *args: None, progress=lambda *args: None)
    payload = getattr(async_task, handler)({"date": "2024-01-03", "ingest_delisted": True}, ctx)
    assert payload["ok"] is False
    assert "quality_scopes" not in payload["message"]
