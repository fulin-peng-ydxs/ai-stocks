"""审计日志写入仓库（阶段五平台能力）。

当前仅提供 best-effort 写入能力；查询、分页、范围收口由后续审计服务任务实现。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.audit")


class AuditRepository:
    """平台级审计日志仓库。"""

    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    def record(
        self,
        *,
        event_category: str,
        event_type: str,
        action: str,
        result: str,
        status: str,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        actor_account: str | None = None,
        resource_code: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        target_label: str | None = None,
        ip: str | None = None,
        method: str | None = None,
        path: str | None = None,
        duration_ms: int | None = None,
        error_summary: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """写入一条审计日志。

        审计不得反向影响主业务，因此本方法吞掉存储异常并返回 None。
        """
        audit_id = uuid.uuid4().hex
        try:
            self.pg.execute(
                """
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, actor_account, event_category,
                    event_type, resource_code, action, target_type, target_id,
                    target_label, result, status, ip, method, path, duration_ms,
                    error_summary, context
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb
                )
                """,
                [
                    audit_id,
                    tenant_id,
                    actor_user_id,
                    actor_account,
                    event_category,
                    event_type,
                    resource_code,
                    action,
                    target_type,
                    target_id,
                    target_label,
                    result,
                    status,
                    ip,
                    method,
                    path,
                    duration_ms,
                    error_summary,
                    json.dumps(context or {}, ensure_ascii=False, default=str),
                ],
            )
            return audit_id
        except Exception as e:  # noqa: BLE001
            log.warning("审计日志写入失败，已降级忽略: %s", e)
            return None

    def list_logs(
        self,
        *,
        filters: dict[str, Any],
        page: int,
        page_size: int,
    ) -> dict:
        where, params = self._where(filters)
        total = int(self.pg.query_df(
            "SELECT count(*) AS n "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            f"{where}",
            params,
        ).iloc[0]["n"])
        rows = self.pg.query_df(
            "SELECT a.id, a.event_time, a.tenant_id, a.actor_user_id, a.actor_account, "
            "a.event_category, a.event_type, a.resource_code, sr.name AS resource_name, "
            "a.action, a.target_type, a.target_id, a.target_label, a.result, a.status, "
            "a.ip, a.method, a.path, a.duration_ms, a.error_summary, a.context, a.created_at "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            f"{where} "
            "ORDER BY a.event_time DESC, a.created_at DESC LIMIT %s OFFSET %s",
            params + [page_size, (page - 1) * page_size],
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": [self._row(r.to_dict()) for _, r in rows.iterrows()],
        }

    def summary(self, *, filters: dict[str, Any]) -> dict:
        where, params = self._where(filters)
        total = int(self.pg.query_df(
            "SELECT count(*) AS n "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            f"{where}",
            params,
        ).iloc[0]["n"])
        by_category = self._counts("a.event_category", where, params)
        by_type = self._counts("a.event_type", where, params)
        by_result = self._counts("a.result", where, params)
        by_status = self._counts("a.status", where, params)
        return {
            "total": total,
            "success": by_result.get("success", 0),
            "failed": by_result.get("failed", 0) + by_result.get("error", 0),
            "by_category": by_category,
            "by_type": by_type,
            "by_result": by_result,
            "by_status": by_status,
        }

    def get(self, audit_id: str, *, tenant_id: str | None = None) -> dict | None:
        conds = ["a.id=%s"]
        params: list[Any] = [audit_id]
        if tenant_id is not None:
            conds.append("a.tenant_id=%s")
            params.append(tenant_id)
        df = self.pg.query_df(
            "SELECT a.id, a.event_time, a.tenant_id, a.actor_user_id, a.actor_account, "
            "a.event_category, a.event_type, a.resource_code, sr.name AS resource_name, "
            "a.action, a.target_type, a.target_id, a.target_label, a.result, a.status, "
            "a.ip, a.method, a.path, a.duration_ms, a.error_summary, a.context, a.created_at "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            "WHERE " + " AND ".join(conds),
            params,
        )
        if df.empty:
            return None
        return self._row(df.iloc[0].to_dict())

    def _counts(self, column: str, where: str, params: list[Any]) -> dict[str, int]:
        df = self.pg.query_df(
            f"SELECT {column} AS k, count(*) AS n "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            f"{where} "
            f"GROUP BY {column} ORDER BY n DESC",
            params,
        )
        return {str(r["k"]): int(r["n"]) for _, r in df.iterrows() if r["k"] is not None}

    @staticmethod
    def _where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
        conds: list[str] = []
        params: list[Any] = []
        exact_cols = {
            "tenant_id": "a.tenant_id",
            "event_category": "a.event_category",
            "event_type": "a.event_type",
            "result": "a.result",
            "status": "a.status",
            "resource_code": "a.resource_code",
        }
        for key, col in exact_cols.items():
            val = filters.get(key)
            if val:
                conds.append(f"{col}=%s")
                params.append(val)
        if filters.get("start_time"):
            conds.append("a.event_time >= %s")
            params.append(filters["start_time"])
        if filters.get("end_time"):
            conds.append("a.event_time <= %s")
            params.append(filters["end_time"])
        if filters.get("actor_keyword"):
            like = f"%{filters['actor_keyword']}%"
            conds.append("(a.actor_user_id ILIKE %s OR a.actor_account ILIKE %s)")
            params += [like, like]
        if filters.get("target_keyword"):
            like = f"%{filters['target_keyword']}%"
            conds.append(
                "(a.target_id ILIKE %s OR a.target_label ILIKE %s OR a.path ILIKE %s "
                "OR a.resource_code ILIKE %s OR sr.name ILIKE %s)"
            )
            params += [like, like, like, like, like]
        return (("WHERE " + " AND ".join(conds)) if conds else ""), params

    @staticmethod
    def _row(row: dict[str, Any]) -> dict[str, Any]:
        def clean(value):
            if value is None:
                return None
            try:
                if pd.isna(value):
                    return None
            except (TypeError, ValueError):
                pass
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return value

        out = {k: clean(v) for k, v in row.items() if k != "context"}
        ctx = row.get("context")
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except ValueError:
                ctx = {}
        out["context"] = ctx if isinstance(ctx, dict) else {}
        return out
