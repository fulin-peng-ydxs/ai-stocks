"""阶段四 T4：用户级布局配置 + /layout/reset 动态 scope 自守卫。

覆盖：
- `POST /api/layout/reset` 动态 scope 自守卫（DYNAMIC_SCOPE_GUARDED_ROUTES 唯一成员）：
  page scope → 非 system 403；user scope → 需 layout:user-config（有则过、无则 403）；
- 用户级偏好读写 `layout:user-config` 守卫。
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


def _mk_user(pg, codes: list[str]) -> tuple[str, str, str]:
    """建租户 + 用户 + 自定义角色（授予 codes）+ 关联，返回 (uid, tid, rid)。非 system。"""
    tid = "s4lt_" + uuid.uuid4().hex[:8]
    uid = "s4lu_" + uuid.uuid4().hex[:8]
    rid = "s4lr_" + uuid.uuid4().hex[:8]
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active') ON CONFLICT DO NOTHING", [tid])
    pg.execute("INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
               "VALUES (%s,%s,%s,'normal',0,'active')", [uid, tid, uid])
    pg.execute("INSERT INTO sys_role (id,code,name,kind,is_builtin,is_locked) "
               "VALUES (%s,%s,'t4','custom',FALSE,FALSE)", [rid, rid])
    pg.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (%s,%s)", [uid, rid])
    for code in codes:
        pg.execute("INSERT INTO sys_role_resource (role_id,resource_id) VALUES (%s,%s) "
                   "ON CONFLICT DO NOTHING", [rid, code])
    return uid, tid, rid


def _rm_user(pg, uid: str, tid: str, rid: str) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
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


def test_reset_user_scope_requires_user_config_code(client, pg):
    """user scope 重置需 layout:user-config：无该码 → 403。"""
    uid, tid, rid = _mk_user(pg, codes=[])   # 仅 baseline，无 layout:user-config
    try:
        r = client.post("/api/layout/reset", json={"scope": "user", "pageKey": "board"},
                        headers=_auth(uid, tid))
        assert r.status_code == 403 and r.json()["code"] == 4030
    finally:
        _rm_user(pg, uid, tid, rid)


def test_reset_user_scope_allowed_with_code(client, pg):
    """有 layout:user-config → user scope 重置过守卫（进入业务层，非 401/403）。"""
    uid, tid, rid = _mk_user(pg, codes=["layout:user-config"])
    try:
        r = client.post("/api/layout/reset", json={"scope": "user", "pageKey": "board"},
                        headers=_auth(uid, tid))
        assert r.status_code not in (401, 403)
    finally:
        _rm_user(pg, uid, tid, rid)


def test_user_config_read_write_requires_code(client, pg):
    """GET/POST /layout/users 需 layout:user-config：有码过守卫、无码 403。"""
    ok_uid, ok_tid, ok_rid = _mk_user(pg, codes=["layout:user-config"])
    no_uid, no_tid, no_rid = _mk_user(pg, codes=[])
    try:
        assert client.get("/api/layout/users/board", headers=_auth(ok_uid, ok_tid)).status_code not in (401, 403)
        assert client.get("/api/layout/users/board", headers=_auth(no_uid, no_tid)).status_code == 403
    finally:
        _rm_user(pg, ok_uid, ok_tid, ok_rid)
        _rm_user(pg, no_uid, no_tid, no_rid)
