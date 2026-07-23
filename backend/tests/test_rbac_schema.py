"""多租户 RBAC 阶段三 · T1：权限数据模型 + seed 验证。

覆盖 §6.1 完成标准：6 表就绪、内置角色/菜单树/功能点 seed、FK 删除策略、默认授权、
存量用户按 role_code 补 sys_user_role、幂等复跑不增行。

统一用真实 PG（pg fixture 已 init_pg_db + seed）；断言针对 seeded 内置数据（按 code/is_builtin
过滤），不依赖绝对总数，兼容后续角色管理页新增的自定义角色/菜单。
"""

from __future__ import annotations

from backend.auth.constants import (
    ASSET_PUBLIC_PUBLISH_RESOURCE_CODES,
    ASSET_TENANT_PUBLISH_RESOURCE_CODES,
    ROLE_NORMAL,
    ROLE_PAID,
    ROLE_SYSTEM,
    ROLE_TENANT_ADMIN,
)
from backend.storage.pg_ddl import (
    _STAGE4_BUSINESS_GRANTS_MARKER,
    _STAGE6_ASSET_VISIBILITY_MARKER,
    _SEED_MENU_TREE,
    _SEED_RESOURCES,
    _USER_RESOURCE_CODES,
    _flatten_menu_tree,
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
        "SELECT code, name, kind, is_builtin, is_locked FROM sys_role "
        "WHERE code = ANY(%s)",
        [[ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID]])
    by_code = {r["code"]: r for _, r in df.iterrows()}
    assert set(by_code) == {ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID}
    # 全部内置；仅 system 锁定
    assert all(bool(r["is_builtin"]) for r in by_code.values())
    assert bool(by_code[ROLE_SYSTEM]["is_locked"]) is True
    assert bool(by_code[ROLE_TENANT_ADMIN]["is_locked"]) is False
    # kind 与 code 同名（系统内置）
    for code in (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID):
        assert by_code[code]["kind"] == code


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
    parent_id = "pytest_menu_parent"
    original = pg.query_df(
        "SELECT parent_id, title, icon, sort, visible FROM sys_menu WHERE id=%s", ["/screen"]
    ).iloc[0].to_dict()
    try:
        pg.execute(
            "INSERT INTO sys_menu "
            "(id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, NULL, %s, %s, 'group', NULL, %s, 999, 'login', FALSE) "
            "ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title",
            [parent_id, parent_id, "测试菜单分组", "Menu"],
        )
        pg.execute(
            "UPDATE sys_menu SET parent_id=%s, title=%s, icon=NULL, sort=%s, visible=%s "
            "WHERE id=%s",
            [parent_id, "运行期筛选", 777, "login", "/screen"],
        )
        seed_rbac(pg)
        row = pg.query_df(
            "SELECT parent_id, title, icon, sort, visible FROM sys_menu WHERE id=%s", ["/screen"]
        ).iloc[0]
        assert row["parent_id"] == parent_id
        assert row["title"] == "运行期筛选"
        assert row["icon"] is None
        assert int(row["sort"]) == 777
        assert row["visible"] == "login"
    finally:
        pg.execute(
            "UPDATE sys_menu SET parent_id=%s, title=%s, icon=%s, sort=%s, visible=%s "
            "WHERE id=%s",
            [
                original["parent_id"], original["title"], original["icon"], int(original["sort"]),
                original["visible"], "/screen",
            ],
        )
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [parent_id])


def test_seed_rbac_does_not_overwrite_db_resource_customization(pg):
    resource_id = "score-profile:view"
    menu_id = "pytest_resource_parent"
    original = pg.query_df(
        "SELECT menu_id, name, type, api_method, api_path, sort "
        "FROM sys_resource WHERE id=%s",
        [resource_id],
    ).iloc[0].to_dict()
    try:
        pg.execute(
            "INSERT INTO sys_menu "
            "(id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, NULL, %s, %s, 'leaf', %s, NULL, 999, 'login', FALSE) "
            "ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title",
            [menu_id, menu_id, "测试功能点菜单", "/pytest-resource-parent"],
        )
        pg.execute(
            "UPDATE sys_resource SET menu_id=%s, name=%s, type=%s, api_method=%s, "
            "api_path=%s, sort=%s WHERE id=%s",
            [
                menu_id, "运行期评分查看", "button", "POST", "/api/custom-score-view", 777,
                resource_id,
            ],
        )
        seed_rbac(pg)
        row = pg.query_df(
            "SELECT menu_id, name, type, api_method, api_path, sort "
            "FROM sys_resource WHERE id=%s",
            [resource_id],
        ).iloc[0]
        assert row["menu_id"] == menu_id
        assert row["name"] == "运行期评分查看"
        assert row["type"] == "button"
        assert row["api_method"] == "POST"
        assert row["api_path"] == "/api/custom-score-view"
        assert int(row["sort"]) == 777
    finally:
        pg.execute(
            "UPDATE sys_resource SET menu_id=%s, name=%s, type=%s, api_method=%s, "
            "api_path=%s, sort=%s WHERE id=%s",
            [
                original["menu_id"], original["name"], original["type"],
                original["api_method"], original["api_path"], int(original["sort"]), resource_id,
            ],
        )
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [menu_id])


def test_seed_resource_codes_are_unique():
    codes = [r[1] for r in _SEED_RESOURCES]
    assert len(codes) == len(set(codes))


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
    assert not any(c.startswith("role:") or c.startswith("tenant:") for c in resources)


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
    assert "score-profile:publish-tenant" not in resources
    assert "score-profile:publish-public" not in resources
    assert not set(ASSET_TENANT_PUBLISH_RESOURCE_CODES) & resources
    assert not set(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) & resources
    assert not any(c.startswith("user:") or c.startswith("role:") or c.startswith("tenant:")
                   for c in resources)


def test_tenant_admin_has_tenant_publish_by_default(pg):
    resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_TENANT_ADMIN])["resource_id"])
    assert "score-profile:publish-tenant" in resources
    assert "score-profile:publish-public" not in resources
    assert set(ASSET_TENANT_PUBLISH_RESOURCE_CODES) <= resources
    assert not set(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) & resources


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
        assert set(ASSET_TENANT_PUBLISH_RESOURCE_CODES) <= resources
        assert not set(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES) & resources
        assert perm_ver == 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_TENANT_ADMIN, role_snapshot)
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
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id IN (%s, %s)",
            [ROLE_NORMAL, "board:view", "score-profile:publish-tenant"],
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
        assert "score-profile:publish-tenant" not in resources
        assert perm_ver == 1
    finally:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
        _restore_role_grants(pg, ROLE_NORMAL, role_snapshot)
        _restore_app_config(pg, [marker_key], marker_snapshot)
        _restore_perm_versions(pg, perm_snapshot)


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
