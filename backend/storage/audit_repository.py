"""审计日志写入仓库（阶段五平台能力）。

当前仅提供 best-effort 写入能力；查询、分页、范围收口由后续审计服务任务实现。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

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
