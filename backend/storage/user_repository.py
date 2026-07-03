"""用户/租户仓库（sys_user / sys_tenant，PG，占位符 %s）——多租户 RBAC stage2·T4。

平台元数据表（自然键，无 owner 归属列）；本阶段承载认证：账号/邮箱查、状态、
perm_ver 自增、注册建租户事务。完整用户/租户管理页留阶段三。
密码哈希由 backend.auth.security 生成，本仓库只存 password_hash 字段，不碰明文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pandas as pd

from backend.auth.constants import ROLE_TENANT_ADMIN
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.user_repository")

_USER_COLS = "id, tenant_id, account, email, password_hash, role_code, perm_ver, status, last_login_at"


class UserRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    def _one(self, where: str, params: list) -> dict | None:
        df = self.pg.query_df(f"SELECT {_USER_COLS} FROM sys_user WHERE {where}", params)
        return df.iloc[0].to_dict() if not df.empty else None

    def get_by_account(self, account: str) -> dict | None:
        return self._one("account=%s", [account])

    def get_by_id(self, user_id: str) -> dict | None:
        return self._one("id=%s", [user_id])

    def get_by_email(self, email: str) -> dict | None:
        return self._one("email=%s", [email])

    def update_last_login(self, user_id: str) -> None:
        self.pg.execute(
            "UPDATE sys_user SET last_login_at=%s WHERE id=%s", [datetime.now(), user_id])

    # 注：perm_ver 自增统一走 perm_resolver.bump_perm_ver(user_ids, conn)——与业务写入同一 PG 事务原子
    # 提交（多租户 RBAC 铁律，Codex 五轮 P1）。此处不再提供独立 autocommit 的自增方法，避免绕开该事务契约。

    def register_tenant_and_admin(
        self, account: str, email: str | None, password_hash: str) -> dict:
        """自助注册（R5）：一个事务内建租户 + 建用户（tenant_admin）+ 回填租户管理员 + 绑角色。

        唯一性由 sys_user(account) 唯一约束 + email 部分唯一索引兜底（并发安全）；
        调用方应先做友好预检（见 auth_service.register）。返回新用户 dict。
        stage3：同事务写 sys_user_role(tenant_admin)，使新注册用户权限解析即生效（不只靠 role_code）。
        """
        tenant_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex
        now = datetime.now()
        with self.pg.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sys_tenant (id, name, status, created_at) "
                    "VALUES (%s, %s, 'active', %s)",
                    [tenant_id, f"{account} 的租户", now])
                cur.execute(
                    "INSERT INTO sys_user "
                    "(id, tenant_id, account, email, password_hash, role_code, status, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)",
                    [user_id, tenant_id, account, email, password_hash, ROLE_TENANT_ADMIN, now])
                cur.execute(
                    "UPDATE sys_tenant SET admin_user_id=%s WHERE id=%s", [user_id, tenant_id])
                # 内置 tenant_admin 角色 id=code；绑关联表使 perm_resolver 解析到租管权限
                cur.execute(
                    "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING", [user_id, ROLE_TENANT_ADMIN])
        log.info("自助注册：新租户 %s + 租户管理员 %s(%s)", tenant_id, user_id, account)
        return self.get_by_id(user_id)  # type: ignore[return-value]

    # ── 用户管理（R10，stage3·T5）：域过滤列表 / 多角色 CRUD / 状态 / 重置密码 ──

    @staticmethod
    def _row_to_admin_view(r: dict) -> dict:
        """管理列表/详情视图（无 password_hash）。roles=角色码集；日期转 iso。"""
        def _iso(v):
            # 混合结果集里 SQL NULL 时间会被 pandas 提升为 NaT（列 dtype=datetime64），
            # 直接 isoformat() 会得到字符串 'NaT' 泄漏到前端；pd.isna 统一兜住 NaT/NA/None → null。
            if v is None or pd.isna(v):
                return None
            return v.isoformat() if hasattr(v, "isoformat") else v
        roles = list(r.get("roles") or [])
        return {
            "id": r["id"], "tenant_id": r["tenant_id"], "account": r["account"],
            "email": r.get("email"), "role_code": r["role_code"], "roles": roles,
            "status": r["status"], "perm_ver": int(r["perm_ver"]),
            "last_login_at": _iso(r.get("last_login_at")), "created_at": _iso(r.get("created_at")),
        }

    def list_users(self, *, tenant_id: str | None = None, role: str | None = None,
                   status: str | None = None, q: str | None = None,
                   page: int = 1, size: int = 20) -> dict:
        """域过滤 + 条件筛选 + 分页。tenant_id=None 表示不限租户（system 全局）。

        返回 {items, total}。role 按角色码 EXISTS 过滤；q 模糊匹配账号/邮箱。
        """
        conds: list[str] = []
        params: list = []
        if tenant_id is not None:
            conds.append("u.tenant_id=%s")
            params.append(tenant_id)
        if status:
            conds.append("u.status=%s")
            params.append(status)
        if role:
            conds.append(
                "EXISTS (SELECT 1 FROM sys_user_role ur2 JOIN sys_role r2 ON r2.id=ur2.role_id "
                "WHERE ur2.user_id=u.id AND r2.code=%s)")
            params.append(role)
        if q:
            conds.append("(u.account ILIKE %s OR u.email ILIKE %s)")
            like = f"%{q}%"
            params += [like, like]
        where = ("WHERE " + " AND ".join(conds)) if conds else ""

        total = int(self.pg.query_df(
            f"SELECT count(*) n FROM sys_user u {where}", params).iloc[0]["n"])
        page = max(1, page)
        size = max(1, min(size, 200))
        rows = self.pg.query_df(
            f"SELECT u.id, u.tenant_id, u.account, u.email, u.role_code, u.status, u.perm_ver, "
            f"u.last_login_at, u.created_at, "
            f"COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{{}}') AS roles "
            f"FROM sys_user u "
            f"LEFT JOIN sys_user_role ur ON ur.user_id=u.id "
            f"LEFT JOIN sys_role r ON r.id=ur.role_id {where} "
            f"GROUP BY u.id ORDER BY u.created_at DESC NULLS LAST LIMIT %s OFFSET %s",
            params + [size, (page - 1) * size])
        items = [self._row_to_admin_view(r.to_dict()) for _, r in rows.iterrows()]
        return {"items": items, "total": total}

    def get_admin_view(self, user_id: str) -> dict | None:
        """单用户管理视图（含角色码集）。"""
        df = self.pg.query_df(
            "SELECT u.id, u.tenant_id, u.account, u.email, u.role_code, u.status, u.perm_ver, "
            "u.last_login_at, u.created_at, "
            "COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') AS roles "
            "FROM sys_user u LEFT JOIN sys_user_role ur ON ur.user_id=u.id "
            "LEFT JOIN sys_role r ON r.id=ur.role_id WHERE u.id=%s GROUP BY u.id", [user_id])
        return self._row_to_admin_view(df.iloc[0].to_dict()) if not df.empty else None

    def create_user(self, *, account: str, email: str | None, password_hash: str,
                    tenant_id: str, role_ids: list[str], role_code: str,
                    status: str = "active") -> str:
        """建用户 + 绑多角色（单事务）。唯一性由 DB 约束兜底。返回 user_id。"""
        user_id = uuid.uuid4().hex
        now = datetime.now()
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sys_user "
                "(id, tenant_id, account, email, password_hash, role_code, status, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [user_id, tenant_id, account, email, password_hash, role_code, status, now])
            for rid in dict.fromkeys(role_ids):
                cur.execute(
                    "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s)", [user_id, rid])
        return user_id

    def update_user(self, user_id: str, *, email: str | None, status: str,
                    role_ids: list[str], role_code: str, conn=None) -> None:
        """更新用户资料 + 重建角色关联（全删后重插，避免残留）。conn 非空则并入调用方事务（与 bump 原子）。"""
        now = datetime.now()
        with self.pg.cursor_in(conn) as cur:
            cur.execute(
                "UPDATE sys_user SET email=%s, status=%s, role_code=%s, updated_at=%s WHERE id=%s",
                [email, status, role_code, now, user_id])
            cur.execute("DELETE FROM sys_user_role WHERE user_id=%s", [user_id])
            for rid in dict.fromkeys(role_ids):
                cur.execute(
                    "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s)", [user_id, rid])

    def set_status(self, user_id: str, status: str, *, conn=None) -> None:
        with self.pg.cursor_in(conn) as cur:
            cur.execute("UPDATE sys_user SET status=%s, updated_at=%s WHERE id=%s",
                        [status, datetime.now(), user_id])

    def reset_password(self, user_id: str, password_hash: str, *, conn=None) -> None:
        with self.pg.cursor_in(conn) as cur:
            cur.execute("UPDATE sys_user SET password_hash=%s, updated_at=%s WHERE id=%s",
                        [password_hash, datetime.now(), user_id])

    def delete_user(self, user_id: str, *, conn=None) -> None:
        """删用户（sys_user_role 经 FK CASCADE 自动清）。conn 非空则并入调用方事务。"""
        with self.pg.cursor_in(conn) as cur:
            cur.execute("DELETE FROM sys_user WHERE id=%s", [user_id])

    def count_tenant_admins(self, tenant_id: str, *, exclude_user_id: str | None = None,
                            active_only: bool = False) -> int:
        """统计租户内拥有 tenant_admin 角色的用户数（用于"最后一个管理员"保护）。"""
        conds = ["u.tenant_id=%s", "r.code=%s"]
        params: list = [tenant_id, ROLE_TENANT_ADMIN]
        if exclude_user_id:
            conds.append("u.id<>%s")
            params.append(exclude_user_id)
        if active_only:
            conds.append("u.status='active'")
        df = self.pg.query_df(
            "SELECT count(DISTINCT u.id) n FROM sys_user u "
            "JOIN sys_user_role ur ON ur.user_id=u.id JOIN sys_role r ON r.id=ur.role_id "
            f"WHERE {' AND '.join(conds)}", params)
        return int(df.iloc[0]["n"])
