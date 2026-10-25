"""可配置布局系统 API（agent-works/configurable-layout-system M4）。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.response import ApiResponse, err, ok
from backend.auth.context import get_current_owner
from backend.auth.deps import require_perm, require_system, require_system_perm
from backend.common.exceptions import ValidationError
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


class UserDensityBody(BaseModel):
    density: Literal["compact", "standard", "comfortable"]
    pageKeys: list[str] = Field(min_length=1, max_length=100)


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


@router.get("/presets", response_model=ApiResponse,
            dependencies=[Depends(require_perm("layout:view"))])
def list_presets(include_disabled: bool = False) -> ApiResponse:
    return ok(
        {
            "schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION,
            "presets": LayoutConfigRepo().list_presets(include_disabled),
        }
    )


@router.post("/presets", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("layout:preset-manage"))])
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
    return ok(preset, msg="视觉预设已保存")


@router.delete("/presets/{preset_key}", response_model=ApiResponse,
               dependencies=[Depends(require_system_perm("layout:preset-manage"))])
def delete_preset(preset_key: str) -> ApiResponse:
    try:
        LayoutConfigRepo().delete_preset(preset_key)
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok({"key": preset_key}, msg="视觉预设已删除")


@router.get("/pages/{page_key}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("layout:view"))])
def get_page_config(page_key: str) -> ApiResponse:
    try:
        return ok(LayoutConfigRepo().get_page_config(page_key))
    except LayoutConfigValidationError as e:
        return err(400, str(e))


@router.post("/pages/{page_key}", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("layout:page-manage"))])
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


@router.get("/users/{page_key}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("layout:user-config"))])
def get_user_config(page_key: str) -> ApiResponse:
    # 用户级布局按当前登录用户隔离；忽略前端传入 userId（防越权读他人配置，评审 P1）
    user_id = get_current_owner()[1]
    try:
        return ok(LayoutConfigRepo().get_user_config(page_key, user_id))
    except LayoutConfigValidationError as e:
        return err(400, str(e))


@router.post("/user-density", response_model=ApiResponse,
             dependencies=[Depends(require_perm("layout:user-config"))])
def sync_user_density(body: UserDensityBody) -> ApiResponse:
    """一次性同步当前用户的页面密度，复用个人布局权限，不修改页面模板。"""
    try:
        data = LayoutConfigRepo().sync_user_density(
            body.pageKeys, body.density, user_id=get_current_owner()[1],
        )
    except (LayoutConfigValidationError, ValidationError) as e:
        return err(400, str(e))
    return ok(data, msg="页面密度已统一")


@router.post("/users/{page_key}", response_model=ApiResponse,
             dependencies=[Depends(require_perm("layout:user-config"))])
def save_user_config(page_key: str, body: UserConfigBody) -> ApiResponse:
    # 归属取自上下文，不信任 body.userId（防越权写他人配置）
    try:
        data = LayoutConfigRepo().set_user_config(
            page_key=page_key,
            config=body.config,
            user_id=get_current_owner()[1],
            schema_version=body.schemaVersion,
            layout=body.layout,
        )
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(data, msg="用户布局配置已保存")


# 布局校验仅系统页面布局工作台（LayoutPagesView，system-only）消费；stage4·T5 补守卫（此前裸露）。
# 归 layout:page-manage：与页面布局保存同工作区、同权限边界。
@router.post("/validate", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("layout:page-manage"))])
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
    # 动态 scope 自守卫（stage4·R21，DYNAMIC_SCOPE_GUARDED_ROUTES 唯一成员）：按 payload scope 分流守卫——
    # page（平台页面布局）仅系统管理员；user（个人偏好）需 layout:user-config。函数体内守卫，故路由扫描白名单登记。
    if body.scope == "page":
        require_system()
    else:
        require_perm("layout:user-config")()   # 复用精确码依赖逻辑（system 恒过 / 无码 403 / 未登录 401）
    # 用户级重置归属取自上下文，不信任 body.userId（防越权重置他人配置）
    user_id = get_current_owner()[1]
    try:
        data = LayoutConfigRepo().reset(
            scope=body.scope,
            page_key=body.pageKey,
            user_id=user_id,
            path=body.path,
        )
    except LayoutConfigValidationError as e:
        return err(400, str(e))
    return ok(data, msg="布局配置已重置")


# 字段开放策略列表：仅布局配置管理页（系统组件工作区，system-only）消费；
# 页面渲染走 /effective（普通用户依赖），故此读接口限 system，与 POST 守卫对齐。
@router.get("/field-policies", response_model=ApiResponse,
            dependencies=[Depends(require_system_perm("layout:field-policy"))])
def list_field_policies() -> ApiResponse:
    """组件字段开放策略：每个受控 (组件, 字段) 的代码最大集 + 当前生效集 + 是否被覆盖。"""
    return ok(
        {
            "schemaVersion": LAYOUT_CONFIG_SCHEMA_VERSION,
            "policies": LayoutConfigRepo().list_field_policies(),
        }
    )


@router.post("/field-policies", response_model=ApiResponse,
             dependencies=[Depends(require_system_perm("layout:field-policy"))])
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


@router.get("/effective/{page_key}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("layout:view"))])
def get_effective_config(page_key: str) -> ApiResponse:
    # 生效配置的用户层按当前登录用户，不信任前端 userId（防越权读他人配置）
    user_id = get_current_owner()[1]
    try:
        return ok(LayoutConfigRepo().effective_config(page_key, user_id))
    except LayoutConfigValidationError as e:
        return err(400, str(e))
