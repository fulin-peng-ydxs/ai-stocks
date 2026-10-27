from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services.intraday_quotes import IntradayServiceUnavailable
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_quotes import _frame, _Redis, _Source

DAY = "2026-09-10"


@pytest.fixture(autouse=True)
def request_settings(monkeypatch):
    # 这些编排单测的假 SDK 不发 HTTP；在策略作用域入口模拟一次物理发送。
    # 真正的发送拦截、多请求和跨进程限额另由 request_policy/governance 回归覆盖。
    from backend.datasource import request_policy as rp
    from backend.datasource.base import check_thread_cancel
    original_scope = rp.http_policy_scope
    @contextmanager
    def fake_wire(group, policy, *, client=None):
        rp.wait_for_source(group, policy, client=client, check=check_thread_cancel)
        with original_scope(group, policy, client=client):
            yield
    monkeypatch.setattr(rp, "http_policy_scope", fake_wire)
    settings = SimpleNamespace(
        rate_limit_per_sec=50, socket_timeout_sec=0.2,
        max_retries=2, retry_backoff_sec=0.01,
    )
    monkeypatch.setattr(
        "backend.services.intraday_source.get_effective_settings",
        lambda: SimpleNamespace(datasource=settings),
    )
    # 原有编排回归关闭最新日复查间隔；间隔、到期和人工绕过由专用证据用例覆盖。
    monkeypatch.setattr(
        "backend.services.intraday_evidence.get_request_settings",
        lambda: SimpleNamespace(intraday=SimpleNamespace(source_recheck_interval_sec=0)),
    )
    return settings


def _service(cache=None, factory=None):
    service = IntradaySourceService(
        redis_client=cache if cache is not None else _Redis(),
        source_factory=factory or (lambda: _Source([])),
    )
    service.config = SimpleNamespace(
        lock_wait_sec=1.0,
    )
    return service


def test_provider_consumes_public_request_policy_without_own_parameter_mapping(monkeypatch):
    """公共策略的返回值同时约束限流、超时、尝试次数和退避，不另组一份配置。"""
    from backend.datasource import request_policy as rp

    policy = rp.RequestPolicy(rate=17, timeout=7.5, attempts=3, backoff=0.25)
    policies, gates, timeouts, waits = [], [], [], []

    def resolved(group, settings):
        policies.append(group)
        return policy

    monkeypatch.setattr(rp, "request_policy", resolved)
    monkeypatch.setattr(rp, "wait_for_source", lambda group, value, **kwargs:
                        gates.append((group, value)))

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            timeouts.append(timeout_sec)
            if len(timeouts) < 3:
                raise TimeoutError("测试重试")
            return _frame()

    service = _service(factory=Source)
    service.sleep = waits.append
    frame = service._fetch_provider(Source(), "600000.SH", "ths")
    assert not frame.empty
    assert set(policies) == {"ths"}
    assert gates == [("ths", policy)] * 3
    assert timeouts == [7.5] * 3
    assert waits == [0.25, 0.5]


def test_ths_repairs_primary_partial_without_eastmoney():
    from backend.tests.test_intraday_archive import Context

    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append((provider, request_year))
            frame = _frame(rows=10 if provider == "sina" else 240)
            frame.attrs["request_years"] = [request_year] if request_year else []
            return frame

    q = _service(factory=Source)
    q.ctx = Context()
    result = q.fetch_window("002879.SZ", [DAY], allow_fallback=True)
    assert result["source"] == "ths"
    assert calls == [("sina", None), ("ths", 2026)]
    assert result["rows"] and result["request_years"] == [2026]
    assert result["errors"] == []
    assert not any("东财" in m for m, _ in q.ctx.logs)
    assert any("同花顺返回" in m and "实际范围" in m for m, _ in q.ctx.logs)


def test_ths_multiple_target_days_use_one_request_per_year_and_keep_other_year_on_failure():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            assert provider == "ths"
            calls.append(request_year)
            if request_year == 2025:
                raise ConnectionError("older year unavailable")
            return pd.concat([_frame(date(2026, 9, 9)), _frame()])

    q = _service(factory=Source)
    result = q.fetch_window("002879.SZ", ["2025-12-31", "2026-09-09", DAY],
                            allow_fallback=True, providers=("ths",))
    assert calls == [2025, 2025, 2026]
    assert result["request_years"] == [2026] and len(result["rows"]) == 480
    assert q.last_observations["ths"]["outcome"] == "error"
    assert any("ths/2025" in error for error in result["errors"])


def test_complete_primary_skips_backup_with_explicit_log():
    from backend.tests.test_intraday_archive import Context

    calls = []
    q = _service(factory=lambda: _Source(calls))
    q.ctx = Context()
    q.fetch_window("002251.SZ", [DAY], allow_fallback=True)
    assert calls == ["sina"]
    for name in ("同花顺",):
        assert any(f"{name}：跳过" in m and "全部目标日" in m for m, _ in q.ctx.logs)


def test_ths_year_response_is_normalized_once_per_year(monkeypatch):
    """跨年窗口逐年清洗一次，汇总和候选构建不能再转换全部年度响应。"""
    q = _service()
    converted = []
    original = q._frame_to_window

    def convert(frame, provider):
        converted.append(len(frame))
        return original(frame, provider)

    monkeypatch.setattr(q, "_frame_to_window", convert)
    monkeypatch.setattr(q, "_fetch_provider", lambda source, code, provider, request_year=None:
                        _frame(date(request_year, 9, 10)))
    result = q.fetch_window("600000.SH", ["2025-09-10", DAY],
                            allow_fallback=True, providers=("ths",))
    assert converted == [240, 240]
    assert result["request_years"] == [2025, 2026] and len(result["rows"]) == 480


def test_source_responses_are_not_read_from_or_written_to_redis():
    calls, cache = [], _Redis()
    key = "market:intraday:1m:window:sina:002251.SZ"
    cache.set(key, json.dumps({"v": 3, "rows": [["legacy response"]]}))
    before = cache.get(key)
    service = _service(cache, lambda: _Source(calls))
    for _ in range(2):
        result = service.fetch_window("002251.SZ", [DAY])
        assert result["source"] == "sina" and len(result["rows"]) == 240
    assert calls == ["sina", "sina"]
    assert cache.get(key) == before
    assert not any(":window:" in k for k in cache.set_ttls)


def test_fallback_is_selected_for_target_day_missing_from_primary():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            return _frame(date(2026, 9, 9) if provider == "sina" else date(2026, 9, 10))

    result = _service(factory=Source).fetch_window("002251.SZ", [DAY], allow_fallback=True, providers=("sina", "ths"))
    assert result["source"] == "ths" and len(result["rows"]) == 240
    assert calls == ["sina", "ths"]


def test_partial_primary_does_not_prevent_complete_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            return _frame(rows=3 if provider == "sina" else 240)

    result = _service(factory=Source).fetch_window("002251.SZ", [DAY], allow_fallback=True, providers=("sina", "ths"))
    assert result["source"] == "ths"
    assert len(result["candidates"]) == 2
    assert calls == ["sina", "ths"]


def test_closing_auction_empty_minutes_do_not_trigger_repair_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            frame = _frame()
            if provider == "sina":
                return frame[~frame.timestamp.dt.strftime("%H:%M").isin(["14:58", "14:59"])]
            return frame

    result = _service(factory=Source).fetch_window("600000.SH", [DAY], allow_fallback=True, providers=("sina", "ths"))
    primary = result["candidates"][0]
    assert len(primary["rows"]) == 238
    assert IntradaySourceService._targets_complete({"sina": primary}, [DAY])
    assert result["source"] == "sina" and calls == ["sina"]


def test_different_target_days_keep_independent_source_candidates():
    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            return _frame(date(2026, 9, 9) if provider == "sina" else date(2026, 9, 10))

    result = _service(factory=Source).fetch_window("002251.SZ", ["2026-09-09", DAY], allow_fallback=True, providers=("sina", "ths"))
    assert len(result["candidates"]) == 2
    assert all(len(item["rows"]) == 240 for item in result["candidates"])


def test_failed_sources_are_retried_immediately_without_caching_failures():
    calls, cache = [], _Redis()

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            raise TimeoutError(provider)

    service = _service(cache, Source)
    for _ in range(2):
        with pytest.raises(IntradayServiceUnavailable):
            service.fetch_window("002251.SZ", [DAY], allow_fallback=True, providers=("sina", "ths"))
    assert calls == ["sina", "sina", "ths", "ths"] * 2
    assert not any(":negative:" in k or ":circuit" in k for k in cache.values)
    assert not any(":window:" in k for k in cache.values)


def test_empty_source_responses_do_not_create_market_cache():
    calls, cache = [], _Redis()
    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            return pd.DataFrame()

    result = _service(cache, Source).fetch_window(
        "002251.SZ", [DAY], allow_fallback=True, providers=("sina", "ths")
    )
    assert result["rows"] == [] and calls == ["sina", "ths"]
    assert not any(":window:" in k for k in cache.values)


@pytest.mark.parametrize("response", ["partial", "empty", "failure"])
def test_regular_collection_never_requests_fallback(response):
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            assert provider == "sina"
            if response == "failure":
                raise ConnectionError("offline")
            return _frame(rows=10) if response == "partial" else pd.DataFrame()

    service = _service(factory=Source)
    if response == "failure":
        with pytest.raises(IntradayServiceUnavailable):
            service.fetch_window("600000.SH", [DAY])
        assert calls == ["sina", "sina"]
    else:
        result = service.fetch_window("600000.SH", [DAY])
        assert calls == ["sina"]
        assert not result.get("errors")


def test_primary_failure_does_not_block_repair_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            if provider == "sina":
                raise ConnectionError("primary offline")
            return _frame()

    service = _service(factory=Source)
    with pytest.raises(IntradayServiceUnavailable):
        service.fetch_window("600000.SH", [DAY])
    result = service.fetch_window("600000.SH", [DAY], allow_fallback=True, providers=("sina", "ths"))
    assert result["source"] == "ths"
    assert calls == ["sina", "sina", "sina", "sina", "ths"]


def test_redis_failure_blocks_collector_before_source_access():
    import redis

    calls, cache = [], _Redis()
    cache.fail = True
    with pytest.raises(redis.ConnectionError):
        _service(cache, lambda: _Source(calls)).fetch_window("002251.SZ", [DAY])
    assert calls == []


def test_different_stocks_overlap_without_multiplying_source_rate():
    cache = _Redis()
    active, maximum = 0, 0
    starts = []
    tracker = threading.Lock()

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            nonlocal active, maximum
            with tracker:
                active += 1
                maximum = max(maximum, active)
                starts.append(time.monotonic())
            time.sleep(0.06)
            with tracker:
                active -= 1
            return _frame()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda code: _service(cache, Source).fetch_window(code, [DAY]), ["002251.SZ", "600000.SH"]))
    assert maximum == 2 and len(starts) == 2
    assert starts[1] - starts[0] >= 0.019


def test_long_timeouts_no_longer_hold_source_lock(request_settings):
    cache = _Redis()
    request_settings.socket_timeout_sec = 120
    result = _service(cache).fetch_window("600000.SH", [DAY])
    assert result is not None
    assert not any(":lock:" in key for key in cache.values)


@pytest.mark.parametrize("provider", ["ths"])
def test_backup_failures_do_not_suppress_other_stocks_or_later_repair(provider):
    from backend.tests.test_intraday_archive import Context

    cache, calls = _Redis(), []
    recovered = False

    class Source:
        def get_intraday_1m(self, code, source, *, timeout_sec=None, request_year=None):
            calls.append((code, source))
            if source == provider:
                if not recovered:
                    raise ConnectionError("HTTP 404 unavailable")
                return _frame()
            return _frame(rows=10)

    for i in range(4):
        q = _service(cache, Source)
        q.ctx = Context()
        result = q.fetch_window(f"00000{i}.SZ", [DAY], allow_fallback=True,
                                providers=("sina", provider))
        assert len(result["rows"]) == 10 and result["errors"]
        assert any(DAY in m and "HTTP 404" in m for m, _ in q.ctx.logs)
    assert sum(source == provider for _, source in calls) == 8
    # 无需等待或清理 Redis，另一个任务可以立即修复此前失败的股票。
    recovered = True
    result = _service(cache, Source).fetch_window("000000.SZ", [DAY], allow_fallback=True,
                                                 providers=("sina", provider))
    assert result["source"] == provider and len(result["rows"]) == 240
    assert not any(":lock:" in key for key in cache.values)


@pytest.mark.parametrize("provider", ["sina", "ths"])
@pytest.mark.parametrize("expired", [False, True])
def test_legacy_failure_states_do_not_skip_requests_or_reduce_system_retries(
    provider, expired, request_settings,
):
    cache, calls = _Redis(), []
    code = "600000.SH"
    cache.set(f"market:intraday:1m:source:{provider}:circuit", json.dumps({
        "failures": 3, "open_until": time.time() + (-1 if expired else 60),
    }), ex=120)
    for suffix in ("", ":repair:v3"):
        cache.set(f"market:intraday:1m:negative:{code}{suffix}", "old failure", ex=60)
    request_settings.max_retries = 3

    class Source:
        def get_intraday_1m(self, code, source, *, timeout_sec=None, request_year=None):
            calls.append(source)
            if len(calls) < 3:
                raise TimeoutError("temporary failure")
            return _frame()

    result = _service(cache, Source).fetch_window(
        code, [DAY], allow_fallback=provider != "sina", providers=(provider,),
    )
    assert calls == [provider] * 3 and len(result["rows"]) == 240


def test_empty_backup_does_not_claim_completeness():
    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            return _frame(rows=10) if provider == "sina" else pd.DataFrame()

    result = _service(factory=Source).fetch_window("600000.SH", [DAY], allow_fallback=True,
                                                   providers=("sina", "ths"))
    assert len(result["rows"]) == 10 and result["source"] == "sina"
    assert not IntradaySourceService._targets_complete({"sina": result}, [DAY])


def test_system_overrides_control_real_requests_and_refresh_during_task(monkeypatch):
    from backend.config import get_effective_settings
    from backend.datasource.akshare_source import AKShareSource
    from backend.tests.test_intraday_datasource import _Response

    overrides = {
        "datasource.rate_limit_per_sec": 2,
        "datasource.socket_timeout_sec": 9,
        "datasource.max_retries": 3,
        "datasource.retry_backoff_sec": 0.4,
    }
    # 走系统设置实际合并入口，仅替换持久层读取，不修改开发库 app_config。
    monkeypatch.setattr("backend.storage.app_config.AppConfigRepo", lambda: SimpleNamespace(
        get_overrides=lambda: overrides,
    ))
    monkeypatch.setattr("backend.services.intraday_source.get_effective_settings",
                        get_effective_settings)
    service = _service(factory=lambda: object.__new__(AKShareSource))
    calls, waits, intervals, messages = [], [], [], []
    service.ctx = SimpleNamespace(
        check_cancel=lambda: None, flush=lambda: None,
        log=lambda message, level: messages.append(message),
    )
    monkeypatch.setattr("backend.datasource.request_policy.wait_for_source",
                        lambda group, policy, **_: intervals.append(1 / policy.rate))

    def pause(seconds):
        # 重试等待期间已经释放全局请求锁。
        assert not any(":lock:" in key for key in service.redis.values)
        waits.append(seconds)

    monkeypatch.setattr(service, "_pause", pause)

    def request(url, *, params, timeout):
        calls.append(timeout)
        assert not any(":lock:" in key for key in service.redis.values)
        if params["symbol"] == "sh600000":
            raise TimeoutError("source unavailable")
        return _Response([{
            "day": "2026-09-10 09:31:00", "open": "3.6", "high": "3.62",
            "low": "3.59", "close": "3.61", "volume": "1000", "amount": "3610",
        }])

    monkeypatch.setattr("backend.datasource.akshare_source.requests.get", request)
    with pytest.raises(IntradayServiceUnavailable):
        service.fetch_window("600000.SH", [DAY])
    assert calls == [9, 9, 9] and waits == [0.4, 0.8]
    assert intervals == [0.5, 0.5, 0.5]
    overrides.update({
        "datasource.rate_limit_per_sec": 4,
        "datasource.socket_timeout_sec": 11,
        "datasource.max_retries": 1,
        "datasource.retry_backoff_sec": 0.9,
    })
    assert len(service.fetch_window("000001.SZ", [DAY])["rows"]) == 1
    assert calls[-1] == 11 and intervals[-1] == 0.25
    assert sum("系统请求配置" in message for message in messages) == 2
    assert any("请求 3/3" in message for message in messages)
    assert any("最多尝试 1 次" in message for message in messages)


@pytest.mark.parametrize("phase", ["limit", "backoff"])
def test_system_request_waits_remain_cancellable(phase, request_settings, monkeypatch):
    from backend.services.async_task import TaskCancelled

    cache, calls = _Redis(), []
    cancelled = False

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            raise TimeoutError("unavailable")

    def check_cancel():
        if cancelled:
            raise TaskCancelled()

    def sleep(_seconds):
        nonlocal cancelled
        cancelled = True

    service = _service(cache, Source)
    service.ctx = SimpleNamespace(check_cancel=check_cancel, log=lambda *_: None, flush=lambda: None)
    service.sleep = sleep
    request_settings.retry_backoff_sec = 2
    if phase == "limit":
        request_settings.rate_limit_per_sec = 0.1
        def waiting(*args, **kwargs):
            sleep(0.1)
            kwargs["check"]()
        monkeypatch.setattr("backend.datasource.request_policy.wait_for_source", waiting)
    with pytest.raises(TaskCancelled):
        service.fetch_window("600000.SH", [DAY])
    assert calls == (["sina"] if phase == "backoff" else [])
    assert not any(":negative:" in k for k in cache.values)
    assert not any(":lock:" in key for key in cache.values)


def test_failed_remaining_backup_never_requests_removed_eastmoney():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            if provider == "ths":
                raise ConnectionError("THS unavailable")
            assert provider == "sina"
            return _frame(rows=10)

    result = _service(factory=Source).fetch_window("600000.SH", [DAY], allow_fallback=True)
    assert calls == ["sina", "ths", "ths"]
    assert result["source"] == "sina" and len(result["rows"]) == 10
    assert result["errors"] and "THS unavailable" in result["errors"][0]


@pytest.mark.parametrize("code", ["600000.SH", "000001.SH"])
def test_removed_source_cannot_be_explicitly_selected_or_probed(code):
    calls = []
    service = _service(factory=lambda: _Source(calls))
    with pytest.raises(ValueError):
        service.fetch_window(code, [DAY], allow_fallback=True, providers=("eastmoney",))
    with pytest.raises(ValueError, match="不支持的分时数据源"):
        service._fetch_provider(service.source_factory(), code, "eastmoney")
    assert calls == []
