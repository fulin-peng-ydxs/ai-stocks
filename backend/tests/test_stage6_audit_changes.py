"""阶段六 T4：审计字段级变更模型。"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.services.audit_service import AuditService
from backend.storage.audit_repository import AuditRepository

_SECRET = "unit-test-stage6-audit-changes-0123456789-abcdef"


@pytest.fixture()
def client(monkeypatch, pg, redis_cli):
    monkeypatch.setenv("AI_STOCKS_JWT_SECRET", _SECRET)
    from backend.main import create_app

    return TestClient(create_app())


def _admin_headers(pg) -> dict:
    from backend.auth.jwt_tokens import issue_access

    pv = int(pg.query_df("SELECT perm_ver FROM sys_user WHERE id='admin'").iloc[0]["perm_ver"])
    return {"Authorization": "Bearer " + issue_access("admin", "default", pv)}


def _decode(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def test_stage6_audit_repository_returns_empty_changes_for_old_records(pg):
    audit_id = f"stage6_changes_old_{uuid.uuid4().hex[:8]}"
    try:
        pg.execute(
            """
            INSERT INTO audit_log (
                id, event_category, event_type, action, target_type,
                target_id, target_label, result, status, context
            ) VALUES (
                %s, 'rbac', 'rbac', 'noop', 'stage6_changes_test',
                %s, 'old record', 'success', 'completed', '{}'::jsonb
            )
            """,
            [audit_id, audit_id],
        )

        row = AuditRepository(pg).get(audit_id)

        assert row is not None
        assert row["changes"] == []
    finally:
        pg.execute("DELETE FROM audit_log WHERE id=%s", [audit_id])


def test_stage6_audit_build_changes_skips_same_and_redacts_sensitive_fields():
    changes = AuditService.build_changes(
        {"name": "旧名称", "password": "old-secret", "status": "active"},
        {"name": "新名称", "password": "new-secret", "status": "active"},
        fields=("name", "password", "status"),
    )

    assert changes == [
        {"field": "name", "before": "旧名称", "after": "新名称"},
        {"field": "password", "before": "已变更", "after": "已变更"},
    ]


def test_stage6_settings_audit_records_field_changes(client, pg, app_cfg):
    key = "audit.retention_days"
    app_cfg.set_many({key: 31})
    pg.execute(
        "DELETE FROM audit_log WHERE event_category='config' AND target_type='app_config' "
        "AND target_id=%s",
        [key],
    )

    resp = client.post(
        "/api/data/settings",
        headers=_admin_headers(pg),
        json={"updates": {key: 32}},
    )
    assert resp.status_code == 200

    rows = pg.query_df(
        """
        SELECT changes
        FROM audit_log
        WHERE event_category='config' AND target_type='app_config' AND target_id=%s
        ORDER BY event_time DESC
        LIMIT 1
        """,
        [key],
    )
    assert len(rows) == 1
    assert _decode(rows.iloc[0]["changes"]) == [
        {"field": key, "before": 31, "after": 32}
    ]


def test_stage6_dict_update_audit_records_field_changes(client, pg):
    type_code = f"stage6_dict_{uuid.uuid4().hex[:8]}"
    try:
        pg.execute("DELETE FROM audit_log WHERE target_id=%s", [type_code])
        create = client.post(
            "/api/dict/types",
            headers=_admin_headers(pg),
            json={"code": type_code, "name": "阶段六字典", "sort": 10},
        )
        assert create.status_code == 200

        update = client.put(
            f"/api/dict/types/{type_code}",
            headers=_admin_headers(pg),
            json={"code": type_code, "name": "阶段六字典更新", "enabled": False, "sort": 20},
        )
        assert update.status_code == 200

        rows = pg.query_df(
            """
            SELECT changes
            FROM audit_log
            WHERE event_category='dict' AND action='type_update' AND target_id=%s
            ORDER BY event_time DESC
            LIMIT 1
            """,
            [type_code],
        )
        assert len(rows) == 1
        assert _decode(rows.iloc[0]["changes"]) == [
            {"field": "name", "before": "阶段六字典", "after": "阶段六字典更新"},
            {"field": "enabled", "before": True, "after": False},
            {"field": "sort", "before": 10, "after": 20},
        ]
    finally:
        pg.execute("DELETE FROM audit_log WHERE target_id LIKE %s", [f"{type_code}%"])
        pg.execute("DELETE FROM dict_item WHERE type_code=%s", [type_code])
        pg.execute("DELETE FROM dict_type WHERE code=%s", [type_code])


def test_stage6_rbac_role_update_audit_records_field_changes(client, pg):
    role_code = f"stage6_role_{uuid.uuid4().hex[:8]}"
    role_id = None
    try:
        create = client.post(
            "/api/roles",
            headers=_admin_headers(pg),
            json={"code": role_code, "name": "阶段六角色", "description": "before"},
        )
        assert create.status_code == 200
        role_id = create.json()["data"]["id"]

        update = client.put(
            f"/api/roles/{role_id}",
            headers=_admin_headers(pg),
            json={"name": "阶段六角色更新", "description": "after"},
        )
        assert update.status_code == 200

        rows = pg.query_df(
            """
            SELECT changes
            FROM audit_log
            WHERE event_category='rbac' AND action='role_update' AND target_id=%s
            ORDER BY event_time DESC
            LIMIT 1
            """,
            [role_id],
        )
        assert len(rows) == 1
        assert _decode(rows.iloc[0]["changes"]) == [
            {"field": "name", "before": "阶段六角色", "after": "阶段六角色更新"},
            {"field": "description", "before": "before", "after": "after"},
        ]
    finally:
        if role_id:
            client.delete(f"/api/roles/{role_id}", headers=_admin_headers(pg))
            pg.execute("DELETE FROM audit_log WHERE target_id=%s", [role_id])
