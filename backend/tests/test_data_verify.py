"""数据契约完整性检查测试：缺失必填字段应被 check_contract 抓出。"""

from __future__ import annotations

from backend.services.data_verify import DataVerifier
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


def _insert_bar(c, code, td, close, adj_factor=None, adj_clean=None):
    c.execute(
        "INSERT INTO daily_bar (code, trade_date, close, adj_factor, adj_factor_clean) "
        "VALUES (?, ?, ?, ?, ?)",
        [code, td, close, adj_factor, adj_clean])


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
