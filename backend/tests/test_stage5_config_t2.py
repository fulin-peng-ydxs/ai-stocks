"""阶段五 T2：认证防滥用与审计保留期配置模型。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.storage.app_config import WHITELIST, AppConfigRepo, ConfigValidationError

_SECRET = "unit-test-stage5-config-0123456789-abcdef"


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


def test_stage5_config_whitelist_contains_auth_and_audit_fields():
    assert {
        "auth.require_email_code",
        "auth.login_captcha_enabled",
        "auth.captcha_after_fails",
        "auth.login_rate_per_min",
        "auth.register_rate_per_hour",
        "auth.email_code_rate_per_hour",
        "audit.retention_days",
    } <= set(WHITELIST)


def test_stage5_config_validation_and_effective_settings(app_cfg):
    app_cfg.set_many({
        "auth.require_email_code": False,
        "auth.login_captcha_enabled": True,
        "auth.captcha_after_fails": 2,
        "auth.login_rate_per_min": 8,
        "auth.register_rate_per_hour": 6,
        "auth.email_code_rate_per_hour": 7,
        "audit.retention_days": 30,
    })

    from backend.config import get_effective_settings
    settings = get_effective_settings()
    assert settings.auth.require_email_code is False
    assert settings.auth.login_captcha_enabled is True
    assert settings.auth.captcha_after_fails == 2
    assert settings.auth.login_rate_per_min == 8
    assert settings.auth.register_rate_per_hour == 6
    assert settings.auth.email_code_rate_per_hour == 7
    assert settings.audit.retention_days == 30

    from backend.services.auth_service import AuthService
    public_cfg = AuthService().public_config()
    assert public_cfg["require_email_code"] is False
    assert public_cfg["login_captcha_enabled"] is True
    assert public_cfg["captcha_after_fails"] == 2

    from backend.config.settings import AuditConfig
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AuditConfig(retention_days=0)


@pytest.mark.parametrize("path,value", [
    ("auth.require_email_code", "false"),
    ("auth.login_captcha_enabled", 1),
    ("auth.captcha_after_fails", 0),
    ("auth.login_rate_per_min", 0),
    ("auth.register_rate_per_hour", 0),
    ("auth.email_code_rate_per_hour", 0),
    ("audit.retention_days", 366),
    ("audit.retention_days", 6),
    ("auth.no_such_key", True),
])
def test_stage5_config_rejects_invalid_values(app_cfg, path, value):
    before = app_cfg.get_overrides()
    with pytest.raises(ConfigValidationError):
        app_cfg.set_many({path: value})
    assert app_cfg.get_overrides() == before


def test_data_settings_api_exposes_and_saves_stage5_config(client, pg, app_cfg):
    resp = client.get("/api/data/settings", headers=_admin_headers(pg))
    assert resp.status_code == 200
    groups = {g["key"]: g for g in resp.json()["data"]["groups"]}
    assert "auth" in groups and "audit" in groups
    fields = {
        f["path"]: f
        for g in (groups["auth"], groups["audit"])
        for f in g["fields"]
    }
    assert fields["auth.require_email_code"]["type"] == "bool"
    assert fields["auth.captcha_after_fails"]["min"] == 1
    assert "登录图形验证码开关开启时" in fields["auth.captcha_after_fails"]["desc"]
    assert fields["audit.retention_days"]["min"] == 7
    assert fields["audit.retention_days"]["max"] == 365

    save = client.post(
        "/api/data/settings",
        headers=_admin_headers(pg),
        json={"updates": {
            "auth.login_captcha_enabled": True,
            "auth.captcha_after_fails": 4,
            "audit.retention_days": 45,
        }},
    )
    assert save.status_code == 200
    assert save.json()["data"]["saved"] == 3

    overrides = AppConfigRepo(pg).get_overrides()
    assert overrides["auth.login_captcha_enabled"] is True
    assert overrides["auth.captcha_after_fails"] == 4
    assert overrides["audit.retention_days"] == 45
