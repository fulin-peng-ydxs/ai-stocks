"""ST会话互斥必须覆盖实际请求，但不能覆盖请求之间的退避。"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import pytest

from backend.datasource import base
from backend.datasource.baostock_source import _SESSION_LOCK
from backend.datasource.request_policy import RequestPolicy
from backend.services.ingest import IngestionService
from backend.tests.test_daily_collection_performance import Context, bars, run_daily
from backend.tests.test_daily_collection_performance import service as service  # noqa: PLC0414


def _isolated_status(operation, args, kwargs, queued_at=None):
    """真正spawn的夹具：乱序完成、每进程独立身份，并返回可核对的日期与状态。"""
    assert operation == "get_st_status"
    code, start, _end = args
    from backend.datasource.baostock_executor import _check_cancel

    _check_cancel()
    time.sleep(0.03 if int(code[:6]) % 2 else 0.005)
    _check_cancel()
    if code == "699999.SH":
        return None, {"message": "模拟完整请求失败", "exhausted": False}, False, {"requests": 1, "failures": 1}, {}, {}
    frame = pd.DataFrame([{"code": code, "trade_date": start,
                           "is_st": bool(int(code[:6]) % 2), "trade_status": 0}])
    frame.attrs["pid"] = os.getpid()
    return frame, None, False, {"requests": 1}, {"baostock": {"requests": 1}}, {"_baostock_worker_pid": os.getpid()}


def _isolated_trading_status(operation, args, kwargs, queued_at=None):
    frame, *rest = _isolated_status(operation, args, kwargs, queued_at)
    if frame is not None:
        frame["trade_status"] = 1
    return frame, *rest


@pytest.mark.parametrize("capacity,work_concurrency", [(1, 6), (2, 6), (4, 6), (4, 2)])
def test_daily_pipeline_keeps_st_prices_and_partial_failure_with_pool_or_rollback(
    service, monkeypatch, capacity, work_concurrency,
):
    """130只实际落库：单会话、两/四进程结果一致，且不能突破工作并发。"""
    from backend.common.exceptions import DataSourceError
    from backend.datasource import baostock_executor as pools
    from backend.datasource import request_policy as policies
    from backend.datasource.baostock_source import BaostockSource
    from backend.tests.test_daily_collection_performance import DAY

    source = BaostockSource()
    service.src.supports = lambda _: False
    monkeypatch.setattr(service, "_source_for", lambda *_: source)
    monkeypatch.setattr(service, "_thread_source", lambda *_: service.src)
    monkeypatch.setattr(service, "_fetch_daily_with_fallback", lambda code, *_: (bars(code), "akshare"))
    monkeypatch.setattr(policies, "request_policy",
                        lambda *_: RequestPolicy(5, 30, 3, 2, concurrency=capacity))
    monkeypatch.setattr(pools, "_query", _isolated_trading_status)

    def direct(code, start, end):
        frame, error, *_ = _isolated_trading_status("get_st_status", (code, start, end), {})
        if error:
            raise DataSourceError(error)
        return frame

    if capacity == 1:
        monkeypatch.setattr(source, "get_st_status", direct)
    codes = [f"{600000+i}.SH" for i in range(129)] + ["699999.SH"]
    ctx = Context()
    results = run_daily(service, codes, ctx=ctx, concurrency=work_concurrency)
    assert sum(error is not None for _, _, error in results) == 1
    assert [code for code, _, error in results if error is not None] == ["699999.SH"]
    facts = service.c.query_df("SELECT code,trade_date,is_st,quality FROM stock_st_status_daily ORDER BY code")
    assert len(facts) == 129 and facts.quality.eq("accurate").all()
    assert facts.trade_date.dt.date.eq(DAY).all()
    assert facts.is_st.tolist() == [bool(i % 2) for i in range(129)]
    prices = service.c.query_df("SELECT code,open,high,low,close,volume,amount FROM daily_bar ORDER BY code")
    assert prices.code.tolist() == sorted(codes[:-1])
    assert prices[["open", "high", "low", "close"]].eq(10).all().all()
    assert prices.volume.eq(100).all() and prices.amount.eq(1000).all()
    assert len(service.c.query_df("SELECT * FROM daily_metrics")) == 129
    assert getattr(service, "_daily_st_pool", None) is None
    expected = min(capacity, work_concurrency) if capacity > 1 else None
    assert ctx.request_tracker.meta.get("baostock_pool_capacity") == expected


def test_worker_accounts_for_queue_wait_separately_from_network(monkeypatch):
    from types import SimpleNamespace

    from backend.datasource import baostock_executor, baostock_source
    from backend.datasource.observability import record, record_source

    day = date(2026, 10, 28)
    frame = pd.DataFrame([{"code": "600000.SH", "trade_date": day,
                           "is_st": False, "trade_status": 1}])

    def query(*args):
        record(requests=1, network_seconds=5)
        record_source("baostock", requests=1, network_seconds=5)
        return frame

    monkeypatch.setattr(baostock_source, "shared_baostock",
                        lambda: SimpleNamespace(get_st_status=query))
    result, error, cancelled, counts, sources, _ = baostock_executor._query(
        "get_st_status", ("600000.SH", day, day), {}, time.monotonic() - 2,
    )
    assert result is frame and error is None and not cancelled
    assert counts["session_wait_seconds"] >= 2
    assert sources["baostock"]["session_wait_seconds"] == counts["session_wait_seconds"]
    assert counts["network_seconds"] == sources["baostock"]["network_seconds"] == 5


def _initialize_together(cancel_event, barrier):
    from backend.datasource.baostock_executor import _initialize

    _initialize(cancel_event)
    barrier.wait(timeout=30)


@pytest.mark.parametrize("workers", [2, 4])
def test_spawn_pool_preserves_identity_aggregates_metrics_and_closes(monkeypatch, workers):
    import multiprocessing

    from backend.datasource import baostock_executor as pools
    from backend.datasource.observability import RequestTracker

    barrier = multiprocessing.get_context("spawn").Barrier(workers)
    original = pools.ProcessPoolExecutor

    def executor(*args, **kwargs):
        kwargs["initializer"] = _initialize_together
        kwargs["initargs"] = (*kwargs["initargs"], barrier)
        return original(*args, **kwargs)

    monkeypatch.setattr(pools, "ProcessPoolExecutor", executor)
    monkeypatch.setattr(pools, "_query", _isolated_status)
    tracker = RequestTracker()
    codes = [f"{600000+i}.SH" for i in range(130)]
    day = date(2026, 10, 28)
    with pools.BaostockExecutor(workers, tracker=tracker) as pool, ThreadPoolExecutor(6) as callers:
        results = list(callers.map(lambda code: pool.call("get_st_status", code, day, day), codes))
        processes = list(pool.executor._processes.values())
    assert len({frame.attrs["pid"] for frame in results}) == workers
    assert os.getpid() not in {frame.attrs["pid"] for frame in results}
    for code, frame in zip(codes, results, strict=True):
        assert frame.to_dict("records") == [{"code": code, "trade_date": day,
                                              "is_st": bool(int(code[:6]) % 2),
                                              "trade_status": 0}]
    assert tracker.snapshot()["requests"] == 130
    assert tracker.snapshot()["sources"]["baostock"]["requests"] == 130
    assert all(not process.is_alive() for process in processes)


@pytest.mark.parametrize("workers", [2, 4])
def test_spawn_pool_failure_is_not_returned_as_empty_success(monkeypatch, workers):
    import pytest

    from backend.common.exceptions import DataSourceError
    from backend.datasource import baostock_executor as pools
    from backend.datasource.observability import RequestTracker

    monkeypatch.setattr(pools, "_query", _isolated_status)
    tracker = RequestTracker()
    day = date(2026, 10, 28)
    with pools.BaostockExecutor(workers, tracker=tracker) as pool:
        with pytest.raises(DataSourceError, match="模拟完整请求失败"):
            pool.call("get_st_status", "699999.SH", day, day)
        assert pool.call("get_st_status", "600000.SH", day, day).code.tolist() == ["600000.SH"]
    assert tracker.snapshot()["requests"] == 2
    assert tracker.snapshot()["failures"] == 1


@pytest.mark.parametrize("workers", [2, 4])
def test_spawn_pool_cancel_closes_workers_and_does_not_publish_result(monkeypatch, workers):
    import pytest

    from backend.datasource import baostock_executor as pools
    from backend.datasource.base import thread_cancel_scope
    from backend.services.async_task import TaskCancelled

    monkeypatch.setattr(pools, "_query", _isolated_status)
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise TaskCancelled()

    day = date(2026, 10, 28)
    with (
        pytest.raises(TaskCancelled), pools.BaostockExecutor(workers) as pool,
        thread_cancel_scope(cancel),
    ):
        pool.call("get_st_status", "600001.SH", day, day)
    assert pool.cancel_event.is_set()


@pytest.mark.parametrize("workers", [0, -1, 5, True, 1.5])
def test_pool_rejects_invalid_or_excessive_workers(workers):
    from backend.datasource.baostock_executor import BaostockExecutor

    with pytest.raises(ValueError, match="整数"):
        BaostockExecutor(workers)


def test_st_backoff_allows_another_stock_to_use_session(monkeypatch):
    """第一股失败后的退避期间，第二股应完成，不能被外层兜底锁挡住。"""
    from backend.datasource import request_policy
    from backend.datasource.request_runtime import session_lock

    retry_started = threading.Event()
    resume_retry = threading.Event()
    calls = []
    monkeypatch.setattr(request_policy, "request_policy",
                        lambda *_: RequestPolicy(5, 30, 2, 2))

    def backoff(_seconds):
        retry_started.set()
        assert resume_retry.wait(3)

    monkeypatch.setattr(base, "_cancel_aware_sleep", backoff)

    class Source:
        name = "baostock"

        @base.with_retry()
        def get_st_status(self, code, start, end):
            # 与SDK的实际边界一致：一次请求结束或抛错即释放会话。
            with session_lock(_SESSION_LOCK, "baostock"):
                calls.append(code)
                if code == "600000.SH" and calls.count(code) == 1:
                    raise ConnectionError("temporary failure")
                return pd.DataFrame([{"code": code, "trade_date": start,
                                      "is_st": False, "trade_status": 1}])

    service = IngestionService.__new__(IngestionService)
    source = Source()
    monkeypatch.setattr(service, "_source_for", lambda *_: source)
    day = date(2026, 10, 28)
    with ThreadPoolExecutor(2) as executor:
        failing = executor.submit(service._fetch_st_status_rows, "600000.SH", day, day)
        try:
            assert retry_started.wait(2)
            healthy = executor.submit(service._fetch_st_status_rows, "600001.SH", day, day)
            assert healthy.result(timeout=1)[1].code.tolist() == ["600001.SH"]
        finally:
            resume_retry.set()
        assert failing.result(timeout=2)[1].code.tolist() == ["600000.SH"]
    assert calls == ["600000.SH", "600001.SH", "600000.SH"]


def test_sdk_query_stays_serial_inside_each_process(monkeypatch):
    from contextlib import nullcontext

    from backend.config.settings import Settings
    from backend.datasource import baostock_source as bao
    from backend.datasource import request_runtime

    source = bao.BaostockSource()
    monkeypatch.setattr(source, "_ensure_login", lambda: None)
    monkeypatch.setattr(source, "_hang_guard", lambda *_: nullcontext())
    monkeypatch.setattr(bao, "get_effective_settings", Settings)
    monkeypatch.setattr(request_runtime, "request_slot", lambda *a, **k: nullcontext())
    monkeypatch.setattr(bao, "_collect", lambda value: value)
    active = maximum = 0

    def query(value):
        def execute():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            try:
                time.sleep(0.005)
                return value
            finally:
                active -= 1
        return source._query_frame(execute)

    with ThreadPoolExecutor(6) as threads:
        assert list(threads.map(query, range(30))) == list(range(30))
    assert maximum == 1 and active == 0


@pytest.mark.parametrize("logged_in", [False, True])
def test_sdk_destructor_never_waits_on_another_query_session(monkeypatch, logged_in):
    from backend.datasource.baostock_source import BaostockSource

    source = BaostockSource()
    source._logged_in = logged_in
    cleaned = []
    monkeypatch.setattr(source, "_invalidate_login", lambda: cleaned.append(True))
    _SESSION_LOCK.acquire()
    try:
        with ThreadPoolExecutor(1) as thread:
            thread.submit(source.__del__).result(timeout=1)
    finally:
        _SESSION_LOCK.release()
        source._logged_in = False
    assert cleaned == []
