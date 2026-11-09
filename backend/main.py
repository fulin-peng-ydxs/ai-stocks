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

from datetime import UTC, datetime

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.audit import router as audit_router
from backend.api.auth import router as auth_router
from backend.api.backtest import router as backtest_router
from backend.api.board import router as board_router
from backend.api.config import router as config_router
from backend.api.data_admin import router as data_admin_router
from backend.api.data_tasks import router as data_tasks_router
from backend.api.dicts import router as dict_router
from backend.api.health import router as health_router
from backend.api.indicators import router as indicators_router
from backend.api.layout import router as layout_router
from backend.api.limit_ladder import router as limit_ladder_router
from backend.api.menus import router as menus_router
from backend.api.profiles import router as profiles_router
from backend.api.resources import router as resources_router
from backend.api.roles import router as roles_router
from backend.api.score_profiles import router as score_profiles_router
from backend.api.sectors import router as sectors_router
from backend.api.stock_groups import router as stock_groups_router
from backend.api.stocks import router as stocks_router
from backend.api.tenants import router as tenants_router
from backend.api.trade_discipline import router as trade_discipline_router
from backend.api.trade_profiles import router as trade_profiles_router
from backend.api.training import router as training_router
from backend.api.user_preferences import router as user_preferences_router
from backend.api.users import router as users_router
from backend.auth.deps import require_system
from backend.auth.middleware import AuthMiddleware, SecurityMiddleware
from backend.common.exceptions import AIStocksError, DataSourceError, StorageError
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
        # 原始异常和 SQL 留在服务端日志；软失败也必须与普通业务提示分层。
        message = exc.msg
        if isinstance(exc, StorageError):
            message = "数据存储暂时不可用，请稍后重试"
        elif isinstance(exc, DataSourceError):
            message = "数据源请求失败，请在数据管理的任务日志中查看详情"
        return JSONResponse(
            status_code=getattr(exc, "http_status", 200),
            content={"code": exc.code, "msg": message, "data": getattr(exc, "data", None)},
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

    # FastAPI 入参校验失败（422）：默认 detail 为 [{loc,msg,type}] 数组，前端拿数组当文案
    # 会空白/变 "[object Object]"。转译为统一 {code:4000,msg:中文}，pydantic 的 msg
    # 是英文系统文本（"Input should be..."），一律不展示，只带出字段名定位问题。
    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors: list = exc.errors()
        field = ""
        field_labels = {
            "date_start": "开始日期", "date_end": "结束日期", "trade_date": "交易日",
            "code": "股票代码", "codes": "股票范围", "issue_ids": "质量问题范围",
            "issue_type": "质量问题类型", "size": "每页条数", "page_size": "每页条数",
            "page": "页码", "password": "密码", "account": "账号", "email": "邮箱",
            "name": "名称", "mode": "执行模式", "task_type": "任务类型",
        }
        for error in errors:
            loc = error.get("loc") or []
            # 嵌套定位优先使用最深的已知业务字段，数字下标不冒充字段名。
            label = next((field_labels[name] for name in reversed(loc)
                          if isinstance(name, str) and name in field_labels), "")
            if label:
                field = label
                break
        message = f"{field}不合法，请检查填写内容" if field else "请求参数不合法，请检查填写内容"
        # pydantic 的 error 会携带 input/ctx，其中可能包含密码或令牌；日志只保留定位元数据。
        safe_errors = [
            {"type": error.get("type"), "loc": error.get("loc")}
            for error in errors
        ]
        log.warning("入参校验失败 %s: %s", field or "(整体)", safe_errors)
        return JSONResponse(
            status_code=422,
            content={"code": 4000, "msg": message, "data": None},
        )

    # 未捕获异常兜底（HTTP 500）：编程错误/存储故障等逃逸到这里的异常，转译为统一 {code,msg} 软失败，
    # 避免 FastAPI 默认 {"detail":"Internal Server Error"} 把英文系统文本直接暴露给前端用户。
    # 真实堆栈记入服务端日志，不回传给用户（内部错误细节不应外泄）。
    @app.exception_handler(Exception)
    async def _handle_uncaught_error(_: Request, exc: Exception) -> JSONResponse:
        log.error("未捕获异常: %s", exc, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"code": 5000, "msg": "服务内部错误，请稍后重试", "data": None},
        )

    # ── 路由注册 ──
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(profiles_router)
    app.include_router(board_router)
    app.include_router(stocks_router)
    app.include_router(backtest_router)
    app.include_router(config_router)
    app.include_router(indicators_router)
    app.include_router(layout_router)
    app.include_router(limit_ladder_router)
    app.include_router(score_profiles_router)
    app.include_router(sectors_router)
    app.include_router(trade_discipline_router)
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

        # 在任何初始化写入前核对外部依赖及密钥，缺失时不留下半初始化的 PG。
        if not get_pg_client().ping():
            raise RuntimeError("PostgreSQL 连通性自检失败：ping 未返回预期结果")
        if not get_redis_client().ping():
            raise RuntimeError("Redis 连通性自检失败：ping 未返回 PONG")
        get_settings().jwt_secret()
        # 双库结构、平台基础数据和预设统一验收；只读 DuckDB 启动不执行初始化写入。
        try:
            market = get_client()
            market.query_df("SELECT 1 AS ok")
            from backend.storage.database_lifecycle import initialize_database, verify_database

            pg = get_pg_client()
            if market.read_only:
                report = verify_database(market, pg)
                if not report["ok"]:
                    raise RuntimeError(f"只读数据库验收未通过：{report}")
            else:
                initialize_database(market, pg)
            builtin_count = len(market.query_df("SELECT key FROM indicator_def WHERE is_builtin"))
            from backend.services.trade_calendar_readiness import (
                calendar_readiness_detail,
                inspect_trade_calendar,
            )

            calendar_readiness = inspect_trade_calendar(market)
        except Exception as e:
            raise RuntimeError(f"数据库初始化或验收失败：{e}") from e
        if (
            not calendar_readiness["lifecycle_ready"]
            or not calendar_readiness["cross_year_ready"]
        ):
            log.warning(
                "交易日历前瞻覆盖不足：%s；请执行日常数据更新，"
                "数据源未发布前规则生命周期保持 fail-closed",
                calendar_readiness_detail(calendar_readiness),
            )
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
            from backend.services.limit_ladder_task_coordinator import (
                LimitLadderTaskCoordinator,
            )

            # 运行态残留任务先转 interrupted，再由 PG 天梯账本对账终态。
            task_service = AsyncTaskService()
            task_service.reconcile()
            LimitLadderTaskCoordinator(task_service=task_service).reconcile(
                startup_at=datetime.now(UTC)
            )
        except Exception as e:  # noqa: BLE001
            log.warning("启动期任务 reconcile 异常: %s", e)

    @app.on_event("startup")
    def _start_scheduler() -> None:
        from backend.scheduler.scheduler import start_scheduler
        start_scheduler()

    @app.on_event("shutdown")
    def _stop_scheduler() -> None:
        from backend.scheduler.scheduler import shutdown_scheduler
        from backend.storage import close_duckdb_clients, get_pg_client, get_redis_client

        shutdown_scheduler()
        close_duckdb_clients()
        get_pg_client().close()
        get_redis_client().close()

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "backend.main:app", host=s.server.host, port=s.server.port, log_level=s.server.log_level
    )
