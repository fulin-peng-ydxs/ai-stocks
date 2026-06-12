"""基础指标算子（SDD §7.2）——全部基于 pandas，**严格后向**，防未来函数。

铁律（防未来函数，SDD §6.1）：
- 只用 `.rolling(N)`（后向窗口）与 `.shift(+N)`（取过去）。
- **绝不** `.shift(-N)`（取未来）。本模块任何函数都不得引用 T 之后的数据。
- 序列必须按 trade_date 升序传入。

这些算子是纯函数：输入 pandas Series，输出 pandas Series（同索引），无副作用。
"""

from __future__ import annotations

import pandas as pd


def MA(x: pd.Series, n: int) -> pd.Series:
    """N 日简单移动平均。不足 N 日 → NaN（不适用）。"""
    return x.rolling(n, min_periods=n).mean()


def HHV(x: pd.Series, n: int) -> pd.Series:
    """最近 N 日最高值（含当日）。不足 N 日 → NaN。"""
    return x.rolling(n, min_periods=n).max()


def LLV(x: pd.Series, n: int) -> pd.Series:
    """最近 N 日最低值（含当日）。不足 N 日 → NaN。"""
    return x.rolling(n, min_periods=n).min()


def REF(x: pd.Series, n: int) -> pd.Series:
    """N 个交易日之前的值（取过去，正向 shift）。"""
    if n < 0:
        raise ValueError("REF 不允许取未来（n 必须 >= 0），防未来函数")
    return x.shift(n)


def COUNT(cond: pd.Series, n: int) -> pd.Series:
    """最近 N 日内满足条件的天数。cond 为布尔 Series。不足 N 日 → NaN。"""
    return cond.astype("float").rolling(n, min_periods=n).sum()


def is_new_high(close: pd.Series, high: pd.Series, n: int) -> pd.Series:
    """N 日新高：收盘 >= 最近 N 日最高价。不足 N 日 → NA（不适用，不冒充）。

    返回可空布尔（pandas 'boolean' 类型，NaN→<NA>）。
    """
    hhv = HHV(high, n)
    res = close >= hhv
    return res.where(hhv.notna(), other=pd.NA).astype("boolean")


def platform_breakout(close: pd.Series, high: pd.Series, n: int) -> pd.Series:
    """平台突破：C > REF(HHV(H,N),1) —— shift(1) 防把当日自身计入平台高点（防自指）。"""
    plat = HHV(high, n).shift(1)
    res = close > plat
    return res.where(plat.notna(), other=pd.NA).astype("boolean")
