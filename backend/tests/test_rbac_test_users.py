from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime
from threading import Event, Thread

import pytest

from backend.auth.constants import ROLE_NORMAL, ROLE_PAID
from backend.common.exceptions import StorageError
from backend.devtools.e2e_test_users import _lock_temporary_user, destroy_temporary_user
from backend.devtools.rbac_test_users import (
    UserSpec,
    _bump_user_permissions,
    _ensure_users,
)
from backend.storage.pg_identity import pg_fingerprint


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


def test_destroy_temporary_user_rolls_back_assets_for_wrong_identity(pg, monkeypatch) -> None:
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    suffix = uuid.uuid4().hex
    tenant_id = f"tt_e2e_{suffix}"
    user_id = f"e2e_{suffix}"
    account = f"e2e_normal_{suffix}"
    expected_fingerprint = pg_fingerprint(pg)

    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')",
        [tenant_id, tenant_id],
    )
    try:
        pg.execute(
            "INSERT INTO sys_user "
            "(id,tenant_id,account,password_hash,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,%s,0,'active')",
            [user_id, tenant_id, account, "test-hash", ROLE_NORMAL],
        )
        pg.execute(
            "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
            [user_id, ROLE_NORMAL],
        )
        pg.execute(
            "INSERT INTO user_preference "
            "(tenant_id,owner_user_id,scope,page_key,pref_key,value,schema_version) "
            "VALUES (%s,%s,'page','stock-detail','settings','{}',1)",
            [tenant_id, user_id],
        )

        with pytest.raises(RuntimeError, match="PostgreSQL 与被测后端不一致"):
            destroy_temporary_user(
                user_id=user_id,
                tenant_id=tenant_id,
                account=account,
                expected_pg_fingerprint="0" * 64,
                pg=pg,
            )

        for wrong_tenant, wrong_account in (
            (tenant_id, f"e2e_wrong_{suffix}"),
            (f"tt_wrong_{suffix}", account),
        ):
            with pytest.raises(StorageError, match="精确身份校验失败"):
                destroy_temporary_user(
                    user_id=user_id,
                    tenant_id=wrong_tenant,
                    account=wrong_account,
                    expected_pg_fingerprint=expected_fingerprint,
                    pg=pg,
                )
            assert int(pg.query_df(
                "SELECT count(*) AS n FROM sys_user "
                "WHERE id=%s AND tenant_id=%s AND account=%s",
                [user_id, tenant_id, account],
            ).iloc[0]["n"]) == 1
            assert int(pg.query_df(
                "SELECT count(*) AS n FROM user_preference "
                "WHERE tenant_id=%s AND owner_user_id=%s "
                "AND scope='page' AND page_key='stock-detail' AND pref_key='settings'",
                [tenant_id, user_id],
            ).iloc[0]["n"]) == 1

        concurrent_account = f"e2e_concurrent_{suffix}"
        update_started = Event()
        update_finished = Event()
        update_errors: list[Exception] = []

        def update_account() -> None:
            update_started.set()
            try:
                pg.execute(
                    "UPDATE sys_user SET account=%s "
                    "WHERE id=%s AND tenant_id=%s AND account=%s",
                    [concurrent_account, user_id, tenant_id, account],
                )
            except Exception as error:  # noqa: BLE001
                update_errors.append(error)
            finally:
                update_finished.set()

        with pg.transaction() as conn, conn.cursor() as cur:
            _lock_temporary_user(
                cur,
                user_id=user_id,
                tenant_id=tenant_id,
                account=account,
            )
            updater = Thread(target=update_account)
            updater.start()
            assert update_started.wait(timeout=1)
            assert not update_finished.wait(timeout=0.2)
        assert update_finished.wait(timeout=2)
        updater.join(timeout=1)
        assert update_errors == []
        assert int(pg.query_df(
            "SELECT count(*) AS n FROM sys_user "
            "WHERE id=%s AND tenant_id=%s AND account=%s",
            [user_id, tenant_id, concurrent_account],
        ).iloc[0]["n"]) == 1
        pg.execute(
            "UPDATE sys_user SET account=%s "
            "WHERE id=%s AND tenant_id=%s AND account=%s",
            [account, user_id, tenant_id, concurrent_account],
        )

        class _DeleteMissCursor:
            def __init__(self, cursor) -> None:
                self._cursor = cursor

            def execute(self, sql, params=None):
                if sql.startswith("DELETE FROM sys_user WHERE id="):
                    return self._cursor.execute("SELECT 1 WHERE FALSE")
                return self._cursor.execute(sql, params)

            def fetchone(self):
                return self._cursor.fetchone()

            @property
            def rowcount(self):
                return self._cursor.rowcount

        class _DeleteMissConnection:
            def __init__(self, connection) -> None:
                self._connection = connection

            @contextmanager
            def cursor(self):
                with self._connection.cursor() as cursor:
                    yield _DeleteMissCursor(cursor)

        class _DeleteMissClient:
            def query_df(self, sql, params=None):
                return pg.query_df(sql, params)

            @contextmanager
            def transaction(self):
                with pg.transaction() as connection:
                    yield _DeleteMissConnection(connection)

        with pytest.raises(StorageError, match="期望 1 行，实际 0 行，已回滚"):
            destroy_temporary_user(
                user_id=user_id,
                tenant_id=tenant_id,
                account=account,
                expected_pg_fingerprint=expected_fingerprint,
                pg=_DeleteMissClient(),
            )
        assert int(pg.query_df(
            "SELECT count(*) AS n FROM user_preference "
            "WHERE tenant_id=%s AND owner_user_id=%s "
            "AND scope='page' AND page_key='stock-detail' AND pref_key='settings'",
            [tenant_id, user_id],
        ).iloc[0]["n"]) == 1

        result = destroy_temporary_user(
            user_id=user_id,
            tenant_id=tenant_id,
            account=account,
            expected_pg_fingerprint=expected_fingerprint,
            pg=pg,
        )
        assert result["userRows"] == 1
        assert result["assetRows"] == 1
    finally:
        pg.execute(
            "DELETE FROM user_preference WHERE tenant_id=%s AND owner_user_id=%s "
            "AND scope='page' AND page_key='stock-detail' AND pref_key='settings'",
            [tenant_id, user_id],
        )
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
