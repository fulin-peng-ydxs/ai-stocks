"""RBAC 管理行为审计辅助。

审计为 best-effort：写入失败不得影响 RBAC 管理主流程。
"""

from __future__ import annotations

from backend.auth.context import get_current_context
from backend.services.audit_service import AuditService


def record_rbac_action(
    *,
    action: str,
    target_type: str,
    target_id: str,
    target_label: str | None = None,
    resource_code: str | None = None,
    affected_count: int = 1,
) -> None:
    ctx = get_current_context()
    AuditService().record_rbac_event(
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        resource_code=resource_code,
        tenant_id=ctx.tenant_id if ctx else None,
        actor_user_id=ctx.user_id if ctx else None,
        affected_count=affected_count,
    )
