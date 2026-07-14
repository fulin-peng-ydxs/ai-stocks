"""阶段四 T4：用户级布局配置 + /layout/reset 动态 scope 自守卫。

覆盖：
- `POST /api/layout/reset` 动态 scope 自守卫（DYNAMIC_SCOPE_GUARDED_ROUTES 唯一成员）：
  page scope → 非 system 403；user scope → 有角色用户通过 baseline 自持久化权限、无角色 fail-closed；
- 用户级偏好读写 `layout:user-config` baseline 守卫。
（layout:view 基线读 presets/pages/effective 的"不误 gate"由 test_auth_middleware 反向用例覆盖。）
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

_SECRET = "test-secret-stage4-layout-0123456789abcdef"   # ≥32B 免 HMAC 长度告警


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


def _auth(uid: str, tid: str, pv: int = 0) -> dict:
    from backend.auth.jwt_tokens import issue_access
    return {"Authorization": "Bearer " + issue_access(uid, tid, pv)}


def _mk_user(pg, codes: list[str], *, with_role: bool = True) -> tuple[str, str, str | None]:
    """建租户 + 用户 + 可选自定义角色（授予 codes）+ 关联，返回 (uid, tid, rid)。非 system。"""
    tid = "s4lt_" + uuid.uuid4().hex[:8]
    uid = "s4lu_" + uuid.uuid4().hex[:8]
    rid = "s4lr_" + uuid.uuid4().hex[:8] if with_role else None
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
    pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
               "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tid, uid])
    if rid:
        pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
                   "VALUES (%s,%s,'t4','custom',FALSE,FALSE)", [rid, rid])
        pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
        for code in codes:
            pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                       "ON CONFLICT DO NOTHING", [rid, code])
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str | None) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    if rid:
        pg.execute("DELETE FROM sys_role WHERE id=%s", [rid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def test_reset_page_scope_forbidden_for_non_system(client, pg):
    """page scope 重置是平台写：非 system（即便持 layout:user-config）→ 403。"""
    uid, tid, rid = _mk_user(pg, codes=["layout:user-config"])
    try:
        r = client.post("/api/layout/reset", json={"scope": "page", "pageKey": "board"},
                        headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_reset_user_scope_allowed_by_baseline(client, pg):
    """有角色用户即使未显式授权 layout:user-config，也通过 baseline 自持久化权限。"""
    uid, tid, rid = _mk_user(pg, codes=[])
    try:
        r = client.post("/api/layout/reset", json={"scope": "user", "pageKey": "board"},
                        headers=_auth(uid, tid))
        assert r.status_code not in (401, 403)
    finally:
        _rm_user(pg, uid, tid, rid)


def test_reset_user_scope_without_role_fail_closed(client, pg):
    """无角色用户不注入 baseline，user scope 重置仍 fail-closed。"""
    uid, tid, rid = _mk_user(pg, codes=[], with_role=False)
    try:
        r = client.post("/api/layout/reset", json={"scope": "user", "pageKey": "board"},
                        headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_user_config_read_write_allowed_by_baseline(client, pg):
    """GET/POST /layout/users 对有角色用户走 baseline 自持久化权限，不要求显式授权。"""
    uid, tid, rid = _mk_user(pg, codes=[])
    try:
        headers = _auth(uid, tid)
        assert client.get("/api/layout/users/board", headers=headers).status_code not in (401, 403)
        assert client.post(
            "/api/layout/users/board",
            json={"config": {"values": {"density": "compact"}}},
            headers=headers,
        ).status_code not in (401, 403)
    finally:
        pg.execute("DELETE FROM layout_user_config WHERE user_id=%s AND page_key=%s", [uid, "board"])
        _rm_user(pg, uid, tid, rid)


def test_user_config_without_role_fail_closed(client, pg):
    """无角色用户不注入 baseline，用户级布局偏好接口仍 403。"""
    uid, tid, rid = _mk_user(pg, codes=[], with_role=False)
    try:
        assert client.get("/api/layout/users/board", headers=_auth(uid, tid)).status_code == 403
    finally:
        _rm_user(pg, uid, tid, rid)
