"""M2 指标引擎测试 —— 重点：防未来函数安全网（SDD §17/§18）。"""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pandas as pd

from backend.indicators import operators as op
from backend.indicators.compute import build_params, compute_stock_indicators


# ── 1. 基础算子正确性 + 后向性 ──
def test_ma_backward_only():
    x = pd.Series([1.0, 2, 3, 4, 5])
    ma = op.MA(x, 3)
    assert pd.isna(ma.iloc[0]) and pd.isna(ma.iloc[1])  # 不足 3 日 → NaN
    assert ma.iloc[2] == 2.0 and ma.iloc[4] == 4.0      # 仅用过去+当日


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
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "shift":
                if node.args:
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
