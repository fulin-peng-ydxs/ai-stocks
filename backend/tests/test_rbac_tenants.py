"""多租户 RBAC 阶段三 · T9：租户管理 API（R14）。

覆盖 §6.9：require_system 守卫(403) / CRUD / 名称唯一 / 指定管理员须属该租户 / 默认租户保护
(不可删·不可停) / 删有用户租户阻止 / **停用即时踢下线**（① bump 使在线 token 下次 401；② 新登录被拒）。

真实 PG + Redis + create_app()。临时租户/用户 uuid 化并清理。停用 bump 仅影响该租户用户（不触碰
default 租户的 admin），故无需还原 admin perm_ver。
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


def _perm_ver(pg, uid):
    df = pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid])
    return int(df.iloc[0]["perm_ver"]) if not df.empty else None


@pytest.fixture()
def env(pg):
    made = {"user": [], "tenant": []}

    def mk_tenant(*, status="active"):
        tid = "tt_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,%s,%s)",
                   [tid, tid, status])
        made["tenant"].append(tid)
        return tid

    def mk_user(tid, role_code, *, password_hash=None):
        uid = "uu_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status,password_hash) "
                   "VALUES (%s,%s,%s,%s,0,'active',%s)", [uid, tid, uid, role_code, password_hash])
        pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [uid, role_code])
        made["user"].append(uid)
        return uid

    def sys_headers():
        pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
        return _tok("admin", "default", pv)

    from types import SimpleNamespace
    yield SimpleNamespace(mk_tenant=mk_tenant, mk_user=mk_user, sys_headers=sys_headers, pg=pg)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])
    # 清 API 建的租户（tenant_ 前缀）
    for tid in pg.query_df("SELECT id FROM sys_tenant WHERE id LIKE %s", ["tenant\\_%"])["id"].tolist():
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


# ── 守卫 ──

def test_list_requires_token(client):
    assert client.get("/api/tenants").status_code == 401


def test_list_forbidden_for_tenant_admin(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.get("/api/tenants", headers=_tok(ta, tid))
    assert r.status_code == 403 and r.json()["code"] == 4030


# ── CRUD / 唯一 ──

def test_create_list_update(client, env):
    name = "tenant demo " + uuid.uuid4().hex[:6]
    r = client.post("/api/tenants", json={"name": name}, headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    tid = r.json()["data"]["id"]
    assert tid == name.replace(" ", "_")
    assert r.json()["data"]["created_at"]
    # 列表能查到
    lst = client.get(f"/api/tenants?q={name}", headers=env.sys_headers()).json()["data"]
    listed = next(t for t in lst["items"] if t["id"] == tid)
    assert listed["created_at"]
    # 改名
    r2 = client.put(f"/api/tenants/{tid}", json={"name": name + "_改"}, headers=env.sys_headers())
    assert r2.json()["data"]["name"] == name + "_改"


def test_list_tenants_sort_by_name(client, env):
    marker = uuid.uuid4().hex[:6]
    for name in [f"sort {marker} c", f"sort {marker} a", f"sort {marker} b"]:
        assert client.post("/api/tenants", json={"name": name}, headers=env.sys_headers()).json()["code"] == 0
    r = client.get(f"/api/tenants?q=sort {marker}&sort_by=name&sort_order=asc", headers=env.sys_headers())
    names = [tenant["name"] for tenant in r.json()["data"]["items"]]
    assert names == sorted(names)


def test_create_tenant_known_chinese_terms(client, env):
    r = client.post("/api/tenants", json={"name": "数据中心"}, headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["id"] == "tenant_data_center"


def test_create_duplicate_name_rejected(client, env):
    name = "dup_" + uuid.uuid4().hex[:6]
    assert client.post("/api/tenants", json={"name": name},
                       headers=env.sys_headers()).json()["code"] == 0
    r2 = client.post("/api/tenants", json={"name": name}, headers=env.sys_headers())
    assert r2.json()["code"] == 4000


def test_assign_admin_must_belong_to_tenant(client, env):
    tid = env.mk_tenant()
    other = env.mk_tenant()
    outsider = env.mk_user(other, ROLE_TENANT_ADMIN)   # 属别的租户
    r = client.put(f"/api/tenants/{tid}", json={
        "name": tid, "adminUserId": outsider}, headers=env.sys_headers())
    assert r.json()["code"] == 4000
    # 属本租户的用户 → 允许
    insider = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r2 = client.put(f"/api/tenants/{tid}", json={
        "name": tid, "adminUserId": insider}, headers=env.sys_headers())
    assert r2.status_code == 200 and r2.json()["data"]["admin_user_id"] == insider


# ── 默认租户保护 / 删除前置 ──

def test_default_tenant_cannot_be_deleted(client, env):
    r = client.delete("/api/tenants/default", headers=env.sys_headers())
    assert r.status_code == 403


def test_default_tenant_cannot_be_disabled(client, env):
    r = client.post("/api/tenants/default/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 403


def test_delete_tenant_with_users_rejected(client, env):
    tid = env.mk_tenant()
    env.mk_user(tid, ROLE_NORMAL)
    r = client.delete(f"/api/tenants/{tid}", headers=env.sys_headers())
    assert r.json()["code"] == 4000   # 仍有用户


def test_delete_empty_tenant(client, env):
    tid = env.mk_tenant()
    r = client.delete(f"/api/tenants/{tid}", headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    assert env.pg.query_df("SELECT 1 FROM sys_tenant WHERE id=%s", [tid]).empty


# ── 停用即时踢下线（R14 + Codex P2）──

def test_disable_bumps_tenant_users(client, env):
    tid = env.mk_tenant()
    u1 = env.mk_user(tid, ROLE_TENANT_ADMIN)
    u2 = env.mk_user(tid, ROLE_NORMAL)
    v1, v2 = _perm_ver(env.pg, u1), _perm_ver(env.pg, u2)
    r = client.post(f"/api/tenants/{tid}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, u1) == v1 + 1 and _perm_ver(env.pg, u2) == v2 + 1


def test_disable_kicks_online_token(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)   # 有 user:list
    tok = _tok(ta, tid, 0)
    assert client.get("/api/users", headers=tok).status_code == 200   # 停用前可用
    client.post(f"/api/tenants/{tid}/status", json={"status": "disabled"},
                headers=env.sys_headers())
    # 旧 token perm_ver=0，停用 bump 后 PG=1 → 下次请求 401（已登录被踢）
    assert client.get("/api/users", headers=tok).status_code == 401


def test_login_rejected_when_tenant_disabled(client, env, monkeypatch):
    from backend.auth.security import hash_password
    from backend.services.auth_service import AuthService
    from backend.common.exceptions import AuthError
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    tid = env.mk_tenant()
    acc_uid = env.mk_user(tid, ROLE_TENANT_ADMIN, password_hash=hash_password("GoodPass1"))
    acct = env.pg.query_df("SELECT account FROM sys_user WHERE id=%s", [acc_uid]).iloc[0]["account"]
    svc = AuthService()
    ip = "ip_" + uuid.uuid4().hex[:10]
    assert svc.login(acct, "GoodPass1", ip=ip)["access_token"]   # 停用前可登录
    client.post(f"/api/tenants/{tid}/status", json={"status": "disabled"},
                headers=env.sys_headers())
    with pytest.raises(AuthError):                               # 停用后新登录被拒
        svc.login(acct, "GoodPass1", ip="ip_" + uuid.uuid4().hex[:10])
