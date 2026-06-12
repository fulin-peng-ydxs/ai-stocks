"""M3 API 冒烟测试（打真实库，库内已有指标/榜单/方案）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


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
