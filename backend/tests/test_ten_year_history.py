"""十年历史窗口及跨制度边界的领域回归。"""
from datetime import date
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from backend.common.timeutil import years_before
from backend.dataquality.checker import add_markers
from backend.market_rules import price_limit_pct_for, price_limit_pct_sql
from backend.services.ingest import IngestionService


@pytest.mark.parametrize("code,day,st,expected", [
    ("300059.SZ", "2020-08-21", False, .10),
    ("300059.SZ", "2020-08-24", False, .20),
    ("300059.SZ", "2020-08-21", True, .10),
    ("300059.SZ", "2020-08-24", True, .20),
    ("688981.SH", "2020-08-21", False, .20),
    ("600000.SH", "2016-10-18", True, .05),
    ("600000.SH", "2026-07-06", True, .10),
])
def test_python_sql_historical_limits_agree(code, day, st, expected):
    pct = .10 if code.startswith("600") else .20
    assert price_limit_pct_for(pct, st, day, code=code) == expected
    expr = price_limit_pct_sql("pct", "st", "day", code_expr="code")
    with duckdb.connect(":memory:") as c:
        actual = c.execute(
            f"SELECT {expr} FROM (SELECT ? AS pct, ? AS st, ?::DATE AS day, ? AS code)",
            [pct, st, day, code],
        ).fetchone()[0]
    assert float(actual) == expected


def test_markers_do_not_apply_chinext_old_limit_to_star():
    bars = pd.DataFrame([
        {"code": code, "trade_date": day, "open": 11., "high": 11., "low": 11.,
         "close": 11., "pre_close": 10.}
        for code, day in [("300059.SZ", "2020-08-21"),
                          ("300059.SZ", "2020-08-24"), ("688981.SH", "2020-08-21")]
    ])
    result = add_markers(bars, .20, False)
    assert result.limit_status.tolist() == [1, 0, 0]
    assert result.is_one_word.tolist() == [True, False, False]


def test_history_window_freezes_and_handles_leap_day():
    svc = object.__new__(IngestionService)
    svc._latest_open_day = lambda: date(2024, 2, 29)
    ctx = SimpleNamespace(checkpoint={})
    ctx.set_checkpoint = lambda **kw: ctx.checkpoint.update(kw)
    assert svc._history_window(10, ctx) == (date(2014, 2, 28), date(2024, 2, 29))
    svc._latest_open_day = lambda: date(2026, 10, 19)
    assert svc._history_window(5, ctx) == (date(2014, 2, 28), date(2024, 2, 29))
    assert years_before(date(2024, 2, 29), 4) == date(2020, 2, 29)


def test_historical_limits_at_market_scale():
    # 5,000 stocks × ~2,400 sessions: SQL 批处理与制度边界计数，不物化千万行到 Python。
    expr = price_limit_pct_sql(".20", "FALSE", "day", code_expr="code")
    with duckdb.connect(":memory:") as c:
        result = c.execute(f"""
            SELECT count(*), count(*) FILTER (WHERE pct=.10),
                   count(*) FILTER (WHERE pct=.20)
            FROM (
              SELECT {expr} AS pct FROM
                (SELECT '300059.SZ' AS code, DATE '2020-08-21' + (i%2)::INTEGER * 3 AS day
                 FROM range(12000000) t(i))
            )
        """).fetchone()
    assert result == (12000000, 6000000, 6000000)


def test_refetch_preserves_existing_total_market_value(market, monkeypatch):
    from backend.storage.repository import MarketRepository

    day = date(2018, 1, 2)
    code = "600519.SH"
    market.execute("INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv) VALUES (?,?,?,?)",
                   [code, day, 1000., 800.])
    svc = object.__new__(IngestionService)
    svc.c = market
    svc.repo = MarketRepository(market)
    svc.src = SimpleNamespace(name="akshare")
    svc.s = SimpleNamespace(datasource=SimpleNamespace(primary="akshare"))
    frame = pd.DataFrame([{"code": code, "trade_date": day, "open": 10., "high": 10., "low": 10.,
                              "close": 10., "pre_close": 10., "volume": 100, "amount": 1000.,
                              "adj_factor": 1., "turnover_rate": 1., "float_share": 80.}])
    monkeypatch.setattr(svc, "_fetch_daily_with_fallback", lambda *a, **kw: (frame, "akshare"))
    assert svc.ingest_one_daily(code, day, day, is_st=False) == 1
    assert market.query_df("SELECT total_mv FROM daily_metrics").iloc[0, 0] == 1000.


def test_history_window_before_close_uses_previous_session(monkeypatch):
    from datetime import datetime

    import backend.services.ingest as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 19, 10, 0, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", Clock)
    svc = object.__new__(IngestionService)
    svc._latest_open_day = lambda: date(2026, 10, 19)
    svc._previous_open_day = lambda day: date(2026, 10, 16)
    assert svc._history_window(10) == (date(2016, 10, 16), date(2026, 10, 16))


def test_history_coverage_does_not_hide_two_missing_sessions(market):
    from backend.storage.repository import MarketRepository
    svc = object.__new__(IngestionService)
    svc.c = market
    svc.repo = MarketRepository(market)
    market.execute("INSERT INTO stock_basic(code,list_date) VALUES ('600519.SH','2001-08-27')")
    market.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600519.SH','2016-10-19',10)")
    market.execute("INSERT INTO trade_calendar VALUES ('2016-10-17',TRUE),('2016-10-18',TRUE),('2016-10-19',TRUE)")
    assert '600519.SH' not in svc._history_start_covered_codes(date(2016,10,16))


def test_failed_factor_is_not_marked_done_and_retries(market, monkeypatch):
    from backend.storage.repository import MarketRepository

    svc = object.__new__(IngestionService)
    svc.c = market
    svc.repo = MarketRepository(market)
    ctx = SimpleNamespace(checkpoint={})
    ctx.set_phase = lambda *a, **kw: ctx.checkpoint.update(kw)
    ctx.log = ctx.progress = lambda *a, **kw: None
    ctx.check_cancel = lambda: None

    def fail(*a, **kw):
        raise ValueError("test factor failure")

    monkeypatch.setattr(svc, "_recompute_clean_one", fail)
    assert svc._recompute_clean(["600519.SH"], ctx=ctx)["fail"] == 1
    assert ctx.checkpoint["factor_done_codes"] == []
    monkeypatch.setattr(svc, "_recompute_clean_one", lambda *a, **kw: 3)
    assert svc._recompute_clean(["600519.SH"], ctx=ctx)["ok"] == 1
    assert ctx.checkpoint["factor_done_codes"] == ["600519.SH"]


def test_full_factor_rebuild_preserves_source_first_preclose(market):
    from backend.storage.repository import MarketRepository

    market.execute("""INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close,adj_factor)
        VALUES ('300059.SZ','2016-10-17',10,10,10,10,9.5,1),
               ('300059.SZ','2016-10-18',11,11,11,11,10,1)""")
    svc = object.__new__(IngestionService)
    svc.c = market
    svc.repo = MarketRepository(market)
    assert svc._recompute_clean_one('300059.SZ', .20) == 2
    values = market.query_df('SELECT pre_close FROM daily_bar ORDER BY trade_date')
    assert values.pre_close.tolist() == [9.5, 10.]


@pytest.mark.parametrize('preclose,expected', [(10., False), (11., True), (None, False)])
def test_abnormal_recheck_uses_code_and_fails_closed_on_missing_preclose(market, preclose, expected):
    from backend.services.data_report import DataIntegrityReport

    market.execute("INSERT INTO stock_basic(code,list_date,price_limit_pct) VALUES ('300059.SZ','2010-03-19',0.20)")
    market.execute("INSERT INTO daily_bar(code,trade_date,close,pre_close) VALUES ('300059.SZ','2018-08-20',11.5,?)", [preclose])
    market.execute("""INSERT INTO stock_st_status_daily VALUES
        ('300059.SZ','2018-08-20',FALSE,'baostock',NULL,'accurate',now(),now())""")
    assert DataIntegrityReport(market).recheck_clean(
        'abnormal_change', '300059.SZ', date(2018, 8, 20)) is expected


def test_missing_sina_preclose_uses_official_backup(monkeypatch):
    svc = object.__new__(IngestionService)
    frame = pd.DataFrame([{'trade_date': date(2017, 12, 18), 'close': 7.3,
                           'pre_close': None, '_pre_close_factor_event': False}])
    backup = SimpleNamespace(name='baostock', get_daily_bar=lambda *a: pd.DataFrame([
        {'trade_date': date(2017, 12, 18), 'pre_close': 10.27, 'close': 7.3}]))
    monkeypatch.setattr(svc, '_bao_source', lambda: backup)
    result, source = svc._calibrate_corporate_action_pre_close(frame, '000155.SZ', .10, 'akshare')
    assert result.pre_close.iloc[0] == 10.27
    assert source == 'akshare+baostock:preclose'


@pytest.mark.parametrize('volume', [0, 100])
def test_confirmed_suspension_removes_only_zero_trade_bars(market, monkeypatch, volume):
    from backend.common.exceptions import DataSourceError

    day = date(2024, 11, 6)
    market.execute("INSERT INTO trade_calendar VALUES (?,TRUE)", [day])
    market.execute("INSERT INTO stock_basic(code,list_date) VALUES ('688089.SH','2020-01-01')")
    market.execute("INSERT INTO daily_bar(code,trade_date,close,volume,amount) VALUES ('688089.SH',?,20,?,0)", [day, volume])
    market.execute("INSERT INTO daily_metrics(code,trade_date,total_mv) VALUES ('688089.SH',?,1000)", [day])
    svc = object.__new__(IngestionService)
    svc.c = market
    svc.src = SimpleNamespace(name='baostock')

    def empty(*a, **kw):
        raise DataSourceError('no daily bar')

    monkeypatch.setattr(svc, '_fetch_daily_with_fallback', empty)
    monkeypatch.setattr(svc, '_fetch_st_status_rows', lambda *a, **kw: (svc.src, pd.DataFrame([
        {'code': '688089.SH', 'trade_date': day, 'is_st': False, 'trade_status': 0}])))
    if volume:
        with pytest.raises(DataSourceError, match='冲突'):
            svc.ingest_one_daily('688089.SH', day, day)
        assert len(market.query_df('SELECT * FROM daily_bar')) == 1
        assert len(market.query_df('SELECT * FROM daily_metrics')) == 1
    else:
        assert svc.ingest_one_daily('688089.SH', day, day) == 0
        assert market.query_df('SELECT * FROM daily_bar').empty
        assert market.query_df('SELECT * FROM daily_metrics').empty
        assert len(market.query_df('SELECT * FROM stock_suspension')) == 1
        from backend.services.data_report import DataIntegrityReport
        assert DataIntegrityReport(market).recheck_clean('ohl_repaired', '688089.SH', day)


def test_basic_refresh_preserves_industry_omitted_by_source(market, monkeypatch):
    from backend.storage.repository import MarketRepository

    market.execute("INSERT INTO stock_basic(code,industry) VALUES ('601198.SH','J67资本市场服务'),('301660.SZ',NULL)")
    svc = object.__new__(IngestionService)
    svc.c = market
    svc.repo = MarketRepository(market)
    source = SimpleNamespace(name='baostock',
        get_basic_dates=lambda: pd.DataFrame([
            {'code': code, 'name': code, 'list_date': date(2020, 1, 1), 'delist_date': None}
            for code in ['601198.SH','301660.SZ']]),
        get_industry=lambda: pd.DataFrame([{'code':'301660.SZ','industry':'C39制造业'}]))
    monkeypatch.setattr(svc, '_source_for', lambda *a: source)
    monkeypatch.setattr(svc, '_in_target_board', lambda *a: (True, '主板', .10))
    assert svc.enrich_basic_dates() == 2
    actual = market.query_df('SELECT code,industry FROM stock_basic').set_index('code').industry
    assert actual['601198.SH'] == 'J67资本市场服务'
    assert actual['301660.SZ'] == 'C39制造业'
