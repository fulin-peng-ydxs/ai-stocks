from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.datasource.akshare_source import AKShareSource


@pytest.fixture(autouse=True)
def request_timeout(monkeypatch):
    monkeypatch.setattr(
        "backend.datasource.akshare_source.get_effective_settings",
        lambda: SimpleNamespace(datasource=SimpleNamespace(socket_timeout_sec=7)),
    )


class _Response:
    def __init__(self, payload: list[dict]) -> None:
        self.text = f"=({json.dumps(payload)});"

    @staticmethod
    def raise_for_status() -> None:
        return None


def _source() -> AKShareSource:
    return object.__new__(AKShareSource)


def test_index_symbols_preserve_exchange_and_ths_callback(monkeypatch):
    calls = []

    def get(url, *, params=None, timeout, headers=None):
        calls.append((url, params))
        if '10jqka' in url:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                text='quotebridge_v6_line_hs_1A0001_60_2026('
                     '{"data":"202610081500,3800,3801,3799,3800,10000,100000"});',
            )
        return _Response([])

    monkeypatch.setattr('backend.datasource.akshare_source.requests.get', get)
    _source().get_intraday_1m('000001.SH', 'sina')
    assert calls[-1][1]['symbol'] == 'sh000001'
    _source().get_intraday_1m('000001.SZ', 'sina')
    assert calls[-1][1]['symbol'] == 'sz000001'
    frame = _source().get_intraday_1m('000001.SH', 'ths', request_year=2026)
    assert '/hs_1A0001/60/2026.js' in calls[-1][0]
    assert frame.iloc[0].volume == 100


def test_sina_intraday_uses_unadjusted_one_minute_window_and_normalizes_fields(monkeypatch) -> None:
    calls: list[tuple[str, dict, float]] = []

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return _Response(
            [
                {
                    "day": "2026-09-10 09:31:00",
                    "open": "3.60",
                    "high": "3.62",
                    "low": "3.59",
                    "close": "3.61",
                    "volume": "1000",
                    "amount": "3610",
                }
            ]
        )

    monkeypatch.setattr("backend.datasource.akshare_source.requests.get", fake_get)
    result = _source().get_intraday_1m("002251.SZ", "sina")

    assert calls[0][1] == {
        "symbol": "sz002251",
        "scale": "1",
        "ma": "no",
        "datalen": "1970",
    }
    assert calls[0][2] == 7
    assert result.columns.tolist() == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert result.iloc[0].to_dict() == {
        "timestamp": pd.Timestamp("2026-09-10 09:31:00"),
        "open": 3.6,
        "high": 3.62,
        "low": 3.59,
        "close": 3.61,
        "volume": 10,
        "amount": 3610,
    }


def test_removed_eastmoney_intraday_rejected_before_any_http(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("分时采集不得访问已移除的东财接口")

    monkeypatch.setattr("backend.datasource.akshare_source.requests.get", unexpected)
    with pytest.raises(ValueError, match="未知分钟行情源"):
        _source().get_intraday_1m("002251.SZ", "eastmoney")


def test_direct_adapter_refreshes_system_timeout_without_recreating_source(monkeypatch):
    from backend.config import get_effective_settings

    overrides = {"datasource.socket_timeout_sec": 6}
    monkeypatch.setattr("backend.storage.app_config.AppConfigRepo", lambda: SimpleNamespace(
        get_overrides=lambda: overrides,
    ))
    monkeypatch.setattr("backend.datasource.akshare_source.get_effective_settings",
                        get_effective_settings)
    timeouts = []

    def get(url, *, params, timeout):
        timeouts.append(timeout)
        return _Response([])

    monkeypatch.setattr("backend.datasource.akshare_source.requests.get", get)
    source = _source()
    source.get_intraday_1m("000001.SZ")
    overrides["datasource.socket_timeout_sec"] = 12
    source.get_intraday_1m("000001.SZ")
    assert timeouts == [6, 12]


def test_ths_year_response_validates_identity_and_normalizes_units(monkeypatch):
    from backend.datasource import ths_intraday

    calls = []

    class Response:
        text = ('quotebridge_v6_line_hs_002879_60_2026({"data":'
                '"202610080930,16.78,16.78,16.78,16.78,164501,2760326.78,0.120,,,0;'
                '202610080931,16.70,16.80,16.58,16.68,888100,14841260.00,0.648,,,0"})')

        def raise_for_status(self):
            pass

    def get(url, *, timeout, headers):
        # 与真实失败样本一致：没有这两个请求头时，源端可返回空 404，解析器根本不会运行。
        assert headers == {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://stockpage.10jqka.com.cn/002879/",
        }
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(ths_intraday.requests, "get", get)
    frame = _source().get_intraday_1m("002879.SZ", "ths", request_year=2026, timeout_sec=11)
    assert calls == [("https://d.10jqka.com.cn/v6/line/hs_002879/60/2026.js", 11)]
    assert frame.timestamp.tolist() == list(pd.to_datetime(["2026-10-08 09:30", "2026-10-08 09:31"]))
    assert frame.volume.tolist() == [1645.01, 8881]
    assert frame.amount.tolist() == [2760326.78, 14841260]
    assert frame.iloc[1][["open", "high", "low", "close"]].tolist() == [16.7, 16.8, 16.58, 16.68]
    assert frame.attrs["request_years"] == [2026]
    Response.text = Response.text.replace("hs_002879", "hs_600519")
    with pytest.raises(ValueError, match="标的、周期或年份"):
        _source().get_intraday_1m("002879.SZ", "ths", request_year=2026)
    Response.text = ('quotebridge_v6_line_hs_002879_60_2025({"data":'
                     '"202610080930,16,16,16,16,100,1600"})')
    with pytest.raises(ValueError, match="超出请求年份"):
        _source().get_intraday_1m("002879.SZ", "ths", request_year=2025)
