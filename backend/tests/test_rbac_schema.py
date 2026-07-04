"""多租户 RBAC 阶段三 · T1：权限数据模型 + seed 验证。

覆盖 §6.1 完成标准：6 表就绪、内置角色/菜单树/功能点 seed、FK 删除策略、默认授权、
存量用户按 role_code 补 sys_user_role、幂等复跑不增行。

统一用真实 PG（pg fixture 已 init_pg_db + seed）；断言针对 seeded 内置数据（按 code/is_builtin
过滤），不依赖绝对总数，兼容后续角色管理页新增的自定义角色/菜单。
"""

from __future__ import annotations

from backend.auth.constants import (
    ROLE_NORMAL,
    ROLE_PAID,
    ROLE_SYSTEM,
    ROLE_TENANT_ADMIN,
)
from backend.storage.pg_ddl import (
    _STAGE4_BUSINESS_GRANTS_MARKER,
    _SEED_MENU_TREE,
    _SEED_RESOURCES,
    _USER_RESOURCE_CODES,
    _flatten_menu_tree,
    seed_rbac,
)

RBAC_TABLES = (
    "sys_role", "sys_menu", "sys_resource",
    "sys_user_role", "sys_role_menu", "sys_role_resource",
)


def _count(pg, table: str) -> int:
    return int(pg.query_df(f"SELECT count(*) n FROM {table}").iloc[0]["n"])


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
    # kind 与 code 同名（内置预设）
    for code in (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID):
        assert by_code[code]["kind"] == code


def test_menu_tree_parent_linkage_and_type(pg):
    seeded = _flatten_menu_tree(_SEED_MENU_TREE)
    codes = [m["code"] for m in seeded]
    df = pg.query_df(
        "SELECT id, parent_id, type, route_path FROM sys_menu WHERE code = ANY(%s)",
        [codes])
    assert len(df) == len(seeded)
    ids = set(df["id"])
    for _, m in df.iterrows():
        # 每个非根 parent_id 必须落在 seeded 菜单内（FK + 树完整）
        if m["parent_id"] is not None:
            assert m["parent_id"] in ids
        # group 无 route_path；leaf 有且等于 id（code）
        if m["type"] == "group":
            assert m["route_path"] is None
        else:
            assert m["route_path"] == m["id"]


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
    assert {"/system/config", "/system/config/score", "/system/config/trade"} <= menus
    assert "/system/config/tech" not in menus and "/system/config/system" not in menus

    resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_TENANT_ADMIN])["resource_id"])
    assert set(_USER_RESOURCE_CODES) <= resources
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
    assert not any(c.startswith("user:") or c.startswith("role:") or c.startswith("tenant:")
                   for c in resources)


def test_tenant_admin_has_tenant_publish_by_default(pg):
    resources = set(pg.query_df(
        "SELECT resource_id FROM sys_role_resource WHERE role_id=%s",
        [ROLE_TENANT_ADMIN])["resource_id"])
    assert "score-profile:publish-tenant" in resources
    assert "score-profile:publish-public" not in resources


def test_stage4_business_grants_backfilled_for_existing_builtin_roles(pg):
    uid = "stage4_backfill_user"
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
        pg.execute("DELETE FROM app_config WHERE key=%s", [_STAGE4_BUSINESS_GRANTS_MARKER])
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
    """存量用户按 role_code 补 sys_user_role；admin=system。"""
    admin = pg.query_df(
        "SELECT role_id FROM sys_user_role WHERE user_id=%s", ["admin"])
    assert ROLE_SYSTEM in set(admin["role_id"])
    # 每个 role_code 命中内置角色的用户都应有对应 user_role（无遗漏）
    gap = pg.query_df(
        "SELECT count(*) n FROM sys_user u JOIN sys_role r ON r.code=u.role_code "
        "WHERE NOT EXISTS (SELECT 1 FROM sys_user_role ur "
        "WHERE ur.user_id=u.id AND ur.role_id=r.id)")
    assert int(gap.iloc[0]["n"]) == 0


def test_seed_rbac_idempotent(pg):
    before = {t: _count(pg, t) for t in RBAC_TABLES}
    seed_rbac(pg)   # 复跑
    after = {t: _count(pg, t) for t in RBAC_TABLES}
    assert before == after
