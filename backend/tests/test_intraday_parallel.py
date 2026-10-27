"""分时真实任务处理器、共享取源策略及有界队列的并发闭环回归；仅替换外部传输。"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.config.settings import Settings
from backend.services import async_task, intraday_archive, intraday_source
from backend.services.async_task import TaskCancelled
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_archive import CODE, DAY, Context, Windows, window
from backend.tests.test_intraday_archive import db as db  # noqa: PLC0414 -- pytest夹具显式复用
from backend.tests.test_intraday_quotes import _frame, _Redis
from backend.tests.test_intraday_source import (
    request_settings as request_settings,  # noqa: PLC0414 -- pytest夹具显式复用
)


@pytest.mark.parametrize("count", [8, pytest.param(
    5000, marks=pytest.mark.skipif(not os.getenv("INTRADAY_SCALE_STOCKS"),
                                 reason="显式全市场规模门禁"),
)])
def test_repair_commits_quality_and_progress_before_full_market_finishes(db, monkeypatch, count):
    """真实恢复入口必须首股即关闭问题，而不是等全市场取源完成；仅替换外部传输。"""
    codes = [f"{600100 + index:06d}.SH" for index in range(count)]
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    db.executemany("INSERT INTO stock_basic(code,name,list_date) VALUES (?,?,'2026-09-09')",
                   [(code, code) for code in codes])
    with db.temp_view(pd.DataFrame({"code": codes})) as view:
        db.execute(f"INSERT INTO stock_intraday_monitor(code,monitoring_start) "
                   f"SELECT code,'2026-09-09' FROM {view}")
        db.execute(f"INSERT INTO daily_bar(code,trade_date,close) "
                   f"SELECT code,trade_date,3.6 FROM {view} CROSS JOIN trade_calendar "
                   "WHERE trade_date IN ('2026-09-09','2026-09-10')")
    archive = IntradayArchiveService(db)
    archive.sync(codes)
    cfg = Settings()
    cfg.datasource.update_concurrency = 4
    monkeypatch.setattr(intraday_archive, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    calls = []
    payload = pd.concat([_frame(date(2026, 9, 9)), _frame(date.fromisoformat(DAY))])

    class Transport:
        def get_intraday_1m(self, code, provider, **kwargs):
            calls.append(code)
            return payload.copy()

    cache = _Redis()
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs:
                        IntradaySourceService(redis_client=cache, source_factory=Transport, **kwargs))

    class LiveContext(Context):
        def __init__(self):
            super().__init__()
            self.updates = []

        def progress(self, value, message):
            self.updates.append((value, message))

        def set_checkpoint(self, **data):
            super().set_checkpoint(**data)
            done = data.get("intraday_repair_checkpoint", {}).get("intraday_done", [])
            if done:
                # 归档完成检查点提交前，选中问题必须已复检关闭并上报外层进度。
                assert len(self.checkpoint["issue_done_ids"]) == 2
                assert db.query_df("SELECT count(*) n FROM data_quality_issue "
                                   "WHERE code=? AND status='resolved'", [done[0]]).iloc[0].n == 2
                assert any(value > 0.1 and "已解决 2 条" in msg for value, msg in self.updates)
                self.cancel = True

    ctx = LiveContext()
    with pytest.raises(TaskCancelled):
        async_task._h_fix({"issue_type": "intraday_gap"}, ctx)
    assert len(ctx.checkpoint["fix_scope_ids"]) == 2 * count
    assert 1 <= len(calls) <= 4 < count
    assert len(ctx.checkpoint["intraday_repair_checkpoint"]["intraday_done"]) == 1


@pytest.mark.parametrize("prior_error", [False, True])
def test_resume_legacy_archived_stock_reconciles_ledger_before_next_request(db, monkeypatch, prior_error):
    """兼容旧检查点：先收敛已落库但未关闭的台账，不再请求已完成股票。"""
    other = "600001.SH"
    db.execute("INSERT INTO stock_basic(code,name,list_date) VALUES (?,'第二股',?)", [other, DAY])
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,3.6)", [other, DAY])
    source = Windows([window(rows=10)])
    archive = IntradayArchiveService(db, quotes=source)
    archive.collect()
    ids = db.query_df("SELECT id FROM data_quality_issue ORDER BY id").id.tolist()
    archive.write_day(CODE, DAY, [window()])
    ctx = Context()
    ctx.checkpoint = {"fix_scope_ids": ids, "intraday_repair_checkpoint": {"intraday_done": [CODE]}}
    if prior_error:
        ctx.checkpoint["intraday_repair_checkpoint"]["intraday_failed"] = {CODE: "旧请求失败"}
    class NextStock(Windows):
        def fetch_window(self, code, dates, **kwargs):
            assert code == other
            assert db.query_df("SELECT status FROM data_quality_issue WHERE code=?", [CODE]).iloc[0, 0] == "resolved"
            return super().fetch_window(code, dates, **kwargs)

    next_source = NextStock([window()])
    cfg = Settings()
    cfg.datasource.update_concurrency = 1  # 传输替身内读取隔离库，仅此回归使用串行。
    monkeypatch.setattr(intraday_archive, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs: next_source)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    result = async_task._h_fix({"issue_ids": ids}, ctx)
    assert result["ok"] and result["resolved"] == 2
    assert len(next_source.calls) == 1
    assert ctx.checkpoint["intraday_repair_checkpoint"]["intraday_failed"] == {}


def test_resume_retries_unresolved_stock_even_after_error_free_archive_checkpoint(db, monkeypatch):
    """取源无异常但分钟仍缺失时，归档完成不等于问题解决，续跑可继续补采。"""
    source = Windows([window(rows=10)])
    IntradayArchiveService(db, quotes=source).collect()
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs: source)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    ctx = Context()
    first = async_task._h_fix({"issue_type": "intraday_partial"}, ctx)
    assert not first["ok"] and first["retryable"]
    assert ctx.checkpoint["intraday_repair_checkpoint"]["intraday_done"] == [CODE]
    previous_calls = len(source.calls)
    source.windows = [window()]
    resumed = Context()
    resumed.checkpoint = json.loads(json.dumps(ctx.checkpoint))
    result = async_task._h_fix({"issue_type": "intraday_partial"}, resumed)
    assert result["ok"] and result["resolved"] == 1
    assert len(source.calls) == previous_calls + 1


def test_daily_and_quality_repair_share_parallel_source_and_resume(db, monkeypatch):
    """96股×两日经日常采集、备用源恢复、取消与失败续跑；主线程独占全部写入。"""
    codes = [f"600{index:03d}.SH" for index in range(100, 196)]
    days = ["2026-09-09", DAY]
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    db.executemany(
        "INSERT INTO stock_basic(code,name,list_date) VALUES (?,?,'2026-09-09')",
        [(code, code) for code in codes],
    )
    db.executemany(
        "INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,3.6)",
        [(code, day) for code in codes for day in days],
    )
    cfg = Settings()
    cfg.datasource.update_concurrency = 4
    cfg.datasource.rate_limit_per_sec = 50
    cfg.datasource.socket_timeout_sec = 0.2
    cfg.datasource.max_retries = 2
    cfg.datasource.retry_backoff_sec = 0
    monkeypatch.setattr(intraday_archive, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(intraday_source, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    cache = _Redis()
    stage = "daily"
    calls, writes = [], []
    active, peaks, starts = {}, {}, {}
    gates = {name: threading.Barrier(4) for name in ("daily", "cancel", "resume")}
    lock = threading.Lock()
    fail_last = True

    class Transport:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            phase = stage
            with lock:
                active[phase] = active.get(phase, 0) + 1
                peaks[phase] = max(peaks.get(phase, 0), active[phase])
                starts[phase] = starts.get(phase, 0) + 1
                first_batch = starts[phase] <= 4
                calls.append((phase, code, provider, timeout_sec, request_year))
            try:
                # 首批确实重叠执行；其余工作走相同队列，不能靠耗时推断并发。
                if phase in gates and first_batch:
                    gates[phase].wait(timeout=5)
                time.sleep(0.02)
                if phase != "daily" and fail_last and code == codes[-1]:
                    raise ConnectionError("测试单股断线")
                partial = phase == "daily" or (provider == "sina" and int(code[:6]) % 2)
                frame = pd.concat(
                    [_frame(date.fromisoformat(day), rows=10 if partial else 240) for day in days],
                    ignore_index=True,
                )
                price = 3 + int(code[3:6]) / 1000
                frame["open"] = frame["high"] = frame["low"] = frame["close"] = price
                return frame
            finally:
                with lock:
                    active[phase] -= 1

    # 保留真实取源服务、共享Redis限流、候选选择及清洗，只用合成传输替代免费外部接口。
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs:
                        IntradaySourceService(redis_client=cache, source_factory=Transport, **kwargs))
    main_thread = threading.get_ident()
    original_write = IntradayArchiveService.write_day
    cancel_writes = 0
    repair = Context()

    def write(self, *args, **kwargs):
        nonlocal cancel_writes
        writes.append(threading.get_ident())
        result = original_write(self, *args, **kwargs)
        if stage == "cancel":
            cancel_writes += 1
            if cancel_writes == 3:
                repair.cancel = True
        return result

    monkeypatch.setattr(IntradayArchiveService, "write_day", write)
    daily = Context()
    daily.svc = SimpleNamespace(market=db)
    result = async_task._h_intraday_ingest({"codes": codes}, daily)
    assert result["ok"] and result["partial"] == len(codes) * 2
    # 日常任务现已包含主源归档后的定向补齐；本夹具关闭复查间隔，补齐时可重取主源。
    assert len(calls) == len(codes) * 3 and {row[2] for row in calls} == {"sina", "ths"}
    assert peaks["daily"] == 4
    checked = async_task._h_verify({"scope": "intraday", "codes": codes}, daily)
    assert checked["quality"]["intraday"]["intraday_partial"] == len(codes) * 2
    assert len(calls) == len(codes) * 3  # 质检扫描只读本地事实，不触发在线取源。

    stage = "cancel"
    with pytest.raises(TaskCancelled):
        async_task._h_fix({"issue_type": "intraday_partial"}, repair)
    nested = repair.checkpoint["intraday_repair_checkpoint"]
    done = set(nested["intraday_done"])
    frozen = repair.checkpoint["fix_scope_ids"]
    assert len(done) == 1 and len(frozen) == len(codes) * 2
    assert not any(active.values())  # 终态前已经等待所有在途取源退出。

    # 后来检出的问题不能混入冻结任务；已完成股票在续跑时也不能重复取源。
    from backend.services.data_report import DataIntegrityReport

    DataIntegrityReport(db)._insert_issues([{
        "code": CODE, "trade_date": DAY, "issue_type": "intraday_partial", "detail": "{}",
    }])
    stage = "resume"
    resumed = Context()
    resumed.checkpoint = json.loads(json.dumps(repair.checkpoint))
    result = async_task._h_fix({"issue_type": "intraday_partial"}, resumed)
    assert not result["ok"] and result["technical_failure"] == 2
    assert peaks["cancel"] == peaks["resume"] == 4
    assert done.isdisjoint(row[1] for row in calls if row[0] == "resume")
    assert resumed.checkpoint["fix_scope_ids"] == frozen

    fail_last = False
    stage = "retry_failed"
    retried = Context()
    retried.checkpoint = json.loads(json.dumps(resumed.checkpoint))
    result = async_task._h_fix({"issue_type": "intraday_partial"}, retried)
    assert result["ok"]
    assert {row[1] for row in calls if row[0] == "retry_failed"} == {codes[-1]}
    assert set(writes) == {main_thread}
    assert {row[3] for row in calls} == {0.2}
    assert {row[4] for row in calls if row[2] == "ths"} == {2026}
    assert {f"market:source:rate:v1:{name}" for name in ("sina", "ths")} <= cache.values.keys()
    assert set(db.query_df(
        "SELECT status FROM data_quality_issue WHERE id IN (SELECT unnest(?::BIGINT[]))",
        [frozen],
    ).status) == {"resolved"}
    assert db.query_df("SELECT status FROM data_quality_issue WHERE code=?", [CODE]).iloc[0, 0] == "open"
    rows = db.query_df(
        "SELECT code,min(close) lo,max(close) hi,count(*) n FROM stock_intraday_bar GROUP BY code"
    )
    assert len(rows) == len(codes) and set(rows.n) == {480}
    for row in rows.itertuples():
        assert row.lo == row.hi == pytest.approx(3 + int(row.code[3:6]) / 1000)


@pytest.mark.parametrize("state", ["ignored", "resolved", "done"])
def test_repair_filters_non_pending_issues_before_source_submission(db, monkeypatch, state):
    archive = IntradayArchiveService(db, quotes=Windows([window(rows=10)]))
    archive.collect()
    issue_id = int(db.query_df("SELECT id FROM data_quality_issue").iloc[0, 0])
    ctx = Context()
    if state == "done":
        ctx.checkpoint["issue_done_ids"] = [issue_id]
    else:
        db.execute("UPDATE data_quality_issue SET status=? WHERE id=?", [state, issue_id])
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs:
                        pytest.fail("非待处理问题不能提交分时取源"))
    async_task._h_fix({"issue_ids": [issue_id]}, ctx)
