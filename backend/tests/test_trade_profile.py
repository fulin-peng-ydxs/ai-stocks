"""买卖指标方案测试（M2.3）：条件树求值 + 校验 + 仓库 CRUD/版本。"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.indicators.definition import IndicatorDefRepo
from backend.signals.trade_profile import (
    TradeProfileRepo,
    collect_indicators,
    eval_conditions,
    validate_trade_profile,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def _snap():
    return pd.DataFrame({
        "rs_pct": [90.0, 50.0, 10.0],
        "is_vol_breakout": [True, False, True],
        "dist_to_high_2y": [0.0, 0.2, 0.5],
    }, index=["A", "B", "C"])


def test_eval_leaf_bool_and_number():
    snap = _snap()
    assert list(eval_conditions({"indicator": "rs_pct", "cmp": ">=", "value": 80}, snap)) == [True, False, False]
    assert list(eval_conditions({"indicator": "is_vol_breakout", "cmp": "==", "value": True}, snap)) == [True, False, True]
    assert list(eval_conditions({"indicator": "dist_to_high_2y", "cmp": "between", "value": [0.0, 0.25]}, snap)) == [True, True, False]


def test_eval_and_or():
    snap = _snap()
    and_tree = {"op": "AND", "children": [
        {"indicator": "rs_pct", "cmp": ">=", "value": 80},
        {"indicator": "is_vol_breakout", "cmp": "==", "value": True}]}
    assert list(eval_conditions(and_tree, snap)) == [True, False, False]
    or_tree = {"op": "OR", "children": [
        {"indicator": "rs_pct", "cmp": ">=", "value": 80},
        {"indicator": "is_vol_breakout", "cmp": "==", "value": True}]}
    assert list(eval_conditions(or_tree, snap)) == [True, False, True]


def test_collect_indicators():
    tree = {"op": "AND", "children": [
        {"indicator": "bull_arrange", "cmp": "==", "value": True},
        {"op": "OR", "children": [{"indicator": "ma_bias", "params": {"n": 20}, "cmp": "<", "value": 0}]}]}
    keys = [c["indicator"] for c in collect_indicators(tree)]
    assert set(keys) == {"bull_arrange", "ma_bias"}


def test_validate_rules():
    known = {"bull_arrange", "is_vol_breakout", "ma_bias"}
    buy = {"op": "AND", "children": [{"indicator": "bull_arrange", "cmp": "==", "value": True}]}
    sell = {"op": "OR", "children": [{"indicator": "ma_bias", "params": {"n": 20}, "cmp": "<", "value": 0}]}
    validate_trade_profile(buy, sell, None, known)                       # ok（有卖出条件）
    validate_trade_profile(buy, {}, {"stop_loss": 0.08}, known)          # ok（无卖出但有兜底）
    with pytest.raises(ValueError):
        validate_trade_profile({}, sell, None, known)                    # 买入为空
    with pytest.raises(ValueError):
        validate_trade_profile(buy, {}, None, known)                     # 无卖出也无兜底
    with pytest.raises(ValueError):
        validate_trade_profile({"op": "AND", "children": [{"indicator": "不存在", "cmp": "==", "value": True}]},
                               sell, None, known)                        # 未知指标


def test_repo_crud_version():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        IndicatorDefRepo(c).seed_builtins()                              # 提供 known 指标
        repo = TradeProfileRepo(c)
        buy = {"op": "AND", "children": [{"indicator": "bull_arrange", "cmp": "==", "value": True}]}
        sell = {"op": "OR", "children": [{"indicator": "ma_bias", "params": {"n": 20}, "cmp": "<", "value": 0}]}
        v1 = repo.save("t1", "方案一", buy, sell, {"stop_loss": 0.08})
        assert v1 == 1
        assert repo.save("t1", "方案一", buy, sell, {"stop_loss": 0.08}) == 1   # 不变不增版本
        buy2 = {"op": "AND", "children": [
            {"indicator": "bull_arrange", "cmp": "==", "value": True},
            {"indicator": "is_vol_breakout", "cmp": "==", "value": True}]}
        assert repo.save("t1", "方案一", buy2, sell, {"stop_loss": 0.08}) == 2  # 买入变 → +1
        got = repo.get("t1")
        assert got["version"] == 2 and len(got["buy_tree"]["children"]) == 2
        assert got["backstop"]["stop_loss"] == 0.08
        assert len(repo.versions("t1")) == 2
        repo.delete("t1")
        assert repo.get("t1") is None
