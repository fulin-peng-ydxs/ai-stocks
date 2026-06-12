"""M0 冒烟测试：配置加载、DuckDB 连通、健康检查接口。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.config import get_settings, reload_settings
from backend.main import app
from backend.storage import DuckDBClient


def test_settings_load():
    s = get_settings()
    assert s.datasource.history_years == 5
    assert s.backtest.benchmark_main == "000905.SH"
    assert s.scoring.weights["position"] == 30
    assert s.universe.boards == ["主板", "创业板", "科创板"]


def test_settings_reload_singleton():
    s1 = get_settings()
    s2 = reload_settings()
    # 重载后仍是有效配置
    assert s2.scoring.top_n == s1.scoring.top_n


def test_duckdb_in_memory():
    with DuckDBClient(db_path=":memory:") as client:
        df = client.query_df("SELECT 1 AS x")
        assert df.iloc[0]["x"] == 1


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "up"
    # duckdb_ok 反映真实连通状态（回填持锁时可能为 False，属预期）；仅校验字段契约
    assert isinstance(body["data"]["duckdb_ok"], bool)
