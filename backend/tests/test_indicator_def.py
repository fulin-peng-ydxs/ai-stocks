"""技术指标定义/自定义测试（M2.1b）：定义 CRUD + 表达式渲染 + 自定义指标求值 + 评分端到端。"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.indicators.compute import build_params
from backend.indicators.definition import (
    IndicatorDefRepo,
    render_expression,
    validate_definition,
)
from backend.indicators.engine import IndicatorEngine
from backend.indicators.registry import (
    PRESET_CATEGORIES,
    PRESET_RELATIONS,
    REGISTRY,
    normalize_indicator_reference,
)
from backend.scoring.score_profile import (
    ScoreProfileModel,
    indicator_value_column,
    resolve_indicator,
    validate_profile,
)
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
    with pytest.raises(ValueError, match="不能大于"):
        render_expression("MA(C, {n})", {"n": 300}, [{
            "name": "n", "type": "int", "default": 20, "min": 2, "max": 250,
        }])


def test_definition_parameter_schema_is_strict_and_descriptive():
    params = validate_definition("MA(C, {window})", [{
        "name": "window", "label": "统计周期", "type": "int", "default": 20,
        "min": 2, "max": 250, "unit": "交易日", "description": "均线窗口",
    }])
    assert params[0]["unit"] == "交易日"
    with pytest.raises(ValueError, match="重复"):
        validate_definition("MA(C, {window})", [params[0], params[0]])
    with pytest.raises(ValueError, match="缺少参数定义"):
        validate_definition("MA(C, {window})", [])
    with pytest.raises(ValueError, match="未被表达式使用"):
        validate_definition("C > 0", params)
    with pytest.raises(ValueError, match="超出允许范围"):
        validate_definition("MA(C, {window})", [{**params[0], "default": 1}])


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


def test_registry_has_governance_layers_and_preset_relationships():
    with DuckDBClient(db_path=":memory:") as c:
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        assert repo.get("close")["layer"] == "field"
        assert repo.get("close")["name_cn"] == "股价"
        assert repo.get("close")["categories"] == ["价格"]
        assert repo.get("volume")["layer"] == "field"
        assert repo.get("pct_change")["layer"] == "metric"
        assert repo.get("new_high")["layer"] == "signal"
        assert repo.get("ma20")["layer"] == "preset"
        assert repo.get("ma20")["parent_key"] == "ma"
        assert repo.get("ma20")["preset_params"] == {"period": 20}
        assert PRESET_RELATIONS["is_high_1y"] == ("new_high", {"n": 240})
        assert repo.get("pct_change")["name_cn"] == "N日涨跌幅"


def test_close_field_can_be_used_by_scoring_profiles():
    items = [{
        "indicator": "close",
        "params": {},
        "weight": 1,
        "scoring": {"type": "linear", "min": 5, "max": 20},
    }]
    validate_profile(items)
    snap = pd.DataFrame({"close": [5.0, 20.0]}, index=["LOW.SH", "HIGH.SH"])
    assert ScoreProfileModel({"items": items}).score(snap)["total_score"].tolist() == [0.0, 100.0]


def test_preset_reference_normalizes_to_parent_and_fixed_params():
    assert normalize_indicator_reference("ma10", {"period": 99}) == (
        "ma", {"period": 10}, "ma10"
    )
    runtime = build_params()
    assert normalize_indicator_reference(
        "ma20_up", None, runtime
    ) == ("ma_up", {"n": 20, "k": runtime["ma_up_lookback"]}, "ma20_up")


def test_preset_and_parent_share_logical_value_column_but_prefer_attached_value():
    logical_column = indicator_value_column("ma", {"period": 10})
    assert indicator_value_column("ma10", {}) == logical_column
    snap = pd.DataFrame({"ma10": [10.0], logical_column: [11.0]}, index=["TEST.SH"])
    assert resolve_indicator("ma10", {}, snap).iloc[0] == 11.0


def test_historical_ma_preset_matches_generic_parent_at_runtime():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        IndicatorDefRepo(c).seed_builtins()
        target = _seed_stock(c, "MA.SH", [10 + i * 0.2 for i in range(40)])
        engine = IndicatorEngine(c)
        preset = engine.eval_named("ma10", {}, target, ["MA.SH"])
        generic = engine.eval_named("ma", {"period": 10}, target, ["MA.SH"])
        assert preset["MA.SH"] == pytest.approx(generic["MA.SH"])


def test_seed_builtins_fills_null_enabled_and_keeps_noop_updated_at():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        c.execute("UPDATE indicator_def SET enabled=NULL WHERE key IN ('ma5','total_mv')")

        repo.seed_builtins()
        assert repo.get("ma5")["enabled"] is True
        assert repo.get("total_mv")["enabled"] is False

        before = c.query_df(
            "SELECT key,updated_at FROM indicator_def WHERE is_builtin ORDER BY key"
        )
        repo.seed_builtins()
        after = c.query_df(
            "SELECT key,updated_at FROM indicator_def WHERE is_builtin ORDER BY key"
        )
        pd.testing.assert_frame_equal(after, before)


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
        for key in _MACD_KEYS:
            with pytest.raises(ValueError, match="内置指标不可删除"):
                repo.delete(key)


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


def test_range_amplitude_is_parameterized_and_point_in_time():
    with DuckDBClient(db_path=":memory:") as c:
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        target = _seed_stock(c, "RANGE.SH", [10, 11, 12, 13, 14, 15])
        value = IndicatorEngine(c).eval_named("range_amplitude_pct", {"window": 3}, target,
                                               ["RANGE.SH"])["RANGE.SH"]
        assert value == pytest.approx((15 / 13 - 1) * 100)


def test_expression_parameter_expands_history_beyond_default_engine_lookback():
    with DuckDBClient(db_path=":memory:") as c:
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        closes = [10.0] * 600
        closes[80] = 100.0  # 位于末日回看 550 日内，但超出旧固定 500 行加载范围。
        target = _seed_stock(c, "LONG.SH", closes)
        value = IndicatorEngine(c).eval_named(
            "range_amplitude_pct", {"window": 550}, target, ["LONG.SH"]
        )["LONG.SH"]
        assert value == pytest.approx(900.0)


def test_referenced_custom_definition_locks_semantics(monkeypatch):
    from backend.services.indicator_definition_service import IndicatorDefinitionService

    with DuckDBClient(db_path=":memory:") as c:
        repo = IndicatorDefRepo(c)
        repo.save_custom("locked_rule", "锁定规则", "bool", "C > MA(C, 5)")
        service = IndicatorDefinitionService(c, pg=object())
        monkeypatch.setattr(service, "references", lambda _key: {"count": 1})
        with pytest.raises(ValueError, match="不可原地修改"):
            service.save({
                "key": "locked_rule", "name_cn": "锁定规则", "dtype": "bool",
                "expression": "C > MA(C, 10)", "params": [], "category": "自定义",
                "categories": [], "desc": "",
            }, key="locked_rule")
        service.save({
            "key": "locked_rule", "name_cn": "新显示名", "dtype": "bool",
            "expression": "C > MA(C, 5)", "params": [], "category": "自定义",
            "categories": ["趋势"], "desc": "只改说明",
        }, key="locked_rule")
        assert repo.get("locked_rule")["name_cn"] == "新显示名"


def test_create_and_update_indicator_endpoints_have_distinct_semantics():
    from backend.services.indicator_definition_service import IndicatorDefinitionService

    with DuckDBClient(db_path=":memory:") as c:
        repo = IndicatorDefRepo(c)
        service = IndicatorDefinitionService(c, pg=object())
        body = {
            "key": "one_rule", "name_cn": "规则", "dtype": "bool",
            "expression": "C > 0", "params": [], "category": "自定义",
            "categories": [], "desc": "",
        }
        service.save(body)
        with pytest.raises(ValueError, match="已存在"):
            service.save(body)
        with pytest.raises(LookupError, match="不存在"):
            service.save({**body, "key": "missing_rule"}, key="missing_rule")
        with pytest.raises(LookupError, match="不存在"):
            service.delete("missing_rule")
        assert repo.get("one_rule") is not None


def test_reference_audit_covers_history_and_backtests_without_cross_db_join():
    from backend.services.indicator_definition_service import IndicatorDefinitionService

    class FakePg:
        def query_df(self, sql, _params=None):
            common = {"tenant_id": "t", "owner_user_id": "u", "id": "p1",
                      "name": "引用方案", "version": 2}
            if "FROM score_profile_version" in sql:
                return pd.DataFrame([{**common, "payload": '[{"indicator":"my_metric"}]'}])
            if "FROM backtest_run" in sql:
                return pd.DataFrame([{"id": "run-1"}])
            if "FROM trade_profile" in sql:
                return pd.DataFrame(columns=[*common, "buy_tree", "sell_tree"])
            return pd.DataFrame(columns=[*common, "payload"])

    with DuckDBClient(db_path=":memory:") as c:
        service = IndicatorDefinitionService(c, FakePg())
        result = service.references("my_metric")
        assert result["count"] == 1
        assert result["items"][0]["historical"] is True
        assert result["backtest_count"] == 1


def test_preview_returns_rendered_expression_and_value():
    from backend.services.indicator_definition_service import IndicatorDefinitionService

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        target = _seed_stock(c, "PREVIEW.SH", [10 + i for i in range(30)])
        result = IndicatorDefinitionService(c, pg=object()).preview({
            "dtype": "number", "expression": "(C / REF(C, {window}) - 1) * 100",
            "params": [{"name": "window", "label": "周期", "type": "int", "default": 5,
                        "min": 1, "max": 20, "unit": "交易日", "description": ""}],
            "values": {"window": 5}, "code": "PREVIEW.SH", "trade_date": target,
        })
        assert result["status"] == "ok"
        assert result["rendered_expression"] == "(C / REF(C, 5) - 1) * 100"
        assert result["value"] == pytest.approx((39 / 34 - 1) * 100)


def test_preview_distinguishes_history_field_empty_and_expression_failures():
    from backend.services.indicator_definition_service import IndicatorDefinitionService

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        target = _seed_stock(c, "DIAG.SH", [10 + i for i in range(5)])
        service = IndicatorDefinitionService(c, pg=object())
        history = service.preview({
            "dtype": "number", "expression": "REF(C, {window})",
            "params": [{"name": "window", "label": "周期", "type": "int",
                        "default": 10, "min": 1, "max": 20}],
            "values": {}, "code": "DIAG.SH", "trade_date": target,
        })
        missing = service.preview({
            "dtype": "number", "expression": "MISSING_FIELD + C",
            "params": [], "values": {}, "code": "DIAG.SH", "trade_date": target,
        })
        c.execute("UPDATE daily_bar SET turnover_rate=NULL WHERE code='DIAG.SH'")
        empty = service.preview({
            "dtype": "number", "expression": "TURN",
            "params": [], "values": {}, "code": "DIAG.SH", "trade_date": target,
        })
        expression_error = service.preview({
            "dtype": "number", "expression": "MA(C)",
            "params": [], "values": {}, "code": "DIAG.SH", "trade_date": target,
        })

        assert history["status"] == "history_insufficient"
        assert missing["status"] == "missing_field"
        assert empty["status"] == "empty_result"
        assert expression_error["status"] == "expression_error"


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


def test_same_expression_indicator_supports_multiple_parameter_sets():
    """同一表达式指标在一个方案中使用不同参数时，取值不能被首个实例覆盖。"""
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        IndicatorDefRepo(c).seed_builtins()
        target = _seed_stock(c, "RISE.SH", [10 + i * 0.3 for i in range(40)])
        eng = IndicatorEngine(c)
        snap = eng.wide_snapshot(target, target).set_index("code")
        items = [
            {"indicator": "consec_up", "params": {"n": 5}, "weight": 0.5,
             "scoring": {"type": "bool"}},
            {"indicator": "consec_up", "params": {"n": 50}, "weight": 0.5,
             "scoring": {"type": "bool"}},
        ]
        eng.attach_columns(snap, items, target)
        out = ScoreProfileModel({"items": items}).score(snap)
        assert out.loc["RISE.SH", "total_score"] == 50.0


def test_score_snapshot_hash_tracks_custom_definition_and_market_revision():
    from backend.scoring.snapshot import _current_param_hash

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        repo.save_custom("my_signal", "自定义", "bool", "C > MA(C, 5)")
        profile = {"items": [{"indicator": "my_signal"}]}
        initial = _current_param_hash(c, profile)

        repo.set_categories("my_signal", ["趋势"])
        assert _current_param_hash(c, profile) == initial

        repo.save_custom("my_signal", "自定义", "bool", "C > MA(C, 10)")
        definition_changed = _current_param_hash(c, profile)
        assert definition_changed != initial

        c.execute(
            "INSERT INTO data_update_log VALUES "
            "(nextval('seq_update_log'),'daily_bar','test',NULL,NULL,1,'success','',current_timestamp)"
        )
        assert _current_param_hash(c, profile) != definition_changed


def test_score_snapshot_hash_tracks_preset_semantics_but_not_layer_display():
    from backend.scoring.snapshot import _current_param_hash

    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = IndicatorDefRepo(c)
        repo.seed_builtins()
        profile = {"items": [{"indicator": "ma10"}]}
        initial = _current_param_hash(c, profile)

        c.execute("UPDATE indicator_def SET layer='metric' WHERE key='ma10'")
        assert _current_param_hash(c, profile) == initial

        c.execute(
            "UPDATE indicator_def SET preset_params=? WHERE key='ma10'",
            ['{"period":20}'],
        )
        preset_changed = _current_param_hash(c, profile)
        assert preset_changed != initial

        c.execute("UPDATE indicator_def SET expression='MA(C, {period}) + 1' WHERE key='ma'")
        assert _current_param_hash(c, profile) != preset_changed
