"""阶段四 T7：菜单/资源解析回归——baseline 强制注入、无角色 fail-closed、运行时不可反选、
自定义角色业务菜单可达、resource 列表 baseline_locked 契约。

资源码变多后（stage4 新增 48 码，配置存储迁移扩展自持久化基线），核查 perm_resolver/AuthService 仍：
- 对**有角色的非 system 用户**强制并入 baseline 码（共享读 + 当前用户自持久化偏好），
  与 role_resource 授权无关、角色页反选不掉（运行时权威防线）；
- 对**无角色**用户 fail-closed（空 menus/resources，不注入 baseline）；
- 自定义角色授了业务菜单即可在 /me 菜单树导航到该业务页；
- ResourceRepository 列表把 baseline 码标 baseline_locked=True（前端权限树据此恒勾选+置灰）。

真实 PG。直接调 perm_resolver.resolve / AuthService.me（不经 token/中间件）。临时租户/用户/角色清理。
"""

from __future__ import annotations

import uuid

import pytest

from backend.auth.constants import SHARED_RESOURCE_CODES

_BASELINE = set(SHARED_RESOURCE_CODES)


@pytest.fixture()
def env(pg, monkeypatch):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", "unit-test-jwt-secret-0123456789-abcdefghij")
    made = {"user": [], "tenant": [], "role": []}

    def mk_custom(resource_codes=(), menu_codes=(), *, with_role=True):
        """建租户 + 非 system 用户（+ 可选自定义角色并授码/授菜单）。with_role=False → 无角色（fail-closed）。"""
        tid = "s4mg_t_" + uuid.uuid4().hex[:8]
        uid = "s4mg_u_" + uuid.uuid4().hex[:8]
        pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
        pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
                   "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tid, uid])
        made["tenant"].append(tid)
        made["user"].append(uid)
        rid = None
        if with_role:
            rid = "s4mg_r_" + uuid.uuid4().hex[:8]
            pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
                       "VALUES (%s,%s,'t7','custom',FALSE,FALSE)", [rid, rid])
            pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
            made["role"].append(rid)
            for c in resource_codes:
                pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                           "ON CONFLICT DO NOTHING", [rid, c])
            for m in menu_codes:
                pg.execute("INSERT INTO sys_role_menu (role_id,menu_id) VALUES (%s,%s) "
                           "ON CONFLICT DO NOTHING", [rid, m])
        return uid, tid, rid

    from types import SimpleNamespace
    yield SimpleNamespace(mk_custom=mk_custom, pg=pg)

    for uid in made["user"]:
        pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    for rid in made["role"]:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    for tid in made["tenant"]:
        pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _resolve(uid):
    from backend.auth.perm_resolver import resolve
    return resolve(uid)


def test_custom_role_baseline_force_injected(env):
    """自定义角色只授了业务码、未授 baseline → resolve 仍强制并入 baseline 码。"""
    uid, _, _ = env.mk_custom(resource_codes=["backtest:view"])
    res = set(_resolve(uid)["resources"])
    assert _BASELINE <= res, "baseline 共享读未被强制注入"
    assert "backtest:view" in res   # 显式授的业务码仍在


def test_baseline_uncancellable_at_runtime(env):
    """运行时不可反选：自定义角色 role_resource 完全为空（模拟角色页未持久化 baseline）→
    只要用户仍持该角色，resolve 就注入 baseline（角色页反选/漏授都不影响运行时基线可用）。"""
    uid, _, _ = env.mk_custom(resource_codes=[])
    assert _BASELINE <= set(_resolve(uid)["resources"])


def test_no_role_user_fail_closed(env):
    """无任何角色的用户 → 空 menus/resources，**不注入 baseline**（fail-closed，非 fail-open）。"""
    uid, _, _ = env.mk_custom(with_role=False)
    r = _resolve(uid)
    assert r["resources"] == [] and r["menus"] == []
    assert not (_BASELINE & set(r["resources"]))   # baseline 也不注入


def test_custom_role_business_menu_navigable(env):
    """自定义角色授了业务菜单 /backtest → /me 菜单树含该叶子（可导航），且非 system 不见 system-only 分支。"""
    from backend.services.auth_service import AuthService
    uid, _, _ = env.mk_custom(resource_codes=["backtest:view"], menu_codes=["/backtest"])
    me = AuthService().me(uid)

    def _indexes(tree):
        out = set()
        for n in tree:
            out.add(n["index"])
            out |= _indexes(n.get("children", []))
        return out

    idx = _indexes(me["menus"])
    assert "/backtest" in idx
    assert "data" not in idx and "/system/config" not in idx   # system-only 分支隐藏


def test_resource_list_marks_baseline_locked(env):
    """ResourceRepository 列表：baseline 码标 baseline_locked=True、其余 False（前端权限树据此恒勾选+置灰）。"""
    from backend.storage.resource_repository import ResourceRepository
    rows = ResourceRepository().list_all()
    by_code = {r["code"]: r for r in rows}
    for c in SHARED_RESOURCE_CODES:
        assert by_code[c]["baseline_locked"] is True, f"{c} 应标 baseline_locked"
    # 抽样非 baseline 业务/系统码 → False
    for c in ("backtest:view", "config:view", "user:list"):
        if c in by_code:
            assert by_code[c]["baseline_locked"] is False, f"{c} 不应标 baseline_locked"


def test_resource_list_marks_explicit_system_only_resource_locked(env):
    """业务菜单内的管理员操作仍需在角色权限树显示并锁定。"""
    from backend.storage.resource_repository import ResourceRepository

    by_code = {r["code"]: r for r in ResourceRepository().list_all()}
    assert by_code["limit-ladder:recompute"]["menu_id"] == "/limit-ladder"
    assert by_code["limit-ladder:recompute"]["system_locked"] is True
    assert by_code["limit-ladder:view"]["system_locked"] is False
