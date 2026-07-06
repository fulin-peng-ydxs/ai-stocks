"""阶段六 T3：审计日志保留期自动清理。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.services.audit_service import AuditService
from backend.storage.audit_repository import AuditRepository


def _insert_audit(pg, audit_id: str, event_time: datetime) -> None:
    pg.execute(
        """
        INSERT INTO audit_log (
            id, event_time, event_category, event_type, action, target_type,
            target_id, target_label, result, status, context
        ) VALUES (
            %s, %s, 'api', 'api', 'request', 'stage6_cleanup_test',
            %s, %s, 'success', 'completed', '{}'::jsonb
        )
        """,
        [audit_id, event_time, audit_id, audit_id],
    )


def _exists(pg, audit_id: str) -> bool:
    df = pg.query_df("SELECT 1 FROM audit_log WHERE id=%s", [audit_id])
    return not df.empty


def _cleanup_test_rows(pg, *cutoffs: str | None) -> None:
    pg.execute("DELETE FROM audit_log WHERE target_type='stage6_cleanup_test'")
    for cutoff in [c for c in cutoffs if c]:
        pg.execute(
            "DELETE FROM audit_log WHERE event_type='audit_cleanup' AND context->>'cutoff'=%s",
            [cutoff],
        )
    pg.execute(
        "DELETE FROM audit_log WHERE event_type='audit_cleanup' "
        "AND context->>'reason' IN ('invalid_retention_days', 'invalid_retention_config')"
    )


def test_stage6_audit_cleanup_deletes_only_records_before_cutoff(pg, monkeypatch):
    fixed_now = datetime(2001, 1, 1, tzinfo=timezone.utc)
    retention_days = 90
    cutoff = fixed_now - timedelta(days=retention_days)
    cutoff_text = cutoff.isoformat()
    monkeypatch.setattr(
        "backend.services.audit_service.get_effective_settings",
        lambda: SimpleNamespace(audit=SimpleNamespace(retention_days=retention_days)),
    )
    _cleanup_test_rows(pg, cutoff_text)
    _insert_audit(pg, "stage6_cleanup_old", cutoff - timedelta(seconds=1))
    _insert_audit(pg, "stage6_cleanup_recent", cutoff)

    try:
        svc = AuditService(AuditRepository(pg))
        result = svc.cleanup_expired(now=fixed_now)
        second = svc.cleanup_expired(now=fixed_now)

        assert result["ok"] is True
        assert result["skipped"] is False
        assert result["affected_count"] == 1
        assert result["cutoff"] == cutoff_text
        assert second["affected_count"] == 0
        assert not _exists(pg, "stage6_cleanup_old")
        assert _exists(pg, "stage6_cleanup_recent")

        audit_rows = pg.query_df(
            """
            SELECT count(*) AS n
            FROM audit_log
            WHERE event_type='audit_cleanup'
              AND status='completed'
              AND context->>'cutoff'=%s
              AND context->>'retention_days'=%s
            """,
            [cutoff_text, str(retention_days)],
        )
        assert int(audit_rows.iloc[0]["n"]) >= 2
    finally:
        _cleanup_test_rows(pg, cutoff_text)


def test_stage6_audit_cleanup_skips_invalid_retention_without_delete(pg, monkeypatch):
    fixed_now = datetime(2001, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "backend.services.audit_service.get_effective_settings",
        lambda: SimpleNamespace(audit=SimpleNamespace(retention_days=0)),
    )
    _cleanup_test_rows(pg, None)
    _insert_audit(pg, "stage6_cleanup_invalid_retention", fixed_now - timedelta(days=365))

    try:
        result = AuditService(AuditRepository(pg)).cleanup_expired(now=fixed_now)

        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "invalid_retention_days"
        assert result["affected_count"] == 0
        assert _exists(pg, "stage6_cleanup_invalid_retention")
    finally:
        _cleanup_test_rows(pg, None)


def test_stage6_audit_cleanup_scheduler_registers_platform_job_once():
    from backend.scheduler import scheduler

    scheduler.shutdown_scheduler()
    try:
        scheduler.register_platform_jobs()
        first_scheduler = scheduler._scheduler
        scheduler.register_platform_jobs()

        assert scheduler._scheduler is first_scheduler
        assert scheduler._scheduler is not None
        assert scheduler._scheduler.running is True
        assert scheduler._scheduler.get_job("platform.audit_cleanup") is not None
        assert len(
            [
                job for job in scheduler._scheduler.get_jobs()
                if job.id == "platform.audit_cleanup"
            ]
        ) == 1
    finally:
        scheduler.shutdown_scheduler()
