from __future__ import annotations

import json

import pandas as pd

from backend.datasource.akshare_source import AKShareSource


class _Response:
    def __init__(self, payload: list[dict]) -> None:
        self.text = f"=({json.dumps(payload)});"

    @staticmethod
    def raise_for_status() -> None:
        return None


def _source() -> AKShareSource:
    return object.__new__(AKShareSource)


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
    assert calls[0][2] == 15
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
        "volume": 1000,
        "amount": 3610,
    }


def test_eastmoney_intraday_is_one_minute_unadjusted_fallback(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "时间": "2026-09-10 09:31:00",
                    "开盘": 3.6,
                    "收盘": 3.61,
                    "最高": 3.62,
                    "最低": 3.59,
                    "成交量": 1000,
                    "成交额": 3610,
                    "均价": 3.61,
                }
            ]
        )

    monkeypatch.setattr("backend.datasource.akshare_source.ak.stock_zh_a_hist_min_em", fake_fetch)
    result = _source().get_intraday_1m("002251.SZ", "eastmoney")

    assert calls == [
        {
            "symbol": "002251",
            "start_date": "1979-09-01 00:00:00",
            "end_date": "2222-01-01 23:59:59",
            "period": "1",
            "adjust": "",
        }
    ]
    assert result.iloc[0]["close"] == 3.61
