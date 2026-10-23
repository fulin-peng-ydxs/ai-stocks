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


def test_baostock_hung_query_is_broken_by_watchdog(monkeypatch):
    """源端丢弃连接时客户端会空转（不抛错）；看门狗必须在阈值内断开会话，让调用失败而不是永久挂起。"""
    import threading
    import time

    from backend.datasource import baostock_source as bsrc

    source = BaostockSource()
    source._hang_break_sec = 0.2
    monkeypatch.setattr(bsrc, "_WATCHDOG_POLL_SEC", 0.05)
    monkeypatch.setattr(source, "_ensure_login", lambda: None)

    closed = threading.Event()

    class Socket:
        def close(self):
            closed.set()

        def settimeout(self, _seconds):
            pass

    monkeypatch.setattr(context, "default_socket", Socket(), raising=False)

    def stalled_query():
        # 模拟 baostock 的空转：只有会话被断开才会退出
        while not closed.is_set():
            time.sleep(0.01)
        raise OSError("Bad file descriptor")

    started = time.monotonic()
    with pytest.raises(Exception):
        source._query_frame(stalled_query)

    assert closed.is_set()
    assert source._logged_in is False
    assert time.monotonic() - started < 5.0


def test_daily_ingest_persists_st_when_baostock_confirms_suspension(market, monkeypatch):
    day = date(2026, 7, 6)
    # 停牌确认只针对已登记且当时存续的股票，夹具必须包含股票池事实。
    market.execute("INSERT INTO stock_basic(code,name,list_date) VALUES ('600001.SH','示例','2020-01-01')")
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
    assert market.query_df(
        "SELECT trade_date FROM stock_suspension WHERE code='600001.SH'"
    )["trade_date"].dt.date.tolist() == [day]
    # 重复采集不重复追加停牌记录。
    assert ingest.ingest_one_daily("600001.SH", day, day, source=source) == 0
    assert len(market.query_df("SELECT * FROM stock_suspension")) == 1


@pytest.mark.parametrize('trade_status,returned_day', [
    (1, date(2026, 7, 6)),
    (0, date(2026, 7, 3)),
])
def test_empty_daily_requires_complete_positive_suspension_evidence(
    market, monkeypatch, trade_status, returned_day,
):
    """正常交易行或源端漏一天，均不得凭空登记停牌来消除质检缺口。"""
    day = date(2026, 7, 6)
    market.execute('INSERT INTO trade_calendar VALUES (?,TRUE)', [day])
    source = SimpleNamespace(name='baostock')
    ingest = IngestionService.__new__(IngestionService)
    ingest.c, ingest.src = market, source
    monkeypatch.setattr(
        ingest, '_fetch_daily_with_fallback',
        lambda *_, **__: (_ for _ in ()).throw(DataSourceError('日线为空')),
    )
    monkeypatch.setattr(
        ingest, '_fetch_st_status_rows',
        lambda *_, **__: (source, pd.DataFrame([{
            'code': '600001.SH', 'trade_date': returned_day,
            'is_st': False, 'trade_status': trade_status,
        }])),
    )
    with pytest.raises(DataSourceError, match='日线为空'):
        ingest.ingest_one_daily('600001.SH', day, day, source=source)
    assert market.query_df('SELECT * FROM stock_suspension').empty
    assert market.query_df('SELECT * FROM stock_st_status_daily').empty


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


def test_st_quality_covers_suspensions_and_latest_listed_without_bars(market):
    """行情覆盖完整不能掩盖停牌 ST 缺失，未来退市不得提前免检。"""
    from backend.services.data_report import DataIntegrityReport
    from backend.services.data_verify import DataVerifier

    old_day, day = date(2026, 10, 12), date(2026, 10, 13)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,is_st) VALUES ('MARKET.SH',?,10,FALSE)",
        [day],
    )
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,is_st) "
        "VALUES ('SUSP.SH',DATE '2026-10-09',10,FALSE)"
    )
    market.execute(
        "INSERT INTO stock_basic (code,board,list_date,delist_date) VALUES "
        "('SUSP.SH','主板','2020-01-01','2026-10-19'),"
        "('DELIST.SH','主板','2020-01-01','2026-10-13'),"
        "('FUTURE.SH','主板','2026-10-14',NULL),"
        "('OUT.SH','北交所','2020-01-01',NULL)"
    )
    market.execute(
        "INSERT INTO stock_suspension (code,trade_date) VALUES ('SUSP.SH',?),('SUSP.SH',?),"
        "('SUSP.SH',DATE '2026-10-08'),('SUSP.SH',DATE '2026-10-09'),"
        "('DELIST.SH',DATE '2026-10-08')",
        [old_day, day],
    )
    service = StockSTStatusService(market)
    service.upsert_facts([
        _fact('MARKET.SH', day, False),
        _fact('SUSP.SH', date(2026, 10, 9), False),
    ], change_reason='seed')
    report = DataIntegrityReport(market)
    coverage = service.coverage()
    assert coverage['expected'] == 4  # 日线/停牌重叠、停牌/最新日重叠都只计一次。
    assert coverage['missing'] == 2
    assert coverage['ready'] is False
    issue = report._collect_st_status_issues()
    assert len(issue) == 1 and issue[0]['code'] == 'SUSP.SH'
    assert issue[0]['issue_type'] == 'st_status_missing'
    assert '2 日' in issue[0]['detail']
    scan = report.scan_quality_issues()
    assert scan['st_status_missing_rows'] == 1
    assert market.query_df(
        "SELECT code FROM data_quality_issue WHERE issue_type='st_status_missing' AND status='open'"
    )['code'].tolist() == ['SUSP.SH']
    assert report.recheck_clean('st_status_missing', 'SUSP.SH', day) is False
    verifier = DataVerifier(market, quiet=True)
    verifier.check_structure()
    assert any('权威 ST 点时事实' in name and not ok for name, ok, _ in verifier.results)

    # 停牌缺失补齐但仍非权威时，复检必须转为质量问题，不能声称可用。
    service.upsert_facts([
        _fact('SUSP.SH', old_day, False),
        _fact('SUSP.SH', day, False, STStatusQuality.APPROXIMATE),
    ], change_reason='controlled_import')
    assert report._collect_st_status_issues()[0]['issue_type'] == 'st_status_approximate'
    assert report.recheck_clean('st_status_missing', 'SUSP.SH', day) is False
    assert report.recheck_clean('st_status_approximate', 'SUSP.SH', day) is False
    service.upsert_facts([_fact('SUSP.SH', day, False)], change_reason='refresh')
    assert report._collect_st_status_issues() == []
    assert report.recheck_clean('st_status_approximate', 'SUSP.SH', day) is True
    assert service.coverage()['ready'] is True
    assert service.status_map(day, ['SUSP.SH']) == {'SUSP.SH': False}


def test_st_latest_missing_without_suspension_and_scale(market):
    """代表性规模全链查询：缺行情、尚未确认停牌也要在最新日在市集合中报缺失。"""
    from backend.services.data_report import DataIntegrityReport

    market.execute(
        "INSERT INTO stock_basic (code,board,list_date,delist_date) "
        "SELECT 'S'||i::VARCHAR,'主板',DATE '2020-01-01',DATE '2026-10-19' "
        "FROM range(1000) t(i)"
    )
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,is_st) "
        "SELECT sb.code,DATE '2026-07-15'+d::INTEGER,10,FALSE "
        "FROM stock_basic sb CROSS JOIN range(90) t(d)"
    )
    market.execute(
        "INSERT INTO stock_st_status_daily "
        "(code,trade_date,is_st,source,quality,captured_at,updated_at) "
        "SELECT code,trade_date,FALSE,'baostock','accurate',current_timestamp,current_timestamp "
        "FROM daily_bar"
    )
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,is_st) "
        "VALUES ('S0',DATE '2026-10-13',10,FALSE)"
    )
    market.execute(
        "INSERT INTO stock_st_status_daily "
        "(code,trade_date,is_st,source,quality,captured_at,updated_at) "
        "VALUES ('S0',DATE '2026-10-13',FALSE,'baostock','accurate',"
        "current_timestamp,current_timestamp)"
    )
    service = StockSTStatusService(market)
    coverage = service.coverage()
    assert coverage['expected'] == 91000
    assert coverage['missing'] == 999
    issues = DataIntegrityReport(market)._collect_st_status_issues()
    assert len(issues) == 999
    assert all(issue['trade_date'].date() == date(2026, 10, 13) for issue in issues)


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


def test_result_input_versions_change_only_for_relevant_published_facts(market):
    first = date(2026, 7, 3)
    second = date(2026, 7, 6)
    market.execute(
        "INSERT INTO daily_bar (code,trade_date,close,pre_close,is_st) VALUES "
        "('600001.SH',?,10,9.5,FALSE),('600001.SH',?,10,9.5,FALSE)",
        [first, second],
    )
    service = StockSTStatusService(market)
    captured = datetime(2026, 7, 7, 8, 0, 0, 123456, tzinfo=UTC).replace(tzinfo=None)
    service.upsert_facts(
        [_fact("600001.SH", first, False), _fact("600001.SH", second, False)],
        change_reason="seed",
        captured_at=captured,
    )
    first_date_version = service.input_version_for_date(first)
    second_date_version = service.input_version_for_date(second)
    through_second_version = service.input_version_through(second)
    assert service.input_versions_for_dates([second, first]) == {
        first: first_date_version,
        second: second_date_version,
    }
    assert service.input_versions_through_dates([second, first]) == {
        first: service.input_version_through(first),
        second: through_second_version,
    }

    # 相同事实重采不写 updated_at/history，缓存版本保持不变。
    assert service.upsert_facts(
        [_fact("600001.SH", first, False)],
        change_reason="same_fact",
        captured_at=captured,
    ) == []
    assert service.input_version_for_date(first) == first_date_version
    assert service.input_version_through(second) == through_second_version

    # 即使使用相同捕获时间，历史计数也能识别真实值变化；仅 D 日榜单和 T>=D 天梯受影响。
    service.upsert_facts(
        [_fact("600001.SH", first, True)],
        change_reason="correction",
        captured_at=captured,
    )
    assert service.input_version_for_date(first) != first_date_version
    assert service.input_version_for_date(second) == second_date_version
    assert service.input_version_through(second) != through_second_version


def test_result_input_version_respects_st_publication_gate(market):
    day = date(2026, 7, 6)
    service = StockSTStatusService(market)
    service.begin_refresh(task_id="task-st", target_count=1, start=day, end=day)

    with pytest.raises(STStatusNotReadyError, match="refreshing"):
        service.input_version_for_date(day)
    with pytest.raises(STStatusNotReadyError, match="refreshing"):
        service.input_version_through(day)


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
