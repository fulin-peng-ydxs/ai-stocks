from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import ClassVar

import pandas as pd
import pytest
from baostock.common import context

from backend.common.exceptions import DataSourceError
from backend.datasource.baostock_source import BaostockSource, _collect
from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.services.ingest import IngestionService
from backend.services.stock_st_status import (
    StockSTStatusFact,
    StockSTStatusService,
    STStatusNotReadyError,
)


def _fact(code: str, trade_date: date, is_st: bool, quality=STStatusQuality.ACCURATE):
    return StockSTStatusFact(
        code=code,
        trade_date=trade_date,
        status=PointInTimeSTStatus(
            is_st=is_st,
            source="baostock" if quality == STStatusQuality.ACCURATE else "stock_name",
            source_ref="query_history_k_data_plus:isST",
            quality=quality,
        ),
    )


def test_baostock_st_status_keeps_suspended_rows(monkeypatch):
    source = BaostockSource()
    monkeypatch.setattr(
        source,
        "_st_data",
        lambda *args, **kwargs: pd.DataFrame([
            {"date": "2026-07-03", "tradestatus": "1", "isST": "1"},
            {"date": "2026-07-06", "tradestatus": "0", "isST": "1"},
        ]),
    )
    rows = source.get_st_status("600001.SH", date(2026, 7, 3), date(2026, 7, 6))
    assert rows["is_st"].tolist() == [True, True]
    assert rows["trade_status"].tolist() == [1, 0]


def test_baostock_collect_rejects_rows_truncated_by_midstream_failure():
    class Result:
        error_code = "0"
        error_msg = ""
        fields: ClassVar[list[str]] = ["date"]
        step = 0

        def next(self):
            self.step += 1
            if self.step == 1:
                return True
            self.error_code = "10002007"
            self.error_msg = "网络接收错误"
            return False

        def get_row_data(self):
            return ["2026-07-03"]

    with pytest.raises(DataSourceError, match="网络接收错误"):
        _collect(Result())


def test_baostock_query_failure_invalidates_socket_before_retry(monkeypatch):
    source = BaostockSource()
    source._logged_in = True
    source._login_at = 1.0
    monkeypatch.setattr(source, "_ensure_login", lambda: None)

    class Socket:
        closed = False

        def close(self):
            self.closed = True

    class Result:
        error_code = "10002007"
        error_msg = "网络接收错误"
        fields: ClassVar[list[str]] = []

    sock = Socket()
    monkeypatch.setattr(context, "default_socket", sock, raising=False)
    with pytest.raises(DataSourceError, match="网络接收错误"):
        source._query_frame(lambda: Result())

    assert source._logged_in is False
    assert source._login_at == 0.0
    assert sock.closed is True
    assert context.default_socket is None


def test_daily_ingest_persists_st_when_baostock_confirms_suspension(market, monkeypatch):
    day = date(2026, 7, 6)
    market.execute("INSERT INTO trade_calendar VALUES (?,TRUE)", [day])
    source = SimpleNamespace(name="baostock")
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    ingest.src = source
    monkeypatch.setattr(
        ingest,
        "_fetch_daily_with_fallback",
        lambda *args, **kwargs: (_ for _ in ()).throw(DataSourceError("日线为空")),
    )
    monkeypatch.setattr(
        ingest,
        "_fetch_st_status_rows",
        lambda *args, **kwargs: (
            source,
            pd.DataFrame(
                [{"code": "600001.SH", "trade_date": day, "is_st": True, "trade_status": 0}]
            ),
        ),
    )

    assert ingest.ingest_one_daily("600001.SH", day, day, source=source) == 0
    row = market.query_df(
        "SELECT is_st,quality FROM stock_st_status_daily WHERE code='600001.SH'"
    ).iloc[0]
    assert bool(row["is_st"]) is True
    assert row["quality"] == "accurate"


def test_st_status_read_gate_rejects_missing_and_approximate(market):
    service = StockSTStatusService(market)
    day = date(2026, 7, 3)
    with pytest.raises(STStatusNotReadyError, match="缺失 1"):
        service.status_map(day, ["600001.SH"])

    service.upsert_facts(
        [_fact("600001.SH", day, True, STStatusQuality.APPROXIMATE)],
        change_reason="legacy_import",
    )
    with pytest.raises(STStatusNotReadyError, match="非权威 1"):
        service.status_map(day, ["600001.SH"])

    service.upsert_facts([_fact("600001.SH", day, False)], change_reason="baostock_refresh")
    assert service.status_map(day, ["600001.SH"]) == {"600001.SH": False}


def test_st_coverage_and_daily_projection_are_observable(market):
    day = date(2026, 7, 3)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close,is_st) "
        "VALUES ('600001.SH',?,10,9.5,TRUE)",
        [day],
    )
    service = StockSTStatusService(market)
    service.upsert_facts([_fact("600001.SH", day, False)], change_reason="baostock_refresh")
    before = service.coverage()
    assert before["ready"] is True
    assert before["coverage_rate"] == 100.0
    assert service.sync_daily_bar_projection([day]) == 1
    row = market.query_df("SELECT is_st FROM daily_bar").iloc[0]
    assert bool(row["is_st"]) is False


def test_st_dataset_version_preserves_subsecond_fact_changes(market):
    day = date(2026, 7, 3)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close,is_st) "
        "VALUES ('600001.SH',?,10,9.5,FALSE)",
        [day],
    )
    service = StockSTStatusService(market)
    service.upsert_facts(
        [_fact("600001.SH", day, False)],
        change_reason="seed",
        captured_at=datetime(2026, 7, 4, 8, 0, 0, 123456, tzinfo=UTC).replace(tzinfo=None),
    )

    assert "2026-07-04T08:00:00.123456" in service.dataset_version(day, day)


def test_set_based_marker_rebuild_applies_main_board_st_cutoff(market):
    before = date(2026, 7, 3)
    after = date(2026, 7, 6)
    market.execute(
        "INSERT INTO stock_basic (code,price_limit_pct) VALUES ('600001.SH',0.10)"
    )
    market.execute(
        "INSERT INTO daily_bar "
        "(code,trade_date,open,high,low,close,pre_close,is_st,limit_status,is_one_word) VALUES "
        "('600001.SH',?,10.5,10.5,10.5,10.5,10,FALSE,0,FALSE),"
        "('600001.SH',?,11,11,11,11,10,FALSE,0,FALSE)",
        [before, after],
    )
    service = StockSTStatusService(market)
    service.upsert_facts(
        [_fact("600001.SH", before, True), _fact("600001.SH", after, True)],
        change_reason="seed",
    )

    assert service.rebuild_daily_bar_markers() == 2
    rows = market.query_df(
        "SELECT trade_date,is_st,limit_status,is_one_word FROM daily_bar ORDER BY trade_date"
    )
    assert rows["is_st"].tolist() == [True, True]
    assert rows["limit_status"].tolist() == [1, 1]
    assert rows["is_one_word"].tolist() == [True, True]


def test_st_refresh_publication_state_blocks_mixed_batch_reads(market):
    day = date(2026, 7, 6)
    service = StockSTStatusService(market)
    service.upsert_facts([_fact("600001.SH", day, True)], change_reason="seed")

    service.begin_refresh(task_id="task-1", target_count=1, start=day, end=day)
    with pytest.raises(STStatusNotReadyError, match="refreshing"):
        service.status_map(day, ["600001.SH"])
    assert service.coverage()["ready"] is False

    service.finish_refresh(ready=False, error="source timeout")
    with pytest.raises(STStatusNotReadyError, match="source timeout"):
        service.status_map(day, ["600001.SH"])

    service.begin_refresh(task_id="task-2", target_count=1, start=day, end=day)
    service.finish_refresh(ready=True)
    assert service.status_map(day, ["600001.SH"]) == {"600001.SH": True}


def test_st_refresh_wrapper_publishes_only_zero_failure_batches(market, monkeypatch):
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    monkeypatch.setattr(
        ingest,
        "_refresh_st_status_impl",
        lambda **kwargs: {"target": 1, "ok": 1, "fail": 0},
    )
    result = ingest.refresh_st_status(codes=["600001.SH"])
    assert result["publication_status"] == "ready"
    assert result["coverage"]["refresh_state"]["status"] == "ready"

    monkeypatch.setattr(
        ingest,
        "_refresh_st_status_impl",
        lambda **kwargs: {"target": 1, "ok": 1, "fail": 1},
    )
    result = ingest.refresh_st_status(codes=["600001.SH"])
    assert result["publication_status"] == "failed"
    assert result["coverage"]["refresh_state"]["status"] == "failed"


def test_targeted_st_refresh_cannot_reopen_gate_while_market_has_gaps(market, monkeypatch):
    day = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) VALUES "
        "('600001.SH',?,10,9),('000001.SZ',?,10,9)",
        [day, day],
    )
    StockSTStatusService(market).upsert_facts(
        [_fact("600001.SH", day, False)], change_reason="seed"
    )
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    monkeypatch.setattr(
        ingest,
        "_refresh_st_status_impl",
        lambda **kwargs: {"target": 1, "ok": 1, "fail": 0},
    )

    result = ingest.refresh_st_status(codes=["600001.SH"])

    assert result["publication_status"] == "failed"
    assert result["coverage"]["refresh_state"]["status"] == "failed"
    assert "1/2" in result["coverage"]["refresh_state"]["last_error"]


def test_targeted_recovery_from_failed_batch_rebuilds_all_markers_before_publish(
    market, monkeypatch
):
    day = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
        "VALUES ('600001.SH',?,10,9)",
        [day],
    )
    st_service = StockSTStatusService(market)
    st_service.upsert_facts([_fact("600001.SH", day, False)], change_reason="seed")
    st_service.begin_refresh(task_id="failed-task", target_count=2, start=None, end=None)
    st_service.finish_refresh(ready=False, error="one source failed")
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    monkeypatch.setattr(
        ingest,
        "_refresh_st_status_impl",
        lambda **kwargs: {"target": 1, "ok": 1, "fail": 0, "projection_rows": 1},
    )
    rebuild_scopes = []

    def rebuild(_self, **scope):
        rebuild_scopes.append(scope)
        return 1

    monkeypatch.setattr(StockSTStatusService, "rebuild_daily_bar_markers", rebuild)

    result = ingest.refresh_st_status(codes=["600001.SH"])

    assert result["publication_status"] == "ready"
    assert rebuild_scopes == [{}]


def test_st_refresh_resume_skips_completed_codes(market, monkeypatch):
    day = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) VALUES "
        "('600001.SH',?,10,9),('000001.SZ',?,10,9)",
        [day, day],
    )
    service = StockSTStatusService(market)
    service.upsert_facts(
        [_fact("600001.SH", day, False), _fact("000001.SZ", day, False)],
        change_reason="seed",
    )
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    ingest.repo = SimpleNamespace(c=market, log_update=lambda *args, **kwargs: None)
    source = SimpleNamespace(name="baostock")
    monkeypatch.setattr(ingest, "_source_for", lambda _capability: source)
    fetched: list[str] = []

    def accurate(code, *_args, **_kwargs):
        fetched.append(code)
        return [_fact(code, day, False)]

    monkeypatch.setattr(ingest, "_accurate_st_facts", accurate)
    monkeypatch.setattr(ingest, "_recompute_clean_one", lambda *args, **kwargs: 1)

    class Context:
        tid = "resume-task"
        checkpoint: ClassVar[dict[str, list[str]]] = {"st_done_codes": ["600001.SH"]}

        def set_checkpoint(self, **values):
            self.checkpoint.update(values)

        def set_phase(self, _phase, **values):
            self.checkpoint.update(values)

        def check_cancel(self):
            return None

        def log(self, *_args, **_kwargs):
            return None

        def flush(self):
            return None

        def progress(self, *_args, **_kwargs):
            return None

    ctx = Context()
    result = ingest._refresh_st_status_impl(ctx=ctx)

    assert fetched == ["000001.SZ"]
    assert result["ok"] == 2
    assert set(ctx.checkpoint["st_done_codes"]) == {"600001.SH", "000001.SZ"}


def test_st_refresh_includes_listed_stock_without_daily_bars(market, monkeypatch):
    market_day = date(2026, 7, 6)
    list_day = date(2026, 7, 1)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
        "VALUES ('600001.SH',?,10,9)",
        [market_day],
    )
    market.execute(
        "INSERT INTO stock_basic (code,list_date,price_limit_pct) "
        "VALUES ('600002.SH',?,0.10)",
        [list_day],
    )
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    ingest.repo = SimpleNamespace(c=market, log_update=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ingest, "_source_for", lambda _capability: SimpleNamespace(name="baostock")
    )
    fetched: list[tuple[str, date, date]] = []

    def accurate(code, _dates, **kwargs):
        fetched.append((code, kwargs["fetch_start"], kwargs["fetch_end"]))
        return [_fact(code, market_day, False)]

    monkeypatch.setattr(ingest, "_accurate_st_facts", accurate)

    result = ingest._refresh_st_status_impl(codes=["600002.SH"])

    assert result["target"] == 1
    assert result["ok"] == 1
    assert result["rows"] == 1
    assert fetched == [("600002.SH", list_day, market_day)]


def test_st_refresh_ignores_stale_checkpoint_codes_outside_current_target(
    market, monkeypatch
):
    day = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
        "VALUES ('600001.SH',?,10,9)",
        [day],
    )
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    ingest.repo = SimpleNamespace(c=market, log_update=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ingest, "_source_for", lambda _capability: SimpleNamespace(name="baostock")
    )
    monkeypatch.setattr(
        ingest,
        "_accurate_st_facts",
        lambda *_args, **_kwargs: [_fact("600001.SH", day, False)],
    )

    ctx = SimpleNamespace(
        tid="resume-task",
        checkpoint={"st_done_codes": ["999999.SZ"]},
        set_checkpoint=lambda **_kwargs: None,
        set_phase=lambda *_args, **_kwargs: None,
        check_cancel=lambda: None,
        log=lambda *_args, **_kwargs: None,
        flush=lambda: None,
        progress=lambda *_args, **_kwargs: None,
    )

    result = ingest._refresh_st_status_impl(ctx=ctx)

    assert result["target"] == 1
    assert result["ok"] == 1


def test_refresh_publication_target_count_uses_actual_target_set(market, monkeypatch):
    market_day = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
        "VALUES ('600001.SH',?,10,9)",
        [market_day],
    )
    market.execute(
        "INSERT INTO stock_basic (code,list_date,price_limit_pct) "
        "VALUES ('600002.SH','2026-07-01',0.10)"
    )
    StockSTStatusService(market).upsert_facts(
        [_fact("600001.SH", market_day, False)], change_reason="seed"
    )
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    monkeypatch.setattr(
        ingest,
        "_refresh_st_status_impl",
        lambda **kwargs: {"target": 2, "ok": 2, "fail": 0},
    )

    result = ingest.refresh_st_status()

    assert result["publication_status"] == "ready"
    assert StockSTStatusService(market).refresh_state()["target_count"] == 2


def test_st_refresh_reports_changes_without_invalidating_downstream_results(
    market, monkeypatch
):
    day = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close) "
        "VALUES ('600001.SH',?,10,9)",
        [day],
    )
    ingest = IngestionService.__new__(IngestionService)
    ingest.c = market
    ingest.repo = SimpleNamespace(c=market, log_update=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ingest, "_source_for", lambda _capability: SimpleNamespace(name="baostock")
    )
    monkeypatch.setattr(
        ingest,
        "_accurate_st_facts",
        lambda *_args, **_kwargs: [_fact("600001.SH", day, True)],
    )

    result = ingest._refresh_st_status_impl(codes=["600001.SH"])

    assert result["changed_date_values"] == [str(day)]
    assert "invalidated" not in result
    assert result["downstream_results_untouched"] is True
    assert market.query_df(
        "SELECT count(*) AS n FROM limit_ladder_invalidation_outbox"
    ).iloc[0]["n"] == 0
