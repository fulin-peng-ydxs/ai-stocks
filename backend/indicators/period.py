"""技术指标的 K 线周期上下文。

周期只改变输入序列粒度，不改变指标原子定义；所有聚合严格使用截止日及以前的数据。
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from backend.indicators.compute import compute_macd

IndicatorPeriod = Literal["day", "week", "month", "year"]
INDICATOR_PERIODS: tuple[IndicatorPeriod, ...] = ("day", "week", "month", "year")
# 方案指标引擎当前只消费日线序列。图表可切换多周期，但不会隐式改变
# 筛选、评分、买卖或回测的计算粒度；未来开放时在方案执行上下文扩展。
INDICATOR_ENGINE_DEFAULT_PERIOD: IndicatorPeriod = "day"
INDICATOR_ENGINE_SUPPORTED_PERIODS: tuple[IndicatorPeriod, ...] = ("day",)
MACD_OUTPUT_COLUMNS: tuple[str, ...] = (
    "macd_diff",
    "macd_dea",
    "macd_hist",
    "macd_golden_cross",
    "macd_dead_cross",
)


def aggregate_period_closes(
    daily: pd.DataFrame,
    period: IndicatorPeriod,
) -> pd.DataFrame:
    """按自然周期取末个有效交易日及其收盘价，保留当前未完成周期。"""
    if period not in INDICATOR_PERIODS:
        raise ValueError(f"不支持的指标周期: {period}")
    if daily.empty:
        return pd.DataFrame(columns=["trade_date", "close"])
    if not {"trade_date", "close"}.issubset(daily.columns):
        raise ValueError("周期指标输入缺少 trade_date 或 close")

    frame = daily[["trade_date", "close"]].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    if period == "day" or frame.empty:
        return frame

    frequency = {"week": "W-SUN", "month": "M", "year": "Y"}[period]
    frame["_period"] = frame["trade_date"].dt.to_period(frequency)
    return (
        frame.groupby("_period", sort=True, observed=True)
        .tail(1)[["trade_date", "close"]]
        .reset_index(drop=True)
    )


def compute_period_macd(
    daily: pd.DataFrame,
    period: IndicatorPeriod,
) -> pd.DataFrame:
    """聚合指定周期后复用唯一 MACD 原子公式，返回周期末交易日序列。"""
    closes = aggregate_period_closes(daily, period)
    if closes.empty:
        return pd.DataFrame(columns=["trade_date", *MACD_OUTPUT_COLUMNS])
    macd = compute_macd(closes["close"])
    return pd.concat([closes[["trade_date"]], macd], axis=1)
