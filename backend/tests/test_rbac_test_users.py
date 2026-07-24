from __future__ import annotations

import uuid
from datetime import datetime

from backend.auth.constants import ROLE_NORMAL, ROLE_PAID
from backend.devtools.rbac_test_users import (
    UserSpec,
    _bump_user_permissions,
    _ensure_users,
)


def test_ensure_users_reactivates_soft_deleted_account_in_postgres(pg) -> None:
    suffix = uuid.uuid4().hex
    tenant_id = f"tt_seed_{suffix}"
    user_id = f"uu_seed_{suffix}"
    account = f"seed_restore_{suffix}"
    user = UserSpec(
        id=user_id,
        account=account,
        tenant_id=tenant_id,
        role_code=ROLE_NORMAL,
        role_ids=(ROLE_NORMAL,),
        purpose="真实 PG 软删除恢复回归。",
    )

    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')",
        [tenant_id, tenant_id],
    )
    try:
        pg.execute(
            "INSERT INTO sys_user "
            "(id,tenant_id,account,password_hash,role_code,perm_ver,status,deleted_at) "
            "VALUES (%s,%s,%s,%s,%s,7,'disabled',%s)",
            [user_id, tenant_id, account, "old-hash", ROLE_PAID, datetime.now()],
        )
        pg.execute(
            "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
            [user_id, ROLE_PAID],
        )

        with pg.transaction() as conn, conn.cursor() as cur:
            _ensure_users(
                cur,
                password_hash="new-hash",
                reset_password=True,
                users=(user,),
            )
            _bump_user_permissions(cur, (user,))

        restored = pg.query_df(
            "SELECT tenant_id,account,password_hash,role_code,perm_ver,status,deleted_at "
            "FROM sys_user WHERE id=%s",
            [user_id],
        ).iloc[0]
        roles = pg.query_df(
            "SELECT role_id FROM sys_user_role WHERE user_id=%s ORDER BY role_id",
            [user_id],
        )["role_id"].tolist()

        assert restored["tenant_id"] == tenant_id
        assert restored["account"] == account
        assert restored["password_hash"] == "new-hash"
        assert restored["role_code"] == ROLE_NORMAL
        assert int(restored["perm_ver"]) == 8
        assert restored["status"] == "active"
        assert restored["deleted_at"] is None
        assert roles == [ROLE_NORMAL]
    finally:
        pg.execute(
            "DELETE FROM sys_user_role WHERE user_id IN ("
            "SELECT id FROM sys_user WHERE id=%s AND tenant_id=%s AND account=%s)",
            [user_id, tenant_id, account],
        )
        pg.execute(
            "DELETE FROM sys_user WHERE id=%s AND tenant_id=%s AND account=%s",
            [user_id, tenant_id, account],
        )
        pg.execute(
            "DELETE FROM sys_tenant WHERE id=%s AND name=%s",
            [tenant_id, tenant_id],
        )
