"""功能点管理 API（多租户 RBAC stage3·T8，R13）。

薄层：参数校验 + 响应包装；守卫/业务规则/失效编排在 services.resource_admin_service。
功能点是平台级全局表，管理入口仅系统管理员——全部端点挂 require_system。
type=button/api；code 全局唯一不可复用；内置码不可删不可改。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_system
from backend.services.audit_service import AuditService
from backend.services.rbac_audit import record_rbac_action
from backend.services.resource_admin_service import ResourceAdminService

router = APIRouter(prefix="/api", tags=["resources"], dependencies=[Depends(require_system)])


class ResourceCreate(BaseModel):
    menuId: str
    code: str
    name: str
    type: str = "api"                 # button | api
    apiMethod: str | None = None
    apiPath: str | None = None
    sort: int | None = None


class ResourceUpdate(BaseModel):
    menuId: str
    code: str
    name: str
    type: str = "api"
    apiMethod: str | None = None
    apiPath: str | None = None


@router.get("/resources", response_model=ApiResponse)
def list_resources(menu_id: str | None = None) -> ApiResponse:
    return ok(ResourceAdminService().list_resources(menu_id))


@router.post("/resources", response_model=ApiResponse)
def create_resource(body: ResourceCreate) -> ApiResponse:
    r = ResourceAdminService().create_resource(
        menu_id=body.menuId, code=body.code, name=body.name, type=body.type,
        api_method=body.apiMethod, api_path=body.apiPath, sort=body.sort)
    record_rbac_action(
        action="resource_create",
        target_type="sys_resource",
        target_id=r["id"],
        target_label=r["name"],
        resource_code="resource:create",
    )
    return ok(r, msg="已创建")


@router.put("/resources/{resource_id}", response_model=ApiResponse)
def update_resource(resource_id: str, body: ResourceUpdate) -> ApiResponse:
    svc = ResourceAdminService()
    before = svc.resources.get(resource_id)
    r = svc.update_resource(
        resource_id, menu_id=body.menuId, code=body.code, name=body.name, type=body.type,
        api_method=body.apiMethod, api_path=body.apiPath)
    record_rbac_action(
        action="resource_update",
        target_type="sys_resource",
        target_id=resource_id,
        target_label=r["name"],
        resource_code="resource:update",
        changes=AuditService.build_changes(
            before,
            r,
            fields=("menu_id", "code", "name", "type", "api_method", "api_path"),
        ),
    )
    return ok(r, msg="已保存")


@router.delete("/resources/{resource_id}", response_model=ApiResponse)
def delete_resource(resource_id: str) -> ApiResponse:
    ResourceAdminService().delete_resource(resource_id)
    record_rbac_action(
        action="resource_delete",
        target_type="sys_resource",
        target_id=resource_id,
        resource_code="resource:delete",
    )
    return ok(msg="已删除")
