"""空行情实例的状态必须返回空日期，不能向壳层传播字符串 NaT。"""

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
