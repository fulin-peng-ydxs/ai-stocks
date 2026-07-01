"""M3 API 冒烟测试（打真实库，库内已有指标/榜单/方案）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def _sys_headers() -> dict:
    """系统管理员(admin) token 头：stage2·T5 起 /api/** 受鉴权中间件保护，冒烟测试需带 token。

    JWT 密钥由 conftest 设默认；admin perm_ver 取自真实 PG。PG/密钥不可用则返回空头，
    由下方 _real_db_ready() 探测到 401 后整组跳过（视为库/依赖不可用）。
    """
    try:
        from backend.auth.jwt_tokens import issue_access
        from backend.storage.pg_client import get_pg_client

        pv = int(get_pg_client().query_df(
            "SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
        return {"Authorization": "Bearer " + issue_access("admin", "default", "system", pv)}
    except Exception:  # noqa: BLE001
        return {}


# 认证 client：默认带 system token（TestClient 支持默认头），所有冒烟调用自动携带
client = TestClient(app, headers=_sys_headers())


def _real_db_ready() -> bool:
    """真实库能否独占可用。DuckDB 同库仅允许单写者：本机正跑着后端 dev 服务时库被锁，
    这组"打真实库"的冒烟测试连不上。探测一次，连不上/未种子化则整组跳过而非误报 failed。"""
    try:
        r = client.get("/api/data/status")
        return r.status_code == 200 and r.json().get("code") == 0
    except Exception:  # noqa: BLE001
        return False


if not _real_db_ready():
    pytest.skip(
        "真实库不可用（被占用/锁冲突/未种子化），跳过 API 冒烟测试；"
        "释放占用 data/ai_stocks.duckdb 的进程后重跑。",
        allow_module_level=True,
    )


def _data(resp):
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


def test_health():
    _data(client.get("/api/health"))


def test_profiles_list():
    data = _data(client.get("/api/profiles"))
    assert isinstance(data, list)
    # 预设方案应已入库（seed_presets 跑过）
    ids = [p["id"] for p in data]
    assert "preset_trend_leader" in ids


def test_scores_top():
    data = _data(client.get("/api/scores/top?top=10"))
    assert "list" in data and len(data["list"]) <= 10


def test_stocks_list_and_bars():
    lst = _data(client.get("/api/stocks?q=600000"))
    assert lst["total"] >= 1
    bars = _data(client.get("/api/stocks/600000.SH/bars?lookback=5"))
    assert len(bars["bars"]) >= 1
    assert {"date", "open", "high", "low", "close", "volume"} <= set(bars["bars"][0])


def test_data_status():
    data = _data(client.get("/api/data/status"))
    assert "latest_trade_date" in data and data["distinct_codes"] > 0


def test_screen_run_expr():
    """动态表达式筛选 API：命中带股票名称（前端筛选页依赖）。"""
    body = {"expression": {"type": "expr", "expr": "C >= HHV(C,60)"}}
    data = _data(client.post("/api/screen/run", json=body))
    assert "count" in data and "hits" in data
    assert data["count"] == len(data["hits"])
    if data["hits"]:
        assert {"code", "name"} <= set(data["hits"][0])


def test_screen_run_preset():
    """预设方案筛选 API。"""
    data = _data(client.post("/api/screen/run", json={"profile_id": "preset_trend_leader"}))
    assert "count" in data and isinstance(data["hits"], list)


def test_spa_fallback():
    """前端路由深链接/刷新需回退到 index.html（T-M4-7 实测踩坑修复）。"""
    from pathlib import Path

    from backend.config import PROJECT_ROOT

    if not (PROJECT_ROOT / "frontend" / "dist" / "index.html").exists():
        return  # 未构建前端时跳过
    resp = client.get("/board")
    assert resp.status_code == 200
    assert "<!doctype html" in resp.text.lower() or "<div id=\"app\">" in resp.text
    # 未匹配的 API 路径仍明确 404，不被前端兜底吞掉
    assert client.get("/api/definitely-not-a-route").status_code == 404


def test_concurrent_queries():
    """并发请求共享 DuckDB 连接不再 500（连接加锁串行化修复）。"""
    from concurrent.futures import ThreadPoolExecutor

    paths = ["/api/data/status", "/api/data/quality?size=10",
             "/api/scores/top?top=5", "/api/stocks?q=600000"]
    with ThreadPoolExecutor(max_workers=4) as ex:
        codes = list(ex.map(lambda p: client.get(p).status_code, paths * 3))
    assert all(c == 200 for c in codes), codes
