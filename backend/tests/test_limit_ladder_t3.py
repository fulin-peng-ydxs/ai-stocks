"""T3: point-in-time ST persistence, ingestion hook, and ladder calculator."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from backend.config import get_effective_settings
from backend.limit_ladder.rules import PointInTimeSTStatus, STStatusQuality
from backend.services.ingest import IngestionService
from backend.services.limit_ladder_calculator import (
    UNCLASSIFIED_KEY,
    LimitLadderCalculator,
)
from backend.services.stock_st_status import StockSTStatusFact, StockSTStatusService
from backend.storage.repository import MarketRepository


def _status(is_st: bool, source: str, quality: STStatusQuality) -> PointInTimeSTStatus:
    return PointInTimeSTStatus(
        is_st=is_st,
        source=source,
        source_ref=f"{source}-ref",
        quality=quality,
    )


def test_st_status_batch_is_idempotent_and_tracks_real_changes(market):
    service = StockSTStatusService(market)
    trade_date = date(2026, 8, 28)
    approximate = StockSTStatusFact(
        code="600001.SH",
        trade_date=trade_date,
        status=_status(False, "stock_name", STStatusQuality.APPROXIMATE),
    )
    assert service.upsert_facts([approximate], change_reason="daily_ingest") == [trade_date]
    assert service.upsert_facts([approximate], change_reason="daily_ingest") == []
    assert int(market.query_df(
        "SELECT count(*) AS n FROM stock_st_status_history"
    ).iloc[0]["n"]) == 0

    accurate = StockSTStatusFact(
        code=approximate.code,
        trade_date=trade_date,
        status=_status(False, "exchange_notice", STStatusQuality.ACCURATE),
    )
    assert service.upsert_facts(
        [accurate], change_reason="accurate_backfill", task_id="task-1"
    ) == [trade_date]
    history = market.query_df(
        "SELECT old_source,new_source,old_quality,new_quality,task_id "
        "FROM stock_st_status_history"
    )
    assert history.to_dict("records") == [{
        "old_source": "stock_name",
        "new_source": "exchange_notice",
        "old_quality": "approximate",
        "new_quality": "accurate",
        "task_id": "task-1",
    }]

    removed = StockSTStatusFact(
        code=approximate.code,
        trade_date=trade_date,
        status=_status(True, "exchange_notice", STStatusQuality.ACCURATE),
    )
    assert service.upsert_facts([removed], change_reason="status_changed") == [trade_date]
    assert int(market.query_df(
        "SELECT count(*) AS n FROM stock_st_status_history"
    ).iloc[0]["n"]) == 2

    approximate_downgrade = StockSTStatusFact(
        code=approximate.code,
        trade_date=trade_date,
        status=_status(False, "stock_name", STStatusQuality.APPROXIMATE),
    )
    assert service.upsert_facts(
        [approximate_downgrade], change_reason="daily_ingest"
    ) == []
    current = market.query_df(
        "SELECT is_st,source,quality FROM stock_st_status_daily"
    ).iloc[0]
    assert bool(current["is_st"]) is True
    assert current["source"] == "exchange_notice"
    assert current["quality"] == "accurate"
    assert int(market.query_df(
        "SELECT count(*) AS n FROM stock_st_status_history"
    ).iloc[0]["n"]) == 2


def test_ingest_one_daily_persists_accurate_st_fact(market, monkeypatch):
    market.execute(
        "INSERT INTO stock_basic (code,name,board,price_limit_pct,list_date) "
        "VALUES ('600001.SH','*ST示例','主板',0.10,DATE '2020-01-01')"
    )
    service = IngestionService.__new__(IngestionService)
    service.s = get_effective_settings()
    service.c = market
    service.repo = MarketRepository(market)
    service.src = object()
    service._bao = None
    bars = pd.DataFrame([{
        "code": "600001.SH",
        "trade_date": date(2026, 8, 28),
        "open": 10.5,
        "high": 10.5,
        "low": 10.5,
        "close": 10.5,
        "pre_close": 10.0,
        "volume": 100,
        "amount": 1050.0,
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
    }])
    monkeypatch.setattr(
        service,
        "_fetch_daily_with_fallback",
        lambda *args, **kwargs: (bars.copy(), service.s.datasource.primary),
    )
    monkeypatch.setattr(
        service,
        "_accurate_st_facts",
        lambda *args, **kwargs: [StockSTStatusFact(
            code="600001.SH", trade_date=date(2026, 8, 28),
            status=_status(True, "baostock", STStatusQuality.ACCURATE),
        )],
    )
    assert service.ingest_one_daily(
        "600001.SH", date(2026, 8, 28), date(2026, 8, 28), board_limit_pct=0.10
    ) == 1
    row = market.query_df(
        "SELECT is_st,source,quality FROM stock_st_status_daily"
    ).iloc[0]
    assert bool(row["is_st"]) is True
    assert row["source"] == "baostock"
    assert row["quality"] == "accurate"


def test_ingest_one_daily_cannot_downgrade_accurate_st_fact_or_daily_marker(
    market, monkeypatch
):
    trade_date = date(2026, 8, 28)
    market.execute(
        "INSERT INTO stock_basic (code,name,board,price_limit_pct,list_date) "
        "VALUES ('600001.SH','已去星示例','主板',0.10,DATE '2020-01-01')"
    )
    accurate = StockSTStatusFact(
        code="600001.SH",
        trade_date=trade_date,
        status=_status(True, "exchange_notice", STStatusQuality.ACCURATE),
    )
    StockSTStatusService(market).upsert_facts(
        [accurate], change_reason="accurate_backfill"
    )
    service = IngestionService.__new__(IngestionService)
    service.s = get_effective_settings()
    service.c = market
    service.repo = MarketRepository(market)
    service.src = object()
    service._bao = None
    bars = pd.DataFrame([{
        "code": "600001.SH",
        "trade_date": trade_date,
        "open": 10.5,
        "high": 10.5,
        "low": 10.5,
        "close": 10.5,
        "pre_close": 10.0,
        "volume": 100,
        "amount": 1050.0,
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
    }])
    monkeypatch.setattr(
        service,
        "_fetch_daily_with_fallback",
        lambda *args, **kwargs: (bars.copy(), service.s.datasource.primary),
    )
    monkeypatch.setattr(
        service,
        "_accurate_st_facts",
        lambda *args, **kwargs: [accurate],
    )

    assert service.ingest_one_daily(
        "600001.SH", trade_date, trade_date, board_limit_pct=0.10
    ) == 1
    fact = market.query_df(
        "SELECT is_st,source,quality FROM stock_st_status_daily"
    ).iloc[0]
    bar = market.query_df(
        "SELECT is_st FROM daily_bar WHERE code='600001.SH' AND trade_date=?",
        [trade_date],
    ).iloc[0]
    assert bool(fact["is_st"]) is True
    assert fact["source"] == "exchange_notice"
    assert fact["quality"] == "accurate"
    assert bool(bar["is_st"]) is True
    assert int(market.query_df(
        "SELECT count(*) AS n FROM stock_st_status_history"
    ).iloc[0]["n"]) == 0


def _seed_ladder_fixture(market) -> tuple[list[date], date]:
    start = date(2026, 5, 31)
    days = [start + timedelta(days=index) for index in range(80)]
    calendar = pd.DataFrame({"trade_date": days, "is_open": True})
    MarketRepository(market).upsert_trade_calendar(calendar)
    market.execute(
        """
        INSERT INTO stock_basic (code,name,board,list_date,industry,price_limit_pct) VALUES
        ('600001.SH','甲公司','主板',DATE '2020-01-01','软件',0.10),
        ('600002.SH','乙公司','主板',DATE '2020-01-01',NULL,0.10),
        ('688003.SH','新股公司','科创板',?, '软件',0.20),
        ('600004.SH','缺数公司','主板',DATE '2020-01-01','银行',0.10)
        """,
        [days[-3]],
    )
    market.execute(
        """
        INSERT INTO board_dict (board_code,name,board_type,source) VALUES
        ('I1','软件','industry','fixture'),
        ('C1','人工智能','concept','fixture'),
        ('C2','国产软件','concept','fixture')
        """
    )
    market.execute(
        "INSERT INTO board_member (board_code,code) VALUES "
        "('C1','600001.SH'),('C2','600001.SH')"
    )

    rows = []
    for index, day in enumerate(days):
        rows.append({
            "code": "600001.SH",
            "trade_date": day,
            "open": 11.0,
            "high": 11.0,
            "low": 11.0,
            "close": 10.0 if index < 5 else 11.0,
            "pre_close": 10.0,
            "volume": 100,
            "amount": 1000.0 + index,
            "adj_factor": 1.0,
            "turnover_rate": 1.0,
            "is_st": False,
            "is_suspended": False,
            "limit_status": 1 if index >= 5 else 0,
            "is_one_word": index >= 5,
        })
    for index in (77, 78, 79):
        rows.append({
            "code": "600002.SH",
            "trade_date": days[index],
            "open": 11.0,
            "high": 11.0,
            "low": 10.0,
            "close": 11.0,
            "pre_close": 10.0,
            "volume": 100,
            "amount": 500.0,
            "adj_factor": 1.0,
            "turnover_rate": 1.0,
            "is_st": False,
            "is_suspended": False,
            "limit_status": 1,
            "is_one_word": False,
        })
    rows.append({
        "code": "688003.SH",
        "trade_date": days[-1],
        "open": 12.0,
        "high": 12.0,
        "low": 12.0,
        "close": 12.0,
        "pre_close": 10.0,
        "volume": 100,
        "amount": 1200.0,
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
        "is_st": False,
        "is_suspended": False,
        "limit_status": 0,
        "is_one_word": False,
    })
    MarketRepository(market).upsert_daily_bar(pd.DataFrame(rows))
    fact_rows = market.query_df("SELECT code,trade_date FROM daily_bar")
    StockSTStatusService(market).upsert_facts(
        [
            StockSTStatusFact(
                code=str(row["code"]),
                trade_date=pd.Timestamp(row["trade_date"]).date(),
                status=_status(False, "baostock", STStatusQuality.ACCURATE),
            )
            for _, row in fact_rows.iterrows()
        ],
        change_reason="fixture",
    )
    market.execute(
        "INSERT INTO stock_suspension (code,trade_date,confirmed_at) "
        "VALUES ('600002.SH',?,current_timestamp)",
        [days[78]],
    )
    return days, days[-1]


def test_calculator_keeps_75_day_streak_and_batches_remaining_candidates(market):
    days, trade_date = _seed_ladder_fixture(market)
    result = LimitLadderCalculator(market).calculate(trade_date, window=60)
    by_code = {stock.code: stock for stock in result.stocks}
    assert set(by_code) == {"600001.SH", "600002.SH"}
    assert by_code["600001.SH"].consecutive_days == 75
    assert by_code["600001.SH"].window_limit_up_days == 60
    assert by_code["600001.SH"].window_start_date == days[-60]
    assert by_code["600001.SH"].actual_trade_days == 60
    assert by_code["600001.SH"].is_one_word is True
    assert by_code["600002.SH"].consecutive_days == 1
    assert by_code["600002.SH"].window_limit_up_days == 2
    assert result.batch_query_count == 3  # selected day + first 60 + remaining active candidates
    assert result.summary == {"stock_count": 2, "highest_board": 75, "first_board_count": 1}


def test_calculator_freezes_industry_concepts_and_reports_coverage(market):
    _, trade_date = _seed_ladder_fixture(market)
    result = LimitLadderCalculator(market).calculate(trade_date, window=31)
    first = next(stock for stock in result.stocks if stock.code == "600001.SH")
    second = next(stock for stock in result.stocks if stock.code == "600002.SH")
    assert first.industry_name == "软件" and first.industry_board_code == "I1"
    assert [concept.board_code for concept in first.concepts] == ["C1", "C2"]
    assert second.industry_name == "未分类" and second.industry_board_code is None
    aggregate = {
        (item.group_type, item.group_key): item.stock_count for item in result.aggregates
    }
    assert aggregate[("industry", "I1")] == 1
    assert aggregate[("industry", UNCLASSIFIED_KEY)] == 1
    assert aggregate[("concept", "C1")] == 1
    assert aggregate[("concept", "C2")] == 1
    assert aggregate[("concept", UNCLASSIFIED_KEY)] == 1
    issue_keys = {(issue.code, issue.trade_date, issue.reason) for issue in result.coverage_issues}
    assert ("600004.SH", trade_date, "MISSING_BAR_OR_SUSPENSION") in issue_keys
    assert "688003.SH" not in {stock.code for stock in result.stocks}  # IPO no-limit session


def test_calculator_filters_explicit_future_concepts_but_keeps_legacy_null(market):
    _, trade_date = _seed_ladder_fixture(market)
    market.execute(
        "UPDATE board_member SET first_seen_date=NULL WHERE board_code='C1' AND code='600001.SH'"
    )
    market.execute(
        "UPDATE board_member SET first_seen_date=? WHERE board_code='C2' AND code='600001.SH'",
        [trade_date + timedelta(days=1)],
    )

    result = LimitLadderCalculator(market).calculate(trade_date, window=31)

    first = next(stock for stock in result.stocks if stock.code == "600001.SH")
    assert [concept.board_code for concept in first.concepts] == ["C1"]


def test_calculator_uses_per_stock_window_and_missing_day_breaks_streak(market):
    days = [date(2026, 8, 10) + timedelta(days=index) for index in range(15)]
    MarketRepository(market).upsert_trade_calendar(
        pd.DataFrame({"trade_date": days, "is_open": True})
    )
    market.execute(
        """
        INSERT INTO stock_basic (code,name,board,list_date,industry,price_limit_pct) VALUES
        ('600010.SH','短历史公司','主板',?,'软件',0.10),
        ('600011.SH','缺口公司','主板',DATE '2020-01-01','软件',0.10)
        """,
        [days[-10]],
    )
    rows = []
    for index, day in enumerate(days[-10:]):
        rows.append({
            "code": "600010.SH",
            "trade_date": day,
            "open": 11.0 if index == 9 else 10.0,
            "high": 11.0 if index == 9 else 10.0,
            "low": 10.0,
            "close": 11.0 if index == 9 else 10.0,
            "pre_close": 10.0,
            "volume": 100,
            "amount": 1000.0,
            "adj_factor": 1.0,
            "turnover_rate": 1.0,
        })
    rows.append({
        "code": "600011.SH",
        "trade_date": days[-1],
        "open": 11.0,
        "high": 11.0,
        "low": 10.0,
        "close": 11.0,
        "pre_close": 10.0,
        "volume": 100,
        "amount": 900.0,
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
    })
    MarketRepository(market).upsert_daily_bar(pd.DataFrame(rows))
    fact_rows = market.query_df("SELECT code,trade_date FROM daily_bar")
    StockSTStatusService(market).upsert_facts(
        [
            StockSTStatusFact(
                code=str(row["code"]),
                trade_date=pd.Timestamp(row["trade_date"]).date(),
                status=_status(False, "baostock", STStatusQuality.ACCURATE),
            )
            for _, row in fact_rows.iterrows()
        ],
        change_reason="fixture",
    )

    result = LimitLadderCalculator(market).calculate(days[-1], window=20)
    by_code = {stock.code: stock for stock in result.stocks}
    short = by_code["600010.SH"]
    missing = by_code["600011.SH"]
    assert short.window_start_date == days[-10]
    assert short.actual_trade_days == 10
    assert short.window_limit_up_days == 1
    assert short.consecutive_days == 1
    assert missing.consecutive_days == 1
    assert ("600011.SH", days[-2], "MISSING_BAR_OR_SUSPENSION") in {
        (issue.code, issue.trade_date, issue.reason) for issue in result.coverage_issues
    }
    assert result.batch_query_count == 2
