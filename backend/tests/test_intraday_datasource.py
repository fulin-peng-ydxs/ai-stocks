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
        "volume": 10,
        "amount": 3610,
    }


def test_eastmoney_intraday_is_one_minute_unadjusted_fallback(monkeypatch) -> None:
    calls: list[tuple[str, dict, float]] = []

    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {
                "data": {
                    "trends": ["2026-09-10 09:31,3.60,3.61,3.62,3.59,1000,361000,3.61"]
                }
            }

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return Response()

    monkeypatch.setattr("backend.datasource.akshare_source.requests.get", fake_get)
    result = _source().get_intraday_1m("002251.SZ", "eastmoney")

    assert calls[0][0].endswith("/api/qt/stock/trends2/get")
    assert calls[0][1]["secid"] == "0.002251"
    assert calls[0][1]["ndays"] == "5"
    assert calls[0][2] == 15
    assert result.iloc[0]["close"] == 3.61
    assert result.iloc[0]["volume"] == 1000
    assert result.iloc[0]["amount"] == 361000
