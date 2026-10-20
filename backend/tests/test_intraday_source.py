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


def _service(cache=None, factory=None):
    service = IntradaySourceService(
        redis_client=cache if cache is not None else _Redis(),
        source_factory=factory or (lambda: _Source([])),
    )
    service.config = SimpleNamespace(
        negative_ttl_sec=60,
        source_min_interval_sec=0.01,
        request_timeout_sec=0.2,
        lock_wait_sec=1.0,
    )
    return service


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
        def get_intraday_1m(self, code, provider):
            calls.append(provider)
            return _frame(date(2026, 9, 9) if provider == "sina" else date(2026, 9, 10))

    result = _service(factory=Source).fetch_window("002251.SZ", [DAY])
    assert result["source"] == "eastmoney" and len(result["rows"]) == 240
    assert calls == ["sina", "eastmoney"]


def test_partial_primary_does_not_prevent_complete_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider):
            calls.append(provider)
            return _frame(rows=3 if provider == "sina" else 240)

    result = _service(factory=Source).fetch_window("002251.SZ", [DAY])
    assert result["source"] == "eastmoney"
    assert len(result["candidates"]) == 2
    assert calls == ["sina", "eastmoney"]


def test_primary_missing_1458_and_1459_stays_partial_and_uses_fallback():
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider):
            calls.append(provider)
            frame = _frame()
            if provider == "sina":
                return frame[~frame.timestamp.dt.strftime("%H:%M").isin(["14:58", "14:59"])]
            return frame

    result = _service(factory=Source).fetch_window("600000.SH", [DAY])
    primary = result["candidates"][0]
    assert len(primary["rows"]) == 238
    assert not IntradaySourceService._targets_complete({"sina": primary}, [DAY])
    assert result["source"] == "eastmoney" and calls == ["sina", "eastmoney"]


def test_different_target_days_keep_independent_source_candidates():
    class Source:
        def get_intraday_1m(self, code, provider):
            return _frame(date(2026, 9, 9) if provider == "sina" else date(2026, 9, 10))

    result = _service(factory=Source).fetch_window("002251.SZ", ["2026-09-09", DAY])
    assert len(result["candidates"]) == 2
    assert all(len(item["rows"]) == 240 for item in result["candidates"])


def test_failed_sources_use_negative_protection_without_caching_market_data():
    calls, cache = [], _Redis()

    class Source:
        def get_intraday_1m(self, code, provider):
            calls.append(provider)
            raise TimeoutError(provider)

    service = _service(cache, Source)
    for _ in range(2):
        with pytest.raises(IntradayServiceUnavailable):
            service.fetch_window("002251.SZ", [DAY])
    assert calls == ["sina", "sina", "eastmoney", "eastmoney"]
    assert cache.set_ttls[service._negative_key("002251.SZ")] == 60
    assert not any(":window:" in k for k in cache.values)


def test_empty_source_responses_do_not_create_market_cache():
    calls, cache = [], _Redis()
    result = _service(cache, lambda: _Source(calls, pd.DataFrame())).fetch_window(
        "002251.SZ", [DAY]
    )
    assert result["rows"] == [] and calls == ["sina", "eastmoney"]
    assert not any(":window:" in k for k in cache.values)


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
        def get_intraday_1m(self, code, provider):
            nonlocal active, maximum
            with tracker:
                active += 1
                maximum = max(maximum, active)
                starts.append(time.monotonic())
            time.sleep(0.03)
            with tracker:
                active -= 1
            return _frame()

    service = _service(cache, Source)
    service.config.source_min_interval_sec = 0.02
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda code: service.fetch_window(code, [DAY]), ["002251.SZ", "600000.SH"]))
    assert maximum == 1 and len(starts) == 2
    assert starts[1] - starts[0] >= 0.019


def test_global_source_lock_covers_long_configured_pacing_wait():
    cache = _Redis()
    service = _service(cache)
    service.config.source_min_interval_sec = 60
    service._acquire_global_source_lock()
    assert cache.set_ttls[service._global_lock_key()] >= (
        service.config.source_min_interval_sec + service.config.request_timeout_sec + 10
    )


class _CircuitSource:
    def __init__(self):
        self.calls = []
        self.fail = True

    def get_intraday_1m(self, code, provider):
        self.calls.append((code, provider))
        if provider == "eastmoney" and self.fail:
            raise ConnectionError("unavailable")
        return _frame(rows=238 if provider == "sina" else 240)


def _expire_circuit(cache):
    key = IntradaySourceService._eastmoney_state_key()
    state = json.loads(cache.get(key))
    state["open_until"] = time.time() - 1
    cache.set(key, json.dumps(state), ex=60)


def test_eastmoney_circuit_is_shared_and_retains_primary_candidates():
    cache, source = _Redis(), _CircuitSource()
    for i in range(3):
        result = _service(cache, lambda: source).fetch_window(f"00000{i}.SZ", [DAY])
        assert len(result["rows"]) == 238 and result["errors"]
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 6
    # 新建服务/另一只股票也遵守共享熔断，不发出备用源请求。
    result = _service(cache, lambda: source).fetch_window("600000.SH", [DAY])
    assert result["errors"] == ["eastmoney:暂时熔断，稍后重试"]
    assert result["source"] == "sina" and len(result["rows"]) == 238
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 6
    assert cache.get(IntradaySourceService._global_lock_key()) is None


def test_eastmoney_half_open_single_failure_reopens_then_success_recovers():
    cache, source = _Redis(), _CircuitSource()
    service = _service(cache, lambda: source)
    for i in range(3):
        service.fetch_window(f"00000{i}.SZ", [DAY])
    _expire_circuit(cache)
    service.fetch_window("000010.SZ", [DAY])
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 7
    service.fetch_window("000011.SZ", [DAY])
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 7
    _expire_circuit(cache)
    source.fail = False
    assert service.fetch_window("000012.SZ", [DAY])["source"] == "eastmoney"
    assert json.loads(cache.get(service._eastmoney_state_key())) == {"failures": 0}
    service.fetch_window("000013.SZ", [DAY])
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 9


def test_success_resets_consecutive_eastmoney_failures():
    cache, source = _Redis(), _CircuitSource()
    service = _service(cache, lambda: source)
    service.fetch_window("000001.SZ", [DAY])
    service.fetch_window("000002.SZ", [DAY])
    source.fail = False
    service.fetch_window("000003.SZ", [DAY])
    source.fail = True
    for code in ("000004.SZ", "000005.SZ"):
        service.fetch_window(code, [DAY])
    state = json.loads(cache.get(service._eastmoney_state_key()))
    assert state == {"failures": 2}


def test_concurrent_recovery_uses_one_probe_on_failure():
    cache, source = _Redis(), _CircuitSource()
    cache.set(IntradaySourceService._eastmoney_state_key(),
              json.dumps({"failures": 3, "open_until": time.time() - 1}), ex=60)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(
            lambda code: _service(cache, lambda: source).fetch_window(code, [DAY]),
            ["000001.SZ", "000002.SZ"],
        ))
    assert len([p for _, p in source.calls if p == "eastmoney"]) == 1


def test_empty_recovery_response_resets_circuit_without_claiming_completeness():
    cache = _Redis()
    cache.set(IntradaySourceService._eastmoney_state_key(),
              json.dumps({"failures": 3, "open_until": time.time() - 1}), ex=60)

    class Source:
        def get_intraday_1m(self, code, provider):
            return _frame(rows=238) if provider == "sina" else pd.DataFrame()

    result = _service(cache, Source).fetch_window("600000.SH", [DAY])
    assert len(result["rows"]) == 238 and result["source"] == "sina"
    assert json.loads(cache.get(IntradaySourceService._eastmoney_state_key())) == {"failures": 0}
    assert not IntradaySourceService._targets_complete({"sina": result}, [DAY])
