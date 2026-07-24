"""Playwright 临时用户夹具。

只允许在本地/测试环境创建唯一临时用户。清理时按租户与用户双重归属删除该用户产生的
全部私有资产，再物理删除用户；不读取或改写固定 debug_* 账号的历史偏好。
"""

from __future__ import annotations

import argparse
import json
import uuid

from backend.auth.constants import ROLE_NORMAL, ROLE_PAID
from backend.auth.perm_resolver import clear_perms_cache
from backend.auth.security import hash_password
from backend.devtools.rbac_test_users import (
    DEBUG_TENANT_ID,
    UserSpec,
    _bump_user_permissions,
    _ensure_users,
    _guard_not_production,
    resolve_debug_password,
)
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_ddl import _ASSET_TABLES

_ALLOWED_ROLES = {ROLE_NORMAL, ROLE_PAID}


def create_temporary_user(
    role_code: str,
    *,
    pg: PostgresClient | None = None,
) -> dict[str, str]:
    """创建单个唯一临时用户，复用真实调试密码与角色校准链路。"""
    _guard_not_production()
    if role_code not in _ALLOWED_ROLES:
        raise ValueError(f"不支持的临时用户角色：{role_code}")

    pg = pg or get_pg_client()
    tenant = pg.query_df(
        "SELECT id FROM sys_tenant "
        "WHERE id=%s AND status='active' AND deleted_at IS NULL",
        [DEBUG_TENANT_ID],
    )
    role = pg.query_df(
        "SELECT id FROM sys_role WHERE id=%s",
        [role_code],
    )
    if tenant.empty or role.empty:
        raise RuntimeError("调试租户或内置角色未就绪；先执行 python -m backend.cli dev-users")

    suffix = uuid.uuid4().hex
    user = UserSpec(
        id=f"e2e_{suffix}",
        account=f"e2e_{role_code}_{suffix}",
        tenant_id=DEBUG_TENANT_ID,
        role_code=role_code,
        role_ids=(role_code,),
        purpose="Playwright 单次运行临时用户。",
    )
    password, _source = resolve_debug_password()
    with pg.transaction() as conn, conn.cursor() as cur:
        _ensure_users(
            cur,
            password_hash=hash_password(password),
            reset_password=True,
            users=(user,),
        )
        _bump_user_permissions(cur, (user,))
    clear_perms_cache([user.id])
    return {
        "userId": user.id,
        "account": user.account,
        "tenantId": user.tenant_id,
        "role": user.role_code,
    }


def destroy_temporary_user(
    *,
    user_id: str,
    tenant_id: str,
    account: str,
    pg: PostgresClient | None = None,
) -> dict[str, int | str]:
    """精确清除一个临时用户及其私有资产；固定账号或跨租户参数均不会被命中。"""
    _guard_not_production()
    if not user_id.startswith("e2e_") or not account.startswith("e2e_"):
        raise ValueError("拒绝清理非 E2E 临时用户")

    pg = pg or get_pg_client()
    asset_rows = 0
    with pg.transaction() as conn, conn.cursor() as cur:
        for table in reversed(tuple(_ASSET_TABLES)):
            if table == "layout_user_config":
                cur.execute(
                    "DELETE FROM layout_user_config "
                    "WHERE tenant_id=%s AND owner_user_id=%s AND user_id=%s",
                    [tenant_id, user_id, user_id],
                )
            else:
                cur.execute(
                    f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s",
                    [tenant_id, user_id],
                )
            asset_rows += max(cur.rowcount, 0)

        cur.execute(
            "DELETE FROM audit_log WHERE tenant_id=%s AND actor_user_id=%s",
            [tenant_id, user_id],
        )
        audit_rows = max(cur.rowcount, 0)
        cur.execute(
            "DELETE FROM sys_user_role ur USING sys_user u "
            "WHERE ur.user_id=u.id AND u.id=%s AND u.tenant_id=%s AND u.account=%s",
            [user_id, tenant_id, account],
        )
        role_rows = max(cur.rowcount, 0)
        cur.execute(
            "DELETE FROM sys_user WHERE id=%s AND tenant_id=%s AND account=%s",
            [user_id, tenant_id, account],
        )
        user_rows = max(cur.rowcount, 0)

    clear_perms_cache([user_id])
    if user_rows != 1:
        raise RuntimeError(f"临时用户精确清理异常：期望 1 行，实际 {user_rows} 行")
    return {
        "userId": user_id,
        "assetRows": asset_rows,
        "auditRows": audit_rows,
        "roleRows": role_rows,
        "userRows": user_rows,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Playwright 临时用户夹具")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--role", required=True, choices=sorted(_ALLOWED_ROLES))
    destroy = sub.add_parser("destroy")
    destroy.add_argument("--user-id", required=True)
    destroy.add_argument("--tenant-id", required=True)
    destroy.add_argument("--account", required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "create":
        result = create_temporary_user(args.role)
    else:
        result = destroy_temporary_user(
            user_id=args.user_id,
            tenant_id=args.tenant_id,
            account=args.account,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
