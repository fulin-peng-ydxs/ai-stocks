"""未捕获异常兜底（HTTP 500 → {code:5000,msg}）、AIStocksError 软失败与入参校验（422 → 4000）测试。

用 create_app() + TestClient 且不进 lifespan，避免触发 DuckDB/PG/Redis 启动副作用；
未捕获异常靠 `raise_server_exceptions=False` 走异常处理器而非直接重抛。
"""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from backend.common.exceptions import AIStocksError, NotFoundError
from backend.main import create_app


def _minimal_5xx_app() -> FastAPI:
    """不含真实存储的极简 app：只挂 create_app 的异常兜底 handler + 一条抛异常的路由。

    不依赖 AuthMiddleware（health 是白名单），无需 token 即可触发。
    """
    from backend.main import app as _main_app

    exceptions = getattr(_main_app, "exception_handlers", {})
    app = FastAPI()
    app.exception_handlers.update(exceptions)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    @app.get("/biz")
    def biz() -> None:
        raise NotFoundError("板块不存在")

    @app.get("/soft")
    def soft() -> None:
        raise AIStocksError("软失败")

    @app.get("/bounded")
    def bounded(size: int = Query(20, ge=1, le=100)) -> None:
        return None

    return app


def test_uncaught_exception_maps_to_code_5000():
    """未捕获异常（500）转译为 {code:5000, msg:中文}，不把英文系统文本回传。"""
    client = TestClient(_minimal_5xx_app(), raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == 5000
    assert body["msg"] == "服务内部错误，请稍后重试"
    assert body["data"] is None
    assert "Internal Server Error" not in resp.text


def test_biz_error_keeps_business_code_and_http_status():
    """已定义的业务异常仍走各自 code/http_status，不被 500 兜底抢占。"""
    client = TestClient(_minimal_5xx_app(), raise_server_exceptions=False)
    resp = client.get("/biz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 4004
    assert body["msg"] == "板块不存在"


def test_soft_error_default_200():
    """AIStocksError 默认 http_status=200 的软失败口径不变。"""
    client = TestClient(_minimal_5xx_app(), raise_server_exceptions=False)
    resp = client.get("/soft")
    assert resp.status_code == 200
    assert resp.json()["code"] == 5000


def test_validation_error_maps_to_code_4000_chinese_msg():
    """FastAPI 422 校验失败转译 {code:4000,msg:中文}，不把 pydantic 英文/数组 detail 回传。"""
    client = TestClient(_minimal_5xx_app(), raise_server_exceptions=False)
    resp = client.get("/bounded?size=200")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 4000
    assert body["msg"] == "参数 size 不合法"
    assert body["data"] is None
    assert "Input should be" not in resp.text
    assert "[" not in resp.text  # 数组 detail 不再原样回传
