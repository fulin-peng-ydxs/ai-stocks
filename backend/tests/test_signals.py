"""M6 买点/风险识别测试（T-M6-1/2）：构造序列验证状态机与风险标签。"""

from __future__ import annotations

import pandas as pd

from backend.signals.buypoint import BuyPointDetector
from backend.signals.risk import RiskDetector


def _bp_df(rows: list[dict]) -> pd.DataFrame:
    """构造买点检测输入，缺省列填中性值。"""
    cols = {"close": 10.0, "ma10": 10.0, "ma20": 9.5, "volume": 1000.0,
            "vol_ma5": 1000.0, "vol_ma20": 1000.0, "is_platform_breakout": False,
            "is_vol_breakout": False, "is_high_2y": False}
    return pd.DataFrame([{**cols, **r} for r in rows])


def test_buypoint_third_on_new_high():
    df = _bp_df([{"is_high_2y": True}])
    assert BuyPointDetector().detect(df).iloc[0] == "第三买点"


def test_buypoint_second_on_vol_breakout():
    df = _bp_df([{"is_platform_breakout": True, "is_vol_breakout": True}])
    assert BuyPointDetector().detect(df).iloc[0] == "第二买点"


def test_buypoint_first_breakout_pullback_confirm():
    # 突破 → 缩量回踩 MA10 不破 → 放量上涨确认
    df = _bp_df([
        {"close": 11.0, "ma10": 10.0, "ma20": 9.5, "volume": 2000, "is_platform_breakout": True},
        {"close": 10.1, "ma10": 10.0, "ma20": 9.6, "volume": 800},   # 缩量回踩
        {"close": 10.5, "ma10": 10.0, "ma20": 9.7, "volume": 1500, "vol_ma5": 1000},  # 放量上涨确认
    ])
    labels = BuyPointDetector().detect(df)
    assert labels.iloc[2] == "第一买点"


def test_buypoint_first_fails_on_breakdown():
    # 回踩直接跌破 MA20 → 形态失败，不产生第一买点
    df = _bp_df([
        {"close": 11.0, "ma10": 10.0, "ma20": 9.5, "volume": 2000, "is_platform_breakout": True},
        {"close": 8.5, "ma10": 10.0, "ma20": 9.5, "volume": 800},    # 跌破 MA20×0.95=9.025
        {"close": 9.0, "ma10": 10.0, "ma20": 9.5, "volume": 1500, "vol_ma5": 1000},
    ])
    assert (BuyPointDetector().detect(df) == "第一买点").sum() == 0


# ── 风险 ──
def _rk_df(rows: list[dict]) -> pd.DataFrame:
    cols = {"open": 10.0, "close": 10.0, "volume": 1000.0, "turnover_rate": 5.0,
            "ma10": 9.0, "ma20": 8.5, "ma60": 8.0, "vol_ma20": 1000.0, "is_high_2y": False}
    return pd.DataFrame([{**cols, **r} for r in rows])


def test_risk_chase_three_big_up():
    big = {"open": 10.0, "close": 10.6}  # +6% 实体大阳线
    df = _rk_df([big, big, big])
    flags = RiskDetector().detect(df)
    assert "连阳追高" not in flags.iloc[0]   # 第1根不算
    assert "连阳追高" in flags.iloc[2]        # 连续3根 → 追高


def test_risk_break_ma_and_overheat():
    df = _rk_df([{"close": 7.0, "ma10": 9.0, "ma20": 8.5, "ma60": 8.0, "turnover_rate": 40.0}])
    flags = RiskDetector().detect(df).iloc[0]
    assert "跌破MA10" in flags and "跌破MA20" in flags and "跌破MA60" in flags
    assert "换手过热" in flags  # 40% > 35%


def test_risk_volume_price_divergence():
    # 创新高但缩量 → 量价背离
    df = _rk_df([{"close": 12.0, "ma10": 9, "ma20": 8.5, "ma60": 8, "is_high_2y": True,
                  "volume": 500, "vol_ma20": 1000}])
    assert "量价背离" in RiskDetector().detect(df).iloc[0]
