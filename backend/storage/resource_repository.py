"""功能点/资源仓库（sys_resource，PG，占位符 %s）——多租户 RBAC stage3·T8（R13）。

功能点是平台级全局表（无 tenant_id），归属某菜单（menu_id FK RESTRICT）：
- code 为精确权限码（如 user:list），全局唯一、不可复用；内置码建后不可改（与端点 require_perm 硬绑）。
- type=button（按钮级）/ api（接口级）；api_method/api_path 记录绑定接口（元数据，供审计/展示）。
删除/改码 bump 由 service 编排（改码影响角色授出的有效权限码）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.resource_repository")

_RES_COLS = "id, menu_id, code, name, type, api_method, api_path, sort, is_builtin"


class ResourceRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    @staticmethod
    def _row(r: dict) -> dict:
        return {
            "id": r["id"], "menu_id": r["menu_id"], "code": r["code"], "name": r["name"],
            "type": r["type"], "api_method": r.get("api_method"), "api_path": r.get("api_path"),
            "sort": int(r["sort"]), "is_builtin": bool(r["is_builtin"]),
        }

    def list_all(self, menu_id: str | None = None) -> list[dict]:
        """全部功能点（可按 menu_id 过滤），附引用该功能的角色数（供前端展示删除影响）。"""
        sql = (f"SELECT {_RES_COLS}, "
               "(SELECT count(*) FROM sys_role_resource rr WHERE rr.resource_id = sys_resource.id) "
               "AS role_count FROM sys_resource")
        params: list = []
        if menu_id:
            sql += " WHERE menu_id = %s"
            params.append(menu_id)
        sql += " ORDER BY menu_id, sort, code"
        df = self.pg.query_df(sql, params)
        out: list[dict] = []
        for _, r in df.iterrows():
            row = self._row(r.to_dict())
            row["role_count"] = int(r["role_count"])
            out.append(row)
        return out

    def get(self, resource_id: str) -> dict | None:
        df = self.pg.query_df(f"SELECT {_RES_COLS} FROM sys_resource WHERE id = %s", [resource_id])
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def get_by_code(self, code: str) -> dict | None:
        df = self.pg.query_df(f"SELECT {_RES_COLS} FROM sys_resource WHERE code = %s", [code])
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def reference_count(self, resource_id: str) -> int:
        df = self.pg.query_df(
            "SELECT count(*) AS n FROM sys_role_resource WHERE resource_id = %s", [resource_id])
        return int(df.iloc[0]["n"])

    def _next_sort(self, menu_id: str) -> int:
        df = self.pg.query_df(
            "SELECT COALESCE(max(sort), 0) AS m FROM sys_resource WHERE menu_id = %s", [menu_id])
        return int(df.iloc[0]["m"]) + 10

    def create(self, *, menu_id: str, code: str, name: str, type: str,
               api_method: str | None, api_path: str | None, sort: int | None) -> str:
        resource_id = uuid.uuid4().hex
        self.pg.execute(
            "INSERT INTO sys_resource "
            "(id, menu_id, code, name, type, api_method, api_path, sort, is_builtin, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)",
            [resource_id, menu_id, code, name, type, api_method, api_path,
             sort if sort is not None else self._next_sort(menu_id), datetime.now()])
        return resource_id

    def update(self, resource_id: str, *, menu_id: str, code: str, name: str, type: str,
               api_method: str | None, api_path: str | None) -> None:
        self.pg.execute(
            "UPDATE sys_resource SET menu_id=%s, code=%s, name=%s, type=%s, "
            "api_method=%s, api_path=%s, updated_at=%s WHERE id=%s",
            [menu_id, code, name, type, api_method, api_path, datetime.now(), resource_id])

    def delete(self, resource_id: str) -> None:
        """删功能点（sys_role_resource 经 FK CASCADE 自动清授权）。"""
        self.pg.execute("DELETE FROM sys_resource WHERE id = %s", [resource_id])
