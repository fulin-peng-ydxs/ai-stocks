"""功能点管理编排（多租户 RBAC stage3·T8，R13）。

承接菜单&功能页的功能点子表：按菜单登记 / 新建 / 编辑 / 删除。守卫（require_system）在 api 层，
业务规则与缓存失效编排集中在此，api/resources.py 只做参数校验与响应包装。

业务规则（阶段三铁律）：
- **类型校验**：type∈{button,api}；code/name 非空。
- **唯一不可复用**：code 全局唯一（撞现有拒）。
- **内置保护**：is_builtin 功能码与端点 require_perm 硬绑，**不可删、code 不可改**（可改 name/type/接口元数据）。
- **归属菜单存在**：menu_id 必须指向已存在菜单。
- **缓存失效（Codex 三轮 P1）**：**删除、改 code → 失效"夹住"业务写入**——写前 `pre_invalidate(affected)`
  （仅清 Redis，fail-closed 门禁）→ 写库 → 写后 `bump_and_invalidate(affected)`（perm_ver++ + 双删），
  保证 perm_ver 自增晚于业务提交。affected = 引用该功能角色的用户 ∪ 全部 system 用户，**删除前算定**（删后
  role_resource CASCADE 清空即查不到引用用户）。改 code = 有效权限码变，故失效；改 name/type/接口元数据/
  移动菜单不影响权限码，不失效；新建为加性变更（无引用）不失效——system 按缓存 TTL 自然刷新（plan §6.8）。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.storage.menu_repository import MenuRepository
from backend.storage.resource_repository import ResourceRepository

log = get_logger("services.resource_admin")

_VALID_TYPE = {"button", "api"}


class ResourceAdminService:
    def __init__(self, resources: ResourceRepository | None = None,
                 menus: MenuRepository | None = None):
        self.resources = resources or ResourceRepository()
        self.menus = menus or MenuRepository()

    # ── 读 ──
    def list_resources(self, menu_id: str | None) -> list[dict]:
        return self.resources.list_all(menu_id)

    # ── 新建 ──
    def create_resource(self, *, menu_id: str, code: str, name: str, type: str,
                        api_method: str | None, api_path: str | None,
                        sort: int | None) -> dict:
        code = (code or "").strip()
        name = (name or "").strip()
        self._check_type(type)
        if not code:
            raise ValidationError("请填写功能码 code")
        if not name:
            raise ValidationError("请填写功能名称")
        if not menu_id or self.menus.get(menu_id) is None:
            raise ValidationError("归属菜单不存在")
        if self.resources.get_by_code(code):
            raise ValidationError("功能码已存在，且不可复用")
        rid = self.resources.create(
            menu_id=menu_id, code=code, name=name, type=type,
            api_method=api_method, api_path=api_path, sort=sort)
        log.info("功能管理：新建功能点 %s(%s) menu=%s type=%s", rid, code, menu_id, type)
        return self.resources.get(rid)  # type: ignore[return-value]

    # ── 编辑 ──
    def update_resource(self, resource_id: str, *, menu_id: str, code: str, name: str,
                        type: str, api_method: str | None, api_path: str | None) -> dict:
        cur = self._load(resource_id)
        code = (code or "").strip()
        name = (name or "").strip()
        self._check_type(type)
        if not code:
            raise ValidationError("请填写功能码 code")
        if not name:
            raise ValidationError("请填写功能名称")
        code_changed = code != cur["code"]
        if cur["is_builtin"] and code_changed:
            raise ForbiddenError("内置功能码与接口守卫硬绑，不可修改")
        if code_changed and self.resources.get_by_code(code):
            raise ValidationError("功能码已存在，且不可复用")
        if not menu_id or self.menus.get(menu_id) is None:
            raise ValidationError("归属菜单不存在")
        # 改 code = 有效权限码变 → 失效"夹住"业务写入（Codex 三轮 P1）：affected 写前算定（成员不因本次
        # 编辑而变）→ 写前门禁清 Redis(fail-closed) → 写 → 写后 perm_ver++，使 perm_ver 自增晚于业务提交。
        affected = perm_resolver.affected_users_of_resource(resource_id) if code_changed else []
        if affected:
            perm_resolver.pre_invalidate(affected)
        self.resources.update(resource_id, menu_id=menu_id, code=code, name=name,
                              type=type, api_method=api_method, api_path=api_path)
        if affected:
            perm_resolver.bump_and_invalidate(affected)
            log.info("功能管理：功能 %s code %s→%s，%d 个用户失效",
                     resource_id, cur["code"], code, len(affected))
        else:
            log.info("功能管理：编辑功能 %s name=%s", resource_id, name)
        return self.resources.get(resource_id)  # type: ignore[return-value]

    # ── 删除 ──
    def delete_resource(self, resource_id: str) -> None:
        cur = self._load(resource_id)
        if cur["is_builtin"]:
            raise ForbiddenError("内置功能点不可删除")
        # 失效夹住业务写入（Codex 三轮 P1）：affected 删除前算定（删后 role_resource CASCADE 清空即查
        # 不到引用用户）→ 写前门禁清 Redis → 删除 → 写后 perm_ver++。
        affected = perm_resolver.affected_users_of_resource(resource_id)
        perm_resolver.pre_invalidate(affected)
        self.resources.delete(resource_id)
        perm_resolver.bump_and_invalidate(affected)
        log.info("功能管理：删除功能点 %s(%s)，%d 个用户失效", resource_id, cur["code"], len(affected))

    # ── 内部 ──
    def _load(self, resource_id: str) -> dict:
        r = self.resources.get(resource_id)
        if r is None:
            raise NotFoundError("功能点不存在")
        return r

    @staticmethod
    def _check_type(type: str) -> None:
        if type not in _VALID_TYPE:
            raise ValidationError(f"无效的功能类型：{type}")
