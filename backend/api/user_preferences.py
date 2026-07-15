"""用户偏好 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_perm
from backend.storage.user_preference import UserPreferenceRepo, UserPreferenceValidationError

router = APIRouter(prefix="/api/user-preferences", tags=["user-preferences"])


class PreferenceBody(BaseModel):
    scope: str
    pageKey: str = ""
    prefKey: str
    value: Any = None
    schemaVersion: int = 1


class PreferenceBulkBody(BaseModel):
    items: list[PreferenceBody] = Field(default_factory=list)


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
        return err(400, str(e))
    return ok({"items": data}, msg="用户偏好已批量保存")
