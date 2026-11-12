"""阶段五 T5：审计采集接入。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.common.exceptions import AuthError
from backend.services.auth_service import AuthService

_SECRET = "unit-test-stage5-audit-collection-0123456789"


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


def _clear_collection_audit(pg) -> None:
    pg.execute(
        "DELETE FROM audit_log WHERE "
        "path IN ('/api/data/settings', '/api/stocks', '/api/audit') "
        "OR (event_category='security' AND actor_account='missing_stage5_user')"
    )


def test_stage5_controlled_api_request_records_api_audit(client, pg, app_cfg):
    _clear_collection_audit(pg)
    resp = client.get("/api/data/settings", headers=_admin_headers(pg))
    assert resp.status_code == 200

    rows = pg.query_df(
        "SELECT event_category, event_type, resource_code, action, result, status, "
        "actor_user_id, tenant_id, method, path, context "
        "FROM audit_log WHERE event_category='api' AND path='/api/data/settings' "
        "ORDER BY event_time DESC LIMIT 1"
    )
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["event_type"] == "api"
    assert row["resource_code"] == "data-settings:manage"
    assert row["action"] == "request"
    assert row["result"] == "success"
    assert row["status"] == "completed"
    assert row["actor_user_id"] == "admin"
    assert row["tenant_id"] == "default"
    assert row["method"] == "GET"


def test_stage5_auth_reject_records_security_audit(client, pg):
    _clear_collection_audit(pg)
    resp = client.get("/api/stocks")
    assert resp.status_code == 401

    rows = pg.query_df(
        "SELECT event_category, event_type, action, result, status, path "
        "FROM audit_log WHERE event_category='security' AND path='/api/stocks' "
        "ORDER BY event_time DESC LIMIT 1"
    )
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["event_type"] == "auth_required"
    assert row["action"] == "authenticate"
    assert row["result"] == "failed"
    assert row["status"] == "blocked"


def test_stage5_audit_api_does_not_record_recursive_api_event(client, pg):
    _clear_collection_audit(pg)
    resp = client.get("/api/audit", headers=_admin_headers(pg))
    assert resp.status_code == 200

    rows = pg.query_df(
        "SELECT count(*) AS n FROM audit_log WHERE event_category='api' AND path='/api/audit'"
    )
    assert int(rows.iloc[0]["n"]) == 0


def test_stage5_login_failure_records_security_audit(pg, redis_cli):
    account = f"missing_stage5_user_{uuid.uuid4().hex[:8]}"
    with pytest.raises(AuthError):
        AuthService().login(
            account,
            "WrongPass1",
            ip="stage5-login-ip",
        )

    rows = pg.query_df(
        "SELECT event_category, event_type, action, result, status, actor_account, ip "
        "FROM audit_log WHERE event_category='security' "
        "AND actor_account=%s ORDER BY event_time DESC LIMIT 1",
        [account],
    )
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["event_type"] == "login"
    assert row["action"] == "login"
    assert row["result"] == "failed"
    assert row["status"] == "failed"
    assert row["ip"] == "stage5-login-ip"


def test_stage5_task_status_change_records_task_audit(pg):
    task_id = "stage5_task_audit"
    pg.execute("DELETE FROM audit_log WHERE target_id=%s", [task_id])

    from backend.services.async_task import AsyncTaskService

    AsyncTaskService._audit_task(
        action="finish",
        result="success",
        status="done",
        task_id=task_id,
        task_type="verify",
    )

    rows = pg.query_df(
        "SELECT event_category, event_type, action, result, status, target_type, target_id, context "
        "FROM audit_log WHERE target_id=%s ORDER BY event_time DESC LIMIT 1",
        [task_id],
    )
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["event_category"] == "task"
    assert row["event_type"] == "task"
    assert row["action"] == "finish"
    assert row["result"] == "success"
    assert row["status"] == "done"
    assert row["target_type"] == "async_task"


def test_stage5_scheduler_skip_and_failure_record_task_audit(pg, monkeypatch):
    pg.execute(
        "DELETE FROM audit_log WHERE target_id IN (%s,%s)",
        ["stage5_job_skip", "stage5_job_fail"],
    )

    from backend.scheduler import scheduler

    class FakeJobService:
        def get(self, job_id):
            return {
                "id": job_id,
                "name": "阶段五调度审计",
                "enabled": True,
                "trading_day_only": job_id == "stage5_job_skip",
                "task_type": "update",
                "params": {},
            }

        def set_last_run(self, job_id, tid):  # noqa: ARG002
            raise AssertionError("skip/failure path should not set last run")

    class FailingTaskService:
        def create(self, *args, **kwargs):  # noqa: ARG002
            raise RuntimeError("scheduler down")

    monkeypatch.setattr(scheduler, "ScheduledJobService", FakeJobService)
    monkeypatch.setattr(scheduler, "_is_trading_day", lambda d: False)  # noqa: ARG005
    scheduler._fire_job("stage5_job_skip")

    import backend.services.async_task as async_task_module

    monkeypatch.setattr(scheduler, "_is_trading_day", lambda d: True)  # noqa: ARG005
    monkeypatch.setattr(async_task_module, "AsyncTaskService", FailingTaskService)
    scheduler._fire_job("stage5_job_fail")

    rows = pg.query_df(
        "SELECT event_category, event_type, action, result, status, target_id, error_summary "
        "FROM audit_log WHERE target_id IN (%s,%s) ORDER BY target_id, event_time",
        ["stage5_job_fail", "stage5_job_skip"],
    )
    by_target = {r["target_id"]: r for _, r in rows.iterrows()}
    assert by_target["stage5_job_skip"]["event_category"] == "task"
    assert by_target["stage5_job_skip"]["event_type"] == "scheduler"
    assert by_target["stage5_job_skip"]["action"] == "skip"
    assert by_target["stage5_job_skip"]["status"] == "skipped"
    assert by_target["stage5_job_fail"]["event_type"] == "scheduler"
    assert by_target["stage5_job_fail"]["action"] == "trigger"
    assert by_target["stage5_job_fail"]["result"] == "failed"
    assert by_target["stage5_job_fail"]["status"] == "failed"


def test_stage5_rbac_management_records_domain_audit(client, pg):
    code = f"stage5_rbac_{uuid.uuid4().hex[:8]}"
    role_id = None
    pg.execute("DELETE FROM audit_log WHERE target_id=%s", [code])
    try:
        resp = client.post(
            "/api/roles",
            headers=_admin_headers(pg),
            json={"code": code, "name": "阶段五RBAC审计"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        role_id = resp.json()["data"]["id"]

        rows = pg.query_df(
            "SELECT event_category, event_type, action, resource_code, target_type, "
            "target_id, actor_user_id, tenant_id, context "
            "FROM audit_log WHERE target_id=%s AND event_category='rbac' "
            "ORDER BY event_time DESC LIMIT 1",
            [role_id],
        )
        assert len(rows) == 1
        row = rows.iloc[0]
        assert row["event_type"] == "rbac"
        assert row["action"] == "role_create"
        assert row["resource_code"] == "role:create"
        assert row["target_type"] == "sys_role"
        assert row["actor_user_id"] == "admin"
        assert row["tenant_id"] == "default"
    finally:
        if role_id:
            pg.execute("DELETE FROM audit_log WHERE target_id=%s", [role_id])
            pg.execute("DELETE FROM sys_role WHERE id=%s", [role_id])
