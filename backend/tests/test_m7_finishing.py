"""M7 收尾项测试：is_st 入库置标（T-M7-8）、adj_jump 全市场扫描（T-M7-6）。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.services.data_report import DataIntegrityReport
from backend.services.ingest import IngestionService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_is_st_by_name():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute("INSERT INTO stock_basic (code, name) VALUES "
                  "('000001.SZ','平安银行'),('000638.SZ','*ST万方'),('600519.SH','贵州茅台')")
        svc = IngestionService.__new__(IngestionService)  # 跳过网络初始化
        from backend.storage.repository import MarketRepository
        svc.repo = MarketRepository(c)
        assert svc._is_st_by_name("000638.SZ") is True
        assert svc._is_st_by_name("000001.SZ") is False
        assert svc._is_st_by_name("600519.SH") is False


def test_scan_adj_jump_flags_gross_jump():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        # 一只正常票 + 一只在某日前复权价暴跳 80%（复权口径异常）
        rows = []
        days = [date(2024, 1, x) for x in (2, 3, 4, 5, 8, 9)]
        for i, d in enumerate(days):
            rows.append({"code": "OK.SH", "trade_date": d, "open": 10, "high": 10, "low": 10,
                         "close": 10.0 + i * 0.1, "pre_close": 10.0, "volume": 1, "amount": 1.0,
                         "adj_factor": 1.0, "turnover_rate": 1.0, "is_st": False,
                         "is_suspended": False, "limit_status": 0, "is_one_word": False})
        # BAD：第6个交易日 adj_factor 异常致前复权价跳变；前5个交易日属上市初期豁免。
        af = [1.0, 1.0, 1.0, 1.0, 1.0, 2.0]
        for i, d in enumerate(days):
            rows.append({"code": "BAD.SH", "trade_date": d, "open": 10, "high": 10, "low": 10,
                         "close": 10.0, "pre_close": 10.0, "volume": 1, "amount": 1.0,
                         "adj_factor": af[i], "turnover_rate": 1.0, "is_st": False,
                         "is_suspended": False, "limit_status": 0, "is_one_word": False})
        c.register_df("t", pd.DataFrame(rows))
        c.execute("INSERT INTO daily_bar BY NAME SELECT * FROM t")
        c.unregister("t")
        n = DataIntegrityReport(c)._scan_adj_jump(threshold=0.5)
        assert n >= 1
        issues = c.query_df("SELECT DISTINCT code FROM data_quality_issue WHERE issue_type='adj_jump'")
        assert "BAD.SH" in issues["code"].tolist()
        assert "OK.SH" not in issues["code"].tolist()


def test_scan_adj_jump_skips_listing_and_long_gap_but_keeps_delisted_history():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute("INSERT INTO stock_basic (code, name, list_date, delist_date) VALUES "
                  "('OLD.SH','退市样本', DATE '2020-01-02', DATE '2024-02-01'),"
                  "('NEW.SH','新股样本', DATE '2024-01-02', NULL),"
                  "('GAP.SH','复牌样本', DATE '2020-01-02', NULL)")
        rows = []
        for code, days in {
            "OLD.SH": [date(2024, 1, x) for x in (2, 3, 4, 5, 8, 9)],
            "NEW.SH": [date(2024, 1, x) for x in (2, 3)],
            "GAP.SH": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4),
                       date(2024, 1, 5), date(2024, 1, 8), date(2024, 3, 1)],
        }.items():
            af = [1.0] * (len(days) - 1) + [2.0]
            for i, d in enumerate(days):
                rows.append({"code": code, "trade_date": d, "open": 10, "high": 10, "low": 10,
                             "close": 10.0, "pre_close": 10.0, "volume": 1, "amount": 1.0,
                             "adj_factor": af[i], "turnover_rate": 1.0, "is_st": False,
                             "is_suspended": False, "limit_status": 0, "is_one_word": False})
        c.register_df("t", pd.DataFrame(rows))
        c.execute("INSERT INTO daily_bar BY NAME SELECT * FROM t")
        c.unregister("t")
        n = DataIntegrityReport(c)._scan_adj_jump(threshold=0.5)
        assert n == 1
        issues = c.query_df("SELECT DISTINCT code FROM data_quality_issue WHERE issue_type='adj_jump'")
        assert issues["code"].tolist() == ["OLD.SH"]
