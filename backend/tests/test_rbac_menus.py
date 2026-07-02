"""多租户 RBAC 阶段三 · T7：菜单管理 API（R12）。

覆盖 §6.7：require_system 守卫(403) / 树读取 / CRUD / code·route 唯一 / 内置保护(不可删) /
级联保护(有子节点不可删) / 移动防成环 / 排序 / **删除·可见性变更 → 引用用户 perm_ver 自增**。

真实 PG + Redis + create_app()。菜单/资源类 bump 连带失效全部 system 用户（含真实 admin，生产
语义正确）；为不污染 admin perm_ver / 其它测试预铸 token，env teardown 还原 admin perm_ver 到快照。
所有临时角色/用户/菜单 uuid 化并清理。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.constants import ROLE_TENANT_ADMIN

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


def _tok(uid, tid, pv=0):
    from backend.auth.jwt_tokens import issue_access
    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _perm_ver(pg, uid):
    df = pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid])
    return int(df.iloc[0]["perm_ver"]) if not df.empty else None


@pytest.fixture()
def env(pg):
    """临时租户/用户/角色/菜单工厂 + teardown 清理；还原 admin perm_ver 防污染。"""
    admin_pv0 = _perm_ver(pg, "admin")
    made = {"user": [], "tenant": [], "role": [], "menu": []}

    def mk_tenant():
        tid = "tt_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')", [tid, tid])
        made["tenant"].append(tid)
        return tid

    def mk_user(tid, role_code):
        uid = "uu_" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,0,'active')", [uid, tid, uid, role_code])
        pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [uid, role_code])
        made["user"].append(uid)
        return uid

    def mk_role():
        rid = "rr_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
                   "VALUES (%s,%s,%s,'custom',FALSE,FALSE)", [rid, rid, rid])
        made["role"].append(rid)
        return rid

    def mk_menu(*, visible="login", parent_id=None):
        """直接落一个自定义菜单（绕过 API，供 bump/删除用例准备数据）。"""
        mid = "mm_" + uuid.uuid4().hex[:8]
        code = "m_" + uuid.uuid4().hex[:6]
        pg.execute(
            "INSERT INTO sys_menu (id,parent_id,code,title,type,route_path,visible,sort,is_builtin) "
            "VALUES (%s,%s,%s,%s,'leaf',%s,%s,10,FALSE)",
            [mid, parent_id, code, code, "/" + code, visible])
        made["menu"].append(mid)
        return mid

    def grant_menu(role_id, menu_id):
        pg.execute("INSERT INTO sys_role_menu (role_id,menu_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [role_id, menu_id])

    def sys_headers():
        pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
        return _tok("admin", "default", pv)

    from types import SimpleNamespace
    yield SimpleNamespace(mk_tenant=mk_tenant, mk_user=mk_user, mk_role=mk_role,
                          mk_menu=mk_menu, grant_menu=grant_menu, sys_headers=sys_headers, pg=pg)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])
    for rid in made["role"]:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    for mid in reversed(made["menu"]):   # 反序：先删子后删父，避开 parent_id FK RESTRICT
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [mid])
    pg.execute("UPDATE sys_user SET perm_ver=%s WHERE id='admin'", [admin_pv0])   # 还原，防污染


def _flatten(tree):
    out = []
    for n in tree:
        out.append(n)
        out.extend(_flatten(n.get("children", [])))
    return out


# ── 守卫 ──

def test_list_requires_token(client):
    assert client.get("/api/menus").status_code == 401


def test_list_forbidden_for_tenant_admin(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.get("/api/menus", headers=_tok(ta, tid))
    assert r.status_code == 403 and r.json()["code"] == 4030


def test_tree_for_system(client, env):
    r = client.get("/api/menus", headers=env.sys_headers())
    assert r.status_code == 200
    codes = {n["code"] for n in _flatten(r.json()["data"])}
    assert {"quotes", "system", "permission", "/system/users"} <= codes   # 含 seed 树
    # 嵌套结构：quotes 应有子节点
    quotes = next(n for n in r.json()["data"] if n["code"] == "quotes")
    assert {c["code"] for c in quotes["children"]} == {"/stocks", "/board"}


# ── CRUD / 唯一 ──

def test_create_leaf_and_group(client, env):
    code = "grp_" + uuid.uuid4().hex[:6]
    r = client.post("/api/menus", json={
        "code": code, "title": "临时分组", "type": "group", "visible": "system"},
        headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    gid = r.json()["data"]["id"]
    assert r.json()["data"]["route_path"] is None   # group 无路由
    try:
        leaf_code = "leaf_" + uuid.uuid4().hex[:6]
        r2 = client.post("/api/menus", json={
            "parentId": gid, "code": leaf_code, "title": "临时叶子", "type": "leaf",
            "routePath": "/" + leaf_code, "icon": "Setting"}, headers=env.sys_headers())
        assert r2.json()["data"]["parent_id"] == gid and r2.json()["data"]["icon"] == "Setting"
        client.delete(f"/api/menus/{r2.json()['data']['id']}", headers=env.sys_headers())
    finally:
        client.delete(f"/api/menus/{gid}", headers=env.sys_headers())


def test_create_duplicate_code_rejected(client, env):
    mid = env.mk_menu()
    code = env.pg.query_df("SELECT code FROM sys_menu WHERE id=%s", [mid]).iloc[0]["code"]
    r = client.post("/api/menus", json={
        "code": code, "title": "撞码", "type": "leaf", "routePath": "/x_" + uuid.uuid4().hex[:6]},
        headers=env.sys_headers())
    assert r.json()["code"] == 4000


def test_create_leaf_requires_unique_route(client, env):
    mid = env.mk_menu()
    route = env.pg.query_df("SELECT route_path FROM sys_menu WHERE id=%s", [mid]).iloc[0]["route_path"]
    r = client.post("/api/menus", json={
        "code": "c_" + uuid.uuid4().hex[:6], "title": "撞路由", "type": "leaf", "routePath": route},
        headers=env.sys_headers())
    assert r.json()["code"] == 4000


def test_create_leaf_without_route_rejected(client, env):
    r = client.post("/api/menus", json={
        "code": "c_" + uuid.uuid4().hex[:6], "title": "无路由叶子", "type": "leaf"},
        headers=env.sys_headers())
    assert r.json()["code"] == 4000


# ── 编辑 / 移动 ──

def test_update_title(client, env):
    mid = env.mk_menu()
    r = client.put(f"/api/menus/{mid}", json={
        "title": "改名了", "type": "leaf",
        "routePath": env.pg.query_df("SELECT route_path FROM sys_menu WHERE id=%s", [mid]).iloc[0]["route_path"],
        "visible": "login"}, headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["data"]["title"] == "改名了"


def test_move_into_own_descendant_rejected(client, env):
    parent = env.mk_menu()
    child = env.mk_menu(parent_id=parent)
    # 把 parent 移到它自己的子节点 child 下 → 成环，拒
    r = client.put(f"/api/menus/{parent}", json={
        "title": "环", "type": "group", "visible": "login", "parentId": child},
        headers=env.sys_headers())
    assert r.json()["code"] == 4000


# ── 内置 / 级联保护 ──

def test_builtin_menu_cannot_be_deleted(client, env):
    # seed 的 /screen 为内置
    mid = env.pg.query_df("SELECT id FROM sys_menu WHERE code='/screen'").iloc[0]["id"]
    r = client.delete(f"/api/menus/{mid}", headers=env.sys_headers())
    assert r.status_code == 403


def test_delete_menu_with_children_rejected(client, env):
    parent = env.mk_menu()
    env.mk_menu(parent_id=parent)
    r = client.delete(f"/api/menus/{parent}", headers=env.sys_headers())
    assert r.json()["code"] == 4000   # 有子节点


# ── 排序 ──

def test_reorder(client, env):
    m1 = env.mk_menu()
    m2 = env.mk_menu()
    r = client.post("/api/menus/reorder", json={"items": [
        {"id": m1, "sort": 50}, {"id": m2, "sort": 20}]}, headers=env.sys_headers())
    assert r.status_code == 200
    assert int(env.pg.query_df("SELECT sort FROM sys_menu WHERE id=%s", [m1]).iloc[0]["sort"]) == 50


# ── 缓存失效（删除 / 可见性变更 → 引用用户 perm_ver 自增）──

def test_delete_bumps_referencing_users(client, env):
    mid = env.mk_menu()
    rid = env.mk_role()
    env.grant_menu(rid, mid)
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, rid])
    v0 = _perm_ver(env.pg, holder)
    r = client.delete(f"/api/menus/{mid}", headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, holder) == v0 + 1   # 删菜单 → 引用它的角色的用户失效


def test_visibility_change_bumps_referencing_users(client, env):
    mid = env.mk_menu(visible="login")
    rid = env.mk_role()
    env.grant_menu(rid, mid)
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, rid])
    v0 = _perm_ver(env.pg, holder)
    route = env.pg.query_df("SELECT route_path FROM sys_menu WHERE id=%s", [mid]).iloc[0]["route_path"]
    r = client.put(f"/api/menus/{mid}", json={
        "title": "收紧可见性", "type": "leaf", "routePath": route, "visible": "system"},
        headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, holder) == v0 + 1   # 可见性变更 → 引用用户失效


def test_title_only_edit_does_not_bump(client, env):
    mid = env.mk_menu(visible="login")
    rid = env.mk_role()
    env.grant_menu(rid, mid)
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, rid])
    v0 = _perm_ver(env.pg, holder)
    route = env.pg.query_df("SELECT route_path FROM sys_menu WHERE id=%s", [mid]).iloc[0]["route_path"]
    client.put(f"/api/menus/{mid}", json={
        "title": "仅改名", "type": "leaf", "routePath": route, "visible": "login"},
        headers=env.sys_headers())
    assert _perm_ver(env.pg, holder) == v0   # 纯展示编辑不失效
