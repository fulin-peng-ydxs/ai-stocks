"""多租户 RBAC 阶段三 · T1：权限数据模型 + seed 验证。

覆盖 §6.1 完成标准：6 表就绪、内置角色/菜单树/功能点 seed、FK 删除策略、默认授权、
存量用户按 role_code 补 sys_user_role、幂等复跑不增行。

统一用真实 PG（pg fixture 已 init_pg_db + seed）；断言针对 seeded 内置数据（按 code/is_builtin
过滤），不依赖绝对总数，兼容后续角色管理页新增的自定义角色/菜单。
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from backend.auth.constants import (
    ASSET_PUBLIC_PUBLISH_RESOURCE_CODES,
    ASSET_TENANT_PUBLISH_RESOURCE_CODES,
    ROLE_NORMAL,
    ROLE_SYSTEM,
    ROLE_TENANT_ADMIN,
)
from backend.storage import pg_ddl
from backend.storage.pg_ddl import (
    _ASSET_PUBLISH_OPEN_LOCK,
    _ASSET_PUBLISH_OPEN_MARKER,
    _PUBLISH_STATE_APPLIED,
    _PUBLISH_STATE_INVALID,
    _PUBLISH_STATE_MISSING,
    _PUBLISH_STATE_ROLLED_BACK,
    _SECTOR_MENU_GRANTS_MARKER,
    _SEED_MENU_TREE,
    _SEED_RESOURCES,
    _STAGE4_BUSINESS_GRANTS_MARKER,
    _STAGE6_ASSET_VISIBILITY_MARKER,
    _USER_RESOURCE_CODES,
    _backfill_asset_publish_open_v1,
    _flatten_menu_tree,
    _publish_policy_state_cur,
    _publish_suppressed,
    _record_config_split_legacy_menu_state,
    _remove_legacy_paid_role,
    _seed_menu_rows,
    _seed_resource_rows,
    _seed_role_grants,
    init_pg_db,
    rollback_asset_publish_open_v1,
    seed_rbac,
    seed_stage6_asset_visibility,
)

RBAC_TABLES = (
    "sys_role", "sys_menu", "sys_resource",
    "sys_user_role", "sys_role_menu", "sys_role_resource",
)


def _count(pg, table: str) -> int:
    return int(pg.query_df(f"SELECT count(*) n FROM {table}").iloc[0]["n"])


def _snapshot_app_config(pg, keys: list[str]) -> list[dict]:
    return pg.query_df(
        "SELECT key, value, updated_at FROM app_config WHERE key = ANY(%s)",
        [keys],
    ).to_dict("records")


def _restore_app_config(pg, keys: list[str], rows: list[dict]) -> None:
    pg.execute("DELETE FROM app_config WHERE key = ANY(%s)", [keys])
    for row in rows:
        pg.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, %s)",
            [row["key"], row["value"], row["updated_at"]],
        )


def _snapshot_role_grants(pg, role_id: str) -> dict[str, list[str]]:
    menus = pg.query_df(
        "SELECT menu_id FROM sys_role_menu WHERE role_id=%s",
        [role_id],
    )["menu_id"].tolist()
    resources = pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [role_id],
    )["resource_id"].tolist()
    return {"menus": menus, "resources": resources}


def _restore_role_grants(pg, role_id: str, snapshot: dict[str, list[str]]) -> None:
    pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s", [role_id])
    pg.execute("DELETE FROM sys_role_resource WHERE role_id=%s", [role_id])
    for menu_id in snapshot["menus"]:
        pg.execute(
            "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s)",
            [role_id, menu_id],
        )
    for resource_id in snapshot["resources"]:
        pg.execute(
            "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s)",
            [role_id, resource_id],
        )


def _snapshot_perm_versions(pg) -> list[dict]:
    return pg.query_df("SELECT id, perm_ver FROM sys_user").to_dict("records")


def _restore_perm_versions(pg, rows: list[dict]) -> None:
    for row in rows:
        pg.execute(
            "UPDATE sys_user SET perm_ver=%s WHERE id=%s",
            [int(row["perm_ver"]), row["id"]],
        )


def test_six_rbac_tables_exist(pg):
    rows = pg.query_df(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name = ANY(%s)",
        [list(RBAC_TABLES)])
    assert set(rows["table_name"]) == set(RBAC_TABLES)


def test_builtin_roles_seeded(pg):
    df = pg.query_df(
        "SELECT code, name, kind, is_builtin, is_locked, tenant_assignable FROM sys_role "
        "WHERE code = ANY(%s)",
        [[ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL]])
    by_code = {r["code"]: r for _, r in df.iterrows()}
    assert set(by_code) == {ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL}
    # 全部内置；仅 system 锁定
    assert all(bool(r["is_builtin"]) for r in by_code.values())
    assert bool(by_code[ROLE_SYSTEM]["is_locked"]) is True
    assert bool(by_code[ROLE_TENANT_ADMIN]["is_locked"]) is False
    assert bool(by_code[ROLE_SYSTEM]["tenant_assignable"]) is False
    assert bool(by_code[ROLE_TENANT_ADMIN]["tenant_assignable"]) is True
    assert bool(by_code[ROLE_NORMAL]["tenant_assignable"]) is True
    # kind 与 code 同名（系统内置）
    for code in (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL):
        assert by_code[code]["kind"] == code


def test_role_assignment_policy_upgrade_preserves_explicit_value(pg):
    """升级只补 NULL，后续启动不可覆盖平台管理员已保存的下放策略。"""
    original = bool(pg.query_df(
        "SELECT tenant_assignable FROM sys_role WHERE id=%s", [ROLE_NORMAL]
    ).iloc[0]["tenant_assignable"])
    try:
        pg.execute(
            "UPDATE sys_role SET tenant_assignable=FALSE WHERE id=%s", [ROLE_NORMAL])
        pg_ddl._upgrade_role_assignment_policy(pg)
        value = pg.query_df(
            "SELECT tenant_assignable FROM sys_role WHERE id=%s", [ROLE_NORMAL]
        ).iloc[0]["tenant_assignable"]
        assert bool(value) is False
    finally:
        pg.execute(
            "UPDATE sys_role SET tenant_assignable=%s WHERE id=%s", [original, ROLE_NORMAL])


def test_legacy_paid_role_is_migrated_to_normal_and_removed(pg):
    legacy_code = "paid"
    tenant_id = "pytest_paid_role_tenant"
    user_id = "pytest_paid_role_user"
    pg.execute(
        "INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active') "
        "ON CONFLICT (id) DO NOTHING",
        [tenant_id, tenant_id],
    )
    try:
        pg.execute(
            "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
            "VALUES (%s,%s,%s,%s,TRUE,FALSE)",
            [legacy_code, legacy_code, "历史角色", legacy_code],
        )
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,4,'active')",
            [user_id, tenant_id, user_id, legacy_code],
        )
        pg.execute(
            "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
            [user_id, legacy_code],
        )
        pg.execute(
            "INSERT INTO dict_item (id,type_code,code,label,sort) "
            "VALUES (%s,'role_type',%s,%s,40)",
            [f"role_type:{legacy_code}", legacy_code, "历史角色"],
        )

        _remove_legacy_paid_role(pg)

        assert pg.query_df(
            "SELECT 1 FROM sys_role WHERE code=%s OR kind=%s",
            [legacy_code, legacy_code],
        ).empty
        assert pg.query_df(
            "SELECT 1 FROM dict_item WHERE type_code='role_type' AND code=%s",
            [legacy_code],
        ).empty
        row = pg.query_df(
            "SELECT role_code,perm_ver FROM sys_user WHERE id=%s",
            [user_id],
        ).iloc[0]
        roles = pg.query_df(
            "SELECT role_id FROM sys_user_role WHERE user_id=%s",
            [user_id],
        )["role_id"].tolist()
        assert row["role_code"] == ROLE_NORMAL
        assert int(row["perm_ver"]) == 5
        assert roles == [ROLE_NORMAL]

        _remove_legacy_paid_role(pg)
        assert int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s",
            [user_id],
        ).iloc[0]["perm_ver"]) == 5
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [user_id])
        pg.execute(
            "DELETE FROM dict_item WHERE type_code='role_type' AND code=%s",
            [legacy_code],
        )
        pg.execute("DELETE FROM sys_role WHERE code=%s", [legacy_code])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tenant_id])


def test_menu_tree_parent_linkage_and_type(pg):
    seeded = _flatten_menu_tree(_SEED_MENU_TREE)
    codes = [m["code"] for m in seeded]
    df = pg.query_df(
        "SELECT id, parent_id FROM sys_menu WHERE code = ANY(%s)",
        [codes])
    assert len(df) == len(seeded)
    for _, m in df.iterrows():
        # sys_menu 是运行期数据库事实源；内置节点可被放到自定义分组下，只校验父节点真实存在。
        if m["parent_id"] is not None:
            parent = pg.query_df("SELECT 1 FROM sys_menu WHERE id=%s", [m["parent_id"]])
            assert not parent.empty


def test_seed_rbac_does_not_overwrite_db_menu_customization(pg):
    menu_id = f"pytest_menu_{uuid4().hex[:10]}"
    try:
        pg.execute(
            "INSERT INTO sys_menu "
            "(id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, NULL, %s, %s, 'group', NULL, NULL, 777, 'system', FALSE)",
            [menu_id, menu_id, "运行期菜单"],
        )
        _seed_menu_rows(pg, [{
            "code": menu_id,
            "parent_code": None,
            "title": "代码默认菜单",
            "type": "leaf",
            "route_path": "/code-default-menu",
            "icon": "Menu",
            "sort": 10,
            "visible": "login",
        }])
        row = pg.query_df(
            "SELECT parent_id,title,type,route_path,icon,sort,visible,is_builtin "
            "FROM sys_menu WHERE id=%s",
            [menu_id],
        ).iloc[0]
        assert row["parent_id"] is None
        assert row["title"] == "运行期菜单"
        assert row["type"] == "group"
        assert row["route_path"] is None
        assert row["icon"] is None
        assert int(row["sort"]) == 777
        assert row["visible"] == "system"
        assert not bool(row["is_builtin"])
    finally:
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [menu_id])


def test_seed_rbac_does_not_overwrite_db_resource_customization(pg):
    suffix = uuid4().hex[:10]
    resource_id = f"pytest_resource_{suffix}"
    menu_id = f"pytest_resource_menu_{suffix}"
    try:
        pg.execute(
            "INSERT INTO sys_menu "
            "(id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, NULL, %s, %s, 'leaf', %s, NULL, 999, 'login', FALSE)",
            [menu_id, menu_id, "测试功能点菜单", "/pytest-resource-parent"],
        )
        pg.execute(
            "INSERT INTO sys_resource "
            "(id,menu_id,code,name,type,api_method,api_path,sort,is_builtin) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE)",
            [
                resource_id, menu_id, resource_id, "运行期功能点", "button", "POST",
                "/api/runtime-resource", 777,
            ],
        )
        _seed_resource_rows(pg, ((
            menu_id, resource_id, "代码默认功能点", "api", "GET", "/api/code-default",
        ),))
        row = pg.query_df(
            "SELECT menu_id,name,type,api_method,api_path,sort,is_builtin "
            "FROM sys_resource WHERE id=%s",
            [resource_id],
        ).iloc[0]
        assert row["menu_id"] == menu_id
        assert row["name"] == "运行期功能点"
        assert row["type"] == "button"
        assert row["api_method"] == "POST"
        assert row["api_path"] == "/api/runtime-resource"
        assert int(row["sort"]) == 777
        assert not bool(row["is_builtin"])
    finally:
        pg.execute("DELETE FROM sys_resource WHERE id=%s", [resource_id])
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [menu_id])


def test_startup_init_preserves_every_existing_menu_and_resource_row(pg):
    menu_sql = (
        "SELECT id,parent_id,code,title,type,route_path,icon,sort,visible,is_builtin "
        "FROM sys_menu ORDER BY id"
    )
    resource_sql = (
        "SELECT id,menu_id,code,name,type,api_method,api_path,sort,is_builtin "
        "FROM sys_resource ORDER BY id"
    )
    before_menus = pg.query_df(menu_sql).to_dict("records")
    before_resources = pg.query_df(resource_sql).to_dict("records")

    init_pg_db(pg)

    assert pg.query_df(menu_sql).to_dict("records") == before_menus
    assert pg.query_df(resource_sql).to_dict("records") == before_resources


def test_config_split_startup_only_records_legacy_menu_without_overwrite(pg, monkeypatch):
    suffix = uuid4().hex[:10]
    legacy_id = f"pytest_legacy_score_{suffix}"
    marker_key = f"pytest.config_split_marker_{suffix}"
    original_config = pg.query_df(
        "SELECT parent_id,title,type,route_path,icon,sort,visible,is_builtin "
        "FROM sys_menu WHERE id=%s",
        ["/system/config"],
    ).iloc[0].to_dict()
    try:
        pg.execute(
            "INSERT INTO sys_menu "
            "(id,parent_id,code,title,type,route_path,icon,sort,visible,is_builtin) "
            "VALUES (%s,NULL,%s,'运行期旧入口','leaf',%s,NULL,888,'login',FALSE)",
            [legacy_id, legacy_id, f"/{legacy_id}"],
        )
        pg.execute(
            "INSERT INTO sys_role_menu (role_id,menu_id) VALUES (%s,%s)",
            ["normal", legacy_id],
        )
        monkeypatch.setattr(pg_ddl, "_LEGACY_SCORE_PROFILES_MENU_ID", legacy_id)
        monkeypatch.setattr(pg_ddl, "_CONFIG_SPLIT_MENU_DISCOVERY_MARKER", marker_key)
        monkeypatch.setattr(
            pg_ddl,
            "_CONFIG_SPLIT_MENU_DISCOVERY_LOCK",
            8600000000 + int(suffix[:6], 16),
        )

        _record_config_split_legacy_menu_state(pg)
        _record_config_split_legacy_menu_state(pg)

        assert not pg.query_df("SELECT 1 FROM sys_menu WHERE id=%s", [legacy_id]).empty
        assert not pg.query_df(
            "SELECT 1 FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
            ["normal", legacy_id],
        ).empty
        config = pg.query_df(
            "SELECT parent_id,title,type,route_path,icon,sort,visible,is_builtin "
            "FROM sys_menu WHERE id=%s",
            ["/system/config"],
        ).iloc[0].to_dict()
        assert config == original_config
        marker = json.loads(pg.query_df(
            "SELECT value FROM app_config WHERE key=%s",
            [marker_key],
        ).iloc[0]["value"])
        assert marker == {
            "version": 1,
            "recorded": True,
            "menu_overwrite": False,
            "legacy_detected_at_recording": True,
        }
    finally:
        pg.execute("DELETE FROM app_config WHERE key=%s", [marker_key])
        pg.execute("DELETE FROM sys_role_menu WHERE menu_id=%s", [legacy_id])
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [legacy_id])


def test_manual_menu_resource_sql_requires_explicit_gate_for_existing_row_overwrite():
    root = Path(__file__).resolve().parents[2]
    sql_paths = tuple((root / "agent-works").rglob("*.sql"))
    for path in sql_paths:
        sql = path.read_text(encoding="utf-8")
        explicit_gate = "AI_STOCKS_MENU_OVERWRITE: EXPLICIT_CONFIRMATION_REQUIRED" in sql
        uncommented = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
        overwrite_found = False
        for statement in uncommented.split(";"):
            normalized = " ".join(statement.split()).lower()
            if not any(table in normalized for table in ("sys_menu", "sys_resource")):
                continue
            overwrite_found = bool(
                overwrite_found
                or re.search(r"\bupdate\s+sys_(?:menu|resource)\b", normalized)
                or re.search(r"\bdelete\s+from\s+sys_(?:menu|resource)\b", normalized)
            )
            if re.search(r"\binsert\s+into\s+sys_(?:menu|resource)\b", normalized):
                overwrite_found = bool(overwrite_found or re.search(
                    r"on\s+conflict\s*\(\s*id\s*\)\s+do\s+update",
                    normalized,
                ))
        if overwrite_found:
            assert explicit_gate, path
            assert "current_setting('ai_stocks.confirm_menu_overwrite', true)" in uncommented, path
            assert "BEGIN;" in sql and "COMMIT;" in sql, path
            assert "app_config" in uncommented, path

    for relative in (
        "agent-works/multi-tenant-rbac/stage4-public-profile-visibility/resource-codes.sql",
        "agent-works/multi-tenant-rbac/stage5-platform-capabilities/resource-codes.sql",
    ):
        sql = (root / relative).read_text(encoding="utf-8")
        assert sql.count("ON CONFLICT (id) DO NOTHING") >= 2
        assert "BEGIN;" in sql and "COMMIT;" in sql


def test_seed_resource_codes_are_unique():
    codes = [r[1] for r in _SEED_RESOURCES]
    assert len(codes) == len(set(codes))


def test_identity_master_data_has_normalized_unique_indexes(pg):
    rows = pg.query_df(
        "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=current_schema() "
        "AND indexname = ANY(%s)",
        [[
            "uq_sys_tenant_name_normalized",
            "uq_sys_role_name_normalized",
            "uq_sys_role_code_normalized",
            "uq_sys_menu_code_normalized",
            "uq_sys_user_account_normalized",
            "uq_sys_user_email_normalized",
        ]],
    )
    assert set(rows["indexname"]) == {
        "uq_sys_tenant_name_normalized",
        "uq_sys_role_name_normalized",
        "uq_sys_role_code_normalized",
        "uq_sys_menu_code_normalized",
        "uq_sys_user_account_normalized",
        "uq_sys_user_email_normalized",
    }
    assert rows["indexdef"].str.contains("lower(btrim", regex=False).all()


def test_resources_seeded_and_bound_to_menu(pg):
    codes = [r[1] for r in _SEED_RESOURCES]
    df = pg.query_df(
        "SELECT r.code, r.menu_id, m.id AS menu_exists "
        "FROM sys_resource r LEFT JOIN sys_menu m ON m.id = r.menu_id "
        "WHERE r.code = ANY(%s)", [codes])
    assert set(df["code"]) == set(codes)
    # 每个功能点都绑定到存在的菜单
    assert df["menu_exists"].notna().all()


def test_system_role_full_grants(pg):
    """system 角色 seed 全量：无任何未授权的 seeded 菜单/功能点。"""
    menu_gap = pg.query_df(
        "SELECT count(*) n FROM sys_menu m "
        "WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu rm "
        "WHERE rm.role_id=%s AND rm.menu_id=m.id)", [ROLE_SYSTEM])
    res_gap = pg.query_df(
        "SELECT count(*) n FROM sys_resource r "
        "WHERE NOT EXISTS (SELECT 1 FROM sys_role_resource rr "
        "WHERE rr.role_id=%s AND rr.resource_id=r.id)", [ROLE_SYSTEM])
    assert int(menu_gap.iloc[0]["n"]) == 0
    assert int(res_gap.iloc[0]["n"]) == 0


def test_tenant_admin_grants_scope(pg):
    """租户管理员：有 用户管理 菜单 + 全部 user:* 功能；无角色/租户管理菜单与功能。"""
    menus = set(pg.query_df(
        "SELECT menu_id FROM sys_role_menu WHERE role_id=%s",
        [ROLE_TENANT_ADMIN])["menu_id"])
    assert "/system/users" in menus
    assert "system" in menus and "permission" in menus  # 上级分组可达
    assert "/system/roles" not in menus
    assert "/system/tenants" not in menus
    assert "/system/audit" not in menus
    assert {"/system/config", "/system/config/score", "/system/config/trade"} <= menus
    assert "/system/config/tech" not in menus and "/system/config/system" not in menus

    resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_TENANT_ADMIN])["resource_id"])
    assert set(_USER_RESOURCE_CODES) <= resources
    assert "audit:view" not in resources
    assert not any(c.startswith(("role:", "tenant:")) for c in resources)


def test_normal_role_business_only(pg):
    menus = set(pg.query_df(
        "SELECT menu_id FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])["menu_id"])
    assert "/screen" in menus and "/backtest" in menus
    assert {"system", "/system/config", "/system/config/score", "/system/config/trade"} <= menus
    assert "/system/users" not in menus
    assert "/system/config/tech" not in menus and "/system/config/system" not in menus
    resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s", [ROLE_NORMAL])["resource_id"])
    assert {
        "score-profile:view",
        "score-profile:save",
        "score-profile:delete",
        "trade-profile:view",
        "trade-profile:save",
        "trade-profile:delete",
        "trade-profile:preview",
    } <= resources
    # asset-ownership-refactor C4/R4：放开普通用户发布——normal 默认获得 8 个 tenant/public 发布码
    assert "score-profile:publish-tenant" in resources
    assert "score-profile:publish-public" in resources
    assert set(ASSET_TENANT_PUBLISH_RESOURCE_CODES) <= resources
    assert set(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) <= resources
    assert not any(c.startswith(("user:", "role:", "tenant:")) for c in resources)


def test_tenant_admin_has_all_publish_by_default(pg):
    # asset-ownership-refactor C4/R4：tenant_admin 默认获得 tenant + public 全部发布码
    resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_TENANT_ADMIN])["resource_id"])
    assert "score-profile:publish-tenant" in resources
    assert "score-profile:publish-public" in resources
    assert set(ASSET_TENANT_PUBLISH_RESOURCE_CODES) <= resources
    assert set(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) <= resources


def test_stage6_asset_visibility_schema_and_resources(pg):
    cols = pg.query_df(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_name = ANY(%s) AND column_name = ANY(%s)",
        [
            ["audit_log", "screen_profile", "trade_profile", "backtest_run"],
            ["changes", "visibility", "published_at", "published_by"],
        ],
    )
    by_table = {
        table: set(group["column_name"])
        for table, group in cols.groupby("table_name")
    }
    assert by_table["audit_log"] >= {"changes"}
    assert by_table["screen_profile"] >= {"visibility", "published_at", "published_by"}
    assert by_table["trade_profile"] >= {"visibility", "published_at", "published_by"}
    assert by_table["backtest_run"] >= {"visibility", "published_at", "published_by"}

    constraints = set(pg.query_df(
        "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
        [[
            "screen_profile_visibility_check",
            "trade_profile_visibility_check",
            "backtest_run_visibility_check",
        ]],
    )["conname"])
    assert {
        "screen_profile_visibility_check",
        "trade_profile_visibility_check",
        "backtest_run_visibility_check",
    } <= constraints

    seeded = set(pg.query_df(
        "SELECT id FROM sys_resource WHERE id = ANY(%s)",
        [list(ASSET_TENANT_PUBLISH_RESOURCE_CODES + ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)],
    )["id"])
    assert set(ASSET_TENANT_PUBLISH_RESOURCE_CODES + ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) <= seeded


def test_stage6_asset_publish_grants_backfilled_for_tenant_admin(pg):
    uid = "stage6_backfill_tenant_admin"
    marker_key = _STAGE6_ASSET_VISIBILITY_MARKER
    marker_snapshot = _snapshot_app_config(pg, [marker_key])
    role_snapshot = _snapshot_role_grants(pg, ROLE_TENANT_ADMIN)
    perm_snapshot = _snapshot_perm_versions(pg)
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute(
        "INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
        "VALUES (%s, 'pytest', %s, %s, 0, 'active')",
        [uid, uid, ROLE_TENANT_ADMIN],
    )
    pg.execute(
        "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        [uid, ROLE_TENANT_ADMIN],
    )
    try:
        pg.execute("DELETE FROM app_config WHERE key=%s", [marker_key])
        pg.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id = ANY(%s)",
            [ROLE_TENANT_ADMIN, list(ASSET_TENANT_PUBLISH_RESOURCE_CODES)],
        )

        seed_stage6_asset_visibility(pg)

        resources = set(pg.query_df(
            "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
            [ROLE_TENANT_ADMIN])["resource_id"])
        perm_ver = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        # C4/R4：seed_stage6 现同时授予 tenant_admin 的 tenant + public 发布码
        assert set(ASSET_TENANT_PUBLISH_RESOURCE_CODES) <= resources
        assert set(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) <= resources
        assert perm_ver == 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_TENANT_ADMIN, role_snapshot)
        _restore_app_config(pg, [marker_key], marker_snapshot)
        _restore_perm_versions(pg, perm_snapshot)


def test_asset_publish_open_backfilled_for_normal(pg):
    """asset-ownership-refactor C4/R4：存量库回填把 8 个发布码授给 normal，并 bump perm_ver。"""
    uid = "asset_publish_open_normal"
    marker_key = _ASSET_PUBLISH_OPEN_MARKER
    marker_snapshot = _snapshot_app_config(pg, [marker_key])
    role_snapshot = _snapshot_role_grants(pg, ROLE_NORMAL)
    perm_snapshot = _snapshot_perm_versions(pg)
    all_publish = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES) + list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute(
        "INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
        "VALUES (%s, 'pytest', %s, %s, 0, 'active')",
        [uid, uid, ROLE_NORMAL],
    )
    pg.execute(
        "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        [uid, ROLE_NORMAL],
    )
    try:
        # 模拟存量库：迁移标记未落地 + normal 尚无任何发布码
        pg.execute("DELETE FROM app_config WHERE key=%s", [marker_key])
        pg.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id = ANY(%s)",
            [ROLE_NORMAL, all_publish],
        )

        _backfill_asset_publish_open_v1(pg)

        resources = set(pg.query_df(
            "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
            [ROLE_NORMAL])["resource_id"])
        perm_ver = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert set(all_publish) <= resources
        assert perm_ver == 1  # 确有新增 → bump 一次

        # marker 只记「已应用」（回滚走确定性基线，不依赖 marker 内容）
        marker_val = json.loads(pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [marker_key]).iloc[0]["value"])
        assert marker_val.get("applied") is True

        # 幂等 + 并发安全：marker 已落地 → 再跑整段 no-op，不重复授权、不再 bump
        _backfill_asset_publish_open_v1(pg)
        perm_ver2 = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert perm_ver2 == 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, role_snapshot)
        _restore_app_config(pg, [marker_key], marker_snapshot)
        _restore_perm_versions(pg, perm_snapshot)


def test_stage4_business_grants_backfilled_for_existing_builtin_roles(pg):
    uid = "stage4_backfill_user"
    marker_key = _STAGE4_BUSINESS_GRANTS_MARKER
    marker_snapshot = _snapshot_app_config(pg, [marker_key])
    role_snapshot = _snapshot_role_grants(pg, ROLE_NORMAL)
    perm_snapshot = _snapshot_perm_versions(pg)
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute(
        "INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
        "VALUES (%s, 'pytest', %s, %s, 0, 'active')",
        [uid, uid, ROLE_NORMAL],
    )
    pg.execute(
        "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        [uid, ROLE_NORMAL],
    )
    try:
        # 模拟旧库：normal 已经有菜单，所以 _seed_role_grants 会跳过；阶段四新增授权缺失。
        pg.execute("DELETE FROM app_config WHERE key=%s", [marker_key])
        pg.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
            [ROLE_NORMAL, "board:view"],
        )
        pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s AND menu_id=%s", [ROLE_NORMAL, "/board"])

        seed_rbac(pg)

        menus = set(pg.query_df(
            "SELECT menu_id FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])["menu_id"])
        resources = set(pg.query_df(
            "SELECT resource_id FROM sys_role_resource WHERE role_id=%s", [ROLE_NORMAL])["resource_id"])
        perm_ver = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert "/board" in menus
        assert "board:view" in resources
        # 发布码不再由 stage4 backfill 管辖（见 _backfill_asset_publish_open_v1），本用例只验证业务码回填
        assert perm_ver == 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, role_snapshot)
        _restore_app_config(pg, [marker_key], marker_snapshot)
        _restore_perm_versions(pg, perm_snapshot)


def test_sector_menu_grants_backfilled_for_normal(pg):
    """存量库 normal 缺 /sectors 菜单（仅资源码 sectors:view）时，迁移补菜单并 bump perm_ver。"""
    uid = "sector_menu_backfill_user"
    marker_key = _SECTOR_MENU_GRANTS_MARKER
    marker_snapshot = _snapshot_app_config(pg, [marker_key])
    role_snapshot = _snapshot_role_grants(pg, ROLE_NORMAL)
    perm_snapshot = _snapshot_perm_versions(pg)
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute(
        "INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
        "VALUES (%s, 'pytest', %s, %s, 0, 'active')",
        [uid, uid, ROLE_NORMAL],
    )
    pg.execute(
        "INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        [uid, ROLE_NORMAL],
    )
    try:
        # 模拟旧库：normal 已有其它菜单（_seed_role_grants 跳过），但 /sectors 菜单缺失。
        pg.execute("DELETE FROM app_config WHERE key=%s", [marker_key])
        pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s AND menu_id=%s", [ROLE_NORMAL, "/sectors"])

        seed_rbac(pg)

        menus = set(pg.query_df(
            "SELECT menu_id FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])["menu_id"])
        perm_ver = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        marker_value = pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [marker_key]
        ).iloc[0]["value"]
        marker = json.loads(marker_value) if isinstance(marker_value, str) else marker_value
        assert "/sectors" in menus
        assert perm_ver == 1
        assert marker["inserted_roles"] == [ROLE_NORMAL]
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, role_snapshot)
        _restore_app_config(pg, [marker_key], marker_snapshot)
        _restore_perm_versions(pg, perm_snapshot)


def test_sector_menu_grants_idempotent(pg):
    """marker 已存在时迁移 no-op：不增行、不 bump。"""
    before = set(pg.query_df(
        "SELECT menu_id FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])["menu_id"])
    perm_snapshot = _snapshot_perm_versions(pg)
    # 确保 marker 存在（seed 已写入），再跑一次 seed_rbac 应无变化。
    seed_rbac(pg)
    after = set(pg.query_df(
        "SELECT menu_id FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])["menu_id"])
    assert after == before
    assert _snapshot_perm_versions(pg) == perm_snapshot


def test_fk_delete_actions(pg):
    """FK 删除策略：parent/menu/role_id=RESTRICT(r)；授权关系与删用户=CASCADE(c)。"""
    df = pg.query_df(
        "SELECT conname, confdeltype FROM pg_constraint "
        "WHERE contype='f' AND conrelid::regclass::text = ANY(%s)",
        [list(RBAC_TABLES)])
    dele = {r["conname"]: r["confdeltype"] for _, r in df.iterrows()}
    assert dele["sys_menu_parent_id_fkey"] == "r"
    assert dele["sys_resource_menu_id_fkey"] == "r"
    assert dele["sys_user_role_role_id_fkey"] == "r"
    assert dele["sys_user_role_user_id_fkey"] == "c"
    assert dele["sys_role_menu_role_id_fkey"] == "c"
    assert dele["sys_role_menu_menu_id_fkey"] == "c"
    assert dele["sys_role_resource_role_id_fkey"] == "c"
    assert dele["sys_role_resource_resource_id_fkey"] == "c"


def test_existing_users_have_user_role(pg):
    """无角色存量用户按 role_code 补 sys_user_role；admin=system。"""
    admin = pg.query_df(
        "SELECT role_id FROM sys_user_role WHERE user_id=%s", ["admin"])
    assert ROLE_SYSTEM in set(admin["role_id"])
    # role_code 只用于无角色旧用户迁移；已有自定义角色的用户不应被追加内置角色。
    gap = pg.query_df(
        "SELECT count(*) n FROM sys_user u JOIN sys_role r ON r.code=u.role_code "
        "WHERE NOT EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id)")
    assert int(gap.iloc[0]["n"]) == 0


def test_seed_rbac_does_not_append_legacy_role_to_user_with_custom_role(pg):
    """启动 seed 不得把遗留 role_code=normal 重新附加给最小权限自定义角色用户。"""
    user_id = "pytest_custom_role_only_user"
    role_id = "pytest_custom_role_only"
    pg.execute("DELETE FROM sys_user WHERE id=%s", [user_id])
    pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])
    try:
        pg.execute(
            "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
            "VALUES (%s,%s,'最小权限测试','custom',FALSE,FALSE)",
            [role_id, role_id],
        )
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,'pytest',%s,%s,0,'active')",
            [user_id, user_id, ROLE_NORMAL],
        )
        pg.execute(
            "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)",
            [user_id, role_id],
        )

        seed_rbac(pg)

        roles = set(pg.query_df(
            "SELECT role_id FROM sys_user_role WHERE user_id=%s",
            [user_id],
        )["role_id"])
        assert roles == {role_id}
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [user_id])
        pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])


def test_seed_rbac_idempotent(pg):
    before = {t: _count(pg, t) for t in RBAC_TABLES}
    seed_rbac(pg)   # 复跑
    after = {t: _count(pg, t) for t in RBAC_TABLES}
    assert before == after


# ── R4/R5：发布权回滚（确定性基线恢复）可执行 + 有测试 ──────────────────────────
def _role_publish_codes(pg, role_id: str, codes: list[str]) -> set[str]:
    got = pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s AND resource_id = ANY(%s)",
        [role_id, codes])
    return set(got["resource_id"]) if not got.empty else set()


class _FaultRbacPG:
    """包装真实 pg：transaction() 内命中指定 SQL 片段即抛错，验证回滚整体原子性。"""

    def __init__(self, real, fail_on: str):
        self._real = real
        self._fail_on = fail_on

    def __getattr__(self, name):
        return getattr(self._real, name)

    @contextmanager
    def transaction(self):
        fail_on = self._fail_on

        class _Cur:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, params=None):
                if fail_on in sql:
                    raise RuntimeError(f"fault-injected on: {fail_on}")
                return self._real.execute(sql, params)

            def fetchone(self):
                return self._real.fetchone()

            @property
            def rowcount(self):
                return self._real.rowcount

        class _Conn:
            def __init__(self, real):
                self._real = real

            @contextmanager
            def cursor(self):
                with self._real.cursor() as c:
                    yield _Cur(c)

        with self._real.transaction() as conn:
            yield _Conn(conn)


def test_asset_publish_open_rollback_restores_c4_baseline(pg):
    """回滚确定性恢复 C4 前基线：normal 清空 8 码；tenant_admin 删 public、补齐 tenant；
    marker 写 tombstone（不删）；确有增删 → bump；回滚后按真实 init 顺序跑三写入者仍不复活；
    二次回滚因 rolled_back 短路 no-op。"""
    marker_key = _ASSET_PUBLISH_OPEN_MARKER
    tenant_codes = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES)
    public_codes = list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    all_codes = tenant_codes + public_codes
    uid = "asset_publish_rollback_user"
    stage6_key = _STAGE6_ASSET_VISIBILITY_MARKER
    marker_snap = _snapshot_app_config(pg, [marker_key, stage6_key])
    normal_snap = _snapshot_role_grants(pg, ROLE_NORMAL)
    ta_snap = _snapshot_role_grants(pg, ROLE_TENANT_ADMIN)
    perm_snap = _snapshot_perm_versions(pg)
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute(
        "INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
        "VALUES (%s, 'pytest', %s, %s, 0, 'active')", [uid, uid, ROLE_NORMAL])
    pg.execute("INSERT INTO sys_user_role (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
               [uid, ROLE_NORMAL])
    try:
        # 前置：确保已应用（marker + 全量授权）
        _backfill_asset_publish_open_v1(pg)
        # 模拟迁移期间人工移除 tenant_admin 一个 tenant 码
        pg.execute("DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
                   [ROLE_TENANT_ADMIN, tenant_codes[0]])
        pv_before = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])

        rollback_asset_publish_open_v1(pg)

        # normal：无任何发布码
        assert _role_publish_codes(pg, ROLE_NORMAL, all_codes) == set()
        # tenant_admin：tenant 全部补齐（含被人工删的）、public 清空
        assert _role_publish_codes(pg, ROLE_TENANT_ADMIN, tenant_codes) == set(tenant_codes)
        assert _role_publish_codes(pg, ROLE_TENANT_ADMIN, public_codes) == set()
        # marker 不删除，改写为 tombstone（rolled_back=true），使正向迁移重启后 no-op
        mval = json.loads(pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [marker_key]).iloc[0]["value"])
        assert mval.get("rolled_back") is True and mval.get("applied") is False
        # 确有增删 → bump 一次
        pv_after = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert pv_after == pv_before + 1

        # 持久性关键回归：回滚后**按真实启动顺序**跑全部发布权写入者 → 发布权**不得复活**、仍 C4 基线。
        # 且构造角色管理接口允许的边界：清空 normal 菜单（触发 _seed_role_grants 重授默认权限）、
        # 删除 stage6 marker（触发 seed_stage6 重跑），确认二者都消费 tombstone、不复活 public/发布码。
        pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])
        pg.execute("DELETE FROM app_config WHERE key=%s", [stage6_key])
        menu_codes = pg.query_df("SELECT id FROM sys_menu")["id"].tolist()
        _seed_role_grants(pg, menu_codes)        # init 第一个写入者
        seed_stage6_asset_visibility(pg)          # init 第二个写入者
        _backfill_asset_publish_open_v1(pg)       # init 第三个写入者
        # 三者跑完，发布权仍为 C4 基线：normal 无、tenant_admin 仅 tenant
        assert _role_publish_codes(pg, ROLE_NORMAL, all_codes) == set()
        assert _role_publish_codes(pg, ROLE_TENANT_ADMIN, public_codes) == set()
        assert _role_publish_codes(pg, ROLE_TENANT_ADMIN, tenant_codes) == set(tenant_codes)
        mval2 = json.loads(pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [marker_key]).iloc[0]["value"])
        assert mval2.get("rolled_back") is True  # tombstone 未被任何写入者覆盖
        # 关键：发布权状态未变（仍基线）。perm_ver 因 _seed_role_grants 重授**菜单**而 +1（R9 正确行为，
        # 菜单也是授权），但这不是发布权复活——上面已断言 normal 无发布码、tenant_admin 仅 tenant。
        pv_reinit = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert pv_reinit == pv_after + 1  # 仅菜单重授触发一次 bump（非发布权变更）

        # 二次回滚：tombstone 已在 → 整段 no-op，不再 bump（perm_ver 停在 reinit 后的值）
        rollback_asset_publish_open_v1(pg)
        pv_again = int(pg.query_df(
            "SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert pv_again == pv_reinit
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, normal_snap)
        _restore_role_grants(pg, ROLE_TENANT_ADMIN, ta_snap)
        _restore_app_config(pg, [marker_key, stage6_key], marker_snap)
        _restore_perm_versions(pg, perm_snap)


def _all_role_grants(pg, role_id: str) -> set[str]:
    got = pg.query_df("SELECT resource_id FROM sys_role_resource WHERE role_id=%s", [role_id])
    return set(got["resource_id"]) if not got.empty else set()


def _perm_ver_map(pg) -> dict[str, int]:
    df = pg.query_df("SELECT id, perm_ver FROM sys_user")
    return {r["id"]: int(r["perm_ver"]) for _, r in df.iterrows()}


def test_asset_publish_open_rollback_is_atomic_on_failure(pg):
    """回滚中途故障（tombstone 写入前抛错）：normal/tenant_admin 授权、marker、perm_ver 整体回滚，无半成品。"""
    marker_key = _ASSET_PUBLISH_OPEN_MARKER
    all_codes = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES) + list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    marker_snap = _snapshot_app_config(pg, [marker_key])
    normal_snap = _snapshot_role_grants(pg, ROLE_NORMAL)
    ta_snap = _snapshot_role_grants(pg, ROLE_TENANT_ADMIN)
    perm_snap = _snapshot_perm_versions(pg)
    try:
        _backfill_asset_publish_open_v1(pg)  # 确保已应用
        # 故障前完整快照：两类角色授权集合 + 全体 perm_ver + marker 值
        normal_before = _all_role_grants(pg, ROLE_NORMAL)
        ta_before = _all_role_grants(pg, ROLE_TENANT_ADMIN)
        perm_before = _perm_ver_map(pg)
        marker_before = pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [marker_key]).iloc[0]["value"]
        assert normal_before & set(all_codes), "前置：normal 应已有发布码"

        # 故障注入：tombstone 写入（UPDATE app_config）抛错 → 整个回滚事务回滚
        import pytest

        from backend.common.exceptions import StorageError
        fault_pg = _FaultRbacPG(pg, fail_on="UPDATE app_config")
        with pytest.raises(StorageError):
            rollback_asset_publish_open_v1(fault_pg)

        # 逐项断言完全不变：normal 授权、tenant_admin 授权、marker 值、全体 perm_ver
        assert _all_role_grants(pg, ROLE_NORMAL) == normal_before
        assert _all_role_grants(pg, ROLE_TENANT_ADMIN) == ta_before
        assert pg.query_df(
            "SELECT value FROM app_config WHERE key=%s", [marker_key]).iloc[0]["value"] == marker_before
        assert _perm_ver_map(pg) == perm_before
    finally:
        _restore_role_grants(pg, ROLE_NORMAL, normal_snap)
        _restore_role_grants(pg, ROLE_TENANT_ADMIN, ta_snap)
        _restore_app_config(pg, [marker_key], marker_snap)
        _restore_perm_versions(pg, perm_snap)


# ── R8-P1-3：发布策略状态机——非法/冲突 marker fail-closed（不放开发布权）──────────
def test_publish_policy_state_model_and_fail_closed(pg):
    key = _ASSET_PUBLISH_OPEN_MARKER
    snap = _snapshot_app_config(pg, [key])
    cases = [
        (None, _PUBLISH_STATE_MISSING),
        ('{"applied":true}', _PUBLISH_STATE_APPLIED),
        ('{"applied":false,"rolled_back":true}', _PUBLISH_STATE_ROLLED_BACK),
        ('not-json', _PUBLISH_STATE_INVALID),
        ('{}', _PUBLISH_STATE_INVALID),
        ('{"applied":true,"rolled_back":true}', _PUBLISH_STATE_INVALID),   # 冲突字段
        ('[1,2,3]', _PUBLISH_STATE_INVALID),                              # 非 dict
    ]
    try:
        for raw, expected in cases:
            pg.execute("DELETE FROM app_config WHERE key=%s", [key])
            if raw is not None:
                pg.execute("INSERT INTO app_config (key,value,updated_at) VALUES (%s,%s,now())", [key, raw])
            with pg.transaction() as conn, conn.cursor() as cur:
                state = _publish_policy_state_cur(cur)
            assert state == expected, (raw, state)
        # fail-closed：rolled_back / invalid 抑制授予；missing / applied 放开
        assert _publish_suppressed(_PUBLISH_STATE_ROLLED_BACK)
        assert _publish_suppressed(_PUBLISH_STATE_INVALID)
        assert not _publish_suppressed(_PUBLISH_STATE_MISSING)
        assert not _publish_suppressed(_PUBLISH_STATE_APPLIED)
    finally:
        _restore_app_config(pg, [key], snap)


# ── R8-P1-1：_seed_role_grants 获取与回滚共享的 advisory lock（串行化，防并发复活）──────
def test_seed_role_grants_acquires_shared_publish_lock(pg):
    import threading

    lock_key = _ASSET_PUBLISH_OPEN_LOCK
    done = threading.Event()
    err: list = []

    def _run_seed():
        try:
            _seed_role_grants(pg, [])
        except Exception as e:  # noqa: BLE001
            err.append(e)
        finally:
            done.set()

    with pg.pool.connection() as holder:
        with holder.cursor() as c:
            c.execute("SELECT pg_advisory_lock(%s)", [lock_key])  # 会话级持有，跨事务
        holder.commit()
        t = threading.Thread(target=_run_seed)
        t.start()
        try:
            # 锁被占用 → seed 的非系统角色事务阻塞在同一把锁上，1s 内不完成
            assert not done.wait(timeout=1.0), "seed_role_grants 应阻塞在共享 advisory lock 上"
        finally:
            with holder.cursor() as c:
                c.execute("SELECT pg_advisory_unlock(%s)", [lock_key])
            holder.commit()
    # 释放锁后 seed 应完成
    assert done.wait(timeout=10.0), "释放锁后 seed_role_grants 应完成"
    t.join(timeout=5.0)
    assert not err, err


def _mk_role_user(pg, uid: str, role_id: str) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute("INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
               "VALUES (%s,'pytest',%s,%s,0,'active')", [uid, uid, role_id])
    pg.execute("INSERT INTO sys_user_role (user_id, role_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
               [uid, role_id])


# ── R8-P1-2：_seed_role_grants 授权非原子——故障时菜单+资源+perm_ver 同退（回滚路径）──────
def test_seed_role_grants_atomic_rollback_on_failure(pg):
    """清空 tenant_admin 授权后重跑 seed，注入 perm_ver bump 故障 → 该角色菜单/资源整体回滚、perm_ver 不变。"""
    import pytest

    from backend.common.exceptions import StorageError
    ta_snap = _snapshot_role_grants(pg, ROLE_TENANT_ADMIN)
    perm_snap = _snapshot_perm_versions(pg)
    try:
        pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s", [ROLE_TENANT_ADMIN])
        pg.execute("DELETE FROM sys_role_resource WHERE role_id=%s", [ROLE_TENANT_ADMIN])
        fault_pg = _FaultRbacPG(pg, fail_on="UPDATE sys_user SET perm_ver")
        with pytest.raises(StorageError):
            _seed_role_grants(fault_pg, [])
        after = _snapshot_role_grants(pg, ROLE_TENANT_ADMIN)
        assert after["menus"] == [] and after["resources"] == []   # 半成品零残留
        assert _perm_ver_map(pg) == {r["id"]: int(r["perm_ver"]) for r in perm_snap}
    finally:
        _restore_role_grants(pg, ROLE_TENANT_ADMIN, ta_snap)
        _restore_perm_versions(pg, perm_snap)


# ── R9-P1：仅清空菜单（资源完整）重授，菜单变化也必须 bump perm_ver ──────────────────
def test_seed_role_grants_menu_only_reseed_bumps_perm_ver(pg):
    """角色管理允许「菜单空、资源完整」合法态；seed 恢复菜单 → 资源 INSERT 全冲突、res 计数为 0，
    但菜单确有恢复 → perm_ver 必须 +1（否则菜单权限扩大与 token 版本脱节）。"""
    uid = "seed_menu_only_user"
    normal_snap = _snapshot_role_grants(pg, ROLE_NORMAL)
    perm_snap = _snapshot_perm_versions(pg)
    _mk_role_user(pg, uid, ROLE_NORMAL)
    try:
        res_before = set(_snapshot_role_grants(pg, ROLE_NORMAL)["resources"])
        assert res_before, "前置：normal 资源应完整"
        # 只清菜单，保留资源
        pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])
        pv0 = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])

        _seed_role_grants(pg, [])

        # 菜单恢复非空、资源不变
        assert _snapshot_role_grants(pg, ROLE_NORMAL)["menus"], "菜单应被恢复"
        assert set(_snapshot_role_grants(pg, ROLE_NORMAL)["resources"]) == res_before
        # 关键：仅菜单变化也 bump perm_ver
        pv1 = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert pv1 == pv0 + 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, normal_snap)
        _restore_perm_versions(pg, perm_snap)


# ── R9-P2：成功重授（菜单+资源都清空）→ 授权恢复且 perm_ver +1（成功路径断言）──────────
def test_seed_role_grants_full_reseed_bumps_perm_ver(pg):
    uid = "seed_full_reseed_user"
    normal_snap = _snapshot_role_grants(pg, ROLE_NORMAL)
    perm_snap = _snapshot_perm_versions(pg)
    _mk_role_user(pg, uid, ROLE_NORMAL)
    try:
        pg.execute("DELETE FROM sys_role_menu WHERE role_id=%s", [ROLE_NORMAL])
        pg.execute("DELETE FROM sys_role_resource WHERE role_id=%s", [ROLE_NORMAL])
        pv0 = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])

        _seed_role_grants(pg, [])

        after = _snapshot_role_grants(pg, ROLE_NORMAL)
        assert after["menus"] and after["resources"]   # 菜单+资源都恢复
        pv1 = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])
        assert pv1 == pv0 + 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, normal_snap)
        _restore_perm_versions(pg, perm_snap)
