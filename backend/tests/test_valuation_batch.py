"""单日估值批量取源的完整分页、同口径转换及逐股补漏回归。"""

import os
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.datasource.akshare_source import AKShareSource
from backend.datasource.share_capital import fetch_daily_valuation_day
from backend.services.async_task import TaskCancelled
from backend.tests.test_daily_collection_performance import DAY, Context
from backend.tests.test_daily_collection_performance import service as service  # noqa: PLC0414


def raw(code="600000.SH", day=DAY):
    return {"SECUCODE": code, "数据日期": str(day), "总市值": 1000,
            "流通市值": 800, "总股本": 100, "流通股本": 80, "CLOSE_PRICE": 10}


def page_transport(monkeypatch, pages):
    calls = []

    def get(url, *, params, timeout):
        calls.append(params.copy())
        payload = pages[params["pageNumber"] - 1]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr("backend.datasource.share_capital.requests.get", get)
    return calls


def payload(rows, *, pages=1, count=None):
    names = {"数据日期": "TRADE_DATE", "总市值": "TOTAL_MARKET_CAP",
             "流通市值": "NOTLIMITED_MARKETCAP_A", "总股本": "TOTAL_SHARES",
             "流通股本": "FREE_SHARES_A"}
    rows = [{names.get(key, key): value for key, value in row.items()} for row in rows]
    return {"result": {"pages": pages, "count": len(rows) if count is None else count,
                       "data": rows}}


def test_full_day_pages_are_complete_and_stably_sorted(monkeypatch):
    calls = page_transport(monkeypatch, [
        payload([raw()], pages=2, count=2),
        payload([raw("000001.SZ")], pages=2, count=2),
    ])
    frame = fetch_daily_valuation_day(DAY)
    assert frame.SECUCODE.tolist() == ["600000.SH", "000001.SZ"]
    assert frame["数据日期"].tolist() == [DAY, DAY]
    assert [p["pageNumber"] for p in calls] == [1, 2]
    assert all(p["filter"] == f"(TRADE_DATE='{DAY}')" for p in calls)
    assert all(p["sortColumns"] == "SECURITY_CODE" for p in calls)


@pytest.mark.parametrize("pages", [
    [payload([raw()], pages=2, count=2), payload([], pages=2, count=2)],
    [payload([raw()], pages=2, count=2), payload([raw("000001.SZ")], pages=2, count=3)],
    [payload([raw()], pages=2, count=2), payload([raw()], pages=2, count=2)],
    [payload([raw(day=DAY + timedelta(days=1))])],
    [payload([raw(code=None)])],
    [{"result": {"pages": 1, "data": [raw()]}}],
    [payload([raw()], pages=101, count=2)],
])
def test_incomplete_or_invalid_day_snapshot_is_rejected(monkeypatch, pages):
    page_transport(monkeypatch, pages)
    with pytest.raises(ValueError):
        fetch_daily_valuation_day(DAY)


def test_batch_adapter_matches_single_stock_fields_and_price_evidence(monkeypatch):
    data = pd.DataFrame([raw(), raw("000001.SZ"), raw("920001.BJ")])
    monkeypatch.setattr("backend.datasource.share_capital.fetch_daily_valuation_day", lambda *a, **kw: data)
    monkeypatch.setattr("backend.datasource.share_capital.fetch_daily_valuation", lambda *a, **kw: data.iloc[[0]])
    source = AKShareSource()
    one = source.get_valuation("600000.SH", DAY, DAY)
    many = source.get_valuation_batch(["600000.SH"], DAY)
    pd.testing.assert_frame_equal(one, many)
    assert source._last_valuation_prices == ("600000.SH", {DAY: 10})
    pd.testing.assert_frame_equal(one, source.get_valuation("600000", DAY, DAY))


def seed_latest(service, monkeypatch, *, count=40, missing=(), batch_error=None):
    codes = [f"{600000 + i:06d}.SH" for i in range(count)]
    service.c.executemany("INSERT INTO stock_basic(code,list_date) VALUES (?,DATE '2010-01-01')",
                          [(code,) for code in codes])
    service.c.executemany("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,10)",
                          [(code, DAY) for code in codes])
    calls = {"batch": [], "single": []}

    def frame(selected):
        return pd.DataFrame([{"code": code, "trade_date": DAY, "total_mv": 1000,
                              "float_mv": 800, "total_share": 100, "float_share": 80,
                              "valuation_close": 10} for code in selected])

    class Source:
        name = "akshare"

        @staticmethod
        def supports(capability):
            return capability in ("valuation", "valuation_batch")

        def get_valuation_batch(self, selected, trade_date):
            calls["batch"].append((selected, trade_date))
            if batch_error:
                raise batch_error
            return frame([code for code in selected if code not in missing])

        def get_valuation(self, code, start, end):
            calls["single"].append(code)
            self._last_valuation_prices = (code, {DAY: 10})
            return frame([code])

    service.src = Source()
    monkeypatch.setattr("backend.services.ingest.get_source", lambda _: Source())
    return codes, calls, frame


@pytest.mark.parametrize("concurrency", [1, 4])
def test_latest_batch_keeps_all_target_facts_and_only_refetches_missing(service, monkeypatch, concurrency):
    codes, calls, _ = seed_latest(service, monkeypatch, missing={"600001.SH"})
    ctx = Context()
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=concurrency, ctx=ctx)
    assert result["ok"] == result["total_mv_rows"] == len(codes)
    assert result["fail"] == 0
    assert len(calls["batch"]) == 1 and calls["single"] == ["600001.SH"]
    assert set(ctx.checkpoint["valuation_latest_done_codes"]) == set(codes)
    metrics = service.c.query_df("SELECT * FROM daily_metrics")
    assert len(metrics) == len(codes)
    assert metrics.total_mv.eq(1000).all() and metrics.float_mv.eq(800).all()
    assert metrics.reported_total_mv.eq(1000).all() and metrics.reported_float_mv.eq(800).all()
    assert metrics.reported_total_close.eq(10).all()
    assert set(service.c.query_df("SELECT trade_date FROM stock_share_capital_daily").trade_date.dt.date) == {DAY}


def test_batch_failure_falls_back_without_losing_targets(service, monkeypatch):
    codes, calls, _ = seed_latest(service, monkeypatch, batch_error=ValueError("分页不完整"))
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=Context())
    assert result["ok"] == len(codes) and result["fail"] == 0
    assert sorted(calls["single"]) == codes


@pytest.mark.parametrize("invalid", ["empty", "duplicate", "date", "code"])
def test_invalid_batch_uses_single_stock_fallback_and_cannot_write_wrong_keys(service, monkeypatch, invalid):
    codes, calls, frame = seed_latest(service, monkeypatch)
    snapshot = frame(codes)
    if invalid == "empty":
        snapshot = pd.DataFrame()
    elif invalid == "duplicate":
        snapshot = pd.concat([snapshot, snapshot.iloc[[0]]])
    elif invalid == "date":
        snapshot.loc[0, "trade_date"] = DAY + timedelta(days=1)
    else:
        snapshot.loc[0, "code"] = "000001.SZ"
    monkeypatch.setattr(service.src, "get_valuation_batch", lambda *_: snapshot)
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=Context())
    assert result["ok"] == len(codes) and result["fail"] == 0
    assert sorted(calls["single"]) == codes
    keys = service.c.query_df("SELECT code,trade_date FROM daily_metrics")
    assert sorted(keys.code) == codes and set(keys.trade_date.dt.date) == {DAY}


def test_small_scope_keeps_single_stock_transport(service, monkeypatch):
    codes, calls, _ = seed_latest(service, monkeypatch, count=3)
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=Context())
    assert result["ok"] == 3 and not calls["batch"]
    assert sorted(calls["single"]) == codes


def test_cancelled_batch_does_not_write_or_start_single_fallback(service, monkeypatch):
    codes, calls, _ = seed_latest(service, monkeypatch, batch_error=TaskCancelled())
    ctx = Context()
    with pytest.raises(TaskCancelled):
        service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=ctx)
    assert not calls["single"]
    assert service.c.query_df("SELECT count(*) FROM daily_metrics").iloc[0, 0] == 0
    assert ctx.checkpoint["valuation_latest_done_codes"] == []


def test_source_conflict_still_uses_existing_multisource_review(service, monkeypatch):
    codes, calls, frame = seed_latest(service, monkeypatch)
    frames = frame(codes)
    frames.loc[frames.code.eq(codes[0]), "total_mv"] = 1200
    monkeypatch.setattr(service.src, "get_valuation_batch", lambda *_: frames)
    reviewed = []

    def review(code, source, start, end):
        reviewed.append(code)
        # 复用批量已取得的接口证据，不能以计算值一致冒充来源冲突已核实。
        assert source.get_valuation(code, start, end).total_mv.iloc[0] == 1200
        return 1

    monkeypatch.setattr(service, "_collect_capital_one", review)
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=4, ctx=Context())
    assert result["ok"] == len(codes) and reviewed == [codes[0]]
    assert calls["single"] == []
    row = service.c.query_df("SELECT total_mv,reported_total_mv FROM daily_metrics WHERE code=?", [codes[0]]).iloc[0]
    assert row.total_mv == 1000 and row.reported_total_mv == 1200


@pytest.mark.skipif(not os.getenv("STOCK_INGEST_SCALE_STOCKS"), reason="显式多股补采规模门禁")
def test_latest_batch_scale_keeps_every_target_and_reported_evidence(service, monkeypatch):
    count = int(os.environ["STOCK_INGEST_SCALE_STOCKS"])
    codes, calls, _ = seed_latest(service, monkeypatch, count=count, missing={"600001.SH"})
    ctx = Context()
    result = service.ingest_valuation_latest(DAY, codes=codes, concurrency=6, ctx=ctx)
    assert result["ok"] == result["total_mv_rows"] == count and result["fail"] == 0
    assert len(calls["batch"]) == 1 and calls["single"] == ["600001.SH"]
    assert set(ctx.checkpoint["valuation_latest_done_codes"]) == set(codes)
    assert service.c.query_df(
        "SELECT count(*) FROM daily_metrics WHERE total_mv=1000 AND float_mv=800 "
        "AND reported_total_mv=1000 AND reported_float_mv=800 AND reported_total_close=10"
    ).iloc[0, 0] == count
