"""历史变更记录保存、展示/回测统一与自动采集闭环。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.services.capital_quality import CapitalQualityService
from backend.services.share_capital_history import ShareCapitalHistoryService
from backend.services.stock_quote_summary import StockQuoteSummaryService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market():
    with DuckDBClient(":memory:") as c:
        init_db(c)
        c.execute("INSERT INTO stock_basic(code) VALUES ('000004.SZ')")
        c.execute(
            "INSERT INTO daily_bar(code,trade_date,close) SELECT '000004.SZ',DATE '2016-12-29'+CAST(i AS INTEGER),10 FROM range(9) t(i)"
        )
        yield c


def events(reason="股本统计", day="2016-12-30", **extra):
    return pd.DataFrame(
        [
            dict(
                END_DATE=day,
                NOTICE_DATE="2017-04-11",
                TOTAL_SHARES=100,
                LISTED_A_SHARES=80,
                TOTAL_A_SHARES=100,
                CHANGE_REASON=reason,
                **extra,
            )
        ]
    )


def test_later_disclosure_is_used_by_date_for_display_and_decisions(market):
    service = ShareCapitalHistoryService(market)
    service.record_events("000004.SZ", events(), "eastmoney_events")
    service.rebuild("000004.SZ", apply_events=True)
    quote = StockQuoteSummaryService(market)
    days = [date(2016, 12, 29), date(2016, 12, 30), date(2017, 1, 2)]
    for basis in ["historical", "point_in_time"]:
        values = quote.get_market_values("000004.SZ", days, basis=basis)
        assert values["2016-12-29"]["float_share"] is None
        assert values["2016-12-30"]["float_share"] == 80
        assert values["2017-01-02"]["float_share"] == 80
        assert values["2017-01-02"]["float_mv"] == 800
    assert market.query_df("SELECT count(*) FROM stock_share_capital_history").iloc[0, 0] == 0
    assert (
        CapitalQualityService(market)
        .aggregate()
        .query("issue_type=='capital_gap'")
        .issue_days.iloc[0]
        == 1
    )


def test_weekend_change_starts_next_trading_day_not_previous_day(market):
    market.execute("DELETE FROM daily_bar WHERE trade_date IN ('2016-12-31','2017-01-01')")
    raw = events(day="2016-12-31")
    service = ShareCapitalHistoryService(market)
    service.record_events("000004.SZ", raw, "eastmoney_events")
    service.rebuild("000004.SZ", apply_events=True)
    values = StockQuoteSummaryService(market).get_market_values(
        "000004.SZ", [date(2016, 12, 30), date(2017, 1, 2)]
    )
    assert values["2016-12-30"]["float_share"] is None
    assert values["2017-01-02"]["float_share"] == 80


def test_revisions_keep_archive_and_rebuild_is_idempotent(market):
    service = ShareCapitalHistoryService(market)
    raw = events()
    service.record_events("000004.SZ", raw, "eastmoney_events")
    service.rebuild("000004.SZ", apply_events=True)
    before = market.query_df("SELECT count(*) FROM data_update_log").iloc[0, 0]
    service.record_events("000004.SZ", raw, "eastmoney_events")
    service.rebuild("000004.SZ", apply_events=True)
    assert market.query_df("SELECT count(*) FROM data_update_log").iloc[0, 0] == before
    raw["LISTED_A_SHARES"] = 90
    service.record_events("000004.SZ", raw, "eastmoney_events")
    service.rebuild("000004.SZ", apply_events=True)
    assert market.query_df(
        "SELECT active FROM stock_share_capital_event ORDER BY float_share"
    ).active.tolist() == [False, True]
    assert (
        market.query_df("SELECT DISTINCT float_share FROM stock_share_capital_daily").iloc[0, 0]
        == 90
    )
    assert market.query_df("SELECT DISTINCT float_mv FROM daily_metrics").iloc[0, 0] == 900


def test_raw_zero_float_is_valid_but_negative_is_reported(market):
    service = ShareCapitalHistoryService(market)
    raw = events(day="1993-12-13")
    raw["LISTED_A_SHARES"] = 0
    service.record_events("000004.SZ", raw, "eastmoney_events")
    quality = CapitalQualityService(market)
    assert quality.sync(["000004.SZ"])["capital_raw_invalid"] == 0
    raw["LISTED_A_SHARES"] = -50
    service.record_events("000004.SZ", raw, "eastmoney_events")
    assert quality.sync(["000004.SZ"])["capital_raw_invalid"] == 0
    assert quality.aggregate(["000004.SZ"], source_only=True).issue_type.tolist() == ["capital_raw_invalid"]
    service.rebuild("000004.SZ", apply_events=True)
    assert (
        market.query_df("SELECT count(float_share) FROM stock_share_capital_daily").iloc[0, 0] == 0
    )
    raw["LISTED_A_SHARES"] = 0
    service.record_events("000004.SZ", raw, "eastmoney_events")
    quality.sync(["000004.SZ"])
    assert quality.clean("capital_raw_invalid", "000004.SZ")


def test_collector_preserves_raw_even_if_normalization_fails(market):
    from backend.common.exceptions import DataSourceError
    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository

    source = SimpleNamespace(get_valuation=lambda *a: pd.DataFrame())

    def fail(code, dates):
        source._last_share_events = (code, events())
        raise ValueError("bad optional column")

    source.get_share_capital = fail
    svc = IngestionService.__new__(IngestionService)
    svc.c = market
    svc.repo = MarketRepository(market)
    svc._source_for = lambda *a: source
    with pytest.raises(DataSourceError, match="bad optional column"):
        svc.repair_capital_quality("000004.SZ")
    assert market.query_df("SELECT count(*) FROM stock_share_capital_event").iloc[0, 0] == 1


def test_direct_source_priority_is_preserved(market):
    from backend.services.share_capital import ShareCapitalService

    svc = ShareCapitalService(market)
    svc.merge(
        pd.DataFrame(
            [
                {
                    "code": "000004.SZ",
                    "trade_date": "2016-12-30",
                    "total_share": 110,
                    "float_share": 90,
                }
            ]
        ),
        "eastmoney_daily",
    )
    history = ShareCapitalHistoryService(market)
    history.record_events("000004.SZ", events(), "eastmoney_events")
    history.rebuild("000004.SZ", apply_events=True)
    v = StockQuoteSummaryService(market).get_market_values("000004.SZ", [date(2016, 12, 30)])[
        "2016-12-30"
    ]
    assert v["float_share"] == 90
    assert v["float_mv"] == 900


def test_bulk_raw_rebuild_pipeline_240000_rows(market):
    market.execute("DELETE FROM daily_bar")
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT 'S'||c::VARCHAR,DATE '2016-01-01'+d::INTEGER,10 FROM range(100) t(c) CROSS JOIN range(2400) u(d)"
    )
    history = ShareCapitalHistoryService(market)
    for i in range(100):
        history.record_events(f"S{i}", events(day="2016-01-01"), "eastmoney_events")
    result = history.rebuild_all()
    assert result["ok"] == 100 and result["fail"] == 0
    assert CapitalQualityService(market).aggregate().empty
    assert market.query_df("SELECT count(*) FROM stock_share_capital_daily").iloc[0, 0] == 240000
    assert (
        market.query_df("SELECT count(*) FROM daily_metrics WHERE float_mv=800").iloc[0, 0]
        == 240000
    )


@pytest.mark.parametrize("with_diagnostics", [False, True])
def test_raw_source_retry_is_not_skipped_when_daily_fields_are_complete(market, with_diagnostics):
    from backend.datasource.share_capital import expand_equity_events
    from backend.services.ingest import IngestionService
    from backend.services.share_capital import ShareCapitalService
    from backend.storage.repository import MarketRepository

    history = ShareCapitalHistoryService(market)
    raw = events(day="2016-12-01")
    dates = market.query_df("SELECT trade_date FROM daily_bar ORDER BY trade_date").trade_date
    ShareCapitalService(market).merge(expand_equity_events("000004.SZ", raw, dates), "eastmoney_daily")
    invalid = raw.copy()
    invalid["LISTED_A_SHARES"] = -1
    history.record_events("000004.SZ", invalid, "sina_events")
    calls = []
    source = SimpleNamespace(get_valuation=lambda *args: pd.DataFrame())

    def fallback(code, days):
        calls.append(code)
        source._last_fallback_share_events = (code, raw)
        return expand_equity_events(code, raw, days)

    source.get_share_capital_fallback = fallback
    service = IngestionService.__new__(IngestionService)
    service.c = market
    service.repo = MarketRepository(market)
    service._collect_capital_one("000004.SZ", source, dates.min().date(), dates.max().date(),
                                 diagnostics={} if with_diagnostics else None)
    assert calls == ["000004.SZ"]
    assert CapitalQualityService(market).clean("capital_raw_invalid", "000004.SZ")
    assert market.query_df("SELECT count(*) FROM stock_share_capital_event WHERE NOT active").iloc[0,0] == 1


def test_historical_shares_feed_universe_indicators_and_backtest_versions(market, monkeypatch):
    from backend.indicators.engine import IndicatorEngine
    from backend.services.backtest_service import BacktestService
    from backend.services.stock_st_status import StockSTStatusService
    from backend.storage.repository import MarketRepository

    day = date(2017, 1, 2)
    market.execute("INSERT INTO stock_st_status_daily(code,trade_date,is_st,source,quality,captured_at,updated_at) VALUES ('000004.SZ',?,false,'test','accurate',now(),now())", [day])
    monkeypatch.setattr(StockSTStatusService, "assert_published", lambda self: None)
    filters = {"boards": [], "exclude_st": False, "min_list_days": 0,
               "exclude_one_word_limit": False, "float_mv_min": 700, "float_mv_max": 1000}
    repo = MarketRepository(market)
    assert repo.get_universe_asof(day, filters) == []
    backtest = BacktestService.__new__(BacktestService)
    backtest.c = market
    for method in ("_visible_score_profile", "_visible_trade_profile", "_visible_screen_profile"):
        monkeypatch.setattr(backtest, method, lambda value: None)
    params = {"date_start": str(day), "date_end": str(day)}
    before = backtest._resolve_versions(params)["capital_data_version"]
    history = ShareCapitalHistoryService(market)
    history.record_events("000004.SZ", events(), "eastmoney_events")
    history.rebuild("000004.SZ", apply_events=True)
    assert repo.get_universe_asof(day, filters) == ["000004.SZ"]
    after = backtest._resolve_versions(params)["capital_data_version"]
    assert after is not None and after != before
    engine = IndicatorEngine.__new__(IndicatorEngine)
    engine.c = market
    monkeypatch.setattr(engine, "range_frame", lambda *a: market.query_df(
        "SELECT code,trade_date FROM daily_bar WHERE trade_date=?", [day]))
    snapshot = engine.wide_snapshot(day, day, ["000004.SZ"]).iloc[0]
    assert snapshot.float_share == 80 and snapshot.float_mv == 800
    history.rebuild("000004.SZ", apply_events=True)
    assert backtest._resolve_versions(params)["capital_data_version"] == after


def test_new_primary_confirmation_blocks_older_fallback_with_different_float(market):
    history = ShareCapitalHistoryService(market)
    raw = pd.concat([events(day="2015-01-01"), events(day="2016-12-01")], ignore_index=True)
    history.record_events("000004.SZ", raw, "eastmoney_events")
    fallback = events(day="2016-03-31")
    fallback["LISTED_A_SHARES"] = 100
    history.record_events("000004.SZ", fallback, "sina_events")
    history.rebuild("000004.SZ", apply_events=True)
    assert market.query_df("SELECT DISTINCT float_share FROM stock_share_capital_daily").float_share.tolist() == [80]
