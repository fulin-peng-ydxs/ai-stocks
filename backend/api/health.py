"""健康检查路由（M0 骨架打通用）。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.response import ApiResponse, ok
from backend.config import get_settings
from backend.storage import get_client

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=ApiResponse)
def health() -> ApiResponse:
    """返回服务健康状态 + DuckDB 连通性 + 配置摘要。"""
    s = get_settings()
    duckdb_ok = False
    duckdb_detail = ""
    try:
        client = get_client()
        version = client.query_df("SELECT version() AS v").iloc[0]["v"]
        duckdb_ok = True
        duckdb_detail = f"duckdb {version} @ {client.db_path.name}"
    except Exception as e:  # noqa: BLE001
        duckdb_detail = str(e)

    return ok(
        {
            "status": "up",
            "duckdb_ok": duckdb_ok,
            "duckdb": duckdb_detail,
            "history_years": s.datasource.history_years,
            "benchmark_main": s.backtest.benchmark_main,
            "top_n": s.scoring.top_n,
        }
    )
