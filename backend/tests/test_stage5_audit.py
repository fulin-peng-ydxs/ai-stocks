"""阶段五 T4：审计查询后端闭环。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.storage.audit_repository import AuditRepository
from backend.storage.user_repository import UserRepository

_SECRET = "unit-test-stage5-audit-0123456789-abcdef"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _token(pg, user_id: str, tenant_id: str) -> str:
    from backend.auth.jwt_tokens import issue_access

    pv = int(pg.query_df(
        "SELECT perm_ver FROM sys_user WHERE id=%s", [user_id],
    ).iloc[0]["perm_ver"])
    return "Bearer " + issue_access(user_id, tenant_id, pv)


def _admin_headers(pg) -> dict:
    return {"Authorization": _token(pg, "admin", "default")}


def _new_tenant_admin(pg) -> dict:
    account = f"stage5_audit_{uuid.uuid4().hex[:10]}"
    user = UserRepository(pg).register_tenant_and_admin(
        account,
        f"{account}@ex.com",
        hash_password("GoodPass1"),
    )
    return user


def _cleanup_user(pg, user: dict) -> None:
    pg.execute("DELETE FROM sys_user WHERE id=%s", [user["id"]])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [user["tenant_id"]])


def _clear_stage5_audit(pg) -> None:
    pg.execute("DELETE FROM audit_log WHERE target_type='stage5_test'")


def test_stage5_audit_system_can_query_summary_and_detail(client, pg):
    _clear_stage5_audit(pg)
    repo = AuditRepository(pg)
    audit_id = repo.record(
        event_category="config",
        event_type="config",
        action="update",
        result="success",
        status="completed",
        tenant_id="default",
        actor_user_id="admin",
        actor_account="admin",
        resource_code="data-settings:manage",
        target_type="stage5_test",
        target_id="system",
        target_label="系统设置",
        context={
            "request_id": "req-1",
            "permission_code": "data-settings:manage",
            "password": "hidden",
            "token": "hidden",
            "unknown": "hidden",
            "data_scope": {"tenant": "default", "access_token": "hidden"},
        },
    )
    assert audit_id

    resp = client.get(
        "/api/audit",
        headers=_admin_headers(pg),
        params={"target_keyword": "system", "page": 1, "page_size": 10},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["page_size"] == 10
    assert data["list"][0]["id"] == audit_id
    assert data["list"][0]["context"] == {
        "request_id": "req-1",
        "permission_code": "data-settings:manage",
        "data_scope": {"tenant": "default"},
    }

    summary = client.get(
        "/api/audit/summary",
        headers=_admin_headers(pg),
        params={"target_keyword": "system"},
    )
    assert summary.status_code == 200
    assert summary.json()["data"]["total"] == 1
    assert summary.json()["data"]["by_category"]["config"] == 1
    assert summary.json()["data"]["success"] == 1

    detail = client.get(f"/api/audit/{audit_id}", headers=_admin_headers(pg))
    assert detail.status_code == 200
    assert detail.json()["data"]["context"] == {
        "request_id": "req-1",
        "permission_code": "data-settings:manage",
        "data_scope": {"tenant": "default"},
    }

    invalid = client.get(
        "/api/audit",
        headers=_admin_headers(pg),
        params={"start_time": "not-a-time"},
    )
    assert invalid.status_code == 200
    assert invalid.json()["code"] == 4000


def test_stage5_audit_tenant_admin_is_scoped_to_own_tenant(client, pg):
    _clear_stage5_audit(pg)
    tenant_admin = _new_tenant_admin(pg)
    other_id = None
    try:
        own_id = AuditRepository(pg).record(
            event_category="api",
            event_type="api",
            action="request",
            result="success",
            status="completed",
            tenant_id=tenant_admin["tenant_id"],
            actor_user_id=tenant_admin["id"],
            resource_code="audit:view",
            target_type="stage5_test",
            target_id="own",
            target_label="本租户记录",
            context={"route": "/api/audit"},
        )
        other_id = AuditRepository(pg).record(
            event_category="api",
            event_type="api",
            action="request",
            result="failed",
            status="failed",
            tenant_id="other_tenant",
            actor_user_id="other",
            resource_code="audit:view",
            target_type="stage5_test",
            target_id="other",
            target_label="其他租户记录",
            context={"route": "/api/audit"},
        )
        headers = {"Authorization": _token(pg, tenant_admin["id"], tenant_admin["tenant_id"])}

        resp = client.get(
            "/api/audit",
            headers=headers,
            params={"target_keyword": "租户记录", "tenant_id": "other_tenant"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["list"][0]["id"] == own_id

        other_detail = client.get(f"/api/audit/{other_id}", headers=headers)
        assert other_detail.status_code == 200
        assert other_detail.json()["code"] == 4004
    finally:
        _cleanup_user(pg, tenant_admin)
