"""角色管理编排（多租户 RBAC stage3·T6，R11）。

承接角色管理页：列表 / 新建自定义角色 / 编辑 / 删除 / 授权（菜单+功能，全选/清空/还原由前端树驱动，
后端只做"替换保存"）。守卫与业务规则集中在此，api/roles.py 只做参数校验与响应包装。

业务规则（阶段三铁律）：
- **内置保护**：is_builtin 角色不可删除（system/tenant_admin/normal/paid）。
- **超管锁定**：is_locked 角色（system 超管）名称/描述与授权均不可改（其权限由 perm_resolver 判全量）。
- **唯一**：角色 code 全局唯一，且不得撞内置码。
- **删除前置**：角色下仍有用户时不可删（避免 FK RESTRICT 直接抛库错，给友好提示）。
- **system-only 码不可授**：require_system 硬守卫的功能码不能授予非 system 角色（授了也不生效，防误导）。
- **授权即时生效**：改授权 → bump_users_of_roles（拥有该角色的用户 perm_ver+1 + 清缓存）→ 下次请求重登拿新权限。

角色为平台级全局表（无 tenant_id），管理入口仅 system（api 层挂 require_system）；assignable 例外，供
用户管理页下拉，挂 require_perm(user:list)（tenant_admin 经授权可读），分流逻辑在 RoleRepository。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.auth.constants import BUILTIN_ROLES
from backend.auth.context import AuthContext
from backend.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.storage.role_repository import RoleRepository

log = get_logger("services.role_admin")


class RoleAdminService:
    def __init__(self, roles: RoleRepository | None = None):
        self.roles = roles or RoleRepository()

    # ── 列表 / 可分配 ──
    def list_roles(self) -> list[dict]:
        return self.roles.list_all()

    def assignable_roles(self, ctx: AuthContext) -> list[dict]:
        """供用户管理页角色下拉；按调用者角色分流（system 含自建 custom，tenant_admin 仅系统预设）。"""
        return self.roles.assignable(is_system=ctx.is_system)

    # ── 新建 ──
    def create_role(self, *, code: str, name: str, description: str | None) -> dict:
        code = (code or "").strip()
        name = (name or "").strip()
        if not code:
            raise ValidationError("请填写角色标识 code")
        if not name:
            raise ValidationError("请填写角色名称")
        if code in BUILTIN_ROLES or self.roles.get_by_code(code):
            raise ValidationError("角色标识已存在")
        rid = self.roles.create(code=code, name=name, description=description)
        log.info("角色管理：新建自定义角色 %s(%s)", rid, code)
        return self.roles.get(rid)  # type: ignore[return-value]

    # ── 编辑（名称/描述）──
    def update_role(self, role_id: str, *, name: str, description: str | None) -> dict:
        role = self._load(role_id)
        if role["is_locked"]:
            raise ForbiddenError("系统超级管理员角色已锁定，不可修改")
        name = (name or "").strip()
        if not name:
            raise ValidationError("请填写角色名称")
        self.roles.update(role_id, name=name, description=description)
        log.info("角色管理：编辑角色 %s name=%s", role_id, name)
        return self.roles.get(role_id)  # type: ignore[return-value]

    # ── 删除 ──
    def delete_role(self, role_id: str) -> None:
        role = self._load(role_id)
        if role["is_builtin"]:
            raise ForbiddenError("内置角色不可删除")
        if self.roles.member_count(role_id) > 0:
            raise ValidationError("该角色下仍有用户，请先移除后再删除")
        self.roles.delete(role_id)
        log.info("角色管理：删除自定义角色 %s(%s)", role_id, role["code"])

    # ── 授权读 / 写 ──
    def get_grants(self, role_id: str) -> dict:
        self._load(role_id)
        return self.roles.get_grants(role_id)

    def set_grants(self, role_id: str, *, menu_ids: list[str], resource_ids: list[str]) -> dict:
        role = self._load(role_id)
        if role["is_locked"]:
            raise ForbiddenError("系统超级管理员角色已锁定，权限不可修改")
        menu_ids = list(dict.fromkeys(menu_ids or []))
        resource_ids = list(dict.fromkeys(resource_ids or []))
        # 存在性：非法 id 直接拒（否则 FK 抛库错 → 500）
        if self.roles.existing_menu_ids(menu_ids) != set(menu_ids):
            raise ValidationError("包含不存在的菜单")
        if self.roles.existing_resource_ids(resource_ids) != set(resource_ids):
            raise ValidationError("包含不存在的功能点")
        # system-only 码不可授予非 system 角色
        if set(resource_ids) & self.roles.system_only_resource_ids():
            raise ForbiddenError("包含仅系统管理员可用的功能，不能授予该角色")
        self.roles.set_grants(role_id, menu_ids=menu_ids, resource_ids=resource_ids)
        # 授权即时生效：拥有该角色的用户 perm_ver+1 + 清缓存 → 下次请求 401 重登拿新权限
        n = perm_resolver.bump_users_of_roles([role_id])
        log.info("角色管理：角色 %s 授权更新 menus=%d resources=%d，%d 个用户失效",
                 role_id, len(menu_ids), len(resource_ids), n)
        return self.roles.get_grants(role_id)

    # ── 内部 ──
    def _load(self, role_id: str) -> dict:
        role = self.roles.get(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        return role
