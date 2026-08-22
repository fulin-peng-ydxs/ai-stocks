"""多租户 RBAC 阶段三 · T10：/me 填充 + 权限消费（按角色授权 ∩ 可见性双过滤的菜单树 + 功能码）。

覆盖 §6.10：system 全菜单（含系统专属分支）/ tenant_admin 过滤后菜单（业务 + 用户管理，无数据管理/
角色·租户管理）/ normal 仅业务菜单（无系统分组）/ 空分组剪除 / permissions 功能码准确 / MenuNode 形状。

真实 PG + Redis。直接调 AuthService().me()（不经 token/中间件）。临时租户/用户清理。
"""

from __future__ import annotations

import uuid

import pytest

from backend.auth.constants import ROLE_NORMAL, ROLE_TENANT_ADMIN

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"


@pytest.fixture()
def svc(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.services.auth_service import AuthService
    return AuthService()


@pytest.fixture()
def env(pg):
    made = {"user": [], "tenant": []}

    def mk_tenant():
        tid = "tt_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')", [tid, tid])
        made["tenant"].append(tid)
        return tid

    def mk_user(tid, role_code):
        uid = "uu_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
                   "VALUES (%s,%s,%s,%s,0,'active')", [uid, tid, uid, role_code])
        pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [uid, role_code])
        made["user"].append(uid)
        return uid

    from types import SimpleNamespace
    yield SimpleNamespace(mk_tenant=mk_tenant, mk_user=mk_user, pg=pg)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _indexes(tree: list) -> set[str]:
    out: set[str] = set()
    for n in tree:
        out.add(n["index"])
        out |= _indexes(n.get("children", []))
    return out


def _find(tree: list, index: str):
    for n in tree:
        if n["index"] == index:
            return n
        got = _find(n.get("children", []), index)
        if got:
            return got
    return None


# ── system 全量 ──

def test_system_me_full_menus_and_perms(svc, env):
    me = svc.me("admin")   # seed 平台管理员=system
    idx = _indexes(me["menus"])
    # 业务 + 系统专属分支全含
    assert {"quotes", "/screen", "data", "/data/quality", "system", "/system/config"} <= idx
    assert {"permission", "/system/users", "/system/roles", "/system/menus", "/system/tenants"} <= idx
    # 功能码含系统专属码
    assert {"role:create", "tenant:create", "menu:create", "user:list"} <= set(me["permissions"])
    assert "/trade-discipline" not in idx  # T5 正式页面接入前，对 system 也隐藏分阶段菜单


# ── tenant_admin 过滤 ──

def test_tenant_admin_me_filtered(svc, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    me = svc.me(ta)
    idx = _indexes(me["menus"])
    # 业务叶子与租户用户管理可达。内置菜单允许在管理页重排，不能把父分组层级写死进断言。
    assert {"/stocks", "/board", "/screen", "/backtest", "/training"} <= idx
    assert {
        "/system/config/score",
        "/system/config/trade",
        "/system/users",
    } <= idx
    assert "/trade-discipline" not in idx
    # 系统专属分支隐藏：数据管理、技术指标、系统设置、角色/菜单/租户管理均不可见
    assert "data" not in idx
    assert {"/system/config/tech", "/system/config/system"} & idx == set()
    assert {"/system/roles", "/system/menus", "/system/tenants"} & idx == set()
    # 功能码：含 user:*，不含系统专属码
    assert "user:list" in me["permissions"] and "user:delete" in me["permissions"]
    assert "role:create" not in me["permissions"] and "tenant:create" not in me["permissions"]


def test_tenant_admin_permission_group_pruned_to_users_only(svc, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    me = svc.me(ta)
    perm = _find(me["menus"], "permission")
    assert perm is not None
    # 权限管理分组下仅剩用户管理（角色/菜单/租户为 system-only 被剪）
    assert {c["index"] for c in perm["children"]} == {"/system/users"}


# ── normal 仅业务 ──

def test_normal_me_business_only(svc, env):
    tid = env.mk_tenant()
    nu = env.mk_user(tid, ROLE_NORMAL)
    me = svc.me(nu)
    idx = _indexes(me["menus"])
    assert {"/stocks", "/board", "/screen", "/backtest", "/training"} <= idx
    assert {"/system/config/score", "/system/config/trade"} <= idx
    assert "permission" not in idx and "data" not in idx
    assert "/trade-discipline" not in idx
    assert {"/system/config/tech", "/system/config/system"} & idx == set()
    # stage4·R21：baseline 基线共享读对非 system 业务用户**强制注入**（与 role_resource 授权无关，恒有）
    perms = set(me["permissions"])
    assert {"layout:view", "trade-calendar:view", "indicator:registry"} <= perms
    # 不含用户管理/系统专属码（system-only 挂 visible='system' 菜单，不授非 system）
    assert "user:list" not in perms and "role:create" not in perms and "config:view" not in perms
    # 注：normal 研究业务功能码（board:*/screen:*/backtest:* 等）默认授权走 seed（新库）/ 回填 SQL（既有库），
    # 授权→/me 生效链路由 test_stage4_resource_codes 的显式授权用例覆盖（本持久库 normal 为 stage3 存量态）。


# ── MenuNode 形状 ──

def test_menu_node_shape(svc, env):
    tid = env.mk_tenant()
    nu = env.mk_user(tid, ROLE_NORMAL)
    me = svc.me(nu)
    quotes = _find(me["menus"], "quotes")
    assert quotes["title"] == "最新行情" and quotes["icon"] == "TrendCharts"   # EP 图标名
    assert "children" in quotes                                                # 分组有 children
    leaf = _find(me["menus"], "/screen")
    assert leaf["index"] == "/screen" and "children" not in leaf              # 叶子无 children
