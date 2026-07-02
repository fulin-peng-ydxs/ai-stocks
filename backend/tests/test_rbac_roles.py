"""多租户 RBAC 阶段三 · T6：角色管理 API（R11）。

覆盖 §6.6：require_system 守卫(403) / assignable 分流(system 含 custom、tenant_admin 仅系统预设) /
自定义角色 CRUD / 唯一 / 内置保护(不可删) / 超管锁定(不可改/不可授) / 授权保存(全选/清空) /
system-only 码不可授 / 授权后关联用户 perm_ver 自增(即时失效)。

真实 PG + Redis + create_app()。所有临时租户/用户/角色 uuid 化并 teardown 清理；acting token
只用 admin(system) 或本用例新建的 tenant_admin。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.constants import ROLE_NORMAL, ROLE_SYSTEM, ROLE_TENANT_ADMIN

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
    """临时租户/用户/自定义角色工厂 + teardown 清理。"""
    made = {"user": [], "tenant": [], "role": []}

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

    def mk_role(*, code=None):
        """直接落一个自定义角色（绕过 API，供 assignable/授权用例准备数据）。"""
        rid = "rr_" + uuid.uuid4().hex[:8]
        code = code or ("c_" + uuid.uuid4().hex[:6])
        pg.execute(
            "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
            "VALUES (%s,%s,%s,'custom',FALSE,FALSE)", [rid, code, code])
        made["role"].append(rid)
        return rid

    def sys_headers():
        pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
        return _tok("admin", "default", pv)

    from types import SimpleNamespace
    yield SimpleNamespace(mk_tenant=mk_tenant, mk_user=mk_user, mk_role=mk_role,
                          sys_headers=sys_headers, pg=pg)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_user WHERE tenant_id=%s", [tid])
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])
    for rid in made["role"]:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])   # role_menu/role_resource FK CASCADE


def _perm_ver(pg, uid):
    df = pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid])
    return int(df.iloc[0]["perm_ver"]) if not df.empty else None


def _menu_id(pg, code):
    return pg.query_df("SELECT id FROM sys_menu WHERE code=%s", [code]).iloc[0]["id"]


def _res_id(pg, code):
    return pg.query_df("SELECT id FROM sys_resource WHERE code=%s", [code]).iloc[0]["id"]


# ── 守卫 ──

def test_list_requires_token(client):
    assert client.get("/api/roles").status_code == 401


def test_list_forbidden_for_tenant_admin(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)   # 非 system → 角色管理 403
    r = client.get("/api/roles", headers=_tok(ta, tid))
    assert r.status_code == 403 and r.json()["code"] == 4030


def test_list_allowed_for_system(client, env):
    r = client.get("/api/roles", headers=env.sys_headers())
    assert r.status_code == 200
    codes = {x["code"] for x in r.json()["data"]}
    assert {ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL} <= codes   # 至少四内置


# ── assignable 分流（Codex P1 + 二轮复核）──

def test_assignable_system_includes_custom(client, env):
    custom = env.mk_role()
    r = client.get("/api/roles/assignable", headers=env.sys_headers())
    assert r.status_code == 200
    data = r.json()["data"]
    ids = {x["id"] for x in data}
    assert custom in ids                                   # system 可分配自建 custom
    assert ROLE_SYSTEM not in {x["code"] for x in data}    # 但永不含 system 超管


def test_assignable_tenant_admin_preset_only(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    custom = env.mk_role()
    r = client.get("/api/roles/assignable", headers=_tok(ta, tid))
    assert r.status_code == 200
    data = r.json()["data"]
    ids = {x["id"] for x in data}
    kinds = {x["kind"] for x in data}
    assert custom not in ids                               # 不含任何 custom
    assert ROLE_SYSTEM not in {x["code"] for x in data}    # 不含 system
    assert kinds <= {"tenant_admin", "normal", "paid"}     # 仅系统预设


# ── CRUD ──

def test_create_update_delete_custom_role(client, env):
    code = "role_" + uuid.uuid4().hex[:6]
    r = client.post("/api/roles", json={"code": code, "name": "自定义A", "description": "d"},
                    headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    rid = r.json()["data"]["id"]
    # 编辑
    r2 = client.put(f"/api/roles/{rid}", json={"name": "自定义B", "description": "d2"},
                    headers=env.sys_headers())
    assert r2.json()["data"]["name"] == "自定义B"
    # 删除
    r3 = client.delete(f"/api/roles/{rid}", headers=env.sys_headers())
    assert r3.status_code == 200 and r3.json()["code"] == 0
    assert env.pg.query_df("SELECT 1 FROM sys_role WHERE id=%s", [rid]).empty


def test_create_duplicate_code_rejected(client, env):
    code = "dup_" + uuid.uuid4().hex[:6]
    body = {"code": code, "name": "x"}
    r1 = client.post("/api/roles", json=body, headers=env.sys_headers())
    assert r1.json()["code"] == 0
    try:
        r2 = client.post("/api/roles", json=body, headers=env.sys_headers())
        assert r2.json()["code"] == 4000   # 标识已存在（业务软失败 200 + code）
    finally:
        env.pg.execute("DELETE FROM sys_role WHERE code=%s", [code])   # 清理 API 建的角色


def test_create_builtin_code_rejected(client, env):
    r = client.post("/api/roles", json={"code": ROLE_NORMAL, "name": "撞内置"},
                    headers=env.sys_headers())
    assert r.json()["code"] == 4000


# ── 内置保护 / 超管锁定 ──

def test_builtin_role_cannot_be_deleted(client, env):
    r = client.delete(f"/api/roles/{ROLE_NORMAL}", headers=env.sys_headers())
    assert r.status_code == 403   # 内置不可删

def test_locked_system_role_cannot_be_updated(client, env):
    r = client.put(f"/api/roles/{ROLE_SYSTEM}", json={"name": "改超管"},
                   headers=env.sys_headers())
    assert r.status_code == 403   # 超管锁定不可改

def test_locked_system_role_grants_cannot_be_changed(client, env):
    r = client.put(f"/api/roles/{ROLE_SYSTEM}/perms",
                   json={"menuIds": [], "resourceIds": []}, headers=env.sys_headers())
    assert r.status_code == 403   # 超管授权锁定


def test_delete_role_with_members_rejected(client, env):
    rid = env.mk_role()
    tid = env.mk_tenant()
    env.mk_user(tid, "normal")   # 建个用户占位
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) "
                   "SELECT id,%s FROM sys_user WHERE tenant_id=%s LIMIT 1", [rid, tid])
    r = client.delete(f"/api/roles/{rid}", headers=env.sys_headers())
    assert r.json()["code"] == 4000   # 仍有用户，不能删（业务软失败）


# ── 授权保存 / system-only / 即时失效 ──

def test_set_grants_save_and_readback(client, env):
    rid = env.mk_role()
    m1 = _menu_id(env.pg, "/screen")
    r1 = _res_id(env.pg, "user:list")   # 属 /system/users（visible=login），可授
    r = client.put(f"/api/roles/{rid}/perms",
                   json={"menuIds": [m1], "resourceIds": [r1]}, headers=env.sys_headers())
    assert r.status_code == 200
    got = client.get(f"/api/roles/{rid}/perms", headers=env.sys_headers()).json()["data"]
    assert got["menu_ids"] == [m1] and got["resource_ids"] == [r1]
    # 清空
    client.put(f"/api/roles/{rid}/perms", json={"menuIds": [], "resourceIds": []},
               headers=env.sys_headers())
    got2 = client.get(f"/api/roles/{rid}/perms", headers=env.sys_headers()).json()["data"]
    assert got2["menu_ids"] == [] and got2["resource_ids"] == []


def test_grant_system_only_code_rejected(client, env):
    rid = env.mk_role()
    sys_only = _res_id(env.pg, "role:create")   # 属 /system/roles（visible=system），不可授
    r = client.put(f"/api/roles/{rid}/perms",
                   json={"menuIds": [], "resourceIds": [sys_only]}, headers=env.sys_headers())
    assert r.status_code == 403   # system-only 码不可授予非 system 角色


def test_grant_bumps_members_perm_ver(client, env):
    rid = env.mk_role()
    tid = env.mk_tenant()
    holder = env.mk_user(tid, "normal")
    env.pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [holder, rid])
    v0 = _perm_ver(env.pg, holder)
    r1 = _res_id(env.pg, "user:list")
    r = client.put(f"/api/roles/{rid}/perms",
                   json={"menuIds": [], "resourceIds": [r1]}, headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, holder) == v0 + 1   # 授权变更 → 关联用户即时失效
