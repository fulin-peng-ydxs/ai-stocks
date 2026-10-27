"""分时主源归档、定向补齐、等待源更新与续跑的真实任务入口回归。"""

import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.config.settings import Settings
from backend.datasource.observability import RequestTracker, observe_work, record
from backend.services import (
    async_task,
    eod_dates,
    intraday_archive,
    intraday_evidence,
    intraday_source,
)
from backend.services.async_task import TaskCancelled
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_contract import rows_for_day, sanitize_minutes
from backend.services.intraday_evidence import IntradayEvidence
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_archive import CODE, DAY, Context, Windows, window
from backend.tests.test_intraday_archive import db as db  # noqa: PLC0414
from backend.tests.test_intraday_quotes import _frame, _Redis
from backend.tests.test_intraday_source import request_settings as request_settings  # noqa: PLC0414


@pytest.fixture
def pipeline(db, monkeypatch):
    cfg = Settings()
    cfg.datasource.update_concurrency = cfg.datasource.max_retries = 1
    monkeypatch.setattr(intraday_archive, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(intraday_source, "get_effective_settings", lambda: cfg)
    monkeypatch.setattr(intraday_evidence, "get_request_settings", lambda: cfg)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    clock = [datetime(2026, 9, 10, 16, tzinfo=eod_dates.SHANGHAI)]
    monkeypatch.setattr(eod_dates, "shanghai_now", lambda: clock[0])

    class SourceClock:
        @staticmethod
        def now(tz):
            return clock[0].astimezone(tz)

    monkeypatch.setattr(intraday_source, "datetime", SourceClock)
    calls = []
    frames = {"sina": _frame(rows=10), "ths": _frame()}
    before_request = []

    class Transport:
        def get_intraday_1m(self, code, provider, **kwargs):
            calls.append((code, provider))
            for hook in before_request:
                hook(provider)
            record(requests=1, network_seconds=0.001)
            frame = frames[provider]
            if isinstance(frame, Exception):
                raise frame
            return frame.copy()

    cache = _Redis()
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kwargs:
                        IntradaySourceService(redis_client=cache, source_factory=Transport, **kwargs))

    def context():
        ctx = Context()
        ctx.svc = SimpleNamespace(market=db)
        ctx.request_tracker = RequestTracker()
        return ctx

    return SimpleNamespace(cfg=cfg, calls=calls, frames=frames, clock=clock,
                           hooks=before_request, context=context)


def test_task_archives_primary_before_backup_and_reports_real_requests(db, pipeline):
    def archived(provider):
        if provider == "ths":
            assert db.query_df("SELECT count(*) FROM stock_intraday_bar").iloc[0, 0] == 10
    pipeline.hooks.append(archived)
    ctx = pipeline.context()
    with observe_work(ctx.request_tracker):
        result = async_task._h_intraday_ingest({"codes": [CODE]}, ctx)
    assert result["ok"] and result["partial"] == result["deferred"] == 0
    assert result["updated"] == 1 and result["quality"]["intraday_partial"] == 0
    assert pipeline.calls == [(CODE, "sina"), (CODE, "ths")]
    assert ctx.request_tracker.snapshot()["requests"] == 2
    assert db.query_df("SELECT DISTINCT source FROM stock_intraday_bar").source.tolist() == ["ths"]
    assert db.query_df("SELECT status FROM data_quality_issue").status.tolist() == ["resolved"]


def test_complete_primary_never_requests_backup(db, pipeline):
    pipeline.frames["sina"] = _frame()
    result = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert result["ok"] and pipeline.calls == [(CODE, "sina")]
    assert "supplement" not in result


def test_not_ready_is_deferred_without_repeated_requests_and_expires(db, pipeline):
    pipeline.frames["ths"] = _frame(rows=20)
    result = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert result["ok"] and result["partial"] == result["deferred"] == 1
    assert result["out_of_range"] == 0
    assert db.query_df("SELECT status FROM data_quality_issue").iloc[0, 0] == "open"
    first_calls = len(pipeline.calls)
    repeat = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert repeat["deferred"] == 1 and len(pipeline.calls) == first_calls
    issue = json.loads(db.query_df("SELECT detail FROM data_quality_issue").iloc[0, 0])
    assert issue["availability"]["retryable"]
    assert issue["availability"]["next_retry_at"] == "2026-09-10T16:15:00+08:00"
    pipeline.clock[0] = datetime(2026, 9, 10, 16, 16, tzinfo=eod_dates.SHANGHAI)
    pipeline.frames["ths"] = _frame()
    finished = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert finished["ok"] and finished["partial"] == finished["deferred"] == 0
    assert len(pipeline.calls) > first_calls


def test_manual_recheck_bypasses_wait_and_failure_is_not_throttled(db, pipeline):
    pipeline.frames["ths"] = _frame(rows=20)
    async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    count = len(pipeline.calls)
    ctx = pipeline.context()
    result = async_task._h_fix({"issue_type": "intraday_partial"}, ctx)
    assert result["deferred"] == 1 and result["retryable"] and len(pipeline.calls) == count
    assert ctx.checkpoint["phase_done"] == 1 and ctx.checkpoint["issue_done_ids"] == []
    pipeline.frames["ths"] = ConnectionError("temporary disconnect")
    async_task._h_fix({"issue_type": "intraday_partial", "recheck_source": True}, pipeline.context())
    evidence = IntradayEvidence(db)
    assert "ths" in evidence.assess(CODE, DAY, ["15:00"], evidence.load())["providers"]
    pipeline.frames["ths"] = _frame()
    final = async_task._h_fix({"issue_type": "intraday_partial", "recheck_source": True}, pipeline.context())
    assert final["ok"]


def test_after_midnight_latest_closed_day_still_defers_unready_source(db, pipeline):
    """交易日历已有次日时，凌晨补昨日数据仍须按最近收盘日等待源更新。"""
    pipeline.clock[0] = datetime(2026, 9, 11, 1, tzinfo=eod_dates.SHANGHAI)
    pipeline.frames["ths"] = _frame(rows=20)
    first = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert first["deferred"] == 1
    calls = len(pipeline.calls)
    repeated = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert repeated["deferred"] == 1 and len(pipeline.calls) == calls


def test_existing_evidence_instance_observes_time_and_configuration_changes(db, pipeline):
    payload = window(rows=10)
    payload["fetched_at"] = pipeline.clock[0].astimezone(eod_dates.SHANGHAI).isoformat()
    evidence = IntradayEvidence(db)
    evidence.record(CODE, [payload])
    states = evidence.load()
    assert evidence.assess(CODE, DAY, ["15:00"], states, allow_fallback=False)["status"] == "deferred"
    pipeline.cfg.intraday.source_recheck_interval_sec = 0
    assert evidence.assess(CODE, DAY, ["15:00"], states, allow_fallback=False)["can_repair"]
    pipeline.cfg.intraday.source_recheck_interval_sec = 900
    pipeline.clock[0] = datetime(2026, 9, 10, 16, 16, tzinfo=eod_dates.SHANGHAI)
    assert evidence.assess(CODE, DAY, ["15:00"], states, allow_fallback=False)["can_repair"]


@pytest.mark.parametrize("value", [-1, 0.5, 86401, True])
def test_recheck_interval_configuration_rejects_invalid_values(value):
    from backend.storage.app_config import ConfigValidationError, _coerce, get_field_meta

    with pytest.raises(ConfigValidationError):
        _coerce(get_field_meta("intraday.source_recheck_interval_sec"), value)


def test_recheck_configuration_invalidates_request_snapshot(monkeypatch):
    from backend.config import request_snapshot
    from backend.storage.app_config import AppConfigRepo, _coerce, get_field_meta

    notifications = []
    monkeypatch.setattr(request_snapshot, "invalidate_request_settings", lambda: notifications.append(1))
    meta = get_field_meta("intraday.source_recheck_interval_sec")
    assert _coerce(meta, 0) == 0 and _coerce(meta, 900) == 900
    AppConfigRepo._invalidate_requests([meta["path"]])
    assert notifications == [1]


@pytest.mark.parametrize("old_ready", [False, True])
def test_all_requests_fail_cannot_become_success_from_old_archive(db, pipeline, old_ready):
    if old_ready:
        IntradayArchiveService(db, quotes=Windows([window()])).collect()
    pipeline.frames.update(sina=ConnectionError("sina failed"), ths=ConnectionError("ths failed"))
    ctx = pipeline.context()
    result = async_task._h_intraday_ingest(
        {"mode": "refetch", "codes": [CODE], "date_start": DAY}, ctx,
    )
    assert not result["ok"] and result["failed"] == 1
    assert CODE not in ctx.checkpoint["intraday_done"]
    assert CODE in ctx.checkpoint["intraday_failed"]
    if old_ready:
        assert db.query_df("SELECT count(*) FROM stock_intraday_bar").iloc[0, 0] == 240


def test_primary_error_is_warning_only_after_fresh_complete_backup(db, pipeline):
    pipeline.frames["sina"] = ConnectionError("sina failed")
    result = async_task._h_intraday_ingest({"codes": [CODE]}, pipeline.context())
    assert result["ok"] and result["failed"] == result["missing"] == 0
    assert result["errors"] and result["quality"]["intraday_gap"] == 0


def test_cancel_during_backup_keeps_primary_and_resume_only_supplements(db, pipeline):
    ctx = pipeline.context()
    def cancel(provider):
        if provider == "ths":
            ctx.cancel = True
    pipeline.hooks.append(cancel)
    with pytest.raises(TaskCancelled):
        async_task._h_intraday_ingest({"codes": [CODE]}, ctx)
    assert db.query_df("SELECT count(*) FROM stock_intraday_bar").iloc[0, 0] == 10
    assert ctx.checkpoint["intraday_done"] == [CODE]
    assert "定向补齐已成功完成 0/1 只" in async_task._resume_message("intraday_ingest", ctx.checkpoint)
    pipeline.hooks.clear()
    resumed = pipeline.context()
    resumed.checkpoint = json.loads(json.dumps(ctx.checkpoint))
    result = async_task._h_intraday_ingest({"codes": [CODE]}, resumed)
    assert result["ok"] and result["partial"] == 0
    assert [provider for _, provider in pipeline.calls].count("sina") == 1


def test_single_pass_cleaning_keeps_exact_daily_diagnostics():
    frame = _frame(rows=4)
    frame.loc[0, "open"] = 0
    frame.loc[1, "volume"] = -1
    frame.loc[2, "timestamp"] = pd.Timestamp(DAY + " 12:00")
    original = pd.concat([frame, frame.iloc[[3]]])
    diagnostics = {}
    clean, total = sanitize_minutes(original, day_diagnostics=diagnostics)
    assert diagnostics[DAY] == total == {
        "invalid_rows": 1, "off_session_rows": 1, "duplicate_rows": 1,
    }
    assert len(clean) == 2 and pd.isna(clean.iloc[0].open)


def test_daily_candidate_index_is_rebuilt_when_window_rows_are_replaced():
    original = window(rows=10)
    assert len(rows_for_day(original, DAY)) == 10
    selected = {**original, "rows": original["rows"][:3]}
    assert len(rows_for_day(selected, DAY)) == 3
    assert len(rows_for_day(original, DAY)) == 10
