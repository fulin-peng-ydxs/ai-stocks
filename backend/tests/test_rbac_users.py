"""多租户 RBAC 阶段三 · T5：用户管理 API（R10）。

覆盖 §6.5：精确码守卫(403) / 域隔离(system 全局、tenant_admin 本租户) / 多角色 CRUD /
唯一冲突 / 启停即时失效(perm_ver bump) / 自身与最后管理员保护 / 可分配角色越权拦截。

真实 PG + Redis + create_app()。所有临时租户/用户 uuid 化并 teardown 清理；acting token
只用 admin(system) 或本用例新建的 tenant_admin，不触碰其它持久数据。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.constants import ROLE_NORMAL, ROLE_TENANT_ADMIN

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


def _tok(uid, tid, pv=0):
    from backend.auth.jwt_tokens import issue_access
    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


@pytest.fixture()
def env(pg):
    """临时租户/用户工厂（带 sys_user_role）+ teardown 清理。"""
    made = {"user": [], "tenant": []}

    def mk_tenant():
        tid = "tt_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,'active')", [tid, tid])
        made["tenant"].append(tid)
        return tid

    def mk_user(tid, role_code, *, status="active"):
        uid = "uu_" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
            "VALUES (%s,%s,%s,%s,0,%s)", [uid, tid, uid, role_code, status])
        pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [uid, role_code])
        made["user"].append(uid)
        return uid

    def sys_headers():
        pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
        return _tok("admin", "default", pv)

    from types import SimpleNamespace
    yield SimpleNamespace(mk_tenant=mk_tenant, mk_user=mk_user, sys_headers=sys_headers, pg=pg)

    # 清理：先删本用例通过 API 新建的用户（按账号前缀），再删登记的用户/租户
    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])   # API 新建的用户
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _perm_ver(pg, uid):
    df = pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid])
    return int(df.iloc[0]["perm_ver"]) if not df.empty else None


# ── 守卫 ──

def test_list_forbidden_for_normal_user(client, env):
    tid = env.mk_tenant()
    nid = env.mk_user(tid, ROLE_NORMAL)   # normal 无 user:list
    r = client.get("/api/users", headers=_tok(nid, tid))
    assert r.status_code == 403 and r.json()["code"] == 4030


def test_list_allowed_for_tenant_admin(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.get("/api/users", headers=_tok(ta, tid))
    assert r.status_code == 200


def test_list_requires_token(client):
    assert client.get("/api/users").status_code == 401


# ── 域隔离 ──

def test_tenant_admin_lists_own_tenant_only(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    env.mk_user(other, ROLE_NORMAL)
    r = client.get("/api/users", headers=_tok(ta, tid))
    data = r.json()["data"]
    assert {u["tenant_id"] for u in data["items"]} == {tid}   # 只见本租户


def test_tenant_admin_cannot_touch_other_tenant_user(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    victim = env.mk_user(other, ROLE_NORMAL)
    r = client.post(f"/api/users/{victim}/status", json={"status": "disabled"},
                    headers=_tok(ta, tid))
    assert r.json()["code"] == 4004   # 跨租户视为不存在（业务软失败 200 + code）


# ── 新建 / 多角色 / 唯一 ──

def test_system_create_and_list(client, env):
    tid = env.mk_tenant()
    acc = "newu_" + uuid.uuid4().hex[:6]
    r = client.post("/api/users", json={
        "account": acc, "password": "GoodPass1", "roleIds": [ROLE_NORMAL],
        "tenantId": tid}, headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    created = r.json()["data"]
    assert created["tenant_id"] == tid and ROLE_NORMAL in created["roles"]


def test_create_multi_role(client, env):
    tid = env.mk_tenant()
    acc = "multi_" + uuid.uuid4().hex[:6]
    r = client.post("/api/users", json={
        "account": acc, "password": "GoodPass1",
        "roleIds": [ROLE_TENANT_ADMIN, ROLE_NORMAL], "tenantId": tid},
        headers=env.sys_headers())
    assert r.status_code == 200
    assert set(r.json()["data"]["roles"]) == {ROLE_TENANT_ADMIN, ROLE_NORMAL}


def test_create_duplicate_account_rejected(client, env):
    tid = env.mk_tenant()
    acc = "dup_" + uuid.uuid4().hex[:6]
    body = {"account": acc, "password": "GoodPass1", "roleIds": [ROLE_NORMAL], "tenantId": tid}
    assert client.post("/api/users", json=body, headers=env.sys_headers()).json()["code"] == 0
    r2 = client.post("/api/users", json=body, headers=env.sys_headers())
    assert r2.json()["code"] == 4000   # 账号已存在（业务软失败 200 + code）


def test_tenant_admin_cannot_assign_system_role(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    acc = "esc_" + uuid.uuid4().hex[:6]
    r = client.post("/api/users", json={
        "account": acc, "password": "GoodPass1", "roleIds": ["system"]},
        headers=_tok(ta, tid))
    assert r.status_code == 403   # 不可分配 system 超管


def test_tenant_admin_create_forced_into_own_tenant(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    acc = "own_" + uuid.uuid4().hex[:6]
    r = client.post("/api/users", json={
        "account": acc, "password": "GoodPass1", "roleIds": [ROLE_NORMAL],
        "tenantId": other},   # 试图指定他租户 → 应被忽略，落自己租户
        headers=_tok(ta, tid))
    assert r.status_code == 200 and r.json()["data"]["tenant_id"] == tid


# ── 启停即时失效 / 自身与最后管理员保护 ──

def test_disable_bumps_perm_ver(client, env):
    tid = env.mk_tenant()
    env.mk_user(tid, ROLE_TENANT_ADMIN)   # 保证不是最后一个管理员
    target = env.mk_user(tid, ROLE_NORMAL)
    v0 = _perm_ver(env.pg, target)
    r = client.post(f"/api/users/{target}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, target) == v0 + 1   # 即时失效


def test_cannot_disable_self(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    env.mk_user(tid, ROLE_TENANT_ADMIN)   # 另有管理员，排除"最后管理员"干扰
    r = client.post(f"/api/users/{ta}/status", json={"status": "disabled"},
                    headers=_tok(ta, tid))
    assert r.json()["code"] == 4000   # 不能停用自己


def test_last_tenant_admin_cannot_be_disabled(client, env):
    tid = env.mk_tenant()
    only_admin = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.post(f"/api/users/{only_admin}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.json()["code"] == 4000   # 最后一个管理员保护


# ── 编辑 / 重置 / 删除 ──

def test_update_roles_and_status(client, env):
    tid = env.mk_tenant()
    env.mk_user(tid, ROLE_TENANT_ADMIN)
    target = env.mk_user(tid, ROLE_NORMAL)
    v0 = _perm_ver(env.pg, target)
    r = client.put(f"/api/users/{target}", json={
        "roleIds": [ROLE_TENANT_ADMIN, ROLE_NORMAL], "status": "active"},
        headers=env.sys_headers())
    assert r.status_code == 200
    assert set(r.json()["data"]["roles"]) == {ROLE_TENANT_ADMIN, ROLE_NORMAL}
    assert _perm_ver(env.pg, target) == v0 + 1   # 角色变更即时失效


def test_reset_password(client, env):
    tid = env.mk_tenant()
    target = env.mk_user(tid, ROLE_NORMAL)
    r = client.post(f"/api/users/{target}/reset-password", json={"password": "NewPass123"},
                    headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0


def test_delete_user(client, env):
    tid = env.mk_tenant()
    target = env.mk_user(tid, ROLE_NORMAL)
    r = client.delete(f"/api/users/{target}", headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    assert env.pg.query_df("SELECT 1 FROM sys_user WHERE id=%s", [target]).empty
