"""股本补数联网范围收敛，但仍覆盖来源疑点、退市股票及全窗口核验。"""
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services.ingest import IngestionService
from backend.services.share_capital import ShareCapitalService
from backend.storage.repository import MarketRepository

LO, HI = date(2011, 10, 30), date(2026, 10, 30)
DAYS = [date(2012, 1, 4), date(2016, 10, 17), HI]
A, B, C, D = "000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"


@pytest.fixture()
def capital_market(market):
    for code in [A, B, C, D]:
        market.execute("INSERT INTO stock_basic(code,list_date,delist_date) VALUES (?,DATE '1995-01-01',?)",
                       [code, date(2019, 1, 1) if code == B else None])
        for day in DAYS:
            if code == B and day == HI:
                continue
            market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,10)", [code, day])
            market.execute("INSERT INTO stock_share_capital_daily "
                           "(code,trade_date,total_share,float_share,total_source,float_source,"
                           "total_effective_date,float_effective_date) VALUES (?,?,100,80,"
                           "'eastmoney_events','eastmoney_events',DATE '2010-01-01',DATE '2010-01-01')", [code, day])
            market.execute("INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv,reported_total_mv,"
                           "reported_float_mv) VALUES (?,?,1000,800,1000,800)", [code, day])
    return market


def seed_issues(market):
    market.execute("DELETE FROM stock_share_capital_daily WHERE code=? AND trade_date=?", [A, DAYS[0]])
    market.execute("UPDATE daily_metrics SET reported_total_mv=2000 WHERE code=? AND trade_date=?", [B, DAYS[1]])
    market.execute("INSERT INTO stock_share_capital_event(event_id,code,source,effective_date,total_share,"
                   "float_share,active) VALUES ('invalid',?,'eastmoney_events',DATE '2012-01-04',100,-1,TRUE)", [C])


def context():
    ctx = SimpleNamespace(checkpoint={})
    ctx.set_checkpoint = lambda **kw: ctx.checkpoint.update(kw)
    ctx.set_phase = lambda *a, **kw: ctx.checkpoint.update(kw)
    ctx.log = ctx.progress = lambda *a, **kw: None
    ctx.flush = ctx.check_cancel = lambda: None
    return ctx


def service(market, monkeypatch, calls):
    obj = object.__new__(IngestionService)
    obj.c = market
    obj.repo = MarketRepository(market)
    obj.s = SimpleNamespace(datasource=SimpleNamespace(history_years=15, update_concurrency=2))
    source = SimpleNamespace(name="akshare", get_valuation=lambda *a: pd.DataFrame())
    monkeypatch.setattr(obj, "_history_window", lambda *a, **kw: (LO, HI))
    monkeypatch.setattr(obj, "_source_for", lambda *a: source)
    monkeypatch.setattr(obj, "_thread_source", lambda *a: source)

    def collect(code, src, lo, hi, diagnostics):
        calls.append((code, lo, hi))
        assert src.get_valuation(code, lo, hi).empty  # 材料回放不重复联网。
        diagnostics[code] = {"remaining": {}}
        return 1

    monkeypatch.setattr(obj, "_collect_capital_one", collect)
    return obj


def test_issue_ranges_include_delisted_source_conflicts_and_invalid_raw(capital_market):
    seed_issues(capital_market)
    result = ShareCapitalService(capital_market).issue_ranges(LO, HI)
    actual = {r.code: (pd.Timestamp(r.issue_start).date(), pd.Timestamp(r.issue_end).date())
              for r in result.itertuples()}
    assert actual == {A: (DAYS[0], DAYS[0]), B: (DAYS[1], DAYS[1]), C: (DAYS[0], HI)}
    assert D not in actual
    assert ShareCapitalService(capital_market).issue_ranges(LO, HI, codes=[A]).code.tolist() == [A]


def test_gap_collection_freezes_requests_and_checks_whole_history(capital_market, monkeypatch):
    seed_issues(capital_market)
    calls, ctx = [], context()
    obj = service(capital_market, monkeypatch, calls)
    result = IngestionService.ingest_share_capital.__wrapped__(obj, gaps_only=True, ctx=ctx)
    assert sorted(calls) == [(A, DAYS[0], DAYS[0]), (B, DAYS[1], DAYS[1]), (C, DAYS[0], HI)]
    assert result["coverage"]["bar_rows"] == 8  # 不是只核验三个缺口小区间。
    assert result["coverage"]["total_share_rows"] == 7
    assert result["diagnostics"][A]["fetch_end"] == str(DAYS[0])
    assert ctx.checkpoint["share_gap_ranges"][B] == [str(DAYS[1]), str(DAYS[1])]
    # 模拟一个未提交的标的需要续跑；新增别处缺口不能使原冻结范围漂移。
    ctx.checkpoint["share_codes_done"] = [A, C]
    capital_market.execute("DELETE FROM stock_share_capital_daily WHERE code=?", [D])
    calls.clear()
    IngestionService.ingest_share_capital.__wrapped__(obj, gaps_only=True, ctx=ctx)
    assert calls == [(B, DAYS[1], DAYS[1])]
    assert ctx.checkpoint["share_gap_ranges"].keys() == {A, B, C}


def test_default_collection_still_fetches_complete_history(capital_market, monkeypatch):
    calls = []
    obj = service(capital_market, monkeypatch, calls)
    result = IngestionService.ingest_share_capital.__wrapped__(obj, ctx=context())
    assert sorted(calls) == [(code, LO, HI) for code in [A, B, C, D]]
    assert result["coverage"]["bar_rows"] == 11


def test_no_gap_does_not_fetch_or_select_other_codes(capital_market, monkeypatch):
    calls = []
    obj = service(capital_market, monkeypatch, calls)
    result = IngestionService.ingest_share_capital.__wrapped__(obj, gaps_only=True, codes=[A], ctx=context())
    assert calls == []
    assert result["target"] == result["coverage"]["bar_rows"] == 0


def test_gap_checkpoint_outside_frozen_window_fails(capital_market, monkeypatch):
    obj = service(capital_market, monkeypatch, [])
    ctx = context()
    ctx.checkpoint["share_gap_ranges"] = {A: ["2010-01-01", "2012-01-04"]}
    with pytest.raises(ValueError, match="超出已冻结历史窗口"):
        IngestionService.ingest_share_capital.__wrapped__(obj, gaps_only=True, ctx=ctx)


def test_gap_ranges_support_representative_3000_stock_parameters(market):
    market.execute("INSERT INTO daily_bar(code,trade_date,close) SELECT "
                   "lpad(i::VARCHAR,6,'0')||'.SZ',DATE '2012-01-04'+d::INTEGER,10 "
                   "FROM range(3000) t(i) CROSS JOIN range(80) dates(d)")
    codes = [f"{i:06}.SZ" for i in range(3000)]
    result = ShareCapitalService(market).issue_ranges(LO, HI, codes=codes)
    assert len(result) == 3000
    assert result.issue_rows.sum() == 240_000
    assert result.issue_start.eq(pd.Timestamp('2012-01-04')).all()
    assert result.issue_end.eq(pd.Timestamp('2012-03-23')).all()


def test_no_matching_stock_does_not_expand_source_scope(capital_market, monkeypatch):
    obj = service(capital_market, monkeypatch, [])
    monkeypatch.setattr(ShareCapitalService, "issue_ranges", lambda *a, **kw: pytest.fail("空目标不得扩大成全市场"))
    result = IngestionService.ingest_share_capital.__wrapped__(obj, codes=["999999.SZ"], gaps_only=True, ctx=context())
    assert result["target"] == result["coverage"]["bar_rows"] == 0


def test_missing_frozen_stock_stops_instead_of_dropping_target(capital_market, monkeypatch):
    obj = service(capital_market, monkeypatch, [])
    ctx = context()
    ctx.checkpoint["share_gap_ranges"] = {"999999.SZ": ["2012-01-04", "2012-01-04"]}
    with pytest.raises(ValueError, match="停止范围漂移"):
        IngestionService.ingest_share_capital.__wrapped__(obj, gaps_only=True, ctx=ctx)
