"""筛选表达式批量预计算（T-M5-10，SDD §8.6）。

回测在数百调仓日反复跑同一筛选，逐日逐股重算 expr 太慢（O(股×日) 次序列拉取）。
本模块把 AST 的 expr 叶子在**全历史一次性**算成 (code, date)->bool 查找表（O(股) 次），
再对每个调仓日用预算好的 expr 值 + 当日截面的 col 叶子，按 AST 合并出命中集。

正确性：expr 多为**尺度不变**的相对条件（C>REF(C,1)、C>=HHV(H,720)、COUNT(...)==5），
对 qfq 基准缩放不变 → 用统一基准（date_end）整段算与逐日 rebase 结果一致，且无未来函数
（序列只到各日；预算用 ≤date_end 全序列，但每个调仓日只读该日及之前的布尔值）。
⚠️ 含**绝对价**比较的 expr（如 `C > 50`）非尺度不变，不适用本优化——此类极少且不建议。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.screening.condition import collect_leaves, eval_ast, validate_ast
from backend.screening.expression import eval_expr
from backend.storage.duckdb_client import get_client

log = get_logger("backtest.precompute")

_CMP = {
    "==": lambda s, v: s == v, "!=": lambda s, v: s != v,
    ">": lambda s, v: s > v, ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v, "<=": lambda s, v: s <= v,
    "between": lambda s, v: (s >= v[0]) & (s <= v[1]),
}


class HitPrecomputer:
    def __init__(self, client=None):
        self.c = client or get_client()
        from backend.indicators.engine import IndicatorEngine
        self.ind = IndicatorEngine(self.c)

    def precompute(self, ast: dict, date_start: date, date_end: date) -> dict:
        """返回 {date: set(命中 code)}（仅含区间内交易日）。"""
        validate_ast(ast)
        _, exprs = collect_leaves(ast)

        # ── 1. expr 叶子：每股全序列一次 → {expr_str: Series((code, ts) -> bool)} ──
        expr_lookup: dict[str, dict] = {e["expr"]: {} for e in exprs}
        if exprs:
            bars = self.c.query_df(
                "SELECT code, trade_date, open, high, low, close, volume, turnover_rate, adj_factor "
                "FROM daily_bar WHERE trade_date <= ? ORDER BY code, trade_date",
                [date_end],
            )
            bars["trade_date"] = pd.to_datetime(bars["trade_date"])
            for code, g in bars.groupby("code", sort=False):
                g = g.reset_index(drop=True)
                af = g["adj_factor"].fillna(1.0)
                base = af.iloc[-1] if len(af) else 1.0
                ctx = {
                    "C": g["close"] * af / base, "O": g["open"] * af / base,
                    "H": g["high"] * af / base, "L": g["low"] * af / base,
                    "V": g["volume"].astype(float), "TURN": g["turnover_rate"].astype(float),
                }
                dts = list(g["trade_date"])  # pd.Timestamp，与下方截面 groupby 键同型
                for e in exprs:
                    try:
                        s = eval_expr(e["expr"], ctx).fillna(False).astype(bool).values
                    except Exception:  # noqa: BLE001
                        continue
                    d = expr_lookup[e["expr"]]
                    for i, ts in enumerate(dts):
                        if s[i]:
                            d[(code, ts)] = True

        # ── 2. 逐调仓日：col 叶子用当日截面 + expr 叶子查预算表，按 AST 合并 ──
        snap_all = self.ind.wide_snapshot(date_start, date_end)
        out: dict = {}
        if snap_all.empty:
            return out
        snap_all["trade_date"] = pd.to_datetime(snap_all["trade_date"])
        for ts, snap in snap_all.groupby("trade_date", sort=False):
            snap = snap.set_index("code")

            def eval_leaf(leaf: dict, _snap=snap, _ts=ts) -> pd.Series:
                if leaf.get("type") == "expr":
                    if leaf.get("ignore"):
                        return pd.Series(True, index=_snap.index)
                    lut = expr_lookup.get(leaf["expr"], {})
                    return pd.Series(
                        [(code, _ts) in lut for code in _snap.index], index=_snap.index
                    )
                if leaf.get("ignore"):
                    return pd.Series(True, index=_snap.index)
                field = leaf["field"]
                if field not in _snap.columns:
                    return pd.Series(False, index=_snap.index)
                return _CMP[leaf["cmp"]](_snap[field], leaf["value"]).fillna(False)

            hit = eval_ast(ast, eval_leaf).fillna(False).astype(bool)
            out[ts.date()] = set(snap.index[hit.values])
        log.info("预计算命中 %s~%s：%d 个交易日", date_start, date_end, len(out))
        return out
