"""角色仓库（sys_role + 授权关联，PG，占位符 %s）——多租户 RBAC stage3。

本文件（T5）先落**只读**部分：按 id 取角色、可分配角色集（供用户管理校验/下拉）。
T6 在此扩展角色 CRUD + 菜单/功能授权（role_menu/role_resource）+ 授权 bump。

可分配规则（Codex 三轮评审结论）：
- 调用者是 system：返回**除 system 超管外的全部**可分配角色（内置预设 + 系统管理员自建 custom）；
- 调用者是 tenant_admin：**仅内置预设**可分配角色（tenant_admin/normal/paid），不含 system、不含 custom。
"""

from __future__ import annotations

from backend.auth.constants import ASSIGNABLE_PRESET_ROLES, ROLE_SYSTEM
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.role_repository")

_ROLE_COLS = "id, code, name, kind, is_builtin, is_locked, description"


class RoleRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    @staticmethod
    def _row(r: dict) -> dict:
        return {
            "id": r["id"], "code": r["code"], "name": r["name"], "kind": r["kind"],
            "is_builtin": bool(r["is_builtin"]), "is_locked": bool(r["is_locked"]),
            "description": r.get("description"),
        }

    def get_by_ids(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        df = self.pg.query_df(
            f"SELECT {_ROLE_COLS} FROM sys_role WHERE id = ANY(%s)", [list(dict.fromkeys(ids))])
        return [self._row(r.to_dict()) for _, r in df.iterrows()]

    def assignable(self, *, is_system: bool) -> list[dict]:
        """可分配角色集（按调用者角色分流，见模块 docstring）。system 超管永不出现在结果中。"""
        if is_system:
            # 除 system 超管外全部（含自建 custom）
            df = self.pg.query_df(
                f"SELECT {_ROLE_COLS} FROM sys_role "
                "WHERE code <> %s AND kind <> 'system' ORDER BY is_builtin DESC, kind, name",
                [ROLE_SYSTEM])
        else:
            # 仅内置预设可分配角色（不含 system、不含 custom）
            df = self.pg.query_df(
                f"SELECT {_ROLE_COLS} FROM sys_role "
                "WHERE is_builtin = TRUE AND kind = ANY(%s) ORDER BY kind, name",
                [list(ASSIGNABLE_PRESET_ROLES)])
        return [self._row(r.to_dict()) for _, r in df.iterrows()]
