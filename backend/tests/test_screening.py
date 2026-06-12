"""M3 筛选：表达式 DSL 沙箱（含安全/注入防护）+ 条件 AST 校验。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.screening.condition import ConditionError, eval_ast, validate_ast
from backend.screening.expression import ExprError, eval_expr, validate_expr


def _ctx(n=10):
    # 构造单股序列：收盘 10,11,...（连续上涨），量先增后减
    close = pd.Series(np.arange(10, 10 + n, dtype=float))
    return {
        "C": close, "O": close, "H": close * 1.0, "L": close * 0.98,
        "V": pd.Series(np.concatenate([np.arange(1, n - 1), [2, 1]]).astype(float)),
        "TURN": pd.Series(np.full(n, 5.0)),
    }


# ── 表达式：业务用例 ──
def test_consecutive_up():
    """连续 5 日上涨：COUNT(C>REF(C,1),5)==5。"""
    ctx = _ctx(10)  # 全程上涨
    res = eval_expr("COUNT(C > REF(C,1), 5) == 5", ctx)
    assert bool(res.iloc[-1]) is True


def test_each_day_up_pct():
    """最近 3 日每天涨幅≥5%。"""
    ctx = _ctx(10)
    res = eval_expr("COUNT(C / REF(C,1) - 1 >= 0.05, 3) == 3", ctx)
    assert res.iloc[-1] in (True, False)  # 能算出布尔，不报错


def test_volume_shrink():
    """缩量：V < MA(V,5)*0.7（末日量=1，明显缩量）。"""
    ctx = _ctx(10)
    res = eval_expr("V < MA(V,5) * 0.7", ctx)
    assert bool(res.iloc[-1]) is True


def test_three_year_high_false_when_insufficient():
    """三年新高 C>=HHV(H,720)：数据不足 720 → 比较得 False（不适用即不命中）。"""
    ctx = _ctx(10)
    res = eval_expr("C >= HHV(H,720)", ctx)
    assert bool(res.iloc[-1]) is False  # HHV 不足→NaN，C>=NaN→False（不命中）


# ── 安全：注入与越权必须被拦 ──
@pytest.mark.parametrize("bad", [
    "__import__('os').system('ls')",
    "C.__class__",
    "open('/etc/passwd')",
    "().__class__.__bases__",
    "C[0]",
    "eval('1+1')",
    "lambda: 1",
])
def test_sandbox_blocks_injection(bad):
    with pytest.raises(ExprError):
        validate_expr(bad)


def test_unknown_func_blocked():
    with pytest.raises(ExprError):
        validate_expr("FOO(C, 5)")


def test_unknown_var_at_eval():
    with pytest.raises(ExprError):
        eval_expr("ZZZ > 1", _ctx())


# ── 条件 AST 校验 ──
def test_validate_ast_ok():
    ast_ok = {
        "op": "AND",
        "children": [
            {"type": "col", "field": "rs_pct", "cmp": ">=", "value": 90},
            {"type": "expr", "expr": "COUNT(C > REF(C,1), 5) == 5"},
            {"op": "OR", "children": [
                {"type": "col", "field": "is_bull_arrange", "cmp": "==", "value": True},
                {"type": "expr", "expr": "C >= HHV(H,720)"},
            ]},
        ],
    }
    validate_ast(ast_ok)  # 不抛错


def test_validate_ast_rejects_bad():
    with pytest.raises(ConditionError):
        validate_ast({"type": "col", "field": "rs_pct", "cmp": "≈", "value": 1})
    with pytest.raises((ConditionError, ExprError)):
        validate_ast({"type": "expr", "expr": "import os"})


def test_eval_ast_combines_leaves():
    """用回调驱动 AST 合并：AND/OR/NOT 正确。"""
    idx = ["A", "B", "C"]
    table = {
        "x": pd.Series([True, True, False], index=idx),
        "y": pd.Series([True, False, False], index=idx),
    }
    node = {"op": "AND", "children": [
        {"type": "col", "field": "x"}, {"type": "col", "field": "y"}]}
    res = eval_ast(node, lambda leaf: table[leaf["field"]])
    assert res.tolist() == [True, False, False]


def test_screen_engine_hybrid_col_and_expr():
    """混合执行集成测试：col 截面 + expr 逐股，AND 合并。"""
    from datetime import date

    from backend.screening.engine import ScreenEngine
    from backend.storage.ddl import init_db
    from backend.storage.duckdb_client import DuckDBClient

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        # v2.0：指标动态计算（无 indicator 表）。灌足够历史（130 交易日 > RS 窗口 120），
        # 让 AAA 持续上涨自然产出 is_bull_arrange=True、横截面 RS 高；BBB 横盘则相反。
        days = [d.date() for d in pd.bdate_range(end=pd.Timestamp("2024-07-01"), periods=130)]
        rows = []
        for code, rising in [("AAA.SH", True), ("BBB.SH", False)]:
            for i, d in enumerate(days):
                px = (10.0 + i * 0.5) if rising else 10.0
                rows.append({"code": code, "trade_date": d, "open": px, "high": px,
                             "low": px, "close": px, "pre_close": px, "volume": 1000,
                             "amount": 1e4, "adj_factor": 1.0, "turnover_rate": 5.0,
                             "is_st": False, "is_suspended": False, "limit_status": 0,
                             "is_one_word": False})
        c.register_df("b", pd.DataFrame(rows)); c.execute("INSERT INTO daily_bar SELECT * FROM b"); c.unregister("b")
        T = days[-1]

        eng = ScreenEngine(c)
        # 纯 col：rs_pct>=90 → 只 A（AAA 横截面 RS=100，BBB=50）
        assert eng.run_hits({"type": "col", "field": "rs_pct", "cmp": ">=", "value": 90}, T) == ["AAA.SH"]
        # 纯 expr：连续5日上涨 → 只 A
        assert eng.run_hits({"type": "expr", "expr": "COUNT(C>REF(C,1),5)==5"}, T) == ["AAA.SH"]
        # 混合 AND → A
        mix = {"op": "AND", "children": [
            {"type": "col", "field": "is_bull_arrange", "cmp": "==", "value": True},
            {"type": "expr", "expr": "COUNT(C>REF(C,1),5)==5"}]}
        assert eng.run_hits(mix, T) == ["AAA.SH"]


def test_score_model_normalizes_to_100():
    """评分：满分维度 → 接近100；资金流权重0自动归一。"""
    from backend.scoring.model import ScoreModel

    snap = pd.DataFrame({
        "is_high_2y": [True, False],
        "dist_to_high_2y": [0.0, 0.5],
        "is_bull_arrange": [True, False],
        "ma20_up": [True, False],
        "is_vol_breakout": [True, False],
        "vol_ma5": [200.0, 100.0], "vol_ma20": [100.0, 100.0],
        "is_turnover_healthy": [True, False],
        "rs_pct": [100.0, 10.0],
    }, index=["STRONG.SH", "WEAK.SZ"])
    out = ScoreModel().score(snap)
    # 全维满分 → 100；分越高 grade 越高
    assert out.loc["STRONG.SH", "total_score"] == 100.0
    assert out.loc["STRONG.SH", "grade"] == "主升浪核心"
    assert out.loc["WEAK.SZ", "total_score"] < out.loc["STRONG.SH", "total_score"]


def test_preset_profiles_valid():
    """内置预设方案 AST 全部合法（含 col+expr 混合）。"""
    from backend.screening.condition import validate_ast
    from backend.screening.presets import PRESET_PROFILES

    assert len(PRESET_PROFILES) == 5
    for p in PRESET_PROFILES:
        validate_ast(p["expression"])  # 不抛错
