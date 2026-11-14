"""M2 指标引擎测试 —— 重点：防未来函数安全网（SDD §17/§18）。"""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from backend.indicators import operators as op
from backend.indicators.compute import (
    INDICATOR_ALGO_VERSION,
    build_params,
    compute_market_indicators,
    compute_stock_indicators,
    param_hash,
)
from backend.indicators.engine import _IND_COLS


# ── 1. 基础算子正确性 + 后向性 ──
def test_ma_backward_only():
    x = pd.Series([1.0, 2, 3, 4, 5])
    ma = op.MA(x, 3)
    assert pd.isna(ma.iloc[0]) and pd.isna(ma.iloc[1])  # 不足 3 日 → NaN
    assert ma.iloc[2] == 2.0 and ma.iloc[4] == 4.0      # 仅用过去+当日


def test_rs_window_participates_in_indicator_hash():
    params = build_params()
    assert params["rs_window"] > 0
    changed = {**params, "rs_window": params["rs_window"] + 1}
    assert param_hash(params) != param_hash(changed)


def test_ema_matches_pandas_recursive_formula_and_preserves_invalid_rows():
    x = pd.Series([1.0, 2, 3, 4, 5, np.nan, 7, np.inf, 9])
    actual = op.EMA(x, 3)
    clean = x.replace([np.inf, -np.inf], np.nan)
    expected = clean.ewm(span=3, adjust=False, min_periods=3).mean().where(clean.notna())
    assert_series_equal(actual, expected)
    assert pd.isna(actual.iloc[5]) and pd.isna(actual.iloc[7])


def test_ema_rejects_non_positive_period():
    try:
        op.EMA(pd.Series([1.0]), 0)
        assert False, "EMA 非正周期应报错"
    except ValueError:
        pass


def test_ref_rejects_future():
    x = pd.Series([1.0, 2, 3])
    assert op.REF(x, 1).iloc[2] == 2.0   # 取过去
    try:
        op.REF(x, -1)
        assert False, "REF 取未来应报错"
    except ValueError:
        pass


def test_hhv_and_new_high_na_when_insufficient():
    high = pd.Series([10.0] * 5)
    close = pd.Series([10.0] * 5)
    nh = op.is_new_high(close, high, 60)   # 不足 60 日
    assert nh.isna().all()                 # 全 <NA> 不适用（不冒充新高）


def test_platform_breakout_no_self_reference():
    # 平台突破必须用 REF(HHV,1)：当日自身不计入平台高点
    high = pd.Series([10, 10, 10, 10, 12.0])  # 第5日冲高
    close = pd.Series([9, 9, 9, 9, 11.5])
    pb = op.platform_breakout(close, high, 3)
    # 第5日：平台=前3日(1..3)最高=10，收盘11.5>10 → 突破True；当日自身12不计入
    assert bool(pb.iloc[4]) is True


# ── 2. 关键：全代码无 shift(-n) 未来引用 ──
def test_no_future_shift_in_indicator_code():
    """扫描 indicators 包源码：禁止任何 shift(负数)（防未来函数）。"""
    pkg = pathlib.Path(op.__file__).parent
    offenders = []
    for pyf in pkg.glob("*.py"):
        src = pyf.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            # 匹配 .shift(<负数字面量>) 或 .shift(-x)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "shift" and node.args):
                a = node.args[0]
                if isinstance(a, ast.UnaryOp) and isinstance(a.op, ast.USub):
                    offenders.append(f"{pyf.name}: shift(-...)")
                if isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) and a.value < 0:
                    offenders.append(f"{pyf.name}: shift({a.value})")
    assert not offenders, f"发现未来函数 shift 负移: {offenders}"


# ── 3. 单股指标整体计算 ──
def _fake_bars(n=300):
    dates = pd.bdate_range("2023-01-02", periods=n).date
    close = pd.Series(np.linspace(10, 30, n))  # 单调上行
    return pd.DataFrame({
        "code": "600000.SH", "trade_date": dates,
        # 每日收在最高（high==close），单调上行 → 末日确为 60 日新高
        "open": close * 0.99, "high": close, "low": close * 0.99,
        "close": close, "volume": np.arange(1, n + 1) * 1000,
        "turnover_rate": np.full(n, 5.0),
    })


def test_compute_stock_indicators_shapes_and_values():
    df = _fake_bars(300)
    ind = compute_stock_indicators(df, build_params())
    assert len(ind) == 300
    # 单调上行 → 多头排列应在足够长后成立
    assert bool(ind["is_bull_arrange"].iloc[-1]) is True
    # 不足 480 日 → 两年新高判 <NA>（不适用）
    assert ind["is_high_2y"].iloc[100] is pd.NA or pd.isna(ind["is_high_2y"].iloc[100])
    # 单调上行最后一日应是 60 日新高
    assert bool(ind["is_high_60"].iloc[-1]) is True
    # 健康换手 5% 落在 3~20 区间
    assert bool(ind["is_turnover_healthy"].iloc[-1]) is True
    # param_hash 非空
    assert ind["param_hash"].iloc[0]
    assert ind["ma30"].iloc[-1] == pytest.approx(df["close"].iloc[-30:].mean())


def test_macd_numeric_values_warmup_and_algo_hash():
    df = _fake_bars(90)
    ind = compute_stock_indicators(df, build_params())
    close = df["close"]
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    expected_diff = ema12 - ema26
    expected_dea = expected_diff.ewm(span=9, adjust=False, min_periods=9).mean()
    expected_hist = 2.0 * (expected_diff - expected_dea)

    assert_series_equal(ind["macd_diff"], expected_diff, check_names=False)
    assert_series_equal(ind["macd_dea"], expected_dea, check_names=False)
    assert_series_equal(ind["macd_hist"], expected_hist, check_names=False)
    assert ind["macd_diff"].iloc[:25].isna().all()
    assert ind["macd_dea"].iloc[:33].isna().all()
    assert ind["macd_hist"].iloc[:33].isna().all()

    params = build_params()
    assert params["algo_version"] == INDICATOR_ALGO_VERSION
    legacy = {**params, "algo_version": "legacy"}
    assert param_hash(params) != param_hash(legacy)


def test_macd_cross_events_include_equal_break_and_do_not_cross_missing_gap():
    close = pd.Series([10.0] * 40 + [20.0, 0.0])
    df = _fake_bars(len(close))
    df["close"] = close
    df["high"] = close
    ind = compute_stock_indicators(df, build_params())
    assert bool(ind["macd_golden_cross"].iloc[40]) is True
    assert bool(ind["macd_dead_cross"].iloc[41]) is True
    assert not (ind["macd_golden_cross"].fillna(False) & ind["macd_dead_cross"].fillna(False)).any()

    gap_close = pd.Series([10.0] * 40 + [np.nan, 20.0])
    gap_df = _fake_bars(len(gap_close))
    gap_df["close"] = gap_close
    gap_df["high"] = gap_close
    gap_ind = compute_stock_indicators(gap_df, build_params())
    assert pd.isna(gap_ind["macd_golden_cross"].iloc[40])
    assert pd.isna(gap_ind["macd_golden_cross"].iloc[41])
    assert pd.isna(gap_ind["macd_dead_cross"].iloc[40])
    assert pd.isna(gap_ind["macd_dead_cross"].iloc[41])


def test_macd_dead_cross_includes_equal_to_down_break():
    close = pd.Series([10.0] * 40 + [0.0])
    df = _fake_bars(len(close))
    df["close"] = close
    df["high"] = close
    ind = compute_stock_indicators(df, build_params())

    assert np.isclose(ind["macd_diff"].iloc[39], ind["macd_dea"].iloc[39])
    assert ind["macd_diff"].iloc[40] < ind["macd_dea"].iloc[40]
    assert bool(ind["macd_dead_cross"].iloc[40]) is True
    assert bool(ind["macd_golden_cross"].iloc[40]) is False


def test_macd_is_prefix_stable_when_future_rows_are_appended():
    df = _fake_bars(120)
    prefix = compute_stock_indicators(df.iloc[:80], build_params())
    full = compute_stock_indicators(df, build_params()).iloc[:80].reset_index(drop=True)
    cols = [
        "macd_diff",
        "macd_dea",
        "macd_hist",
        "macd_golden_cross",
        "macd_dead_cross",
    ]
    pd.testing.assert_frame_equal(prefix[cols], full[cols])


def test_market_macd_matches_per_stock_and_engine_columns():
    first = _fake_bars(100)
    second = _fake_bars(100)
    second["code"] = "000001.SZ"
    second["close"] = pd.Series([10.0] * 40 + [20.0, 0.0] + [12.0] * 58)
    second["high"] = second["close"]
    market_bars = pd.concat([first, second], ignore_index=True)
    market = compute_market_indicators(market_bars, build_params())
    cols = [
        "macd_diff",
        "macd_dea",
        "macd_hist",
        "macd_golden_cross",
        "macd_dead_cross",
    ]

    for code, bars in market_bars.groupby("code", sort=False):
        stock = compute_stock_indicators(bars, build_params()).reset_index(drop=True)
        actual = market[market["code"] == code].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual[cols], stock[cols])

    assert set(cols).issubset(_IND_COLS)


def test_market_macd_matches_per_stock_with_nan_and_infinite_close():
    first = _fake_bars(100)
    second = _fake_bars(100)
    second["code"] = "000001.SZ"
    second.loc[45, "close"] = np.nan
    second.loc[65, "close"] = np.inf
    second.loc[85, "close"] = -np.inf
    market_bars = pd.concat([first, second], ignore_index=True)
    market = compute_market_indicators(market_bars, build_params())
    cols = [
        "macd_diff",
        "macd_dea",
        "macd_hist",
        "macd_golden_cross",
        "macd_dead_cross",
    ]

    for code, bars in market_bars.groupby("code", sort=False):
        stock = compute_stock_indicators(bars, build_params()).reset_index(drop=True)
        actual = market[market["code"] == code].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual[cols], stock[cols])

    invalid = market[market["code"] == "000001.SZ"].reset_index(drop=True).iloc[[45, 65, 85]]
    assert invalid[["macd_diff", "macd_dea", "macd_hist"]].isna().all().all()
    assert invalid[["macd_golden_cross", "macd_dead_cross"]].isna().all().all()
