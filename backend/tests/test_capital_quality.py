"""股本市值：全历史发现、稳定台账、来源失败、修复复检、规模回归。"""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError
from backend.services.async_task import _recover_one
from backend.services.capital_quality import CapitalQualityService
from backend.services.data_report import DataIntegrityReport
from backend.services.ingest import IngestionService
from backend.services.share_capital import ShareCapitalService
from backend.storage.catalog import build_catalog
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


@pytest.fixture
def market(tmp_path):
    with DuckDBClient(str(tmp_path / "capital.duckdb")) as c:
        init_db(c)
        c.execute(
            "INSERT INTO stock_basic(code,delist_date) VALUES ('600001.SH',NULL),('600002.SH','2020-01-01')"
        )
        c.execute(
            "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600001.SH','2017-01-05',10),('600002.SH','2017-01-05',10)"
        )
        yield c


def fact(code="600001.SH", **kwargs):
    return pd.DataFrame(
        [
            {
                "code": code,
                "trade_date": date(2017, 1, 5),
                "total_share": 100,
                "float_share": 80,
                **kwargs,
            }
        ]
    )


def ingest(c, source):
    service = IngestionService.__new__(IngestionService)
    service.c = c
    service.repo = MarketRepository(c)
    service._source_for = lambda *args: source
    return service


def ctx():
    return SimpleNamespace(
        tid="capital_fix_test", check_cancel=lambda: None, log=lambda *args: None
    )


def issue(c, code="600001.SH", kind="capital_gap"):
    return int(
        c.query_df(
            "SELECT id FROM data_quality_issue WHERE code=? AND issue_type=? AND status='open'",
            [code, kind],
        ).iloc[0, 0]
    )


def test_full_history_includes_delisted_and_table_catalog(market):
    quality = CapitalQualityService(market)
    assert quality.sync()["capital_gap"] == 2
    catalog = {row["table"]: row for row in build_catalog(market)}
    assert catalog["stock_share_capital_daily"]["open_issues"] == 2
    assert catalog["daily_metrics"]["open_issues"] == 2
    assert not DataIntegrityReport(market).recheck_clean("capital_gap", "600002.SH", None)


def test_scoped_sync_preserves_other_stock_id_and_fixing(market):
    quality = CapitalQualityService(market)
    quality.sync()
    first, other = issue(market), issue(market, "600002.SH")
    market.execute(
        "UPDATE data_quality_issue SET status='fixing',fix_task_id='test' WHERE id=?", [first]
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600001.SH','2018-01-05',10)"
    )
    quality.sync(["600001.SH"])
    assert market.query_df("SELECT count(*) FROM data_quality_issue").iloc[0, 0] == 2
    assert (
        market.query_df("SELECT status FROM data_quality_issue WHERE id=?", [first]).iloc[0, 0]
        == "fixing"
    )
    assert issue(market, "600002.SH") == other
    ShareCapitalService(market).merge(fact(), "eastmoney_events")
    market.execute("DELETE FROM daily_bar WHERE trade_date='2018-01-05'")
    quality.sync(["600001.SH"])
    assert issue(market, "600002.SH") == other
    # 当前修复任务拥有终态判定，局部扫描不能提前关闭 fixing。
    assert (
        market.query_df("SELECT status FROM data_quality_issue WHERE id=?", [first]).iloc[0, 0]
        == "fixing"
    )


def test_fix_real_shared_collector_resolves_only_after_recheck(market):
    quality = CapitalQualityService(market)
    quality.sync()
    iid = issue(market)
    source = SimpleNamespace(
        get_valuation=lambda *args: pd.DataFrame(), get_share_capital=lambda *args: fact()
    )
    clean, _, _ = _recover_one(
        market, DataIntegrityReport(market), ingest(market, source), ctx(), iid
    )
    assert clean
    assert (
        market.query_df("SELECT status FROM data_quality_issue WHERE id=?", [iid]).iloc[0, 0]
        == "resolved"
    )
    assert issue(market, "600002.SH")
    assert market.query_df(
        "SELECT total_mv,float_mv FROM daily_metrics WHERE code='600001.SH'"
    ).iloc[0].tolist() == [1000, 800]


def test_failed_primary_is_visible_even_when_fallback_fills(market):
    CapitalQualityService(market).sync()
    iid = issue(market)

    def fail(*args):
        raise ValueError("接口超时")

    source = SimpleNamespace(get_valuation=fail, get_share_capital=lambda *args: fact())
    with pytest.raises(DataSourceError, match="接口超时"):
        _recover_one(market, DataIntegrityReport(market), ingest(market, source), ctx(), iid)
    row = market.query_df(
        "SELECT status,fix_task_id FROM data_quality_issue WHERE id=?", [iid]
    ).iloc[0]
    assert row.status == "open" and pd.isna(row.fix_task_id)
    assert (
        "接口超时"
        in market.query_df(
            "SELECT detail FROM data_update_log WHERE source='capital_collect:600001.SH'"
        ).iloc[0, 0]
    )
    # 下次修复先复检真实数据，已补齐可正常关闭，不必重复请求失败来源。
    clean, _, _ = _recover_one(
        market, DataIntegrityReport(market), ingest(market, source), ctx(), iid
    )
    assert clean


def test_price_basis_difference_is_source_review_not_business_failure(market):
    source = SimpleNamespace(
        get_valuation=lambda *args: fact(total_mv=990, float_mv=792, valuation_close=9.9),
        _last_valuation_prices=("600001.SH", {date(2017, 1, 5): 9.9}),
    )
    ing = ingest(market, source)
    result = ing.repair_capital_quality("600001.SH")
    quality = CapitalQualityService(market)
    assert quality.sync(["600001.SH"])["capital_mismatch"] == 0
    assert quality.clean("capital_mismatch", "600001.SH")
    assert quality.aggregate(["600001.SH"], source_only=True).issue_days.sum() == 1
    assert "total_mv_price_basis_mismatch" in result["diagnostics"]["600001.SH"]["remaining"]
    assert market.query_df("SELECT total_mv,reported_total_mv FROM daily_metrics WHERE code='600001.SH'").iloc[0].tolist() == [1000,990]


def test_invalid_mv_repair_uses_share_fallback(market):
    market.execute(
        "INSERT INTO daily_metrics(code,trade_date,total_mv,float_mv) VALUES ('600001.SH','2017-01-05',-1,-1)"
    )
    source = SimpleNamespace(
        get_valuation=lambda *args: pd.DataFrame(), get_share_capital=lambda *args: fact()
    )
    ing = ingest(market, source)
    ing.repair_invalid_valuation("600001.SH", window_days=None)
    assert CapitalQualityService(market).clean("capital_invalid", "600001.SH")
    assert (
        market.query_df("SELECT total_mv FROM daily_metrics WHERE code='600001.SH'").iloc[0, 0]
        == 1000
    )


def test_future_metadata_and_nonfinite_mv_are_invalid(market):
    ShareCapitalService(market).merge(fact(), "eastmoney_events")
    market.execute(
        "UPDATE stock_share_capital_daily SET total_available_date='2017-01-06' WHERE code='600001.SH'"
    )
    market.execute("UPDATE daily_metrics SET float_mv='NaN'::DOUBLE WHERE code='600001.SH'")
    rows = CapitalQualityService(market).aggregate(["600001.SH"])
    assert "capital_invalid" in rows.issue_type.tolist()
    CapitalQualityService(market).sync(["600001.SH"])
    assert not DataIntegrityReport(market).recheck_clean("capital_invalid", "600001.SH", None)


def test_scale_240000_rows_scan_and_scoped_resolution(market):
    market.execute("DELETE FROM daily_bar")
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close) SELECT 'S'||c::VARCHAR,DATE '2016-01-01'+d::INTEGER,10 FROM range(100) t(c) CROSS JOIN range(2400) u(d)"
    )
    quality = CapitalQualityService(market)
    assert quality.sync()["capital_gap"] == 100
    assert market.query_df("SELECT count(*) FROM data_quality_issue").iloc[0, 0] == 100
    rows = market.query_df(
        "SELECT code,trade_date,100 total_share,80 float_share FROM daily_bar WHERE code='S0'"
    )
    ShareCapitalService(market).merge(rows, "eastmoney_events")
    quality.sync(["S0"])
    assert quality.clean("capital_gap", "S0")
    assert (
        market.query_df("SELECT count(*) FROM data_quality_issue WHERE status='open'").iloc[0, 0]
        == 99
    )


def test_quality_model_and_cache_follow_nonempty_capital_revision(market):
    market.execute("INSERT INTO trade_calendar(trade_date,is_open) VALUES ('2017-01-05',true)")
    ShareCapitalService(market).merge(fact(), "eastmoney_daily")
    report = DataIntegrityReport(market)
    before = report.stock_quality(codes=["600001.SH"])["list"][0]
    assert before["layers"]["L2"]["ok"]
    # 源端非空市值变化：行数/空值数不变，实际修订号仍必须让概览重新计算。
    ShareCapitalService(market).merge(
        fact(total_mv=990, float_mv=792), "eastmoney_daily", reported=True
    )
    after = report.stock_quality(codes=["600001.SH"])["list"][0]
    assert after["layers"]["L2"]["ok"]
    assert after["layers"]["L2"]["capital_issues"] == 0
    assert CapitalQualityService(market).aggregate(["600001.SH"], source_only=True).issue_days.sum() == 1


def test_scoped_scan_preserves_ignored_other_stock(market):
    quality = CapitalQualityService(market)
    quality.sync()
    other = issue(market, "600002.SH")
    market.execute(
        "UPDATE data_quality_issue SET status='ignored',ignore_active=true,ignore_scope='object' WHERE id=?",
        [other],
    )
    quality.sync(["600001.SH"])
    quality.sync()
    rows = market.query_df(
        "SELECT status,ignore_active FROM data_quality_issue WHERE code='600002.SH'"
    )
    assert len(rows) == 1 and rows.iloc[0].status == "ignored" and rows.iloc[0].ignore_active


def test_nonfinite_market_value_is_repaired_from_valid_shares(market):
    ShareCapitalService(market).merge(fact(), "eastmoney_events")
    market.execute("UPDATE daily_metrics SET total_mv='Infinity'::DOUBLE,total_mv_source='legacy'")
    source = SimpleNamespace(
        get_valuation=lambda *args: pd.DataFrame(), get_share_capital=lambda *args: fact()
    )
    ingest(market, source).repair_capital_quality("600001.SH")
    assert CapitalQualityService(market).clean("capital_invalid", "600001.SH")
    assert (
        market.query_df("SELECT total_mv FROM daily_metrics WHERE code='600001.SH'").iloc[0, 0]
        == 1000
    )


def test_manual_failed_review_retries_but_partial_check_cannot_delay_history(market):
    svc = ShareCapitalService(market)
    repo = MarketRepository(market)
    lo, hi = date(2016, 1, 1), date(2026, 1, 1)
    repo.log_update("stock_share_capital_daily", "capital_review:600001.SH", lo, hi, 1, "checked")
    market.execute("UPDATE data_update_log SET updated_at=now()-INTERVAL '3 days'")
    assert svc.review_candidates(lo, hi, codes=["600001.SH"]).empty
    repo.log_update("stock_share_capital_daily", "capital_collect:600001.SH", lo, hi, 1, "failed")
    market.execute(
        "UPDATE data_update_log SET updated_at=now()-INTERVAL '2 days' WHERE status='failed'"
    )
    assert svc.review_candidates(lo, hi, codes=["600001.SH"]).code.tolist() == ["600001.SH"]
    repo.log_update("stock_share_capital_daily", "capital_collect:600001.SH", hi, hi, 0, "checked")
    assert svc.review_candidates(lo, hi, codes=["600001.SH"]).code.tolist() == ["600001.SH"]


def test_scoped_repair_expires_only_its_occurrence_ignore(market):
    quality = CapitalQualityService(market)
    quality.sync()
    market.execute(
        "UPDATE data_quality_issue SET status='ignored',ignore_active=true,ignore_scope='occurrence'"
    )
    assert quality.sync()["capital_gap"] == 0
    ShareCapitalService(market).merge(fact(), "eastmoney_events")
    quality.sync(["600001.SH"])
    rows = market.query_df("SELECT code,ignore_active FROM data_quality_issue ORDER BY code")
    assert not rows.iloc[0].ignore_active and rows.iloc[1].ignore_active
    market.execute("DELETE FROM stock_share_capital_daily WHERE code='600001.SH'")
    assert quality.sync(["600001.SH"])["capital_gap"] == 1


def test_legacy_source_issues_close_without_erasing_evidence_or_ignores(market):
    import json
    ShareCapitalService(market).merge(fact(total_mv=990,float_mv=792), "eastmoney_daily", reported=True)
    report = DataIntegrityReport(market)
    report._insert_issues([
        {"code":"600001.SH","trade_date":None,"issue_type":"capital_mismatch","detail":"原接口差异"},
        {"code":"600001.SH","trade_date":None,"issue_type":"capital_raw_invalid","detail":"原始负数"},
        {"code":"600002.SH","trade_date":None,"issue_type":"capital_raw_invalid","detail":"其他股票"},
    ])
    quality = CapitalQualityService(market)
    quality.sync(["600001.SH"])
    old = market.query_df("SELECT status,detail FROM data_quality_issue WHERE code='600001.SH'")
    assert old.status.tolist() == ["resolved", "resolved"]
    assert all("不表示源端数据已修正" in json.loads(x)["resolution_note"] for x in old.detail)
    assert market.query_df("SELECT status FROM data_quality_issue WHERE code='600002.SH'").iloc[0,0] == "open"
    assert quality.aggregate(["600001.SH"], source_only=True).issue_days.sum() == 1
    quality.sync(["600001.SH"])
    assert market.query_df("SELECT count(*) FROM data_quality_issue WHERE code='600001.SH'").iloc[0,0] == 2
    # 真正的业务计算错误仍应进入主台账。
    market.execute("UPDATE daily_metrics SET total_mv=500 WHERE code='600001.SH'")
    assert quality.sync(["600001.SH"])["capital_mismatch"] == 1


def test_source_warnings_are_visible_but_business_contract_stays_clean(market):
    from backend.services.data_verify import DataVerifier
    from backend.services.share_capital_history import ShareCapitalHistoryService
    ShareCapitalService(market).merge(fact(total_mv=990,float_mv=792), "eastmoney_daily", reported=True)
    ShareCapitalHistoryService(market).record_events("600001.SH", pd.DataFrame([{
        "END_DATE":"2016-01-01", "NOTICE_DATE":"2016-01-02", "TOTAL_SHARES":100, "LISTED_A_SHARES":-50,
    }]), "sina_events")
    quality = CapitalQualityService(market)
    assert quality.aggregate(["600001.SH"]).empty
    assert set(quality.aggregate(["600001.SH"], source_only=True).issue_type) == {"capital_source_mismatch","capital_raw_invalid"}
    verifier = DataVerifier(market, quiet=True)
    verifier.check_contract()
    warnings = [r for r in verifier._structured if r["name"].startswith("来源核验")]
    assert len(warnings) == 2
    assert all(r["status"] == "warn" and r["evidence"] for r in warnings)
    # 没有替代有效股本时必须报缺口，不能以“来源异常”豁免业务缺失。
    market.execute("UPDATE stock_share_capital_daily SET float_share=NULL WHERE code='600001.SH'")
    assert quality.sync(["600001.SH"])["capital_gap"] == 1
