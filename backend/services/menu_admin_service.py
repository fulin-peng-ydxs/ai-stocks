"""菜单管理编排（多租户 RBAC stage3·T7，R12）。

承接菜单管理页：菜单树读取 / 新建 / 编辑 / 删除 / 排序。守卫（require_system）在 api 层，
业务规则与缓存失效编排集中在此，api/menus.py 只做参数校验与响应包装。

业务规则（阶段三铁律）：
- **类型/可见性/标题校验**：type∈{group,leaf}、visible∈{login,system}、标题非空。
- **唯一**：code 全局唯一且建后不可改（稳定自然键）；leaf 的非空 route_path 在菜单间唯一。
- **内置保护**：is_builtin 菜单对应已发布前端页面/路由，不可删除（可改标题/图标/可见性）。
- **级联保护**：有子节点的菜单不可直接删（先删子节点，避免 FK RESTRICT 抛库错）。
- **防成环**：移动节点（改 parent）时目标父不得是自身或自身子孙。
- **缓存失效（Codex P1）**：**删除、可见性变更 → bump_users_of_menu**（引用该菜单角色的用户 ∪ 全部
  system 用户，下次请求 401 重登拿新视图）。新建为**加性变更**（新节点尚无引用），不立即 bump——
  system 用户按缓存 TTL 自然刷新即可见，避免每次加菜单就强制管理员重登（对齐 plan §6.7 口径：仅
  删除/可见性变更失效）；纯展示编辑（标题/图标/路由/排序，可见性未变）与排序同理不 bump。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.storage.menu_repository import MenuRepository

log = get_logger("services.menu_admin")

_VALID_TYPE = {"group", "leaf"}
_VALID_VISIBLE = {"login", "system"}


class MenuAdminService:
    def __init__(self, menus: MenuRepository | None = None):
        self.menus = menus or MenuRepository()

    # ── 读 ──
    def tree(self) -> list[dict]:
        return self.menus.tree()

    # ── 新建 ──
    def create_menu(self, *, parent_id: str | None, code: str, title: str, type: str,
                    route_path: str | None, icon: str | None, visible: str,
                    sort: int | None) -> dict:
        code = (code or "").strip()
        title = (title or "").strip()
        self._check_type(type)
        self._check_visible(visible)
        if not code:
            raise ValidationError("请填写菜单标识 code")
        if not title:
            raise ValidationError("请填写菜单标题")
        if self.menus.get_by_code(code):
            raise ValidationError("菜单标识已存在")
        route_path = self._normalize_route(type, route_path, exclude_id=None)
        if parent_id and self.menus.get(parent_id) is None:
            raise ValidationError("上级菜单不存在")
        mid = self.menus.create(
            parent_id=parent_id, code=code, title=title, type=type,
            route_path=route_path, icon=icon, visible=visible, sort=sort)
        log.info("菜单管理：新建菜单 %s(%s) type=%s parent=%s", mid, code, type, parent_id)
        return self.menus.get(mid)  # type: ignore[return-value]

    # ── 编辑 ──
    def update_menu(self, menu_id: str, *, title: str, type: str, route_path: str | None,
                    icon: str | None, visible: str, parent_id: str | None) -> dict:
        cur = self._load(menu_id)
        title = (title or "").strip()
        self._check_type(type)
        self._check_visible(visible)
        if not title:
            raise ValidationError("请填写菜单标题")
        route_path = self._normalize_route(type, route_path, exclude_id=menu_id)
        # 移动节点：目标父须存在且不成环
        if parent_id != cur["parent_id"]:
            if parent_id:
                if parent_id == menu_id:
                    raise ValidationError("上级菜单不能是自身")
                if self.menus.get(parent_id) is None:
                    raise ValidationError("上级菜单不存在")
                if self.menus.is_descendant(parent_id, menu_id):
                    raise ValidationError("不能移动到自身的子节点下")
        self.menus.update(menu_id, title=title, type=type, route_path=route_path,
                          icon=icon, visible=visible, parent_id=parent_id)
        # 可见性变更 → 失效（登录可见性收紧/放开影响谁能看到该菜单）
        if visible != cur["visible"]:
            n = perm_resolver.bump_users_of_menu(menu_id)
            log.info("菜单管理：菜单 %s 可见性 %s→%s，%d 个用户失效",
                     menu_id, cur["visible"], visible, n)
        else:
            log.info("菜单管理：编辑菜单 %s title=%s", menu_id, title)
        return self.menus.get(menu_id)  # type: ignore[return-value]

    # ── 删除 ──
    def delete_menu(self, menu_id: str) -> None:
        cur = self._load(menu_id)
        if cur["is_builtin"]:
            raise ForbiddenError("内置菜单不可删除")
        if self.menus.child_count(menu_id) > 0:
            raise ValidationError("该菜单存在子节点，请先删除子节点")
        # 先 bump（删除后 role_menu 经 CASCADE 清空，届时查不到引用用户）
        n = perm_resolver.bump_users_of_menu(menu_id)
        self.menus.delete(menu_id)
        log.info("菜单管理：删除菜单 %s(%s)，%d 个用户失效", menu_id, cur["code"], n)

    # ── 排序 / 移动（sort/parent，不改权限成员 → 不 bump）──
    def reorder(self, items: list[dict]) -> list[dict]:
        for it in items:
            mid = it.get("id")
            if not mid or self.menus.get(mid) is None:
                raise ValidationError("包含不存在的菜单节点")
            pid = it.get("parentId")
            if pid:
                if pid == mid:
                    raise ValidationError("上级菜单不能是自身")
                if self.menus.get(pid) is None:
                    raise ValidationError("上级菜单不存在")
                if self.menus.is_descendant(pid, mid):
                    raise ValidationError("不能移动到自身的子节点下")
        self.menus.reorder(items)
        log.info("菜单管理：排序更新 %d 项", len(items))
        return self.menus.tree()

    # ── 内部 ──
    def _load(self, menu_id: str) -> dict:
        m = self.menus.get(menu_id)
        if m is None:
            raise NotFoundError("菜单不存在")
        return m

    def _normalize_route(self, type: str, route_path: str | None, *, exclude_id: str | None) -> str | None:
        """group 强制 route=None；leaf 须有 route 且非空 route 唯一。返回规范化后的 route_path。"""
        if type == "group":
            return None
        route_path = (route_path or "").strip()
        if not route_path:
            raise ValidationError("叶子菜单须填写路由 route_path")
        if self.menus.route_exists(route_path, exclude_id=exclude_id):
            raise ValidationError("路由已被其它菜单占用")
        return route_path

    @staticmethod
    def _check_type(type: str) -> None:
        if type not in _VALID_TYPE:
            raise ValidationError(f"无效的菜单类型：{type}")

    @staticmethod
    def _check_visible(visible: str) -> None:
        if visible not in _VALID_VISIBLE:
            raise ValidationError(f"无效的可见性：{visible}")
