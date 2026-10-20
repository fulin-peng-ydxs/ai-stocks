from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from backend.services import eod_dates
from backend.services.async_task import TaskCancelled
from backend.services.intraday_archive import IntradayArchiveService
from backend.services.intraday_contract import normalize_intraday_params, sanitize_minutes
from backend.services.intraday_quotes import IntradayQuoteService
from backend.services.intraday_source import IntradaySourceService
from backend.tests.test_intraday_quotes import _frame, _Redis
from backend.tests.test_intraday_source import request_settings as request_settings

CODE = "600000.SH"
DAY = "2026-09-10"


class Context:
    tid = "isolated_intraday"

    def __init__(self):
        self.checkpoint = {}
        self.cancel = False
        self.logs = []
        self.flushes = 0

    def set_checkpoint(self, **data):
        self.checkpoint.update(data)

    def check_cancel(self):
        if self.cancel:
            raise TaskCancelled()

    def set_phase(self, phase, **data):
        self.set_checkpoint(**data)

    def log(self, message, level="info"):
        self.logs.append((message, level))

    def flush(self):
        self.flushes += 1

    def progress(self, *args):
        self.flush()


class Windows:
    def __init__(self, windows):
        self.windows = windows
        self.calls = []
        self.fail = False

    def fetch_window(self, code, dates, **kwargs):
        self.calls.append((code, dates, kwargs))
        if self.fail:
            raise RuntimeError("offline")
        return {"candidates": self.windows}


def window(day=DAY, provider="sina", rows=240, close=None):
    frame = _frame(date.fromisoformat(day), rows)
    if close:
        frame["close"] = close
        frame["high"] = close + 0.1
        frame["low"] = close - 0.1
        frame["open"] = close
    result = IntradaySourceService._frame_to_window(frame, provider)
    result["fetched_at"] = "2026-09-10T08:00:00+00:00"
    return result


@pytest.fixture()
def db(market, monkeypatch):
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 10, 16, tzinfo=eod_dates.SHANGHAI)
    )
    market.execute(
        "INSERT INTO stock_basic(code,name,list_date) VALUES (?,?,'2026-09-10')", [CODE, "示例"]
    )
    market.execute("INSERT INTO trade_calendar VALUES ('2026-09-10',true),('2026-09-11',true)")
    market.execute(
        "INSERT INTO daily_bar(code,trade_date,open,high,low,close,pre_close) VALUES (?,? ,3.6,3.7,3.5,3.6,3.55)",
        [CODE, DAY],
    )
    return market


def test_cleaner_preserves_missing_open_and_rejects_bad_and_off_session_rows():
    f = _frame(rows=4)
    f.loc[0, "open"] = 0
    f.loc[1, "volume"] = -1
    f.loc[2, "timestamp"] = pd.Timestamp(DAY + " 12:00")
    clean, diag = sanitize_minutes(pd.concat([f, f.iloc[[3]]]))
    assert len(clean) == 2 and pd.isna(clean.iloc[0].open)
    assert diag == {"invalid_rows": 1, "off_session_rows": 1, "duplicate_rows": 1}


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "bad"},
        {"mode": "refetch"},
        {"codes": []},
        {"mode": "update", "date_start": DAY},
        {"mode": "refetch", "date_start": DAY, "date_end": "2026-09-09"},
        {"concurrency": 16},
        {"allow_fallback": True},
    ],
)
def test_parameter_rejection(params):
    with pytest.raises(ValueError):
        normalize_intraday_params(params)


def test_collect_idempotent_and_skip_complete(db):
    q = Windows([window()])
    service = IntradayArchiveService(db, quotes=q)
    first = service.collect()
    assert first["ok"] and first["inserted"] == 1
    assert service.summary()["complete_days"] == 1
    before = service.read(CODE, DAY)
    again = service.collect()
    assert again["skipped"] == 1 and len(q.calls) == 1
    assert service.read(CODE, DAY)["revision"] == before["revision"]
    assert db.query_df("SELECT count(*) n FROM stock_intraday_bar").iloc[0].n == 240


@pytest.mark.parametrize("recheck", ["scan", "collect"])
def test_closing_auction_rule_rechecks_old_archive_and_invalidates_cache(db, recheck):
    from backend.services.data_report import DataIntegrityReport
    from backend.services.intraday_contract import INTRADAY_ISSUE_TYPES

    frame = _frame()
    frame = frame[~frame.timestamp.dt.strftime("%H:%M").isin(["14:58", "14:59"])]
    payload = IntradaySourceService._frame_to_window(frame, "sina")
    payload["fetched_at"] = "2026-09-10T08:00:00+00:00"
    q = Windows([payload])
    service = IntradayArchiveService(db, quotes=q)
    service.collect()
    assert service.read(CODE, DAY)["status"] == "ready"
    assert len(service.read(CODE, DAY)["rows"]) == 238
    assert q.calls[0][2]["allow_fallback"] is False

    # 模拟旧口径已落库的 partial 和质量误报；复检只改状态与修订，不伪造分钟。
    db.execute("UPDATE stock_intraday_coverage SET status='partial',revision='legacy'")
    issue = service._issue(CODE, date.fromisoformat(DAY), "intraday_partial", "旧口径误报", {})
    DataIntegrityReport(db)._upsert_scan_issues([issue], INTRADAY_ISSUE_TYPES, codes=[CODE])
    cache = _Redis()
    assert service.read(CODE, DAY, cache)["status"] == "partial"
    if recheck == "scan":
        service.sync([CODE])
    else:
        result = service.collect()
        assert result["partial"] == 0 and result["quality"]["intraday_partial"] == 0
    assert service.read(CODE, DAY, cache)["status"] == "ready"
    assert service.read(CODE, DAY)["revision"] != "legacy"
    assert service.summary()["complete_days"] == 1
    assert service.issues() == []
    assert db.query_df("SELECT status FROM data_quality_issue").iloc[0].status == "resolved"
    assert db.query_df("SELECT count(*) n FROM stock_intraday_bar").iloc[0].n == 238
    service.collect()
    assert len(q.calls) == (1 if recheck == "scan" else 2)


@pytest.mark.parametrize("missing", ["09:31", "11:30", "13:01", "14:57", "15:00"])
def test_real_missing_minute_stays_partial_even_with_enough_other_points(db, missing):
    frame = _frame()
    frame = frame[frame.timestamp.dt.strftime("%H:%M").ne(missing)]
    payload = IntradaySourceService._frame_to_window(frame, "sina")
    payload["fetched_at"] = "2026-09-10T08:00:00+00:00"
    service = IntradayArchiveService(db, quotes=Windows([payload]))
    result = service.collect()
    assert result["failed"] == 0 and result["partial"] == 1
    assert service.read(CODE, DAY)["status"] == "partial"
    assert not service.clean("intraday_partial", CODE, DAY)
    assert service.summary()["partial_days"] == 1


def test_whole_day_precedence_and_failure_preserves_archive(db):
    q = Windows([window(provider="sina", rows=100), window(provider="eastmoney")])
    service = IntradayArchiveService(db, quotes=q)
    service.collect()
    assert service.read(CODE, DAY)["source"] == "eastmoney"
    q.windows = [window(provider="sina", rows=20)]
    service.collect({"mode": "refetch", "date_start": DAY})
    assert len(service.read(CODE, DAY)["rows"]) == 240
    q.fail = True
    result = service.collect({"mode": "refetch", "date_start": DAY})
    assert not result["ok"] and result["failed"] == 1
    assert len(service.read(CODE, DAY)["rows"]) == 240


def test_cache_revision_and_redis_failure(db):
    q = Windows([window()])
    service = IntradayArchiveService(db, quotes=q)
    service.collect()
    cache = _Redis()
    before = service.read(CODE, DAY, cache)
    q.windows = [window(close=5)]
    service.collect({"mode": "refetch", "date_start": DAY})
    after = service.read(CODE, DAY, cache)
    assert after["rows"][0][4] == 5 and after["revision"] != before["revision"]
    cache.fail = True
    response = IntradayQuoteService(market=db, redis_client=cache).get(
        CODE, date.fromisoformat(DAY)
    )
    assert response["archived"] and response["points"][0]["close"] == 5


def test_archive_before_online_window_is_queryable(db, monkeypatch):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect()
    db.execute(
        "INSERT INTO trade_calendar SELECT CAST(d AS DATE),true FROM generate_series(DATE '2026-09-12',DATE '2026-09-30',INTERVAL 1 DAY) dates(d)"
    )
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 30, 16, tzinfo=eod_dates.SHANGHAI)
    )
    response = IntradayQuoteService(market=db, redis_client=_Redis()).get(
        CODE, date.fromisoformat(DAY)
    )
    assert response["status"] == "ready" and response["supported_start"] is None
    assert response["archive_start"] == DAY


def test_quality_partial_repair_and_ignore_rule(db):
    service = IntradayArchiveService(db, quotes=Windows([window(rows=10)]))
    service.collect()
    assert not service.clean("intraday_partial", CODE, DAY)
    row = db.query_df("SELECT id FROM data_quality_issue WHERE issue_type='intraday_partial'").iloc[
        0
    ]
    service.quotes.windows = [window()]
    service.collect()
    assert service.clean("intraday_partial", CODE, DAY)
    assert (
        db.query_df("SELECT status FROM data_quality_issue WHERE id=?", [int(row.id)])
        .iloc[0]
        .status
        == "resolved"
    )


def test_failed_task_resume_retries_failed_code_and_clears_failure(db):
    q, ctx = Windows([window()]), Context()
    q.fail = True
    service = IntradayArchiveService(db, quotes=q)
    result = service.collect(ctx=ctx)
    assert not result["ok"] and ctx.checkpoint["intraday_done"] == []
    q.fail = False
    result = service.collect(ctx=ctx)
    assert result["ok"] and result["failed"] == 0


def test_midday_excludes_current_day_and_resume_scope_is_frozen(db, monkeypatch):
    ctx = Context()
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect(ctx=ctx)
    frozen = dict(ctx.checkpoint["intraday_scope"])
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 11, 14, tzinfo=eod_dates.SHANGHAI)
    )
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-11',3.6)", [CODE])
    assert service._scope({"mode": "update"}, Context())["end"] == DAY
    assert service._scope({"mode": "update"}, ctx) == frozen


def test_calendar_window_alone_does_not_block_unknown_history(db, monkeypatch):
    service = IntradayArchiveService(db, quotes=Windows([]))
    service.collect()
    monkeypatch.setattr(service, "online_dates", lambda: ["2026-09-21"])
    q = service.quotes
    q.calls.clear()
    service.collect({"mode": "refetch", "date_start": DAY})
    assert len(q.calls) == 1 and not service.clean("intraday_gap", CODE, DAY)
    assert "源端暂无数据" in db.query_df("SELECT failure_reason FROM stock_intraday_coverage").iloc[0].failure_reason


def test_confirmed_suspension_not_expected_but_empty_not_suspension(db):
    service = IntradayArchiveService(db, quotes=Windows([]))
    service.collect()
    assert service.summary()["missing_days"] == 1
    assert db.query_df("SELECT count(*) n FROM stock_suspension").iloc[0].n == 0
    db.execute("INSERT INTO stock_suspension(code,trade_date) VALUES (?,?)", [CODE, DAY])
    service.sync()
    assert service.issues() == []


def test_cancel_before_first_request_and_source_wait(db):
    ctx = Context()
    ctx.cancel = True
    q = Windows([window()])
    with pytest.raises(TaskCancelled):
        IntradayArchiveService(db, quotes=q).collect(ctx=ctx)
    assert q.calls == []
    service = IntradaySourceService(redis_client=_Redis(), ctx=ctx)
    with pytest.raises(TaskCancelled):
        service._pause(100)


def test_quality_detects_physical_loss_even_with_ready_coverage(db):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect()
    db.execute("DELETE FROM stock_intraday_bar WHERE timestamp=TIMESTAMP '2026-09-10 09:31:00'")
    kinds = {r["issue_type"] for r in service.issues()}
    assert kinds == {"intraday_invalid", "intraday_partial"}


def test_async_write_mutex_failure_resume_and_terminal_logs(db, monkeypatch):
    from backend.services import async_task, intraday_source

    q = Windows([window()])
    q.fail = True
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    monkeypatch.setattr(async_task.AsyncTaskService, "_audit_task", staticmethod(lambda **kw: None))

    class NoThread:
        def __init__(self, **kw):
            pass

        def start(self):
            pass

    monkeypatch.setattr(async_task.threading, "Thread", NoThread)
    svc = async_task.AsyncTaskService(db)
    tid = svc.create("intraday_ingest")
    with pytest.raises(async_task.ConcurrentTaskError):
        svc.create("stock_ingest", {"recipe": "daily_update"})
    svc._run(tid, "intraday_ingest", {}, None)
    task = svc.get(tid)
    assert task["status"] == "failed"
    checkpoint = task["result"]["checkpoint"]
    assert checkpoint["intraday_done"] == []
    q.fail = False
    svc.resume(tid)
    svc._run(tid, "intraday_ingest", {}, checkpoint)
    assert svc.get(tid)["status"] == "done"
    assert any("分时" in row["message"] for row in svc.get_logs(tid))


def test_intraday_schedule_and_quality_repair_use_existing_contract(db):
    from backend.scheduler.scheduler import ScheduledJobService

    svc = ScheduledJobService(db)
    task = svc.create(
        name="独立分时",
        task_type="intraday_ingest",
        params={},
        freq_type="daily",
        freq_config={"time": "18:00"},
        trading_day_only=True,
        enabled=False,
    )
    assert task["params"] == {"mode": "update"} and task["enabled"] is False
    with pytest.raises(ValueError):
        svc.update(
            task["id"],
            name="独立分时",
            task_type="intraday_ingest",
            params={"mode": "refetch"},
            freq_type="daily",
            freq_config={"time": "18:00"},
            trading_day_only=True,
            enabled=False,
        )
    repair = svc.create(
        name="分时缺口恢复",
        task_type="fix",
        params={"issue_type": "intraday_gap"},
        freq_type="daily",
        freq_config={"time": "19:00"},
        trading_day_only=True,
        enabled=False,
    )
    assert repair["params"]["issue_type"] == "intraday_gap"


def test_fix_rechecks_actual_data_before_resolving(db, monkeypatch):
    from backend.services import async_task, intraday_source
    from backend.services.data_report import DataIntegrityReport

    q = Windows([window(rows=10)])
    service = IntradayArchiveService(db, quotes=q)
    service.collect()
    issue_id = int(db.query_df("SELECT id FROM data_quality_issue WHERE status='open'").iloc[0].id)
    q.windows = [window()]
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: q)
    context = Context()
    clean, _, message = async_task._recover_one(
        db, DataIntegrityReport(db), None, context, issue_id
    )
    assert clean and "复检通过" in message
    assert q.calls[-1][2]["allow_fallback"] is True
    assert (
        db.query_df("SELECT status FROM data_quality_issue WHERE id=?", [issue_id]).iloc[0].status
        == "resolved"
    )


def test_regular_partial_archive_uses_fallback_only_when_quality_repair_runs(db, monkeypatch):
    from backend.services import async_task, intraday_source
    from backend.services.data_report import DataIntegrityReport
    from backend.tests.test_intraday_source import _service

    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            return _frame(rows=10 if provider == "sina" else 240)

    quotes = _service(factory=Source)
    service = IntradayArchiveService(db, quotes=quotes)
    first = service.collect()
    assert first["ok"] and first["partial"] == 1 and calls == ["sina"]
    issue_id = int(db.query_df(
        "SELECT id FROM data_quality_issue WHERE issue_type='intraday_partial' AND status='open'"
    ).iloc[0].id)
    monkeypatch.setattr(intraday_source, "IntradaySourceService", lambda **kw: quotes)
    clean, _, _ = async_task._recover_one(
        db, DataIntegrityReport(db), None, Context(), issue_id
    )
    assert clean and calls == ["sina", "sina", "eastmoney"]
    assert service.read(CODE, DAY)["source"] == "eastmoney"
    assert service.read(CODE, DAY)["status"] == "ready"


def test_schedule_api_defaults_disable_only_intraday():
    from backend.api.data_admin import ScheduledJobIn

    assert ScheduledJobIn(name="x", task_type="intraday_ingest").enabled is False
    assert ScheduledJobIn(name="x", task_type="intraday_ingest", enabled=True).enabled is True
    assert ScheduledJobIn(name="x", task_type="stock_ingest").enabled is True


def test_repair_outside_eastmoney_window_does_not_request_unavailable_fallback(db):
    db.execute("UPDATE stock_basic SET list_date='2026-09-01'")
    db.execute("INSERT INTO trade_calendar SELECT d::DATE,true "
               "FROM generate_series(DATE '2026-09-01',DATE '2026-09-09',INTERVAL 1 DAY) t(d) "
               "WHERE dayofweek(d) BETWEEN 1 AND 5")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-01',3.6)", [CODE])
    q = Windows([window(day="2026-09-01", rows=10)])
    ctx = Context()
    service = IntradayArchiveService(db, quotes=q)
    result = service.collect(
        {"mode": "refetch", "codes": [CODE], "date_start": "2026-09-01"},
        ctx=ctx, allow_fallback=True,
    )
    assert result["partial"] == 1
    assert q.calls[0][2]["providers"] == ("sina", "ths")
    assert any("东财：跳过" in m and "2026-09-01 不在该接口近5交易日范围" in m for m, _ in ctx.logs)
    assert not service.clean("intraday_partial", CODE, "2026-09-01")


def test_eastmoney_five_day_window_includes_current_open_day(db, monkeypatch):
    db.execute("INSERT INTO trade_calendar SELECT d::DATE,true "
               "FROM generate_series(DATE '2026-09-01',DATE '2026-09-09',INTERVAL 1 DAY) t(d) "
               "WHERE dayofweek(d) BETWEEN 1 AND 5")
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 10, 14, tzinfo=eod_dates.SHANGHAI)
    )
    service = IntradayArchiveService(db)
    assert service.online_dates(provider="eastmoney") == [
        "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
    ]
    assert "2026-09-10" not in service.online_dates()


def test_refetch_does_not_expand_unmonitored_history(db):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    db.execute("UPDATE stock_basic SET list_date='2020-01-01'")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2020-01-02',3.6)", [CODE])
    with pytest.raises(ValueError, match="超出"):
        service.collect({"mode": "refetch", "codes": [CODE], "date_start": "2020-01-02"})
    assert service.summary()["expected_days"] == 0
    service.collect(
        {"mode": "refetch", "codes": [CODE], "date_start": "2020-01-02", "date_end": DAY}
    )
    assert service.summary()["monitoring_start"][:10] == DAY


def test_monitoring_start_is_frozen_across_resume(db):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    ctx = Context()
    first = service._scope({"mode": "update"}, ctx)
    db.execute(
        "INSERT INTO stock_intraday_coverage(code,trade_date) VALUES (?,'2026-01-01')", [CODE]
    )
    assert service._scope({"mode": "update"}, ctx) == first
    assert service._ensure_expected(CODE, first).trade_date.min().date() == date.fromisoformat(DAY)


def test_file_reopen_and_offline_cache_still_read_archive(db, tmp_path):
    from backend.storage.ddl import init_db
    from backend.storage.duckdb_client import DuckDBClient

    path = tmp_path / "archive.duckdb"
    with DuckDBClient(path) as local:
        init_db(local)
        for table in ("stock_basic", "trade_calendar", "daily_bar"):
            frame = db.query_df("SELECT * FROM " + table)
            with local.temp_view(frame) as view:
                local.execute(f"INSERT INTO {table} BY NAME SELECT * FROM {view}")
        IntradayArchiveService(local, quotes=Windows([window()])).collect()
    cache = _Redis()
    cache.fail = True
    with DuckDBClient(path) as reopened:
        result = IntradayQuoteService(market=reopened, redis_client=cache).get(
            CODE, date.fromisoformat(DAY)
        )
    assert result["archived"] and result["status"] == "ready" and len(result["points"]) == 240


def test_quality_scan_reconciles_summary_and_cache_revision(db):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect()
    before = service.read(CODE, DAY, _Redis())
    db.execute("DELETE FROM stock_intraday_bar WHERE timestamp=TIMESTAMP '2026-09-10 09:31:00'")
    service.sync()
    assert service.summary()["partial_days"] == 1
    after = service.read(CODE, DAY)
    assert len(after["rows"]) == 239 and after["revision"] != before["revision"]


def test_catalog_freshness_checks_each_latest_stock_but_not_old_quality_gap(db):
    from backend.storage.catalog import _duck_runtime_metrics

    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect()
    db.execute(
        "INSERT INTO stock_intraday_coverage(code,trade_date) VALUES (?,'2026-01-01')", [CODE]
    )
    tables = {"stock_intraday_bar", "stock_intraday_coverage", "daily_bar"}
    assert _duck_runtime_metrics(db, tables)[3]["stock_intraday_bar"] is True
    db.execute("INSERT INTO stock_basic(code,name) VALUES ('600001.SH','另股')")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600001.SH',?,3.6)", [DAY])
    assert _duck_runtime_metrics(db, tables)[3]["stock_intraday_bar"] is False


def test_queries_never_fetch_or_write_and_collector_is_only_ingestion_path(db):
    from backend.tests.test_intraday_source import _service

    calls = []

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append((code, provider))
            return _frame()

    cache = _Redis()
    cache.set(f"market:intraday:1m:window:sina:{CODE}", "legacy response")
    reader = IntradayQuoteService(market=db, redis_client=cache)
    before = reader.get(CODE, date.fromisoformat(DAY))
    assert before["status"] == "no_data" and calls == []
    assert db.query_df("SELECT count(*) n FROM stock_intraday_bar").iloc[0].n == 0
    assert db.query_df("SELECT count(*) n FROM stock_intraday_coverage").iloc[0].n == 0
    collector = IntradayArchiveService(db, quotes=_service(cache, Source))
    result = collector.collect()
    assert result["inserted"] == 1 and calls == [(CODE, "sina")]
    # 查询只消费这次落库的事实，清缓存、Redis 故障都不增加源站请求。
    first = reader.get(CODE, date.fromisoformat(DAY))
    cache.values.clear()
    cache.fail = True
    again = reader.get(CODE, date.fromisoformat(DAY))
    assert first == again and len(again["points"]) == 240
    assert calls == [(CODE, "sina")]
    assert collector.collect()["skipped"] == 1


def test_first_window_is_fixed_even_when_first_source_response_is_empty(db, monkeypatch):
    db.execute("UPDATE stock_basic SET list_date='2026-09-01'")
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    service = IntradayArchiveService(db, quotes=Windows([]))
    service.collect()
    assert (
        str(db.query_df("SELECT monitoring_start FROM stock_intraday_monitor").iloc[0, 0].date())
        == "2026-09-09"
    )
    assert service.summary()["missing_days"] == 2
    # 即使第一天覆盖丢失、源窗口向前滚动，独立起点仍保留历史缺口。
    db.execute("DELETE FROM stock_intraday_coverage WHERE trade_date='2026-09-09'")
    monkeypatch.setattr(service, "online_dates", lambda: [DAY])
    service.quotes.windows = [window()]
    service.collect()
    assert service.summary()["monitoring_start"].startswith("2026-09-09")
    assert service.summary()["missing_days"] == 1
    gaps = [r for r in service.issues() if r["issue_type"] == "intraday_gap"]
    assert [str(r["trade_date"]) for r in gaps] == ["2026-09-09"]


def test_new_days_without_coverage_are_historical_and_latest_gap_issues(db, monkeypatch):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect()
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 14, 16, tzinfo=eod_dates.SHANGHAI)
    )
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-14',true)")
    # 11日没有本地个股日线也不能被默认为停牌；最新日线仅作为全局上界。
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-14',3.6)", [CODE])
    gaps = [r for r in service.issues() if r["issue_type"] == "intraday_gap"]
    assert {str(r["trade_date"]) for r in gaps} == {"2026-09-11", "2026-09-14"}
    assert service.summary()["missing_days"] == 2
    assert service.summary_by_stock([CODE])[0]["missing_days"] == 2
    service.sync()
    assert (
        db.query_df("SELECT count(*) n FROM stock_intraday_coverage WHERE point_count=0").iloc[0].n
        == 2
    )
    assert (
        db.query_df(
            "SELECT count(*) n FROM data_quality_issue WHERE issue_type='intraday_gap' AND status='open'"
        )
        .iloc[0]
        .n
        == 2
    )


def test_monitor_survives_loss_of_all_daily_coverage_and_rebuilds_metadata(db):
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    service.collect()
    db.execute("DELETE FROM stock_intraday_coverage")
    # 分钟事实仍在时不能报整日缺失；覆盖计数不一致可由扫描恢复。
    assert not any(r["issue_type"] == "intraday_gap" for r in service.issues())
    service.sync()
    response = IntradayQuoteService(market=db, redis_client=_Redis()).get(
        CODE, date.fromisoformat(DAY)
    )
    assert response["status"] == "ready" and response["source"] == "sina"
    assert len(response["points"]) == 240
    db.execute("DELETE FROM stock_intraday_coverage")
    db.execute("DELETE FROM stock_intraday_bar")
    assert {r["issue_type"] for r in service.issues()} == {"intraday_gap"}
    assert service.summary()["missing_days"] == 1


def test_monitor_excludes_prelisting_delisted_and_confirmed_suspension(db, monkeypatch):
    service = IntradayArchiveService(db, quotes=Windows([]))
    service.collect()
    db.execute("UPDATE stock_intraday_monitor SET monitoring_start='2026-09-09'")
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    monkeypatch.setattr(
        eod_dates, "shanghai_now", lambda: datetime(2026, 9, 14, 16, tzinfo=eod_dates.SHANGHAI)
    )
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-14',true)")
    db.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES (?,'2026-09-14',3.6)", [CODE])
    db.execute("UPDATE stock_basic SET delist_date='2026-09-14'")
    db.execute("INSERT INTO stock_suspension(code,trade_date) VALUES (?,'2026-09-11')", [CODE])
    assert {str(r["trade_date"]) for r in service.issues()} == {DAY}


def test_refetch_subrange_does_not_shrink_first_monitoring_window(db):
    db.execute("UPDATE stock_basic SET list_date='2026-09-01'")
    db.execute("INSERT INTO trade_calendar VALUES ('2026-09-09',true)")
    service = IntradayArchiveService(db, quotes=Windows([window()]))
    result = service.collect({"mode": "refetch", "date_start": DAY})
    assert result["missing"] == 1
    assert service.summary()["monitoring_start"].startswith("2026-09-09")
    assert service.summary()["missing_days"] == 1


def test_monitor_migration_is_idempotent_and_preserves_dimension_customization(db):
    from backend.storage.ddl import init_db

    db.execute("INSERT INTO stock_intraday_coverage(code,trade_date) VALUES (?,?)", [CODE, DAY])
    db.execute(
        "UPDATE data_dimension_registry SET name_cn='定制分时',tables='[\"stock_intraday_bar\"]' WHERE dimension='intraday'"
    )
    init_db(db)
    db.execute(
        "INSERT INTO stock_intraday_coverage(code,trade_date) VALUES (?,'2026-09-11')", [CODE]
    )
    db.execute("DELETE FROM stock_intraday_coverage WHERE trade_date=?", [DAY])
    init_db(db)
    assert (
        str(db.query_df("SELECT monitoring_start FROM stock_intraday_monitor").iloc[0, 0].date())
        == DAY
    )
    import json

    dimension = db.query_df(
        "SELECT name_cn,tables FROM data_dimension_registry WHERE dimension='intraday'"
    ).iloc[0]
    assert dimension.name_cn == "定制分时"
    assert set(json.loads(dimension.tables)) == {"stock_intraday_bar", "stock_intraday_monitor", "stock_intraday_source_state"}


def test_expired_historical_gap_explains_reason_without_running_collection(db, monkeypatch):
    import json

    service = IntradayArchiveService(db, quotes=Windows([]))
    service.collect()
    db.execute("DELETE FROM stock_intraday_coverage")
    monkeypatch.setattr(service, "online_dates", lambda: ["2026-09-11"])
    issues = service.issues()
    assert len(issues) == 1 and issues[0]["issue_type"] == "intraday_gap"
    assert json.loads(issues[0]["detail"])["availability"]["status"] == "needs_verification"
    assert len(service.quotes.calls) == 1


def test_collection_logs_each_stock_and_flushes_before_source_request(db):
    ctx = Context()
    q = Windows([window()])
    service = IntradayArchiveService(db, quotes=q)
    service.collect(ctx=ctx)
    messages = [m for m, _ in ctx.logs]
    assert any("近期增量补采" in m and "目标" in m for m in messages)
    assert any("[1/1]" in m and "待取源 1 日" in m for m in messages)
    assert any("落库：新增 1 日" in m and "完整 1 日" in m for m in messages)
    assert any("正在复检" in m for m in messages)
    assert ctx.flushes >= 3 and ctx.checkpoint["phase_done"] == 1


def test_partial_source_failure_keeps_data_and_warns_in_task_log(db):
    from backend.tests.test_intraday_source import _service

    ctx = Context()

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            assert ctx.flushes > 0
            assert any("请求" in message for message, _ in ctx.logs)
            if provider == "eastmoney":
                raise ConnectionError("offline")
            return _frame(rows=10)

    quotes = _service(_Redis(), Source)
    quotes.ctx = ctx
    result = IntradayArchiveService(db, quotes=quotes).collect(ctx=ctx, allow_fallback=True)
    assert result["failed"] == 1 and result["inserted"] == 1
    assert any("新浪返回" in message and "目标日完整 0/1" in message for message, _ in ctx.logs)
    assert any("东财取源失败" in message and level == "warn" for message, level in ctx.logs)
    assert any("部分 1 日" in message and "未完成项保留重试" in message for message, _ in ctx.logs)


def test_circuit_skip_keeps_partial_archive_issue_and_resume_eligibility(db):
    import json
    import time

    from backend.tests.test_intraday_source import _service

    ctx, cache, calls = Context(), _Redis(), []
    for provider in ("eastmoney", "ths"):
        cache.set(IntradaySourceService._backup_state_key(provider),
                  json.dumps({"failures": 3, "open_until": time.time() + 60}), ex=120)

    class Source:
        def get_intraday_1m(self, code, provider, *, timeout_sec=None):
            calls.append(provider)
            assert provider == "sina"
            return _frame(rows=238)

    quotes = _service(cache, Source)
    quotes.ctx = ctx
    service = IntradayArchiveService(db, quotes=quotes)
    result = service.collect(ctx=ctx, allow_fallback=True)
    assert calls == ["sina"] and result["inserted"] == 1 and result["failed"] == 1
    assert ctx.checkpoint["intraday_done"] == []
    assert "暂时熔断" in ctx.checkpoint["intraday_failed"][CODE]
    assert len(service.read(CODE, DAY)["rows"]) == 238
    assert any(i["issue_type"] == "intraday_partial" for i in service.issues())

    # 续跑时重新评估未完成股票，不会被 checkpoint 当作成功跳过。
    service.collect(ctx=ctx, allow_fallback=True)
    assert calls == ["sina", "sina"]
    assert db.query_df("SELECT count(*) n FROM stock_intraday_bar").iloc[0].n == 238
