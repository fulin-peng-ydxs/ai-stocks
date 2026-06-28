"""FastAPI 应用入口（SDD §3 接口层）。

启动：
    uvicorn backend.main:app --reload
或：
    python -m backend.cli serve

约定：
- 统一前缀 /api，统一响应 {code, msg, data}。
- 业务异常 AIStocksError 统一捕获映射。
- 生产期 frontend/dist 由 StaticFiles 托管（M4 接入；现做存在性判断）。
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.backtest import router as backtest_router
from backend.api.board import router as board_router
from backend.api.config import router as config_router
from backend.api.health import router as health_router
from backend.api.indicators import router as indicators_router
from backend.api.layout import router as layout_router
from backend.api.profiles import router as profiles_router
from backend.api.score_profiles import router as score_profiles_router
from backend.api.trade_profiles import router as trade_profiles_router
from backend.api.stock_groups import router as stock_groups_router
from backend.api.stocks import router as stocks_router
from backend.api.data_tasks import router as data_tasks_router
from backend.api.data_admin import router as data_admin_router
from backend.api.training import router as training_router
from backend.common.exceptions import AIStocksError
from backend.common.logging import get_logger
from backend.config import PROJECT_ROOT, get_settings

log = get_logger("api.main")


def create_app() -> FastAPI:
    app = FastAPI(
        title="A股趋势龙头选股、打分与回测系统",
        description="本地 EOD 选股 + 打分 + 回测（FastAPI + Vue + DuckDB）",
        version="0.1.0",
    )

    # 开发期允许本地前端跨域（生产期同源托管）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 业务异常统一处理 ──
    @app.exception_handler(AIStocksError)
    async def _handle_biz_error(_: Request, exc: AIStocksError) -> JSONResponse:
        log.warning("业务异常 code=%s msg=%s", exc.code, exc.msg)
        return JSONResponse(
            status_code=200, content={"code": exc.code, "msg": exc.msg, "data": None}
        )

    # ── 路由注册 ──
    app.include_router(health_router)
    app.include_router(profiles_router)
    app.include_router(board_router)
    app.include_router(stocks_router)
    app.include_router(backtest_router)
    app.include_router(config_router)
    app.include_router(indicators_router)
    app.include_router(layout_router)
    app.include_router(score_profiles_router)
    app.include_router(trade_profiles_router)
    app.include_router(stock_groups_router)
    app.include_router(data_tasks_router)
    app.include_router(data_admin_router)
    app.include_router(training_router)

    # ── 前端静态托管（M4：frontend/dist 存在时生效）──
    # 关键：SPA 前端路由（/board、/stocks/xxx）在客户端，刷新/深链接需回退到
    # index.html，否则 StaticFiles 找不到对应文件会返回 404（T-M4-7 实测踩到）。
    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.exists():
        index_file = dist / "index.html"
        assets_dir = dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa_fallback(path: str) -> FileResponse:
            # /api/* 未匹配到的，明确 404（避免把 API 误兜成前端页面）
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            target = dist / path
            if path and target.is_file():
                return FileResponse(str(target))  # favicon、vite.svg 等真实文件
            return FileResponse(str(index_file))  # 其余一律回退到 SPA 入口
        log.info("前端静态资源已挂载（含 SPA 回退）: %s", dist)

    # ── 启动：混合持久层连通性自检（stage1 R1）──
    # 行情 DuckDB + 资产 PostgreSQL + 短状态 Redis 三类存储任一不通即明确启动失败，
    # 避免运行期才暴露连接问题（密码不进异常信息，见各 client）。
    @app.on_event("startup")
    def _check_storages() -> None:
        from backend.storage import get_pg_client, get_redis_client

        if not get_pg_client().ping():
            raise RuntimeError("PostgreSQL 连通性自检失败：ping 未返回预期结果")
        if not get_redis_client().ping():
            raise RuntimeError("Redis 连通性自检失败：ping 未返回 PONG")
        # 幂等建 PG 资产/骨架表 + seed 默认租户/管理员（一次性，避免每次构造仓库重建）
        from backend.storage.pg_ddl import init_pg_db

        init_pg_db()
        log.info("混合持久层自检通过：DuckDB + PostgreSQL + Redis 均连通，PG 资产表已就绪")

    # ── 启动：任务 reconcile（FR-DM-10）+ 定时调度（按 scheduler.enabled）──
    @app.on_event("startup")
    def _reconcile_tasks() -> None:
        try:
            from backend.services.async_task import AsyncTaskService
            AsyncTaskService().reconcile()
        except Exception as e:  # noqa: BLE001
            log.warning("启动期任务 reconcile 异常: %s", e)

    @app.on_event("startup")
    def _start_scheduler() -> None:
        from backend.scheduler.scheduler import start_scheduler
        start_scheduler()

    @app.on_event("shutdown")
    def _stop_scheduler() -> None:
        from backend.scheduler.scheduler import shutdown_scheduler
        shutdown_scheduler()

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "backend.main:app", host=s.server.host, port=s.server.port, log_level=s.server.log_level
    )
