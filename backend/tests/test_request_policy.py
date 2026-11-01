"""统一配置、来源分组、HTTP发送与会话互斥的低层回归。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext, contextmanager
import threading
import time

import pandas as pd
import pytest
import requests

from backend.config.settings import Settings
from backend.datasource import request_policy as rp
from backend.tests.test_intraday_quotes import _Redis


@contextmanager
def _gate(calls, group, policy):
    calls.append((group, policy.rate))
    yield {}


def test_policy_inherits_common_and_preserves_legacy_explicit_values():
    settings = Settings()
    settings.ths_board.min_interval_sec = 1
    settings.datasource.socket_timeout_sec = 37
    settings.datasource.max_retries = 4
    assert rp.request_policy("ths_board", settings).timeout == 37
    assert rp.request_policy("ths_board", settings).attempts == 4
    assert rp.request_policy("ths_board", settings).rate == 1
    settings.ths_board.timeout_sec = 11
    assert rp.request_policy("ths_board", settings).timeout == 11
    assert rp.request_policy("ths_board", settings).overrides == ("ths_board.timeout_sec",)
    settings.ths_board.timeout_sec = None
    assert rp.request_policy("ths_board", settings).timeout == 37
    settings.datasource.rate_limit_per_sec = 0.5
    assert rp.request_policy("ths_board", settings).rate == 0.5


def test_board_source_overrides_are_not_reported_as_legacy(monkeypatch):
    """板块来源独立配置与旧超时覆盖分别展示，配置页不再误报会话串行。"""
    from backend.config.settings import SourceRequestOverrides
    from backend.services import data_sources, ths_cookie_status

    settings = Settings()
    settings.datasource.sources["ths_board"] = SourceRequestOverrides(
        network_concurrency=8, rate_limit_per_sec=8,
    )
    monkeypatch.setattr(data_sources, "get_effective_settings", lambda: settings)
    monkeypatch.setattr(ths_cookie_status, "ths_cookie_status", lambda **_: {})

    class Repo:
        def list(self, _):
            return {}

    row = data_sources.source_status(False, repo=Repo(), source="ths_board")["sources"][0]
    assert row["network_concurrency"] == row["work_concurrency"] == 8
    assert row["bar_work_concurrency"] == settings.ths_board.bar_concurrency
    assert row["rate_limit_per_sec"] == 8
    assert row["serial_required"] is False
    assert row["policy_origin"] == "来源单独配置 + 板块频率限制"


@pytest.mark.parametrize(
    "url,group",
    [
        ("https://quotes.sina.cn/api", "sina"),
        ("https://finance.sina.com.cn/", "sina"),
        ("https://datacenter-web.eastmoney.com/api", "eastmoney"),
        ("https://push2his.eastmoney.com/api", "eastmoney"),
        ("https://d.10jqka.com.cn/v6/line/hs_600000/60/2026.js", "ths"),
        ("https://d.10jqka.com.cn/v6/line/bk_886000/01/2026.js", "ths_board"),
        ("https://query.sse.com.cn/commonQuery.do", "sse"),
        ("https://web.ifzq.gtimg.cn/appstock/app/kline/kline", "tencent"),
        ("https://evil-gtimg.cn/", None),
        ("https://www.szse.cn/api/report/ShowReport", "szse"),
        ("https://www.bse.cn/nqxxController/nqxxCnzq.do", "bse"),
        ("https://evil-szse.cn/", None),
        ("https://evil-sina.cn/", None),
    ],
)
def test_rate_group_uses_actual_endpoint(url, group):
    assert rp.source_group(url) == group


def test_http_pages_and_retries_use_shared_gate_and_next_request_settings(monkeypatch):
    from backend.datasource import akshare_source  # noqa: F401 -- 安装现有唯一requests包装

    settings = Settings()
    monkeypatch.setattr(rp, "get_effective_settings", lambda: settings)
    gates, timeouts = [], []
    monkeypatch.setattr(
        "backend.datasource.request_runtime.request_slot",
        lambda group, policy, **_: _gate(gates, group, policy)
    )

    def send(_session, request, **kwargs):
        timeouts.append(kwargs["timeout"])
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response._content_consumed = True
        return response

    monkeypatch.setattr(rp, "_HTTP_SEND", send)
    session = requests.Session()
    for index in range(3):
        settings.datasource.socket_timeout_sec = 10 + index
        session.get("https://datacenter-web.eastmoney.com/api", params={"page": index}, timeout=999)
    assert gates == [("eastmoney", 5)] * 3
    assert timeouts == [10, 11, 12]
    with rp.http_policy_scope("eastmoney", rp.RequestPolicy(2, 19, 1, 0)):
        session.get("https://push2his.eastmoney.com/api")
    assert len(gates) == 4 and gates[-1] == ("eastmoney", 2) and timeouts[-1] == 19  # 每个真实HTTP都准入


@pytest.mark.parametrize("url,group", [
    ("https://www.szse.cn/api/report/ShowReport", "szse"),
    ("https://www.bse.cn/nqxxController/nqxxCnzq.do", "bse"),
])
def test_stock_catalog_endpoints_override_sdk_timeout_and_share_request_gate(monkeypatch, url, group):
    from backend.datasource import akshare_source  # noqa: F401 -- 安装唯一发送拦截

    settings = Settings()
    settings.datasource.socket_timeout_sec = 47
    settings.datasource.rate_limit_per_sec = 0.5
    monkeypatch.setattr(rp, "get_effective_settings", lambda: settings)
    gates, timeouts = [], []
    monkeypatch.setattr(
        "backend.datasource.request_runtime.request_slot",
        lambda group, policy, **_: _gate(gates, group, policy)
    )

    def send(_session, request, **kwargs):
        timeouts.append(kwargs["timeout"])
        response = requests.Response()
        response.status_code = 200
        response._content = b"{}"
        response._content_consumed = True
        return response

    monkeypatch.setattr(rp, "_HTTP_SEND", send)
    # 股票列表 SDK 自带 timeout=15；每个真实请求都必须消费系统配置。
    for timeout in (47, 19):
        settings.datasource.socket_timeout_sec = timeout
        requests.get(url, timeout=15)
    assert timeouts == [47, 19]
    assert gates == [(group, 0.5), (group, 0.5)]


def test_shared_limiter_allows_overlap_but_keeps_aggregate_start_interval():
    cache = _Redis()
    starts, tracker = [], threading.Lock()
    policy = rp.RequestPolicy(50, 1, 1, 0)

    def worker(_):
        rp.wait_for_source("sina", policy, client=cache)
        with tracker:
            starts.append(time.monotonic())
        time.sleep(0.04)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(12)))
    assert len(starts) == 12
    assert all(b - a >= 0.018 for a, b in zip(starts, starts[1:]))
    assert starts[-1] - starts[0] < 0.45  # HTTP等待没有串行叠加


def test_baostock_adapter_serializes_probe_and_collection_even_without_caller_lock(monkeypatch):
    from backend.datasource import baostock_source as bao

    active = maximum = 0
    tracker = threading.Lock()
    monkeypatch.setattr("backend.datasource.request_runtime.request_slot", lambda *_, **__: nullcontext({}))
    monkeypatch.setattr(bao, "get_effective_settings", Settings)
    monkeypatch.setattr(bao, "_collect", lambda frame: frame)

    def query():
        nonlocal active, maximum
        with tracker:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        with tracker:
            active -= 1
        return pd.DataFrame({"ok": [True]})

    sources = [bao.BaostockSource() for _ in range(3)]
    for source in sources:
        monkeypatch.setattr(source, "_ensure_login", lambda: None)
        monkeypatch.setattr(source, "_hang_guard", lambda _: nullcontext())
    with ThreadPoolExecutor(max_workers=3) as pool:
        frames = list(pool.map(lambda source: source._query_frame(query), sources))
    assert maximum == 1 and all(len(frame) == 1 for frame in frames)


def test_source_registry_explains_capabilities_and_uses_real_policy(monkeypatch):
    from backend.services import data_sources, ths_cookie_status

    settings = Settings()
    settings.datasource.update_concurrency = 7
    settings.datasource.rate_limit_per_sec = 2.5
    settings.datasource.max_retries = 4
    settings.datasource.retry_backoff_sec = 1.5
    settings.datasource.socket_timeout_sec = 31
    settings.datasource.baostock_login_timeout_sec = 123
    settings.ths_board.timeout_sec = 12
    monkeypatch.setattr(data_sources, "get_effective_settings", lambda: settings)
    monkeypatch.setattr(ths_cookie_status, "ths_cookie_status", lambda **_: {})

    class Repo:
        def list(self, _):
            return {}

    rows = {row["source"]: row for row in data_sources.source_status(False, repo=Repo())["sources"]}
    assert len(rows) == 7
    assert rows["ths_board"]["timeout_sec"] == 12
    assert rows["intraday_ths"]["timeout_sec"] == 31
    assert rows["baostock"]["login_timeout_sec"] == 123
    assert rows["baostock"]["concurrency"] == 4
    assert rows["baostock"]["serial_required"] is False
    assert rows["ths_board"]["serial_required"] is False
    assert rows["ths_board"]["work_concurrency"] == settings.ths_board.member_concurrency
    assert rows["akshare"]["network_concurrency"] == 6
    assert rows["akshare"]["work_concurrency"] == 7
    assert rows["akshare"]["serial_required"] is False
    assert rows["akshare"]["rate_limit_per_sec"] == 2.5
    assert rows["akshare"]["max_attempts"] == 4
    assert rows["akshare"]["retry_backoff_sec"] == 1.5
    settings.datasource.update_concurrency = 3
    refreshed = {row["source"]: row for row in data_sources.source_status(False, repo=Repo())["sources"]}
    assert refreshed["akshare"]["work_concurrency"] == 3
    assert refreshed["akshare"]["network_concurrency"] == 6
    assert refreshed["baostock"]["concurrency"] == 4
    assert rows["eastmoney_capital"]["rate_group"] == "eastmoney"
    assert "intraday_eastmoney" not in rows
    with pytest.raises(ValueError, match="未知"):
        data_sources.source_status(False, repo=Repo(), source="intraday_eastmoney")
    assert all(row["scope"] and row["probe_scope"] for row in rows.values())
    with pytest.raises(ValueError, match="未知"):
        data_sources.source_status(False, repo=Repo(), source="missing")


def test_nested_retry_does_not_multiply_configured_attempts(monkeypatch):
    from backend.datasource.base import with_retry

    settings = Settings()
    settings.datasource.max_retries = 3
    settings.datasource.retry_backoff_sec = 0
    monkeypatch.setattr(rp, "get_effective_settings", lambda: settings)
    calls = []

    class Source:
        name = "akshare"

        @with_retry()
        def pair(self):
            return self.request()

        @with_retry()
        def request(self):
            calls.append(1)
            raise TimeoutError("offline")

    with pytest.raises(Exception, match="3"):
        Source().pair()
    assert len(calls) == 3


def test_legacy_override_is_nullable_but_common_timeout_is_not():
    from backend.storage.app_config import _coerce, get_field_meta, ConfigValidationError

    assert _coerce(get_field_meta("ths_board.timeout_sec"), None) is None
    with pytest.raises(ConfigValidationError):
        _coerce(get_field_meta("datasource.socket_timeout_sec"), None)


@pytest.mark.parametrize("value", [2.5, float("inf"), float("nan"), True])
def test_integer_config_rejects_fractional_or_nonfinite_values(value):
    from backend.storage.app_config import _coerce, get_field_meta, ConfigValidationError
    with pytest.raises(ConfigValidationError):
        _coerce(get_field_meta("datasource.update_concurrency"), value)
