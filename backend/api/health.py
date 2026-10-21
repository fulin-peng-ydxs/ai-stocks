"""健康检查路由（M0 骨架打通用）。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.response import ApiResponse, err, ok
from backend.config import get_settings
from backend.devtools.environment_guard import e2e_write_environment
from backend.storage import get_pg_client, get_read_client, get_redis_client
from backend.storage.pg_identity import pg_fingerprint
from backend.storage.task_runtime import get_task_runtime_client, task_runtime_backend

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=ApiResponse)
def health() -> ApiResponse:
    """返回服务健康状态 + 三类存储连通性 + 配置摘要（混合持久层：DuckDB+PG+Redis）。"""
    s = get_settings()
    duckdb_ok = False
    duckdb_detail = ""
    duckdb_pool: dict = {"enabled": False}
    active_task_count: int | None = None
    try:
        client = get_read_client()
        # version() 不读取持久化数据，实例失效时仍可能成功，必须实际访问业务表。
        version = client.query_df(
            "SELECT version() AS v FROM (SELECT count(*) FROM stock_basic) probe",
            timeout_sec=0.1,
        ).iloc[0]["v"]
        duckdb_pool = client.stats()
        duckdb_ok = True
        duckdb_detail = f"duckdb {version} @ {client.db_path.name}"
    except Exception as e:  # noqa: BLE001
        duckdb_detail = str(e)

    pg_ok = False
    pg_detail = ""
    runtime_backend = "unavailable"
    try:
        pg_ok = get_pg_client().ping()
        pg_detail = f"postgres @ {s.postgres.host}:{s.postgres.port}/{s.postgres.database}"
        runtime_backend = task_runtime_backend()
        task_row = get_task_runtime_client().query_df(
            "SELECT count(*) AS n FROM async_task WHERE status IN ('pending', 'running')"
        ).iloc[0]
        active_task_count = int(task_row["n"])
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
            "status": (
                "up" if duckdb_ok and pg_ok and redis_ok and active_task_count is not None
                else "degraded"
            ),
            "duckdb_ok": duckdb_ok,
            "duckdb": duckdb_detail,
            "duckdb_pool": duckdb_pool,
            "active_task_count": active_task_count,
            "task_runtime_backend": runtime_backend,
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
