"""批量修复真实落库回归：有界取源、原口径复检、失败不重复取源及取消续跑。"""

import json
import threading
import time
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataQualityError, DataSourceError, StorageError
from backend.config.settings import Settings
from backend.datasource.base import check_thread_cancel, thread_cancel_scope
from backend.datasource.observability import RequestTracker, observe_work
from backend.services import async_task, board_ingest, ingest, quality_repair_sources
from backend.services.async_task import TaskCancelled
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository

DAY = date(2024, 1, 5)
DAYS = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), DAY]


class Context:
    tid = "test_quality_parallel"

    def __init__(self):
        self.checkpoint, self.logs = {}, []
        self.request_tracker = RequestTracker()
        self.cancel = False
        self.cancel_after = None

    def check_cancel(self):
        if self.cancel:
            raise TaskCancelled()

    def set_checkpoint(self, **values):
        self.checkpoint.update(values)
        if self.cancel_after and len(self.checkpoint.get("issue_done_ids", [])) >= self.cancel_after:
            self.cancel = True

    def set_phase(self, phase, **values):
        self.set_checkpoint(phase=phase, **values)

    def log(self, message, level="info"):
        self.logs.append(message)

    def flush(self):
        pass

    def progress(self, *args):
        pass


class Source:
    """独立工作线程会话共用测试计数器，成功/空/异常/不完整成分均走原服务持久化。"""

    name = "test_board"
    fund_flow_is_live_snapshot = False

    def __init__(self, state):
        self.state = state

    def fork(self):
        return Source(self.state)

    def close(self):
        self.state.closed += 1

    def _begin(self, operation, code):
        check_thread_cancel()
        with self.state.lock:
            self.state.calls.append((operation, code, threading.get_ident()))
            self.state.active += 1
            self.state.maximum = max(self.state.maximum, self.state.active)
            request_number = len(self.state.calls)
        try:
            gate = getattr(self.state, "first_wave_gate", None)
            if gate is not None and request_number <= gate.parties:
                gate.wait(timeout=10)
            time.sleep(getattr(self.state, "delay", .015))
        finally:
            with self.state.lock:
                self.state.active -= 1
        check_thread_cancel()
        if code in self.state.errors:
            raise DataSourceError("测试来源失败")

    def get_board_bar(self, code, board_type, start, end):
        self._begin("bar", code)
        if code in self.state.empty:
            return pd.DataFrame()
        return pd.DataFrame([
            {"trade_date": day, "open": 100., "high": 102., "low": 99., "close": 101.,
             "volume": 1000., "amount": 100000.}
            for day in DAYS if start <= day <= end
        ])

    def get_board_members(self, code, board_type):
        self._begin("member", code)
        return {"codes": ["600000", "300750"], "complete": code not in self.state.empty, "pages": 1}

    def get_board_fund_flow(self, board_type, period):
        self._begin("fund", period)
        return pd.DataFrame([
            {"name": code, "board_code": code, "inflow": 10., "outflow": 5.,
             "net_inflow": 5., "net_ratio": 1., "leader_stock": "测试", "leader_pct": 1.}
            for code in self.state.codes
        ])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    databases = []
    original_board = board_ingest.BoardIngestService
    original_ingest = ingest.IngestionService
    settings = Settings()
    settings.datasource.update_concurrency = 4
    monkeypatch.setattr(board_ingest, "get_effective_settings", lambda: settings)

    def make(name="repair", count=12):
        client = DuckDBClient(str(tmp_path / f"{name}.duckdb"))
        init_db(client)
        databases.append(client)
        client.executemany("INSERT INTO trade_calendar VALUES (?,TRUE)", [(day,) for day in DAYS])
        client.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH',?,10)", [DAY])
        codes = [str(300000+i) for i in range(count)]
        client.executemany(
            "INSERT INTO board_dict(board_code,name,board_type,has_bar,has_members,has_fund_flow) "
            "VALUES (?,?,'concept',TRUE,FALSE,FALSE)", [(code, code) for code in codes],
        )
        state = SimpleNamespace(lock=threading.Lock(), active=0, maximum=0, calls=[],
                                closed=0, errors=set(), empty=set(), codes=codes)
        # 使用真实服务构造、DDL、事务和复检，仅替换取源。
        service = original_board(client, source=Source(state))
        svc = original_ingest.__new__(original_ingest)
        svc.s, svc.c, svc.repo = settings, client, MarketRepository(client)
        svc.src = SimpleNamespace(name="akshare")
        monkeypatch.setattr(async_task, "get_client", lambda: client)
        monkeypatch.setattr(ingest, "IngestionService", lambda: svc)
        # board_repair_service只构造一次，再复用正常入口；独立工作会话由Source.fork提供。
        monkeypatch.setattr(board_ingest, "BoardIngestService", lambda *_: service)
        return client, state, service, svc

    yield make
    for client in databases:
        client.close()


def issue(client, code, kind="board_index_gap_daily", day=DAY, detail="{}"):
    return int(client.query_df(
        "INSERT INTO data_quality_issue(id,code,trade_date,issue_type,severity,status,detail,detected_at) "
        "VALUES(nextval('seq_quality_issue'),?,?,?,'high','open',?,CURRENT_TIMESTAMP) RETURNING id",
        [code, day, kind, detail],
    ).iloc[0, 0])


def run(ids, ctx):
    with observe_work(ctx.request_tracker), thread_cancel_scope(ctx.check_cancel):
        return async_task._h_fix({"issue_ids": ids}, ctx)


def test_92_board_repairs_parallel_main_thread_landing_and_no_material_leak(setup, monkeypatch):
    client, state, service, _ = setup(count=92)
    ids = [issue(client, code) for code in state.codes]
    main = threading.get_ident()
    original = service._upsert_board_bar

    def store(frame):
        assert threading.get_ident() == main
        return original(frame)

    monkeypatch.setattr(service, "_upsert_board_bar", store)
    ctx = Context()
    result = run(ids, ctx)
    assert result["ok"] and result["resolved"] == 92
    assert state.maximum == 8 and state.active == 0
    assert len(state.calls) == 92 and all(t != main for _, _, t in state.calls)
    assert client.query_df("SELECT count(*) FROM board_bar").iloc[0, 0] == 92
    assert set(ctx.checkpoint["issue_done_ids"]) == set(ids)
    assert ctx.request_tracker.meta["work_concurrency"] == 8
    assert ctx._board_repair_material is None and ctx._board_repair_base is None
    assert state.closed >= 2


def test_multiple_dates_share_annual_request_without_overwriting_other_dates(setup):
    client, state, _, _ = setup(count=1)
    code = state.codes[0]
    client.execute("INSERT INTO board_bar(board_code,trade_date,close) VALUES (?,?,777)", [code, DAYS[2]])
    ids = [issue(client, code, day=day) for day in [DAYS[0], DAY]]
    result = run(ids, Context())
    assert result["resolved"] == 2 and len(state.calls) == 1
    rows = client.query_df("SELECT trade_date,close FROM board_bar ORDER BY trade_date")
    assert rows.close.tolist() == [101., 777., 101.]
    assert DAYS[1] not in rows.trade_date.dt.date.tolist()


def test_empty_and_failed_source_not_retried_per_issue_and_success_survives(setup):
    client, state, _, _ = setup(count=4)
    state.empty = {state.codes[0]}
    state.errors = {state.codes[1]}
    ids = [issue(client, code, day=day) for code in state.codes for day in [DAYS[0], DAY]]
    ctx = Context()
    result = run(ids, ctx)
    assert not result["ok"] and result["resolved"] == 4 and result["failed"] == 2
    assert len(state.calls) == 4
    statuses = client.query_df("SELECT id,status,fix_task_id FROM data_quality_issue WHERE id IN (SELECT unnest(?::BIGINT[])) ORDER BY id", [ids])
    assert statuses.status.tolist() == ["open"] * 4 + ["resolved"] * 4
    assert statuses.fix_task_id.isna().all()
    assert set(ctx.checkpoint["issue_done_ids"]) == set(ids[4:])


def test_cancel_drains_workers_keeps_only_committed_checkpoints_then_resumes(setup):
    client, state, _, _ = setup(count=24)
    ids = [issue(client, code) for code in state.codes]
    ctx = Context()
    ctx.cancel_after = 1
    with pytest.raises(TaskCancelled):
        run(ids, ctx)
    assert state.active == 0
    committed = client.query_df("SELECT board_code FROM board_bar").board_code.tolist()
    assert len(committed) == len(ctx.checkpoint["issue_done_ids"]) == 1
    assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='fixing'").iloc[0,0] == 0
    ctx.cancel, ctx.cancel_after = False, None
    before = len(state.calls)
    result = run(ids, ctx)
    assert result["ok"] and result["resolved"] == 23
    assert len(state.calls)-before == 23
    assert client.query_df("SELECT count(*) FROM board_bar").iloc[0,0] == 24


def test_member_repairs_parallel_and_incomplete_snapshot_preserves_old_members(setup):
    client, state, _, _ = setup(count=12)
    client.execute("UPDATE board_dict SET has_members=TRUE,has_bar=FALSE")
    # 显式首轮会合，避免忙机上15ms延时不足以稳定观察八路工作并发。
    state.first_wave_gate = threading.Barrier(8)
    state.empty = {state.codes[0]}
    client.execute("INSERT INTO board_member(board_code,code) VALUES (?, '000001.SZ')", [state.codes[0]])
    ids = [issue(client, code, kind="board_member_incomplete") for code in state.codes]
    result = run(ids, Context())
    assert result["resolved"] == 11 and result["failed"] == 1
    assert state.maximum == 8 and len(state.calls) == 12
    assert client.query_df("SELECT code FROM board_member WHERE board_code=?", [state.codes[0]]).code.tolist() == ["000001.SZ"]


def test_old_complete_snapshot_does_not_hide_new_incomplete_members(setup):
    client, state, service, _ = setup(count=1)
    code = state.codes[0]
    client.execute("UPDATE board_dict SET has_members=TRUE,has_bar=FALSE")
    service.ingest_board_members(snapshot_date=DAY, board_codes=[code], force=True)
    iid = issue(client, code, kind="board_member_incomplete")
    state.calls.clear()
    state.empty.add(code)
    ctx = Context()
    result = run([iid], ctx)
    assert not result["ok"] and result["failed"] == 1 and result["resolved"] == 0
    assert len(state.calls) == 1
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0, 0] == "open"
    assert set(client.query_df("SELECT code FROM board_member WHERE board_code=?", [code]).code) == {
        "600000.SH", "300750.SZ",
    }
    assert iid not in ctx.checkpoint.get("issue_done_ids", [])


def test_fund_missing_reuses_one_market_response_but_only_writes_selected_boards(setup):
    client, state, _, _ = setup(count=4)
    client.execute("UPDATE board_dict SET has_fund_flow=TRUE,has_bar=FALSE")
    # 只修三个板块，缓存的全市场响应包含第四个也不能越过原选中范围写入。
    ids = [issue(client, code, kind="board_fund_missing", detail='{"periods":["即时"]}')
           for code in state.codes[:3]]
    result = run(ids, Context())
    assert result["resolved"] == 3
    assert [(op, code) for op, code, _ in state.calls] == [("fund", "即时")]
    rows = client.query_df("SELECT board_code,snapshot_date FROM board_fund_flow ORDER BY board_code")
    assert rows.board_code.tolist() == state.codes[:3]
    assert rows.snapshot_date.dt.date.tolist() == [DAY] * 3


def test_market_index_repairs_parallel_and_keep_unselected_dates(setup):
    from backend.services.market_benchmark import configured_benchmark_codes

    client, state, _, svc = setup()
    codes = configured_benchmark_codes()[:3]

    class IndexSource(Source):
        def get_index_bar(self, code, start, end):
            return self.get_board_bar(code, "concept", start, end).assign(index_code=code)

    svc.src = IndexSource(state)
    svc._thread_source = lambda *_: IndexSource(state)
    ids = [issue(client, code, kind="market_index_gap_daily") for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert result["resolved"] == 3 and result["failed"] == 0
    assert state.maximum == 3 and len(state.calls) == 3
    rows = client.query_df("SELECT index_code,trade_date FROM index_bar ORDER BY index_code")
    assert rows.index_code.tolist() == sorted(codes) and len(rows) == 3
    assert ctx.request_tracker.meta["work_concurrency"] == 3


@pytest.mark.parametrize("partial", [False, True])
def test_st_three_issue_types_share_one_refresh_and_failures_stay_open(setup, monkeypatch, partial):
    from backend.services.data_report import DataIntegrityReport

    client, _, _, svc = setup()
    codes = ["600000.SH", "600519.SH", "000001.SZ"]
    ids = [issue(client, code, kind=kind) for code, kind in zip(codes, sorted(quality_repair_sources.ST_TYPES), strict=True)]
    ready, calls = set(), []
    recheck = DataIntegrityReport.recheck_clean

    def checked(self, kind, code, day, **kwargs):
        return code in ready if kind in quality_repair_sources.ST_TYPES else recheck(self, kind, code, day, **kwargs)

    def refresh(codes, ctx):
        calls.append(codes)
        ready.update(codes[:-1] if partial else codes)
        return {"rows": len(ready), "fail": int(partial), "changed_date_values": [],
                "failures": [{"code": codes[-1], "error": "source failed"}] if partial else []}

    monkeypatch.setattr(DataIntegrityReport, "recheck_clean", checked)
    svc.refresh_st_status = refresh
    result = run(ids, Context())
    assert len(calls) == 1 and set(calls[0]) == set(codes)
    assert result["resolved"] == (2 if partial else 3) and result["failed"] == int(partial)
    rows = client.query_df("SELECT status FROM data_quality_issue WHERE id IN (SELECT unnest(?::BIGINT[])) ORDER BY id", [ids])
    assert rows.status.tolist() == (["resolved", "resolved", "open"] if partial else ["resolved"] * 3)


@pytest.mark.parametrize(("failures", "reason"), [
    ([{"code": "600000.SH", "error": "600000.SH ST 点时事实缺 1 个行情日，示例: 2026-11-13"}],
     "600000.SH ST 点时事实缺 1 个行情日，示例: 2026-11-13"),
    ([], "未取得完整的逐日 ST 事实"),
    ([{"code": "600000.SH"}], "未取得完整的逐日 ST 事实"),
    ([{"code": "600000.SH", "error": "The read operation timed out"}],
     "数据源请求超时，未能完成取数，请稍后重试"),
    ([{"code": "600000.SH", "error": "Connection reset by peer"}],
     "数据源连接失败，未能取得数据，请检查网络后重试"),
])
def test_single_st_failure_exposes_readable_reason_and_keeps_diagnostic(setup, monkeypatch, failures, reason):
    """单条失败摘要不回显字典；原因与台账状态仍可在质量页直接消费。"""
    from backend.services.data_report import DataIntegrityReport

    client, _, _, svc = setup()
    iid = issue(client, "600000.SH", kind="st_status_missing")
    monkeypatch.setattr(DataIntegrityReport, "recheck_clean", lambda *args, **kwargs: False)
    svc.refresh_st_status = lambda **kwargs: {"fail": 1, "failures": failures}
    result = run([iid], Context())
    assert result["message"] == f"恢复失败，已退回待处理：ST 状态刷新失败：{reason}"
    assert result["ok"] is False and result["failed"] == 1
    assert result["failure_reason"] == f"ST 状态刷新失败：{reason}"
    row = client.query_df("SELECT status,fix_task_id,detail FROM data_quality_issue WHERE id=?", [iid]).iloc[0]
    assert row.status == "open" and pd.isna(row.fix_task_id)
    assert reason in json.loads(row.detail)["last_repair"]["error"]
    assert json.loads(row.detail)["last_repair"]["failure_reason"] == result["failure_reason"]


@pytest.mark.parametrize(("error", "expected"), [
    (RuntimeError("源端仍无数据，保持待处理"), "源端仍无数据"),
    (DataSourceError("ReadTimeout: GET https://secret.test/token"), "请求超时"),
    (ConnectionError("connection failed https://secret.test/token"), "连接失败"),
    (RuntimeError("HTTPError: 429 for https://secret.test/token"), "限流"),
    (RuntimeError("HTTPError: 403 for https://secret.test/token"), "拒绝访问"),
    (DataSourceError("HTTPError: 502 for https://secret.test/token"), "数据源请求失败"),
    (ValueError("invalid response at /Users/private/secret"), "参数或返回数据"),
    (StorageError("SQL: SELECT secret FROM private_table"), "读取或写入失败"),
    (DataQualityError("invalid data at /tmp/secret"), "质量校验"),
    (RuntimeError("SQL: SELECT secret FROM private_table"), "修复执行异常"),
    (RuntimeError("未知异常 Traceback: /tmp/secret"), "修复执行异常"),
])
def test_repair_failure_translation_preserves_cause_without_technical_details(error, expected):
    from backend.services.quality_repair_feedback import repair_failure_reason

    reason = repair_failure_reason(error)
    assert expected in reason
    assert not any(value in reason for value in ("secret", "HTTPError", "SQL:", "Traceback", "查看日志"))


def test_repair_failure_translation_checks_wrapped_cause():
    from backend.services.quality_repair_feedback import repair_failure_reason

    error = RuntimeError("source failed")
    error.__cause__ = TimeoutError("request timed out")
    assert "请求超时" in repair_failure_reason(error)


@pytest.mark.parametrize(("raw", "expected"), [
    ("concept/即时: empty", "数据源返回空数据"),
    ("300001: years [2025, 2026]", "2025, 2026 年的采集"),
    ("concept/即时:板块: net_inflow=1 != inflow-outflow=2", "净流入与流入减流出"),
])
def test_board_collection_known_failure_formats_are_translated(raw, expected):
    from backend.services.quality_repair_feedback import repair_collection_reason

    assert expected in repair_collection_reason([raw])


@pytest.mark.parametrize("kind", [
    "board_index_gap_daily", "board_fund_missing", "board_fund_stale", "board_fund_unmatched",
])
def test_board_failure_list_keeps_reason_and_raw_log(setup, monkeypatch, kind):
    from backend.services.data_report import DataIntegrityReport

    client, state, service, _ = setup(count=1)
    code = state.codes[0]
    iid = issue(client, code, kind=kind)
    # 本用例验证采集返回失败后的反馈；明确保持目标问题未通过复检，避免
    # 来源级 stale 因空快照被现有扫描判为无需恢复而提前收敛。
    monkeypatch.setattr(DataIntegrityReport, "recheck_clean", lambda *args, **kwargs: False)
    fail = lambda *args, **kwargs: {
        "failed": [{"error": "源端尚未提供目标日指数"}], "rows": 0,
    }
    service.ingest_board_bar = fail
    service.ingest_board_fund_flow = fail
    service.ingest_board_dict = lambda **kwargs: None
    ctx = Context()
    result = run([iid], ctx)
    label = "板块指数" if kind == "board_index_gap_daily" else "板块资金流"
    assert result["failure_reason"] == f"{label}重采失败：源端尚未提供目标日指数"
    assert result["failed"] == 1 and result["resolved"] == 0
    assert any("'error':" in message for message in ctx.logs)
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0, 0] == "open"


def test_four_capital_issue_types_do_not_repeat_full_history_or_close_remaining_issues(setup, monkeypatch):
    from backend.services.data_report import DataIntegrityReport

    client, _, _, svc = setup()
    codes = ["600000.SH", "600519.SH"]
    ids = [issue(client, code, kind=kind) for kind in quality_repair_sources.CAPITAL_TYPES for code in codes]
    recheck = DataIntegrityReport.recheck_clean
    monkeypatch.setattr(DataIntegrityReport, "recheck_clean", lambda self, kind, code, day, **kw:
                        False if kind in quality_repair_sources.CAPITAL_TYPES else recheck(self, kind, code, day, **kw))
    calls = []
    client.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600519.SH',?,10)", [DAY])
    svc._source_for = lambda *_: SimpleNamespace(name="test")
    svc._thread_source = lambda *_: SimpleNamespace(name="test")
    svc._fetch_capital_material = lambda *_: (pd.DataFrame(), None)
    svc.repair_capital_quality = lambda code, ctx, **kw: calls.append(code) or {"rows": 0}
    def batch(entries, source, windows, one, **kwargs):
        checks = kwargs["checks"]
        for _i, code, _frame, _error, _pending in entries:
            checks.update({(kind, code): False for kind in quality_repair_sources.CAPITAL_TYPES})
        material = [(i, code, (frame, None), error, pending)
                    for i, code, frame, error, pending in entries]
        return svc._complete_capital_material(material, source, one)
    monkeypatch.setattr(svc, "_merge_valuation_batch", batch)
    for _ in range(2):
        before = len(calls)
        result = run(ids, Context())
        assert result["resolved"] == result["failed"] == 0
        assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='open'").iloc[0,0] == 8
        # 并发完成顺序不固定；每轮严格验证每股仅调用一次，且下一任务重新取源。
        assert sorted(calls[before:]) == sorted(codes)


def wire_stock_repairs(setup, monkeypatch, *, name="stocks", count=12):
    """真实行情/ST/股本落库；固定网络延时并记录线程，禁止工作线程访问数据库。"""
    from backend.tests.test_daily_collection_performance import bars

    client, state, _, svc = setup(name=name, count=count)
    main = threading.get_ident()
    codes = [f"{600001 + i}.SH" for i in range(count)]
    state.codes = codes
    client.executemany("INSERT INTO stock_basic(code,list_date) VALUES (?,?)", [(code, DAYS[0]) for code in codes])
    client.executemany(
        "INSERT INTO daily_bar(code,trade_date,open,high,low,close,volume,amount,adj_factor) "
        "VALUES (?,?,10,10,10,10,100,1000,1)", [(code, DAYS[0]) for code in codes],
    )
    state.stopped, state.partial = set(), set()
    source = Source(state)
    svc._bao = None
    svc.src = source
    svc._thread_source = lambda *_: source
    svc._source_for = lambda *_: source
    svc._bao_source = lambda: source

    def frame(code, start, end):
        return pd.concat([bars(code).assign(trade_date=day) for day in DAYS if start <= day <= end], ignore_index=True)

    def daily(code, start, end, *_args, **kw):
        source._begin("daily", code)
        if code in state.errors:
            raise DataSourceError("测试来源失败")
        result = frame(code, start, end)
        if code in state.partial:
            result = result[result.trade_date != DAY]
        return result, source.name

    def status(code, start, end, **kw):
        source._begin("status", code)
        return source, pd.DataFrame([
            {"trade_date": day, "is_st": False, "trade_status": 0 if code in state.stopped else 1}
            for day in DAYS if start <= day <= end
        ])

    def capital(code, _source, start, end):
        source._begin("capital", code)
        return frame(code, start, end).assign(total_mv=1000., float_mv=800.), None

    source.get_valuation = lambda code, start, end: capital(code, source, start, end)[0]

    def collect(code, source, start, end, diagnostics=None):
        assert threading.get_ident() == main
        value = svc._valuation_one(code, source, start, end)
        if diagnostics is not None:
            diagnostics[code] = {"remaining": {}}
        return value

    original_query = client.query_df
    def query(*args, **kw):
        assert threading.get_ident() == main
        return original_query(*args, **kw)

    monkeypatch.setattr(client, "query_df", query)
    monkeypatch.setattr(svc, "_fetch_daily_with_fallback", daily)
    monkeypatch.setattr(svc, "_fetch_st_status_rows", status)
    monkeypatch.setattr(svc, "_fetch_capital_material", capital)
    monkeypatch.setattr(svc, "_collect_capital_one", collect)
    # 使用真实因子、日线及股本合并；仅多来源事件补充在上述 collect 中隔离。
    svc.repair_capital_quality = type(svc).repair_capital_quality.__get__(svc)
    return client, state, svc, codes


@pytest.mark.parametrize("kind", ["history_data_gap", "stale", "adj_jump", "capital_gap"])
def test_stock_repairs_fetch_concurrently_and_commit_on_main_thread(setup, monkeypatch, kind):
    client, state, _, codes = wire_stock_repairs(setup, monkeypatch)
    ids = [issue(client, code, kind=kind, day=None) for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert result["resolved"] == len(ids) and result["failed"] == 0, ctx.logs
    assert state.maximum == 4 and state.active == 0
    assert set(ctx.checkpoint["issue_done_ids"]) == set(ids)
    assert ctx._stock_repair_material is None and ctx._capital_repair_material is None
    assert ctx.request_tracker.meta["work_concurrency"] == 4
    expected = (len(codes) if kind in {"adj_jump", "capital_gap"} else len(codes) * 4)
    assert client.query_df("SELECT count(*) FROM daily_bar WHERE code<> '600000.SH'").iloc[0, 0] == expected
    if kind != "adj_jump":
        assert sum(op == "capital" for op, *_ in state.calls) == len(codes)
    if kind == "history_data_gap":
        assert sum(op == "status" for op, *_ in state.calls) == len(codes)


def test_history_repair_suspension_skips_prices_and_duplicate_stale_reuses_material(setup, monkeypatch):
    client, state, _, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    state.stopped = {codes[0]}
    ids = [issue(client, code, kind=kind, day=None) for code in codes
           for kind in ["history_data_gap", "stale"]]
    ctx = Context()
    result = run(ids, ctx)
    assert result["resolved"] == len(ids), ctx.logs
    assert len([op for op, code, _ in state.calls if code == codes[0]]) == 1
    assert client.query_df("SELECT count(*) FROM stock_suspension WHERE code=?", [codes[0]]).iloc[0, 0] == 3
    assert sum(op == "daily" for op, *_ in state.calls) == 3
    assert sum(op == "status" for op, *_ in state.calls) == 4


def test_stock_repair_cancel_drains_prefetch_and_resumes_only_uncommitted(setup, monkeypatch):
    client, state, _, codes = wire_stock_repairs(setup, monkeypatch, count=12)
    ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
    ctx = Context()
    ctx.cancel_after = 1
    with pytest.raises(TaskCancelled):
        run(ids, ctx)
    assert state.active == 0 and len(ctx.checkpoint["issue_done_ids"]) == 1
    assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='fixing'").iloc[0, 0] == 0
    done = client.query_df("SELECT code FROM data_quality_issue WHERE status='resolved'").iloc[0, 0]
    before = len(state.calls)
    ctx.cancel, ctx.cancel_after = False, None
    result = run(ids, ctx)
    assert result["resolved"] == 11, ctx.logs
    assert done not in {code for _, code, _ in state.calls[before:]}


def test_stock_repair_failed_source_remains_open_without_retrying_material(setup, monkeypatch):
    client, state, _, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    state.errors = {codes[0]}
    ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert result["resolved"] == 3 and not result["ok"], ctx.logs
    assert ids[0] not in ctx.checkpoint["issue_done_ids"]
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [ids[0]]).iloc[0, 0] == "open"


def test_remaining_history_gap_does_not_repeat_fallback_for_sibling_issue(setup, monkeypatch):
    client, state, _, codes = wire_stock_repairs(setup, monkeypatch, count=1)
    state.partial = set(codes)
    # 逆序选择也必须先处理包含近端的历史范围，再逐类复检。
    ids = [issue(client, codes[0], kind=kind, day=None) for kind in ["stale", "history_data_gap"]]
    ctx = Context()
    result = run(ids, ctx)
    assert not result["ok"] and result["resolved"] == 0, ctx.logs
    assert sum(op == "daily" for op, *_ in state.calls) == 2  # 主源一次 + 剩余日期备用源一次
    assert sum(op == "status" for op, *_ in state.calls) == 1
    assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='fixing'").iloc[0, 0] == 0


def test_capital_partial_write_failure_is_not_hidden_by_early_ledger_resolution(setup, monkeypatch):
    from backend.services.capital_quality import CapitalQualityService
    from backend.services.share_capital import ShareCapitalService
    from backend.tests.test_daily_collection_performance import bars

    client, state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    fetch = svc._fetch_capital_material
    def conflicting(code, *args):
        frame, prices = fetch(code, *args)
        if code == codes[0]:
            frame = frame.assign(total_share=90.)  # 与接口市值不一致，必须进入事件核验。
        return frame, prices
    monkeypatch.setattr(svc, "_fetch_capital_material", conflicting)
    collect = svc._collect_capital_one
    def partial(code, *args, **kwargs):
        result = collect(code, *args, **kwargs)
        if code == codes[0]:
            # 模拟补充源已补齐业务值，但随后来源事件归档失败；事实干净也不能掩盖失败。
            clean = pd.concat([bars(code).assign(trade_date=day, total_mv=1000., float_mv=800.)
                               for day in DAYS], ignore_index=True)
            ShareCapitalService(client).merge(clean, "eastmoney_daily", reported=True)
            raise DataSourceError("股本事件来源失败，估值已保留")
        return result
    monkeypatch.setattr(svc, "_collect_capital_one", partial)
    ids = [issue(client, code, kind="capital_gap", day=None) for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert not result["ok"] and result["failed"] == 1 and result["resolved"] == 3, ctx.logs
    assert ids[0] not in ctx.checkpoint["issue_done_ids"]
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [ids[0]]).iloc[0, 0] == "open"
    assert sum(op == "capital" for op, *_ in state.calls) == 4
    assert CapitalQualityService(client).aggregate(codes).empty
    assert set(ctx.checkpoint["stock_repair_pending"]) == {f"capital:{codes[0]}"}
    monkeypatch.setattr(svc, "_fetch_capital_material", fetch)
    result = run(ids, ctx)
    assert not result["ok"] and result["failed"] == 1, ctx.logs
    assert ids[0] not in ctx.checkpoint["issue_done_ids"]
    monkeypatch.setattr(svc, "_collect_capital_one", collect)
    result = run(ids, ctx)
    assert result["ok"] and result["resolved"] == 1, ctx.logs
    assert not ctx.checkpoint["stock_repair_pending"]


@pytest.mark.parametrize("missing_day", [DAYS[1], DAY])
def test_fallback_completed_dates_keep_full_valuation_evidence(setup, monkeypatch, missing_day):
    """备用源补齐首日/末日后，来源证据和干净因子均须与逐条恢复一致。"""
    batch = quality_repair_sources.run_stock_repairs
    snapshots = []
    for mode in ["serial", "parallel"]:
        client, state, svc, codes = wire_stock_repairs(
            setup, monkeypatch, name=mode, count=4,
        )
        daily = svc._fetch_daily_with_fallback
        calls = {}

        def partial_first(code, start, end, *args, daily=daily, calls=calls, **kwargs):
            frame, source = daily(code, start, end, *args, **kwargs)
            calls[code] = calls.get(code, 0) + 1
            return (frame[frame.trade_date != missing_day] if calls[code] == 1 else frame), source

        monkeypatch.setattr(svc, "_fetch_daily_with_fallback", partial_first)
        monkeypatch.setattr(
            quality_repair_sources, "run_stock_repairs",
            (lambda *args, **kwargs: None) if mode == "serial" else batch,
        )
        ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
        ctx = Context()
        result = run(ids, ctx)
        assert result["resolved"] == len(ids) and result["failed"] == 0, ctx.logs
        assert all(calls[code] == 2 for code in codes)
        assert sum(op == "capital" for op, *_ in state.calls) == len(codes)
        frame = client.query_df(
            "SELECT code,trade_date,total_mv,float_mv,reported_total_mv,reported_float_mv "
            "FROM daily_metrics WHERE code IN (SELECT unnest(?::VARCHAR[])) "
            "ORDER BY code,trade_date", [codes],
        )
        assert len(frame) == len(codes) * (len(DAYS) - 1)
        assert frame[["reported_total_mv", "reported_float_mv"]].notna().all().all()
        prices = client.query_df(
            "SELECT code,trade_date,adj_factor,adj_factor_clean,pre_close FROM daily_bar "
            "WHERE code IN (SELECT unnest(?::VARCHAR[])) ORDER BY code,trade_date", [codes],
        )
        assert prices.adj_factor_clean.notna().all()
        assert not svc._dirty_daily_codes(codes)
        assert set(ctx.checkpoint["issue_done_ids"]) == set(ids)
        assert not ctx.checkpoint.get("stock_repair_pending")
        snapshots.append((frame, prices))
    for serial, parallel in zip(*snapshots, strict=True):
        pd.testing.assert_frame_equal(serial, parallel)


@pytest.mark.parametrize("kind", ["stale", "data_gap", "history_data_gap", "adj_jump"])
def test_batch_daily_validation_failure_keeps_diagnostics_and_resumes(setup, monkeypatch, kind):
    import json

    client, state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=2)
    original = svc.ingest_one_daily
    attempts = {}
    def invalid(code, *args, **kwargs):
        attempts[code] = attempts.get(code, 0) + 1
        if code == codes[0]:
            raise ValueError("行情材料校验失败")
        return original(code, *args, **kwargs)
    monkeypatch.setattr(svc, "ingest_one_daily", invalid)
    ids = [issue(client, code, kind=kind, day=None) for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert not result["ok"] and result["failed"] == result["technical_failure"] == 1, ctx.logs
    assert result["resolved"] == 1
    row = client.query_df("SELECT status,fix_task_id,detail FROM data_quality_issue WHERE id=?", [ids[0]]).iloc[0]
    assert row.status == "open" and pd.isna(row.fix_task_id)
    assert json.loads(row.detail)["last_repair"]["error"] == "行情材料校验失败"
    assert ids[0] not in ctx.checkpoint["issue_done_ids"]
    assert attempts[codes[0]] == 1
    assert sum(op == "daily" and code == codes[0] for op, code, _ in state.calls) == 1
    monkeypatch.setattr(svc, "ingest_one_daily", original)
    before = len(state.calls)
    result = run(ids, ctx)
    assert result["ok"] and result["resolved"] == 1 and result["failed"] == 0, ctx.logs
    assert {code for _, code, _ in state.calls[before:]} == {codes[0]}
    assert not svc._dirty_daily_codes(codes)
    assert not ctx.checkpoint["stock_repair_pending"]


def test_batch_primary_source_failure_still_uses_original_gap_fallback(setup, monkeypatch):
    client, _state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=2)
    original = svc._fetch_daily_with_fallback
    calls = {}
    def unavailable(code, *args, **kwargs):
        calls[code] = calls.get(code, 0) + 1
        if code == codes[0] and calls[code] == 1:
            raise DataSourceError("主源暂不可用")
        return original(code, *args, **kwargs)
    monkeypatch.setattr(svc, "_fetch_daily_with_fallback", unavailable)
    ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert result["ok"] and result["resolved"] == 2 and result["failed"] == 0, ctx.logs
    assert calls == {codes[0]: 2, codes[1]: 1}
    assert any("主源暂不可用" in message for message in ctx.logs)
    assert not svc._dirty_daily_codes(codes)
    assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='fixing'").iloc[0, 0] == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_fallback_factor_failure_keeps_pending_scope_and_resumes(setup, monkeypatch, cancel):
    client, _state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=1)
    code = codes[0]
    daily, factors = svc._fetch_daily_with_fallback, svc._recompute_clean
    fetches = recomputes = 0
    ctx = Context()
    def partial(*args, **kwargs):
        nonlocal fetches
        frame, source = daily(*args, **kwargs)
        fetches += 1
        return (frame[frame.trade_date != DAY] if fetches == 1 else frame), source
    def unfinished(*args, **kwargs):
        nonlocal recomputes
        recomputes += 1
        if recomputes == 2:
            if cancel:
                ctx.cancel = True
                ctx.check_cancel()
            return {"fail": 1}
        return factors(*args, **kwargs)
    monkeypatch.setattr(svc, "_fetch_daily_with_fallback", partial)
    monkeypatch.setattr(svc, "_recompute_clean", unfinished)
    iid = issue(client, code, kind="history_data_gap", day=None)
    if cancel:
        with pytest.raises(TaskCancelled):
            run([iid], ctx)
    else:
        result = run([iid], ctx)
        assert not result["ok"] and result["failed"] == 1, ctx.logs
    assert recomputes == 2
    assert not ctx.checkpoint.get("issue_done_ids")
    assert set(ctx.checkpoint["stock_repair_pending"]) == {f"gap:{code}"}
    assert svc._dirty_daily_codes(codes) == {code}
    assert client.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0, 0] == "open"
    monkeypatch.setattr(svc, "_recompute_clean", factors)
    ctx.cancel = False
    result = run([iid], ctx)
    assert result["ok"] and result["resolved"] == 1, ctx.logs
    assert not svc._dirty_daily_codes(codes)
    assert not ctx.checkpoint["stock_repair_pending"]


def test_stock_serial_parallel_equivalence_and_request_cost(setup, monkeypatch):
    """同量固定响应，真实落库与复检对比；耗时只观测，避免机器负载导致脆弱门限。"""
    import json

    batch = quality_repair_sources.run_stock_repairs
    snapshots, timings = [], []
    for mode in ["serial", "parallel"]:
        client, state, _, codes = wire_stock_repairs(setup, monkeypatch, name=mode, count=48)
        state.delay = .025
        ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
        monkeypatch.setattr(quality_repair_sources, "run_stock_repairs",
                            (lambda *args, **kwargs: None) if mode == "serial" else batch)
        started = time.monotonic()
        ctx = Context()
        result = run(ids, ctx)
        assert result["resolved"] == len(ids), ctx.logs
        assert state.maximum == (1 if mode == "serial" else 4)
        snapshots.append([
            client.query_df(sql) for sql in [
                "SELECT code,trade_date,open,high,low,close,volume,amount,adj_factor,adj_factor_clean FROM daily_bar ORDER BY code,trade_date",
                "SELECT code,trade_date,is_st,source,quality FROM stock_st_status_daily ORDER BY code,trade_date",
                "SELECT code,trade_date,total_share,float_share FROM stock_share_capital_daily ORDER BY code,trade_date",
                ("SELECT code,trade_date,total_mv,float_mv,reported_total_mv,reported_float_mv "
                 "FROM daily_metrics ORDER BY code,trade_date"),
                "SELECT code,issue_type,status FROM data_quality_issue ORDER BY code,issue_type",
            ]
        ])
        timings.append({"mode": mode, "seconds": round(time.monotonic() - started, 3),
                        "source_calls": len(state.calls), "max_active": state.maximum,
                        "resolved": result["resolved"]})
    for before, after in zip(*snapshots, strict=True):
        pd.testing.assert_frame_equal(before, after)
    assert timings[1]["source_calls"] < timings[0]["source_calls"]
    print("STOCK_REPAIR_EQUIVALENCE " + json.dumps(timings))


@pytest.mark.parametrize("cancel", [False, True])
def test_empty_response_backoff_has_own_observation_and_cancel_records_elapsed(monkeypatch, cancel):
    from backend.datasource import observability, request_policy
    from backend.datasource.ths_board import ThsBoardSource

    now = [0.0]
    monkeypatch.setattr(observability.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(request_policy, "install_http_policy", lambda: None)
    monkeypatch.setattr(request_policy, "request_policy", lambda *_: request_policy.RequestPolicy(8, 30, 3, 2))

    def pause(seconds, check):
        now[0] += 1 if cancel else seconds
        if cancel:
            raise TaskCancelled()

    monkeypatch.setattr(request_policy, "pause", pause)
    response = SimpleNamespace(status_code=200, text="empty", raise_for_status=lambda: None)
    source = ThsBoardSource(session=SimpleNamespace(get=lambda *a, **k: response))
    monkeypatch.setattr(source, "_headers", lambda **_: {})
    tracker = RequestTracker()
    with observe_work(tracker):
        if cancel:
            with pytest.raises(TaskCancelled):
                source._http_get("https://d.10jqka.com.cn/test", accept=lambda _: False)
        else:
            assert source._http_get("https://d.10jqka.com.cn/test", accept=lambda _: False) == "empty"
    expected = 1 if cancel else 6
    result = tracker.snapshot()
    assert result["retry_wait_seconds"] == expected
    assert result["sources"]["ths_board"]["retry_wait_seconds"] == expected
    assert result["wait_seconds"] == result["network_seconds"] == 0 and not result["states"]


def test_annual_material_avoids_unselected_years_and_keeps_partial_failure_boundary():
    calls = []

    def fetch(code, board_type, start, end):
        calls.append((start, end))
        frame = (pd.DataFrame([{"trade_date": start, "close": 10.}])
                 if start.year == 2018 else pd.DataFrame())
        frame.attrs["failed_years"] = [] if start.year == 2018 else [2024]
        return frame

    source = SimpleNamespace(get_board_bar=fetch)
    early, late = date(2018, 3, 1), date(2024, 1, 5)
    raw = quality_repair_sources._annual_bars(source, "300000", "concept", [(early, early), (late, late)])
    assert calls == [(early, early), (late, late)]
    material = quality_repair_sources._MaterialSource(source, "bar", "300000", raw, None)
    assert material.get_board_bar("300000", "concept", early, early).attrs["failed_years"] == []
    assert material.get_board_bar("300000", "concept", late, late).attrs["failed_years"] == [2024]
    with pytest.raises(RuntimeError, match="不匹配"):
        material.get_board_bar("300001", "concept", early, early)


def test_cached_live_fund_material_cannot_bypass_historical_date_guard(setup, monkeypatch):
    from datetime import datetime

    from backend.services.eod_dates import SHANGHAI

    client, state, service, _ = setup(count=1)
    client.execute("UPDATE board_dict SET has_fund_flow=TRUE")
    service.src.fund_flow_is_live_snapshot = True
    service.src = quality_repair_sources._TaskBoardSource(service.src, service)
    monkeypatch.setattr(board_ingest, "_asia_now", lambda: datetime(2024, 1, 5, 16, tzinfo=SHANGHAI))
    service.ingest_board_fund_flow(snapshot_date=DAY, periods=("即时",), board_codes=state.codes)
    with pytest.raises(DataSourceError, match="不支持历史回填"):
        service.ingest_board_fund_flow(snapshot_date=DAYS[1], periods=("即时",), board_codes=state.codes)
    assert len(state.calls) == 1
    assert client.query_df("SELECT DISTINCT snapshot_date FROM board_fund_flow").iloc[0,0].date() == DAY


def test_serial_and_parallel_92_issue_landing_are_identical(setup, monkeypatch):
    """等量模拟网络延时+真实DDL/SQL/台账复检；比较原逐条拓扑与有界批量结果。"""
    import json

    snapshots, timings = [], []
    batch = quality_repair_sources.run_batched_repairs
    for mode in ["serial", "parallel"]:
        client, state, _, _ = setup(name=mode, count=92)
        ids = [issue(client, code) for code in state.codes]
        monkeypatch.setattr(quality_repair_sources, "run_batched_repairs",
                            (lambda *args: None) if mode == "serial" else batch)
        started = time.monotonic()
        result = run(ids, Context())
        elapsed = time.monotonic()-started
        assert result["resolved"] == 92 and len(state.calls) == 92
        assert state.maximum == (1 if mode == "serial" else 8)
        snapshots.append(client.query_df(
            "SELECT board_code,trade_date,open,high,low,close,volume,amount FROM board_bar ORDER BY board_code,trade_date"))
        timings.append({"mode": mode, "seconds": elapsed, "source_calls": len(state.calls),
                        "max_active": state.maximum, "resolved": result["resolved"]})
    pd.testing.assert_frame_equal(*snapshots)
    print("REPAIR_EQUIVALENCE " + json.dumps(timings))


@pytest.mark.parametrize("technical_failure", [False, True])
def test_grouped_dates_keep_partial_responses_and_retry_missing_targets(technical_failure):
    from backend.common.exceptions import SourceRequestError
    from backend.tests.test_ths_board_source import _FakeResp, _make_source

    source = _make_source({}, max_retries=3)
    calls = []
    first, second = DAYS[0], DAYS[2]

    def get(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 1:
            return _FakeResp('quotebridge({"data":"20240102,10,11,9,10.5,1000,2000"})')
        if technical_failure:
            raise SourceRequestError("传输预算耗尽")
        return _FakeResp('quotebridge({"data":"20240104,10,11,9,10.5,1000,2000"})')

    source._session.get = get
    raw = quality_repair_sources._annual_bars(
        source, "881121", "industry", [(first, first), (second, second)], {first, second},
    )
    assert len(calls) == 2  # 首次只取得一个日期，不能提前视为整组完成。
    material = quality_repair_sources._MaterialSource(source, "bar", "881121", raw, None)
    early = material.get_board_bar("881121", "industry", first, first)
    late = material.get_board_bar("881121", "industry", second, second)
    assert len(early) == 1 and early.attrs["failed_years"] == []
    assert late.empty == technical_failure
    assert late.attrs["failed_years"] == ([2024] if technical_failure else [])


def test_gap_repair_uses_shared_batch_landing_and_batch_quality(setup, monkeypatch):
    from backend.services.capital_quality import CapitalQualityService

    _client, _state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=16)
    batches, quality = [], []
    landing, sync = svc._write_daily_batch, CapitalQualityService.sync
    def write(materials, **kwargs):
        batches.append([item.code for item in materials])
        return landing(materials, **kwargs)
    def checked(self, scope=None):
        quality.append(scope)
        return sync(self, scope)
    monkeypatch.setattr(svc, "_write_daily_batch", write)
    monkeypatch.setattr(CapitalQualityService, "sync", checked)
    ids = [issue(svc.c, code, kind="history_data_gap", day=None) for code in codes]
    ctx = Context()
    result = run(ids, ctx)
    assert result["resolved"] == len(ids), ctx.logs
    assert any(len(batch) > 1 for batch in batches)
    assert any(len(scope) > 1 for scope in quality)
    assert max(map(len, batches)) <= svc.s.datasource.update_concurrency
    assert {code for batch in batches for code in batch} == set(codes)
    assert not ctx.checkpoint.get("stock_repair_pending")


@pytest.mark.parametrize("kind", ["capital_gap", "history_data_gap"])
def test_batch_cancel_after_landing_resumes_unfinished_maintenance(setup, monkeypatch, kind):
    from backend.services.capital_quality import CapitalQualityService

    client, state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    ids = [issue(client, code, kind=kind, day=None) for code in codes]
    ctx = Context()
    merge = svc._merge_valuation_batch
    def cancel(*args, **kwargs):
        merge(*args, **kwargs)
        ctx.cancel = True
        ctx.check_cancel()
    monkeypatch.setattr(svc, "_merge_valuation_batch", cancel)
    with pytest.raises(TaskCancelled):
        run(ids, ctx)
    assert state.active == 0
    assert ctx.checkpoint["stock_repair_pending"]
    assert not ctx.checkpoint.get("issue_done_ids")
    assert client.query_df(
        "SELECT count(*) FROM data_quality_issue WHERE status='fixing'"
    ).iloc[0, 0] == 0
    monkeypatch.setattr(svc, "_merge_valuation_batch", merge)
    ctx.cancel = False
    result = run(ids, ctx)
    assert result["resolved"] == len(ids), ctx.logs
    assert not ctx.checkpoint["stock_repair_pending"]
    remaining = CapitalQualityService(client).aggregate(codes)
    if kind == "capital_gap":
        assert remaining.empty
    else:
        # 夹具原有首日不属于本次日线缺口，不能把修复扩大成其它历史股本补采。
        assert remaining.date_end.dt.date.eq(DAYS[0]).all()
    assert client.query_df(
        "SELECT count(*) FROM daily_metrics WHERE code IN (SELECT unnest(?::VARCHAR[])) "
        "AND trade_date>? AND reported_total_mv IS NULL", [codes, DAYS[0]],
    ).iloc[0, 0] == 0


def test_gap_batch_landing_failure_keeps_all_checkpoints_and_claims_uncommitted(setup, monkeypatch):
    from backend.common.exceptions import StorageError

    client, state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
    def fail(_frame):
        raise StorageError("批次写入失败")
    monkeypatch.setattr(svc.repo, "upsert_daily_bar", fail)
    ctx = Context()
    with pytest.raises(StorageError, match="批次写入失败"):
        run(ids, ctx)
    assert not ctx.checkpoint.get("issue_done_ids")
    assert state.active == 0
    assert client.query_df(
        "SELECT count(*) FROM data_quality_issue WHERE status='open' AND fix_task_id IS NULL"
    ).iloc[0, 0] == len(ids)
    assert client.query_df(
        "SELECT count(*) FROM daily_bar WHERE code IN (SELECT unnest(?::VARCHAR[]))", [codes],
    ).iloc[0, 0] == len(codes)


def test_batch_claim_cannot_take_over_another_tasks_issue(setup, monkeypatch):
    from backend.services.data_report import DataIntegrityReport

    client, state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=1)
    iid = issue(client, codes[0], kind="capital_gap", day=None)
    client.execute("UPDATE data_quality_issue SET status='fixing',fix_task_id='other' WHERE id=?", [iid])
    ctx = Context()
    ctx._stock_batch_claimed = {iid}
    with pytest.raises(ValueError, match="仅未处理问题"):
        async_task._recover_one(client, DataIntegrityReport(client), svc, ctx, iid)
    assert client.query_df("SELECT fix_task_id FROM data_quality_issue WHERE id=?", [iid]).iloc[0, 0] == "other"
    assert not state.calls


def test_capital_cancel_before_terminal_callback_keeps_maintenance(setup, monkeypatch):
    client, _state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    ids = [issue(client, code, kind="capital_gap", day=None) for code in codes]
    ctx = Context()
    queue = svc._run_bounded_parallel
    def interrupted(*args, **kwargs):
        commit = kwargs["transform_batch"]
        def after_commit(entries):
            result = commit(entries)
            ctx.cancel = True
            ctx.check_cancel()
            return result
        kwargs["transform_batch"] = after_commit
        return queue(*args, **kwargs)
    monkeypatch.setattr(svc, "_run_bounded_parallel", interrupted)
    with pytest.raises(TaskCancelled):
        run(ids, ctx)
    assert not ctx.checkpoint.get("issue_done_ids")
    assert set(ctx.checkpoint["stock_repair_pending"]) == {f"capital:{code}" for code in codes}
    assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='fixing'").iloc[0, 0] == 0
    monkeypatch.setattr(svc, "_run_bounded_parallel", queue)
    ctx.cancel = False
    assert run(ids, ctx)["resolved"] == len(ids), ctx.logs
    assert not ctx.checkpoint["stock_repair_pending"]


def test_factor_failure_after_batch_landing_keeps_maintenance_for_resume(setup, monkeypatch):
    client, _state, svc, codes = wire_stock_repairs(setup, monkeypatch, count=4)
    ids = [issue(client, code, kind="history_data_gap", day=None) for code in codes]
    factors = svc._recompute_clean
    monkeypatch.setattr(svc, "_recompute_clean", lambda *a, **kw: {"fail": 1})
    ctx = Context()
    result = run(ids, ctx)
    assert not result["ok"] and result["failed"] == len(ids), ctx.logs
    assert set(ctx.checkpoint["stock_repair_pending"]) == {f"gap:{code}" for code in codes}
    assert not ctx.checkpoint.get("issue_done_ids")
    monkeypatch.setattr(svc, "_recompute_clean", factors)
    result = run(ids, ctx)
    assert result["resolved"] == len(ids), ctx.logs
    assert not ctx.checkpoint["stock_repair_pending"]
    assert client.query_df(
        "SELECT count(*) FROM daily_metrics WHERE code IN (SELECT unnest(?::VARCHAR[])) "
        "AND trade_date>? AND reported_total_mv IS NULL", [codes, DAYS[0]],
    ).iloc[0, 0] == 0


def test_gap_maintenance_does_not_replace_other_operation_and_keeps_frozen_history(setup, monkeypatch):
    client, _state, _svc, codes = wire_stock_repairs(setup, monkeypatch, count=1)
    code = codes[0]
    # 续跑时历史问题已被扫描收口，但同股近端问题仍在冻结范围中；维护要补完原历史日期。
    client.executemany(
        "INSERT INTO daily_bar(code,trade_date,open,high,low,close,volume,amount,adj_factor) "
        "VALUES (?,?,10,10,10,10,100,1000,1)", [(code, day) for day in DAYS[1:]],
    )
    iid = issue(client, code, kind="stale", day=DAY)
    ctx = Context()
    other = {"operation": "adj", "code": code, "full": False, "dates": []}
    ctx.checkpoint["stock_repair_pending"] = {
        f"adj:{code}": other,
        f"gap:{code}": {"operation": "gap", "code": code, "full": True,
                        "dates": [str(day) for day in DAYS[1:]]},
    }
    result = run([iid], ctx)
    assert result["resolved"] == 1, ctx.logs
    assert ctx.checkpoint["stock_repair_pending"] == {f"adj:{code}": other}
    assert client.query_df(
        "SELECT count(*) FROM daily_metrics WHERE code=? AND trade_date>? "
        "AND reported_total_mv IS NOT NULL", [code, DAYS[0]],
    ).iloc[0, 0] == len(DAYS) - 1
