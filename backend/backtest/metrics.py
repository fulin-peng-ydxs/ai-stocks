"""绩效指标计算（T-M5-7，SDD §10.4）。

输入逐日净值序列（+基准）与逐笔交易，输出累计/年化/回撤/夏普/卡玛/索提诺/胜率/盈亏比等。
纯函数，无 IO，便于单测。约定每年约 242 个交易日；无风险利率默认 0。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 242


def _max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """最大回撤（≤0）与最长水下持续交易日数。"""
    if len(equity) < 2:
        return 0.0, 0
    cummax = equity.cummax()
    dd = equity / cummax - 1.0
    mdd = float(dd.min())
    # 最长水下区间：从一个峰值到恢复（或序列末）的最长跨度
    underwater = (equity < cummax).values
    longest = cur = 0
    for u in underwater:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    return mdd, int(longest)


def compute_metrics(
    equity: pd.Series,
    benchmark: pd.Series | None,
    trades: list[dict],
    risk_free: float = 0.0,
) -> dict:
    """equity/benchmark：按日期升序的净值序列（同起点对齐）。trades：含 return_pct/pnl/hold_days。"""
    equity = equity.dropna()
    if len(equity) < 2:
        return {"total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0,
                "max_dd_days": 0, "annual_vol": 0.0, "sharpe": 0.0, "calmar": 0.0,
                "sortino": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "avg_hold_days": 0.0, "n_trades": len(trades),
                "benchmark_return": 0.0, "excess_return": 0.0}

    n = len(equity)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    years = max(n / TRADING_DAYS, 1e-9)
    annual_return = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)

    r = equity.pct_change().dropna()
    mean_d, std_d = float(r.mean()), float(r.std())
    annual_vol = std_d * math.sqrt(TRADING_DAYS)
    sharpe = ((mean_d * TRADING_DAYS - risk_free) / annual_vol) if annual_vol > 1e-12 else 0.0

    downside = r[r < 0]
    dstd = float(downside.std()) if len(downside) > 1 else 0.0
    sortino = ((mean_d * TRADING_DAYS - risk_free) / (dstd * math.sqrt(TRADING_DAYS))
               if dstd > 1e-12 else 0.0)

    mdd, mdd_days = _max_drawdown(equity)
    calmar = (annual_return / abs(mdd)) if mdd < -1e-12 else 0.0

    # 逐笔交易统计
    rets = [t["return_pct"] for t in trades if t.get("return_pct") is not None]
    pnls = [t["pnl"] for t in trades if t.get("pnl") is not None]
    holds = [t["hold_days"] for t in trades if t.get("hold_days") is not None]
    win_rate = float(np.mean([1.0 if x > 0 else 0.0 for x in rets])) if rets else 0.0
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    profit_factor = float(gains / losses) if losses > 1e-9 else (float("inf") if gains > 0 else 0.0)
    avg_hold = float(np.mean(holds)) if holds else 0.0

    bench_return = 0.0
    if benchmark is not None and len(benchmark.dropna()) >= 2:
        b = benchmark.dropna()
        bench_return = float(b.iloc[-1] / b.iloc[0] - 1.0)

    return {
        "total_return": round(total_return, 6),
        "annual_return": round(annual_return, 6),
        "max_drawdown": round(mdd, 6),
        "max_dd_days": mdd_days,
        "annual_vol": round(annual_vol, 6),
        "sharpe": round(sharpe, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": (round(profit_factor, 4) if math.isfinite(profit_factor) else None),
        "avg_hold_days": round(avg_hold, 2),
        "n_trades": len(rets),
        "benchmark_return": round(bench_return, 6),
        "excess_return": round(total_return - bench_return, 6),
    }
