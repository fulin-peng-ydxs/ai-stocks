"""批量修复真实落库回归：有界取源、原口径复检、失败不重复取源及取消续跑。"""

import threading
import time
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError
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
        time.sleep(.015)
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
    state.empty = {state.codes[0]}
    client.execute("INSERT INTO board_member(board_code,code) VALUES (?, '000001.SZ')", [state.codes[0]])
    ids = [issue(client, code, kind="board_member_incomplete") for code in state.codes]
    result = run(ids, Context())
    assert result["resolved"] == 11 and result["failed"] == 1
    assert state.maximum == 8 and len(state.calls) == 12
    assert client.query_df("SELECT code FROM board_member WHERE board_code=?", [state.codes[0]]).code.tolist() == ["000001.SZ"]


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


def test_four_capital_issue_types_do_not_repeat_full_history_or_close_remaining_issues(setup, monkeypatch):
    from backend.services.data_report import DataIntegrityReport

    client, _, _, svc = setup()
    codes = ["600000.SH", "600519.SH"]
    ids = [issue(client, code, kind=kind) for kind in quality_repair_sources.CAPITAL_TYPES for code in codes]
    recheck = DataIntegrityReport.recheck_clean
    monkeypatch.setattr(DataIntegrityReport, "recheck_clean", lambda self, kind, code, day, **kw:
                        False if kind in quality_repair_sources.CAPITAL_TYPES else recheck(self, kind, code, day, **kw))
    calls = []
    svc.repair_capital_quality = lambda code, ctx: calls.append(code) or {"rows": 0}
    for _ in range(2):
        result = run(ids, Context())
        assert result["resolved"] == result["failed"] == 0
        assert client.query_df("SELECT count(*) FROM data_quality_issue WHERE status='open'").iloc[0,0] == 8
    assert calls == codes * 2  # 缓存仅本任务有效，下一任务仍可真实重试。


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
