from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    settings = SimpleNamespace(
        rate_limit_per_sec=50, socket_timeout_sec=0.2,
        max_retries=2, retry_backoff_sec=0.01,
    )
    monkeypatch.setattr(
        "backend.services.intraday_source.get_effective_settings",
        lambda: SimpleNamespace(datasource=settings),
    )
    return settings


def _service(cache=None, factory=None):
    service = IntradaySourceService(
        redis_client=cache if cache is not None else _Redis(),
        source_factory=factory or (lambda: _Source([])),
    )
    service.config = SimpleNamespace(
        negative_ttl_sec=60,
        lock_wait_sec=1.0,
    )
    return service


def test_third_source_repairs_when_primary_partial_and_eastmoney_fails():
    from backend.tests.test_intraday_archive import Context

    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append((provider, request_year))
            if provider == "eastmoney":
                raise ConnectionError("unavailable")
            frame = _frame(rows=10 if provider == "sina" else 240)
            frame.attrs["request_years"] = [request_year] if request_year else []
            return frame

    q = _service(factory=Source)
    q.ctx = Context()
    result = q.fetch_window("002879.SZ", [DAY], allow_fallback=True)
    assert result["source"] == "ths"
    assert calls == [("sina", None), ("eastmoney", None), ("eastmoney", None), ("ths", 2026)]
    assert result["rows"] and result["request_years"] == [2026]
    assert "eastmoney:ConnectionError" in result["errors"]
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


def test_complete_primary_skips_both_backups_with_explicit_log():
    from backend.tests.test_intraday_archive import Context

    calls = []
    q = _service(factory=lambda: _Source(calls))
    q.ctx = Context()
    q.fetch_window("002251.SZ", [DAY], allow_fallback=True)
    assert calls == ["sina"]
    for name in ("东财", "同花顺"):
        assert any(f"{name}：跳过" in m and "全部目标日" in m for m, _ in q.ctx.logs)


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
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            return _frame(date(2026, 9, 9) if provider == "sina" else date(2026, 9, 10))

    result = _service(factory=Source).fetch_window("002251.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert result["source"] == "eastmoney" and len(result["rows"]) == 240
    assert calls == ["sina", "eastmoney"]


def test_partial_primary_does_not_prevent_complete_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            return _frame(rows=3 if provider == "sina" else 240)

    result = _service(factory=Source).fetch_window("002251.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert result["source"] == "eastmoney"
    assert len(result["candidates"]) == 2
    assert calls == ["sina", "eastmoney"]


def test_closing_auction_empty_minutes_do_not_trigger_repair_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            frame = _frame()
            if provider == "sina":
                return frame[~frame.timestamp.dt.strftime("%H:%M").isin(["14:58", "14:59"])]
            return frame

    result = _service(factory=Source).fetch_window("600000.SH", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    primary = result["candidates"][0]
    assert len(primary["rows"]) == 238
    assert IntradaySourceService._targets_complete({"sina": primary}, [DAY])
    assert result["source"] == "sina" and calls == ["sina"]


def test_different_target_days_keep_independent_source_candidates():
    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            return _frame(date(2026, 9, 9) if provider == "sina" else date(2026, 9, 10))

    result = _service(factory=Source).fetch_window("002251.SZ", ["2026-09-09", DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert len(result["candidates"]) == 2
    assert all(len(item["rows"]) == 240 for item in result["candidates"])


def test_failed_sources_use_negative_protection_without_caching_market_data():
    calls, cache = [], _Redis()

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            raise TimeoutError(provider)

    service = _service(cache, Source)
    for _ in range(2):
        with pytest.raises(IntradayServiceUnavailable):
            service.fetch_window("002251.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert calls == ["sina", "sina", "eastmoney", "eastmoney"]
    assert cache.set_ttls[service._negative_key("002251.SZ", allow_fallback=True)] == 60
    assert not any(":window:" in k for k in cache.values)


def test_empty_source_responses_do_not_create_market_cache():
    calls, cache = [], _Redis()
    result = _service(cache, lambda: _Source(calls, pd.DataFrame())).fetch_window(
        "002251.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney")
    )
    assert result["rows"] == [] and calls == ["sina", "eastmoney"]
    assert not any(":window:" in k for k in cache.values)


@pytest.mark.parametrize("response", ["partial", "empty", "failure"])
def test_regular_collection_never_requests_fallback(response):
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
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


def test_primary_failure_protection_does_not_block_repair_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            if provider == "sina":
                raise ConnectionError("primary offline")
            return _frame()

    service = _service(factory=Source)
    with pytest.raises(IntradayServiceUnavailable):
        service.fetch_window("600000.SH", [DAY])
    result = service.fetch_window("600000.SH", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert result["source"] == "eastmoney"
    assert calls == ["sina", "sina", "sina", "sina", "eastmoney"]


def test_redis_failure_blocks_collector_before_source_access():
    import redis

    calls, cache = [], _Redis()
    cache.fail = True
    with pytest.raises(redis.ConnectionError):
        _service(cache, lambda: _Source(calls)).fetch_window("002251.SZ", [DAY])
    assert calls == []


def test_different_stocks_share_global_serial_gate_and_interval():
    cache = _Redis()
    active, maximum = 0, 0
    starts = []
    tracker = threading.Lock()

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            nonlocal active, maximum
            with tracker:
                active += 1
                maximum = max(maximum, active)
                starts.append(time.monotonic())
            time.sleep(0.003)
            with tracker:
                active -= 1
            return _frame()

    service = _service(cache, Source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda code: service.fetch_window(code, [DAY]), ["002251.SZ", "600000.SH"]))
    assert maximum == 1 and len(starts) == 2
    assert starts[1] - starts[0] >= 0.019


def test_global_source_lock_covers_long_configured_pacing_wait(request_settings):
    cache = _Redis()
    service = _service(cache)
    request_settings.rate_limit_per_sec = 0.1
    request_settings.socket_timeout_sec = 120
    service._acquire_global_source_lock(request_settings)
    assert cache.set_ttls[service._global_lock_key()] >= (
        1 / request_settings.rate_limit_per_sec + 2 * request_settings.socket_timeout_sec + 10
    )


class _CircuitSource:
    def __init__(self):
        self.calls = []
        self.fail = True

    def get_intraday_1m(self, code, provider, *, timeout_sec=None):
        self.calls.append((code, provider))
        if provider == "eastmoney" and self.fail:
            raise ConnectionError("unavailable")
        return _frame(rows=238 if provider == "sina" else 240)


def _expire_circuit(cache):
    key = IntradaySourceService._backup_state_key()
    state = json.loads(cache.get(key))
    state["open_until"] = time.time() - 1
    cache.set(key, json.dumps(state), ex=60)


def test_eastmoney_circuit_is_shared_and_retains_primary_candidates():
    cache, source = _Redis(), _CircuitSource()
    for i in range(3):
        result = _service(cache, lambda: source).fetch_window(f"00000{i}.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
        assert len(result["rows"]) == 238 and result["errors"]
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 6
    # 新建服务/另一只股票也遵守共享熔断，不发出备用源请求。
    result = _service(cache, lambda: source).fetch_window("600000.SH", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert result["errors"] == ["eastmoney:暂时熔断，稍后重试"]
    assert result["source"] == "sina" and len(result["rows"]) == 238
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 6
    assert cache.get(IntradaySourceService._global_lock_key()) is None


def test_eastmoney_half_open_single_failure_reopens_then_success_recovers():
    cache, source = _Redis(), _CircuitSource()
    service = _service(cache, lambda: source)
    for i in range(3):
        service.fetch_window(f"00000{i}.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    _expire_circuit(cache)
    service.fetch_window("000010.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 7
    service.fetch_window("000011.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 7
    _expire_circuit(cache)
    source.fail = False
    assert service.fetch_window("000012.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))["source"] == "eastmoney"
    assert json.loads(cache.get(service._backup_state_key())) == {"failures": 0}
    service.fetch_window("000013.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 9


def test_success_resets_consecutive_eastmoney_failures():
    cache, source = _Redis(), _CircuitSource()
    service = _service(cache, lambda: source)
    service.fetch_window("000001.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    service.fetch_window("000002.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    source.fail = False
    service.fetch_window("000003.SZ", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    source.fail = True
    for code in ("000004.SZ", "000005.SZ"):
        service.fetch_window(code, [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    state = json.loads(cache.get(service._backup_state_key()))
    assert state == {"failures": 2}


def test_concurrent_recovery_uses_one_probe_on_failure():
    cache, source = _Redis(), _CircuitSource()
    cache.set(IntradaySourceService._backup_state_key(),
              json.dumps({"failures": 3, "open_until": time.time() - 1}), ex=60)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(
            lambda code: _service(cache, lambda: source).fetch_window(code, [DAY], allow_fallback=True, providers=("sina", "eastmoney")),
            ["000001.SZ", "000002.SZ"],
        ))
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 1


def test_empty_recovery_response_resets_circuit_without_claiming_completeness():
    cache = _Redis()
    cache.set(IntradaySourceService._backup_state_key(),
              json.dumps({"failures": 3, "open_until": time.time() - 1}), ex=60)

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            return _frame(rows=238) if provider == "sina" else pd.DataFrame()

    result = _service(cache, Source).fetch_window("600000.SH", [DAY], allow_fallback=True, providers=("sina", "eastmoney"))
    assert len(result["rows"]) == 238 and result["source"] == "sina"
    assert json.loads(cache.get(IntradaySourceService._backup_state_key())) == {"failures": 0}
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
    monkeypatch.setattr(service, "_wait_source_interval", intervals.append)

    def pause(seconds):
        # 重试等待期间已经释放全局请求锁。
        assert service.redis.get(service._global_lock_key()) is None
        waits.append(seconds)

    monkeypatch.setattr(service, "_pause", pause)

    def request(url, *, params, timeout):
        calls.append(timeout)
        ttl = service.redis.set_ttls[service._global_lock_key()]
        assert ttl >= 2 * timeout + 10
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


@pytest.mark.parametrize("phase", ["lock", "limit", "backoff"])
def test_system_request_waits_remain_cancellable(phase, request_settings):
    from backend.services.async_task import TaskCancelled

    cache, calls = _Redis(), []
    cancelled = False

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
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
    if phase == "lock":
        cache.set(service._global_lock_key(), "another worker", ex=60)
    if phase == "limit":
        request_settings.rate_limit_per_sec = 0.1
        cache.set(service._last_start_key(), str(time.time()), ex=60)
    with pytest.raises(TaskCancelled):
        service.fetch_window("600000.SH", [DAY])
    assert calls == (["sina"] if phase == "backoff" else [])
    assert not cache.get(service._negative_key("600000.SH"))
    assert cache.get(service._global_lock_key()) == ("another worker" if phase == "lock" else None)
