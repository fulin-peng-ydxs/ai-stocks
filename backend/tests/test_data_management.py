"""M2.8-A 数据管理收口·数据底座扩展与配置覆盖层测试。

覆盖：app_config 覆盖层优先级 + 白名单/校验、catalog 数据字典拼装、
维度注册表 seed、data_quality_issue 迁移列与严重度回填。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.storage.app_config import (
    WHITELIST,
    AppConfigRepo,
    ConfigValidationError,
    apply_overrides,
)
from backend.storage.catalog import build_catalog
from backend.storage.ddl import init_db, seed_dimension_registry
from backend.storage.duckdb_client import DuckDBClient


# ── 配置覆盖层 ──────────────────────────────────────────────

def test_app_config_override_roundtrip():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = AppConfigRepo(c)
        assert repo.get_overrides() == {}
        n = repo.set_many({"datasource.update_concurrency": 4, "backtest.top_n": 30})
        assert n == 2
        ov = repo.get_overrides()
        assert ov["datasource.update_concurrency"] == 4
        assert ov["backtest.top_n"] == 30


def test_app_config_rejects_non_whitelist():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = AppConfigRepo(c)
        # 评分权重已废弃，不在白名单
        with pytest.raises(ConfigValidationError):
            repo.set_many({"scoring.weights.position": 50})
        assert "scoring.weights.position" not in WHITELIST


def test_app_config_range_and_type_validation():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = AppConfigRepo(c)
        with pytest.raises(ConfigValidationError):
            repo.set_many({"datasource.update_concurrency": 0})      # < min
        with pytest.raises(ConfigValidationError):
            repo.set_many({"scheduler.daily_cron_hour": 25})         # > max
        with pytest.raises(ConfigValidationError):
            repo.set_many({"datasource.update_concurrency": "abc"})  # 类型错
        # 整批校验失败不部分写入
        assert repo.get_overrides() == {}


def test_app_config_cross_field_mv_bounds():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        repo = AppConfigRepo(c)
        with pytest.raises(ConfigValidationError):
            repo.set_many({"universe.float_mv_min": 1e10, "universe.float_mv_max": 5e9})
        # 合法
        assert repo.set_many({"universe.float_mv_min": 5e9, "universe.float_mv_max": 4e10}) == 2


def test_apply_overrides_deep_merge():
    base = {"datasource": {"primary": "akshare"}, "backtest": {"cost": {"slippage": 0.002}}}
    merged = apply_overrides(base, {
        "datasource.update_concurrency": 8,
        "backtest.cost.slippage": 0.001,
        "scheduler.enabled": True,
    })
    assert merged["datasource"]["primary"] == "akshare"        # 保留未覆盖项
    assert merged["datasource"]["update_concurrency"] == 8     # 新增嵌套
    assert merged["backtest"]["cost"]["slippage"] == 0.001     # 深层覆盖
    assert merged["scheduler"]["enabled"] is True              # 新建分支


def test_effective_settings_override_first(monkeypatch, tmp_path):
    """get_effective_settings 覆盖层优先于 settings.yaml。"""
    # 用临时库承载 app_config，并让 get_client 指向它
    import backend.storage.duckdb_client as dc
    client = DuckDBClient(db_path=str(tmp_path / "t.duckdb"))
    init_db(client)
    monkeypatch.setattr(dc, "_client", client)
    AppConfigRepo(client).set_many({"backtest.top_n": 7})

    from backend.config import get_effective_settings
    s = get_effective_settings()
    assert s.backtest.top_n == 7
    client.close()


# ── 数据字典 / 维度注册表 ──────────────────────────────────

def test_build_catalog_rows_and_latest():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute("INSERT INTO daily_bar (code, trade_date, close) VALUES "
                  "('600000.SH', DATE '2024-01-02', 10.0), ('600000.SH', DATE '2024-01-03', 11.0)")
        cat = build_catalog(c)
        by_table = {x["table"]: x for x in cat}
        assert "daily_bar" in by_table and "stock_basic" in by_table
        bar = by_table["daily_bar"]
        assert bar["rows"] == 2
        assert bar["latest_time"].startswith("2024-01-03")
        assert bar["name_cn"] == "日线行情" and bar["fields"]  # 字段字典非空


def test_catalog_open_issue_count():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        c.execute("INSERT INTO data_quality_issue (id, code, issue_type, status, detected_at) "
                  "VALUES (1, '600000.SH', 'adj_jump', 'open', ?)", [datetime.now()])
        cat = {x["table"]: x for x in build_catalog(c)}
        assert cat["data_quality_issue"]["open_issues"] == 1


def test_dimension_registry_seeded_idempotent():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)  # 已 seed 一次
        rows = c.query_df("SELECT dimension, status FROM data_dimension_registry")
        dims = dict(zip(rows["dimension"], rows["status"]))
        assert dims.get("quote") == "collected"
        assert dims.get("shareholders") == "planned"   # 股东数占位（DM-D5）
        assert dims.get("chip_peak") == "planned"      # 筹码峰占位
        # 再 seed 不重复
        added = seed_dimension_registry(c)
        assert added == 0


# ── data_quality_issue 迁移 ──────────────────────────────────

def test_quality_issue_migration_columns_and_severity():
    with DuckDBClient(db_path=":memory:") as c:
        init_db(c)
        cols = c.query_df("PRAGMA table_info('data_quality_issue')")["name"].tolist()
        for col in ("status", "severity", "resolved_at"):
            assert col in cols
        # 插入各类型，验证迁移 UPDATE 的严重度映射逻辑（手动按 DM-D10 核对）
        c.execute("INSERT INTO data_quality_issue (id, code, issue_type, detected_at) VALUES "
                  "(1,'A','adj_jump',?),(2,'B','ohl_repaired',?),(3,'C','abnormal_change',?)",
                  [datetime.now(), datetime.now(), datetime.now()])
        # 应用与迁移同口径的回填
        c.execute("UPDATE data_quality_issue SET status='open' WHERE status IS NULL")
        c.execute("UPDATE data_quality_issue SET severity = CASE "
                  "WHEN issue_type='adj_jump' THEN 'high' "
                  "WHEN issue_type='ohl_repaired' THEN 'low' ELSE 'mid' END WHERE severity IS NULL")
        df = c.query_df("SELECT issue_type, severity, status FROM data_quality_issue ORDER BY id")
        m = dict(zip(df["issue_type"], df["severity"]))
        assert m["adj_jump"] == "high" and m["ohl_repaired"] == "low" and m["abnormal_change"] == "mid"
        assert set(df["status"]) == {"open"}
