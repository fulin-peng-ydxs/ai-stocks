"""阶段五 T3：认证链路消费运行时配置。"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.services.auth_service import AuthService

_SECRET = "unit-test-stage5-auth-config-0123456789-abcdef"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _admin_headers(pg) -> dict:
    from backend.auth.jwt_tokens import issue_access

    pv = int(pg.query_df(
        "SELECT perm_ver FROM sys_user WHERE id='admin'",
    ).iloc[0]["perm_ver"])
    return {"Authorization": "Bearer " + issue_access("admin", "default", pv)}


def _cleanup_account(pg, account: str) -> None:
    df = pg.query_df("SELECT id, tenant_id FROM sys_user WHERE account=%s", [account])
    if df.empty:
        return
    user_id = df.iloc[0]["id"]
    tenant_id = df.iloc[0]["tenant_id"]
    pg.execute("DELETE FROM sys_user WHERE id=%s", [user_id])
    pg.execute("DELETE FROM sys_tenant WHERE id=%s", [tenant_id])


def _decode_context(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def test_stage5_auth_settings_are_consumed_by_public_config_and_register(
    client, pg, app_cfg
):
    save = client.post(
        "/api/data/settings",
        headers=_admin_headers(pg),
        json={"updates": {
            "auth.require_email_code": False,
            "auth.login_captcha_enabled": True,
            "auth.captcha_after_fails": 2,
        }},
    )
    assert save.status_code == 200

    public_cfg = client.get("/api/auth/public-config")
    assert public_cfg.status_code == 200
    data = public_cfg.json()["data"]
    assert data["require_email_code"] is False
    assert data["login_captcha_enabled"] is True
    assert data["captcha_after_fails"] == 2

    account = f"stage5_auth_{uuid.uuid4().hex[:10]}"
    try:
        out = AuthService().register(
            account,
            "GoodPass1",
            ip=f"ip_{uuid.uuid4().hex[:10]}",
        )
        assert out["user"]["account"] == account
    finally:
        _cleanup_account(pg, account)


def test_stage5_settings_save_records_sanitized_config_audit(client, pg, app_cfg):
    pg.execute(
        "DELETE FROM audit_log WHERE event_category='config' AND action='update' "
        "AND target_type='app_config'"
    )
    save = client.post(
        "/api/data/settings",
        headers=_admin_headers(pg),
        json={"updates": {"auth.login_captcha_enabled": True}},
    )
    assert save.status_code == 200

    rows = pg.query_df(
        "SELECT tenant_id, actor_user_id, event_category, event_type, resource_code, "
        "action, target_type, result, status, method, path, context "
        "FROM audit_log WHERE event_category='config' AND action='update' "
        "ORDER BY event_time DESC LIMIT 1"
    )
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["tenant_id"] == "default"
    assert row["actor_user_id"] == "admin"
    assert row["event_type"] == "config"
    assert row["resource_code"] == "data-settings:manage"
    assert row["target_type"] == "app_config"
    assert row["result"] == "success"
    assert row["status"] == "completed"
    assert row["method"] == "POST"
    assert row["path"] == "/api/data/settings"
    context = _decode_context(row["context"])
    assert context == {
        "config_keys": ["auth.login_captcha_enabled"],
        "affected_count": 1,
    }


def test_stage5_settings_save_ignores_audit_write_failure(
    client, pg, app_cfg, monkeypatch
):
    from backend.storage.audit_repository import AuditRepository

    def fail_record(self, **kwargs):  # noqa: ARG001
        raise RuntimeError("audit down")

    monkeypatch.setattr(AuditRepository, "record", fail_record)
    save = client.post(
        "/api/data/settings",
        headers=_admin_headers(pg),
        json={"updates": {"auth.captcha_after_fails": 4}},
    )
    assert save.status_code == 200
    assert save.json()["data"]["saved"] == 1
    assert AuthService().public_config()["captcha_after_fails"] == 4
