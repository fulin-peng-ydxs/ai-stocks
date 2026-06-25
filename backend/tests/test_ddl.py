"""M1 DDL 测试：建表幂等、表齐全、抽象接口约束。"""

from __future__ import annotations

import pytest

from backend.datasource.base import DataSource, with_retry
from backend.storage.ddl import (
    M1_TABLES,
    M2_TABLES,
    M3_TABLES,
    M4_TABLES,
    M5_TABLES,
    M6_TABLES,
    M28_TABLES,
    M_TRAINING_TABLES,
    init_db,
    list_tables,
)
from backend.storage.duckdb_client import DuckDBClient


def test_init_db_creates_all_tables():
    with DuckDBClient(db_path=":memory:") as client:
        created = init_db(client)
        expected = {
            **M1_TABLES,
            **M2_TABLES,
            **M3_TABLES,
            **M4_TABLES,
            **M5_TABLES,
            **M6_TABLES,
            **M28_TABLES,
            **M_TRAINING_TABLES,
        }
        assert set(created) == set(expected.keys())
        tables = list_tables(client)
        for name in expected:
            assert name in tables


def test_init_db_idempotent():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        # 再次执行不应报错（IF NOT EXISTS）
        init_db(client)
        assert "daily_bar" in list_tables(client)


def test_daily_bar_pk_upsert():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        client.execute(
            "INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2024-01-02', 10.0)"
        )
        # 同主键 upsert 覆盖
        client.execute(
            "INSERT INTO daily_bar (code, trade_date, close) VALUES ('600000.SH', DATE '2024-01-02', 11.0) "
            "ON CONFLICT (code, trade_date) DO UPDATE SET close = EXCLUDED.close"
        )
        df = client.query_df("SELECT close FROM daily_bar")
        assert len(df) == 1
        assert df.iloc[0]["close"] == 11.0


def test_datasource_is_abstract():
    # 抽象类不可直接实例化
    with pytest.raises(TypeError):
        DataSource()  # type: ignore[abstract]


def test_with_retry_eventually_raises():
    calls = {"n": 0}

    @with_retry(max_retries=2, backoff_sec=0.01)
    def always_fail():
        calls["n"] += 1
        raise ValueError("boom")

    from backend.common.exceptions import DataSourceError

    with pytest.raises(DataSourceError):
        always_fail()
    assert calls["n"] == 2


def test_with_retry_honors_instance_config():
    """实例属性 _max_retries/_retry_backoff_sec 覆盖装饰器入参——前端改重试配置即生效。"""
    from backend.common.exceptions import DataSourceError
    calls = {"n": 0}

    class Src:
        _max_retries = 2          # 实例配置=2，应覆盖装饰器的 5
        _retry_backoff_sec = 0.01

        @with_retry(max_retries=5, backoff_sec=9)
        def fetch(self):
            calls["n"] += 1
            raise ValueError("boom")

    with pytest.raises(DataSourceError):
        Src().fetch()
    assert calls["n"] == 2        # 用实例的 2 次，而非装饰器导入期的 5 次


def test_baostock_code_conversion():
    from backend.datasource.baostock_source import bs_to_full, full_to_bs

    assert bs_to_full("sh.600000") == "600000.SH"
    assert bs_to_full("sz.000001") == "000001.SZ"
    assert full_to_bs("600000.SH") == "sh.600000"
    assert full_to_bs("000001.SZ") == "sz.000001"


def test_classify_board_covers_new_ranges():
    from backend.datasource.akshare_source import classify_board, to_full_code

    # 创业板新号段 302/303 应判为深市创业板（修复 302132 误判）
    assert classify_board("302132") == ("SZ", "创业板", 0.20)
    assert classify_board("301001") == ("SZ", "创业板", 0.20)
    assert classify_board("300001") == ("SZ", "创业板", 0.20)
    assert to_full_code("302132") == "302132.SZ"
    # 其余号段
    assert classify_board("600000")[0] == "SH"
    assert classify_board("000001") == ("SZ", "主板", 0.10)
    assert classify_board("688981") == ("SH", "科创板", 0.20)


def test_index_to_sina_symbol():
    from backend.datasource.akshare_source import index_to_sina_symbol

    assert index_to_sina_symbol("000905.SH") == "sh000905"
    assert index_to_sina_symbol("000300.SH") == "sh000300"
    assert index_to_sina_symbol("399001.SZ") == "sz399001"
    assert index_to_sina_symbol("000905") == "sh000905"  # 兼容裸代码


def test_source_capabilities_and_contract():
    """能力声明 + 契约完整性：缺能力的方法应明确报错，而非隐式硬绑定。"""
    import pytest

    from backend.datasource.akshare_source import AKShareSource
    from backend.datasource.baostock_source import BaostockSource

    ak, bao = AKShareSource(), BaostockSource()
    # 能力声明正确
    assert ak.supports("valuation") and not ak.supports("industry")
    assert bao.supports("industry") and bao.supports("delisted") and not bao.supports("valuation")
    # 契约：不支持的能力调用 → NotImplementedError（不再静默/崩在别处）
    from datetime import date

    with pytest.raises(NotImplementedError):
        bao.get_valuation("600000.SH", date(2024, 1, 1), date(2024, 1, 2))
    with pytest.raises(NotImplementedError):
        ak.get_industry()
