"""前向收益计算（T-M5-2/3 的正确性基元，SDD §6.5）。

回答"信号发出后 N 日内最高摸到多少涨幅"——信号质量分析与 base rate 的共用核心。

关键正确性约定
--------------
1. **复权一致**：用**后复权价**（hfq = 原价 × adj_factor）算前向收益。entry→fwd_high
   的比值会消去任意公共基准（qfq 的 /base_factor 项），故 hfq 比值 == 真实复权收益，
   且 adj_factor 是历史已知值，**无未来函数**（用未来 N 日价格是"评估"，非信号生成）。
2. **入场 = T+1 开盘**：信号在 T 日，入场价取该股**下一根可得 bar** 的开盘价（停牌则自然
   顺延到复牌首日 open，与撮合"顺延"一致）。无下一根 bar（如随后退市）→ 不可评估，剔除。
3. **窗口 = [T+1 .. T+N]**：N 根交易日内的最高价（含入场日）。
4. **防幸存者偏差**：全市场口径（base rate）含退市股；某股若在窗口内退市，用**已得数据**
   算最大浮盈（它确实没机会再涨，诚实口径），不剔除。
5. **右沿截断**：临近数据末端的信号缺完整 N 日窗口 → `eval_N=False`（按市场日历判定，
   与个股是否退市无关），默认从命中率统计中排除以免低估，并标注被丢样本量。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from backend.common.logging import get_logger
from backend.market_identity import STOCK_CODE_CHANGES, canonical_stock_code
from backend.storage.duckdb_client import get_client

log = get_logger("backtest.forward")


def _market_dates(client, lo: date, hi: date) -> list[pd.Timestamp]:
    """[lo, hi] 内的交易日（按 daily_bar 实际出现的日期，已是市场口径）。"""
    df = client.query_df(
        "SELECT DISTINCT trade_date FROM daily_bar "
        "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        [lo, hi],
    )
    return [pd.Timestamp(d) for d in df["trade_date"]]


def compute_forward_returns(
    date_start: date,
    date_end: date,
    horizons: list[int],
    codes: list[str] | None = None,
    client=None,
) -> pd.DataFrame:
    """对 [date_start, date_end] 内每个 (code, signal_date) 算各 N 的前向最大涨幅。

    返回 DataFrame 列：code, trade_date(信号日), entry_price(hfq 次日开),
      以及每个 N：fwd_ret_<N>（max_fwd_return）, eval_<N>（是否满足完整窗口/可入场）。

    实现：按市场日历确定右沿可评估截止日；逐股反向滚动最大（hfq high）；
    入场价 = 该股下一根 bar 的 hfq open。
    """
    client = client or get_client()
    horizons = sorted(set(horizons))
    max_n = max(horizons)

    # 取信号区间 + 前向缓冲（max_n 个交易日）的全部 bar
    buf_hi = date_end + timedelta(days=max_n * 3 + 30)  # 日历日宽松上界，交易日截断在下方
    sql = (
        "SELECT code, trade_date, open, high, "
        "       COALESCE(adj_factor_clean, adj_factor) AS adj_factor FROM daily_bar "
        "WHERE trade_date BETWEEN ? AND ?"
    )
    params: list = [date_start, buf_hi]
    if codes is not None:
        if not codes:
            return pd.DataFrame(columns=["code", "trade_date", "entry_price"])
        query_codes = list(dict.fromkeys([*codes, *[
            canonical_stock_code(c) for c in codes
            if any(x.previous_code == c and x.effective_date <= buf_hi for x in STOCK_CODE_CHANGES)
        ]]))
        sql += f" AND code IN ({','.join('?' * len(query_codes))})"
        params += query_codes
    sql += " ORDER BY code, trade_date"
    bars = client.query_df(sql, params)
    if bars.empty:
        return pd.DataFrame(columns=["code", "trade_date", "entry_price"])

    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    af = bars["adj_factor"].fillna(1.0)
    bars["open_hfq"] = bars["open"] * af
    bars["high_hfq"] = bars["high"] * af

    # 右沿可评估截止：信号日的市场位置 k 满足 k+N <= last_market_pos
    mdates = _market_dates(client, date_start, buf_hi)
    last_pos = len(mdates) - 1
    cutoff_n = {
        n: (mdates[last_pos - n] if last_pos - n >= 0 else None) for n in horizons
    }

    out_parts: list[pd.DataFrame] = []
    for code, g in bars.groupby("code", sort=False):
        g = g.reset_index(drop=True)
        entry = g["open_hfq"].shift(-1)  # 次日（下一根 bar）开盘价
        rec = pd.DataFrame({"code": code, "trade_date": g["trade_date"], "entry_price": entry})
        hi = g["high_hfq"]
        for n in horizons:
            # rmax_from[q] = max(high[q : q+n])；窗口 [i+1, i+n] = rmax_from[i+1]
            rmax_from = hi[::-1].rolling(n, min_periods=1).max()[::-1]
            fwd_high = rmax_from.shift(-1)
            rec[f"fwd_ret_{n}"] = fwd_high / entry - 1.0
        out_parts.append(rec)

    res = pd.concat(out_parts, ignore_index=True)
    # 只保留信号区间内的日期（缓冲日不作为信号）
    res = res[res["trade_date"] <= pd.Timestamp(date_end)]

    value_cols = ["entry_price", *[f"fwd_ret_{n}" for n in horizons]]
    for change in STOCK_CODE_CHANGES:
        if not date_start <= change.effective_date <= buf_hi:
            continue
        mask = res["code"].eq(change.previous_code) & res["trade_date"].lt(pd.Timestamp(change.effective_date))
        if not mask.any():
            continue
        continuous = res.loc[res["code"].eq(canonical_stock_code(change.current_code))].set_index("trade_date")
        dates = res.loc[mask, "trade_date"]
        if not dates.isin(continuous.index).all():
            raise ValueError(f"{change.previous_code} 更码前向收益缺同一证券的连续行情")
        res.loc[mask, value_cols] = continuous.reindex(dates)[value_cols].to_numpy()
    if codes is not None:
        res = res.loc[res["code"].isin(codes)].copy()

    # 可评估标记：有入场价（下一根 bar 存在）且右沿完整窗口
    has_entry = res["entry_price"].notna()
    for n in horizons:
        cut = cutoff_n[n]
        full = (res["trade_date"] <= cut) if cut is not None else False
        res[f"eval_{n}"] = has_entry & full & res[f"fwd_ret_{n}"].notna()
    return res.reset_index(drop=True)
