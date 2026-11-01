"""质检 SQL 下推的业务边界与代表性规模回归。"""

from datetime import date

import pytest

from backend.services.data_report import DataIntegrityReport
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.fixture
def market():
    with DuckDBClient(":memory:") as client:
        init_db(client)
        yield client


def test_adj_jump_keeps_listing_lag_clean_factor_and_ignore_boundaries(market):
    market.execute(
        "INSERT INTO stock_basic(code,name,list_date,delist_date) VALUES "
        "('NEW.SH','新股','2024-01-01','2024-01-08'),"
        "('OLD.SH','老股','2010-01-01',NULL),"
        "('RET.SH','退市股','2010-01-01',NULL),"
        "('ZERO.SH','零基数','2010-01-01',NULL)"
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,adj_factor,adj_factor_clean) VALUES "
        "('NEW.SH','2024-01-01',10,1,NULL),('NEW.SH','2024-01-02',10,2,NULL),"
        "('NEW.SH','2024-01-03',10,2,NULL),('NEW.SH','2024-01-04',10,2,NULL),"
        "('NEW.SH','2024-01-05',10,2,NULL),('NEW.SH','2024-01-06',10,4,NULL),"
        "('NEW.SH','2024-01-07',10,8,4),('NEW.SH','2024-01-08',10,8,NULL),"
        "('OLD.SH','2024-01-01',10,1,NULL),('OLD.SH','2024-01-02',10,2,NULL),"
        "('OLD.SH','2024-01-03',10,2,1),('OLD.SH','2024-01-04',10,'NaN',NULL),"
        "('OLD.SH','2024-01-05',10,NULL,NULL),('OLD.SH','2024-01-06',10,4,2),"
        "('OLD.SH','2024-01-07',10,4,NULL),"
        "('OLD.SH','2024-02-07',10,8,NULL),"
        "('RET.SH','2024-01-01',10,1,NULL),('RET.SH','2024-01-12',10,2,NULL),"
        "('ZERO.SH','2024-01-01',10,1,NULL),('ZERO.SH','2024-01-02',10,0,NULL)"
    )
    report = DataIntegrityReport(market)
    rows = report._collect_adj_jump_issues()
    assert {(r["code"], str(r["trade_date"])[:10]) for r in rows} == {
        ("NEW.SH", "2024-01-06"),
        ("OLD.SH", "2024-01-02"),
        ("OLD.SH", "2024-01-07"),
    }
    scoped = report._collect_adj_jump_issues(
        codes=["OLD.SH"],
        ignored_exact={("OLD.SH", "adj_jump", "2024-01-02")},
    )
    assert len(scoped) == 1
    assert str(scoped[0]["trade_date"])[:10] == "2024-01-07"
    # 01-05 缺因子不再冒充 1，于是 01-06 不产生伪跳变；01-07 的真实跳变仍被检出。
    assert not report.recheck_clean('adj_jump', 'OLD.SH', None)
    assert report._collect_adj_jump_issues(codes=[]) == []


def test_abnormal_change_preserves_cent_tolerance_and_accurate_st_cutoff(market):
    market.execute(
        "INSERT INTO stock_basic(code,name,list_date,price_limit_pct) VALUES "
        "('600001.SH','ST股票','2010-01-01',0.1)"
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close) VALUES "
        "('600001.SH','2026-07-01',10.51,10),"
        "('600001.SH','2026-07-02',10.52,10),"
        "('600001.SH','2026-07-03',10.52,10),"
        "('600001.SH','2026-07-06',10.52,10),"
        "('600001.SH','2026-07-07',10.52,10)"
    )
    market.execute(
        "INSERT INTO stock_st_status_daily(code,trade_date,is_st,quality,source,captured_at,updated_at) "
        "SELECT code,trade_date,true,CASE WHEN trade_date='2026-07-03' "
        "THEN 'approximate' ELSE 'accurate' END,'test',now(),now() FROM daily_bar"
    )
    # 明确无涨跌幅限制日不参与普通涨跌停越界检查。
    market.execute("UPDATE daily_bar SET close=20 WHERE trade_date='2026-07-07'")
    market.execute(
        "INSERT INTO stock_special_trading_day "
        "(code,trade_date,event_type,active,announcement_date,source_ref,note,task_id,updated_at) "
        "VALUES ('600001.SH','2026-07-07','resumption_no_limit',true,"
        "'2026-07-06','test','核验样本','test',now())"
    )
    rows = DataIntegrityReport(market)._collect_abnormal_change_issues()
    assert len(rows) == 1
    assert str(rows[0]["trade_date"])[:10] == "2026-07-02"
    assert "10.52" in rows[0]["detail"]
    assert DataIntegrityReport(market)._collect_abnormal_change_issues(codes=[]) == []


def test_large_scan_only_returns_candidates_and_anomalies(market, monkeypatch):
    """16 万行覆盖扫描、窗口、结果传输；不以仅 SQL 文本或计时断言代替规模验证。"""
    market.execute(
        "INSERT INTO stock_basic(code,name,list_date,price_limit_pct) "
        "SELECT printf('%06d.SH',i),'规模样本','2010-01-01',0.1 FROM range(80) t(i)"
    )
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,close,pre_close,adj_factor) "
        "SELECT code,DATE '2017-01-01'+CAST(d AS INTEGER),"
        "CASE WHEN d=600 THEN 12 ELSE 10 END,10,CASE WHEN d>=500 THEN 2 ELSE 1 END "
        "FROM stock_basic CROSS JOIN range(2000) t(d)"
    )
    transferred = []
    query = market.query_df

    def track(sql, params=None):
        result = query(sql, params)
        transferred.append(len(result))
        return result

    monkeypatch.setattr(market, "query_df", track)
    report = DataIntegrityReport(market)
    abnormal = report._collect_abnormal_change_issues()
    jumps = report._collect_adj_jump_issues()
    assert len(abnormal) == len(jumps) == 80
    assert set(transferred) == {80}
    assert {r["trade_date"].date() for r in jumps} == {date(2018, 5, 16)}
