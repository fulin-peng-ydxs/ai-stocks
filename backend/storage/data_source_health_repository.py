"""数据源联通测试运行态的 PostgreSQL 持久化仓库。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from backend.storage.pg_client import PostgresClient, get_pg_client


def _iso(value: Any) -> str | None:
    """把数据库时间稳定序列化为秒级 ISO 文本。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat(timespec="seconds")
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


class DataSourceHealthRepository:
    """读写平台全局的数据源最近一次联通测试结果。"""

    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    def list(self, sources: list[str]) -> dict[str, dict]:
        """批量读取指定数据源，避免逐源查询。"""
        if not sources:
            return {}
        rows = self.pg.query_df(
            "SELECT source,is_up,last_test_at,last_success_at,failure_reason "
            "FROM data_source_health WHERE source = ANY(%s)",
            [sources],
        ).to_dict("records")
        return {
            str(row["source"]): {
                "up": bool(row["is_up"]),
                "last_test_at": _iso(row.get("last_test_at")),
                "last_success_at": _iso(row.get("last_success_at")),
                "failure_reason": _optional_text(row.get("failure_reason")),
            }
            for row in rows
        }

    def record(
        self,
        source: str,
        *,
        up: bool,
        tested_at: datetime,
        failure_reason: str | None,
    ) -> None:
        """幂等保存最近测试；失败不得覆盖历史最近成功时间。"""
        self.pg.execute(
            "INSERT INTO data_source_health "
            "(source,is_up,last_test_at,last_success_at,failure_reason,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (source) DO UPDATE SET "
            "is_up=CASE WHEN EXCLUDED.last_test_at>=data_source_health.last_test_at "
            "THEN EXCLUDED.is_up ELSE data_source_health.is_up END,"
            "last_test_at=greatest(EXCLUDED.last_test_at,data_source_health.last_test_at),"
            "last_success_at=greatest(data_source_health.last_success_at,"
            "CASE WHEN EXCLUDED.is_up THEN EXCLUDED.last_test_at "
            "ELSE data_source_health.last_success_at END),"
            "failure_reason=CASE WHEN EXCLUDED.last_test_at>=data_source_health.last_test_at "
            "THEN EXCLUDED.failure_reason ELSE data_source_health.failure_reason END,"
            "updated_at=greatest(EXCLUDED.updated_at,data_source_health.updated_at)",
            [source, up, tested_at, tested_at if up else None, failure_reason, tested_at],
        )


__all__ = ["DataSourceHealthRepository"]
