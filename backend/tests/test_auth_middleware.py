"""鉴权中间件 + 角色守卫 + 上下文隔离测试（多租户 RBAC stage2·T5）。

用 create_app()+TestClient（不进 lifespan）。真实 PG/Redis + JWT 密钥。
覆盖：白名单放行 / 非白名单默认 deny(401) / 系统级接口角色守卫(403) / 路由扫描机制 /
上下文归属隔离（tenant_admin 看不到 admin 的预设方案）。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

_SECRET = "unit-test-jwt-secret-0123456789-abcdefghij"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app
    return TestClient(create_app())


@pytest.fixture()
def tadmin(pg):
    """临时租户管理员（独立租户），用于验证角色守卫与归属隔离；teardown 清理。"""
    uid = "pytest_ta_" + uuid.uuid4().hex[:8]
    tid = "pytest_tt_" + uuid.uuid4().hex[:8]
    pg.execute("INSERT INTO sys_tenant (id,name,status) VALUES (%s,'t','active')", [tid])
    pg.execute(
        "INSERT INTO sys_user (id,tenant_id,account,role_code,perm_ver,status) "
        "VALUES (%s,%s,%s,'tenant_admin',0,'active')", [uid, tid, uid])
    yield uid, tid
    pg.execute("DELETE FROM sys_user WHERE id=%s", [uid])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tid])


def _access(user_id, tenant_id, role, perm_ver=0):
    from backend.auth.jwt_tokens import issue_access
    return issue_access(user_id, tenant_id, role, perm_ver)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_whitelist_public_no_token(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/public-config").status_code == 200


def test_controlled_route_without_token_401(client):
    resp = client.get("/api/profiles")
    assert resp.status_code == 401 and resp.json()["code"] == 4010


def test_invalid_token_401(client):
    resp = client.get("/api/profiles", headers=_auth("garbage.token.xxx"))
    assert resp.status_code == 401


def test_system_route_forbidden_for_tenant_admin(client, tadmin):
    uid, tid = tadmin
    resp = client.get("/api/data/overview", headers=_auth(_access(uid, tid, "tenant_admin")))
    assert resp.status_code == 403 and resp.json()["code"] == 4030


def test_system_route_allows_system_role(client, pg):
    pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    resp = client.get("/api/data/overview", headers=_auth(_access("admin", "default", "system", pv)))
    assert resp.status_code not in (401, 403)   # 通过鉴权+角色守卫（业务是否 200 不在本测范围）


def test_context_isolation_tenant_admin_sees_no_admin_presets(client, tadmin):
    # admin 归属下有内置预设方案；租户管理员在独立租户应看不到（上下文归属隔离）
    uid, tid = tadmin
    resp = client.get("/api/profiles", headers=_auth(_access(uid, tid, "tenant_admin")))
    assert resp.status_code == 200
    assert resp.json()["data"] == []   # 各自归属，互不可见


def test_indicator_patch_writes_forbidden_for_tenant_admin(client, tadmin):
    # 评审 P0-1 回归：指标启停/分类修改是全局元数据写，非 system 一律 403
    uid, tid = tadmin
    h = _auth(_access(uid, tid, "tenant_admin"))
    r1 = client.patch("/api/indicators/def/MA/enabled", json={"enabled": False}, headers=h)
    r2 = client.patch("/api/indicators/def/MA/categories", json={"categories": ["x"]}, headers=h)
    assert r1.status_code == 403 and r2.status_code == 403


def test_layout_page_reset_forbidden_for_tenant_admin(client, tadmin):
    # 评审 P1-3 回归：页面级布局重置是平台写，非 system 403（用户级 scope 不在此限）
    uid, tid = tadmin
    resp = client.post("/api/layout/reset", json={"scope": "page", "pageKey": "board"},
                       headers=_auth(_access(uid, tid, "tenant_admin")))
    assert resp.status_code == 403


def test_redis_failure_fails_closed_503(client, pg, monkeypatch):
    # 评审 P1-4 回归：鉴权关键 Redis 故障 → fail-closed 503（非未处理 500）
    import redis as _redis

    from backend.auth import session_store as ss
    monkeypatch.setattr(ss, "is_jti_revoked",
                        lambda *_a, **_k: (_ for _ in ()).throw(_redis.ConnectionError("down")))
    pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    resp = client.get("/api/profiles", headers=_auth(_access("admin", "default", "system", pv)))
    assert resp.status_code == 503


def test_layout_user_config_owner_from_context_not_request(client, pg, tadmin):
    # 评审 P1 回归：用户级 layout 归属取自上下文，前端传 userId=admin 被忽略（不越权写 admin 名下）
    uid, tid = tadmin
    pk = "iso" + uuid.uuid4().hex[:6]
    try:
        r = client.post(
            f"/api/layout/users/{pk}",
            json={"userId": "admin", "config": {"values": {"density": "comfortable"}}},
            headers=_auth(_access(uid, tid, "tenant_admin")))
        assert r.status_code == 200
        # 写入了当前用户(uid)名下，而非被伪造的 admin
        assert not pg.query_df(
            "SELECT 1 FROM layout_user_config WHERE user_id=%s AND page_key=%s", [uid, pk]).empty
        assert pg.query_df(
            "SELECT 1 FROM layout_user_config WHERE user_id='admin' AND page_key=%s", [pk]).empty
    finally:
        pg.execute("DELETE FROM layout_user_config WHERE page_key=%s", [pk])


def test_security_headers_present(client):
    # T6：安全响应头（对所有响应，含白名单）
    resp = client.get("/api/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "SAMEORIGIN"
    assert "referrer-policy" in resp.headers


def test_global_rate_limit_returns_429(client, monkeypatch):
    # T6：全局 /api 限流超限 → 429（monkeypatch rate_limit_ok 令 api 域超限；不影响其它域）
    from backend.auth import session_store as ss
    monkeypatch.setattr(ss, "rate_limit_ok", lambda scope, *a, **k: scope != "api")
    resp = client.get("/api/health")
    assert resp.status_code == 429 and resp.json()["code"] == 4290


def test_all_controlled_get_routes_require_token(client):
    """机制性默认 deny：扫描所有静态 GET /api 路由，白名单外无一漏挂鉴权。"""
    from backend.auth.middleware import is_public

    checked = 0
    for route in client.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path.startswith("/api/") or is_public(path) or "{" in path:
            continue
        if "GET" in methods:
            assert client.get(path).status_code == 401, f"{path} 未被鉴权拦截"
            checked += 1
    assert checked > 0
