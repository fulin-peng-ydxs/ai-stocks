"""筛选执行引擎（SDD §8.3）——混合执行：col 截面向量化 + expr 逐股点时求值。

run_ast(ast, run_date, universe) 流程：
  1. 取 run_date 当日截面 snapshot（indicator⋈daily_bar⋈daily_metrics），col 叶子在此向量化。
  2. 若含 expr 叶子：逐股取 ≤run_date 前复权序列，DSL 沙箱求值，取当日布尔。
  3. 按 AST 的 AND/OR/NOT 合并 → 命中票池 + 命中明细。

点时安全：snapshot 只取 run_date 当日；expr 序列只到 run_date；防未来函数。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.common.logging import get_logger
from backend.indicators.engine import IndicatorEngine
from backend.screening.condition import collect_leaves, eval_ast, validate_ast
from backend.screening.expression import eval_expr
from backend.storage.duckdb_client import get_client
from backend.storage.repository import MarketRepository

log = get_logger("screening.engine")

_CMP_FUNCS = {
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "between": lambda s, v: (s >= v[0]) & (s <= v[1]),
}


class ScreenEngine:
    def __init__(self, client=None):
        self.c = client or get_client()
        self.repo = MarketRepository(self.c)
        self.ind = IndicatorEngine(self.c)

    def _snapshot(self, run_date: date, universe: list[str] | None) -> pd.DataFrame:
        """run_date 当日全市场截面（动态指标+行情+市值），索引=code。"""
        df = self.ind.wide_snapshot(run_date, run_date, codes=universe)
        if df.empty:
            return df
        return df.set_index("code")

    def _eval_col(self, leaf: dict, snap: pd.DataFrame) -> pd.Series:
        if leaf.get("ignore"):
            return pd.Series(True, index=snap.index)
        field = leaf["field"]
        if field not in snap.columns:
            raise KeyError(f"col 字段不存在: {field}")
        return _CMP_FUNCS[leaf["cmp"]](snap[field], leaf["value"])

    def _eval_ind(self, leaf: dict, snap: pd.DataFrame, run_date: date) -> pd.Series:
        """注册表指标叶子：内置→复用快照列；表达式型/自定义→渲染参数后逐股点时求值。"""
        if leaf.get("ignore"):
            return pd.Series(True, index=snap.index)
        from backend.indicators.definition import IndicatorDefRepo
        from backend.scoring.score_profile import resolve_indicator
        key, params = leaf["key"], leaf.get("params")
        d = IndicatorDefRepo(self.c).get(key)
        if d and d.get("kind") == "expr":
            s = self.ind._eval_expr_indicator(
                d["expression"], params, d.get("params"), run_date, list(snap.index))
            s = s.reindex(snap.index)
        else:
            s = resolve_indicator(key, params, snap)  # 复用已建快照，避免重算
        return _CMP_FUNCS[leaf["cmp"]](s, leaf["value"])

    def _eval_exprs(self, exprs: list[dict], run_date: date, codes: list[str]) -> dict:
        """逐股算各 expr 叶子在 run_date 的布尔值 → {expr_str: Series(code->bool)}。"""
        out = {e["expr"]: {} for e in exprs}
        for code in codes:
            bars = self.repo.get_bars(code, run_date, adjust="qfq")
            if bars.empty:
                continue
            ctx = {
                "C": bars["close"], "O": bars["open"], "H": bars["high"], "L": bars["low"],
                "V": bars["volume"].astype(float), "TURN": bars["turnover_rate"].astype(float),
            }
            for e in exprs:
                try:
                    val = eval_expr(e["expr"], ctx).iloc[-1]
                    out[e["expr"]][code] = bool(val) if pd.notna(val) else False
                except Exception:  # noqa: BLE001
                    out[e["expr"]][code] = False
        return {k: pd.Series(v, dtype="boolean") for k, v in out.items()}

    def run_ast(self, ast: dict, run_date: date, universe: list[str] | None = None) -> pd.DataFrame:
        """执行筛选，返回 DataFrame[code, hit]（按命中过滤前的全 universe 布尔）。"""
        validate_ast(ast)
        snap = self._snapshot(run_date, universe)
        if snap.empty:
            return pd.DataFrame(columns=["code", "hit"])
        cols, exprs = collect_leaves(ast)
        expr_series = self._eval_exprs(exprs, run_date, list(snap.index)) if exprs else {}

        def eval_leaf(leaf: dict) -> pd.Series:
            t = leaf.get("type")
            if t == "expr":
                if leaf.get("ignore"):
                    return pd.Series(True, index=snap.index)
                s = expr_series.get(leaf["expr"], pd.Series(False, index=snap.index))
                return s.reindex(snap.index).fillna(False)
            if t == "ind":
                return self._eval_ind(leaf, snap, run_date)
            return self._eval_col(leaf, snap)

        hit = eval_ast(ast, eval_leaf).fillna(False).astype(bool)
        res = pd.DataFrame({"code": snap.index, "hit": hit.values})
        log.info("筛选 %s：universe %d，命中 %d", run_date, len(res), int(res["hit"].sum()))
        return res

    def run_hits(self, ast: dict, run_date: date, universe: list[str] | None = None) -> list[str]:
        """只返回命中的股票代码列表。"""
        res = self.run_ast(ast, run_date, universe)
        return res[res["hit"]]["code"].tolist()
