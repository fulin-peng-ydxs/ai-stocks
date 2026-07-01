"""用户/租户仓库（sys_user / sys_tenant，PG，占位符 %s）——多租户 RBAC stage2·T4。

平台元数据表（自然键，无 owner 归属列）；本阶段承载认证：账号/邮箱查、状态、
perm_ver 自增、注册建租户事务。完整用户/租户管理页留阶段三。
密码哈希由 backend.auth.security 生成，本仓库只存 password_hash 字段，不碰明文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

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

    def bump_perm_ver(self, user_id: str) -> int:
        """权限/状态变更后自增 perm_ver 并返回新值（旧 token 随即失效）。"""
        df = self.pg.query_df(
            "UPDATE sys_user SET perm_ver=perm_ver+1, updated_at=%s WHERE id=%s RETURNING perm_ver",
            [datetime.now(), user_id])
        return int(df.iloc[0]["perm_ver"]) if not df.empty else 0

    def register_tenant_and_admin(
        self, account: str, email: str | None, password_hash: str) -> dict:
        """自助注册（R5）：一个事务内建租户 + 建用户（tenant_admin）+ 回填租户管理员。

        唯一性由 sys_user(account) 唯一约束 + email 部分唯一索引兜底（并发安全）；
        调用方应先做友好预检（见 auth_service.register）。返回新用户 dict。
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
        log.info("自助注册：新租户 %s + 租户管理员 %s(%s)", tenant_id, user_id, account)
        return self.get_by_id(user_id)  # type: ignore[return-value]
