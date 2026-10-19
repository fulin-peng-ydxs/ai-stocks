"""转股自动采集、历史轮询与非空字段复查的回归。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.datasource.share_conversion import fetch_sse_conversions, reconstruct_conversion_shares
from backend.services.share_capital import ShareCapitalService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


@pytest.fixture
def market():
    with DuckDBClient(":memory:") as c:
        init_db(c)
        c.execute("INSERT INTO stock_basic(code) VALUES ('600001.SH'),('600002.SH')")
        c.execute(
            "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600001.SH','2026-01-05',10),('600002.SH','2026-01-05',10)"
        )
        yield c


def events():
    return pd.DataFrame(
        [
            {
                "END_DATE": "2025-12-01",
                "NOTICE_DATE": "2025-12-02",
                "TOTAL_SHARES": 10000,
                "CHANGE_REASON": "首发上市",
            },
            {
                "END_DATE": "2026-01-04",
                "NOTICE_DATE": "2026-01-06",
                "TOTAL_SHARES": 10100,
                "CHANGE_REASON": "可转债转股",
            },
        ]
    )


def bonds():
    return [
        {
            "SECURITY_CODE": "110001",
            "TRANSFER_START_DATE": "2026-01-01",
            "TRANSFER_END_DATE": "2026-12-31",
        }
    ]


def daily(bond, year):
    return pd.DataFrame(
        {"effective": pd.to_datetime(["2026-01-04", "2026-01-06"]), "cumulative": [300, 500]}
    )


def test_reconstruction_ignores_incomplete_quarter_anchor_and_never_reads_future_daily():
    evidence = {}
    out = reconstruct_conversion_shares(
        "600001.SH",
        ["2026-01-03", "2026-01-05", "2026-01-06"],
        events(),
        bonds(),
        daily,
        evidence=evidence,
    )
    assert out.total_share.tolist() == [10300, 10500]
    assert out.total_available_date.tolist() == [date(2026, 1, 4), date(2026, 1, 6)]
    assert evidence["anchors"][0]["total_share"] == 10000
    assert evidence["precision_shares"] == 100


@pytest.mark.parametrize("reason", ["回购", "转增股上市", "增发", "债转股及增发"])
def test_non_conversion_changes_stop_old_anchor(reason):
    ev = pd.concat(
        [
            events(),
            pd.DataFrame(
                [
                    {
                        "END_DATE": "2026-01-06",
                        "NOTICE_DATE": "2026-01-07",
                        "TOTAL_SHARES": 15000,
                        "CHANGE_REASON": reason,
                    }
                ]
            ),
        ]
    )
    out = reconstruct_conversion_shares(
        "600001.SH", ["2026-01-05", "2026-01-06", "2026-01-07"], ev, bonds(), daily
    )
    assert out.trade_date.tolist() == [date(2026, 1, 5)]


def test_unknown_anchor_and_overlapping_bonds_are_rejected():
    ev = events()
    ev.loc[0, "NOTICE_DATE"] = None
    assert reconstruct_conversion_shares("600001.SH", ["2026-01-05"], ev, bonds(), daily).empty
    overlapping = bonds() + [dict(bonds()[0], SECURITY_CODE="110002")]
    assert reconstruct_conversion_shares(
        "600001.SH", ["2026-01-05"], events(), overlapping, daily
    ).empty


def test_sse_bad_page_is_not_silent_empty(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"pageHelp": {"total": 1, "pageCount": 1, "data": []}}

    monkeypatch.setattr(
        "backend.datasource.share_conversion.requests.get", lambda *a, **k: Response()
    )
    with pytest.raises(ValueError, match="分页不完整"):
        fetch_sse_conversions("110001", 2026)


def test_sse_source_corrects_stale_event_but_preserves_precision_and_verified(market):
    svc = ShareCapitalService(market)
    old = pd.DataFrame(
        [
            {
                "code": "600001.SH",
                "trade_date": "2026-01-05",
                "total_share": 10000,
                "float_share": 9000,
            }
        ]
    )
    svc.merge(old, "eastmoney_events")
    corrected = old.copy()
    corrected["total_share"] = 10300
    corrected["float_share"] = None
    corrected["evidence_source"] = "sse_conversion_100share:110001"
    svc.merge(corrected, "sse_conversion")
    row = market.query_df("SELECT total_share,total_source FROM stock_share_capital_daily").iloc[0]
    assert row.total_share == 10300 and row.total_source == "sse_conversion_100share:110001"
    corrected["total_share"] = 10320
    svc.merge(corrected, "sse_conversion")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 10300
    market.execute("UPDATE stock_share_capital_daily SET total_source='verified_notice:test'")
    corrected["total_share"] = 11000
    svc.merge(corrected, "sse_conversion")
    assert market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0] == 10300


def test_nonempty_mismatch_is_reviewed_and_attempt_rotation_survives_recreation(market):
    svc = ShareCapitalService(market)
    df = pd.DataFrame(
        [
            {
                "code": "600001.SH",
                "trade_date": "2026-01-05",
                "total_share": 100,
                "float_share": 80,
                "total_mv": 2000,
                "float_mv": 1800,
            }
        ]
    )
    svc.merge(df, "eastmoney_daily", reported=True)
    assert svc.review_candidates(date(2026, 1, 1), date(2026, 1, 6), limit=1).code.tolist() == [
        "600001.SH"
    ]
    MarketRepository(market).log_update(
        "stock_share_capital_daily", "capital_review:600001.SH", None, None, 2, "checked"
    )
    svc = ShareCapitalService(market)
    assert svc.review_candidates(date(2026, 1, 1), date(2026, 1, 6), limit=1).code.tolist() == [
        "600002.SH"
    ]
    market.execute("UPDATE data_update_log SET status='failed',updated_at=now()-INTERVAL '2 days'")
    assert (
        "600001.SH"
        in svc.review_candidates(date(2026, 1, 1), date(2026, 1, 6), limit=2).code.tolist()
    )


def test_history_review_uses_shared_collector_and_retains_unresolved_evidence(market):
    from backend.services.ingest import IngestionService

    ing = IngestionService.__new__(IngestionService)
    ing.c = market
    ing.repo = MarketRepository(market)
    ing.s = SimpleNamespace(
        datasource=SimpleNamespace(
            capital_review_batch_size=1,
            capital_review_interval_days=7,
            history_years=10,
            update_concurrency=1,
        )
    )
    ing._history_window = lambda *args: (date(2026, 1, 1), date(2026, 1, 6))
    ing._source_for = lambda *args: SimpleNamespace(name="test")
    ing._thread_source = lambda *args: None
    calls = []

    def collect(code, source, start, end, diagnostics):
        calls.append(code)
        diagnostics[code] = {
            "remaining": {"total_share_not_yet_disclosed": {"count": 1, "samples": ["2026-01-05"]}}
        }
        return 0

    ing._collect_capital_one = collect
    first = ing.review_capital_history()
    second = ing.review_capital_history()
    assert first["target"] == second["target"] == 1
    assert calls == ["600001.SH", "600002.SH"]
    assert first["remaining_field_issues"] == 1
    assert (
        market.query_df("SELECT count(*) FROM data_update_log WHERE status='checked'").iloc[0, 0]
        == 2
    )


def test_review_only_dispatch_and_param_validation(monkeypatch):
    from backend.services.async_task import _h_stock_ingest
    from backend.services.stock_ingest import normalize_stock_ingest_params

    calls = []
    monkeypatch.setattr(
        "backend.services.ingest.IngestionService",
        lambda: SimpleNamespace(
            review_capital_history=lambda **kw: calls.append(kw) or {"ok": 1, "fail": 0}
        ),
    )
    params = {"recipe": "share_capital_history", "review_only": True}
    ctx = SimpleNamespace(log=lambda *a: None, progress=lambda *a: None)
    assert _h_stock_ingest(params, ctx)["ingest"]["ok"] == 1
    assert len(calls) == 1
    for extra in (
        {"years": 10},
        {"recalculate_only": True},
        {"recipe": "daily_update"},
        {"review_only": "true"},
    ):
        with pytest.raises(ValueError):
            normalize_stock_ingest_params(dict(params, **extra))


def test_conflicting_float_refresh_does_not_erase_existing_fact(market):
    svc = ShareCapitalService(market)
    old = pd.DataFrame([{"code": "600001.SH", "trade_date": "2026-01-05", "total_share": 100, "float_share": 80}])
    svc.merge(old, "eastmoney_events")
    incoming = old.drop(columns="total_share").assign(float_share=150)
    svc.merge(incoming, "sina_daily")
    assert market.query_df("SELECT float_share FROM stock_share_capital_daily").iloc[0, 0] == 80


def test_diagnostics_distinguish_source_price_from_share_error(market, monkeypatch):
    from backend.services.ingest import IngestionService

    service = IngestionService.__new__(IngestionService)
    service.c = market
    monkeypatch.setattr(service, "_valuation_one", lambda *args: 0)
    ShareCapitalService(market).merge(pd.DataFrame([{
        "code": "600001.SH", "trade_date": "2026-01-05", "total_share": 100,
        "float_share": 80, "total_mv": 990, "float_mv": 792,
    }]), "eastmoney_daily", reported=True)
    source = SimpleNamespace(_last_valuation_prices=("600001.SH", {date(2026, 1, 5): 9.9}))
    diagnostics = {}
    service._collect_capital_one("600001.SH", source, date(2026, 1, 5), date(2026, 1, 5), diagnostics)
    remaining = diagnostics["600001.SH"]["remaining"]
    assert set(remaining) == {"total_mv_price_basis_mismatch", "float_mv_price_basis_mismatch"}
    assert remaining["total_mv_price_basis_mismatch"]["evidence"][0]["raw_close"] == 10
    assert market.query_df("SELECT total_mv FROM daily_metrics").iloc[0, 0] == 990


def test_diagnostics_explain_rounded_exchange_total_below_exact_float(market, monkeypatch):
    from backend.services.ingest import IngestionService

    service = IngestionService.__new__(IngestionService)
    service.c = market
    monkeypatch.setattr(service, "_valuation_one", lambda *args: 0)
    ShareCapitalService(market).merge(pd.DataFrame([{
        "code": "600001.SH", "trade_date": "2026-01-05", "float_share": 10022,
    }]), "sina_daily")
    converted = pd.DataFrame([{
        "code": "600001.SH", "trade_date": "2026-01-05", "total_share": 10000,
        "evidence_source": "sse_conversion_100share:110001",
    }])
    source = SimpleNamespace(get_exchange_share_capital=lambda *args: converted)
    diagnostics = {}
    service._collect_capital_one("600001.SH", source, date(2026, 1, 5), date(2026, 1, 5), diagnostics)
    assert diagnostics["600001.SH"]["remaining"]["total_share_exchange_precision_conflict"]["count"] == 1
    assert pd.isna(market.query_df("SELECT total_share FROM stock_share_capital_daily").iloc[0, 0])


def test_review_resume_keeps_window_without_changing_daily_checkpoint(market):
    from backend.services.ingest import IngestionService

    service = IngestionService.__new__(IngestionService)
    service.c = market
    service.repo = MarketRepository(market)
    service.s = SimpleNamespace(datasource=SimpleNamespace(
        capital_review_batch_size=1, capital_review_interval_days=7,
        history_years=10, update_concurrency=1,
    ))
    service._source_for = lambda *args: SimpleNamespace(name="test")
    service._thread_source = lambda *args: None
    service._history_window = lambda *args: pytest.fail("续跑不重新计算日期")
    checkpoint = {"target_end": "2026-01-06", "history_start": "2020-01-01",
                  "capital_review_window": ["2016-01-05", "2026-01-05"],
                  "capital_review_targets": ["600001.SH"]}
    ctx = SimpleNamespace(checkpoint=checkpoint, set_checkpoint=lambda **kw: checkpoint.update(kw),
                          log=lambda *args: None, flush=lambda: None)
    windows = []
    service._collect_capital_one = lambda code, source, start, end, diagnostics: windows.append((start, end))
    service._run_bounded_parallel = lambda pending, worker, **kw: [worker(code) for code in pending]
    service.review_capital_history(ctx=ctx)
    assert windows == [(date(2016, 1, 5), date(2026, 1, 5))]
    assert checkpoint["target_end"] == "2026-01-06"
    assert checkpoint["history_start"] == "2020-01-01"
