"""技术指标定义/自定义测试（M2.1b）：定义 CRUD + 表达式渲染 + 自定义指标求值 + 评分端到端。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.indicators.definition import IndicatorDefRepo, render_expression
from backend.indicators.engine import IndicatorEngine
from backend.indicators.registry import PRESET_CATEGORIES, REGISTRY
from backend.scoring.score_profile import ScoreProfileModel
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient

_MACD_KEYS = {
    "macd_diff",
    "macd_dea",
    "macd_hist",
    "macd_golden_cross",
    "macd_dead_cross",
}


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


def test_seed_builtins_is_full_idempotent_and_preserves_admin_state():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = IndicatorDefRepo(c)
        assert repo.seed_builtins() == len(REGISTRY)
        assert set(c.query_df(
            "SELECT key FROM indicator_def WHERE is_builtin"
        )["key"]) == {d.key for d in REGISTRY}

        repo.set_enabled("ma5", False)
        repo.set_categories("ma5", [])
        repo.set_enabled("macd_dead_cross", False)
        repo.set_categories("macd_dead_cross", ["风险事件"])
        c.execute("UPDATE indicator_def SET name_cn='旧名称' WHERE key IN ('ma5','macd_dead_cross')")

        assert repo.seed_builtins() == len(REGISTRY)
        assert len(repo.list()) == len(REGISTRY)
        assert repo.get("ma5")["name_cn"] == "MA5"
        assert repo.get("ma5")["enabled"] is False
        assert repo.get("ma5")["categories"] == []
        assert repo.get("macd_dead_cross")["name_cn"] == "MACD死叉"
        assert repo.get("macd_dead_cross")["enabled"] is False
        assert repo.get("macd_dead_cross")["categories"] == ["风险事件"]
        assert "macd_dead_cross" not in {
            item["key"] for item in repo.list(include_disabled=False)
        }


def test_macd_builtin_metadata_and_registry_api(monkeypatch):
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        items = {item["key"]: item for item in repo.list() if item["key"] in _MACD_KEYS}
        assert set(items) == _MACD_KEYS
        for key, item in items.items():
            assert item["dtype"] == ("bool" if key.endswith("_cross") else "number")
            assert item["category"] == "趋势"
            assert item["categories"] == ["趋势", "动量"]
            assert item["direction"] is None
            assert item["params"] == []
            assert item["kind"] == "builtin"
            assert item["is_builtin"] is True
            assert item["enabled"] is True
            assert "12/26/9" in item["desc"]
            assert "前复权" in item["desc"]
            assert PRESET_CATEGORIES[key] == ["趋势", "动量"]

        monkeypatch.setattr("backend.indicators.definition.get_client", lambda: c)
        from backend.api.indicators import indicators_registry

        response = indicators_registry(include_disabled=False)
        api_keys = {item["key"] for item in response.data["items"]}
        assert response.code == 0
        assert _MACD_KEYS <= api_keys
        assert response.data["count"] == sum(1 for item in REGISTRY if item.enabled)


def test_application_startup_seeds_full_builtin_registry(monkeypatch):
    with DuckDBClient(db_path=":memory:") as c:
        import backend.main as main_module
        import backend.storage as storage_module
        import backend.storage.pg_ddl as pg_ddl_module

        class _ReadyDependency:
            @staticmethod
            def ping() -> bool:
                return True

        class _ReadySettings:
            @staticmethod
            def jwt_secret() -> str:
                return "test-jwt-secret"

        monkeypatch.setattr(storage_module, "get_client", lambda: c)
        monkeypatch.setattr(storage_module, "get_pg_client", _ReadyDependency)
        monkeypatch.setattr(storage_module, "get_redis_client", _ReadyDependency)
        monkeypatch.setattr(pg_ddl_module, "init_pg_db", lambda: None)
        monkeypatch.setattr(main_module, "get_settings", _ReadySettings)

        app = main_module.create_app()
        startup = next(fn for fn in app.router.on_startup if fn.__name__ == "_check_storages")
        startup()
        assert set(c.query_df(
            "SELECT key FROM indicator_def WHERE is_builtin"
        )["key"]) == {d.key for d in REGISTRY}


def _seed_stock(c, code, closes):
    """按收盘序列灌一只票（open=high=low=close，足够长）。"""
    days = [d.date() for d in pd.bdate_range(end=pd.Timestamp("2024-06-03"), periods=len(closes))]
    rows = [{"code": code, "trade_date": d, "open": px, "high": px, "low": px, "close": px,
             "pre_close": px, "volume": 1e6, "amount": px * 1e6, "adj_factor": 1.0,
             "turnover_rate": 5.0, "is_st": False, "is_suspended": False,
             "limit_status": 0, "is_one_word": False}
            for d, px in zip(days, closes)]
    c.register_df("t", pd.DataFrame(rows)); c.execute("INSERT INTO daily_bar BY NAME SELECT * FROM t"); c.unregister("t")
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
