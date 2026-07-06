"""用户管理 API（多租户 RBAC stage3·T5，R10）。

薄层：参数校验 + 响应包装；域过滤/守卫/失效编排在 services.user_admin_service。
逐端点挂 require_perm 精确码（system 恒过，tenant_admin 经授权管本租户用户）。
归属/角色一律取自上下文，前端传的 tenantId 仅 system 生效（tenant_admin 忽略，防越权）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.auth.context import get_current_context
from backend.auth.deps import require_perm
from backend.common.exceptions import AuthError
from backend.services.audit_service import AuditService
from backend.services.rbac_audit import record_rbac_action
from backend.services.user_admin_service import UserAdminService

router = APIRouter(prefix="/api", tags=["users"])


def _ctx():
    ctx = get_current_context()
    if ctx is None:            # 理论上中间件已保证；防御式兜底
        raise AuthError("未登录")
    return ctx


class UserCreate(BaseModel):
    account: str
    password: str
    email: str | None = None
    roleIds: list[str] = []
    status: str = "active"
    tenantId: str | None = None       # 仅 system 生效；tenant_admin 忽略


class UserUpdate(BaseModel):
    email: str | None = None
    roleIds: list[str] = []
    status: str = "active"


class StatusBody(BaseModel):
    status: str                       # active | disabled | locked


class ResetPwdBody(BaseModel):
    password: str


@router.get("/users", response_model=ApiResponse,
            dependencies=[Depends(require_perm("user:list"))])
def list_users(tenant_id: str | None = None, role: str | None = None,
               status: str | None = None, q: str | None = None,
               page: int = 1, size: int = 20,
               sort_by: str = "created", sort_order: str = "desc") -> ApiResponse:
    return ok(UserAdminService().list_users(
        _ctx(), tenant_id=tenant_id, role=role, status=status, q=q, page=page, size=size,
        sort_by=sort_by, sort_order=sort_order))


@router.post("/users", response_model=ApiResponse,
             dependencies=[Depends(require_perm("user:create"))])
def create_user(body: UserCreate) -> ApiResponse:
    ctx = _ctx()
    u = UserAdminService().create_user(
        ctx, account=body.account, password=body.password, email=body.email,
        role_ids=body.roleIds, status=body.status, tenant_id=body.tenantId)
    record_rbac_action(
        action="user_create",
        target_type="sys_user",
        target_id=u["id"],
        target_label=u["account"],
        resource_code="user:create",
    )
    return ok(u, msg="已创建")


@router.put("/users/{user_id}", response_model=ApiResponse,
            dependencies=[Depends(require_perm("user:update"))])
def update_user(user_id: str, body: UserUpdate) -> ApiResponse:
    ctx = _ctx()
    svc = UserAdminService()
    before = svc.users.get_admin_view(user_id)
    u = svc.update_user(
        ctx, user_id, email=body.email, role_ids=body.roleIds, status=body.status)
    record_rbac_action(
        action="user_update",
        target_type="sys_user",
        target_id=user_id,
        target_label=u["account"],
        resource_code="user:update",
        changes=AuditService.build_changes(before, u, fields=("email", "status", "roles")),
    )
    return ok(u, msg="已保存")


@router.post("/users/{user_id}/status", response_model=ApiResponse,
             dependencies=[Depends(require_perm("user:disable"))])
def set_status(user_id: str, body: StatusBody) -> ApiResponse:
    svc = UserAdminService()
    before = svc.users.get_admin_view(user_id)
    u = svc.set_status(_ctx(), user_id, body.status)
    record_rbac_action(
        action="user_status",
        target_type="sys_user",
        target_id=user_id,
        target_label=u["account"],
        resource_code="user:disable",
        changes=AuditService.build_changes(before, u, fields=("status",)),
    )
    return ok(u, msg="已更新")


@router.post("/users/{user_id}/reset-password", response_model=ApiResponse,
             dependencies=[Depends(require_perm("user:reset-password"))])
def reset_password(user_id: str, body: ResetPwdBody) -> ApiResponse:
    UserAdminService().reset_password(_ctx(), user_id, body.password)
    record_rbac_action(
        action="user_reset_password",
        target_type="sys_user",
        target_id=user_id,
        resource_code="user:reset-password",
        changes=AuditService.build_changes(
            {"password": None},
            {"password": "updated"},
            fields=("password",),
        ),
    )
    return ok(msg="密码已重置")


@router.delete("/users/{user_id}", response_model=ApiResponse,
               dependencies=[Depends(require_perm("user:delete"))])
def delete_user(user_id: str) -> ApiResponse:
    UserAdminService().delete_user(_ctx(), user_id)
    record_rbac_action(
        action="user_delete",
        target_type="sys_user",
        target_id=user_id,
        resource_code="user:delete",
    )
    return ok(msg="已删除")
