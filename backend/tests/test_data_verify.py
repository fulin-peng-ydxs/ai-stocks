"""数据契约完整性检查测试：缺失必填字段应被 check_contract 抓出。"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.services.data_report import DataIntegrityReport
from backend.services.data_verify import DataVerifier
from backend.services.stock_st_status import StockSTStatusFact, StockSTStatusService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_contract_catches_missing_industry():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        # 在市股但 industry 为空 → 契约应判 FAIL
        c.execute(
            "INSERT INTO stock_basic (code,name,exchange,board,list_date,price_limit_pct) "
            "VALUES ('600000.SH','浦发','SH','主板',DATE '2000-01-01',0.10)"
        )
        v = DataVerifier(c)
        v.check_contract()
        industry = [(n, ok) for (n, ok, _) in v.results if "行业" in n]
        assert industry and industry[0][1] is False  # 行业缺失被抓出


def test_contract_passes_when_complete():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO stock_basic (code,name,exchange,board,list_date,price_limit_pct,industry) "
            "VALUES ('600000.SH','浦发','SH','主板',DATE '2000-01-01',0.10,'J66')"
        )
        v = DataVerifier(c)
        v.check_contract()
        # 基础字段项全部 PASS（无 daily_bar 数据时日线项也为 0 缺失）
        base = [ok for (n, ok, _) in v.results if "基础" in n or "在市股·行业" in n]
        assert all(base)


def test_contract_catches_missing_list_date_and_pending_ladder_invalidation():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO stock_basic (code,name,exchange,board,list_date,price_limit_pct,industry) "
            "VALUES ('600001.SH','未知上市日','SH','主板',NULL,0.10,'J66')"
        )
        c.execute(
            "INSERT INTO limit_ladder_invalidation_outbox "
            "(event_id,reason,status,attempt_count,created_at,updated_at) "
            "VALUES ('pending-1','test','pending',0,current_timestamp,current_timestamp)"
        )
        verifier = DataVerifier(c)
        verifier.check_contract()
        checks = {name: ok for name, ok, _ in verifier.results}
        assert checks["基础·上市日 无缺失"] is False
        assert checks["连板天梯·失效 outbox 无积压"] is False


def test_market_value_contract_and_report_cover_old_history_rows():
    """全量体检不得因缺口不在近端窗口而漏掉旧年份的总市值空值。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO stock_basic "
            "(code,name,exchange,board,list_date,price_limit_pct,industry,total_share) "
            "VALUES ('600000.SH','浦发','SH','主板',DATE '2000-01-01',0.10,'J66',1000000)"
        )
        c.execute(
            "INSERT INTO daily_bar (code,trade_date,open,high,low,close,volume,amount,turnover_rate) "
            "VALUES ('600000.SH',DATE '2021-01-04',10,10,10,10,100,1000,1),"
            "('600000.SH',DATE '2026-01-05',11,11,11,11,100,1100,1)"
        )
        c.execute(
            "INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) VALUES "
            "('600000.SH',DATE '2021-01-04',800000000,NULL),"
            "('600000.SH',DATE '2026-01-05',880000000,1100000000)"
        )

        verifier = DataVerifier(c, quiet=True)
        verifier.check_contract()
        checks = {name: ok for name, ok, _ in verifier.results}
        critical = DataIntegrityReport(c).null_critical()

        assert checks["在市股·总市值无缺失"] is False
        assert critical["null_total_mv"] == 1
        assert critical["null_float_mv"] == 0


def test_market_value_contract_rejects_nonpositive_and_inverted_values():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO stock_basic "
            "(code,name,exchange,board,list_date,price_limit_pct,industry,total_share) "
            "VALUES ('600000.SH','浦发','SH','主板',DATE '2000-01-01',0.10,'J66',1000000)"
        )
        c.execute(
            "INSERT INTO daily_metrics (code,trade_date,float_mv,total_mv) VALUES "
            "('600000.SH',DATE '2020-01-02',800,-1),"
            "('600000.SH',DATE '2021-01-04',900,800),"
            "('600000.SH',DATE '2022-01-04',800,799.9999999999)"
        )

        verifier = DataVerifier(c, quiet=True)
        verifier.check_contract()
        checks = {name: ok for name, ok, _ in verifier.results}
        critical = DataIntegrityReport(c).null_critical()

        assert checks["在市股·市值均为正数"] is False
        assert checks["在市股·总市值不低于流通市值（万分之一容差）"] is False
        assert critical["nonpositive_mv"] == 1
        assert critical["inverted_mv"] == 1
        inverted_check = next(
            item
            for item in verifier._structured
            if item["name"] == "在市股·总市值不低于流通市值（万分之一容差）"
        )
        assert inverted_check["detail"] == "全历史异常 1 行；近90交易日台账范围 0 行"
        assert "结构体检覆盖库内全部年份" in inverted_check["help"]


def test_structure_warns_when_valid_ladder_uses_old_st_version():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        trade_date = "2026-01-05"
        st_service = StockSTStatusService(c)
        fact = StockSTStatusFact(
            code="600001.SH",
            trade_date=date.fromisoformat(trade_date),
            status=PointInTimeSTStatus(
                is_st=False,
                source="test_fixture",
                source_ref="initial",
                quality=STStatusQuality.ACCURATE,
            ),
        )
        st_service.upsert_facts([fact], change_reason="seed")
        old_version = st_service.input_version_through(fact.trade_date)
        c.execute(
            "INSERT INTO limit_ladder_snapshot_state "
            "(trade_date,status,current_snapshot_id,rule_version,st_input_version,updated_at) "
            "VALUES (?, 'valid', 'snap-old', 'v1', ?, current_timestamp)",
            [fact.trade_date, old_version],
        )
        st_service.upsert_facts(
            [
                StockSTStatusFact(
                    code=fact.code,
                    trade_date=fact.trade_date,
                    status=PointInTimeSTStatus(
                        is_st=True,
                        source="test_fixture",
                        source_ref="corrected",
                        quality=STStatusQuality.ACCURATE,
                    ),
                )
            ],
            change_reason="correction",
        )

        verifier = DataVerifier(c, quiet=True)
        verifier.check_structure()
        warning = next(
            item for item in verifier._structured if item["name"] == "连板天梯快照待 ST 版本自愈"
        )
        assert warning["status"] == "warn"
        assert "1 个日期" in warning["detail"]
        assert warning["evidence"][0]["rows"][0]["trade_date"] == trade_date
        assert warning["evidence"][0]["rows"][0]["st_input_version"] == old_version


def _insert_bar(c, code, td, close, adj_factor=None, adj_clean=None):
    c.execute(
        "INSERT INTO daily_bar (code, trade_date, close, adj_factor, adj_factor_clean) "
        "VALUES (?, ?, ?, ?, ?)",
        [code, td, close, adj_factor, adj_clean],
    )


def test_adj_factor_pass_when_clean_nonnull_source_null():
    """源 adj_factor=NULL 但 adj_factor_clean 非空 → 复权因子项 PASS。

    回归 2026-08-15：001331.SZ 除权日源因子缺失，clean 去抖已回填前段因子。
    业务读因子一律 COALESCE(adj_factor_clean, adj_factor)，核查器同口径不应误报。
    """
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _insert_bar(c, "001331.SZ", "2026-06-26", 69.78, adj_factor=None, adj_clean=2.4007)
        v = DataVerifier(c)
        v.check_prices()
        v.check_contract()
        factor = [(n, ok) for (n, ok, _) in v.results if "复权因子" in n]
        assert len(factor) == 2
        assert all(ok for _, ok in factor)  # B组"为正" + D组"无缺失"都 PASS


def test_adj_factor_fail_when_both_null():
    """源因子与 clean 均 NULL → 复权因子项 FAIL（真实缺失应被抓出）。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _insert_bar(c, "600000.SH", "2026-08-14", 10.0, adj_factor=None, adj_clean=None)
        v = DataVerifier(c)
        v.check_prices()
        v.check_contract()
        factor = [(n, ok) for (n, ok, _) in v.results if "复权因子" in n]
        assert len(factor) == 2
        assert all(not ok for _, ok in factor)


# ── E 组：板块数据 ──


def _seed_board(c, *, bar: bool = True, member: bool = True, fund: bool = True):
    """最小一致板块数据：字典标记、成分、指数、资金流四向对齐。"""
    c.execute(
        "INSERT INTO board_dict (board_code, name, board_type, has_members, has_bar, has_fund_flow) "
        "VALUES ('301558', '测试概念', 'concept', ?, ?, ?)",
        [member, bar, fund],
    )
    c.execute(
        "INSERT INTO stock_basic (code,name,exchange,board,list_date,price_limit_pct) "
        "VALUES ('600000.SH','浦发','SH','主板',DATE '2000-01-01',0.10)"
    )
    c.execute("INSERT INTO trade_calendar (trade_date, is_open) VALUES (DATE '2026-08-21', TRUE)")
    if member:
        c.execute("INSERT INTO board_member (board_code, code) VALUES ('301558', '600000.SH')")
    if bar:
        c.execute(
            "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
            "VALUES ('301558', DATE '2026-08-21', 100.0, 105.0, 99.0, 103.0, 1000.0, 2000.0)"
        )
    if fund:
        c.execute(
            "INSERT INTO board_fund_flow (board_code, snapshot_date, period, inflow, outflow, net_inflow) "
            "VALUES ('301558', DATE '2026-08-21', '即时', 10.0, 8.0, 2.0)"
        )


def test_board_checks_pass_on_consistent_data():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_board(c)
        v = DataVerifier(c)
        v.check_board()
        assert v.fails() == []


def test_board_structure_exposes_stale_history_and_missing_same_day_fund(market):
    """旧历史仍合法，但不能掩盖一季报类板块的当前不可用状态。"""
    _seed_board(market)
    market.execute("UPDATE board_dict SET name='一季报预增' WHERE board_code='301558'")
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close) VALUES ('600000.SH',DATE '2026-10-13',10)"
    )
    for period in ("即时", "3日", "5日", "10日"):
        market.execute(
            "INSERT INTO board_fund_flow (board_code,snapshot_date,period,net_inflow) "
            "VALUES ('301558',DATE '2026-10-13',?,1)",
            [period],
        )
    market.execute(
        "INSERT INTO board_fund_flow (board_code,snapshot_date,period,net_inflow) "
        "VALUES ('301558',DATE '2026-10-14','20日',1)"
    )
    report = DataIntegrityReport(market)
    coverage = report.board_coverage_issues()
    assert len(coverage["index_gaps"]) == len(coverage["fund_missing"]) == 1
    verifier = DataVerifier(market, quiet=True)
    verifier.check_board()
    warnings = {row["name"]: row for row in verifier._structured if row["status"] == "warn"}
    assert warnings["板块指数覆盖至最新行情日"]["items"][0]["name"] == "一季报预增"
    assert warnings["板块资金流目标日五周期齐全"]["items"][0]["missing_periods"] == ["20日"]
    assert verifier.fails() == []  # 数据结构合法，覆盖风险以提醒展示。
    assert market.query_df("SELECT * FROM data_quality_issue").empty  # 体检只读。
    counts = report.scan_board_quality()
    assert counts["index_gap"] == counts["fund_missing"] == 1

    # 补齐目标日后提醒消失，未来快照不能代替当前快照。
    market.execute(
        "INSERT INTO board_bar (board_code,trade_date,open,high,low,close,volume,amount) "
        "VALUES ('301558',DATE '2026-10-13',10,10,10,10,100,1000)"
    )
    market.execute("INSERT INTO trade_calendar VALUES (DATE '2026-10-13',TRUE)")
    market.execute(
        "INSERT INTO board_fund_flow (board_code,snapshot_date,period,net_inflow) "
        "VALUES ('301558',DATE '2026-10-13','20日',1)"
    )
    verifier = DataVerifier(market, quiet=True)
    verifier.check_board()
    assert not any(row["status"] == "warn" for row in verifier._structured)


def test_board_coverage_aggregation_at_market_scale(market):
    """600 个板块 × 1000 日，验证聚合入口及五周期缺口而非逐板块 SQL。"""
    market.execute(
        "INSERT INTO board_dict (board_code,name,board_type,has_bar,has_members) "
        "SELECT 'B'||i::VARCHAR,'板块'||i::VARCHAR,'concept',TRUE,TRUE FROM range(600) t(i)"
    )
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close) VALUES ('MARKET',DATE '2026-10-13',10)"
    )
    market.execute(
        "INSERT INTO board_bar (board_code,trade_date,close) "
        "SELECT b.board_code,DATE '2026-10-13'-d::INTEGER,10 "
        "FROM board_dict b CROSS JOIN range(1000) t(d) "
        "WHERE b.board_code<>'B0' OR d>0"
    )
    market.execute(
        "INSERT INTO board_fund_flow (board_code,snapshot_date,period,net_inflow) "
        "SELECT b.board_code,DATE '2026-10-13',p.period,1 FROM board_dict b "
        "CROSS JOIN (VALUES ('即时'),('3日'),('5日'),('10日'),('20日')) p(period) "
        "WHERE b.board_code<>'B0' OR p.period<>'20日'"
    )
    result = DataIntegrityReport(market).board_coverage_issues()
    assert [row["code"] for row in result["index_gaps"]] == ["B0"]
    assert [row["code"] for row in result["fund_missing"]] == ["B0"]
    assert "20日" in result["fund_missing"][0]["detail"]


def test_board_checkup_items_keep_disposition_and_ignore_scope_read_only(market):
    """整体忽略跨日期生效，本次忽略只对原日期生效，体检不结束忽略规则。"""
    _seed_board(market)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close) VALUES ('600000.SH','2026-10-13',10)"
    )
    market.execute(
        "INSERT INTO data_quality_issue "
        "(id,code,trade_date,issue_type,status,ignore_scope,ignore_active) VALUES "
        "(1,'301558','2026-10-09','board_fund_missing','ignored','object',TRUE),"
        "(2,'301558','2026-10-09','board_index_gap','ignored','occurrence',TRUE),"
        "(3,'301558','2026-10-13','board_index_gap','fixing',NULL,FALSE)"
    )
    verifier = DataVerifier(market, quiet=True)
    verifier.check_board()
    warnings = {x["name"]: x for x in verifier._structured if "items" in x}
    funds = warnings["板块资金流目标日五周期齐全"]
    assert funds["detail"] == "0 个待处理 · 1 个已忽略"
    assert funds["items"][0]["status"] == "ignored"
    assert warnings["板块指数覆盖至最新行情日"]["items"][0]["status"] == "fixing"
    assert market.query_df("SELECT ignore_active FROM data_quality_issue WHERE id=2").iloc[0, 0]
    # 覆盖最终报告序列化，不能只在内部 _structured 中保留明细。
    payload = DataVerifier(market, quiet=True).run_structured()
    checks = [check for group in payload["groups"] for check in group["checks"]]
    funds = next(x for x in checks if x["name"] == "板块资金流目标日五周期齐全")
    assert funds["items"][0]["status"] == "ignored"


def test_board_orphan_bar_fails():
    """board_bar 出现字典外板块 → 孤儿项应判 FAIL。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_board(c)
        c.execute(
            "INSERT INTO board_bar (board_code, trade_date, open, high, low, close, volume, amount) "
            "VALUES ('309999', DATE '2026-08-21', 1.0, 1.0, 1.0, 1.0, 0.0, 0.0)"
        )
        v = DataVerifier(c)
        v.check_board()
        orphan = [(n, ok) for (n, ok, _) in v.results if "板块指数无孤儿" in n]
        assert orphan and orphan[0][1] is False


def test_board_flag_mismatch_fails():
    """有指数数据但 has_bar 未标记 → 标记一致性项应判 FAIL。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_board(c)
        c.execute("UPDATE board_dict SET has_bar = FALSE WHERE board_code = '301558'")
        v = DataVerifier(c)
        v.check_board()
        flag = [(n, ok) for (n, ok, _) in v.results if "指数能力标记" in n]
        assert flag and flag[0][1] is False


def test_board_bj_member_exempt():
    """北交所成分不在 stock_basic 属既定宇宙边界，不应判 FAIL。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        _seed_board(c)
        c.execute("INSERT INTO board_member (board_code, code) VALUES ('301558', '920001.BJ')")
        v = DataVerifier(c)
        v.check_board()
        member = [(n, ok) for (n, ok, _) in v.results if "成分股（沪深）" in n]
        assert member and member[0][1] is True


def test_all_local_failures_and_warnings_have_detail_or_explicit_state(market):
    """从最终报告检查所有组，不能只在内部结果里补明细。"""
    _seed_board(market)
    market.execute("UPDATE stock_basic SET industry=NULL, total_share=NULL")
    market.execute("INSERT INTO board_member (board_code,code) VALUES ('301558','600099.SH')")
    report = DataVerifier(market, quiet=True).run_structured()
    checks = [check for group in report["groups"] for check in group["checks"]]
    for check in checks:
        assert "evidence" in check
        if check["status"] != "pass":
            assert check["help"], check["name"]
            assert (
                check.get("items")
                or check["evidence"]
                or check["name"]
                in (
                    "板块指数覆盖至最新行情日",
                    "板块资金流目标日五周期齐全",
                    "连板天梯 ST 输入版本暂不可核验",
                )
            ), check["name"]
    industry = next(check for check in checks if check["name"] == "在市股·行业 无缺失")
    assert industry["evidence"][0]["rows"] == [{"code": "600000.SH", "industry": "缺失"}]
    missing = next(check for check in checks if check["name"] == "成分股（沪深）均有基础信息")
    assert missing["evidence"][0]["rows"] == [{"code": "600099.SH"}]
    calendar = next(check for check in checks if check["name"] == "交易日历已覆盖下一自然年")
    assert calendar["evidence"][0]["rows"][0]["最远开市日"] == "2026-08-21"
    json.dumps(report, allow_nan=False)
    assert market.query_df("SELECT * FROM data_quality_issue").empty


def test_detail_limit_uses_full_count_and_filters_at_scale(market):
    """十万异常成分通过真实体检入口聚合，样例有界且北交所豁免保持不变。"""
    market.execute(
        "INSERT INTO board_member (board_code,code) "
        "SELECT 'UNKNOWN',i::VARCHAR||'.SH' FROM range(100000) t(i)"
    )
    market.execute("INSERT INTO board_member (board_code,code) VALUES ('UNKNOWN','920001.BJ')")
    verifier = DataVerifier(market, quiet=True)
    verifier.check_board()
    check = next(x for x in verifier._structured if x["name"] == "成分股（沪深）均有基础信息")
    evidence = check["evidence"][0]
    assert evidence["total"] == 100000
    assert len(evidence["rows"]) == evidence["limit"] == 20
    assert all(row["code"].endswith(".SH") for row in evidence["rows"])
    assert market.query_df("SELECT * FROM data_quality_issue").empty


def test_compound_check_keeps_both_evidence_conditions(market):
    _seed_board(market)
    market.execute("UPDATE board_dict SET has_bar=FALSE")
    market.execute(
        "INSERT INTO board_dict (board_code,name,board_type,has_bar) "
        "VALUES ('301559','空指数','concept',TRUE)"
    )
    verifier = DataVerifier(market, quiet=True)
    verifier.check_board()
    check = next(x for x in verifier._structured if x["name"] == "指数能力标记与实际数据一致")
    assert [x["label"] for x in check["evidence"]] == ["有标记无数据", "有数据无标记"]
    assert check["evidence"][0]["rows"][0]["board_code"] == "301559"
    assert check["evidence"][1]["rows"][0]["board_code"] == "301558"


def test_cross_validation_has_price_detail_and_no_common_dates_fail(market, monkeypatch):
    from backend.datasource.akshare_source import AKShareSource

    _insert_bar(market, "600000.SH", "2026-01-05", 10, adj_clean=1)
    fresh = pd.DataFrame([{"date": "2026-01-05", "close": 11}])
    monkeypatch.setattr(AKShareSource, "_sina_daily", lambda *args: fresh.copy())
    verifier = DataVerifier(market, quiet=True)
    verifier.cross_validate(codes=["600000.SH"])
    check = verifier._structured[-1]
    assert check["status"] == "fail"
    assert check["evidence"][0]["rows"][0]["实时原价"] == "11"
    fresh["date"] = "2026-01-06"
    verifier.cross_validate(codes=["600000.SH"])
    check = verifier._structured[-1]
    assert check["status"] == "fail"
    assert check["detail"] == "本地与实时源无共同交易日"
    assert check["evidence"][0]["rows"][0]["code"] == "600000.SH"
