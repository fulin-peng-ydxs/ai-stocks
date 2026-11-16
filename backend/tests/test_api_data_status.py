"""空行情实例的状态必须返回空日期，不能向壳层传播字符串 NaT。"""

from datetime import date

import pytest
from fastapi import HTTPException

from backend.api import stocks


def test_empty_market_status_keeps_missing_dates_null(market, monkeypatch):
    monkeypatch.setattr(stocks, "get_client", lambda: market)
    result = stocks.data_status().data
    assert result["latest_trade_date"] is None
    assert result["distinct_codes"] == result["bar_rows"] == 0
    assert stocks.trade_dates().data == {"dates": [], "min": None, "max": None, "count": 0}


def test_populated_market_status_keeps_exact_trading_date(market, monkeypatch):
    monkeypatch.setattr(stocks, "get_client", lambda: market)
    market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH','2026-11-13',10)")
    result = stocks.data_status().data
    assert result["latest_trade_date"] == "2026-11-13"
    assert result["distinct_codes"] == result["bar_rows"] == 1


@pytest.mark.parametrize("has_security", [False, True])
def test_empty_market_list_and_charts_do_not_invent_a_trading_date(market, monkeypatch, has_security):
    monkeypatch.setattr(stocks, "get_client", lambda: market)
    if has_security:
        market.execute("INSERT INTO stock_basic(code,name,board) VALUES ('600000.SH','样本','主板')")
    assert stocks.list_stocks(q="600000.SH").data == {
        "total": 0, "page": 1, "size": 50, "trade_date": None, "list": [],
    }
    assert stocks.stock_bars("600000.SH").data == {
        "code": "600000.SH", "name": "样本" if has_security else None, "adjust": "qfq", "bars": [],
    }
    assert stocks.stock_benchmark_bars("000905.SH").data == {
        "index_code": "000905.SH", "name": "中证 500", "end": None, "bars": [],
    }
    assert stocks.stock_signal("600000.SH").data == {
        "code": "600000.SH", "date": None, "buy_point": None, "risk_flags": [], "buypoint_markers": [],
    }


def test_empty_market_keeps_explicit_date_st_guard_and_benchmark_validation(market, monkeypatch):
    from backend.services.stock_st_status import STStatusNotReadyError

    monkeypatch.setattr(stocks, "get_client", lambda: market)
    market.execute("INSERT INTO stock_basic(code,name,board) VALUES ('600000.SH','样本','主板')")
    with pytest.raises(STStatusNotReadyError):
        stocks.list_stocks(trade_date=date(2026, 11, 13))
    with pytest.raises(HTTPException) as failure:
        stocks.stock_benchmark_bars("unsupported")
    assert failure.value.status_code == 400


def test_empty_market_trade_evaluation_keeps_profile_boundary(market, monkeypatch):
    from backend.signals.trade_profile import TradeProfileRepo

    monkeypatch.setattr(stocks, "get_client", lambda: market)
    monkeypatch.setattr(TradeProfileRepo, "get_visible", lambda _self, _profile: None)
    assert stocks.stock_trade_eval("600000.SH", "missing").code == 404
    monkeypatch.setattr(TradeProfileRepo, "get_visible", lambda _self, _profile: {"name": "样本方案"})
    assert stocks.stock_trade_eval("600000.SH", "visible").data == {
        "code": "600000.SH", "date": None, "profile_id": "visible", "name": "样本方案",
        "buy_signal": False, "sell_signal": False,
        "buy": {"op": "AND", "conds": []}, "sell": {"op": "OR", "conds": []}, "backstop": {},
    }
