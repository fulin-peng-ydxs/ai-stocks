"""T4: completeness gate, immutable publication and invalidation semantics."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from backend.common.exceptions import StorageError
from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.services.ingest import IngestionService
from backend.services.limit_ladder_calculator import LimitLadderCalculator
from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService
from backend.services.stock_st_status import StockSTStatusFact, StockSTStatusService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


def _seed_calendar(market, end: date, count: int = 5) -> list[date]:
    days = [end - timedelta(days=count - index - 1) for index in range(count)]
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": days, "is_open": True})
    )
    return days


def _seed_basic(market, rows: list[tuple]) -> None:
    frame = pd.DataFrame(
        rows,
        columns=["code", "name", "board", "list_date", "industry", "price_limit_pct"],
    )
    MarketRepository(market).upsert_stock_basic(frame)


def _bar(code: str, trade_date: date, *, close: float = 10.0, amount: float = 1000.0):
    return {
        "code": code,
        "trade_date": trade_date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "pre_close": 10.0,
        "volume": 100,
        "amount": amount,
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
        "is_st": False,
        "is_suspended": False,
    }


def _upsert_bars(market, frame: pd.DataFrame) -> None:
    MarketRepository(market).upsert_daily_bar(frame)
    StockSTStatusService(market).upsert_facts([
        StockSTStatusFact(
            code=str(row["code"]),
            trade_date=pd.Timestamp(row["trade_date"]).date(),
            status=PointInTimeSTStatus(
                is_st=bool(row.get("is_st", False)),
                source="test_fixture",
                source_ref="test_limit_ladder_t4",
                quality=STStatusQuality.ACCURATE,
            ),
        )
        for row in frame.to_dict("records")
    ], change_reason="test_fixture", captured_at=datetime.now(UTC))


def _log_terminal(market, trade_date: date, status: str, run_id: str, moment: datetime) -> None:
    detail = json.dumps({
        "kind": "market_day_terminal",
        "run_id": run_id,
        "expected": 1,
        "successful": 1 if status == "success" else 0,
        "failed": 0 if status == "success" else 1,
        "status": status,
    })
    market.execute(
        """
        INSERT INTO data_update_log (
            id,table_name,source,date_start,date_end,row_count,status,detail,updated_at
        ) VALUES (nextval('seq_update_log'),'daily_bar','pipeline',?,?,?,?,?,?)
        """,
        [trade_date, trade_date, 1, status, detail, moment],
    )


def test_gate_distinguishes_non_trading_day(market):
    coverage = LimitLadderSnapshotService(market).check_coverage(date(2026, 8, 30))
    assert coverage.ready is False
    assert coverage.reason_codes == ("NOT_TRADING_DAY",)


def test_gate_does_not_treat_missing_stock_universe_as_legal_empty(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)
    assert coverage.ready is False
    assert coverage.reason_codes == ("POINT_IN_TIME_POOL_EMPTY",)


def test_gate_closes_pool_with_valid_bar_and_confirmed_suspension(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
        ("600002.SH", "乙公司", "主板", date(2020, 1, 1), "软件", 0.10),
        ("600003.SH", "丙公司", "主板", date(2020, 1, 1), "银行", 0.10),
    ])
    _upsert_bars(market, pd.DataFrame([_bar("600001.SH", trade_date)]))
    market.execute(
        "INSERT INTO stock_suspension (code,trade_date,confirmed_at) VALUES (?,?,current_timestamp)",
        ["600002.SH", trade_date],
    )
    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)
    assert coverage.pool_count == 3
    assert coverage.valid_bar_count == 1
    assert coverage.confirmed_suspension_count == 1
    assert coverage.missing_count == 1
    assert coverage.reason_codes == ("MISSING_BAR_OR_SUSPENSION",)

    _upsert_bars(market, pd.DataFrame([_bar("600003.SH", trade_date)]))
    ready = LimitLadderSnapshotService(market).check_coverage(trade_date)
    assert ready.ready is True
    assert ready.ingest_terminal_status == "unknown"


@pytest.mark.parametrize(
    ("day_offset", "residual_bar"),
    [(-1, False), (0, False), (1, False), (0, True)],
)
def test_delisting_boundary_agrees_across_quality_calculation_and_publication(
    market, day_offset, residual_bar
):
    from backend.services.history_quality import HistoryQualityService

    delist_date = date(2026, 8, 28)
    # 覆盖完整上市起点及前五日不限幅窗口，避免截断日历造成未知规则。
    days = _seed_calendar(market, delist_date + timedelta(days=1), count=12)
    trade_date = delist_date + timedelta(days=day_offset)
    _seed_basic(market, [
        ("600001.SH", "在市公司", "主板", days[0], "软件", 0.10),
        ("600002.SH", "退市公司", "主板", days[0], "软件", 0.10),
    ])
    market.execute(
        "UPDATE stock_basic SET delist_date=? WHERE code='600002.SH'", [delist_date]
    )
    bars = [_bar("600001.SH", day, close=11.0) for day in days]
    bars += [_bar("600002.SH", day, close=11.0) for day in days if day < delist_date]
    if residual_bar:
        # 即使残留退市当天行情，也不能把已退市股票重新纳入天梯。
        bars.append(_bar("600002.SH", delist_date, close=11.0))
    _upsert_bars(market, pd.DataFrame(bars))

    expected_codes = {"600001.SH", "600002.SH"} if day_offset < 0 else {"600001.SH"}
    assert HistoryQualityService(market).dates("600002.SH") == []

    service = LimitLadderSnapshotService(market)
    coverage = service.check_coverage(trade_date)
    assert coverage.ready
    assert coverage.pool_count == len(expected_codes)
    assert coverage.valid_bar_count == len(expected_codes)
    assert coverage.missing_count == 0
    calculation = LimitLadderCalculator(market).calculate(trade_date)
    assert {stock.code for stock in calculation.stocks} == expected_codes
    assert not calculation.coverage_issues

    outcome = service.materialize(trade_date)
    assert outcome.status == "valid"
    published = market.query_df(
        "SELECT code FROM limit_ladder_snapshot_stock WHERE snapshot_id=?",
        [outcome.snapshot_id],
    )
    assert set(published.code) == expected_codes


def test_gate_still_requires_data_before_delisting(market):
    trade_date = date(2026, 8, 27)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "即将退市公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    market.execute("UPDATE stock_basic SET delist_date=?", [trade_date + timedelta(days=1)])

    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)
    assert coverage.pool_count == 1
    assert coverage.missing_count == 1
    assert coverage.reason_codes == ("MISSING_BAR_OR_SUSPENSION",)
    calculation = LimitLadderCalculator(market).calculate(trade_date)
    assert {(issue.code, issue.reason) for issue in calculation.coverage_issues} == {
        ("600001.SH", "MISSING_BAR_OR_SUSPENSION"),
    }


def test_gate_uses_latest_structured_terminal_and_ignores_legacy_detail(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(market, pd.DataFrame([_bar("600001.SH", trade_date)]))
    _log_terminal(
        market, trade_date, "failed", "failed-run", datetime(2026, 8, 28, 18, 0, tzinfo=UTC)
    )
    market.execute(
        """
        INSERT INTO data_update_log (
            id,table_name,source,date_start,date_end,row_count,status,detail,updated_at
        ) VALUES (nextval('seq_update_log'),'daily_bar','pipeline',?,?,1,'failed','旧日志',?)
        """,
        [trade_date, trade_date, datetime(2026, 8, 28, 18, 1, tzinfo=UTC)],
    )
    _log_terminal(
        market, trade_date, "success", "success-run", datetime(2026, 8, 28, 18, 2, tzinfo=UTC)
    )
    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)
    assert coverage.ready is True
    assert coverage.ingest_terminal_status == "success"
    assert coverage.ingest_run_id == "success-run"

    _log_terminal(
        market, trade_date, "partial", "partial-run", datetime(2026, 8, 28, 18, 3, tzinfo=UTC)
    )
    covered = LimitLadderSnapshotService(market).check_coverage(trade_date)
    assert covered.ready is True
    assert covered.ingest_terminal_status == "partial"
    assert covered.reason_codes == ()


def test_gate_accepts_confirmed_suspensions_from_partial_ingest(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
        ("600002.SH", "乙公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(market, pd.DataFrame([_bar("600001.SH", trade_date)]))
    market.execute(
        "INSERT INTO stock_suspension (code,trade_date,confirmed_at) "
        "VALUES (?,?,current_timestamp)",
        ["600002.SH", trade_date],
    )
    _log_terminal(
        market, trade_date, "partial", "partial-suspension-run",
        datetime(2026, 8, 28, 18, 0, tzinfo=UTC),
    )

    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)

    assert coverage.valid_bar_count == 1
    assert coverage.confirmed_suspension_count == 1
    assert coverage.missing_count == 0
    assert coverage.ready is True
    assert coverage.reason_codes == ()


def test_gate_accepts_no_pre_close_during_ipo_no_limit_window(market):
    trade_date = date(2026, 9, 9)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("301699.SZ", "洛轴股份", "创业板", trade_date, "通用设备", 0.20),
    ])
    bar = _bar("301699.SZ", trade_date, close=31.99)
    bar.update({"open": 30.0, "high": 36.66, "low": 30.0, "pre_close": None})
    _upsert_bars(market, pd.DataFrame([bar]))

    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)

    assert coverage.ready is True
    assert coverage.valid_bar_count == 1
    assert coverage.invalid_bar_count == 0


def test_gate_still_rejects_missing_pre_close_on_ordinary_limit_day(market):
    trade_date = date(2026, 9, 9)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "普通股票", "主板", date(2020, 1, 1), "制造", 0.10),
    ])
    bar = _bar("600001.SH", trade_date, close=10.0)
    bar["pre_close"] = None
    _upsert_bars(market, pd.DataFrame([bar]))

    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)

    assert coverage.ready is False
    assert coverage.invalid_bar_count == 1
    assert coverage.reason_codes == ("INVALID_DAILY_BAR",)


def test_gate_fingerprint_ignores_explicit_future_concepts(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(market, pd.DataFrame([_bar("600001.SH", trade_date)]))
    market.execute(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES ('C1','未来概念','concept')"
    )
    market.execute(
        "INSERT INTO board_member (board_code,code,first_seen_date) VALUES ('C1','600001.SH',?)",
        [trade_date + timedelta(days=1)],
    )
    service = LimitLadderSnapshotService(market)

    before = service.check_coverage(trade_date).upstream_fingerprint
    market.execute(
        "UPDATE board_member SET first_seen_date=? WHERE board_code='C1' AND code='600001.SH'",
        [trade_date],
    )
    after = service.check_coverage(trade_date).upstream_fingerprint

    assert before != after


def test_legal_empty_snapshot_is_published_and_repeat_creates_immutable_version(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(market, pd.DataFrame([_bar("600001.SH", trade_date)]))
    service = LimitLadderSnapshotService(market)
    first = service.materialize(trade_date, task_id="task-1")
    second = service.materialize(trade_date, task_id="task-2")
    assert first.status == second.status == "valid"
    assert first.snapshot_id != second.snapshot_id
    snapshots = market.query_df(
        "SELECT snapshot_id,stock_count FROM limit_ladder_snapshot ORDER BY computed_at,snapshot_id"
    )
    assert len(snapshots) == 2
    assert snapshots["stock_count"].tolist() == [0, 0]
    state = market.query_df(
        "SELECT status,current_snapshot_id,task_id FROM limit_ladder_snapshot_state"
    ).iloc[0]
    assert state["status"] == "valid"
    assert state["current_snapshot_id"] == second.snapshot_id
    assert state["task_id"] == "task-2"


def test_failed_recompute_keeps_last_success_pointer(market, monkeypatch):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(market,
        pd.DataFrame([_bar("600001.SH", trade_date, close=11.0)])
    )
    service = LimitLadderSnapshotService(market)
    succeeded = service.materialize(trade_date, task_id="task-ok")

    def fail_publish(*args, **kwargs):
        raise RuntimeError("forced publish failure")

    monkeypatch.setattr(service, "publish", fail_publish)
    with pytest.raises(RuntimeError, match="forced publish failure"):
        service.materialize(trade_date, task_id="task-failed")
    state = market.query_df(
        "SELECT status,current_snapshot_id,task_id,failure_summary "
        "FROM limit_ladder_snapshot_state WHERE trade_date=?",
        [trade_date],
    ).iloc[0]
    assert state["status"] == "failed"
    assert state["current_snapshot_id"] == succeeded.snapshot_id
    assert state["task_id"] == "task-failed"
    assert "forced publish failure" in state["failure_summary"]


def test_publication_transaction_rolls_back_partial_version(tmp_path, monkeypatch):
    client = DuckDBClient(tmp_path / "ladder-publish.duckdb")
    init_db(client)
    trade_date = date(2026, 8, 28)
    _seed_calendar(client, trade_date)
    _seed_basic(client, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(client, pd.DataFrame([_bar("600001.SH", trade_date)]))
    service = LimitLadderSnapshotService(client)
    succeeded = service.materialize(trade_date, task_id="task-ok")

    def fail_after_snapshot_meta(*args, **kwargs):
        raise RuntimeError("forced child insert failure")

    monkeypatch.setattr(service, "_insert_frame", fail_after_snapshot_meta)
    with pytest.raises(StorageError, match="forced child insert failure"):
        service.materialize(trade_date, task_id="task-failed")
    snapshots = client.query_df("SELECT snapshot_id FROM limit_ladder_snapshot")
    state = client.query_df(
        "SELECT status,current_snapshot_id,failure_summary FROM limit_ladder_snapshot_state"
    ).iloc[0]
    assert snapshots["snapshot_id"].tolist() == [succeeded.snapshot_id]
    assert state["status"] == "failed"
    assert state["current_snapshot_id"] == succeeded.snapshot_id
    assert "forced child insert failure" in state["failure_summary"]
    client.close()


def test_historical_invalidation_propagates_to_all_later_snapshots(market):
    first = date(2026, 8, 27)
    second = date(2026, 8, 28)
    for trade_date, snapshot_id in ((first, "snap-1"), (second, "snap-2")):
        market.execute(
            """
            INSERT INTO limit_ladder_snapshot_state (
                trade_date,status,current_snapshot_id,rule_version,updated_at
            ) VALUES (?,'valid',?,'v1',current_timestamp)
            """,
            [trade_date, snapshot_id],
        )
    changed = LimitLadderSnapshotService(market).invalidate_dates(
        [first], reason="st_status_changed"
    )
    assert changed == 2
    rows = market.query_df(
        "SELECT trade_date,status,current_snapshot_id,invalid_reason "
        "FROM limit_ladder_snapshot_state ORDER BY trade_date"
    ).to_dict("records")
    assert rows[0]["status"] == "invalid"
    assert rows[0]["current_snapshot_id"] == "snap-1"
    assert rows[0]["invalid_reason"] == "st_status_changed"
    assert rows[1]["status"] == "invalid"
    assert rows[1]["current_snapshot_id"] == "snap-2"
    assert rows[1]["invalid_reason"] == "st_status_changed"


def test_incremental_market_change_does_not_invalidate_ladder(market):
    first = date(2026, 8, 27)
    second = date(2026, 8, 28)
    for trade_date, snapshot_id in ((first, "snap-1"), (second, "snap-2")):
        market.execute(
            "INSERT INTO limit_ladder_snapshot_state "
            "(trade_date,status,current_snapshot_id,rule_version,updated_at) "
            "VALUES (?,'valid',?,'v1',current_timestamp)",
            [trade_date, snapshot_id],
        )

    service = IngestionService.__new__(IngestionService)
    service.c = market
    assert service._mark_snapshots_stale(ladder_dates=[first]) == 0
    rows = market.query_df(
        "SELECT trade_date,status FROM limit_ladder_snapshot_state ORDER BY trade_date"
    ).to_dict("records")
    assert [row["status"] for row in rows] == ["valid", "valid"]


def test_unknown_list_date_is_excluded_from_point_in_time_pool(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "已知", "主板", date(2020, 1, 1), "软件", 0.10),
        ("600002.SH", "未知", "主板", None, "软件", 0.10),
    ])
    _upsert_bars(market,
        pd.DataFrame([_bar("600001.SH", trade_date)])
    )

    coverage = LimitLadderSnapshotService(market).check_coverage(trade_date)

    assert coverage.ready is True
    assert coverage.pool_count == 1


def test_invalidation_outbox_remains_pending_and_raises_on_failure(market, monkeypatch):
    service = LimitLadderSnapshotService(market)
    monkeypatch.setattr(
        service,
        "process_pending_invalidations",
        lambda: (_ for _ in ()).throw(RuntimeError("forced invalidation failure")),
    )
    with pytest.raises(RuntimeError, match="forced invalidation failure"):
        service.request_invalidation([date(2026, 8, 28)], reason="test")
    row = market.query_df(
        "SELECT status,attempt_count,last_error FROM limit_ladder_invalidation_outbox"
    ).iloc[0]
    assert row["status"] == "pending"
    assert int(row["attempt_count"]) == 0
    assert pd.isna(row["last_error"])


def test_pending_invalidation_outbox_replays_to_completion(market):
    trade_date = date(2026, 8, 28)
    market.execute(
        "INSERT INTO limit_ladder_snapshot_state "
        "(trade_date,status,current_snapshot_id,rule_version,updated_at) "
        "VALUES (?,'valid','snap-1','v1',current_timestamp)",
        [trade_date],
    )
    market.execute(
        "INSERT INTO limit_ladder_invalidation_outbox "
        "(event_id,affected_from,reason,status,attempt_count,created_at,updated_at) "
        "VALUES ('pending-replay',?,'retry','pending',0,current_timestamp,current_timestamp)",
        [trade_date],
    )

    assert LimitLadderSnapshotService(market).process_pending_invalidations() == 1
    state = market.query_df(
        "SELECT status,invalid_reason FROM limit_ladder_snapshot_state"
    ).iloc[0]
    event = market.query_df(
        "SELECT status,attempt_count,completed_at FROM limit_ladder_invalidation_outbox"
    ).iloc[0]
    assert state["status"] == "invalid"
    assert state["invalid_reason"] == "retry"
    assert event["status"] == "completed"
    assert int(event["attempt_count"]) == 1
    assert pd.notna(event["completed_at"])


def test_ingest_never_calls_ladder_invalidation(market, monkeypatch):
    def fail_invalidation(*args, **kwargs):
        raise RuntimeError("forced ladder invalidation failure")

    monkeypatch.setattr(
        LimitLadderSnapshotService, "request_invalidation", fail_invalidation
    )
    service = IngestionService.__new__(IngestionService)
    service.c = market

    assert service._mark_snapshots_stale(ladder_dates=[date(2026, 8, 28)]) == 0


def test_coverage_fingerprint_tracks_published_one_word_and_industry_dictionary(market):
    trade_date = date(2026, 8, 28)
    _seed_calendar(market, trade_date)
    _seed_basic(market, [
        ("600001.SH", "甲公司", "主板", date(2020, 1, 1), "软件", 0.10),
    ])
    _upsert_bars(market,
        pd.DataFrame([{**_bar("600001.SH", trade_date, close=11.0), "is_one_word": False}])
    )
    market.execute(
        "INSERT INTO board_dict (board_code,name,board_type) "
        "VALUES ('I001','软件','industry')"
    )
    service = LimitLadderSnapshotService(market)
    initial = service.check_coverage(trade_date).upstream_fingerprint

    market.execute(
        "UPDATE daily_bar SET is_one_word=TRUE WHERE code=? AND trade_date=?",
        ["600001.SH", trade_date],
    )
    one_word_changed = service.check_coverage(trade_date).upstream_fingerprint
    assert one_word_changed != initial

    market.execute("UPDATE board_dict SET board_code='I002' WHERE board_code='I001'")
    industry_changed = service.check_coverage(trade_date).upstream_fingerprint
    assert industry_changed != one_word_changed


def test_ingest_terminal_helper_writes_structured_fact(market):
    service = IngestionService.__new__(IngestionService)
    service.c = market
    service.repo = MarketRepository(market)
    trade_date = date(2026, 8, 28)
    detail = service._log_market_day_terminal(
        trade_date,
        expected=3,
        successful=2,
        failed=1,
        run_id="task-1",
    )
    assert detail["status"] == "partial"
    row = market.query_df(
        "SELECT source,date_start,date_end,status,detail FROM data_update_log"
    ).iloc[0]
    assert row["source"] == "pipeline"
    assert row["status"] == "partial"
    assert json.loads(row["detail"]) == detail


def test_st_fact_change_does_not_implicitly_invalidate_ladder(market):
    trade_date = date(2026, 8, 28)
    for day, snapshot_id in (
        (trade_date, "snap-1"),
        (trade_date + timedelta(days=1), "snap-2"),
    ):
        market.execute(
            """
            INSERT INTO limit_ladder_snapshot_state (
                trade_date,status,current_snapshot_id,rule_version,updated_at
            ) VALUES (?,'valid',?,'v1',current_timestamp)
            """,
            [day, snapshot_id],
        )
    status = PointInTimeSTStatus(
        is_st=True,
        source="exchange_notice",
        source_ref="notice-1",
        quality=STStatusQuality.ACCURATE,
    )
    assert StockSTStatusService(market).upsert_facts(
        [StockSTStatusFact("600001.SH", trade_date, status)],
        change_reason="accurate_backfill",
    ) == [trade_date]
    states = market.query_df(
        "SELECT status,current_snapshot_id,invalid_reason "
        "FROM limit_ladder_snapshot_state ORDER BY trade_date"
    ).to_dict("records")
    assert [state["status"] for state in states] == ["valid", "valid"]
    assert [state["current_snapshot_id"] for state in states] == ["snap-1", "snap-2"]
    assert all(pd.isna(state["invalid_reason"]) for state in states)
