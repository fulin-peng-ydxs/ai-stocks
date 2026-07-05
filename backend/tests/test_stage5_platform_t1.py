"""阶段五 T1：平台能力 DDL、菜单/资源码 seed、baseline 与既有库授权回填。"""

from __future__ import annotations

import uuid

from backend.auth.constants import (
    ROLE_NORMAL,
    ROLE_SYSTEM,
    ROLE_TENANT_ADMIN,
    SHARED_RESOURCE_CODES,
)
from backend.auth.perm_resolver import resolve
from backend.storage.pg_ddl import (
    _SEED_DICT_ITEMS,
    _SEED_DICT_TYPES,
    _STAGE5_PLATFORM_CAPABILITIES_MARKER,
    seed_stage5_platform_capabilities,
)
from backend.storage.resource_repository import ResourceRepository


def test_stage5_tables_indexes_and_defaults_seeded(pg, app_cfg):
    tables = pg.query_df(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name = ANY(%s)",
        [["audit_log", "dict_type", "dict_item"]],
    )
    assert set(tables["table_name"]) == {"audit_log", "dict_type", "dict_item"}

    indexes = set(pg.query_df(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
        "AND indexname = ANY(%s)",
        [[
            "idx_audit_log_event_time",
            "idx_audit_log_tenant_time",
            "idx_audit_log_category_time",
            "idx_audit_log_type_time",
            "idx_audit_log_resource_time",
            "idx_audit_log_result_time",
            "idx_dict_type_enabled_sort",
            "idx_dict_item_type_enabled_sort",
        ]],
    )["indexname"])
    assert indexes == {
        "idx_audit_log_event_time",
        "idx_audit_log_tenant_time",
        "idx_audit_log_category_time",
        "idx_audit_log_type_time",
        "idx_audit_log_resource_time",
        "idx_audit_log_result_time",
        "idx_dict_type_enabled_sort",
        "idx_dict_item_type_enabled_sort",
    }

    config_keys = [
        "auth.require_email_code",
        "auth.login_captcha_enabled",
        "auth.captcha_after_fails",
        "audit.retention_days",
    ]
    pg.execute("DELETE FROM app_config WHERE key = ANY(%s)", [config_keys])
    seed_stage5_platform_capabilities(pg)
    cfg = dict(pg.query_df(
        "SELECT key, value FROM app_config WHERE key = ANY(%s)",
        [config_keys],
    ).itertuples(index=False, name=None))
    assert cfg["auth.require_email_code"] == "true"
    assert cfg["auth.login_captcha_enabled"] == "false"
    assert cfg["auth.captcha_after_fails"] == "3"
    assert cfg["audit.retention_days"] == "90"

    dict_types = set(pg.query_df("SELECT code FROM dict_type")["code"])
    assert {t[0] for t in _SEED_DICT_TYPES} <= dict_types
    items = set(pg.query_df("SELECT type_code || ':' || code AS k FROM dict_item")["k"])
    assert {f"{type_code}:{code}" for type_code, code, _label, _sort in _SEED_DICT_ITEMS} <= items

    fk = pg.query_df(
        "SELECT confdeltype FROM pg_constraint "
        "WHERE conname='dict_item_type_code_fkey'",
    )
    assert not fk.empty
    assert fk.iloc[0]["confdeltype"] == "r"


def test_stage5_menu_resource_seed_and_default_grants(pg):
    menus = {
        r["id"]: r
        for _, r in pg.query_df(
            "SELECT id, parent_id, route_path, visible FROM sys_menu "
            "WHERE id = ANY(%s)",
            [["/system/audit", "/system/dicts"]],
        ).iterrows()
    }
    assert menus["/system/audit"]["parent_id"] == "system"
    assert menus["/system/audit"]["route_path"] == "/system/audit"
    assert menus["/system/audit"]["visible"] == "login"
    assert menus["/system/dicts"]["visible"] == "system"

    resources = {
        r["code"]: r
        for _, r in pg.query_df(
            "SELECT r.code, r.menu_id, m.visible FROM sys_resource r "
            "JOIN sys_menu m ON m.id = r.menu_id "
            "WHERE r.code = ANY(%s)",
            [[
                "audit:view",
                "dict:read",
                "dict:view",
                "dict:type-manage",
                "dict:item-manage",
            ]],
        ).iterrows()
    }
    assert resources["audit:view"]["menu_id"] == "/system/audit"
    assert resources["dict:read"]["menu_id"] == "/board"
    assert resources["dict:read"]["visible"] == "login"
    assert resources["dict:view"]["menu_id"] == "/system/dicts"
    assert resources["dict:type-manage"]["visible"] == "system"
    assert resources["dict:item-manage"]["visible"] == "system"

    assert "dict:read" in SHARED_RESOURCE_CODES
    repo_row = {
        r["code"]: r for r in ResourceRepository(pg).list_all()
    }["dict:read"]
    assert repo_row["baseline_locked"] is True

    tenant_admin_menus = set(pg.query_df(
        "SELECT menu_id FROM sys_role_menu WHERE role_id=%s",
        [ROLE_TENANT_ADMIN],
    )["menu_id"])
    tenant_admin_resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_TENANT_ADMIN],
    )["resource_id"])
    assert "/system/audit" in tenant_admin_menus
    assert "audit:view" in tenant_admin_resources
    assert "/system/dicts" not in tenant_admin_menus
    assert not {"dict:view", "dict:type-manage", "dict:item-manage"} & tenant_admin_resources
    assert "dict:read" not in tenant_admin_resources

    for role_id in (ROLE_NORMAL, "paid"):
        menus_for_role = set(pg.query_df(
            "SELECT menu_id FROM sys_role_menu WHERE role_id=%s",
            [role_id],
        )["menu_id"])
        resources_for_role = set(pg.query_df(
            "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
            [role_id],
        )["resource_id"])
        assert "/system/audit" not in menus_for_role
        assert "/system/dicts" not in menus_for_role
        assert not {
            "audit:view",
            "dict:read",
            "dict:view",
            "dict:type-manage",
            "dict:item-manage",
        } & resources_for_role

    system_resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_SYSTEM],
    )["resource_id"])
    assert {
        "audit:view",
        "dict:read",
        "dict:view",
        "dict:type-manage",
        "dict:item-manage",
    } <= system_resources


def test_dict_read_baseline_injected_but_no_role_fail_closed(pg):
    tid = "s5_t_" + uuid.uuid4().hex[:8]
    with_role = "s5_u_" + uuid.uuid4().hex[:8]
    no_role = "s5_u_" + uuid.uuid4().hex[:8]
    try:
        pg.execute(
            "INSERT INTO sys_tenant (id,name,status) VALUES (%s,'stage5','active')",
            [tid],
        )
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,0,'active')",
            [with_role, tid, with_role, ROLE_NORMAL],
        )
        pg.execute(
            "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
            [with_role, ROLE_NORMAL],
        )
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,0,'active')",
            [no_role, tid, no_role, ROLE_NORMAL],
        )

        assert "dict:read" in set(resolve(with_role, pg)["resources"])
        no_role_perms = resolve(no_role, pg)
        assert no_role_perms["menus"] == []
        assert no_role_perms["resources"] == []
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=ANY(%s)", [[with_role, no_role]])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def test_stage5_backfill_marker_bumps_once_and_restores_tenant_admin_audit(pg):
    tid = "s5bf_t_" + uuid.uuid4().hex[:8]
    normal_uid = "s5bf_n_" + uuid.uuid4().hex[:8]
    tenant_uid = "s5bf_ta_" + uuid.uuid4().hex[:8]
    admin_before = int(pg.query_df(
        "SELECT perm_ver FROM sys_user WHERE id='admin'",
    ).iloc[0]["perm_ver"])
    try:
        pg.execute("DELETE FROM app_config WHERE key=%s", [_STAGE5_PLATFORM_CAPABILITIES_MARKER])
        pg.execute(
            "DELETE FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
            [ROLE_TENANT_ADMIN, "/system/audit"],
        )
        pg.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
            [ROLE_TENANT_ADMIN, "audit:view"],
        )
        pg.execute(
            "INSERT INTO sys_tenant (id,name,status) VALUES (%s,'stage5-bf','active')",
            [tid],
        )
        for uid, role in ((normal_uid, ROLE_NORMAL), (tenant_uid, ROLE_TENANT_ADMIN)):
            pg.execute(
                "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
                "VALUES (%s,%s,%s,%s,0,'active')",
                [uid, tid, uid, role],
            )
            pg.execute(
                "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
                [uid, role],
            )

        seed_stage5_platform_capabilities(pg)

        assert int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s",
            [normal_uid],
        ).iloc[0]["perm_ver"]) == 1
        assert int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s",
            [tenant_uid],
        ).iloc[0]["perm_ver"]) == 1
        assert int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id='admin'",
        ).iloc[0]["perm_ver"]) == admin_before
        assert not pg.query_df(
            "SELECT 1 FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
            [ROLE_TENANT_ADMIN, "/system/audit"],
        ).empty
        assert not pg.query_df(
            "SELECT 1 FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
            [ROLE_TENANT_ADMIN, "audit:view"],
        ).empty

        seed_stage5_platform_capabilities(pg)
        assert int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s",
            [normal_uid],
        ).iloc[0]["perm_ver"]) == 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=ANY(%s)", [[normal_uid, tenant_uid]])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])
