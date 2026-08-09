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

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.auth.deps import require_system
from backend.api.audit import router as audit_router
from backend.auth.middleware import AuthMiddleware, SecurityMiddleware
from backend.api.auth import router as auth_router
from backend.api.backtest import router as backtest_router
from backend.api.board import router as board_router
from backend.api.board_candidates import router as board_candidates_router
from backend.api.config import router as config_router
from backend.api.health import router as health_router
from backend.api.indicators import router as indicators_router
from backend.api.layout import router as layout_router
from backend.api.profiles import router as profiles_router
from backend.api.score_profiles import router as score_profiles_router
from backend.api.trade_profiles import router as trade_profiles_router
from backend.api.user_preferences import router as user_preferences_router
from backend.api.stock_groups import router as stock_groups_router
from backend.api.stocks import router as stocks_router
from backend.api.data_tasks import router as data_tasks_router
from backend.api.data_admin import router as data_admin_router
from backend.api.dicts import router as dict_router
from backend.api.training import router as training_router
from backend.api.users import router as users_router
from backend.api.roles import router as roles_router
from backend.api.menus import router as menus_router
from backend.api.resources import router as resources_router
from backend.api.tenants import router as tenants_router
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

    # 中间件顺序（add 越晚越外层）：Auth(内) → Security(中) → CORS(外)。
    # Auth：机制性默认 deny + 上下文注入（T5）。
    # Security：全局限流 backstop + 安全响应头（T6），在鉴权前拦、头覆盖所有响应。
    # CORS：最外层，保证拒绝响应也带 CORS 头，预检 OPTIONS 先处理。
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SecurityMiddleware)

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
        # 业务异常默认 HTTP 200 + 软失败 code；认证/鉴权/限流类用真实 401/403/429（exc.http_status）
        log.warning("业务异常 code=%s msg=%s", exc.code, exc.msg)
        return JSONResponse(
            status_code=getattr(exc, "http_status", 200),
            content={"code": exc.code, "msg": exc.msg, "data": None},
        )

    # 鉴权关键依赖 Redis 故障兜底：任何逃逸到路由层的 redis 错误 → fail-closed 503（非 500）。
    # 正常路径 session_store 已翻译为 ServiceUnavailableError(由上方 handler 出 503)；此为防御性兜底。
    @app.exception_handler(redis.RedisError)
    async def _handle_redis_error(_: Request, exc: redis.RedisError) -> JSONResponse:
        log.warning("Redis 依赖不可用，fail-closed 503: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"code": 5030, "msg": "服务暂时不可用（依赖 Redis），请稍后重试", "data": None},
        )

    # ── 路由注册 ──
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(profiles_router)
    app.include_router(board_router)
    app.include_router(board_candidates_router)
    app.include_router(stocks_router)
    app.include_router(backtest_router)
    app.include_router(config_router)
    app.include_router(indicators_router)
    app.include_router(layout_router)
    app.include_router(score_profiles_router)
    app.include_router(trade_profiles_router)
    app.include_router(user_preferences_router)
    app.include_router(stock_groups_router)
    # 系统级 / 全市场写路由：整 router 挂 require_system 硬守卫（R8 最小切片，闭合注册越权窗口）。
    # stage4·T5：端点内已逐一叠加 require_system_perm 精确码（供路由扫描/审计识别），此处硬守卫保留作兜底。
    app.include_router(data_tasks_router, dependencies=[Depends(require_system)])
    app.include_router(data_admin_router, dependencies=[Depends(require_system)])
    app.include_router(audit_router)
    app.include_router(dict_router)
    app.include_router(training_router)
    # 用户管理（stage3·R10）：逐端点已挂 require_perm 精确码，不整 router gate（tenant_admin 经授权可用）
    app.include_router(users_router)
    # 角色管理（stage3·R11）：逐端点已挂守卫（CRUD/授权 require_system，assignable require_perm），不整 router gate
    app.include_router(roles_router)
    # 菜单管理（stage3·R12）：整 router 挂 require_system（全部端点系统专属）
    app.include_router(menus_router)
    # 功能点管理（stage3·R13）：整 router 挂 require_system
    app.include_router(resources_router)
    # 租户管理（stage3·R14）：整 router 挂 require_system
    app.include_router(tenants_router)

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
        from backend.storage import get_client, get_pg_client, get_redis_client

        # 行情 DuckDB（只读分析）及其平台指标定义：IndicatorDefRepo 会先幂等确保 schema，
        # 再持久化完整 REGISTRY；重复启动保留管理员对 builtin 的 enabled/categories 设置。
        try:
            market = get_client()
            market.query_df("SELECT 1 AS ok")
            from backend.indicators.definition import IndicatorDefRepo

            builtin_count = IndicatorDefRepo(market).seed_builtins()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"DuckDB 连通性或内置指标初始化失败：{e}") from e
        if not get_pg_client().ping():
            raise RuntimeError("PostgreSQL 连通性自检失败：ping 未返回预期结果")
        if not get_redis_client().ping():
            raise RuntimeError("Redis 连通性自检失败：ping 未返回 PONG")
        # 幂等建 PG 资产/骨架表 + seed 默认租户/管理员（一次性，避免每次构造仓库重建）
        from backend.storage.pg_ddl import init_pg_db

        init_pg_db()
        # 认证密钥自检（stage2·T2）：JWT 签名密钥无弱默认，缺失即启动失败（不留到首个请求才 500）
        get_settings().jwt_secret()
        log.info(
            "混合持久层自检通过：DuckDB + PostgreSQL + Redis 均连通，"
            "builtin 指标 %d 个、PG 资产表与 JWT 密钥已就绪",
            builtin_count,
        )

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
