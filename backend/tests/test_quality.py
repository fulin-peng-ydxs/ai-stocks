"""T-M1-8 数据质检测试：涨跌停标记、一字板、ST 限制、异常检测。"""

from __future__ import annotations

import pandas as pd

from backend.dataquality.checker import QualityChecker, add_markers, limit_pct_for
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _bar(open_, high, low, close, pre_close):
    return pd.DataFrame(
        [{"open": open_, "high": high, "low": low, "close": close, "pre_close": pre_close}]
    )


def test_limit_pct_st_override():
    assert limit_pct_for(0.10, is_st=False) == 0.10
    assert limit_pct_for(0.20, is_st=False) == 0.20
    assert limit_pct_for(0.10, is_st=True) == 0.05  # ST 一律 5%


def test_limit_up_main_board():
    # 主板 10%：pre_close 10.00 -> 涨停 11.00
    df = add_markers(_bar(10.5, 11.0, 10.4, 11.0, 10.0), 0.10, False)
    assert df["limit_status"].iloc[0] == 1
    assert not df["is_one_word"].iloc[0]  # 非一字（开!=收）


def test_one_word_limit():
    # 一字涨停：开=高=低=收=11.00，pre=10.00
    df = add_markers(_bar(11.0, 11.0, 11.0, 11.0, 10.0), 0.10, False)
    assert df["limit_status"].iloc[0] == 1
    assert df["is_one_word"].iloc[0]


def test_limit_down_star_board():
    # 科创 20%：pre 10.00 -> 跌停 8.00
    df = add_markers(_bar(8.5, 8.6, 8.0, 8.0, 10.0), 0.20, False)
    assert df["limit_status"].iloc[0] == -1


def test_no_limit_normal_day():
    df = add_markers(_bar(10.0, 10.3, 9.9, 10.2, 10.0), 0.10, False)
    assert df["limit_status"].iloc[0] == 0
    assert not df["is_one_word"].iloc[0]


def test_first_day_no_pre_close():
    df = add_markers(_bar(10.0, 10.3, 9.9, 10.2, None), 0.10, False)
    assert df["limit_status"].iloc[0] == 0  # pre_close 缺失不判涨跌停


def test_abnormal_change_detection():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute(
            "INSERT INTO daily_bar (code, trade_date, close, pre_close) VALUES "
            "('600000.SH', DATE '2024-01-02', 13.0, 10.0)"  # +30% 远超主板 10%
        )
        qc = QualityChecker(c)
        n = qc.check_abnormal_change("600000.SH", 0.10)
        assert n == 1
        issues = c.query_df("SELECT issue_type FROM data_quality_issue")
        assert issues.iloc[0]["issue_type"] == "abnormal_change"


def test_compute_pre_close_exrights():
    """除权日前收盘按复权因子调整（修复 001332 类高送转误判）。"""
    import pandas as pd

    from backend.datasource.akshare_source import compute_pre_close

    # 普通日因子不变 → pre_close = 上一日收盘
    close = pd.Series([10.0, 10.5, 11.0])
    factor = pd.Series([2.0, 2.0, 2.0])
    pc = compute_pre_close(close, factor)
    assert pd.isna(pc.iloc[0])
    assert abs(pc.iloc[1] - 10.0) < 1e-9
    assert abs(pc.iloc[2] - 10.5) < 1e-9

    # 除权日：因子从 1.5 跳到 2.12（类 001332），前收盘应被调小
    close2 = pd.Series([63.97, 46.45])
    factor2 = pd.Series([1.503674, 2.121851])
    pc2 = compute_pre_close(close2, factor2)
    # 63.97 × 1.503674/2.121851 ≈ 45.33（而非原始 63.97）
    assert abs(pc2.iloc[1] - 45.33) < 0.1


def test_sanitize_bars():
    """入库自清洗：丢弃坏close、回填零OHL、零成交填0。"""
    import pandas as pd

    from backend.dataquality.checker import sanitize_bars

    df = pd.DataFrame([
        {"close": 10.0, "open": 0.0, "high": 0.0, "low": 0.0, "volume": 100, "amount": 1000.0, "turnover_rate": 1.0},  # OHL=0→回填
        {"close": 0.0, "open": 5.0, "high": 5.0, "low": 5.0, "volume": 0, "amount": None, "turnover_rate": None},      # close=0→丢弃
        {"close": 8.0, "open": 8.0, "high": 8.0, "low": 8.0, "volume": 0, "amount": None, "turnover_rate": None},      # 零成交→填0
    ])
    out, stats = sanitize_bars(df)
    assert stats["dropped"] == 1          # 丢了 close=0 那行
    assert len(out) == 2
    row0 = out.iloc[0]
    assert row0["open"] == 10.0 and row0["high"] == 10.0  # OHL 用 close 回填
    zero = out[out["volume"] == 0].iloc[0]
    assert zero["amount"] == 0.0 and zero["turnover_rate"] == 0.0
