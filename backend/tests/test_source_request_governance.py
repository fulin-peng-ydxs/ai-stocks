"""请求治理真实 Redis 原子准入、跨进程共享、取消和有界落库回归。"""

import multiprocessing
import os
import time
from contextlib import contextmanager
from itertools import pairwise
from uuid import uuid4

import pandas as pd
import pytest
import redis

from backend.config.settings import Settings, SourceRequestOverrides
from backend.datasource import request_policy as rp
from backend.datasource import request_runtime as rt
from backend.datasource.observability import RequestTracker, observe_work
from backend.services.async_task import TaskCancelled
from backend.services.bounded_parallel import run_bounded_parallel


def _process_request(url, prefix, events):
    client = redis.Redis.from_url(url, decode_responses=True)
    policy = rp.RequestPolicy(50, 1, 1, 0, concurrency=2)
    rp.request_policy = lambda *_: policy
    rt._keys = lambda _: [
        prefix + name for name in ("active", "last", "stats", "starts", "waiting")
    ]
    for _ in range(3):
        with rt.request_slot("sina", policy, client=client):
            events.put(("start", time.time()))
            time.sleep(0.06)
            events.put(("end", time.time()))


@pytest.fixture
def runtime(monkeypatch):
    from backend.storage import get_redis_client

    store = get_redis_client()
    client = store.client
    client.ping()
    prefix = f"pytest:source:{uuid4().hex}:"
    keys = [prefix + name for name in ("active", "last", "stats", "starts", "waiting")]
    monkeypatch.setattr(rt, "_keys", lambda _: keys)
    policy = rp.RequestPolicy(
        50, 1, 1, 0, concurrency=2, wait_timeout=2, cooldown=0.1, failure_threshold=1
    )
    monkeypatch.setattr(rp, "request_policy", lambda *_: policy)
    yield client, policy, keys, prefix, store.url
    client.delete(*keys)


def test_shared_network_concurrency_and_rate_across_processes(runtime):
    client, _, keys, prefix, url = runtime
    context = multiprocessing.get_context("spawn")
    events = context.Queue()
    processes = [
        context.Process(target=_process_request, args=(url, prefix, events)) for _ in range(3)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(15)
            assert process.exitcode == 0
        samples = sorted(events.get(timeout=2) for _ in range(18))
        samples.sort(key=lambda event: event[1])
        active = maximum = 0
        starts = []
        for kind, timestamp in samples:
            active += 1 if kind == "start" else -1
            maximum = max(maximum, active)
            if kind == "start":
                starts.append(timestamp)
        assert maximum == 2 and active == 0
        # 用Redis原子准入时间验证频率；子进程拿到额度后可能被OS调度延迟，
        # 客户端事件时间不能反推真实准入间隔。
        admissions = [score for _, score in client.zrange(keys[3], 0, -1, withscores=True)]
        assert len(admissions) == 9
        assert all(b - a >= 0.019 for a, b in pairwise(admissions))
        assert client.hlen(keys[0]) == client.hlen(keys[4]) == 0
        assert int(client.hget(keys[2], "requests")) == 9
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
        events.close()


def test_cancelled_wait_does_not_leak_or_preconsume_slot(runtime):
    client, policy, keys, _, _ = runtime
    client.hset(
        keys[0],
        mapping={"held1": f"{rt._HOST}:{os.getpid()}", "held2": f"{rt._HOST}:{os.getpid()}"},
    )

    def cancel():
        raise TaskCancelled()

    with pytest.raises(TaskCancelled), rt.request_slot("sina", policy, client=client, check=cancel):
        pytest.fail("取消后不应请求来源")
    assert client.hlen(keys[4]) == 0
    assert client.hlen(keys[0]) == 2
    assert client.hget(keys[2], "requests") is None


def test_dead_local_owner_reclaimed_but_unverified_remote_owner_not_expired(runtime):
    client, policy, keys, _, _ = runtime
    client.hset(keys[0], "dead", f"{rt._HOST}:99999999")
    with rt.request_slot("sina", policy, client=client):
        assert client.hget(keys[0], "dead") is None
    client.hset(keys[0], mapping={"remote1": "unverified-host:1", "remote2": "unverified-host:2"})
    from dataclasses import replace

    with (
        pytest.raises(Exception, match="额度超时"),
        rt.request_slot("sina", replace(policy, wait_timeout=0.05), client=client),
    ):
        pytest.fail("不能仅凭超时回收未确认死亡的请求")
    assert client.hlen(keys[0]) == 2


def test_shared_cooldown_releases_network_slot_and_records_wait(runtime):
    client, policy, keys, _, _ = runtime
    with rt.request_slot("sina", policy, client=client) as outcome:
        outcome["failed"] = True
    assert client.hlen(keys[0]) == 0
    started = time.monotonic()
    with rt.request_slot("sina", policy, client=client):
        pass
    assert time.monotonic() - started >= 0.08
    assert float(client.hget(keys[2], "wait_seconds")) >= 0.08
    assert float(client.hget(keys[2], "cooldown_until")) == 0


def test_source_overrides_and_session_hard_limit():
    settings = Settings()
    settings.datasource.sources["sina"] = SourceRequestOverrides(
        network_concurrency=3, rate_limit_per_sec=7
    )
    assert rp.request_policy("sina", settings).concurrency == 3
    assert rp.request_policy("sina", settings).rate == 7
    settings.datasource.sources["baostock"] = SourceRequestOverrides(network_concurrency=9)
    assert rp.request_policy("baostock", settings).concurrency == 1
    with pytest.raises(ValueError, match="未登记来源"):
        Settings.model_validate({"datasource": {"sources": {"unknown": {"max_retries": 2}}}})


def test_actual_source_override_also_controls_sdk_semantic_retries(monkeypatch):
    from backend.datasource import base, share_capital
    from backend.datasource.akshare_source import AKShareSource

    settings = Settings()
    settings.datasource.max_retries = 1
    settings.datasource.sources["eastmoney"] = SourceRequestOverrides(
        max_retries=4,
        retry_backoff_sec=0,
    )
    monkeypatch.setattr(rp, "get_effective_settings", lambda: settings)
    waits, calls = [], []
    monkeypatch.setattr(base, "_cancel_aware_sleep", waits.append)

    def fetch(*args, **kwargs):
        calls.append(1)
        if len(calls) < 4:
            raise ValueError("源响应字段尚未就绪")
        return pd.DataFrame()

    monkeypatch.setattr(share_capital, "fetch_daily_valuation", fetch)
    source = AKShareSource.__new__(AKShareSource)
    source._share_timeout_sec = 1
    from datetime import date

    assert source.get_valuation("600000.SH", date(2026, 10, 22), date(2026, 10, 23)).empty
    assert len(calls) == 4 and waits == [0, 0, 0]


def test_nested_missing_context_preserves_cancellation_and_session_wait_is_bounded(monkeypatch):
    import threading
    from dataclasses import replace

    from backend.datasource.base import check_thread_cancel, thread_cancel_scope

    def cancel():
        raise TaskCancelled()

    with thread_cancel_scope(cancel), thread_cancel_scope(None), pytest.raises(TaskCancelled):
        check_thread_cancel()
    policy = replace(rp.RequestPolicy(5, 30, 1, 0), wait_timeout=0.01)
    monkeypatch.setattr(rp, "request_policy", lambda *_: policy)
    lock = threading.Lock()
    lock.acquire()
    try:
        with pytest.raises(Exception, match="本机会话超时"), rt.session_lock(lock, "baostock"):
            pytest.fail("不能越过已有会话")
        with (
            thread_cancel_scope(cancel),
            pytest.raises(TaskCancelled),
            rt.session_lock(lock, "baostock"),
        ):
            pytest.fail("等待会话时必须可取消")
        assert lock.locked()
    finally:
        lock.release()
    with (
        thread_cancel_scope(cancel),
        pytest.raises(TaskCancelled),
        rt.session_lock(lock, "baostock"),
    ):
        pass
    assert not lock.locked()


def test_st_fallback_binds_explicit_cancel_context_before_waiting_for_session(monkeypatch):
    from dataclasses import replace

    from backend.services import ingest

    monkeypatch.setattr(
        rp,
        "request_policy",
        lambda *_: replace(
            rp.RequestPolicy(5, 30, 1, 0),
            wait_timeout=0.01,
        ),
    )
    service = ingest.IngestionService.__new__(ingest.IngestionService)
    source = type("Source", (), {"name": "baostock"})()
    monkeypatch.setattr(service, "_source_for", lambda *_: source)

    class Context:
        def check_cancel(self):
            raise TaskCancelled()

        def log(self, *args):
            pass

        def flush(self):
            pass

    ingest._BAO_FALLBACK_LOCK.acquire()
    try:
        with pytest.raises(TaskCancelled):
            service._fetch_st_status_rows("600000.SH", None, None, ctx=Context())
    finally:
        ingest._BAO_FALLBACK_LOCK.release()


def test_baostock_repeated_queries_do_not_reload_full_configuration(monkeypatch):
    from backend.config import request_snapshot as cache
    from backend.datasource import baostock_source as bao
    from backend.storage.app_config import AppConfigRepo

    reads = []
    monkeypatch.setattr(cache, "_settings", None)
    monkeypatch.setattr(cache, "_checked", 0)
    monkeypatch.setattr(cache, "_loaded", 0)
    monkeypatch.setattr(cache, "_notification", None)
    monkeypatch.setattr(cache, "_status", {"version": "", "degraded": False})
    monkeypatch.setattr(cache, "_redis", lambda: type("Version", (), {"get": lambda *_: "v1"})())
    monkeypatch.setattr(AppConfigRepo, "get_overrides", lambda *_: reads.append(1) or {})
    source = bao.BaostockSource()
    monkeypatch.setattr(source, "_ensure_login", lambda: None)

    @contextmanager
    def guard(*args, **kwargs):
        yield

    monkeypatch.setattr(source, "_hang_guard", guard)
    monkeypatch.setattr(rt, "request_slot", guard)
    monkeypatch.setattr(bao, "_collect", lambda value: value)
    for _ in range(3):
        assert source._query_frame(lambda: pd.DataFrame({"value": [1]})).iloc[0, 0] == 1
    assert len(reads) == 1


def test_cold_parallel_http_install_keeps_one_transport_layer():
    import subprocess
    import sys

    script = """
from concurrent.futures import ThreadPoolExecutor
import threading
import requests
from backend.datasource import request_policy as rp
original = requests.adapters.HTTPAdapter.send
barrier = threading.Barrier(8)
def install(_):
    barrier.wait()
    rp.install_http_policy()
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(install, range(8)))
assert rp._HTTP_SEND is original
assert requests.adapters.HTTPAdapter.send is not original
assert requests.sessions.Session._ai_stocks_timeout_patched
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=15)


def test_ready_batch_committed_before_checkpoints_and_bounded_to_window():
    committed, completed, sizes = [], [], []

    def flush(entries):
        sizes.append(len(entries))
        committed.extend(item for _, item, _, _, _ in entries)
        return entries

    def complete(index, item, value, error, pending):
        assert item in committed
        completed.append(item)

    run_bounded_parallel(
        list(range(64)),
        lambda item: item,
        concurrency=4,
        ctx=None,
        wait_label="规模回归",
        on_complete=complete,
        transform_batch=flush,
        batch_size=4,
    )
    assert sorted(completed) == list(range(64))
    assert max(sizes) <= 4 and sum(sizes) == 64


def test_batch_commit_error_cannot_advance_checkpoint():
    completed = []

    def flush(entries):
        raise RuntimeError("模拟事务失败")

    with pytest.raises(RuntimeError, match="事务失败"):
        run_bounded_parallel(
            list(range(10)),
            lambda item: item,
            concurrency=3,
            ctx=None,
            wait_label="回滚",
            on_complete=lambda *entry: completed.append(entry),
            transform_batch=flush,
            batch_size=3,
        )
    assert completed == []


def test_operation_material_reuse_validates_stock_and_does_not_cross_scopes(monkeypatch):
    import requests

    from backend.datasource.akshare_source import AKShareSource  # noqa: F401

    monkeypatch.setattr(rp, "get_effective_settings", Settings)
    calls = []

    @contextmanager
    def slot(*args, **kwargs):
        yield {}

    monkeypatch.setattr(rt, "request_slot", slot)

    def send(adapter, request, **kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = b'var KLC_K2_sh600000="payload";'
        response._content_consumed = True
        return response

    monkeypatch.setattr(rp, "_HTTP_SEND", send)
    url = "https://finance.sina.com.cn/realstock/company/sh600000/hisdata_klc2/klc_kl.js"
    with rp.daily_materials("sh600000"):
        requests.get(url)
        requests.get(url)
    assert len(calls) == 1
    with rp.daily_materials("sh600000"):
        requests.get(url)
    assert len(calls) == 2
    with pytest.raises(ValueError, match="标的不匹配"), rp.daily_materials("sh600001"):
        requests.get(url)


def test_request_tracker_uses_current_states_and_phase_scoped_eta():
    tracker = RequestTracker()
    with observe_work(tracker):
        assert tracker.snapshot()["states"] == {"processing": 1}
    assert tracker.snapshot()["states"] == {}
    assert (
        tracker.snapshot({"phase": "new", "phase_done": 30, "phase_total": 100})["eta_seconds"]
        is None
    )


def test_eta_requires_known_total_and_new_completions_after_resume(monkeypatch):
    from backend.datasource import observability

    clock = [100.0]
    monkeypatch.setattr(observability.time, "monotonic", lambda: clock[0])
    tracker = RequestTracker()
    assert tracker.snapshot({"phase_done": 300})["eta_seconds"] is None
    clock[0] += 10
    assert tracker.snapshot({"phase_done": 330})["eta_seconds"] is None
    assert tracker.snapshot({"phase_done": 330, "phase_total": 500})["eta_seconds"] == 57
    assert tracker.snapshot({"phase_done": 330, "phase_total": 300})["eta_seconds"] is None


def test_physical_retry_exhaustion_cannot_be_multiplied_by_sdk_wrapper(monkeypatch):
    import requests

    from backend.common.exceptions import SourceRequestError
    from backend.datasource.akshare_source import AKShareSource  # noqa: F401
    from backend.datasource.base import with_retry

    settings = Settings()
    settings.datasource.sources["sina"] = SourceRequestOverrides(max_retries=2, retry_backoff_sec=0)
    monkeypatch.setattr(rp, "get_effective_settings", lambda: settings)

    @contextmanager
    def slot(*args, **kwargs):
        yield {}

    monkeypatch.setattr(rt, "request_slot", slot)
    calls = []

    def send(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout("source timeout")

    monkeypatch.setattr(rp, "_HTTP_SEND", send)

    class Source:
        name = "akshare"

        @with_retry(max_retries=3, backoff_sec=0)
        def fetch(self):
            return requests.get("https://finance.sina.com.cn/test")

    with pytest.raises(SourceRequestError, match="尝试 2 次"):
        Source().fetch()
    assert len(calls) == 2


def test_config_batch_failure_rolls_back_before_version_notification(monkeypatch):
    from backend.storage.app_config import AppConfigRepo

    notifications = []

    class Store:
        def __init__(self):
            self.values = {}

        @contextmanager
        def transaction(self):
            previous = dict(self.values)
            try:
                yield self
            except Exception:
                self.values = previous
                raise

        @contextmanager
        def cursor(self):
            yield self

        def execute(self, sql, params):
            if len(self.values):
                raise RuntimeError("数据库第二项写失败")
            self.values[params[0]] = params[1]

    store = Store()
    repo = AppConfigRepo(store)
    monkeypatch.setattr(repo, "_invalidate_requests", lambda _: notifications.append(1))
    with pytest.raises(RuntimeError, match="第二项"):
        repo.set_many({"datasource.network_concurrency": 3, "datasource.rate_limit_per_sec": 5})
    assert store.values == {} and notifications == []


def test_semantic_and_http_failures_share_one_attempt_budget(monkeypatch):
    import requests

    from backend.common.exceptions import SourceRequestError
    from backend.datasource.akshare_source import AKShareSource  # noqa: F401
    from backend.datasource.base import with_retry

    settings = Settings()
    settings.datasource.retry_backoff_sec = 0
    monkeypatch.setattr(rp, "get_effective_settings", lambda: settings)

    @contextmanager
    def slot(*args, **kwargs):
        yield {}

    monkeypatch.setattr(rt, "request_slot", slot)
    calls = []

    def send(*args, **kwargs):
        calls.append(1)
        response = requests.Response()
        response.status_code = 200 if len(calls) == 1 else 503
        response._content = b"{}"
        response._content_consumed = True
        return response

    monkeypatch.setattr(rp, "_HTTP_SEND", send)

    class Source:
        name = "akshare"

        @with_retry()
        def fetch(self):
            requests.get("https://finance.sina.com.cn/test")
            raise ValueError("响应语义错误")

    with pytest.raises(SourceRequestError, match="预算已耗尽"):
        Source().fetch()
    assert len(calls) == 3


def test_configuration_snapshot_caches_invalidates_and_preserves_known_good(monkeypatch):
    from backend.config import request_snapshot as cache
    from backend.storage.app_config import AppConfigRepo

    clock, writes = [100.0], []

    class Notifications:
        version = "one"

        def get(self, key):
            return self.version

        def set(self, key, value):
            self.version = value

    notifications = Notifications()
    monkeypatch.setattr(cache, "_settings", None)
    monkeypatch.setattr(cache, "_checked", 0.0)
    monkeypatch.setattr(cache, "_loaded", 0.0)
    monkeypatch.setattr(cache, "_notification", None)
    monkeypatch.setattr(cache, "_status", {"version": "", "degraded": False})
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cache, "_redis", lambda: notifications)

    def overrides(self):
        writes.append(1)
        return {"datasource.rate_limit_per_sec": 7}

    monkeypatch.setattr(AppConfigRepo, "get_overrides", overrides)
    before = cache.get_request_settings()
    for _ in range(100):
        assert cache.get_request_settings() is before
    assert len(writes) == 1
    cache.invalidate_request_settings()
    cache.get_request_settings()
    assert len(writes) == 2

    def failed(self):
        raise RuntimeError("PG unavailable")

    monkeypatch.setattr(AppConfigRepo, "get_overrides", failed)
    clock[0] += 6
    assert cache.get_request_settings().datasource.rate_limit_per_sec == 7
    assert cache.request_settings_status()["degraded"] is True
    monkeypatch.setattr(cache, "_settings", None)
    clock[0] += 6
    with pytest.raises(Exception, match="停止外部请求"):
        cache.get_request_settings()


def test_latest_valuation_real_service_batches_128_stocks_with_ten_year_market(monkeypatch):
    """307200行行情经真实服务加载、取源、合并、质检；取源用确定性源隔离外部抖动。"""
    import threading
    from datetime import date

    from backend.services import ingest
    from backend.services.share_capital import ShareCapitalService
    from backend.storage.ddl import init_db
    from backend.storage.duckdb_client import DuckDBClient

    main_thread = threading.get_ident()
    codes = [f"{900000 + i}.SZ" for i in range(128)]
    end = date(2026, 10, 23)
    days = pd.bdate_range(end=end, periods=2400).date

    class Source:
        name = "akshare"
        capabilities = frozenset({"valuation"})

        def supports(self, name):
            return name in self.capabilities

        def get_valuation(self, code, start, finish):
            assert threading.get_ident() != main_thread
            return pd.DataFrame(
                [
                    {
                        "code": code,
                        "trade_date": end,
                        "total_share": 100,
                        "float_share": 80,
                        "total_mv": 1000,
                        "float_mv": 800,
                    }
                ]
            )

    settings = Settings()
    settings.datasource.update_concurrency = 8
    sizes = []
    merge = ShareCapitalService.merge

    def checked_merge(self, frame, source, **kwargs):
        assert threading.get_ident() == main_thread
        sizes.append(len(frame))
        return merge(self, frame, source, **kwargs)

    monkeypatch.setattr(ShareCapitalService, "merge", checked_merge)
    monkeypatch.setattr(ingest, "get_effective_settings", lambda: settings)
    with DuckDBClient(":memory:") as market:
        init_db(market)
        with market.temp_view(pd.DataFrame({"code": codes}), "test_codes") as view:
            market.execute(
                f"INSERT INTO stock_basic(code,list_date) SELECT code,DATE '2010-01-01' FROM {view}"
            )
            with market.temp_view(pd.DataFrame({"trade_date": days}), "test_days") as dates:
                market.execute(
                    f"INSERT INTO daily_bar(code,trade_date,close) SELECT code,trade_date,10 FROM {view} CROSS JOIN {dates}"
                )
        monkeypatch.setattr(ingest, "get_client", lambda: market)
        service = ingest.IngestionService(source=Source())
        monkeypatch.setattr(service, "_thread_source", lambda *_: Source())
        # 收尾扫描另有领域回归；此处保留真实股本质量检查，仅隔离日线/ST未完整的合成夹具。
        from backend.services.collection_quality import CollectionQualityBatch

        monkeypatch.setattr(CollectionQualityBatch, "finish", lambda *args, **kwargs: {})
        result = service.ingest_valuation_latest(end, codes=codes, concurrency=8)
        assert result["ok"] == 128 and result["fail"] == 0
        assert result["total_mv_rows"] == 128
        assert len(sizes) <= 24 and max(sizes) <= 8
        assert (
            market.query_df(
                "SELECT count(*) n FROM daily_metrics WHERE total_mv=1000 AND float_mv=800"
            ).iloc[0, 0]
            == 128
        )


def test_completed_task_keeps_request_statistics_without_exposing_resume_checkpoint(monkeypatch):
    from datetime import UTC, datetime

    from backend.datasource.observability import record
    from backend.services import async_task
    from backend.storage.ddl import init_db
    from backend.storage.duckdb_client import DuckDBClient

    with DuckDBClient(":memory:") as market:
        init_db(market)
        service = async_task.AsyncTaskService(market)
        monkeypatch.setattr(service, "_audit_task", lambda **kwargs: None)
        monkeypatch.setattr(
            "backend.scheduler.scheduler.enqueue_terminal_events", lambda *args, **kwargs: None
        )

        def handler(params, ctx):
            record(requests=3, network_seconds=1.25, wait_seconds=0.5)
            ctx.set_phase("daily_bar", phase_done=1, phase_total=1)
            return {"ok": True, "message": "完成"}

        monkeypatch.setitem(async_task._HANDLERS, "stock_ingest", handler)
        now = datetime.now(UTC).replace(tzinfo=None)
        market.execute(
            "INSERT INTO async_task(id,task_type,params,status,created_at,updated_at) VALUES ('metrics','stock_ingest','{}','pending',?,?)",
            [now, now],
        )
        service._run("metrics", "stock_ingest", {}, None)
        task = service.get("metrics")
        assert task["status"] == "done"
        assert task["capability"]["request_runtime"]["requests"] == 3
        assert task["capability"]["request_runtime"]["states"] == {}
        assert "checkpoint" not in task["result"]
