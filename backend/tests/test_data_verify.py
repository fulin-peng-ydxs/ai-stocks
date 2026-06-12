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
