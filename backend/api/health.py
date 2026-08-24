"""健康检查路由（M0 骨架打通用）。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.response import ApiResponse, err, ok
from backend.config import get_settings
from backend.devtools.environment_guard import e2e_write_environment
from backend.storage import get_client, get_pg_client, get_redis_client
from backend.storage.pg_identity import pg_fingerprint

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=ApiResponse)
def health() -> ApiResponse:
    """返回服务健康状态 + 三类存储连通性 + 配置摘要（混合持久层：DuckDB+PG+Redis）。"""
    s = get_settings()
    duckdb_ok = False
    duckdb_detail = ""
    active_task_count: int | None = None
    try:
        client = get_client()
        version = client.query_df("SELECT version() AS v").iloc[0]["v"]
        task_row = client.query_df(
            "SELECT count(*) AS n FROM async_task WHERE status IN ('pending', 'running')"
        ).iloc[0]
        active_task_count = int(task_row["n"])
        duckdb_ok = True
        duckdb_detail = f"duckdb {version} @ {client.db_path.name}"
    except Exception as e:  # noqa: BLE001
        duckdb_detail = str(e)

    pg_ok = False
    pg_detail = ""
    try:
        pg_ok = get_pg_client().ping()
        pg_detail = f"postgres @ {s.postgres.host}:{s.postgres.port}/{s.postgres.database}"
    except Exception as e:  # noqa: BLE001
        pg_detail = str(e)

    redis_ok = False
    redis_detail = ""
    try:
        redis_ok = get_redis_client().ping()
        redis_detail = f"redis @ {s.redis.host}:{s.redis.port}/{s.redis.db}"
    except Exception as e:  # noqa: BLE001
        redis_detail = str(e)

    return ok(
        {
            "status": "up",
            "duckdb_ok": duckdb_ok,
            "duckdb": duckdb_detail,
            "active_task_count": active_task_count,
            "pg_ok": pg_ok,
            "postgres": pg_detail,
            "redis_ok": redis_ok,
            "redis": redis_detail,
            "history_years": s.datasource.history_years,
            "benchmark_main": s.backtest.benchmark_main,
            "top_n": s.scoring.top_n,
        }
    )


@router.get("/health/e2e", response_model=ApiResponse)
def e2e_health() -> ApiResponse:
    """只在明确本地/测试环境且开启写开关时提供后端 PG 的不可逆指纹。"""
    environment = e2e_write_environment()
    if environment is None:
        return err(403, "E2E 写环境未启用")
    try:
        fingerprint = pg_fingerprint()
    except Exception as e:  # noqa: BLE001
        return err(503, f"PostgreSQL 指纹读取失败: {e}")
    return ok({"environment": environment, "pgFingerprint": fingerprint})
