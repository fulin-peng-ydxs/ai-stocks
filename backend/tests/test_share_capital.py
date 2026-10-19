"""股本采集、点时边界及市值优先级的闭环回归。"""

from datetime import date

import pandas as pd
import pytest

from backend.datasource.share_capital import expand_equity_events
from backend.services.share_capital import ShareCapitalService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market():
    with DuckDBClient(":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO stock_basic(code,total_share,float_share) VALUES ('600000.SH',999,888)"
        )
        c.execute(
            "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH','2026-01-02',10),('600000.SH','2026-01-05',20)"
        )
        yield c


def frame(day="2026-01-05", **kw):
    return pd.DataFrame(
        [
            dict(
                code="600000.SH",
                trade_date=day,
                total_share=100,
                float_share=80,
                total_mv_eligible=True,
                **kw,
            )
        ]
    )


def test_old_backfill_cannot_overwrite_latest_and_source_values_win(market):
    svc = ShareCapitalService(market)
    svc.merge(frame("2026-01-02"), "eastmoney_events")
    assert market.query_df("SELECT total_share FROM stock_basic").iloc[0, 0] == 999
    svc.merge(frame(), "eastmoney_events")
    assert market.query_df(
        "SELECT total_mv,float_mv FROM daily_metrics ORDER BY trade_date DESC"
    ).iloc[0].tolist() == [2000, 1600]
    svc.merge(frame(total_mv=2100, float_mv=1700), "eastmoney_daily", reported=True)
    svc.merge(frame(), "sina_daily")
    assert market.query_df(
        "SELECT total_mv,float_mv FROM daily_metrics ORDER BY trade_date DESC"
    ).iloc[0].tolist() == [2100, 1700]
    svc.merge(frame("2026-01-02"), "eastmoney_daily")
    assert market.query_df("SELECT total_share_date FROM stock_basic").iloc[0, 0].date() == date(
        2026, 1, 5
    )


def test_total_uses_a_price_even_for_mixed_or_unknown_scope_and_invalid_does_not_erase(market):
    svc = ShareCapitalService(market)
    df = frame()
    df["total_mv_eligible"] = False
    svc.merge(df, "eastmoney_daily")
    assert market.query_df("SELECT total_mv FROM daily_metrics").iloc[0, 0] == 2000
    df["float_share"] = -1
    df["total_share"] = None
    svc.merge(df, "eastmoney_daily")
    assert market.query_df("SELECT float_share FROM stock_share_capital_daily").iloc[0, 0] == 80


def test_event_expansion_uses_change_date_without_publication_gate():
    ev = pd.DataFrame(
        [
            {
                "END_DATE": "2026-01-02",
                "NOTICE_DATE": "2026-01-02",
                "TOTAL_SHARES": 100,
                "LISTED_A_SHARES": 80,
                "TOTAL_A_SHARES": 100,
            },
            {
                "END_DATE": "2026-01-05",
                "NOTICE_DATE": "2026-01-07",
                "TOTAL_SHARES": 200,
                "LISTED_A_SHARES": 90,
                "TOTAL_A_SHARES": 150,
            },
        ]
    )
    df = expand_equity_events(
        "600000.SH", ev, ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-07"]
    )
    assert df.total_share.isna().tolist() == [True, False, False, False]
    assert df.total_mv_eligible.tolist() == [False, True, False, False]


def test_latest_quote_never_falls_back_to_unversioned_basic(market):
    from backend.services.stock_quote_summary import StockQuoteSummaryService

    assert StockQuoteSummaryService(market).get("600000.SH")["total_share"] is None


def test_merge_representative_history_scale():
    # 一批 100 股 × 2400 日，覆盖输入、合并 SQL、最新投影和落表，而非纯算法基准。
    import numpy as np

    with DuckDBClient(":memory:") as c:
        init_db(c)
        codes = [f"{i:06d}.SZ" for i in range(100)]
        df = pd.DataFrame(
            {
                "code": np.repeat(codes, 2400),
                "trade_date": np.tile(pd.date_range("2016-01-01", periods=2400), 100),
                "total_share": 10000,
                "float_share": 8000,
                "total_mv_eligible": True,
            }
        )
        with c.temp_view(df, prefix="scale") as t:
            c.execute(f"INSERT INTO stock_basic(code) SELECT DISTINCT code FROM {t}")
            c.execute(
                f"INSERT INTO daily_bar(code,trade_date,close) SELECT code,trade_date,10 FROM {t}"
            )
        ShareCapitalService(c).merge(df, "eastmoney_events")
        assert c.query_df("SELECT count(*) FROM stock_share_capital_daily").iloc[0, 0] == 240000
        assert (
            c.query_df(
                "SELECT count(*) FROM daily_metrics WHERE total_mv=100000 AND float_mv=80000"
            ).iloc[0, 0]
            == 240000
        )


def test_later_publication_does_not_erase_historical_shares_or_mv(market):
    svc = ShareCapitalService(market)
    svc.merge(frame(), "eastmoney_events")
    revised = frame(total_available_date="2026-01-07", float_available_date="2026-01-07")
    svc.merge(revised, "eastmoney_events")
    row = market.query_df("SELECT total_mv,float_mv FROM daily_metrics").iloc[0]
    assert row.tolist() == [2000,1600]
    assert market.query_df("SELECT total_share FROM stock_basic").iloc[0,0] == 100


def test_reported_revisions_replace_same_source_without_replacing_other_dates(market):
    svc = ShareCapitalService(market)
    svc.merge(frame(), "eastmoney_daily")
    correction = frame()
    correction["total_share"] = 120
    svc.merge(correction, "eastmoney_daily")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 120


def test_source_empty_is_not_transport_failure(monkeypatch):
    from backend.datasource.share_capital import fetch_daily_valuation

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": None, "code": 9201}

    monkeypatch.setattr("backend.datasource.share_capital.requests.get", lambda *a, **k: Response())
    assert fetch_daily_valuation("000013.SZ").empty


def test_scope_evidence_update_preserves_a_price_total_mv(market):
    svc = ShareCapitalService(market)
    df = frame()
    df["total_mv_eligible"] = False
    svc.merge(df, "eastmoney_daily")
    svc.merge(frame(), "eastmoney_events")
    assert market.query_df("SELECT total_mv FROM daily_metrics").iloc[0, 0] == 2000


def test_sina_float_history_uses_share_units_and_never_backfills_future(monkeypatch):
    from backend.datasource.share_capital import fetch_sina_float_shares

    class Response:
        text = 'var x=([{"date":"2026-01-05","amount":12.34}]);'

        def raise_for_status(self):
            pass

    monkeypatch.setattr("backend.datasource.share_capital.requests.get", lambda *a, **k: Response())
    df = fetch_sina_float_shares("600000.SH", ["2026-01-02", "2026-01-05"])
    assert pd.isna(df.iloc[0].float_share)
    assert df.iloc[1].float_share == 123400


def test_sina_explicit_null_is_empty(monkeypatch):
    from backend.datasource.share_capital import fetch_sina_float_shares

    class Response:
        text = "var KKE_ShareAmount_sz000971=(null);"

        def raise_for_status(self):
            pass

    monkeypatch.setattr("backend.datasource.share_capital.requests.get", lambda *a, **k: Response())
    assert fetch_sina_float_shares("000971.SZ", ["2026-01-02"]).empty


def test_valuation_incomplete_page_is_rejected(monkeypatch):
    from backend.datasource.share_capital import fetch_daily_valuation

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"pages": 1, "count": 2, "data": [{"TRADE_DATE": "2026-01-02"}]}}

    monkeypatch.setattr("backend.datasource.share_capital.requests.get", lambda *a, **k: Response())
    with pytest.raises(ValueError, match="分页总数"):
        fetch_daily_valuation("600000.SH")


def test_raw_price_correction_refreshes_only_computed_market_values(market):
    svc = ShareCapitalService(market)
    svc.merge(frame(), "eastmoney_events")
    market.execute("UPDATE daily_bar SET close=30 WHERE trade_date='2026-01-05'")
    svc.merge(pd.DataFrame([{"code": "600000.SH", "trade_date": "2026-01-05"}]), "sina_daily")
    assert market.query_df("SELECT total_mv,float_mv FROM daily_metrics").iloc[0].tolist() == [
        3000,
        2400,
    ]


def test_computed_value_cannot_invert_protected_legacy_market_value(market):
    market.execute("INSERT INTO daily_metrics(code,trade_date,float_mv) VALUES ('600000.SH','2026-01-05',2200)")
    ShareCapitalService(market).merge(frame(), "eastmoney_events")
    row = market.query_df("SELECT total_mv,float_mv,total_mv_source FROM daily_metrics").iloc[0]
    assert pd.isna(row.total_mv)
    assert row.float_mv == 2200
    assert pd.isna(row.total_mv_source)


def test_unchanged_total_survives_late_float_disclosure():
    events = pd.DataFrame([
        {"END_DATE": "2026-01-02", "NOTICE_DATE": "2026-01-02", "TOTAL_SHARES": 100,
         "TOTAL_A_SHARES": 100, "LISTED_A_SHARES": 80},
        {"END_DATE": "2026-01-05", "NOTICE_DATE": "2026-01-09", "TOTAL_SHARES": 100,
         "TOTAL_A_SHARES": 100, "LISTED_A_SHARES": 90},
        {"END_DATE": "2026-01-06", "NOTICE_DATE": "2026-01-10", "TOTAL_SHARES": 120,
         "TOTAL_A_SHARES": 120, "LISTED_A_SHARES": 90},
    ])
    out = expand_equity_events("600000.SH", events, ["2026-01-05", "2026-01-06"])
    assert out.iloc[0].total_share == 100
    assert out.iloc[0].total_available_date == date(2026, 1, 9)
    assert out.iloc[0].float_share == 90
    assert out.iloc[1].total_share == 120  # 变动日立即使用新股数，不等公告日


def test_sina_structure_units_dates_and_scope(monkeypatch):
    from backend.datasource.share_capital import fetch_sina_equity_events
    class Response:
        text = '<html></html>'
        def raise_for_status(self):
            pass
    monkeypatch.setattr("backend.datasource.share_capital.requests.get", lambda *a, **k: Response())
    table = pd.DataFrame([
        ["·变动日期", "20260102", "20260105"], ["·公告日期", "19000101", "20260103"],
        ["·总股本(历史记录)", "10 万股", "12 万股"],
        ["流通A股(历史记录)", "8 万股", "9 万股"],
        ["限售A股(历史记录)", "2 万股", "--"],
    ])
    monkeypatch.setattr("backend.datasource.share_capital.pd.read_html", lambda *a, **k: [table])
    events = fetch_sina_equity_events("600000.SH")
    assert events.iloc[0].TOTAL_SHARES == 100000
    assert pd.isna(events.iloc[0].NOTICE_DATE)
    assert pd.isna(events.iloc[1].TOTAL_A_SHARES)  # 未知限售份额不证明纯A股


def test_latest_collection_checks_missing_shares_even_with_both_market_values(market, monkeypatch):
    from types import SimpleNamespace

    from backend.services.ingest import IngestionService
    from backend.storage.repository import MarketRepository
    market.execute("INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv) VALUES ('600000.SH','2026-01-05',2000,1600)")
    service = IngestionService.__new__(IngestionService)
    service.c = market
    service.repo = MarketRepository(market)
    service.s = SimpleNamespace(datasource=SimpleNamespace(update_concurrency=1))
    monkeypatch.setattr(service, "_source_for", lambda key: SimpleNamespace(name="test"))
    calls = []
    def collect(code, source, start, end):
        calls.append(code)
        ShareCapitalService(market).merge(frame(), "eastmoney_daily")
        return 1
    monkeypatch.setattr(service, "_collect_capital_one", collect)
    service.ingest_valuation_latest(trade_date=date(2026, 1, 5))
    assert calls == ["600000.SH"]
    calls.clear()
    service.ingest_valuation_latest(trade_date=date(2026, 1, 5))
    assert calls == []


def test_fallback_cannot_cross_primary_unpublished_change(market, monkeypatch):
    from types import SimpleNamespace

    from backend.services.ingest import IngestionService
    service = IngestionService.__new__(IngestionService)
    service.c = market
    monkeypatch.setattr(service, "_valuation_one", lambda *args: 0)
    primary = frame(total_effective_date="2026-01-05", total_available_date="2026-01-09",
                    float_effective_date="2026-01-05", float_available_date="2026-01-09")
    older = frame(total_effective_date="2026-01-02", total_available_date="2026-01-02",
                  float_effective_date="2026-01-02", float_available_date="2026-01-02")
    source = SimpleNamespace(get_share_capital=lambda *args: primary,
                             get_share_capital_fallback=lambda *args: older)
    diagnostic = {}
    service._collect_capital_one("600000.SH", source, date(2026, 1, 5), date(2026, 1, 5), diagnostic)
    assert market.query_df("SELECT total_source FROM stock_share_capital_daily").iloc[0,0] == "eastmoney_events"
    assert diagnostic["600000.SH"]["remaining"] == {}


def test_independent_source_runs_after_primary_failure(market, monkeypatch):
    from types import SimpleNamespace

    from backend.common.exceptions import DataSourceError
    from backend.services.ingest import IngestionService
    service = IngestionService.__new__(IngestionService)
    service.c = market
    monkeypatch.setattr(service, "_valuation_one", lambda *args: 0)
    def fail(*args):
        raise ValueError("primary unavailable")
    source = SimpleNamespace(get_share_capital=fail, get_share_capital_fallback=lambda *args: frame())
    diagnostic = {}
    with pytest.raises(DataSourceError, match="primary unavailable"):
        service._collect_capital_one("600000.SH", source, date(2026, 1, 5), date(2026, 1, 5), diagnostic)
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 100
    assert diagnostic["600000.SH"]["errors"]


def test_real_value_changes_update_revision_but_repeated_merge_does_not(market):
    from backend.scoring.snapshot import _current_param_hash
    before = _current_param_hash(market)
    service = ShareCapitalService(market)
    service.merge(frame(), "eastmoney_events")
    revision = market.query_df("SELECT max(id) FROM data_update_log").iloc[0, 0]
    assert _current_param_hash(market) != before
    service.merge(frame(), "eastmoney_events")
    assert market.query_df("SELECT max(id) FROM data_update_log").iloc[0, 0] == revision
    revised = frame()
    revised["total_share"] = 110
    service.merge(revised, "eastmoney_events")
    assert market.query_df("SELECT max(id) FROM data_update_log").iloc[0, 0] > revision


def test_backtest_signature_tracks_capital_changes_only_in_requested_window(market, monkeypatch):
    from backend.services.backtest_service import BacktestService
    service = BacktestService.__new__(BacktestService)
    service.c = market
    for name in ("_visible_score_profile", "_visible_trade_profile", "_visible_screen_profile"):
        monkeypatch.setattr(service, name, lambda key: None)
    params = {"date_start": "2026-01-05", "date_end": "2026-01-05"}
    before = service._resolve_versions(params)["capital_data_version"]
    svc = ShareCapitalService(market)
    svc.merge(frame("2026-01-02"), "eastmoney_events")
    assert service._resolve_versions(params)["capital_data_version"] == before
    svc.merge(frame(), "eastmoney_events")
    assert service._resolve_versions(params)["capital_data_version"] is not None


def verified_fact(**changes):
    value = {"code": "600000.SH", "trade_date": "2026-01-05", "effective_date": "2026-01-02",
                 "available_date": "2026-01-05", "total_share": 120, "total_mv_eligible": True,
                 "notice_id": "AN_example", "source_ref": "https://example.com/notice", "reason": "已核验公告总股本"}
    value.update(changes)
    return value


@pytest.mark.parametrize("change", [
    {"effective_date": "2026-01-06"},
    {"total_share": 1.5}, {"total_share": True}, {"total_share": 0},
    {"total_mv_eligible": "true"}, {"source_ref": "file:///local"}, {"reason": ""},
    {"code": "600001.SH"}, {"trade_date": "2099-01-01"},
])
def test_verified_notice_rejects_unsafe_evidence(change):
    from backend.services.stock_ingest import normalize_stock_ingest_params
    with pytest.raises(ValueError):
        normalize_stock_ingest_params({"recipe": "share_capital_history", "codes": ["600000.SH"],
                                          "verified_facts": [verified_fact(**change)]})


def test_verified_notice_persists_exact_total_and_survives_routine_refresh(market):
    svc = ShareCapitalService(market)
    svc.merge(frame("2026-01-02"), "eastmoney_events")
    svc.merge(frame(), "eastmoney_events")
    assert svc.merge_verified([verified_fact()], ["600000.SH"]) == 1
    for source in ("eastmoney_events", "sina_events", "eastmoney_daily", "sina_daily"):
        old = frame()
        old["total_mv_eligible"] = False
        svc.merge(old, source)
    values = market.query_df("SELECT trade_date,total_share,float_share,total_source,total_mv_eligible "
                             "FROM stock_share_capital_daily ORDER BY trade_date")
    assert values.total_share.tolist() == [100, 120]
    assert values.float_share.tolist() == [80, 80]
    assert values.iloc[1].total_source == "verified_notice:AN_example"
    assert bool(values.iloc[1].total_mv_eligible)
    assert market.query_df("SELECT total_mv FROM daily_metrics ORDER BY trade_date").iloc[1, 0] == 2400
    revision = market.query_df("SELECT max(id) FROM data_update_log").iloc[0, 0]
    svc.merge_verified([verified_fact()], ["600000.SH"])
    assert market.query_df("SELECT max(id) FROM data_update_log").iloc[0, 0] == revision


def test_verified_notice_batch_prevalidation_prevents_partial_import(market):
    svc = ShareCapitalService(market)
    svc.merge(frame(), "eastmoney_events")
    with pytest.raises(ValueError, match="整批"):
        svc.merge_verified([verified_fact(), verified_fact(trade_date="2026-01-06")], ["600000.SH"])
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 100
    with pytest.raises(ValueError, match="整批"):
        svc.merge_verified([verified_fact(total_share=50)], ["600000.SH"])
    assert market.query_df("SELECT float_share FROM stock_share_capital_daily").iloc[0, 0] == 80


def test_primary_event_updates_or_withdraws_older_fallback_but_keeps_same_event_evidence(market):
    svc = ShareCapitalService(market)
    old = frame(total_effective_date="2026-01-02", total_available_date="2026-01-02")
    svc.merge(old, "sina_events")
    newer = frame(total_effective_date="2026-01-05", total_available_date="2026-01-08")
    newer["total_share"] = 120
    svc.merge(newer, "eastmoney_events")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 120
    # 独立来源已在当日披露同一事件时，不受另一源的更晚公告日覆盖。
    newer["total_available_date"] = "2026-01-05"
    svc.merge(newer, "sina_events")
    later = newer.copy()
    later["total_available_date"] = "2026-01-08"
    svc.merge(later, "eastmoney_events")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 120
    newer["total_share"] = 125
    svc.merge(newer, "eastmoney_events")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 125


def test_verified_facts_are_dispatched_before_collection(market, monkeypatch):
    from types import SimpleNamespace

    import backend.services.ingest as ingest_module
    from backend.services.async_task import _h_stock_ingest
    from backend.services.stock_ingest import normalize_stock_ingest_params
    params = {"recipe": "share_capital_history", "codes": ["600000.SH"], "verified_facts": [verified_fact()]}
    def collect(**kwargs):
        assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 120
        return {"ok": 1, "fail": 0}
    monkeypatch.setattr(ingest_module, "IngestionService",
                        lambda: SimpleNamespace(c=market, ingest_share_capital=collect))
    ctx = SimpleNamespace(log=lambda *args: None, progress=lambda *args: None, check_cancel=lambda: None)
    result = _h_stock_ingest(params, ctx)
    assert result["ingest"]["verified_fact_rows"] == 1
    for invalid in [dict(params, recipe="daily_update"), dict(params, codes=[]),
                    dict(params, verified_facts=[verified_fact(), verified_fact()])]:
        with pytest.raises(ValueError):
            normalize_stock_ingest_params(invalid)


def test_unknown_publication_does_not_block_valid_historical_record(market):
    svc = ShareCapitalService(market)
    svc.merge(frame(total_effective_date="2026-01-02"), "eastmoney_events")
    unknown = frame(total_effective_date="2026-01-05", total_available_date=None)
    unknown["total_share"] = 120
    svc.merge(unknown, "eastmoney_events")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 120
    assert market.query_df("SELECT total_mv FROM daily_metrics").iloc[0, 0] == 2400


def test_unchanged_value_keeps_latest_confirmation_date():
    events = pd.DataFrame([
        {"END_DATE": "2026-01-02", "NOTICE_DATE": "2026-02-01", "TOTAL_SHARES": 100,
             "LISTED_A_SHARES": 80, "TOTAL_A_SHARES": 100},
        {"END_DATE": "2026-01-05", "NOTICE_DATE": "2026-01-03", "TOTAL_SHARES": 100,
             "LISTED_A_SHARES": 85, "TOTAL_A_SHARES": 100},
        {"END_DATE": "2026-01-06", "NOTICE_DATE": "2026-02-02", "TOTAL_SHARES": 100,
             "LISTED_A_SHARES": 85, "TOTAL_A_SHARES": 100},
    ])
    facts = expand_equity_events("600000.SH", events, ["2026-01-02", "2026-01-05", "2026-01-06"])
    assert facts.iloc[0].total_share == 100
    assert facts.total_share.iloc[1:].tolist() == [100, 100]
    assert facts.total_available_date.iloc[1:].tolist() == [date(2026, 1, 3), date(2026, 2, 2)]
    assert facts.total_effective_date.tolist() == [date(2026,1,2), date(2026,1,5), date(2026,1,6)]


def test_scope_change_does_not_hide_unchanged_disclosed_total_share():
    events = pd.DataFrame([
        {"END_DATE": "2026-01-02", "NOTICE_DATE": "2026-01-02", "TOTAL_SHARES": 100,
         "LISTED_A_SHARES": 80, "TOTAL_A_SHARES": 100},
        {"END_DATE": "2026-01-05", "NOTICE_DATE": "2026-01-09", "TOTAL_SHARES": 100,
         "LISTED_A_SHARES": 80, "TOTAL_A_SHARES": 90},
    ])
    out = expand_equity_events("600000.SH", events, ["2026-01-05"])
    assert out.iloc[0].total_share == 100
    assert not out.iloc[0].total_mv_eligible


def test_missing_recalculation_is_scoped_idempotent_and_preserves_reported(market):
    svc = ShareCapitalService(market)
    svc.merge(frame("2026-01-02"), "eastmoney_daily")
    svc.merge(frame(total_mv=2100, float_mv=1700), "eastmoney_daily", reported=True)
    market.execute("UPDATE daily_metrics SET total_mv=NULL,total_mv_source=NULL WHERE trade_date='2026-01-02'")
    market.execute("UPDATE stock_share_capital_daily SET total_mv_eligible=false")
    assert svc.recalculate_missing(["600001.SH"])["target"] == 0
    assert svc.recalculate_missing()["total_mv_filled"] == 1
    assert market.query_df("SELECT total_mv FROM daily_metrics ORDER BY trade_date").total_mv.tolist() == [1000,2100]
    n = market.query_df("SELECT count(*) n FROM data_update_log").iloc[0,0]
    assert svc.recalculate_missing()["target"] == 0
    assert market.query_df("SELECT count(*) n FROM data_update_log").iloc[0,0] == n


def test_exchange_daily_evidence_survives_source_refresh(market):
    svc = ShareCapitalService(market)
    fact = verified_fact(source_type="exchange_daily", source_ref="https://bond.sse.com.cn/data/statistics/Statistics/debtstock/index_his.shtml")
    svc.merge_verified([fact], ["600000.SH"])
    svc.merge(frame(), "eastmoney_daily")
    row = market.query_df("SELECT total_share,total_source FROM stock_share_capital_daily").iloc[0]
    assert row.total_share == 120
    assert row.total_source == "verified_exchange_daily:AN_example"
    with pytest.raises(ValueError, match="上交所"):
        svc.merge_verified([dict(fact, source_ref="https://example.com")], ["600000.SH"])


def test_recalculation_params_reject_mixed_modes():
    from backend.services.stock_ingest import normalize_stock_ingest_params
    params = {"recipe":"share_capital_history", "recalculate_only":True}
    assert normalize_stock_ingest_params(params)["recalculate_only"]
    for extra in ({"years":10}, {"verified_facts":[verified_fact()], "codes":["600000.SH"]}, {"recalculate_only":"true"}, {"recipe":"daily"}):
        with pytest.raises(ValueError):
            normalize_stock_ingest_params(dict(params, **extra))


def test_recalculation_task_does_not_call_external_collection(market, monkeypatch):
    from types import SimpleNamespace

    import backend.services.ingest as module
    from backend.services.async_task import _h_stock_ingest
    ShareCapitalService(market).merge(frame(), "eastmoney_daily")
    market.execute("UPDATE daily_metrics SET total_mv=NULL,total_mv_source=NULL")
    monkeypatch.setattr(module, "IngestionService", lambda: SimpleNamespace(c=market))
    ctx = SimpleNamespace(log=lambda *args: None, progress=lambda *args: None, check_cancel=lambda: None)
    result = _h_stock_ingest({"recipe":"share_capital_history", "recalculate_only":True}, ctx)
    assert result["ingest"]["total_mv_filled"] == 1


def test_newer_fallback_event_replaces_stale_primary_but_same_date_primary_wins(market):
    service = ShareCapitalService(market)
    old = frame(total_effective_date="2026-01-02", float_effective_date="2026-01-02")
    service.merge(old, "eastmoney_events")
    newer = frame(total_effective_date="2026-01-05", float_effective_date="2026-01-05").assign(total_share=120, float_share=90)
    service.merge(newer, "sina_events")
    row = market.query_df("SELECT total_share,float_share,total_source FROM stock_share_capital_daily").iloc[0]
    assert row.tolist() == [120, 90, "sina_events"]
    service.merge(old, "eastmoney_events")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0,0] == 120
    newer["total_share"] = 125
    service.merge(newer, "eastmoney_events")
    service.merge(newer.assign(total_share=130), "sina_events")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0,0] == 125


def test_newer_fallback_float_cannot_erase_good_value_when_total_conflicts(market):
    service = ShareCapitalService(market)
    service.merge(frame(total_effective_date="2026-01-02", float_effective_date="2026-01-02"), "eastmoney_events")
    service.merge(frame(total_effective_date="2026-01-02", float_effective_date="2026-01-05").assign(total_share=120, float_share=110), "sina_events")
    assert market.query_df("SELECT total_share,float_share FROM stock_share_capital_daily").iloc[0].tolist() == [100,80]


def test_precision_only_fallback_cannot_replace_exact_primary_or_erase_float(market):
    service = ShareCapitalService(market)
    old = frame(total_effective_date="2026-01-02", float_effective_date="2026-01-02").assign(total_share=104, float_share=104)
    service.merge(old, "eastmoney_events")
    rounded = frame(total_effective_date="2026-01-05", float_effective_date="2026-01-05").assign(total_share=100, float_share=100)
    service.merge(rounded, "sina_events")
    assert market.query_df("SELECT total_share,float_share FROM stock_share_capital_daily").iloc[0].tolist() == [104,104]


def test_precise_event_refines_100_share_exchange_estimate(market):
    service = ShareCapitalService(market)
    service.merge(frame(total_effective_date="2026-01-02"), "eastmoney_events")
    market.execute("UPDATE stock_share_capital_daily SET total_source='sse_conversion_100share:110001'")
    exact = frame(total_effective_date="2026-01-05", float_effective_date="2026-01-05").assign(total_share=126,float_share=126)
    service.merge(exact, "eastmoney_events")
    assert market.query_df("SELECT total_share,float_share FROM stock_share_capital_daily").iloc[0].tolist() == [126,126]


def test_newer_fallback_does_not_replace_primary_confirmed_by_reported_market_value(market):
    service = ShareCapitalService(market)
    old = frame(total_effective_date="2026-01-02",float_effective_date="2026-01-02",float_mv=1600)
    service.merge(old, "eastmoney_events", reported=True)
    newer = frame(total_effective_date="2026-01-05",float_effective_date="2026-01-05").assign(float_share=90)
    service.merge(newer, "sina_events")
    assert market.query_df("SELECT float_share FROM stock_share_capital_daily").iloc[0,0] == 80
    market.execute("UPDATE stock_share_capital_daily SET float_share=90,float_source='sina_events',float_effective_date='2026-01-05'")
    service.merge(old, "eastmoney_events")
    assert market.query_df("SELECT float_share FROM stock_share_capital_daily").iloc[0,0] == 80
