"""技术指标定义/自定义测试（M2.1b）：定义 CRUD + 表达式渲染 + 自定义指标求值 + 评分端到端。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.indicators.definition import IndicatorDefRepo, render_expression
from backend.indicators.engine import IndicatorEngine
from backend.scoring.score_profile import ScoreProfileModel
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_render_expression_substitutes_and_validates():
    assert render_expression("COUNT(C > REF(C,1), {n}) == {n}", {"n": 5}) == "COUNT(C > REF(C,1), 5) == 5"
    # 用默认参数
    assert render_expression("MA(C, {n})", None, [{"name": "n", "default": 20}]) == "MA(C, 20)"
    with pytest.raises(ValueError):
        render_expression("__import__('os')", {})            # 注入 → 白名单拒绝
    with pytest.raises(ValueError):
        render_expression("COUNT(C, {n})", {})               # 缺参数


def test_def_repo_seed_crud_and_builtin_protection():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = IndicatorDefRepo(c)
        n = repo.seed_builtins()
        assert n >= 20
        assert repo.get("consec_up")["kind"] == "expr"      # 内置表达式型
        # 自定义
        repo.save_custom("my_rule", "我的规则", "bool", "COUNT(C > REF(C,1), {n}) == {n}",
                         params=[{"name": "n", "label": "天数", "type": "int", "default": 4}])
        assert repo.get("my_rule")["is_builtin"] is False
        # 启停
        repo.set_enabled("my_rule", False)
        assert repo.get("my_rule")["enabled"] is False
        assert len(repo.list(include_disabled=False)) < len(repo.list(include_disabled=True))
        # 内置不可删 / 不可被自定义覆盖
        with pytest.raises(ValueError):
            repo.delete("consec_up")
        with pytest.raises(ValueError):
            repo.save_custom("consec_up", "x", "bool", "C > 0")
        # 删自定义
        repo.delete("my_rule")
        assert repo.get("my_rule") is None
        # 非法表达式拒绝保存
        with pytest.raises(ValueError):
            repo.save_custom("bad", "坏", "bool", "C > ")


def _seed_stock(c, code, closes):
    """按收盘序列灌一只票（open=high=low=close，足够长）。"""
    days = [d.date() for d in pd.bdate_range(end=pd.Timestamp("2024-06-03"), periods=len(closes))]
    rows = [{"code": code, "trade_date": d, "open": px, "high": px, "low": px, "close": px,
             "pre_close": px, "volume": 1e6, "amount": px * 1e6, "adj_factor": 1.0,
             "turnover_rate": 5.0, "is_st": False, "is_suspended": False,
             "limit_status": 0, "is_one_word": False}
            for d, px in zip(days, closes)]
    c.register_df("t", pd.DataFrame(rows)); c.execute("INSERT INTO daily_bar SELECT * FROM t"); c.unregister("t")
    return days[-1]


def test_eval_named_expr_indicator_consec_up():
    """自定义表达式指标「连续上涨N天」逐股点时求值正确。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        IndicatorDefRepo(c).seed_builtins()
        # RISE 末尾连涨≥5；FLAT 横盘
        T = _seed_stock(c, "RISE.SH", [10 + i * 0.3 for i in range(40)])
        _seed_stock(c, "FLAT.SH", [10.0] * 40)
        eng = IndicatorEngine(c)
        s5 = eng.eval_named("consec_up", {"n": 5}, T, ["RISE.SH", "FLAT.SH"])
        assert bool(s5["RISE.SH"]) is True and bool(s5["FLAT.SH"]) is False
        # 动态参数：换 6 天仍成立（RISE 全程上涨）
        s6 = eng.eval_named("consec_up", {"n": 6}, T, ["RISE.SH", "FLAT.SH"])
        assert bool(s6["RISE.SH"]) is True


def test_custom_indicator_in_scoring_end_to_end():
    """自定义指标可作为评分项：attach_columns 补列 → ScoreProfileModel 打分。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        IndicatorDefRepo(c).seed_builtins()
        T = _seed_stock(c, "RISE.SH", [10 + i * 0.3 for i in range(40)])
        _seed_stock(c, "FLAT.SH", [10.0] * 40)
        eng = IndicatorEngine(c)
        snap = eng.wide_snapshot(T, T).set_index("code")
        items = [{"indicator": "consec_up", "params": {"n": 5}, "weight": 1.0, "scoring": {"type": "bool"}}]
        eng.attach_columns(snap, items, T)
        assert "consec_up" in snap.columns
        out = ScoreProfileModel({"items": items}).score(snap)
        assert out.loc["RISE.SH", "total_score"] == 100.0   # 连涨满足→100
        assert out.loc["FLAT.SH", "total_score"] == 0.0
