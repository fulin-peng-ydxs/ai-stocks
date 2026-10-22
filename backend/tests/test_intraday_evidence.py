from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from backend.services import eod_dates
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_contract import REQUIRED_TIMES
from backend.services.intraday_evidence import IntradayEvidence, missing_ranges
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_archive import CODE, DAY, Context, Windows, window
from backend.tests.test_intraday_archive import db as db
from backend.tests.test_intraday_quotes import _frame
from backend.tests.test_intraday_source import request_settings as request_settings


def _boundary(db, monkeypatch, first_points=81):
    """真实 1970 点形态：八个后续交易日加首日尾段，含本地尚未入库的新日。"""
    days = pd.bdate_range("2026-09-01", "2026-09-11")
    db.execute("DELETE FROM trade_calendar")
    with db.temp_view(pd.DataFrame({"trade_date": days.date, "is_open": True})) as view:
        db.execute(f"INSERT INTO trade_calendar SELECT * FROM {view}")
    db.execute("UPDATE stock_basic SET list_date='2026-09-01'")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-01',3.6)", [CODE])
    db.execute(
        "INSERT INTO stock_intraday_monitor(code,monitoring_start) VALUES (?,'2026-09-01')", [CODE]
    )
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 11, 16, tzinfo=eod_dates.SHANGHAI)
    )
    frames = [_frame(d.date()) for d in days]
    frames = [f[f.timestamp.dt.strftime("%H:%M").isin(REQUIRED_TIMES)] for f in frames]
    frames[0] = frames[0].tail(first_points)
    # 始终 1970 点；首日更短时，后续日已新增更多分钟。
    frames[1] = frames[1].iloc[first_points - 66 :]
    payload = IntradaySourceService._frame_to_window(pd.concat(frames), "sina")
    payload["fetched_at"] = "2026-09-11T08:00:00+00:00"
    assert len(payload["rows"]) == 1970
    IntradayEvidence(db).record(CODE, [{**payload, "source": "ths", "request_years": [2026]}])
    return payload


def test_boundary_archive_retained_manual_recheck_and_automatic_skip(db, monkeypatch):
    payload = _boundary(db, monkeypatch)
    q = Windows([payload])
    archive = IntradayArchiveService(db, quotes=q)
    params = {"mode": "refetch", "codes": [CODE], "date_start": "2026-09-01"}
    archive.collect(params)
    before = archive.read(CODE, "2026-09-01")
    assert len(before["rows"]) == 81
    old_issue = (
        db.query_df("SELECT id FROM data_quality_issue WHERE trade_date='2026-09-01'").iloc[0].id
    )
    second = archive.collect(params, allow_fallback=True)
    assert second["out_of_range"] == 1 and len(q.calls) == 1
    q.windows = [_boundary_payload(70, payload)]
    archive.collect(params, allow_fallback=True, recheck_source=True)
    after = archive.read(CODE, "2026-09-01")
    assert len(q.calls) == 2 and after["rows"] == before["rows"]
    assert after["revision"] == before["revision"]
    row = db.query_df(
        "SELECT id,status,detail FROM data_quality_issue WHERE trade_date='2026-09-01'"
    ).iloc[0]
    assert row.id == old_issue and row.status == "open"
    detail = json.loads(row.detail)
    assert detail["availability"]["can_repair"] is False
    assert detail["reason_code"] == "window_truncated"
    assert detail["coverage"]["covered_count"] == 81
    assert detail["coverage"]["missing_ranges"] == ["09:31–11:30", "13:01–13:37"]
    assert (
        db.query_df("SELECT monitoring_start FROM stock_intraday_monitor")
        .iloc[0, 0]
        .date()
        .isoformat()
        == "2026-09-01"
    )
    archive.collect(params, allow_fallback=True)
    assert len(q.calls) == 2


def _boundary_payload(count, original):
    rows = [r for r in original["rows"] if r[0][:10] != "2026-09-01"]
    old = [r for r in original["rows"] if r[0][:10] == "2026-09-01"][-count:]
    # 多出的后续分钟只影响来源范围证据，不写入目标日期。
    extra = [r for r in window(day="2026-09-02")["rows"] if r[0] not in {x[0] for x in rows}]
    combined = old + rows + extra[: 81 - count]
    combined.sort(key=lambda r: r[0])
    assert len(combined) == 1970
    return {**original, "rows": combined, "raw_first": combined[0][0], "raw_last": combined[-1][0]}


def test_errors_keep_last_success_but_do_not_prove_unavailability(db):
    evidence = IntradayEvidence(db)
    payload = window(rows=10)
    evidence.record(CODE, [payload])
    first = evidence.load([CODE])[(CODE, "sina")]["evidence"]
    evidence.record(CODE, [], {"sina": {"outcome": "error", "error": "TimeoutError"}})
    state = evidence.load([CODE])
    assert state[(CODE, "sina")]["evidence"] == first
    assert evidence.assess(CODE, DAY, ["15:00"], state)["can_repair"]


def test_short_response_and_tail_not_ready_remain_retryable(db):
    evidence = IntradayEvidence(db)
    evidence.record(CODE, [window(rows=10)])
    assert evidence.assess(CODE, DAY, ["15:00"], evidence.load())["can_repair"]
    assert missing_ranges(["11:29", "11:30", "13:01", "15:00"]) == ["11:29–11:30", "13:01", "15:00"]


def test_old_session_evidence_requires_new_verification(db, monkeypatch):
    payload = _boundary(db, monkeypatch)
    evidence = IntradayEvidence(db)
    evidence.record(CODE, [payload])
    missing = sorted(
        REQUIRED_TIMES - {r[0][11:16] for r in payload["rows"] if r[0][:10] == "2026-09-01"}
    )
    assert not evidence.assess(CODE, "2026-09-01", missing, evidence.load())["can_repair"]
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-14',true)")
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 14, 16, tzinfo=eod_dates.SHANGHAI)
    )
    latest = IntradayEvidence(db)
    result = latest.assess(CODE, "2026-09-01", missing, latest.load())
    assert result["status"] == "needs_verification" and result["can_repair"]


def test_batch_repair_same_stock_uses_one_window_and_retains_issue_identity(db, monkeypatch):
    from backend.services import async_task, intraday_source
    from backend.services.data_report import DataIntegrityReport

    db.execute("UPDATE stock_basic SET list_date='2026-09-09'")
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-09',3.6)", [CODE])
    q = Windows([window(day="2026-09-09", rows=10), window(rows=10)])
    archive = IntradayArchiveService(db, quotes=q)
    archive.collect()
    ids = db.query_df(
        "SELECT id FROM data_quality_issue WHERE issue_type='intraday_partial'"
    ).id.tolist()
    assert len(ids) == 2
    q.windows = [window(day="2026-09-09"), window()]
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    ctx = Context()
    result = async_task._h_fix({"issue_ids": ids}, ctx)
    assert result["ok"] and result["resolved"] == 2
    assert len(q.calls) == 2  # 首次采集一次 + 批量修复一次
    assert set(db.query_df("SELECT id FROM data_quality_issue").id) == set(ids)
    assert set(db.query_df("SELECT status FROM data_quality_issue").status) == {"resolved"}
    assert "疑源端口径" not in result["message"]
    assert DataIntegrityReport(db).recheck_clean("intraday_partial", CODE, DAY)


def test_unavailable_repair_is_not_technical_failure_or_self_retry(db, monkeypatch):
    from backend.services import async_task, intraday_source

    payload = _boundary(db, monkeypatch)
    q = Windows([payload])
    archive = IntradayArchiveService(db, quotes=q)
    archive.collect({"mode": "refetch", "codes": [CODE], "date_start": "2026-09-01"})
    ids = db.query_df("SELECT id FROM data_quality_issue WHERE trade_date='2026-09-01'").id.tolist()
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    result = async_task._h_fix({"issue_ids": ids}, Context())
    assert not result["ok"] and result["unavailable"] == 1
    assert result["failed"] == result["technical_failure"] == 0
    assert result["retryable"] is False and len(q.calls) == 1
    detail = json.loads(
        db.query_df("SELECT detail FROM data_quality_issue WHERE id=?", ids).iloc[0, 0]
    )
    assert detail["last_repair"]["outcome"] == "unavailable"
    archive.sync([CODE])
    detail2 = json.loads(
        db.query_df("SELECT detail FROM data_quality_issue WHERE id=?", ids).iloc[0, 0]
    )
    assert detail2["last_repair"] == detail["last_repair"]


def test_repair_cancel_resume_freezes_ids_and_does_not_repeat_completed_stock(db, monkeypatch):
    import pytest

    from backend.services import async_task, intraday_source
    from backend.services.async_task import TaskCancelled
    from backend.services.data_report import DataIntegrityReport

    second = "600001.SH"
    db.execute("INSERT INTO stock_basic(code,name,list_date) VALUES (?,'第二股',?)", [second, DAY])
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,?,3.6)", [second, DAY])
    q = Windows([window(rows=10)])
    IntradayArchiveService(db, quotes=q).collect()
    q.windows = [window()]
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)

    class Cancelling(Context):
        def set_phase(self, phase, **data):
            super().set_phase(phase, **data)
            if phase == "fix_issue" and data.get("phase_done") == 1:
                self.cancel = True

    ctx = Cancelling()
    with pytest.raises(TaskCancelled):
        async_task._h_fix({"issue_type": "intraday_partial"}, ctx)
    # 并发请求可能已返回，但取消后仅完成归档收口的股票进入检查点。
    assert len(q.calls) == 4
    frozen = list(ctx.checkpoint["fix_scope_ids"])
    DataIntegrityReport(db)._insert_issues(
        [
            {
                "code": "600002.SH",
                "trade_date": DAY,
                "issue_type": "intraday_partial",
                "detail": "{}",
            }
        ]
    )
    resumed = Context()
    resumed.checkpoint = json.loads(json.dumps(ctx.checkpoint))
    result = async_task._h_fix({"issue_type": "intraday_partial"}, resumed)
    assert result["ok"] and len(q.calls) == 5
    assert q.calls[-1][0] == second  # 已完成股票不重复取源，未落库的在途结果正常重试。
    assert resumed.checkpoint["fix_scope_ids"] == frozen
    assert (
        db.query_df("SELECT status FROM data_quality_issue WHERE code='600002.SH'").iloc[0, 0]
        == "open"
    )
    assert len(getattr(resumed, "_intraday_repair_cache", {})) <= 1


def test_intraday_only_verify_uses_shared_scan_without_network(db, monkeypatch):
    from types import SimpleNamespace

    from backend.services import async_task, intraday_source

    archive = IntradayArchiveService(db, quotes=Windows([window(rows=10)]))
    archive.collect()
    before_id = db.query_df("SELECT id FROM data_quality_issue").iloc[0, 0]
    monkeypatch.setattr(
        intraday_source,
        "IntradaySourceService",
        lambda **kw: (_ for _ in ()).throw(AssertionError("no source")),
    )
    ctx = Context()
    ctx.svc = SimpleNamespace(market=db)
    result = async_task._h_verify({"scope": "intraday"}, ctx)
    assert result["quality"]["intraday"]["intraday_partial"] == 1
    assert db.query_df("SELECT id FROM data_quality_issue").iloc[0, 0] == before_id


def test_redis_failure_after_primary_does_not_discard_obtained_candidate(db, monkeypatch):
    import redis

    from backend.tests.test_intraday_quotes import _Redis
    from backend.tests.test_intraday_source import _service

    class Cache(_Redis):
        source_locks = 0

        def eval(self, script, keys, key, interval):
            self.source_locks += 1
            if self.source_locks > 1:
                raise redis.ConnectionError("protection unavailable")
            return super().eval(script, keys, key, interval)

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            assert provider == "sina"
            return _frame(rows=10)

    q = _service(Cache(), Source)
    result = IntradayArchiveService(db, quotes=q).collect(allow_fallback=True)
    assert result["failed"] == 1 and result["inserted"] == 1
    assert len(IntradayArchiveService(db).read(CODE, DAY)["rows"]) == 10
    assert db.query_df("SELECT source FROM stock_intraday_source_state").source.tolist() == ["sina"]


def test_shared_response_that_expands_range_improves_previously_blocked_day(db, monkeypatch):
    payload = _boundary(db, monkeypatch)
    q = Windows([payload])
    archive = IntradayArchiveService(db, quotes=q)
    archive.collect({"mode": "refetch", "codes": [CODE], "date_start": "2026-09-01"})
    q.windows = [window(day="2026-09-01"), window()]
    result = archive.collect(
        {"mode": "refetch", "codes": [CODE], "date_start": "2026-09-01", "date_end": DAY}
    )
    assert len(q.calls) == 2
    assert len(archive.read(CODE, "2026-09-01")["rows"]) == 240
    assert archive.clean("intraday_partial", CODE, "2026-09-01")
    assert result["out_of_range"] == 0


def test_boundary_and_interior_hole_do_not_trigger_identical_automatic_requests(db, monkeypatch):
    payload = _boundary(db, monkeypatch)
    rows = [r for r in payload["rows"] if r[0] != "2026-09-01 14:21:00"]
    extra = next(r for r in window(day="2026-09-01")["rows"] if r[0] == "2026-09-01 13:37:00")
    rows.append(extra)
    rows.sort(key=lambda r: r[0])
    payload.update(rows=rows, raw_first=rows[0][0])
    q = Windows([payload])
    archive = IntradayArchiveService(db, quotes=q)
    params = {"mode": "refetch", "codes": [CODE], "date_start": "2026-09-01"}
    archive.collect(params)
    result = archive.collect(params, allow_fallback=True)
    assert result["out_of_range"] == 1 and len(q.calls) == 1
    issue = next(r for r in archive.issues() if str(r["trade_date"]) == "2026-09-01")
    detail = json.loads(issue["detail"])
    assert "14:21" in detail["coverage"]["missing_times"]
    assert not detail["availability"]["can_repair"]
    assert detail["reason_code"] == "window_truncated"


def test_prior_day_known_hole_can_try_backup_but_current_day_keeps_retrying(db):
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    yesterday = _frame(pd.Timestamp("2026-09-09").date())
    today = _frame()
    frames = pd.concat([yesterday, today])
    frames = frames[frames.timestamp.dt.strftime("%H:%M").ne("11:07")]
    payload = IntradaySourceService._frame_to_window(frames, "sina")
    payload["fetched_at"] = "2026-09-10T08:00:00+00:00"
    evidence = IntradayEvidence(db)
    evidence.record(CODE, [payload])
    states = evidence.load()
    old = evidence.assess(CODE, "2026-09-09", ["11:07"], states, allow_fallback=False)
    assert not old["can_repair"] and old["reason_code"] == "source_missing_minutes"
    backup = evidence.assess(CODE, "2026-09-09", ["11:07"], states)
    assert backup["providers"] == ["ths", "eastmoney"]
    assert evidence.assess(CODE, DAY, ["11:07"], states, allow_fallback=False)["can_repair"]


def test_new_backup_is_not_blocked_by_primary_boundary_and_logs_exact_eastmoney_reason(db, monkeypatch):
    payload = _boundary(db, monkeypatch)
    db.execute("DELETE FROM stock_intraday_source_state WHERE source='ths'")
    evidence = IntradayEvidence(db)
    evidence.record(CODE, [payload])
    missing = sorted(REQUIRED_TIMES - {r[0][11:16] for r in payload["rows"]
                                      if r[0][:10] == "2026-09-01"})
    result = evidence.assess(CODE, "2026-09-01", missing, evidence.load())
    assert result["providers"] == ["ths"] and result["can_repair"]
    decision = {r["source"]: r for r in result["decisions"]}
    assert not decision["eastmoney"]["request"]
    assert "2026-09-07～2026-09-11" in decision["eastmoney"]["reason"]
    assert "不在该接口近5交易日范围" in decision["eastmoney"]["reason"]
    forced = evidence.assess(CODE, "2026-09-01", missing, evidence.load(), recheck=True)
    assert forced["providers"] == ["sina", "ths"]


def test_ths_actual_year_response_bounds_prevent_repeated_uncovered_requests(db, monkeypatch):
    _boundary(db, monkeypatch)
    evidence = IntradayEvidence(db)
    payload = window(day="2026-09-02", provider="ths")
    payload.update(request_years=[2026], fetched_at="2026-09-11T08:00:00+00:00")
    evidence.record(CODE, [payload])
    result = evidence.assess(CODE, "2026-09-01", ["09:31"], evidence.load())
    ths = next(r for r in result["decisions"] if r["source"] == "ths")
    assert not ths["request"] and "最近年度响应从 2026-09-02" in ths["reason"]
    assert "ths" not in result["providers"]
    assert "ths" in evidence.assess(CODE, "2026-09-01", ["09:31"], evidence.load(),
                                   recheck=True)["providers"]


def test_repair_prefers_ths_replaces_whole_day_and_closes_only_after_recheck(db, monkeypatch):
    from backend.services import async_task, intraday_source
    from backend.tests.test_intraday_quotes import _Redis
    from backend.tests.test_intraday_source import _service

    IntradayArchiveService(db, quotes=Windows([window(rows=81)])).collect()
    issue = int(db.query_df("SELECT id FROM data_quality_issue").iloc[0, 0])
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            if provider == "eastmoney":
                raise ConnectionError("backup unavailable")
            return _frame(rows=81 if provider == "sina" else 240)

    q = _service(_Redis(), Source)
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    result = async_task._h_fix({"issue_ids": [issue], "recheck_source": True}, Context())
    assert result["ok"] and result["resolved"] == 1 and result["technical_failure"] == 0
    assert calls == ["sina", "ths"]
    archived = IntradayArchiveService(db).read(CODE, DAY)
    assert len(archived["rows"]) == 240 and archived["source"] == "ths"
    assert db.query_df("SELECT status FROM data_quality_issue").iloc[0, 0] == "resolved"
    assert db.query_df("SELECT DISTINCT source FROM stock_intraday_bar").source.tolist() == ["ths"]


def test_unresolved_repair_explains_missing_minute_source_end_and_request_error(db, monkeypatch):
    from backend.services import async_task, intraday_source
    from backend.tests.test_intraday_source import _service

    partial = _frame()
    partial = partial[partial.timestamp.dt.strftime("%H:%M").ne("10:32")]
    saved = IntradaySourceService._frame_to_window(partial, "sina")
    saved["fetched_at"] = "2026-09-10T08:00:00+00:00"
    IntradayArchiveService(db, quotes=Windows([saved])).collect()
    issue = int(db.query_df("SELECT id FROM data_quality_issue").iloc[0, 0])
    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None, request_year=None):
            calls.append(provider)
            if provider == "sina":
                return partial
            if provider == "ths":
                return _frame(pd.Timestamp("2026-09-09").date())
            raise ConnectionError("RemoteDisconnected: endpoint closed")

    q = _service(factory=Source)
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    monkeypatch.setattr(async_task, "get_client", lambda: db)
    monkeypatch.setattr("backend.services.ingest.IngestionService", lambda: None)
    ctx = Context()
    result = async_task._h_fix({"issue_ids": [issue], "recheck_source": True}, ctx)
    assert not result["ok"] and result["technical_failure"] == 1
    assert calls == ["sina", "ths", "eastmoney", "eastmoney"]
    for text in (DAY, "10:32", "2026-09-09 15:00:00", "RemoteDisconnected", "保持待处理"):
        assert text in result["message"]
    row = db.query_df("SELECT status,detail FROM data_quality_issue WHERE id=?", [issue]).iloc[0]
    assert row.status == "open"
    assert "RemoteDisconnected" in json.loads(row.detail)["availability"]["reason"]
    assert len(IntradayArchiveService(db).read(CODE, DAY)["rows"]) == 239
