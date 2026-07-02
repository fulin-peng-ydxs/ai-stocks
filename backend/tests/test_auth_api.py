"""认证接口 HTTP 契约测试（多租户 RBAC stage2·T4）：验证真实 401/403/429 出码。

用 create_app() + TestClient（不进入 lifespan，跳过 scheduler/DuckDB 启动副作用）；
只校验 HTTP 状态码与响应体口径，业务逻辑由 test_auth_service 覆盖。
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
    # 不用 with：不触发 startup 事件（scheduler/reconcile/DuckDB 自检），只测路由 + 异常映射
    return TestClient(create_app())


def test_bad_credentials_returns_401(client):
    resp = client.post("/api/auth/login",
                       json={"account": f"nope_{uuid.uuid4().hex[:8]}", "password": "whatever1"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 4010 and body["data"] is None


def test_me_without_token_returns_401(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == 4010


def test_public_config_is_public_200(client):
    resp = client.get("/api/auth/public-config")
    assert resp.status_code == 200
    assert "require_email_code" in resp.json()["data"]


def test_oauth_placeholder_is_soft_business_error(client):
    # R6 占位：ValidationError → 业务软失败（HTTP 200 + code 4000），非 401
    resp = client.get("/api/auth/oauth/wechat")
    assert resp.status_code == 200
    assert resp.json()["code"] == 4000


def _admin_token():
    from backend.auth.jwt_tokens import issue_access
    from backend.storage.pg_client import get_pg_client
    pv = int(get_pg_client().query_df(
        "SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    return issue_access("admin", "default", pv)


def test_me_contract_shape(client):
    # 评审 P2 回归：/me 固定契约 {user, tenant, role, menus, permissions}
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer " + _admin_token()})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) >= {"user", "tenant", "role", "menus", "permissions"}
    assert {"id", "account"} <= set(data["user"])
    assert "id" in data["tenant"]
    assert data["role"] == "system"


def test_me_redis_down_returns_503(client, monkeypatch):
    # 评审 P1 回归：白名单 auth 路径(/me) Redis 故障也须 fail-closed 503（非 500）
    import redis as _redis

    from backend.auth import session_store as ss
    monkeypatch.setattr(ss, "is_jti_revoked",
                        lambda *_a, **_k: (_ for _ in ()).throw(_redis.ConnectionError("down")))
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer " + _admin_token()})
    assert resp.status_code == 503
