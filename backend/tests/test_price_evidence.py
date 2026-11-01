"""价量恢复只使用独立原始价格证据，并保留量额/源因子及失败边界。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError
from backend.datasource.price_evidence import fetch_tencent_prices, repair_baostock_price_conflicts


@pytest.fixture
def material(monkeypatch):
    from backend.datasource import price_evidence as module

    days = pd.to_datetime(["2013-06-20", "2013-06-21", "2013-06-24"]).date
    raw = pd.DataFrame({"date": days, "close": [9.92, 9.92, 9.53],
                        "preclose": [10.44, 9.92, 10.03], "tradestatus": ["1"] * 3})
    frame = pd.DataFrame([{"code": "000018.SZ", "trade_date": days[1],
                           "open": 9.92, "high": 9.92, "low": 9.92, "close": 9.92,
                           "pre_close": 9.92, "reference_close": 9.92,
                           "volume": 507657, "amount": 5100218.0, "adj_factor": 1.5}])
    prices = pd.DataFrame({"date": days, "open": [10.32, 10.04, 9.92],
                           "close": [9.92, 10.03, 9.53], "high": [10.43, 10.37, 10.09],
                           "low": [9.92, 9.80, 9.53], "lots": [4226, 5076, 6014]}).set_index("date")
    monkeypatch.setattr(module, "fetch_tencent_prices", lambda *a, **k: prices)
    calls = []

    def fetch(code, start, end, flag):
        calls.append((code, start, end, flag))
        result = raw.copy()
        if flag == "1":
            result["close"] *= 1.5
        return result

    return frame, raw, prices, fetch, calls


def test_verified_ohlc_uses_next_reference_and_keeps_precise_volume_amount_factor(material):
    frame, _, _, fetch, calls = material
    result = repair_baostock_price_conflicts("000018.SZ", frame, fetch)
    assert result[["open", "high", "low", "close"]].iloc[0].tolist() == [10.04, 10.37, 9.80, 10.03]
    assert result.iloc[0].reference_close == 10.03
    assert result.iloc[0].volume == 507657 and result.iloc[0].amount == 5100218
    assert result.iloc[0].adj_factor == 1.5 and frame.iloc[0].close == 9.92
    assert "original_ohlc=9.92" in result.iloc[0]._price_repair_evidence
    assert [call[-1] for call in calls] == ["3", "1"]


@pytest.mark.parametrize("case", ["volume", "mean", "next_reference", "neighbor", "missing_neighbor", "factor", "factor_switch"])
def test_conflicting_or_missing_evidence_never_changes_source(material, case):
    frame, raw, prices, fetch, _ = material
    if case == "volume":
        prices.iloc[1, prices.columns.get_loc("lots")] = 5000
    elif case == "mean":
        prices.iloc[1, prices.columns.get_loc("high")] = 10.04
    elif case == "next_reference":
        raw.iloc[2, raw.columns.get_loc("preclose")] = 9.92
    elif case == "neighbor":
        prices.iloc[0, prices.columns.get_loc("close")] = 9.80
    elif case == "missing_neighbor":
        raw.drop(index=2, inplace=True)
    elif case == "factor":
        frame["adj_factor"] = 1.6
    else:
        original_fetch = fetch
        def fetch(*args):
            value = original_fetch(*args)
            if args[-1] == "1":
                value.iloc[-1, value.columns.get_loc("close")] *= 1.1
            return value
    with pytest.raises(DataSourceError):
        repair_baostock_price_conflicts("000018.SZ", frame, fetch)
    assert frame.iloc[0].close == 9.92


def test_unchanged_close_only_replaces_ohl_without_claiming_adjacent_verification(material):
    frame, _, _, fetch, calls = material
    frame["close"] = frame["reference_close"] = 10.03
    result = repair_baostock_price_conflicts("000018.SZ", frame, fetch)
    assert not calls
    assert result.iloc[0].adj_factor == 1.5
    assert "adjacent_reference_verified=false" in result.iloc[0]._price_repair_evidence


def test_regular_representative_history_never_fetches_or_copies(material):
    frame = pd.concat([material[0]] * 300_000, ignore_index=True)
    frame["high"] = 10.37
    def forbidden(*a, **k):
        raise AssertionError("正常行情不得新增取源")
    result = repair_baostock_price_conflicts("000018.SZ", frame, forbidden)
    assert result is frame


@pytest.mark.parametrize("case", ["wrong_symbol", "duplicate", "invalid_ohlc", "out_of_range", "nonfinite"])
def test_tencent_parser_rejects_incomplete_or_invalid_evidence(monkeypatch, case):
    rows = [["2013-06-21", "10.04", "10.03", "10.37", "9.8", "5076"]]
    payload = {"code": 0, "data": {"sz000018": {"day": rows}}}
    if case == "wrong_symbol":
        payload["data"] = {"sz000019": {"day": rows}}
    elif case == "duplicate":
        rows *= 2
    elif case == "invalid_ohlc":
        rows[0][3] = "9.00"
    elif case == "out_of_range":
        rows[0][0] = "2013-06-24"
    else:
        rows[0][1] = "nan"
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr("backend.datasource.price_evidence.requests.get", lambda *a, **k: response)
    with pytest.raises(DataSourceError):
        fetch_tencent_prices("000018.SZ", date(2013, 6, 21), date(2013, 6, 21))


@pytest.mark.parametrize('factor_fail', [False, True])
def test_quality_repair_finishes_factors_before_closing_ledger(market, factor_fail):
    from backend.services.async_task import _recover_one

    market.execute("INSERT INTO data_quality_issue(id,code,trade_date,issue_type,severity,status) "
                   "VALUES (1,'000018.SZ','2013-06-21','price_volume_mismatch','high','open')")
    calls = []
    ing = SimpleNamespace(
        ingest_one_daily=lambda *a, **k: calls.append('ingest'),
        _recompute_clean=lambda *a, **k: calls.append('factors') or {'fail': int(factor_fail)},
    )
    rep = SimpleNamespace(recheck_clean=lambda *a, **k: calls.append('check') or True)
    ctx = SimpleNamespace(tid='repair', log=lambda *a, **k: None)
    if factor_fail:
        with pytest.raises(RuntimeError, match='因子收尾失败'):
            _recover_one(market, rep, ing, ctx, 1)
        assert calls == ['ingest', 'factors']
        assert market.query_df('SELECT status FROM data_quality_issue').iloc[0, 0] == 'open'
    else:
        assert _recover_one(market, rep, ing, ctx, 1)[0]
        assert calls == ['ingest', 'factors', 'check']
        assert market.query_df('SELECT status FROM data_quality_issue').iloc[0, 0] == 'resolved'
