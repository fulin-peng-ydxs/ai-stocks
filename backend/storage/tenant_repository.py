"""租户仓库（sys_tenant，PG，占位符 %s）——多租户 RBAC stage3·T9（R14）。

租户为平台级实体（自身无 tenant_id 归属），承载多租户隔离的顶层单元。status=active|disabled；
admin_user_id 指定该租户管理员（须属本租户）。列表附 user_count / admin_account 供管理页展示。
停用踢下线（bump_users_of_tenant）由 service 编排。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from backend.common.ids import prefixed_readable_id
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.tenant_repository")

_TENANT_COLS = "id, name, status, admin_user_id, created_at, deleted_at"
_TENANT_SORT_COLS = {
    "created": "t.created_at",
    "name": "lower(t.name)",
    "userCount": "user_count",
}


class TenantRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    @staticmethod
    def _row(r: dict) -> dict:
        return {
            "id": r["id"], "name": r["name"], "status": r["status"],
            "admin_user_id": r.get("admin_user_id"),
            "created_at": str(r["created_at"]) if r.get("created_at") is not None else None,
            "deleted_at": str(r["deleted_at"]) if r.get("deleted_at") is not None else None,
        }

    def list_all(self, *, q: str | None, status: str | None, page: int, size: int,
                 sort_by: str = "created", sort_order: str = "desc") -> dict:
        """租户分页列表（附用户数 + 管理员账号）。返回 {items, total}。"""
        conds: list[str] = ["t.deleted_at IS NULL"]  # 逻辑删除:列表不含已删
        params: list = []
        if status:
            conds.append("t.status = %s")
            params.append(status)
        if q:
            conds.append("(t.id ILIKE %s OR t.name ILIKE %s)")
            like = f"%{q}%"
            params += [like, like]
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        total = int(self.pg.query_df(
            f"SELECT count(*) n FROM sys_tenant t {where}", params).iloc[0]["n"])
        page = max(1, page)
        size = max(1, min(size, 200))
        sort_col = _TENANT_SORT_COLS.get(sort_by, "t.created_at")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        rows = self.pg.query_df(
            f"SELECT t.id, t.name, t.status, t.admin_user_id, t.created_at, "
            "(SELECT count(*) FROM sys_user u WHERE u.tenant_id = t.id AND u.deleted_at IS NULL) AS user_count, "
            "(SELECT account FROM sys_user a WHERE a.id = t.admin_user_id) AS admin_account "
            f"FROM sys_tenant t {where} "
            f"ORDER BY {sort_col} {direction} NULLS LAST, t.created_at DESC NULLS LAST, t.id "
            "LIMIT %s OFFSET %s",
            params + [size, (page - 1) * size])
        items = []
        for _, r in rows.iterrows():
            row = self._row(r.to_dict())
            row["user_count"] = int(r["user_count"])
            row["admin_account"] = r["admin_account"] if r["admin_account"] is not None else None
            items.append(row)
        return {"items": items, "total": total}

    def get(self, tenant_id: str) -> dict | None:
        df = self.pg.query_df(f"SELECT {_TENANT_COLS} FROM sys_tenant WHERE id = %s", [tenant_id])
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def get_by_name(self, name: str) -> dict | None:
        df = self.pg.query_df(f"SELECT {_TENANT_COLS} FROM sys_tenant WHERE name = %s", [name])
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def exists(self, tenant_id: str) -> bool:
        df = self.pg.query_df("SELECT 1 FROM sys_tenant WHERE id = %s", [tenant_id])
        return not df.empty

    def user_count(self, tenant_id: str) -> int:
        # 逻辑删除:已软删用户不计数,否则会挡住租户删除
        df = self.pg.query_df(
            "SELECT count(*) AS n FROM sys_user WHERE tenant_id = %s AND deleted_at IS NULL",
            [tenant_id])
        return int(df.iloc[0]["n"])

    def create(self, *, name: str, status: str) -> str:
        base = prefixed_readable_id(name, prefix="tenant_")
        tenant_id = base
        seq = 2
        while self.exists(tenant_id):
            tenant_id = f"{base}_{seq}"
            seq += 1
        if len(tenant_id) > 80:
            tenant_id = "tenant_" + uuid.uuid4().hex[:12]
        self.pg.execute(
            "INSERT INTO sys_tenant (id, name, status, created_at) VALUES (%s, %s, %s, %s)",
            [tenant_id, name, status, datetime.now()])
        return tenant_id

    def update(self, tenant_id: str, *, name: str, admin_user_id: str | None) -> None:
        self.pg.execute(
            "UPDATE sys_tenant SET name=%s, admin_user_id=%s, updated_at=%s WHERE id=%s",
            [name, admin_user_id, datetime.now(), tenant_id])

    def set_status(self, tenant_id: str, status: str, *, conn=None) -> None:
        """启停租户。conn 非空则并入调用方事务（停用与该租户成员 perm_ver 自增原子提交）。"""
        with self.pg.cursor_in(conn) as cur:
            cur.execute("UPDATE sys_tenant SET status=%s, updated_at=%s WHERE id=%s",
                        [status, datetime.now(), tenant_id])

    def delete(self, tenant_id: str, *, conn=None) -> None:
        """逻辑删除:打 deleted_at 标记（软删后不恢复,数据保留供审计）。"""
        now = datetime.now()
        with self.pg.cursor_in(conn) as cur:
            cur.execute("UPDATE sys_tenant SET deleted_at=%s, updated_at=%s WHERE id=%s",
                        [now, now, tenant_id])
