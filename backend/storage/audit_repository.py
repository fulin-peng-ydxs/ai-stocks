"""审计日志写入仓库（阶段五平台能力）。

当前仅提供 best-effort 写入能力；查询、分页、范围收口由后续审计服务任务实现。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.audit")

_AUDIT_SORT_COLS = {
    "event_time": "a.event_time",
    "duration_ms": "a.duration_ms",
    "result": "a.result",
    "status": "a.status",
    "event_category": "a.event_category",
}


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
        changes: list[dict[str, Any]] | None = None,
        source_event_key: str | None = None,
    ) -> str | None:
        """写入一条审计日志。

        审计不得反向影响主业务，因此本方法吞掉存储异常并返回 None。
        """
        audit_id = uuid.uuid4().hex
        try:
            conflict_clause = "ON CONFLICT DO NOTHING" if source_event_key else ""
            self.pg.execute(
                f"""
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, actor_account, event_category,
                    event_type, resource_code, action, target_type, target_id,
                    target_label, result, status, ip, method, path, duration_ms,
                    error_summary, context, changes, source_event_key
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb, %s
                )
                {conflict_clause}
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
                    json.dumps(changes or [], ensure_ascii=False, default=str),
                    source_event_key,
                ],
            )
            if source_event_key:
                existing = self.pg.query_df(
                    "SELECT id FROM audit_log WHERE source_event_key=%s",
                    [source_event_key],
                )
                if not existing.empty:
                    return str(existing.iloc[0]["id"])
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
        sort_by: str = "event_time",
        sort_order: str = "desc",
    ) -> dict:
        where, params, needs_resource_join = self._where(filters)
        sort_col = _AUDIT_SORT_COLS.get(sort_by, "a.event_time")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        count_from = self._from_clause(include_resource=needs_resource_join)
        total = int(self.pg.query_df(
            "SELECT count(*) AS n "
            f"{count_from} "
            f"{where}",
            params,
        ).iloc[0]["n"])
        rows = self.pg.query_df(
            "SELECT a.id, a.event_time, a.tenant_id, a.actor_user_id, a.actor_account, "
            "a.event_category, a.event_type, a.resource_code, sr.name AS resource_name, "
            "a.action, a.target_type, a.target_id, a.target_label, a.result, a.status, "
            "a.ip, a.method, a.path, a.duration_ms, a.error_summary, a.context, "
            "a.changes, a.created_at "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            f"{where} "
            f"ORDER BY {sort_col} {direction} NULLS LAST, a.event_time DESC, a.created_at DESC "
            "LIMIT %s OFFSET %s",
            params + [page_size, (page - 1) * page_size],
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": [self._row(r.to_dict()) for _, r in rows.iterrows()],
        }

    def summary(self, *, filters: dict[str, Any]) -> dict:
        where, params, needs_resource_join = self._where(filters)
        rows = self.pg.query_df(
            """
            SELECT
                CASE
                    WHEN GROUPING(a.event_category)=0 THEN 'event_category'
                    WHEN GROUPING(a.event_type)=0 THEN 'event_type'
                    WHEN GROUPING(a.result)=0 THEN 'result'
                    WHEN GROUPING(a.status)=0 THEN 'status'
                    ELSE 'total'
                END AS bucket,
                CASE
                    WHEN GROUPING(a.event_category)=0 THEN a.event_category
                    WHEN GROUPING(a.event_type)=0 THEN a.event_type
                    WHEN GROUPING(a.result)=0 THEN a.result
                    WHEN GROUPING(a.status)=0 THEN a.status
                    ELSE NULL
                END AS k,
                count(*) AS n
            """
            f"{self._from_clause(include_resource=needs_resource_join)} "
            f"{where} "
            "GROUP BY GROUPING SETS ((), "
            "(a.event_category), (a.event_type), (a.result), (a.status))",
            params,
        )
        total = 0
        by_category: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_result: dict[str, int] = {}
        by_status: dict[str, int] = {}
        bucket_map = {
            "event_category": by_category,
            "event_type": by_type,
            "result": by_result,
            "status": by_status,
        }
        for _, row in rows.iterrows():
            bucket = str(row["bucket"])
            count = int(row["n"])
            if bucket == "total":
                total = count
                continue
            key = row["k"]
            if key is None or pd.isna(key):
                continue
            bucket_map[bucket][str(key)] = count
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
            "a.ip, a.method, a.path, a.duration_ms, a.error_summary, a.context, "
            "a.changes, a.created_at "
            "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code "
            "WHERE " + " AND ".join(conds),
            params,
        )
        if df.empty:
            return None
        return self._row(df.iloc[0].to_dict())

    def delete_before(self, cutoff: datetime) -> int:
        """删除保留期外审计日志，返回受影响行数。"""
        affected = self.pg.execute("DELETE FROM audit_log WHERE event_time < %s", [cutoff])
        return max(0, int(affected))

    @staticmethod
    def _from_clause(*, include_resource: bool) -> str:
        if include_resource:
            return "FROM audit_log a LEFT JOIN sys_resource sr ON sr.code = a.resource_code"
        return "FROM audit_log a"

    @staticmethod
    def _where(filters: dict[str, Any]) -> tuple[str, list[Any], bool]:
        conds: list[str] = []
        params: list[Any] = []
        needs_resource_join = False
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
            values = AuditRepository._exact_values(val)
            if len(values) == 1:
                conds.append(f"{col}=%s")
                params.append(values[0])
            elif values:
                conds.append(f"{col} IN ({', '.join(['%s'] * len(values))})")
                params.extend(values)
        if filters.get("start_time"):
            conds.append("a.event_time >= %s")
            params.append(filters["start_time"])
        if filters.get("end_time"):
            conds.append("a.event_time <= %s")
            params.append(filters["end_time"])
        if filters.get("actor_keyword"):
            like = f"%{AuditRepository._escape_like(filters['actor_keyword'])}%"
            conds.append(
                "(a.actor_user_id ILIKE %s ESCAPE '\\' "
                "OR a.actor_account ILIKE %s ESCAPE '\\')"
            )
            params += [like, like]
        if filters.get("target_keyword"):
            like = f"%{AuditRepository._escape_like(filters['target_keyword'])}%"
            needs_resource_join = True
            conds.append(
                "(a.target_id ILIKE %s ESCAPE '\\' "
                "OR a.target_label ILIKE %s ESCAPE '\\' "
                "OR a.path ILIKE %s ESCAPE '\\' "
                "OR a.resource_code ILIKE %s ESCAPE '\\' "
                "OR sr.name ILIKE %s ESCAPE '\\')"
            )
            params += [like, like, like, like, like]
        return (("WHERE " + " AND ".join(conds)) if conds else ""), params, needs_resource_join

    @staticmethod
    def _exact_values(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [text for item in value if (text := str(item).strip())]
        text = str(value).strip()
        return [text] if text else []

    @staticmethod
    def _escape_like(value: Any) -> str:
        return str(value).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

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

        out = {k: clean(v) for k, v in row.items() if k not in {"context", "changes"}}
        ctx = row.get("context")
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except ValueError:
                ctx = {}
        out["context"] = ctx if isinstance(ctx, dict) else {}
        changes = row.get("changes")
        if isinstance(changes, str):
            try:
                changes = json.loads(changes)
            except ValueError:
                changes = []
        out["changes"] = changes if isinstance(changes, list) else []
        return out
