"""可配置布局系统 API（agent-works/configurable-layout-system M4）。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.api.response import ApiResponse, err, ok
from backend.auth.deps import require_system
from backend.storage.layout_config import (
    DEFAULT_USER_ID,
    LAYOUT_CONFIG_SCHEMA_VERSION,
    LayoutConfigRepo,
    LayoutConfigValidationError,
    check_component_config_ownership,
    normalize_override,
    validate_layout_payload,
)

router = APIRouter(prefix="/api/layout", tags=["layout"])


class PresetBody(BaseModel):
    key: str
    name: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_builtin: bool = False
    schemaVersion: int | None = None


class PageConfigBody(BaseModel):
    presetKey: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    schemaVersion: int | None = None
    # 含组件配置路径时必须提供 layout，用于后端校验字段归属（slot 存在 + 字段属于该组件种类）。
    layout: dict[str, Any] | None = None


class UserConfigBody(BaseModel):
    userId: str = DEFAULT_USER_ID
    config: dict[str, Any] = Field(default_factory=dict)
    schemaVersion: int | None = None
    layout: dict[str, Any] | None = None


class ValidateBody(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] | None = None
    schemaVersion: int | None = None


class ResetBody(BaseModel):
    scope: Literal["page", "user"]
    pageKey: str
    userId: str = DEFAULT_USER_ID
    path: str | None = None


class FieldPolicyBody(BaseModel):
    componentKind: str
    field: str
    # 为空数组时视为重置（回落代码最大集）。
    allowedLayers: list[str] = Field(default_factory=list)


@router.get("/presets", response_model=ApiResponse)
def list_presets(include_disabled: bool = False) -> ApiResponse:
    return ok(
        {
            "schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION,
            "presets": LayoutConfigRepo().list_presets(include_disabled),
        }
    )


@router.post("/presets", response_model=ApiResponse, dependencies=[Depends(require_system)])
def save_preset(body: PresetBody) -> ApiResponse:
    try:
        preset = LayoutConfigRepo().upsert_preset(
            key=body.key,
            name=body.name,
            description=body.description,
            config=body.config,
            enabled=body.enabled,
            is_builtin=body.is_builtin,
            schema_version=body.schemaVersion,
        )
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(preset, msg="布局预设已保存")


@router.delete("/presets/{preset_key}", response_model=ApiResponse, dependencies=[Depends(require_system)])
def delete_preset(preset_key: str) -> ApiResponse:
    try:
        LayoutConfigRepo().delete_preset(preset_key)
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok({"key": preset_key}, msg="布局预设已删除")


@router.get("/pages/{page_key}", response_model=ApiResponse)
def get_page_config(page_key: str) -> ApiResponse:
    try:
        return ok(LayoutConfigRepo().get_page_config(page_key))
    except LayoutConfigValidationError as e:
        return err(400, str(e))


@router.post("/pages/{page_key}", response_model=ApiResponse, dependencies=[Depends(require_system)])
def save_page_config(page_key: str, body: PageConfigBody) -> ApiResponse:
    try:
        data = LayoutConfigRepo().set_page_config(
            page_key=page_key,
            config=body.config,
            preset_key=body.presetKey,
            schema_version=body.schemaVersion,
            layout=body.layout,
        )
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(data, msg="页面布局配置已保存")


@router.get("/users/{page_key}", response_model=ApiResponse)
def get_user_config(page_key: str, user_id: str = Query(DEFAULT_USER_ID, alias="userId")) -> ApiResponse:
    try:
        return ok(LayoutConfigRepo().get_user_config(page_key, user_id))
    except LayoutConfigValidationError as e:
        return err(400, str(e))


@router.post("/users/{page_key}", response_model=ApiResponse)
def save_user_config(page_key: str, body: UserConfigBody) -> ApiResponse:
    try:
        data = LayoutConfigRepo().set_user_config(
            page_key=page_key,
            config=body.config,
            user_id=body.userId,
            schema_version=body.schemaVersion,
            layout=body.layout,
        )
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(data, msg="用户布局配置已保存")


@router.post("/validate", response_model=ApiResponse)
def validate_layout_config(body: ValidateBody) -> ApiResponse:
    errors: list[str] = []
    normalized: dict[str, Any] = {}
    try:
        normalized = normalize_override(body.config, body.schemaVersion)["values"]
    except LayoutConfigValidationError as e:
        errors.append(str(e))
    if body.layout is not None:
        errors.extend(validate_layout_payload(body.layout))
        # 组件配置路径归属交叉校验：slot 存在 + 字段属于该 slot 的组件种类。
        errors.extend(check_component_config_ownership(normalized, body.layout))
    return ok({"valid": not errors, "errors": errors})


@router.post("/reset", response_model=ApiResponse)
def reset_layout_config(body: ResetBody) -> ApiResponse:
    if body.scope == "page":
        require_system()   # 页面级布局是平台配置，删除/重置仅系统管理员（用户级 scope 不限）
    try:
        data = LayoutConfigRepo().reset(
            scope=body.scope,
            page_key=body.pageKey,
            user_id=body.userId,
            path=body.path,
        )
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(data, msg="布局配置已重置")


@router.get("/field-policies", response_model=ApiResponse)
def list_field_policies() -> ApiResponse:
    """组件字段开放策略：每个受控 (组件, 字段) 的代码最大集 + 当前生效集 + 是否被覆盖。"""
    return ok(
        {
            "schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION,
            "policies": LayoutConfigRepo().list_field_policies(),
        }
    )


@router.post("/field-policies", response_model=ApiResponse, dependencies=[Depends(require_system)])
def save_field_policy(body: FieldPolicyBody) -> ApiResponse:
    """收紧 / 放开某字段的开放层级；空数组视为重置回代码最大集。只能在代码最大集内收放。"""
    try:
        repo = LayoutConfigRepo()
        if not body.allowedLayers:
            data = repo.reset_field_policy(body.componentKind, body.field)
        else:
            data = repo.set_field_policy(body.componentKind, body.field, body.allowedLayers)
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(data, msg="组件字段开放策略已保存")


@router.get("/effective/{page_key}", response_model=ApiResponse)
def get_effective_config(
    page_key: str,
    user_id: str = Query(DEFAULT_USER_ID, alias="userId"),
) -> ApiResponse:
    try:
        return ok(LayoutConfigRepo().effective_config(page_key, user_id))
    except LayoutConfigValidationError as e:
        return err(400, str(e))
