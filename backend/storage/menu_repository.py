"""菜单仓库（sys_menu，PG，占位符 %s）——多租户 RBAC stage3·T7（R12）。

菜单为平台级全局表（无 tenant_id），承载导航树：group（分组，仅展开）/ leaf（叶子，可导航）。
icon 存 Element Plus 图标名；visible=login（登录可见）/ system（仅系统管理员）。code 全局唯一、
建后不可改（作稳定自然键）；leaf 的 route_path 在非空叶子间唯一。删除/授权 bump 由 service 编排。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.menu_repository")

_MENU_COLS = "id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin"


def _build_tree(rows: list[dict]) -> list[dict]:
    """把展平（已按 sort 排序）的菜单行装配成嵌套树，children 保持 sort 顺序。"""
    by_id = {r["id"]: {**r, "children": []} for r in rows}
    roots: list[dict] = []
    for r in rows:
        node = by_id[r["id"]]
        parent = by_id.get(r["parent_id"]) if r["parent_id"] else None
        (parent["children"] if parent else roots).append(node)
    return roots


class MenuRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    @staticmethod
    def _row(r: dict) -> dict:
        return {
            "id": r["id"], "parent_id": r.get("parent_id"), "code": r["code"],
            "title": r["title"], "type": r["type"], "route_path": r.get("route_path"),
            "icon": r.get("icon"), "sort": int(r["sort"]), "visible": r["visible"],
            "is_builtin": bool(r["is_builtin"]),
        }

    def list_all(self) -> list[dict]:
        df = self.pg.query_df(f"SELECT {_MENU_COLS} FROM sys_menu ORDER BY sort, title")
        return [self._row(r.to_dict()) for _, r in df.iterrows()]

    def tree(self) -> list[dict]:
        return _build_tree(self.list_all())

    def get(self, menu_id: str) -> dict | None:
        df = self.pg.query_df(f"SELECT {_MENU_COLS} FROM sys_menu WHERE id = %s", [menu_id])
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def get_by_code(self, code: str) -> dict | None:
        df = self.pg.query_df(f"SELECT {_MENU_COLS} FROM sys_menu WHERE code = %s", [code])
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def route_exists(self, route_path: str, *, exclude_id: str | None = None) -> bool:
        """非空 route_path 是否已被其它菜单占用（叶子路由唯一性）。"""
        sql = "SELECT 1 FROM sys_menu WHERE route_path = %s"
        params: list = [route_path]
        if exclude_id:
            sql += " AND id <> %s"
            params.append(exclude_id)
        return not self.pg.query_df(sql + " LIMIT 1", params).empty

    def child_count(self, menu_id: str) -> int:
        df = self.pg.query_df(
            "SELECT count(*) AS n FROM sys_menu WHERE parent_id = %s", [menu_id])
        return int(df.iloc[0]["n"])

    def resource_count(self, menu_id: str) -> int:
        """归属该菜单的功能点数（sys_resource.menu_id 为 ON DELETE RESTRICT，删前须查，避免库错）。"""
        df = self.pg.query_df(
            "SELECT count(*) AS n FROM sys_resource WHERE menu_id = %s", [menu_id])
        return int(df.iloc[0]["n"])

    def is_descendant(self, node_id: str, maybe_ancestor_id: str) -> bool:
        """maybe_ancestor_id 是否为 node_id 的祖先（含自身）——防移动成环。自下而上走父链。"""
        cur: str | None = node_id
        seen: set[str] = set()
        while cur and cur not in seen:
            if cur == maybe_ancestor_id:
                return True
            seen.add(cur)
            df = self.pg.query_df("SELECT parent_id FROM sys_menu WHERE id = %s", [cur])
            cur = None if df.empty else df.iloc[0]["parent_id"]
        return False

    def _next_sort(self, parent_id: str | None) -> int:
        df = self.pg.query_df(
            "SELECT COALESCE(max(sort), 0) AS m FROM sys_menu WHERE parent_id IS NOT DISTINCT FROM %s",
            [parent_id])
        return int(df.iloc[0]["m"]) + 10

    def create(self, *, parent_id: str | None, code: str, title: str, type: str,
               route_path: str | None, icon: str | None, visible: str,
               sort: int | None) -> str:
        menu_id = uuid.uuid4().hex
        self.pg.execute(
            "INSERT INTO sys_menu "
            "(id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)",
            [menu_id, parent_id, code, title, type, route_path, icon,
             sort if sort is not None else self._next_sort(parent_id), visible, datetime.now()])
        return menu_id

    def update(self, menu_id: str, *, title: str, type: str, route_path: str | None,
               icon: str | None, visible: str, parent_id: str | None) -> None:
        """编辑菜单（code 不可改）。parent_id 变更即移动节点（成环由 service 先校验）。"""
        self.pg.execute(
            "UPDATE sys_menu SET title=%s, type=%s, route_path=%s, icon=%s, visible=%s, "
            "parent_id=%s, updated_at=%s WHERE id=%s",
            [title, type, route_path, icon, visible, parent_id, datetime.now(), menu_id])

    def delete(self, menu_id: str) -> None:
        """删菜单（sys_role_menu 经 FK CASCADE 自动清；有子节点时 DB RESTRICT，service 先查 child_count）。"""
        self.pg.execute("DELETE FROM sys_menu WHERE id = %s", [menu_id])

    def reorder(self, items: list[dict]) -> None:
        """批量改排序（可含 parentId 移动），单事务。items=[{id, sort, parentId?}]。"""
        with self.pg.transaction() as conn, conn.cursor() as cur:
            for it in items:
                if "parentId" in it:
                    cur.execute(
                        "UPDATE sys_menu SET sort=%s, parent_id=%s, updated_at=%s WHERE id=%s",
                        [int(it["sort"]), it.get("parentId"), datetime.now(), it["id"]])
                else:
                    cur.execute(
                        "UPDATE sys_menu SET sort=%s, updated_at=%s WHERE id=%s",
                        [int(it["sort"]), datetime.now(), it["id"]])
