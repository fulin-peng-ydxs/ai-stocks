"""T-M1-9 点时安全访问层测试（防未来函数/幸存者偏差核心安全网）。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


def _seed(c):
    init_db(c)
    # 两只股票：A 全程存活；B 在 2024-01-04 后退市
    bars = []
    dates = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
    for i, d in enumerate(dates):
        bars.append(
            {
                "code": "AAA.SH", "trade_date": d,
                "open": 10.0 + i, "high": 10.5 + i, "low": 9.5 + i, "close": 10.0 + i,
                "pre_close": (10.0 + i - 1) if i else None,
                "volume": 1000, "amount": 10000.0, "adj_factor": 2.0,
                "turnover_rate": 5.0, "is_st": False, "is_suspended": False,
                "limit_status": 0, "is_one_word": False,
            }
        )
    df = pd.DataFrame(bars)
    c.register_df("t", df)
    c.execute("INSERT INTO daily_bar SELECT * FROM t")
    c.unregister("t")
    c.execute(
        "INSERT INTO stock_basic (code, name, board, price_limit_pct) VALUES ('AAA.SH','测试A','主板',0.10)"
    )
    # 市值
    mdf = pd.DataFrame(
        [{"code": "AAA.SH", "trade_date": d, "float_mv": 1.0e10, "total_mv": 1.0e10} for d in dates]
    )
    c.register_df("m", mdf)
    c.execute("INSERT INTO daily_metrics SELECT * FROM m")
    c.unregister("m")


def test_get_bars_point_in_time_cutoff():
    """只返回 <= end_date 的行，绝不含未来。"""
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        repo = MarketRepository(c)
        df = repo.get_bars("AAA.SH", end_date=date(2024, 1, 4), adjust="")
        assert pd.Timestamp(df["trade_date"].max()).date() == date(2024, 1, 4)
        assert len(df) == 3  # 1/2, 1/3, 1/4


def test_get_bars_qfq_normalized_to_asof():
    """前复权按 as_of 当日因子归一：当日收盘的前复权价 == 原始价。"""
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        repo = MarketRepository(c)
        df = repo.get_bars("AAA.SH", end_date=date(2024, 1, 4), adjust="qfq")
        # adj_factor 恒为 2.0，归一后 == 原始（最后一行）
        raw = repo.get_bars("AAA.SH", end_date=date(2024, 1, 4), adjust="")
        assert abs(df["close"].iloc[-1] - raw["close"].iloc[-1]) < 1e-9


def test_get_bars_lookback():
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        repo = MarketRepository(c)
        df = repo.get_bars("AAA.SH", end_date=date(2024, 1, 8), lookback=2, adjust="")
        assert len(df) == 2
        got = [pd.Timestamp(d).date() for d in df["trade_date"]]
        assert got == [date(2024, 1, 5), date(2024, 1, 8)]


def test_universe_asof_excludes_xinshenggu():
    """次新剔除：min_list_days 大于已上市天数则不入池。"""
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        repo = MarketRepository(c)
        # 截至 1/4 只有 3 个交易日，min_list_days=60 → 应剔除
        u = repo.get_universe_asof(date(2024, 1, 4), filters={"min_list_days": 60})
        assert "AAA.SH" not in u
        # min_list_days=1 → 入池
        u2 = repo.get_universe_asof(date(2024, 1, 4), filters={"min_list_days": 1})
        assert "AAA.SH" in u2


def test_universe_asof_suspended_not_in_pool():
    """非交易日/无行情日不在池中（点时存活以当日有行情为据）。"""
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)
        repo = MarketRepository(c)
        # 2024-01-06 周六无行情
        u = repo.get_universe_asof(date(2024, 1, 6), filters={"min_list_days": 1})
        assert u == []


def test_get_suspension_days():
    """停牌日推导：存续期内开市但无行情的日子。"""
    with DuckDBClient(db_path=":memory:") as c:
        _seed(c)  # AAA.SH 有 1/2,1/3,1/4,1/5,1/8；日历这些都开市
        # 人为制造停牌：删掉 1/4 那天的行情
        c.execute("DELETE FROM daily_bar WHERE code='AAA.SH' AND trade_date=DATE '2024-01-04'")
        # 日历需含这些开市日
        cal = pd.DataFrame([{"trade_date": date(2024, 1, d), "is_open": d not in (6, 7)} for d in range(2, 9)])
        c.register_df("cal2", cal)
        c.execute("INSERT INTO trade_calendar SELECT * FROM cal2 ON CONFLICT (trade_date) DO NOTHING")
        c.unregister("cal2")
        repo = MarketRepository(c)
        susp = repo.get_suspension_days("AAA.SH")
        assert date(2024, 1, 4) in susp
        assert repo.is_suspended_on("AAA.SH", date(2024, 1, 4)) is True
        assert repo.is_suspended_on("AAA.SH", date(2024, 1, 3)) is False
