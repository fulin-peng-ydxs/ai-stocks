"""阶段四 T5：system-only 路由叠加精确码后仍保持硬守卫。

覆盖：
- 每类 system-only 端点（config / indicators 写 / layout 平台 / data_admin / data_tasks / data 读）
  非 system → 403，system → 非 401/403（业务是否 200 不在本测范围）；
- **硬守卫不降级铁律**：`require_system_perm` ≠ `require_perm`——即便把 system-only 资源码直接授予
  自定义角色（绕过 system_only_resource_ids 服务层拦截，直插授权行），非 system 用户仍 403；
- 本次新补守卫的 `POST /api/layout/validate`（此前裸露）非 system → 403。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret-stage4-systemonly-0123456789ab"   # ≥32B 免 HMAC 长度告警


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access
    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, codes: list[str]) -> tuple[str, str, str]:
    """建租户 + 非 system 用户 + 自定义角色（授予 codes）+ 关联，返回 (uid, tid, rid)。"""
    tid = "s4st_" + uuid.uuid4().hex[:8]
    uid = "s4su_" + uuid.uuid4().hex[:8]
    rid = "s4sr_" + uuid.uuid4().hex[:8]
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
    pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
               "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tid, uid])
    pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
               "VALUES (%s,%s,'t5','custom',FALSE,FALSE)", [rid, rid])
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    for code in codes:
        pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [rid, code])
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _admin_auth(pg) -> dict:
    pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    return _auth("admin", "default", pv)


# 每类 system-only 端点抽样（method, path, json body）——覆盖 T5 六个功能域。
_SYSTEM_ONLY_ENDPOINTS = [
    ("GET", "/api/config", None),                                   # config:view
    ("POST", "/api/config/reload", {}),                             # config:reload
    ("POST", "/api/indicators/def", {"key": "x", "name_cn": "x", "dtype": "bool", "expression": "close>0"}),  # indicator:def-manage
    ("POST", "/api/layout/presets", {"key": "x", "name": "x"}),     # layout:preset-manage
    ("POST", "/api/layout/pages/board", {"config": {}}),           # layout:page-manage
    ("POST", "/api/layout/validate", {"config": {}}),              # layout:page-manage（本次新补守卫）
    ("GET", "/api/layout/field-policies", None),                   # layout:field-policy
    ("GET", "/api/data/overview", None),                           # data:overview
    ("GET", "/api/data/quality", None),                            # data-quality:view
    ("POST", "/api/data/sources/test", {}),                        # data-source:test
    ("GET", "/api/data/tasks", None),                              # data-task:manage
    ("GET", "/api/data/status", None),                             # data-status:view
]


@pytest.mark.parametrize("method,path,body", _SYSTEM_ONLY_ENDPOINTS)
def test_system_only_endpoint_forbidden_for_non_system(client, pg, method, path, body):
    """非 system（仅 baseline，无任何管理码）→ 403。"""
    uid, tid, rid = _mk_user(pg, codes=[])
    try:
        r = client.request(method, path, json=body, headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030, f"{path} 未挡住非 system"
    finally:
        _rm_user(pg, uid, tid, rid)


@pytest.mark.parametrize("method,path,body", _SYSTEM_ONLY_ENDPOINTS)
def test_system_only_endpoint_allows_system(client, pg, method, path, body):
    """system（admin）→ 过守卫（非 401/403）；业务是否 200 不在本测范围。"""
    r = client.request(method, path, json=body, headers=_admin_auth(pg))
    assert r.status_code not in (401, 403), f"{path} 误挡 system"


def test_hard_guard_not_downgraded_by_grant(client, pg):
    """硬守卫铁律：即便把 system-only 码直接授予自定义角色，非 system 仍 403。

    require_system_perm 运行时 = require_system()，不看资源码是否在上下文 resources 内；
    这正是它区别于可授权的 require_perm 之处（system-only 边界不因授权而降级）。
    """
    uid, tid, rid = _mk_user(pg, codes=["config:view"])   # 直插授权行（绕过服务层 system_only 拦截）
    try:
        r = client.get("/api/config", headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030, "system-only 码被授权后竟放行非 system（降级）"
    finally:
        _rm_user(pg, uid, tid, rid)
