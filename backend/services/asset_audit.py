"""阶段六公开资产审计工具。"""

from __future__ import annotations

from typing import Any

from backend.auth.context import get_current_context, get_current_resource_code
from backend.services.audit_service import AuditService


def record_asset_visibility_audit(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    action: str,
    target_type: str,
    ref_key: str,
    fallback_resource_prefix: str,
) -> None:
    ctx = get_current_context()
    if ctx is None:
        return
    visibility = after.get("visibility")
    resource_code = get_current_resource_code()
    if not resource_code and visibility in {"tenant", "public"}:
        resource_code = f"{fallback_resource_prefix}:publish-{visibility}"
    AuditService().record_security_event(
        event_type="asset_visibility",
        action=action,
        result="success",
        status="completed",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        resource_code=resource_code,
        target_type=target_type,
        target_id=after.get("id"),
        target_label=after.get("name") or after.get("id"),
        context={
            "action": action,
            "profile_ref": after.get(ref_key),
        },
        changes=AuditService.build_changes(before, after, fields=("visibility",)),
    )


def record_asset_copy_audit(
    source: dict[str, Any],
    copied: dict[str, Any] | None,
    *,
    action: str,
    target_type: str,
    resource_code: str,
    ref_key: str,
) -> None:
    ctx = get_current_context()
    if ctx is None:
        return
    AuditService().record_security_event(
        event_type="asset_copy",
        action=action,
        result="success",
        status="completed",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        resource_code=resource_code,
        target_type=target_type,
        target_id=(copied or {}).get("id"),
        target_label=(copied or {}).get("name") or (copied or {}).get("id"),
        context={
            "action": action,
            "profile_ref": source.get(ref_key),
            "affected_count": 1,
        },
        changes=[
            {"field": "source_ref", "before": None, "after": source.get(ref_key)},
            {"field": "target_id", "before": None, "after": (copied or {}).get("id")},
            {"field": "target_visibility", "before": None, "after": (copied or {}).get("visibility")},
        ],
    )


def record_backtest_reuse_audit(source_run: dict[str, Any], new_run_id: str) -> None:
    ctx = get_current_context()
    if ctx is None:
        return
    AuditService().record_security_event(
        event_type="asset_reuse",
        action="backtest_run_reuse",
        result="success",
        status="completed",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        resource_code="backtest:run",
        target_type="backtest_run",
        target_id=new_run_id,
        target_label=new_run_id,
        context={
            "action": "backtest_run_reuse",
            "source_run_ref": source_run.get("run_ref"),
            "affected_count": 1,
        },
        changes=[
            {"field": "source_run_ref", "before": source_run.get("run_ref"), "after": new_run_id},
        ],
    )
