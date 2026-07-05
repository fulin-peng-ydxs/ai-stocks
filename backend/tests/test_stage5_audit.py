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
    target_id = f"stage5_query_{uuid.uuid4().hex[:8]}"
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
        target_id=target_id,
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
        params={"target_keyword": target_id, "page": 1, "page_size": 10},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["page_size"] == 10
    assert data["list"][0]["id"] == audit_id
    assert data["list"][0]["resource_name"] == "数据设置保存"
    assert data["list"][0]["target_description"] == "数据设置保存"
    assert data["list"][0]["context"] == {
        "request_id": "req-1",
        "permission_code": "data-settings:manage",
        "data_scope": {"tenant": "default"},
    }

    by_resource_name = client.get(
        "/api/audit",
        headers=_admin_headers(pg),
        params={
            "target_keyword": "数据设置保存",
            "resource_code": "data-settings:manage",
            "page": 1,
            "page_size": 100,
        },
    )
    assert by_resource_name.status_code == 200
    assert audit_id in {row["id"] for row in by_resource_name.json()["data"]["list"]}

    summary = client.get(
        "/api/audit/summary",
        headers=_admin_headers(pg),
        params={"target_keyword": target_id},
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


def test_stage5_audit_supports_multi_value_filters(client, pg):
    _clear_stage5_audit(pg)
    repo = AuditRepository(pg)
    first_id = repo.record(
        event_category="api",
        event_type="api",
        action="request",
        result="success",
        status="completed",
        tenant_id="default",
        actor_user_id="admin",
        actor_account="admin",
        resource_code="audit:view",
        target_type="stage5_test",
        target_id="stage5_multi_filter_a",
        target_label="multi filter A",
        context={"route": "/api/audit"},
    )
    second_id = repo.record(
        event_category="security",
        event_type="login",
        action="login",
        result="failed",
        status="failed",
        tenant_id="other_tenant",
        actor_user_id="u2",
        actor_account="other",
        resource_code="auth:login",
        target_type="stage5_test",
        target_id="stage5_multi_filter_b",
        target_label="multi filter B",
        context={"route": "/api/auth/login"},
    )
    assert first_id and second_id

    params = [
        ("target_keyword", "stage5_multi_filter"),
        ("event_category", "api"),
        ("event_category", "security"),
        ("result", "success"),
        ("result", "failed"),
        ("tenant_id", "default"),
        ("tenant_id", "other_tenant"),
    ]
    resp = client.get("/api/audit", headers=_admin_headers(pg), params=params)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert {row["id"] for row in data["list"]} == {first_id, second_id}

    summary = client.get("/api/audit/summary", headers=_admin_headers(pg), params=params)
    assert summary.status_code == 200
    assert summary.json()["data"]["total"] == 2
    assert summary.json()["data"]["by_category"]["api"] == 1
    assert summary.json()["data"]["by_category"]["security"] == 1


def test_stage5_audit_default_retention_window_filters_old_records(client, pg, app_cfg):
    _clear_stage5_audit(pg)
    app_cfg.set_many({"audit.retention_days": 7})
    recent_id = "stage5_retention_recent"
    old_id = "stage5_retention_old"
    try:
        pg.execute(
            """
            INSERT INTO audit_log (
                id, event_time, tenant_id, actor_user_id, actor_account,
                event_category, event_type, resource_code, action, target_type,
                target_id, target_label, result, status, context
            ) VALUES (
                %s, now() - interval '1 day', 'default', 'admin', 'admin',
                'config', 'config', 'data-settings:manage', 'update', 'stage5_test',
                %s, 'retention-default recent', 'success', 'completed', '{}'::jsonb
            ), (
                %s, now() - interval '8 days', 'default', 'admin', 'admin',
                'config', 'config', 'data-settings:manage', 'update', 'stage5_test',
                %s, 'retention-default old', 'success', 'completed', '{}'::jsonb
            )
            """,
            [recent_id, recent_id, old_id, old_id],
        )

        resp = client.get(
            "/api/audit",
            headers=_admin_headers(pg),
            params={"target_keyword": "retention-default", "page": 1, "page_size": 10},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert [row["id"] for row in data["list"]] == [recent_id]
    finally:
        _clear_stage5_audit(pg)
