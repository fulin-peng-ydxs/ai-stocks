"""角色管理 API（多租户 RBAC stage3·T6，R11）。

薄层：参数校验 + 响应包装；守卫/业务规则/失效编排在 services.role_admin_service。
角色是平台级全局表，管理入口仅系统管理员——除 assignable 外全部挂 require_system；
`GET /api/roles/assignable` 挂 require_perm(user:list)（供用户管理页下拉，tenant_admin 经授权可读）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm, require_system
from backend.common.exceptions import AuthError
from backend.services.audit_service import AuditService
from backend.services.rbac_audit import record_rbac_action
from backend.services.role_admin_service import RoleAdminService

router = APIRouter(prefix="/api", tags=["roles"])


def _ctx():
    ctx = get_current_context()
    if ctx is None:            # 理论上中间件已保证；防御式兜底
        raise AuthError("未登录")
    return ctx


class RoleCreate(BaseModel):
    code: str | None = None
    name: str
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str
    description: str | None = None


class GrantsBody(BaseModel):
    menuIds: list[str] = []
    resourceIds: list[str] = []


# assignable 先声明：静态段，避免被 /roles/{role_id} 之类动态段误匹配
@router.get("/roles/assignable", response_model=ApiResponse,
            dependencies=[Depends(require_perm("user:list"))])
def assignable_roles() -> ApiResponse:
    return ok(RoleAdminService().assignable_roles(_ctx()))


@router.get("/roles", response_model=ApiResponse,
            dependencies=[Depends(require_system)])
def list_roles() -> ApiResponse:
    return ok(RoleAdminService().list_roles())


@router.post("/roles", response_model=ApiResponse,
             dependencies=[Depends(require_system)])
def create_role(body: RoleCreate) -> ApiResponse:
    r = RoleAdminService().create_role(
        code=body.code, name=body.name, description=body.description)
    record_rbac_action(
        action="role_create",
        target_type="sys_role",
        target_id=r["id"],
        target_label=r["name"],
        resource_code="role:create",
    )
    return ok(r, msg="已创建")


@router.put("/roles/{role_id}", response_model=ApiResponse,
            dependencies=[Depends(require_system)])
def update_role(role_id: str, body: RoleUpdate) -> ApiResponse:
    svc = RoleAdminService()
    before = svc.roles.get(role_id)
    r = svc.update_role(role_id, name=body.name, description=body.description)
    record_rbac_action(
        action="role_update",
        target_type="sys_role",
        target_id=role_id,
        target_label=r["name"],
        resource_code="role:update",
        changes=AuditService.build_changes(before, r, fields=("name", "description")),
    )
    return ok(r, msg="已保存")


@router.delete("/roles/{role_id}", response_model=ApiResponse,
               dependencies=[Depends(require_system)])
def delete_role(role_id: str) -> ApiResponse:
    RoleAdminService().delete_role(role_id)
    record_rbac_action(
        action="role_delete",
        target_type="sys_role",
        target_id=role_id,
        resource_code="role:delete",
    )
    return ok(msg="已删除")


@router.get("/roles/{role_id}/perms", response_model=ApiResponse,
            dependencies=[Depends(require_system)])
def get_role_perms(role_id: str) -> ApiResponse:
    return ok(RoleAdminService().get_grants(role_id))


@router.put("/roles/{role_id}/perms", response_model=ApiResponse,
            dependencies=[Depends(require_system)])
def set_role_perms(role_id: str, body: GrantsBody) -> ApiResponse:
    svc = RoleAdminService()
    before = svc.get_grants(role_id)
    grants = svc.set_grants(
        role_id, menu_ids=body.menuIds, resource_ids=body.resourceIds)
    record_rbac_action(
        action="role_set_perms",
        target_type="sys_role",
        target_id=role_id,
        resource_code="role:assign-perm",
        affected_count=len(body.menuIds) + len(body.resourceIds),
        changes=AuditService.build_changes(
            before,
            grants,
            fields=("menu_ids", "resource_ids"),
        ),
    )
    return ok(grants, msg="权限已保存")
