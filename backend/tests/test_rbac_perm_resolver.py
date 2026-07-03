"""多租户 RBAC 阶段三 · T2：权限解析 + Redis 缓存 + 失效全触发点。

覆盖 §6.2：多角色并集 / system 全量 / bump 触发点（角色授权·菜单·资源·租户）→ 关联用户
perm_ver 自增 + 缓存清 / 有效权限缓存读写 / Redis 故障 fail-closed。

统一真实 PG + Redis；所有可变操作只作用于本用例创建的**临时**角色/用户/菜单（uuid 化，teardown
清理），绝不触碰真实 admin 或 default 租户既有用户。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import redis

from backend.auth import perm_resolver, session_store
from backend.common.exceptions import ServiceUnavailableError


def _perm_ver(pg, uid: str) -> int:
    return int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id=%s", [uid]).iloc[0]["perm_ver"])


@pytest.fixture()
def sandbox(pg):
    """临时 RBAC 数据工厂 + teardown 清理（顺序遵守 FK：先删用户/角色触发级联，再删资源/菜单）。

    菜单/资源类 bump 会连带失效**全部 system 用户**（含真实 admin，生产语义正确）；为不污染
    admin perm_ver / 其它测试预铸 token，teardown 还原 admin 的 perm_ver 到用例前快照。
    """
    made = {"user": [], "role": [], "menu": [], "resource": [], "tenant": []}
    admin_pv0 = _perm_ver(pg, "admin")

    def mk_role(name="role", kind="custom"):
        rid = "t_role_" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_role (id, code, name, kind, is_builtin) VALUES (%s,%s,%s,%s,FALSE)",
            [rid, rid, name, kind])
        made["role"].append(rid)
        return rid

    def mk_menu(*, parent_id=None, is_group=False):
        mid = "t_menu_" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_menu (id, parent_id, code, title, type, route_path) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            [mid, parent_id, mid, mid, "group" if is_group else "leaf",
             None if is_group else "/" + mid])
        made["menu"].append(mid)
        return mid

    def mk_resource(menu_id):
        cid = "t:res:" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_resource (id, menu_id, code, name, type) VALUES (%s,%s,%s,%s,'api')",
            [cid, menu_id, cid, cid])
        made["resource"].append(cid)
        return cid

    def mk_tenant():
        tid = "t_ten_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_tenant (id, name, status) VALUES (%s,%s,'active')", [tid, tid])
        made["tenant"].append(tid)
        return tid

    def mk_user(tenant_id="default", role_ids=()):
        uid = "t_user_" + uuid.uuid4().hex[:8]
        pg.execute(
            "INSERT INTO sys_user (id, tenant_id, account, role_code, perm_ver, status) "
            "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tenant_id, uid])
        made["user"].append(uid)
        for rid in role_ids:
            pg.execute("INSERT INTO sys_user_role (user_id, role_id) VALUES (%s,%s)", [uid, rid])
        return uid

    def grant_menu(rid, mid):
        pg.execute("INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s,%s)", [rid, mid])

    def grant_resource(rid, cid):
        pg.execute("INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s,%s)", [rid, cid])

    yield SimpleNamespace(
        mk_role=mk_role, mk_menu=mk_menu, mk_resource=mk_resource, mk_tenant=mk_tenant,
        mk_user=mk_user, grant_menu=grant_menu, grant_resource=grant_resource)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])       # 级联 sys_user_role
    for rid in made["role"]:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])       # 级联 role_menu/role_resource
    for cid in made["resource"]:
        pg.execute("DELETE FROM sys_resource WHERE id=%s", [cid])
    for mid in reversed(made["menu"]):   # 反序：先删子后删父，避开 parent_id FK RESTRICT
        pg.execute("DELETE FROM sys_menu WHERE id=%s", [mid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])
    pg.execute("UPDATE sys_user SET perm_ver=%s WHERE id='admin'", [admin_pv0])   # 还原，防污染


# ── 解析 ──────────────────────────────────────────────────────────────────────

def test_resolve_multi_role_union(pg, sandbox):
    m1, m2 = sandbox.mk_menu(), sandbox.mk_menu()
    r_a, r_b = sandbox.mk_role("A"), sandbox.mk_role("B")
    sandbox.grant_menu(r_a, m1)
    sandbox.grant_menu(r_b, m2)
    res_b = sandbox.mk_resource(m2)
    sandbox.grant_resource(r_b, res_b)
    uid = sandbox.mk_user(role_ids=[r_a, r_b])

    p = perm_resolver.resolve(uid)
    assert p["is_system"] is False
    assert m1 in p["menus"] and m2 in p["menus"]
    assert res_b in p["resources"]
    assert set(p["roles"]) == {r_a, r_b}


def test_resolve_system_full(pg, sandbox):
    r_sys = sandbox.mk_role("sysrole", kind="system")
    uid = sandbox.mk_user(role_ids=[r_sys])
    p = perm_resolver.resolve(uid)
    assert p["is_system"] is True
    # 全量：含 seeded 内置菜单/功能码，不受 role_menu 授权约束
    assert "/screen" in p["menus"]
    assert "user:list" in p["resources"]


def test_resolve_no_role_empty(pg, sandbox):
    uid = sandbox.mk_user()
    p = perm_resolver.resolve(uid)
    assert p["is_system"] is False
    assert p["menus"] == [] and p["resources"] == []
    assert p["roles"] == []


def test_resolve_reads_perm_ver(pg, sandbox):
    uid = sandbox.mk_user()
    pg.execute("UPDATE sys_user SET perm_ver=7 WHERE id=%s", [uid])
    assert perm_resolver.resolve(uid)["perm_ver"] == 7


# ── 缓存 ──────────────────────────────────────────────────────────────────────

def test_cache_perms_roundtrip(redis_cli):
    uid = "t_cache_" + uuid.uuid4().hex[:8]
    payload = {"roles": ["normal"], "is_system": False, "menus": ["/screen"], "resources": [], "perm_ver": 3}
    session_store.cache_perms(uid, payload, ttl_seconds=60)
    assert session_store.get_cached_perms(uid) == payload
    session_store.clear_perms(uid)
    assert session_store.get_cached_perms(uid) is None


def test_cache_perms_fail_closed(monkeypatch):
    """Redis 故障 → cache/get/clear 全部 fail-closed 抛 ServiceUnavailableError(503)。"""
    class Boom:
        def set(self, *a, **k): raise redis.RedisError("down")
        def get(self, *a, **k): raise redis.RedisError("down")
        def delete(self, *a, **k): raise redis.RedisError("down")

    monkeypatch.setattr(session_store, "_r", lambda: Boom())
    with pytest.raises(ServiceUnavailableError):
        session_store.cache_perms("u", {"x": 1})
    with pytest.raises(ServiceUnavailableError):
        session_store.get_cached_perms("u")
    with pytest.raises(ServiceUnavailableError):
        session_store.clear_perms("u")


# ── 失效触发点 ────────────────────────────────────────────────────────────────

def test_bump_and_invalidate(pg, redis_cli, sandbox):
    uid = sandbox.mk_user()
    pg.execute("UPDATE sys_user SET perm_ver=5 WHERE id=%s", [uid])
    session_store.cache_perms(uid, {"x": 1})
    session_store.cache_perm_ver(uid, 5)

    n = perm_resolver.bump_and_invalidate([uid, uid, ""])   # 去重去空
    assert n == 1
    assert _perm_ver(pg, uid) == 6
    assert session_store.get_cached_perms(uid) is None
    assert session_store.get_cached_perm_ver(uid) is None


def test_bump_users_of_roles(pg, redis_cli, sandbox):
    r = sandbox.mk_role("R")
    u1 = sandbox.mk_user(role_ids=[r])
    u2 = sandbox.mk_user(role_ids=[r])
    v1, v2 = _perm_ver(pg, u1), _perm_ver(pg, u2)
    n = perm_resolver.bump_users_of_roles([r])
    assert n == 2
    assert _perm_ver(pg, u1) == v1 + 1
    assert _perm_ver(pg, u2) == v2 + 1


def test_bump_users_of_menu_includes_system(pg, redis_cli, sandbox):
    """菜单变更 → 引用它的角色的用户 + 全部 system 用户（超管看全量，结构变更也影响）。"""
    m = sandbox.mk_menu()
    r = sandbox.mk_role("R")
    sandbox.grant_menu(r, m)
    u_norm = sandbox.mk_user(role_ids=[r])
    r_sys = sandbox.mk_role("S", kind="system")
    u_sys = sandbox.mk_user(role_ids=[r_sys])
    v_norm, v_sys = _perm_ver(pg, u_norm), _perm_ver(pg, u_sys)

    perm_resolver.bump_users_of_menu(m)
    assert _perm_ver(pg, u_norm) == v_norm + 1
    assert _perm_ver(pg, u_sys) == v_sys + 1


def test_bump_users_of_menu_covers_subtree(pg, redis_cli, sandbox):
    """移动/隐藏父分组 → 只授到子孙叶子的用户也被 bump（Codex 第二轮 P2-c：按「当前节点+子树」汇总）。

    构造：父分组 ⊃ 子叶子；角色**只授子叶子、未授父分组**。对父节点 bump 时，旧实现只查直接引用父
    节点的角色 → 漏掉该用户；修复后经递归 CTE 覆盖子树，用户被正确失效。
    """
    parent = sandbox.mk_menu(is_group=True)
    child = sandbox.mk_menu(parent_id=parent)
    r = sandbox.mk_role("R")
    sandbox.grant_menu(r, child)               # 只授子叶子
    u = sandbox.mk_user(role_ids=[r])
    v = _perm_ver(pg, u)
    perm_resolver.bump_users_of_menu(parent)   # 对父分组失效
    assert _perm_ver(pg, u) == v + 1           # 子树用户也被 bump


def test_bump_second_clear_closes_backfill_race(pg, redis_cli, sandbox, monkeypatch):
    """延迟双删：模拟①清缓存后、②自增 PG 期间并发请求回填了旧值，③二次清理须抹掉（Codex 第二轮 P1）。"""
    from backend.storage.pg_client import get_pg_client

    uid = sandbox.mk_user()
    pg.execute("UPDATE sys_user SET perm_ver=5 WHERE id=%s", [uid])
    client = get_pg_client()
    orig_execute = client.execute

    def execute_with_backfill(sql, params=None):
        result = orig_execute(sql, params)
        # 模拟并发读在 PG 自增窗口内回查到旧 perm_ver 并回填 Redis
        session_store.cache_perms(uid, {"stale": True})
        session_store.cache_perm_ver(uid, 5)
        return result

    monkeypatch.setattr(client, "execute", execute_with_backfill)
    perm_resolver.bump_and_invalidate([uid], client)
    # ③ 二次清理抹掉窗口内回填的旧值 → 下次读必回查已自增 PG（旧 token 失配 401）
    assert session_store.get_cached_perms(uid) is None
    assert session_store.get_cached_perm_ver(uid) is None
    assert _perm_ver(pg, uid) == 6


def test_bump_users_of_resource(pg, redis_cli, sandbox):
    m = sandbox.mk_menu()
    res = sandbox.mk_resource(m)
    r = sandbox.mk_role("R")
    sandbox.grant_resource(r, res)
    u = sandbox.mk_user(role_ids=[r])
    v = _perm_ver(pg, u)
    perm_resolver.bump_users_of_resource(res)
    assert _perm_ver(pg, u) == v + 1


def test_bump_users_of_tenant(pg, redis_cli, sandbox):
    tid = sandbox.mk_tenant()
    u1 = sandbox.mk_user(tenant_id=tid)
    u2 = sandbox.mk_user(tenant_id=tid)
    v1, v2 = _perm_ver(pg, u1), _perm_ver(pg, u2)
    n = perm_resolver.bump_users_of_tenant(tid)
    assert n == 2
    assert _perm_ver(pg, u1) == v1 + 1
    assert _perm_ver(pg, u2) == v2 + 1
