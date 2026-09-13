"""角色仓库（sys_role + 授权关联，PG，占位符 %s）——多租户 RBAC stage3。

T5 落**只读**部分（按 id 取角色、可分配角色集）；T6 扩展角色 CRUD + 菜单/功能授权
（role_menu/role_resource 全删重插）+ 内置/成员/ system-only 检测（bump 由 service 编排）。

可分配规则：
- 调用者是 system：返回全部角色，可为其他用户新增或撤销系统管理员角色；
- 调用者是 tenant_admin：返回平台明确标记 tenant_assignable 的非 system 角色。
"""

from __future__ import annotations

from datetime import datetime

from backend.auth.constants import EXPLICIT_SYSTEM_ONLY_RESOURCE_CODES
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.role_repository")

_ROLE_COLS = "id, code, name, kind, is_builtin, is_locked, tenant_assignable, description"

# 角色列表默认排序：system 超管在前，其余按内置优先 + 预设序 + 名称
_ROLE_ORDER = (
    "CASE kind WHEN 'system' THEN 0 WHEN 'tenant_admin' THEN 1 "
    "WHEN 'normal' THEN 2 ELSE 3 END, name")


class RoleRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    @staticmethod
    def _row(r: dict) -> dict:
        return {
            "id": r["id"], "code": r["code"], "name": r["name"], "kind": r["kind"],
            "is_builtin": bool(r["is_builtin"]), "is_locked": bool(r["is_locked"]),
            "tenant_assignable": bool(r["tenant_assignable"]),
            "description": r.get("description"),
        }

    def get_by_ids(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        df = self.pg.query_df(
            f"SELECT {_ROLE_COLS} FROM sys_role WHERE id = ANY(%s)", [list(dict.fromkeys(ids))])
        return [self._row(r.to_dict()) for _, r in df.iterrows()]

    def assignable(self, *, is_system: bool) -> list[dict]:
        """可分配角色集（按调用者身份分流，见模块 docstring）。"""
        if is_system:
            # 系统管理员可以任命其他系统管理员，也可以分配自建角色。
            df = self.pg.query_df(
                f"SELECT {_ROLE_COLS} FROM sys_role "
                f"ORDER BY is_builtin DESC, {_ROLE_ORDER}")
        else:
            # system 无论字段是否被误写都不可下放；其余角色由平台显式配置。
            df = self.pg.query_df(
                f"SELECT {_ROLE_COLS} FROM sys_role "
                "WHERE tenant_assignable = TRUE AND kind <> 'system' AND code <> 'system' "
                f"ORDER BY {_ROLE_ORDER}")
        return [self._row(r.to_dict()) for _, r in df.iterrows()]

    # ── T6：列表 / 单取 / CRUD ─────────────────────────────────────────────
    def list_all(self) -> list[dict]:
        """全部角色（含成员数），供角色管理页左栏列表。"""
        df = self.pg.query_df(
            f"SELECT {_ROLE_COLS}, "
            "(SELECT count(*) FROM sys_user_role ur WHERE ur.role_id = sys_role.id) AS member_count "
            f"FROM sys_role ORDER BY is_builtin DESC, {_ROLE_ORDER}")
        out: list[dict] = []
        for _, r in df.iterrows():
            row = self._row(r.to_dict())
            row["member_count"] = int(r["member_count"])
            out.append(row)
        return out

    def get(self, role_id: str) -> dict | None:
        rows = self.get_by_ids([role_id])
        return rows[0] if rows else None

    def get_by_code(self, code: str) -> dict | None:
        df = self.pg.query_df(
            f"SELECT {_ROLE_COLS} FROM sys_role WHERE lower(btrim(code)) = lower(btrim(%s))",
            [code],
        )
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def get_by_name(self, name: str) -> dict | None:
        df = self.pg.query_df(
            f"SELECT {_ROLE_COLS} FROM sys_role WHERE lower(btrim(name)) = lower(btrim(%s))",
            [name],
        )
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def create(self, *, code: str, name: str, description: str | None,
               tenant_assignable: bool) -> str:
        """新建自定义角色（kind=custom、is_builtin=false）。唯一性由 UNIQUE(code) 兜底。返回 id。"""
        role_id = code
        self.pg.execute(
            "INSERT INTO sys_role "
            "(id, code, name, kind, is_builtin, is_locked, tenant_assignable, description, created_at) "
            "VALUES (%s, %s, %s, 'custom', FALSE, FALSE, %s, %s, %s)",
            [role_id, code, name, tenant_assignable, description, datetime.now()])
        return role_id

    def update(self, role_id: str, *, name: str, description: str | None,
               tenant_assignable: bool) -> None:
        """编辑角色名称/描述/下放策略（code 与 kind 不可改，属身份稳定字段）。"""
        self.pg.execute(
            "UPDATE sys_role SET name = %s, description = %s, tenant_assignable = %s, "
            "updated_at = %s WHERE id = %s",
            [name, description, tenant_assignable, datetime.now(), role_id])

    def assigned_role_ids(self, user_id: str) -> list[str]:
        """读取用户当前角色 id，供租户管理员编辑时保留平台收回下放的角色。"""
        df = self.pg.query_df(
            "SELECT role_id FROM sys_user_role WHERE user_id = %s ORDER BY role_id", [user_id])
        return df["role_id"].tolist() if not df.empty else []

    def delete(self, role_id: str) -> None:
        """删角色（role_menu/role_resource 经 FK CASCADE 自动清；被 user_role 引用时 DB RESTRICT）。"""
        self.pg.execute("DELETE FROM sys_role WHERE id = %s", [role_id])

    def member_count(self, role_id: str) -> int:
        df = self.pg.query_df("SELECT count(*) AS n FROM sys_user_role WHERE role_id = %s", [role_id])
        return int(df.iloc[0]["n"])

    # ── T6：授权（菜单/功能）读写与校验 ───────────────────────────────────
    def get_grants(self, role_id: str) -> dict:
        """取角色当前授权的菜单 id 集与功能 id 集（供角色页勾选树回显）。"""
        m = self.pg.query_df("SELECT menu_id FROM sys_role_menu WHERE role_id = %s", [role_id])
        r = self.pg.query_df("SELECT resource_id FROM sys_role_resource WHERE role_id = %s", [role_id])
        return {
            "menu_ids": m["menu_id"].tolist() if not m.empty else [],
            "resource_ids": r["resource_id"].tolist() if not r.empty else [],
        }

    def set_grants(self, role_id: str, *, menu_ids: list[str], resource_ids: list[str],
                   conn=None) -> None:
        """替换角色授权（全删后重插，避免残留）。conn 非空则并入调用方事务（与 bump 原子）。存在性调用方先校验。"""
        with self.pg.cursor_in(conn) as cur:
            cur.execute("DELETE FROM sys_role_menu WHERE role_id = %s", [role_id])
            cur.execute("DELETE FROM sys_role_resource WHERE role_id = %s", [role_id])
            for mid in dict.fromkeys(menu_ids):
                cur.execute(
                    "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s)", [role_id, mid])
            for rid in dict.fromkeys(resource_ids):
                cur.execute(
                    "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s)",
                    [role_id, rid])

    def existing_menu_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        df = self.pg.query_df("SELECT id FROM sys_menu WHERE id = ANY(%s)", [list(set(ids))])
        return set(df["id"].tolist()) if not df.empty else set()

    def existing_resource_ids(self, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        df = self.pg.query_df("SELECT id FROM sys_resource WHERE id = ANY(%s)", [list(set(ids))])
        return set(df["id"].tolist()) if not df.empty else set()

    def system_only_resource_ids(self) -> set[str]:
        """返回不可授予非 system 角色的功能码 id。

        系统菜单资源由可见性推导；普通业务页上的管理员操作由显式 system-only 码补充。
        这些接口均由 require_system_perm 硬守卫，禁止误授造成“已授权但不可用”的误导。
        """
        df = self.pg.query_df(
            "SELECT r.id FROM sys_resource r JOIN sys_menu m ON m.id = r.menu_id "
            "WHERE m.visible = 'system' OR r.code = ANY(%s)",
            [list(EXPLICIT_SYSTEM_ONLY_RESOURCE_CODES)],
        )
        return set(df["id"].tolist()) if not df.empty else set()
