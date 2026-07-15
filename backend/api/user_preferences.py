"""用户偏好 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_owner
from backend.auth.deps import require_perm
from backend.common.logging import get_logger
from backend.storage.audit_repository import AuditRepository
from backend.storage.user_preference import UserPreferenceRepo, UserPreferenceValidationError

router = APIRouter(prefix="/api/user-preferences", tags=["user-preferences"])
log = get_logger("api.user_preferences")
CONFIG_STORAGE_CLIENT_MIGRATION_SOURCE = "config-storage-pg-v1"


class PreferenceBody(BaseModel):
    scope: str
    pageKey: str = ""
    prefKey: str
    value: Any = None
    schemaVersion: int = 1


class PreferenceBulkBody(BaseModel):
    items: list[PreferenceBody] = Field(default_factory=list)
    migrationSource: str | None = None


def _record_client_migration_audit(
    *,
    source: str | None,
    item_count: int,
    saved_count: int,
    success: bool,
    error_summary: str | None = None,
) -> None:
    if source != CONFIG_STORAGE_CLIENT_MIGRATION_SOURCE:
        return
    try:
        tenant_id, owner_user_id = get_current_owner()
        AuditRepository().record(
            event_category="migration",
            event_type="client_preference_migration",
            action="bulk_save",
            result="success" if success else "failed",
            status="completed" if success else "failed",
            tenant_id=tenant_id,
            actor_user_id=owner_user_id,
            resource_code="user-preference:manage",
            target_type="user_preference",
            target_id=source,
            target_label="客户端偏好迁移",
            error_summary=error_summary,
            context={
                "action": "client_preference_migration",
                "migration_source": source,
                "item_count": item_count,
                "saved_count": saved_count,
                "affected_count": saved_count,
                "reason": None if success else "bulk_save_failed",
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("客户端偏好迁移审计写入失败，已降级忽略: %s", e)


@router.get("", response_model=ApiResponse,
            dependencies=[Depends(require_perm("user-preference:manage"))])
def list_user_preferences(
    scope: str | None = None,
    pageKey: str | None = None,
    prefKey: str | None = None,
) -> ApiResponse:
    try:
        rows = UserPreferenceRepo().list(scope=scope, page_key=pageKey, pref_key=prefKey)
    except UserPreferenceValidationError as e:
        return err(400, str(e))
    return ok({"items": rows})


@router.post("", response_model=ApiResponse,
             dependencies=[Depends(require_perm("user-preference:manage"))])
def save_user_preference(body: PreferenceBody) -> ApiResponse:
    try:
        data = UserPreferenceRepo().set(
            scope=body.scope,
            page_key=body.pageKey,
            pref_key=body.prefKey,
            value=body.value,
            schema_version=body.schemaVersion,
        )
    except UserPreferenceValidationError as e:
        return err(400, str(e))
    return ok(data, msg="用户偏好已保存")


@router.post("/bulk", response_model=ApiResponse,
             dependencies=[Depends(require_perm("user-preference:manage"))])
def save_user_preferences_bulk(body: PreferenceBulkBody) -> ApiResponse:
    try:
        items = [
            {
                "scope": item.scope,
                "pageKey": item.pageKey,
                "prefKey": item.prefKey,
                "value": item.value,
                "schemaVersion": item.schemaVersion,
            }
            for item in body.items
        ]
        data = UserPreferenceRepo().set_many(items)
    except UserPreferenceValidationError as e:
        _record_client_migration_audit(
            source=body.migrationSource,
            item_count=len(body.items),
            saved_count=0,
            success=False,
            error_summary=str(e),
        )
        return err(400, str(e))
    _record_client_migration_audit(
        source=body.migrationSource,
        item_count=len(body.items),
        saved_count=len(data),
        success=True,
    )
    return ok({"items": data}, msg="用户偏好已批量保存")
