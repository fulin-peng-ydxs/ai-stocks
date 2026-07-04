"""菜单管理编排（多租户 RBAC stage3·T7，R12）。

承接菜单管理页：菜单树读取 / 新建 / 编辑 / 删除 / 排序。守卫（require_system）在 api 层，
业务规则与缓存失效编排集中在此，api/menus.py 只做参数校验与响应包装。

业务规则（阶段三铁律）：
- **类型/可见性/标题校验**：type∈{group,leaf}、visible∈{login,system}、标题非空。
- **唯一**：code 全局唯一且建后不可改（稳定自然键）；leaf 的非空 route_path 在菜单间唯一。
- **内置保护**：is_builtin 菜单对应已发布前端页面/路由，不可删除（可改标题/图标/可见性）。
- **级联保护**：有子节点的菜单不可直接删（先删子节点，避免 FK RESTRICT 抛库错）。
- **防成环**：移动节点（改 parent）时目标父不得是自身或自身子孙。
- **缓存失效（Codex 五轮 P1，原子化）**：**删除、可见性变更、移动跨可见域 → 菜单写入(conn) +
  `bump_perm_ver` 同一 PG 事务原子提交** → 提交后 `clear_perms_cache` best-effort。affected = 引用「该菜单
  **及其子孙**」角色的用户 ∪ 全部 system 用户，**删除前算定**（删后 role_menu CASCADE 清空即查不到引用
  用户）。新建为**加性变更**（新节点尚无引用），不失效——system 用户按缓存 TTL 自然刷新（对齐 plan §6.7：
  仅删除/可见性/移动失效）；纯展示编辑（标题/图标/路由，可见性未变）与纯排序不失效。
"""

from __future__ import annotations

from backend.auth import perm_resolver
from backend.common.ids import prefixed_readable_id
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
    def create_menu(self, *, parent_id: str | None, code: str | None, title: str, type: str,
                    route_path: str | None, icon: str | None, visible: str,
                    sort: int | None) -> dict:
        code = (code or "").strip()
        title = (title or "").strip()
        self._check_type(type)
        self._check_visible(visible)
        if not title:
            raise ValidationError("请填写菜单标题")
        if not code:
            code = self._make_menu_code(title)
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
        # 可见性变更（收紧/放开）或移动父节点（可能跨系统专属分支，改变非 system 用户可见菜单）→ 失效。
        vis_changed = visible != cur["visible"]
        moved = parent_id != cur["parent_id"]   # P2-c：移动跨可见域会改变非 system 用户可见菜单
        # affected 含子树、写前算定（移动不改自身子树集）；菜单写入 +（如需）perm_ver 自增**同事务原子
        # 提交**（Codex 五轮 P1）→ 提交后 best-effort 清缓存。
        affected = perm_resolver.affected_users_of_menu(menu_id) if (vis_changed or moved) else []
        with self.menus.pg.transaction() as conn:
            self.menus.update(menu_id, title=title, type=type, route_path=route_path,
                              icon=icon, visible=visible, parent_id=parent_id, conn=conn)
            if affected:
                perm_resolver.bump_perm_ver(affected, conn)
        if affected:
            perm_resolver.clear_perms_cache(affected)
            log.info("菜单管理：菜单 %s 变更(vis:%s→%s move:%s)，%d 个用户失效",
                     menu_id, cur["visible"], visible, moved, len(affected))
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
        # P2-a：sys_resource.menu_id 为 RESTRICT，菜单下有功能点直接删会退化为库错，须先查并给业务提示
        if self.menus.resource_count(menu_id) > 0:
            raise ValidationError("该菜单下存在功能点，请先删除功能点")
        # affected 删除前算定（删后 role_menu CASCADE 清空即查不到引用用户）；删除 + perm_ver 自增
        # **同事务原子提交**（Codex 五轮 P1）→ 提交后 best-effort 清缓存。
        affected = perm_resolver.affected_users_of_menu(menu_id)
        with self.menus.pg.transaction() as conn:
            self.menus.delete(menu_id, conn=conn)
            perm_resolver.bump_perm_ver(affected, conn)
        perm_resolver.clear_perms_cache(affected)
        log.info("菜单管理：删除菜单 %s(%s)，%d 个用户失效", menu_id, cur["code"], len(affected))

    # ── 排序 / 移动 ──
    def reorder(self, items: list[dict]) -> list[dict]:
        """批量排序/移动。纯排序不 bump；含移动(parent 变更)的节点 → bump（P2-c：跨可见域改变可见菜单）。"""
        moved: list[str] = []
        for it in items:
            mid = it.get("id")
            if not mid:
                raise ValidationError("包含不存在的菜单节点")
            node = self.menus.get(mid)
            if node is None:
                raise ValidationError("包含不存在的菜单节点")
            if "parentId" in it and it["parentId"] != node["parent_id"]:
                pid = it["parentId"]
                if pid:                                  # 移到某父下（None=移到根，无需下列校验）
                    if pid == mid:
                        raise ValidationError("上级菜单不能是自身")
                    if self.menus.get(pid) is None:
                        raise ValidationError("上级菜单不存在")
                    if self.menus.is_descendant(pid, mid):
                        raise ValidationError("不能移动到自身的子节点下")
                moved.append(mid)
        # 被移动节点的 affected（各含子树）写前一次性算定；排序落库 +（如有移动）perm_ver 自增**同事务
        # 原子提交**（Codex 五轮 P1）→ 提交后 best-effort 清缓存。纯排序(无 parent 变更)不影响可见性、不失效。
        affected: set[str] = set()
        for mid in moved:
            affected.update(perm_resolver.affected_users_of_menu(mid))
        affected_list = list(affected)
        with self.menus.pg.transaction() as conn:
            self.menus.reorder(items, conn=conn)
            if affected_list:
                perm_resolver.bump_perm_ver(affected_list, conn)
        if affected_list:
            perm_resolver.clear_perms_cache(affected_list)
        log.info("菜单管理：排序更新 %d 项（其中移动 %d 项已失效）", len(items), len(moved))
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

    def _make_menu_code(self, title: str) -> str:
        base = prefixed_readable_id(title, prefix="menu_")
        code = base
        seq = 2
        while self.menus.get(code) or self.menus.get_by_code(code):
            code = f"{base}_{seq}"
            seq += 1
        return code
