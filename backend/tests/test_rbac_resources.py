"""多租户 RBAC 阶段三 · T8：功能点管理 API（R13）。

覆盖 §6.8：require_system 守卫(403) / 按菜单列举 / CRUD / code 全局唯一不可复用 / 内置保护
(不可删·code 不可改) / **删除·改 code → 引用用户 perm_ver 自增** / 可被角色勾选(role_count)。

真实 PG + Redis + create_app()。资源类 bump 连带失效全部 system 用户（含真实 admin）；env teardown
还原 admin perm_ver 防污染。临时角色/用户/功能点 uuid 化并清理。
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
    admin_pv0 = _perm_ver(pg, "admin")
    made = {"user": [], "tenant": [], "role": [], "res": []}
    # 用现有内置菜单挂载临时功能点（避免再造菜单）
    menu_id = pg.query_df("SELECT id FROM sys_menu WHERE code='/system/users'").iloc[0]["id"]

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

    def mk_role():
        rid = "rr_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
                   "VALUES (%s,%s,%s,'custom',FALSE,FALSE)", [rid, rid, rid])
        made["role"].append(rid)
        return rid

    def mk_res(*, code=None):
        rid = "res_" + uuid.uuid4().hex[:8]
        code = code or ("cap:" + uuid.uuid4().hex[:6])
        pg.execute("INSERT INTO sys_resource (id,menu_id,code,name,type,sort,is_builtin) "
                   "VALUES (%s,%s,%s,%s,'api',10,FALSE)", [rid, menu_id, code, code])
        made["res"].append(rid)
        return rid

    def grant_res(role_id, res_id):
        pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [role_id, res_id])

    def sys_headers():
        pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
        return _tok("admin", "default", pv)

    from types import SimpleNamespace
    yield SimpleNamespace(mk_tenant=mk_tenant, mk_user=mk_user, mk_role=mk_role, mk_res=mk_res,
                          grant_res=grant_res, sys_headers=sys_headers, menu_id=menu_id, pg=pg)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])
    for rid in made["role"]:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    for rid in made["res"]:
        pg.execute("DELETE FROM sys_resource WHERE id=%s", [rid])
    pg.execute("UPDATE sys_user SET perm_ver=%s WHERE id='admin'", [admin_pv0])


# ── 守卫 ──

def test_list_requires_token(client):
    assert client.get("/api/resources").status_code == 401


def test_list_forbidden_for_tenant_admin(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.get("/api/resources", headers=_tok(ta, tid))
    assert r.status_code == 403 and r.json()["code"] == 4030


def test_list_and_filter_by_menu(client, env):
    r = client.get("/api/resources", headers=env.sys_headers())
    assert r.status_code == 200
    all_codes = {x["code"] for x in r.json()["data"]}
    assert "user:list" in all_codes   # seed 功能点
    # 按菜单过滤：/system/users 菜单下应含 user:* 且不含 role:*
    r2 = client.get(f"/api/resources?menu_id={env.menu_id}", headers=env.sys_headers())
    codes = {x["code"] for x in r2.json()["data"]}
    assert "user:list" in codes and "role:create" not in codes


# ── CRUD / 唯一 ──

def test_create_update_delete(client, env):
    code = "cap:" + uuid.uuid4().hex[:6]
    r = client.post("/api/resources", json={
        "menuId": env.menu_id, "code": code, "name": "临时功能", "type": "button"},
        headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    rid = r.json()["data"]["id"]
    try:
        r2 = client.put(f"/api/resources/{rid}", json={
            "menuId": env.menu_id, "code": code, "name": "改名功能", "type": "api",
            "apiMethod": "GET", "apiPath": "/api/x"}, headers=env.sys_headers())
        assert r2.json()["data"]["name"] == "改名功能" and r2.json()["data"]["type"] == "api"
        r3 = client.delete(f"/api/resources/{rid}", headers=env.sys_headers())
        assert r3.status_code == 200 and r3.json()["code"] == 0
        assert env.pg.query_df("SELECT 1 FROM sys_resource WHERE id=%s", [rid]).empty
    finally:
        env.pg.execute("DELETE FROM sys_resource WHERE id=%s", [rid])


def test_create_duplicate_code_rejected(client, env):
    existing = env.mk_res()
    code = env.pg.query_df("SELECT code FROM sys_resource WHERE id=%s", [existing]).iloc[0]["code"]
    r = client.post("/api/resources", json={
        "menuId": env.menu_id, "code": code, "name": "撞码"}, headers=env.sys_headers())
    assert r.json()["code"] == 4000   # 功能码不可复用


def test_create_bad_menu_rejected(client, env):
    r = client.post("/api/resources", json={
        "menuId": "no_such_menu", "code": "cap:" + uuid.uuid4().hex[:6], "name": "坏菜单"},
        headers=env.sys_headers())
    assert r.json()["code"] == 4000


# ── 内置保护 ──

def test_builtin_resource_cannot_be_deleted(client, env):
    r = client.delete("/api/resources/user:list", headers=env.sys_headers())
    assert r.status_code == 403


def test_builtin_resource_code_cannot_be_changed(client, env):
    r = client.put("/api/resources/user:list", json={
        "menuId": env.menu_id, "code": "user:list-x", "name": "查看用户", "type": "api"},
        headers=env.sys_headers())
    assert r.status_code == 403   # 内置码硬绑守卫不可改


def test_builtin_resource_name_editable(client, env):
    # 内置码不改、仅改 name → 允许；用后还原名称避免污染 seed 语义
    orig = env.pg.query_df("SELECT name FROM sys_resource WHERE id='user:list'").iloc[0]["name"]
    try:
        r = client.put("/api/resources/user:list", json={
            "menuId": env.menu_id, "code": "user:list", "name": "查看用户(改)", "type": "api"},
            headers=env.sys_headers())
        assert r.status_code == 200 and r.json()["data"]["name"] == "查看用户(改)"
    finally:
        env.pg.execute("UPDATE sys_resource SET name=%s WHERE id='user:list'", [orig])


# ── 缓存失效（删除 / 改 code → 引用用户 perm_ver 自增）──

def test_delete_bumps_referencing_users(client, env):
    rid = env.mk_res()
    before = env.pg.query_df(
        "SELECT menu_id,code,name,type,api_method,api_path,sort,is_builtin "
        "FROM sys_resource WHERE id=%s",
        [rid],
    ).iloc[0].to_dict()
    role = env.mk_role()
    env.grant_res(role, rid)
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, role])
    v0 = _perm_ver(env.pg, holder)
    r = client.delete(f"/api/resources/{rid}", headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, holder) == v0 + 1
    audit = env.pg.query_df(
        "SELECT target_label,changes FROM audit_log "
        "WHERE event_category='rbac' AND action='resource_delete' AND target_id=%s "
        "ORDER BY event_time DESC LIMIT 1",
        [rid],
    ).iloc[0]
    assert audit["target_label"] == before["name"]
    changes = {item["field"]: item for item in audit["changes"]}
    assert changes["menu_id"]["before"] == before["menu_id"]
    assert changes["code"]["before"] == before["code"]
    assert all(item["after"] is None for item in changes.values())
    env.pg.execute(
        "DELETE FROM audit_log WHERE event_category='rbac' AND action='resource_delete' "
        "AND target_id=%s",
        [rid],
    )


def test_code_change_bumps_referencing_users(client, env):
    rid = env.mk_res()
    role = env.mk_role()
    env.grant_res(role, rid)
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, role])
    v0 = _perm_ver(env.pg, holder)
    r = client.put(f"/api/resources/{rid}", json={
        "menuId": env.menu_id, "code": "cap:renamed_" + uuid.uuid4().hex[:6],
        "name": "改码", "type": "api"}, headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, holder) == v0 + 1   # 改 code → 有效权限码变，引用用户失效


def test_name_only_edit_does_not_bump(client, env):
    rid = env.mk_res()
    role = env.mk_role()
    env.grant_res(role, rid)
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, role])
    v0 = _perm_ver(env.pg, holder)
    code = env.pg.query_df("SELECT code FROM sys_resource WHERE id=%s", [rid]).iloc[0]["code"]
    client.put(f"/api/resources/{rid}", json={
        "menuId": env.menu_id, "code": code, "name": "仅改名", "type": "api"},
        headers=env.sys_headers())
    assert _perm_ver(env.pg, holder) == v0   # 改 name 不影响权限码，不失效


# ── 可被角色勾选（role_count 反映引用）──

def test_role_count_reflects_grants(client, env):
    rid = env.mk_res()
    role = env.mk_role()
    env.grant_res(role, rid)
    r = client.get(f"/api/resources?menu_id={env.menu_id}", headers=env.sys_headers())
    row = next(x for x in r.json()["data"] if x["id"] == rid)
    assert row["role_count"] == 1
