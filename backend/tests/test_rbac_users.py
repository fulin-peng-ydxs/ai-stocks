"""多租户 RBAC 阶段三 · T5：用户管理 API（R10）。

覆盖 §6.5：精确码守卫(403) / 域隔离(system 全局、tenant_admin 本租户) / 多角色 CRUD /
唯一冲突 / 启停即时失效(perm_ver bump) / 自身保护 / 可分配角色越权拦截。

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


# ── 逻辑删除（软删）──

def test_soft_deleted_user_excluded_and_token_rejected(client, env):
    """软删用户后:不在列表、在线 token 被 claims_from_bearer 实时拒、行仍在(打标记)。"""
    tid = env.mk_tenant()
    normal = env.mk_user(tid, ROLE_NORMAL)
    ntok = _tok(normal, tid)
    # 删前:baseline 共享读可用
    assert client.get("/api/data/trade-dates", headers=ntok).status_code == 200
    # 软删
    r = client.delete(f"/api/users/{normal}", headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    # 行保留 + deleted_at 标记
    assert not env.pg.query_df(
        "SELECT 1 FROM sys_user WHERE id=%s AND deleted_at IS NOT NULL", [normal]).empty
    # 不在管理列表
    listed = client.get("/api/users", headers=env.sys_headers()).json()["data"]["items"]
    assert normal not in {u["id"] for u in listed}
    # 在线 token 被拒（每请求 claims_from_bearer 校验 deleted_at）
    assert client.get("/api/data/trade-dates", headers=ntok).status_code == 401


def test_soft_deleted_account_cannot_be_recreated(client, env):
    """不允许重建:软删后同名 account 仍占用(查重命中已删行)。"""
    from backend.storage.user_repository import UserRepository

    tid = env.mk_tenant()
    normal = env.mk_user(tid, ROLE_NORMAL)  # account == normal(=uid)
    client.delete(f"/api/users/{normal}", headers=env.sys_headers())
    # 查重口径看全量:已删账号名仍能查到 → 重建会被拦/撞唯一约束
    assert UserRepository(env.pg).get_by_account(normal) is not None


def test_system_user_can_delete_other_system_user(client, env):
    """system 可删除其他 system 用户；唯一硬限制是不能删除自己。"""
    from backend.auth.constants import ROLE_SYSTEM

    actor = env.mk_user("default", ROLE_SYSTEM)
    target = env.mk_user("default", ROLE_SYSTEM)
    r = client.delete(f"/api/users/{target}", headers=_tok(actor, "default"))
    assert r.status_code == 200 and r.json()["code"] == 0
    assert not env.pg.query_df(
        "SELECT 1 FROM sys_user WHERE id=%s AND deleted_at IS NOT NULL", [target]).empty


def test_soft_delete_user_frees_tenant_deletion(client, env):
    """软删租户内用户后 user_count=0,租户可删(软删)。"""
    tid = env.mk_tenant()
    u = env.mk_user(tid, ROLE_NORMAL)
    client.delete(f"/api/users/{u}", headers=env.sys_headers())
    r = client.delete(f"/api/tenants/{tid}", headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    assert not env.pg.query_df(
        "SELECT 1 FROM sys_tenant WHERE id=%s AND deleted_at IS NOT NULL", [tid]).empty


def test_cannot_create_user_in_soft_deleted_tenant(client, env):
    """软删租户视为不存在,system 也不能继续往隐藏租户下挂新用户。"""
    tid = env.mk_tenant()
    assert client.delete(
        f"/api/tenants/{tid}", headers=env.sys_headers()).json()["code"] == 0
    account = "soft_deleted_tenant_" + uuid.uuid4().hex[:8]
    r = client.post(
        "/api/users",
        json={
            "account": account,
            "password": "GoodPass123",
            "roleIds": [ROLE_NORMAL],
            "tenantId": tid,
        },
        headers=env.sys_headers(),
    )
    assert r.json()["code"] == 4000
    assert env.pg.query_df("SELECT 1 FROM sys_user WHERE account=%s", [account]).empty


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


def test_tenant_admin_user_list_includes_custom_role_name(client, env):
    """租户管理员不能分配自定义角色，但查看已有成员时仍应得到角色名称而非只能展示编码。"""
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    member = env.mk_user(tid, ROLE_NORMAL)
    role_id = "role_" + uuid.uuid4().hex[:8]
    role_name = "租户复核员"
    env.pg.execute(
        "INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
        "VALUES (%s,%s,%s,'custom',FALSE,FALSE)",
        [role_id, role_id, role_name],
    )
    try:
        env.pg.execute(
            "INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [member, role_id])
        items = client.get("/api/users", headers=_tok(ta, tid)).json()["data"]["items"]
        row = next(item for item in items if item["id"] == member)
        assert row["role_names"][role_id] == role_name
    finally:
        env.pg.execute("DELETE FROM sys_user_role WHERE user_id=%s AND role_id=%s", [member, role_id])
        env.pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])


def test_list_users_sort_by_account(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    env.mk_user(tid, ROLE_NORMAL)
    env.mk_user(tid, ROLE_NORMAL)
    r = client.get("/api/users?sort_by=account&sort_order=asc", headers=_tok(ta, tid))
    accounts = [u["account"] for u in r.json()["data"]["items"]]
    assert accounts == sorted(accounts)


def test_tenant_admin_cannot_touch_other_tenant_user(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    victim = env.mk_user(other, ROLE_NORMAL)
    r = client.post(f"/api/users/{victim}/status", json={"status": "disabled"},
                    headers=_tok(ta, tid))
    assert r.json()["code"] == 4004   # 跨租户视为不存在（业务软失败 200 + code）


# ── T16 多账号交叉核查：租户管理员对他租户用户的**每个变更动作**都被 _load_in_scope 拦成 404 ──
# （status 已由上例覆盖；此处锁 update/reset-password/delete 三个动词，防未来重构漏挂域闸门）

def test_tenant_admin_cannot_update_other_tenant_user(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    victim = env.mk_user(other, ROLE_NORMAL)
    r = client.put(f"/api/users/{victim}", json={"roleIds": [ROLE_NORMAL], "status": "active"},
                   headers=_tok(ta, tid))
    assert r.json()["code"] == 4004   # 跨租户编辑视为不存在
    assert env.pg.query_df("SELECT status FROM sys_user WHERE id=%s", [victim]).iloc[0]["status"] == "active"


def test_tenant_admin_cannot_reset_other_tenant_user(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    victim = env.mk_user(other, ROLE_NORMAL)
    r = client.post(f"/api/users/{victim}/reset-password", json={"password": "GoodPass1"},
                    headers=_tok(ta, tid))
    assert r.json()["code"] == 4004   # 跨租户重置密码视为不存在


def test_tenant_admin_cannot_delete_other_tenant_user(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    other = env.mk_tenant()
    victim = env.mk_user(other, ROLE_NORMAL)
    r = client.delete(f"/api/users/{victim}", headers=_tok(ta, tid))
    assert r.json()["code"] == 4004   # 跨租户删除视为不存在
    assert not env.pg.query_df("SELECT 1 FROM sys_user WHERE id=%s", [victim]).empty   # 未被删


def test_tenant_admin_cannot_escalate_role_via_update(client, env):
    """租户管理员编辑本租户用户时不能把角色越权提升为 system（走 _validate_roles → 403）。"""
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    member = env.mk_user(tid, ROLE_NORMAL)
    r = client.put(f"/api/users/{member}", json={"roleIds": ["system"], "status": "active"},
                   headers=_tok(ta, tid))
    assert r.status_code == 403   # 不可分配 system 超管


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


def test_system_can_create_another_system_admin(client, env):
    from backend.auth.constants import ROLE_SYSTEM

    tid = env.mk_tenant()
    acc = "newsys_" + uuid.uuid4().hex[:6]
    r = client.post(
        "/api/users",
        json={
            "account": acc,
            "password": "GoodPass1",
            "roleIds": [ROLE_SYSTEM],
            "tenantId": tid,
        },
        headers=env.sys_headers(),
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    created = r.json()["data"]
    assert created["role_code"] == ROLE_SYSTEM
    assert created["roles"] == [ROLE_SYSTEM]


@pytest.mark.parametrize("action", ["update", "status", "reset", "delete"])
def test_tenant_admin_cannot_operate_system_user_in_own_tenant(client, env, action):
    from backend.auth.constants import ROLE_SYSTEM

    tid = env.mk_tenant()
    tenant_admin = env.mk_user(tid, ROLE_TENANT_ADMIN)
    target = env.mk_user(tid, ROLE_SYSTEM)
    headers = _tok(tenant_admin, tid)

    if action == "update":
        r = client.put(
            f"/api/users/{target}",
            json={"email": None, "roleIds": [ROLE_NORMAL], "status": "active"},
            headers=headers,
        )
    elif action == "status":
        r = client.post(
            f"/api/users/{target}/status",
            json={"status": "disabled"},
            headers=headers,
        )
    elif action == "reset":
        r = client.post(
            f"/api/users/{target}/reset-password",
            json={"password": "GoodPass1"},
            headers=headers,
        )
    else:
        r = client.delete(f"/api/users/{target}", headers=headers)

    assert r.status_code == 403
    row = env.pg.query_df(
        "SELECT status, deleted_at FROM sys_user WHERE id=%s",
        [target],
    ).iloc[0]
    assert row["status"] == "active"
    assert row["deleted_at"] is None


def test_system_admin_cannot_remove_own_system_role(client, env):
    r = client.put(
        "/api/users/admin",
        json={"email": None, "roleIds": [ROLE_NORMAL], "status": "active"},
        headers=env.sys_headers(),
    )
    assert r.json()["code"] == 4000
    roles = set(env.pg.query_df(
        "SELECT role_id FROM sys_user_role WHERE user_id='admin'",
    )["role_id"])
    assert "system" in roles


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


# ── 启停即时失效 / 自身保护 ──

def test_disable_bumps_perm_ver(client, env):
    tid = env.mk_tenant()
    target = env.mk_user(tid, ROLE_NORMAL)
    v0 = _perm_ver(env.pg, target)
    r = client.post(f"/api/users/{target}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, target) == v0 + 1   # 即时失效


def test_cannot_disable_self(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.post(f"/api/users/{ta}/status", json={"status": "disabled"},
                    headers=_tok(ta, tid))
    assert r.json()["code"] == 4000   # 不能停用自己


def test_system_admin_cannot_disable_self(client, env):
    r = client.post("/api/users/admin/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.json()["code"] == 4000
    assert env.pg.query_df(
        "SELECT status FROM sys_user WHERE id='admin'").iloc[0]["status"] == "active"


def test_cannot_disable_self_via_update_user(client, env):
    tid = env.mk_tenant()
    ta = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.put(
        f"/api/users/{ta}",
        json={"email": None, "roleIds": [ROLE_NORMAL], "status": "disabled"},
        headers=_tok(ta, tid),
    )
    assert r.json()["code"] == 4000
    assert env.pg.query_df(
        "SELECT status FROM sys_user WHERE id=%s", [ta]).iloc[0]["status"] == "active"


def test_system_admin_cannot_disable_self_via_update_user(client, env):
    r = client.put(
        "/api/users/admin",
        json={"email": None, "roleIds": [ROLE_NORMAL], "status": "disabled"},
        headers=env.sys_headers(),
    )
    assert r.json()["code"] == 4000
    assert env.pg.query_df(
        "SELECT status FROM sys_user WHERE id='admin'").iloc[0]["status"] == "active"


def test_last_tenant_admin_can_be_disabled(client, env):
    tid = env.mk_tenant()
    only_admin = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.post(f"/api/users/{only_admin}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    assert env.pg.query_df("SELECT status FROM sys_user WHERE id=%s",
                           [only_admin]).iloc[0]["status"] == "disabled"


def test_last_tenant_admin_can_be_downgraded(client, env):
    tid = env.mk_tenant()
    only_admin = env.mk_user(tid, ROLE_TENANT_ADMIN)
    r = client.put(f"/api/users/{only_admin}",
                   json={"email": None, "roleIds": [ROLE_NORMAL], "status": "active"},
                   headers=env.sys_headers())
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["roles"] == [ROLE_NORMAL]


def test_disable_normal_user_not_blocked_when_tenant_has_no_admin(client, env):
    # 租户是否还有 tenant_admin 不影响普通用户停用。
    tid = env.mk_tenant()
    normal = env.mk_user(tid, ROLE_NORMAL)   # 该租户无任何 tenant_admin
    r = client.put(f"/api/users/{normal}",
                   json={"email": None, "roleIds": [ROLE_NORMAL], "status": "disabled"},
                   headers=env.sys_headers())
    assert r.json()["code"] == 0
    assert env.pg.query_df("SELECT status FROM sys_user WHERE id=%s",
                           [normal]).iloc[0]["status"] == "disabled"


def test_list_null_last_login_not_serialized_as_nat(client, env):
    # 回归（T11 验证发现）：混合结果集里 SQL NULL 的 last_login_at 会被 pandas 提升为 NaT（列 dtype
    # =datetime64），早期 _iso 直接 isoformat() 输出字符串 'NaT' 泄漏前端。断言 null → JSON null。
    tid = env.mk_tenant()
    logged = env.mk_user(tid, ROLE_NORMAL)     # 有登录时间
    never = env.mk_user(tid, ROLE_NORMAL)      # 从未登录（null）
    env.pg.execute("UPDATE sys_user SET last_login_at=now() WHERE id=%s", [logged])
    r = client.get(f"/api/users?tenant_id={tid}", headers=env.sys_headers())
    items = {i["account"]: i for i in r.json()["data"]["items"]}
    assert items[never]["last_login_at"] is None       # 不是 'NaT'
    assert items[logged]["last_login_at"] is not None


def test_create_in_nonexistent_tenant_rejected(client, env):
    # P2-b：system 指定不存在的租户 → 拒（防孤儿用户）
    r = client.post("/api/users", json={
        "account": "orphan_" + uuid.uuid4().hex[:6], "password": "GoodPass1",
        "roleIds": [ROLE_NORMAL], "tenantId": "ghost_tenant"}, headers=env.sys_headers())
    assert r.json()["code"] == 4000


def test_create_in_disabled_tenant_rejected(client, env):
    # P2-b：目标租户已停用 → 拒（新建用户也登录不了，破坏关联租户闭环）
    tid = env.mk_tenant()
    env.pg.execute("UPDATE sys_tenant SET status='disabled' WHERE id=%s", [tid])
    r = client.post("/api/users", json={
        "account": "u_" + uuid.uuid4().hex[:6], "password": "GoodPass1",
        "roleIds": [ROLE_NORMAL], "tenantId": tid}, headers=env.sys_headers())
    assert r.json()["code"] == 4000


def test_business_write_and_bump_commit_atomically(client, env, monkeypatch):
    # Codex 五轮 P1：业务写入 + perm_ver 自增在同一 PG 事务。事务提交前，另一连接(env.pg)看不到任何变化
    # （status 仍旧、perm_ver 仍旧）；提交后两者一起可见——即无"业务已变、版本未进/版本已进、业务未变"窗口。
    from backend.storage.user_repository import UserRepository
    tid = env.mk_tenant()
    target = env.mk_user(tid, ROLE_NORMAL)
    v0 = _perm_ver(env.pg, target)

    seen: dict[str, object] = {}
    orig = UserRepository.set_status

    def spy(self, user_id, status, *, conn=None):
        # 在事务内、业务 UPDATE 之后立即用独立连接读取：应仍看不到提交（status/perm_ver 都还是旧值）
        row = env.pg.query_df("SELECT status, perm_ver FROM sys_user WHERE id=%s", [user_id]).iloc[0]
        seen["status"], seen["pv"] = row["status"], int(row["perm_ver"])
        return orig(self, user_id, status, conn=conn)
    monkeypatch.setattr(UserRepository, "set_status", spy)

    r = client.post(f"/api/users/{target}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200
    assert seen["status"] == "active" and seen["pv"] == v0   # 事务内对外不可见（原子性）
    assert _perm_ver(env.pg, target) == v0 + 1               # 提交后 perm_ver 与业务一起前进


def test_stale_redis_perm_ver_cannot_bypass_authoritative_pg(client, env):
    # Codex 四轮 P1：即便"权限失效后 Redis 清理失败 + 并发回填了旧 perm_ver/perms"，旧 token 也必须被拒——
    # 鉴权闸门以 PG 为权威、每请求校验 perm_ver（不信任陈旧 auth:pv）。此处显式注入陈旧 Redis 缓存模拟该竞态。
    from backend.auth import session_store
    from backend.auth.constants import ROLE_NORMAL as _NORMAL
    tid = env.mk_tenant()
    target = env.mk_user(tid, _NORMAL)
    old = _tok(target, tid, 0)                   # 旧 token：perm_ver=0

    # 基线：token 有效（无 user:list 权限得 403 而非 401 → 证明 token 本身能过鉴权闸门）
    assert client.get("/api/users", headers=old).status_code == 403

    # 触发权限变更：PG perm_ver 自增到 1（业务已提交）
    r = client.put(f"/api/users/{target}", json={"roleIds": [_NORMAL], "status": "active"},
                   headers=env.sys_headers())
    assert r.status_code == 200 and _perm_ver(env.pg, target) == 1

    # 模拟"写后清理失败 + 并发回填"：Redis 残留旧 perm_ver=0 / 旧 perms
    session_store.cache_perm_ver(target, 0)
    session_store.cache_perms(target, {"roles": [_NORMAL], "is_system": False,
                                       "menus": [], "resources": [], "perm_ver": 0})

    # 旧 token 再次请求：必须 401（PG perm_ver=1 ≠ token 0），不因陈旧 Redis auth:pv 而 fail-open
    assert client.get("/api/users", headers=old).status_code == 401


def test_redis_clear_failure_does_not_block_authoritative_invalidation(client, env, monkeypatch):
    # Codex 五轮 P1：业务写入 + perm_ver 自增在**同一 PG 事务**原子提交，Redis 清缓存为 best-effort。
    # 故"写后 Redis 清理失败"不再阻断权威失效：状态照常提交、perm_ver 照常自增、旧 token 照常 401。
    # （对比旧实现：先清 Redis、清失败即 503 且 PG 不 bump → 业务已落库却没失效，是 fail-open。）
    from backend.auth import session_store
    from backend.common.exceptions import ServiceUnavailableError
    tid = env.mk_tenant()
    target = env.mk_user(tid, ROLE_NORMAL)
    v0 = _perm_ver(env.pg, target)
    old = _tok(target, tid, v0)

    def boom(_uid):
        raise ServiceUnavailableError("Redis down")
    monkeypatch.setattr(session_store, "clear_perms", boom)

    r = client.post(f"/api/users/{target}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200                     # best-effort 清理失败不影响操作成功
    assert env.pg.query_df("SELECT status FROM sys_user WHERE id=%s",
                           [target]).iloc[0]["status"] == "disabled"   # 业务已原子提交
    assert _perm_ver(env.pg, target) == v0 + 1      # 权威 perm_ver 已前进（不被 Redis 阻断）
    assert client.get("/api/users", headers=old).status_code == 401   # 旧 token 被 PG 权威闸门拒


def test_tenant_disable_invalidates_online_token_even_if_redis_fails(client, env, monkeypatch):
    # Codex 五轮 P1（租户覆盖）：停用 + 成员 perm_ver 自增同事务原子提交；Redis 清理失败也不影响——
    # 停租用户在线 token 被拒（perm_ver 失配 + 租户 status 实时校验双保险）。
    from backend.auth import session_store
    from backend.auth.constants import ROLE_NORMAL as _NORMAL
    from backend.common.exceptions import ServiceUnavailableError
    tid = env.mk_tenant()
    member = env.mk_user(tid, _NORMAL)
    old = _tok(member, tid, 0)
    assert client.get("/api/users", headers=old).status_code == 403   # 基线：token 有效

    def boom(_uid):
        raise ServiceUnavailableError("Redis down")
    monkeypatch.setattr(session_store, "clear_perms", boom)

    r = client.post(f"/api/tenants/{tid}/status", json={"status": "disabled"},
                    headers=env.sys_headers())
    assert r.status_code == 200
    assert _perm_ver(env.pg, member) == 1                             # 成员 perm_ver 原子自增
    assert client.get("/api/users", headers=old).status_code == 401   # 停租在线 token 被拒


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
    # 逻辑删除:行保留并打 deleted_at 标记,而非物理消失
    assert not env.pg.query_df(
        "SELECT 1 FROM sys_user WHERE id=%s AND deleted_at IS NOT NULL", [target]).empty


def test_system_admin_can_delete_users_across_tenants(client, env):
    """system 可删除任意租户非本人用户；删除仍是软删。"""
    default_user = env.mk_user("default", ROLE_NORMAL)
    tid = env.mk_tenant()
    tenant_user = env.mk_user(tid, ROLE_NORMAL)
    last_tenant_admin = env.mk_user(tid, ROLE_TENANT_ADMIN)

    for uid in (default_user, tenant_user, last_tenant_admin):
        r = client.delete(f"/api/users/{uid}", headers=env.sys_headers())
        assert r.status_code == 200 and r.json()["code"] == 0
        assert not env.pg.query_df(
            "SELECT 1 FROM sys_user WHERE id=%s AND deleted_at IS NOT NULL", [uid]).empty


def test_system_admin_cannot_delete_self(client, env):
    r = client.delete("/api/users/admin", headers=env.sys_headers())
    assert r.json()["code"] == 4000
    assert env.pg.query_df(
        "SELECT 1 FROM sys_user WHERE id='admin' AND deleted_at IS NULL").shape[0] == 1
