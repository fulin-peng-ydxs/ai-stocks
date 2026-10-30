"""通用BaoStock执行器的入口覆盖、跨任务额度、ST发布和参考价等价回归。"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from backend.datasource import baostock_executor as executor
from backend.datasource.baostock_source import BaostockSource
from backend.services.stock_st_status import StockSTStatusService
from backend.tests.test_daily_collection_performance import DAY, Context, bars
from backend.tests.test_daily_collection_performance import service as service  # noqa: PLC0414


def _mixed_query(operation, args, kwargs, queued_at=None):
    """跨真实spawn传输各类响应；源业务逻辑仍由服务层执行。"""
    from backend.datasource.baostock_executor import _check_cancel

    _check_cancel()
    time.sleep(.02)
    code = args[0] if args else "600000.SH"
    counts = {"requests": 1}
    error = None
    if code == "600005.SH":
        counts["failures"] = 1
        value, error = None, {"message": "source failed", "exhausted": True}
    elif operation == "get_st_status":
        value = pd.DataFrame([{"code": code, "trade_date": day.date(),
                               "is_st": bool(int(code[:6]) % 2), "trade_status": 1}
                              for day in pd.bdate_range(args[1], args[2])])
    elif operation == "get_daily_bar":
        value = pd.concat([bars(code).assign(trade_date=day.date())
                           for day in pd.bdate_range(args[1], args[2])], ignore_index=True)
        value["reference_pre_close"] = 10.0
        value["reference_close"] = value["close"]
        value["reference_source"] = "baostock"
        if code == "600003.SH":
            value["close"] = 12.0  # 参考价不匹配必须拒用，不能覆盖本地原始价。
    elif operation == "get_delisted_list":
        value = pd.DataFrame([{"code": c, "name": c, "delist_date": DAY + timedelta(days=1)}
                              for c in ["600000.SH", "600002.SH", "600005.SH"]])
    else:
        value = pd.DataFrame([{"operation": operation, "code": code}])
    return value, error, False, counts, {"baostock": counts}, {"_baostock_worker_pid": os.getpid()}


def _network_query(operation, args, kwargs, queued_at=None):
    """在独立Redis测试键上验证不同任务进程池的合计在途额度。"""
    import redis

    from backend.datasource import request_policy, request_runtime
    from backend.datasource.baostock_executor import _check_cancel
    from backend.datasource.request_policy import RequestPolicy

    _check_cancel()
    policy = RequestPolicy(50, 1, 1, 0, concurrency=4)
    request_policy.request_policy = lambda *_: policy
    request_runtime._keys = lambda _: kwargs["keys"]
    client = redis.Redis.from_url(kwargs["url"], decode_responses=True)
    try:
        with request_runtime.request_slot("baostock", policy, client=client, check=_check_cancel):
            time.sleep(.15)
        return args[0], None, False, {"requests": 1}, {}, {"_baostock_worker_pid": os.getpid()}
    finally:
        client.close()


def test_all_public_operations_use_one_shared_task_executor(monkeypatch):
    source = BaostockSource()
    calls = []
    scope = SimpleNamespace(workers=4, call=lambda op, *a, **k: calls.append((op, a, k)) or op)
    with executor.bind_executor(scope):
        for operation in executor.OPERATIONS:
            assert getattr(source, operation)() == operation
    assert {x[0] for x in calls} == executor.OPERATIONS
    assert len(calls) == len(executor.OPERATIONS)


def test_nested_scopes_reuse_pool_and_idle_scope_does_not_spawn():
    with executor.execution_scope(4) as outer, executor.execution_scope(1) as inner:
        assert inner is outer and outer.executor is None
    assert outer.closed and outer.executor is None


def test_unknown_operation_cannot_run_arbitrary_source_method():
    with executor.BaostockExecutor(4) as pool:
        with pytest.raises(ValueError, match="未登记"):
            pool.call("close")
        assert pool.executor is None


def test_cancelling_one_task_does_not_cancel_another(monkeypatch):
    from backend.common.exceptions import SourceRequestError
    from backend.services.async_task import TaskCancelled

    monkeypatch.setattr(executor, "_query", _mixed_query)
    with executor.BaostockExecutor(2) as first, executor.BaostockExecutor(2) as second:
        assert first.call("get_basic_dates").iloc[0].operation == "get_basic_dates"
        first.cancel()
        with pytest.raises(TaskCancelled):
            first.call("get_st_status", "600000.SH", DAY, DAY)
        assert second.call("get_industry").iloc[0].operation == "get_industry"
        with pytest.raises(SourceRequestError, match="source failed"):
            second.call("get_st_status", "600005.SH", DAY, DAY)
        assert not second.cancel_event.is_set()


def test_two_task_pools_share_four_network_slots(monkeypatch):
    from backend.storage import get_redis_client

    store = get_redis_client()
    client = store.client
    prefix = f"pytest:bao-shared:{uuid4().hex}:"
    keys = [prefix + suffix for suffix in ["active", "last", "stats", "starts", "waiting"]]
    monkeypatch.setattr(executor, "_query", _network_query)
    stop = threading.Event()
    active = []

    def sample():
        while not stop.is_set():
            active.append(client.hlen(keys[0]))
            stop.wait(.005)

    sampler = threading.Thread(target=sample)
    sampler.start()
    try:
        with (executor.BaostockExecutor(4) as a, executor.BaostockExecutor(4) as b,
              ThreadPoolExecutor(8) as callers):
            futures = [callers.submit((a if i % 2 else b).call, "get_st_status", i,
                                           keys=keys, url=store.url) for i in range(16)]
            assert [f.result(timeout=30) for f in futures] == list(range(16))
        assert max(active) == 4
        assert client.hlen(keys[0]) == client.hlen(keys[4]) == 0
        assert int(client.hget(keys[2], "requests")) == 16
    finally:
        stop.set()
        sampler.join()
        client.delete(*keys)


def _seed(service, codes):
    basic = pd.DataFrame([{"code": code, "name": code, "board": "主板", "list_date": DAY,
                           "price_limit_pct": .1} for code in codes])
    service.repo.upsert_stock_basic(basic)
    service.repo.upsert_daily_bar(pd.concat([bars(code) for code in codes], ignore_index=True)
                                  .drop(columns=["float_share", "total_share"]))


@pytest.mark.parametrize("failed", [False, True])
def test_parallel_st_refresh_preserves_publication_and_retry_checkpoint(service, monkeypatch, failed):
    codes = [f"{600000+i}.SH" for i in range(130) if failed or i != 5]
    _seed(service, codes)
    source = BaostockSource()
    monkeypatch.setattr(service, "_source_for", lambda *_: source)
    monkeypatch.setattr(executor, "_query", _mixed_query)
    main = threading.get_ident()
    original = StockSTStatusService.upsert_facts

    def upsert(obj, *args, **kwargs):
        assert threading.get_ident() == main
        return original(obj, *args, **kwargs)

    monkeypatch.setattr(StockSTStatusService, "upsert_facts", upsert)
    ctx = Context()
    result = service.refresh_st_status(codes=codes, start=DAY, end=DAY, ctx=ctx)
    assert result["fail"] == int(failed)
    assert result["publication_status"] == ("failed" if failed else "ready")
    facts = service.c.query_df("SELECT code,is_st,quality FROM stock_st_status_daily ORDER BY code")
    assert len(facts) == 129 and facts.quality.eq("accurate").all()
    assert facts.is_st.tolist() == [bool(i % 2) for i in range(130) if i != 5]
    assert "600005.SH" not in ctx.checkpoint["st_done_codes"]
    if failed:
        assert result["projection_rows"] == 0
        assert StockSTStatusService(service.c).refresh_state()["status"] == "failed"
    assert ctx.request_tracker.snapshot()["requests"] == len(codes)


def test_parallel_reference_refresh_keeps_prices_and_rejects_unmatched_source(service, monkeypatch):
    codes = ["600000.SH", "600003.SH", "600005.SH"]
    _seed(service, codes)
    source = BaostockSource()
    monkeypatch.setattr(service, "_bao_source", lambda: source)
    monkeypatch.setattr(executor, "_query", _mixed_query)
    before = service.c.query_df("SELECT code,open,high,low,close,volume,amount,adj_factor FROM daily_bar ORDER BY code")
    result = service.refresh_price_references(codes, ctx=Context())
    assert result["updated"] == result["unmatched"] == 1
    assert list(result["errors"]) == ["600005.SH"]
    after = service.c.query_df("SELECT code,open,high,low,close,volume,amount,adj_factor FROM daily_bar ORDER BY code")
    pd.testing.assert_frame_equal(before, after)
    reference = service.c.query_df("SELECT code,reference_pre_close FROM daily_bar ORDER BY code")
    assert reference.iloc[0].reference_pre_close == 10
    assert reference.iloc[1:].reference_pre_close.isna().all()


def _recovered_query(operation, args, kwargs, queued_at=None):
    if args and args[0] == "600005.SH":
        updated = ("600006.SH", *args[1:])
        value, error, cancelled, counts, sources, meta = _mixed_query(operation, updated, kwargs, queued_at)
        if value is not None and "code" in value:
            value["code"] = args[0]
            if operation == "get_st_status":
                value["is_st"] = True
        return value, error, cancelled, counts, sources, meta
    return _mixed_query(operation, args, kwargs, queued_at)


@pytest.mark.parametrize("workers", [1, 4])
def test_delisted_parallel_uses_effective_boundary_and_resumes_missing_stock(service, monkeypatch, workers):
    source = BaostockSource()
    monkeypatch.setattr(service, "_source_for", lambda *_: source)
    monkeypatch.setattr(service, "_history_window", lambda *_: (DAY-timedelta(days=3), DAY))
    monkeypatch.setattr(executor, "_query", _mixed_query)
    if workers == 1:
        # 单路原生调用不用RPC；同一材料验证单路/多路采用相同有效摘牌边界与续跑规则。
        def native(operation):
            def call(*args, **kwargs):
                from backend.common.exceptions import SourceRequestError

                value, error, *_ = executor._query(operation, args, kwargs)
                if error:
                    raise SourceRequestError(error["message"])
                return value
            return call

        for operation in ["get_delisted_list", "get_daily_bar", "get_st_status"]:
            monkeypatch.setattr(source, operation, native(operation))
        monkeypatch.setattr(service, "_thread_source", lambda *_: source)
    service.c.execute("INSERT INTO trade_calendar VALUES (?,TRUE)", [DAY-timedelta(days=3)])
    service.c.execute(
        "INSERT INTO stock_basic(code,list_date,delist_date,delist_date_manual) "
        "VALUES ('600002.SH',DATE '2020-01-01',?,TRUE)", [DAY-timedelta(days=1)],
    )
    with executor.execution_scope(workers):
        first = service.ingest_delisted(years=1, ctx=Context())
    assert first["ok"] == 2 and first["fail"] == 1
    dates = service.c.query_df("SELECT code,trade_date FROM daily_bar ORDER BY code,trade_date")
    assert dates[dates.code.eq("600000.SH")].trade_date.dt.date.tolist() == [DAY-timedelta(days=3), DAY]
    assert dates[dates.code.eq("600002.SH")].trade_date.dt.date.tolist() == [DAY-timedelta(days=3)]
    assert "600005.SH" not in dates.code.tolist()
    assert service.c.query_df("SELECT delist_date FROM stock_basic WHERE code='600002.SH'").iloc[0,0].date() == DAY-timedelta(days=1)
    monkeypatch.setattr(executor, "_query", _recovered_query)
    with executor.execution_scope(workers):
        second = service.ingest_delisted(years=1, ctx=Context())
    assert second["skip"] == 2 and second["ok"] == 1 and second["fail"] == 0
    facts = service.c.query_df("SELECT * FROM stock_st_status_daily WHERE code='600005.SH'")
    assert len(facts) == 2 and facts.is_st.all() and facts.quality.eq("accurate").all()
