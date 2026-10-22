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


class ProgressContext:
    def __init__(self, checkpoint=None):
        self.checkpoint = checkpoint if checkpoint is not None else {}
        self.events = []
        self.logs = []

    def set_checkpoint(self, **data):
        self.checkpoint.update(data)

    def set_phase(self, phase, **data):
        self.set_checkpoint(phase=phase, **data)

    def progress(self, p, message):
        self.events.append((p, message))

    def log(self, message, level="info"):
        self.logs.append(message)

    def flush(self):
        pass

    def check_cancel(self):
        pass


def test_resume_checks_committed_facts_before_more_collection(market, monkeypatch):
    DataIntegrityReport(market).scan_quality_issues(include_intraday=False)
    ctx = ProgressContext()

    class Collector(BatchCollector):
        @checked_collection
        def collect(self, ctx=None, interrupt=False):
            include_collection_scope(self, "stock", ["600001.SH"])
            if not interrupt:
                # 这是续跑后的第一个取源位置：已提交的数据必须已经复检，且不改变其他股票。
                assert set(ledger(self.c).query("code == '600001.SH' and issue_type == 'price_volume_mismatch'").status) == {"resolved"}
                assert set(ledger(self.c).query("code == '600002.SH' and issue_type == 'price_volume_mismatch'").status) == {"open"}
            self.c.execute("UPDATE daily_bar SET amount=1000 WHERE code='600001.SH'")
            if interrupt:
                raise TaskCancelled()
            return {}

    collector = Collector(market)
    with pytest.raises(TaskCancelled):
        collector.collect(ctx=ctx, interrupt=True)
    assert ctx.checkpoint["collection_quality_pending"] == {"stock": ["600001.SH"]}
    original = DataIntegrityReport.scan_quality_issues
    scopes = []
    def scan(report, **kwargs):
        scopes.append(kwargs["codes"])
        return original(report, **kwargs)
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", scan)
    collector.collect(ctx=ctx)
    assert scopes == [["600001.SH"], ["600001.SH"]]
    assert ctx.checkpoint["collection_quality_pending"] == {}
    assert any("先复检" in msg for msg in ctx.logs)
    assert any(p >= 0.9 and "收尾质检" in msg for p, msg in ctx.events)
    assert max(p for p, _ in ctx.events) < 1


def test_failed_resume_check_preserves_pending_scope_and_does_not_fetch(market, monkeypatch):
    ctx = ProgressContext({"collection_quality_pending": {"stock": ["600001.SH"]}})
    def fail(*args, **kwargs):
        raise RuntimeError("quality unavailable")
    monkeypatch.setattr(DataIntegrityReport, "scan_quality_issues", fail)
    collector = BatchCollector(market)
    with pytest.raises(RuntimeError, match="quality unavailable"):
        collector.collect(["600002.SH"], ctx=ctx)
    assert ctx.checkpoint["collection_quality_pending"] == {"stock": ["600001.SH"]}
    assert collector._collection_quality_batch is None


def test_resume_does_not_claim_previous_domain_as_current_batch_result(market):
    ctx = ProgressContext({"collection_quality_pending": {"board": None}})
    result = BatchCollector(market).collect(["600001.SH"], ctx=ctx)
    assert set(result["quality"]) == {"stock"}
    assert result["quality_scopes"] == {"stock": ["600001.SH"]}


def test_second_interruption_after_resume_keeps_new_pending_range(market):
    ctx = ProgressContext({"collection_quality_pending": {"board": None}})
    with pytest.raises(RuntimeError, match="fatal source error"):
        BatchCollector(market).collect(["600001.SH"], ctx=ctx, fail=True)
    assert ctx.checkpoint["collection_quality_pending"] == {"stock": ["600001.SH"]}


@pytest.mark.parametrize("method", ["ingest_valuation", "ingest_valuation_latest",
                                   "ingest_valuation_gaps", "repair_invalid_valuation_history"])
@pytest.mark.parametrize("concurrency", [1, 4])
def test_valuation_reports_first_completion_and_preserves_retryable_failures(
    market, monkeypatch, method, concurrency,
):
    """真实批次编排，最后一只失败也计入处理进度，但不能写入成功断点。"""
    market.execute("INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv) "
                   "SELECT code,DATE '2024-01-03',-1,-1 FROM stock_basic")
    if method == "ingest_valuation":
        market.execute("UPDATE daily_metrics SET total_mv=NULL,float_mv=NULL")
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = market, MarketRepository(market)
    svc.s = get_settings().model_copy(deep=True)
    source = SimpleNamespace(name="fake")
    svc.src = source
    monkeypatch.setattr(svc, "_source_for", lambda _: source)
    monkeypatch.setattr(svc, "_history_window", lambda *args: (date(2024, 1, 2), date(2024, 1, 3)))
    monkeypatch.setattr(svc, "_thread_source", lambda *args: source)
    ctx = ProgressContext()
    # worker 不做断点和进度操作；由真实有界队列完成回调更新。
    def collect(code, source, start, end, **kwargs):
        if code == "600002.SH":
            raise RuntimeError("source unavailable")
        market.execute("UPDATE daily_metrics SET total_mv=1000,float_mv=800 WHERE code=?", [code])
        return 1
    monkeypatch.setattr(svc, "_collect_capital_one", collect)
    result = getattr(svc, method)(concurrency=concurrency, ctx=ctx)
    assert result["ok"] == result["fail"] == 1
    assert any("1/2" in message for _, message in ctx.events)
    assert any("2/2" in message for _, message in ctx.events)
    assert any(p >= 0.9 and "收尾质检" in message for p, message in ctx.events)
    for key, done in ctx.checkpoint.items():
        if key.endswith("_done_codes"):
            assert done == ["600001.SH"]
    assert ctx.checkpoint["collection_quality_pending"] == {}
    assert [p for p, _ in ctx.events] == sorted(p for p, _ in ctx.events)


def test_board_reports_each_member_before_tail_quality(market, monkeypatch):
    from backend.services.board_ingest import BoardIngestService

    market.execute("INSERT INTO board_dict(board_code,name,board_type,has_members) VALUES "
                   "('B1','板一','concept',true),('B2','板二','concept',true)")
    ctx = ProgressContext()
    def init(service, *args, **kwargs):
        service.c = market
    monkeypatch.setattr(BoardIngestService, "__init__", init)
    def member(service, code, board_type, day):
        assert ctx.checkpoint["collection_quality_pending"] == {"board": ["B1", "B2"]}
        if code == "B2":
            assert any("1/2" in msg for _, msg in ctx.events)
        market.execute("UPDATE board_dict SET member_snapshot_at=now() WHERE board_code=?", [code])
        return {"total": 0, "added": 0}
    monkeypatch.setattr(BoardIngestService, "_ingest_one_member", member)
    service = IngestionService.__new__(IngestionService)
    service.c = market
    result = service.ingest_board(ctx=ctx, board_codes=["B1", "B2"], only=["members"])
    assert result["ok"] is True
    assert ctx.checkpoint["member_done_codes"] == ["B1", "B2"]
    assert any("板块成分 1/2" in msg for _, msg in ctx.events)
    assert any("收尾质检" in msg and p >= 0.9 for p, msg in ctx.events)
    assert max(p for p, _ in ctx.events) == 0.99
    assert [p for p, _ in ctx.events] == sorted(p for p, _ in ctx.events)


@pytest.mark.parametrize("stage,key", [("dict", "dict_done_types"),
                                      ("members", "member_done_codes"), ("bar", "bar_done_codes")])
def test_failed_board_units_advance_count_without_success_checkpoint(market, stage, key):
    from backend.services.board_ingest import BoardIngestService

    market.execute("INSERT INTO board_dict(board_code,name,board_type,has_members,has_bar) VALUES "
                   "('B1','板一','concept',true,true),('B2','板二','industry',true,true)")
    def fail(*args, **kwargs):
        raise RuntimeError("source unavailable")
    source = SimpleNamespace(get_board_dict=fail, get_board_members=fail, get_board_bar=fail)
    service = BoardIngestService(client=market, source=source)
    ctx = ProgressContext()
    if stage == "dict":
        service.ingest_board_dict(ctx=ctx)
    elif stage == "members":
        service.ingest_board_members(ctx=ctx, force=True)
    else:
        service.ingest_board_bar(date(2024, 1, 2), date(2024, 1, 3), ctx=ctx)
    assert ctx.checkpoint["phase_done"] == ctx.checkpoint["phase_total"] == 2
    assert ctx.checkpoint[key] == []


def test_immediate_quality_reports_real_rule_groups(market, monkeypatch):
    from backend.services.async_task import _h_verify

    # 正式扫描器，只有取得行情连接的工厂替换为临时库。
    ctx = ProgressContext()
    monkeypatch.setattr("backend.services.data_report.get_client", lambda: market)
    result = _h_verify({}, ctx)
    assert "quality" in result
    for part in ("股本", "历史行情缺口", "指数覆盖", "板块覆盖"):
        assert any(part in msg for _, msg in ctx.events)
    assert [p for p, _ in ctx.events] == sorted(p for p, _ in ctx.events)
    assert max(p for p, _ in ctx.events) == 0.99


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
    ctx = ProgressContext()

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
            if len(calls) == 5:
                # 有界并发初始只有4只，补充第5只前必须已发布首只的完成进度。
                assert any("日线采集 1/96" in msg for _, msg in ctx.events)
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
    result = service.backfill(codes=codes, concurrency=4, ctx=ctx)
    assert result["ok"] == 96 and result["fail"] == 0 and result["rows"] == 9600
    assert sorted(calls) == codes
    assert result["quality"]["stock"]["price_volume_mismatch_rows"] == 9600
    assert result["quality"]["stock"]["st_status_missing_rows"] == 0
    assert market.query_df("SELECT count(*) FROM daily_bar WHERE adj_factor_clean IS NOT NULL").iloc[0, 0] == 9600
    assert set(ledger(market).query("issue_type == 'capital_gap'").code) == set(codes)
    assert [p for p, _ in ctx.events] == sorted(p for p, _ in ctx.events)
    assert max(p for p, _ in ctx.events) == 0.99
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


def test_daily_nested_collection_stays_within_parent_progress(market, monkeypatch):
    from backend.services.intraday_archive import IntradayArchiveService
    from backend.services.pipeline import DailyPipeline

    monkeypatch.setattr(IngestionService, "__init__", lambda *args: None)
    def update(service, *, ctx, **kwargs):
        ctx.set_phase("daily_bar", phase_total=10, phase_done=10)
        ctx.progress(0.99, "日线收尾完成")
        return {"end": "2024-01-03", "quality": {"stock": {}, "market_index": {}},
                "quality_scopes": {"stock": None}}
    def board(service, *, ctx, **kwargs):
        ctx.set_phase("board_dict", phase_total=2, phase_done=2)
        ctx.progress(0.99, "板块收尾完成")
        return {"quality": {"board": {}}}
    def minutes(service, **kwargs):
        kwargs["progress"](1, "分时检查完成")
        return {}
    monkeypatch.setattr(IngestionService, "update", update)
    monkeypatch.setattr(IngestionService, "ingest_board", board)
    monkeypatch.setattr(IntradayArchiveService, "sync", minutes)
    ctx = ProgressContext()
    result = DailyPipeline(market).run(ctx=ctx)
    assert result["ok"]
    assert [p for p, _ in ctx.events] == sorted(p for p, _ in ctx.events)
    assert next(p for p, msg in ctx.events if msg == "日线收尾完成") < 0.35
    assert next(p for p, msg in ctx.events if msg == "板块收尾完成") < 0.65


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
