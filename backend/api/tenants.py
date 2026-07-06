"""租户管理 API（多租户 RBAC stage3·T9，R14）。

薄层：参数校验 + 响应包装；守卫/业务规则/停用踢下线编排在 services.tenant_admin_service。
租户是平台级实体，管理入口仅系统管理员——全部端点挂 require_system。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_system
from backend.services.audit_service import AuditService
from backend.services.rbac_audit import record_rbac_action
from backend.services.tenant_admin_service import TenantAdminService

router = APIRouter(prefix="/api", tags=["tenants"], dependencies=[Depends(require_system)])


class TenantCreate(BaseModel):
    name: str
    status: str = "active"


class TenantUpdate(BaseModel):
    name: str
    adminUserId: str | None = None


class StatusBody(BaseModel):
    status: str                       # active | disabled


@router.get("/tenants", response_model=ApiResponse)
def list_tenants(q: str | None = None, status: str | None = None,
                 page: int = 1, size: int = 20,
                 sort_by: str = "created", sort_order: str = "desc") -> ApiResponse:
    return ok(TenantAdminService().list_tenants(
        q=q, status=status, page=page, size=size, sort_by=sort_by, sort_order=sort_order))


@router.post("/tenants", response_model=ApiResponse)
def create_tenant(body: TenantCreate) -> ApiResponse:
    t = TenantAdminService().create_tenant(name=body.name, status=body.status)
    record_rbac_action(
        action="tenant_create",
        target_type="sys_tenant",
        target_id=t["id"],
        target_label=t["name"],
        resource_code="tenant:create",
    )
    return ok(t, msg="已创建")


@router.put("/tenants/{tenant_id}", response_model=ApiResponse)
def update_tenant(tenant_id: str, body: TenantUpdate) -> ApiResponse:
    svc = TenantAdminService()
    before = svc.tenants.get(tenant_id)
    t = svc.update_tenant(
        tenant_id, name=body.name, admin_user_id=body.adminUserId)
    record_rbac_action(
        action="tenant_update",
        target_type="sys_tenant",
        target_id=tenant_id,
        target_label=t["name"],
        resource_code="tenant:update",
        changes=AuditService.build_changes(before, t, fields=("name", "admin_user_id")),
    )
    return ok(t, msg="已保存")


@router.post("/tenants/{tenant_id}/status", response_model=ApiResponse)
def set_status(tenant_id: str, body: StatusBody) -> ApiResponse:
    svc = TenantAdminService()
    before = svc.tenants.get(tenant_id)
    t = svc.set_status(tenant_id, body.status)
    record_rbac_action(
        action="tenant_status",
        target_type="sys_tenant",
        target_id=tenant_id,
        target_label=t["name"],
        resource_code="tenant:disable",
        changes=AuditService.build_changes(before, t, fields=("status",)),
    )
    return ok(t, msg="已更新")


@router.delete("/tenants/{tenant_id}", response_model=ApiResponse)
def delete_tenant(tenant_id: str) -> ApiResponse:
    TenantAdminService().delete_tenant(tenant_id)
    record_rbac_action(
        action="tenant_delete",
        target_type="sys_tenant",
        target_id=tenant_id,
        resource_code="tenant:delete",
    )
    return ok(msg="已删除")
