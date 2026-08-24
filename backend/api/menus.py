"""菜单管理 API（多租户 RBAC stage3·T7，R12）。

薄层：参数校验 + 响应包装；守卫/业务规则/失效编排在 services.menu_admin_service。
菜单是平台级全局表，管理入口仅系统管理员——全部端点挂 require_system。
icon 存 Element Plus 图标名；type=group/leaf；visible=login/system。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.response import ApiResponse, ok
from backend.auth.deps import require_system
from backend.services.audit_service import AuditService
from backend.services.menu_admin_service import MenuAdminService
from backend.services.rbac_audit import record_rbac_action

router = APIRouter(prefix="/api", tags=["menus"], dependencies=[Depends(require_system)])


class MenuCreate(BaseModel):
    parentId: str | None = None
    code: str | None = None
    title: str
    type: str = "leaf"                # group | leaf
    routePath: str | None = None
    icon: str | None = None
    visible: str = "login"            # login | system
    sort: int | None = None


class MenuUpdate(BaseModel):
    title: str
    type: str = "leaf"
    routePath: str | None = None
    icon: str | None = None
    visible: str = "login"
    parentId: str | None = None


class ReorderBody(BaseModel):
    items: list[dict] = []            # [{id, sort, parentId?}]


@router.get("/menus", response_model=ApiResponse)
def list_menus() -> ApiResponse:
    return ok(MenuAdminService().tree())


@router.post("/menus", response_model=ApiResponse)
def create_menu(body: MenuCreate) -> ApiResponse:
    m = MenuAdminService().create_menu(
        parent_id=body.parentId, code=body.code, title=body.title, type=body.type,
        route_path=body.routePath, icon=body.icon, visible=body.visible, sort=body.sort)
    record_rbac_action(
        action="menu_create",
        target_type="sys_menu",
        target_id=m["id"],
        target_label=m["title"],
        resource_code="menu:create",
    )
    return ok(m, msg="已创建")


@router.post("/menus/reorder", response_model=ApiResponse)
def reorder_menus(body: ReorderBody) -> ApiResponse:
    tree, changed_items = MenuAdminService().reorder_with_changes(body.items)
    # 批量请求按菜单分别留痕，才能通过 target_id 还原具体节点的父级和排序变化。
    for item in changed_items:
        before = item["before"]
        after = item["after"]
        record_rbac_action(
            action="menu_reorder",
            target_type="sys_menu",
            target_id=before["id"],
            target_label=before["title"],
            resource_code="menu:reorder",
            changes=AuditService.build_changes(
                before,
                after,
                fields=("parent_id", "sort"),
            ),
        )
    return ok(tree, msg="排序已保存")


# menu_id 用 :path 转换器：内置菜单 seed id=code 含斜杠（如 /screen、/system/users），
# 普通 str 段无法匹配（会 404/405）；:path 可捕获且不与 /menus/reorder(POST) 冲突（方法不同、
# 且该前缀下无其它子资源）。前端 `/api/menus/${id}` 对含斜杠 id 天然形成路径。
@router.put("/menus/{menu_id:path}", response_model=ApiResponse)
def update_menu(menu_id: str, body: MenuUpdate) -> ApiResponse:
    svc = MenuAdminService()
    before = svc.menus.get(menu_id)
    m = svc.update_menu(
        menu_id, title=body.title, type=body.type, route_path=body.routePath,
        icon=body.icon, visible=body.visible, parent_id=body.parentId)
    record_rbac_action(
        action="menu_update",
        target_type="sys_menu",
        target_id=menu_id,
        target_label=m["title"],
        resource_code="menu:update",
        changes=AuditService.build_changes(
            before,
            m,
            fields=("title", "type", "route_path", "icon", "visible", "parent_id"),
        ),
    )
    return ok(m, msg="已保存")


@router.delete("/menus/{menu_id:path}", response_model=ApiResponse)
def delete_menu(menu_id: str) -> ApiResponse:
    before = MenuAdminService().delete_menu(menu_id)
    record_rbac_action(
        action="menu_delete",
        target_type="sys_menu",
        target_id=menu_id,
        target_label=before["title"],
        resource_code="menu:delete",
        changes=AuditService.build_changes(
            before,
            None,
            fields=(
                "parent_id", "code", "title", "type", "route_path",
                "icon", "sort", "visible", "is_builtin",
            ),
        ),
    )
    return ok(msg="已删除")
