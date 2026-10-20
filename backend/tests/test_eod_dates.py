"""所有 EOD 入口共享的日期边界、真实临时库落表与日常流程契约。"""

from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.common.exceptions import DataSourceError
from backend.services import eod_dates
from backend.services.board_ingest import BoardIngestService
from backend.services.ingest import IngestionService
from backend.services.pipeline import DailyPipeline
from backend.storage.repository import MarketRepository


@pytest.fixture()
def clock(monkeypatch):
    def set_time(value):
        instant = datetime.fromisoformat(value)
        instant = (
            instant.replace(tzinfo=eod_dates.SHANGHAI)
            if instant.tzinfo is None
            else instant.astimezone(eod_dates.SHANGHAI)
        )
        monkeypatch.setattr(eod_dates, "shanghai_now", lambda: instant)

    set_time("2026-10-20T12:00:00")
    return set_time


@pytest.fixture()
def calendar(market, clock):
    # 模拟 AKShare：只列真实开市日，不补工作日或休市行。
    market.execute(
        "INSERT INTO trade_calendar VALUES ('2026-09-30',TRUE),"
        "('2026-10-09',TRUE),('2026-10-16',TRUE),('2026-10-19',TRUE),"
        "('2026-10-20',TRUE),('2026-10-21',TRUE)"
    )
    return market


@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-10-20T00:00:00", "2026-10-19"),
        ("2026-10-20T03:57:24", "2026-10-19"),
        ("2026-10-20T09:15:00", "2026-10-19"),
        ("2026-10-20T12:00:00", "2026-10-19"),
        ("2026-10-20T15:29:59", "2026-10-19"),
        ("2026-10-20T15:30:00", "2026-10-20"),
        ("2026-10-19T19:57:24+00:00", "2026-10-19"),
        ("2026-10-18T16:00:00", "2026-10-16"),
        ("2026-10-19T03:00:00", "2026-10-16"),
        ("2026-10-08T16:00:00", "2026-09-30"),
        ("2026-10-09T03:00:00", "2026-09-30"),
    ],
)
def test_resolve_end_only_open_calendar(calendar, clock, instant, expected):
    clock(instant)
    assert eod_dates.resolve_end(calendar) == date.fromisoformat(expected)


def test_calendar_missing_coverage_fails_closed(calendar, clock):
    clock("2026-10-22T16:00:00")
    with pytest.raises(DataSourceError, match="日历未覆盖"):
        eod_dates.resolve_end(calendar)


@pytest.mark.parametrize("instant", ["2026-10-20T12:00:00", "2026-10-18T16:00:00"])
def test_force_never_bypasses_close_or_holidays(calendar, clock, instant):
    clock(instant)
    with pytest.raises(DataSourceError):
        eod_dates.resolve_end(calendar, force=True)


def test_force_after_close(calendar, clock):
    clock("2026-10-20T15:30:00")
    assert eod_dates.resolve_end(calendar, force=True) == date(2026, 10, 20)


def test_bound_bars_filters_source_outside_requested_and_closed_dates(clock):
    frame = pd.DataFrame({"trade_date": ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]})
    result = eod_dates.bound_bars(frame, date(2026, 10, 19), date(2026, 10, 21))
    assert result.trade_date.tolist() == ["2026-10-19"]
    assert len(frame) == 4
    assert eod_dates.bound_bars(result, date(2026, 10, 19), date(2026, 10, 19)) is result


def _bars(code=None):
    return pd.DataFrame(
        [
            dict(
                trade_date=day,
                open=10.0,
                high=11.0,
                low=9.0,
                close=10.0,
                pre_close=10.0,
                volume=100.0,
                amount=1000.0,
                adj_factor=1.0,
                turnover_rate=1.0,
                float_share=80.0,
                **({"code": code} if code else {}),
            )
            for day in [date(2026, 10, 19), date(2026, 10, 20)]
        ]
    )


def test_stock_direct_write_excludes_unclosed_source_rows(calendar, monkeypatch):
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = calendar, MarketRepository(calendar)
    svc.src = SimpleNamespace(name="akshare")
    svc.s = SimpleNamespace(datasource=SimpleNamespace(primary="akshare"))
    monkeypatch.setattr(
        svc, "_fetch_daily_with_fallback", lambda *a, **k: (_bars("600519.SH"), "akshare")
    )
    rows = svc.ingest_one_daily("600519.SH", date(2026, 10, 19), date(2026, 10, 20), is_st=False)
    assert rows == 1
    assert calendar.query_df("SELECT trade_date FROM daily_bar").iloc[0, 0].date() == date(
        2026, 10, 19
    )


def test_index_direct_write_excludes_unclosed_source_rows(calendar, monkeypatch):
    from backend.services import ingest as module

    monkeypatch.setattr(module, "configured_benchmark_codes", lambda: ["000001.SH"])
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = calendar, MarketRepository(calendar)
    frame = _bars()[["trade_date", "open", "high", "low", "close", "volume", "amount"]]
    svc.src = SimpleNamespace(
        name="fake", get_index_bar=lambda *a: frame.assign(index_code="000001.SH")
    )
    assert svc.ingest_indices(date(2026, 10, 19), date(2026, 10, 20)) == 1
    assert calendar.query_df("SELECT trade_date FROM index_bar").iloc[0, 0].date() == date(
        2026, 10, 19
    )


def test_board_direct_write_excludes_unclosed_source_rows(calendar):
    calendar.execute(
        "INSERT INTO board_dict(board_code,name,board_type,has_bar) "
        "VALUES ('309121','AI PC','concept',TRUE)"
    )
    source = SimpleNamespace(get_board_bar=lambda *a: _bars())
    svc = BoardIngestService(calendar, source=source)
    result = svc.ingest_board_bar(date(2026, 10, 19), date(2026, 10, 20))
    assert result["rows"] == 1
    assert result["end"] == "2026-10-19" and result["reason"] == "not_closed"
    assert calendar.query_df("SELECT trade_date FROM board_bar").iloc[0, 0].date() == date(
        2026, 10, 19
    )


def test_range_refetch_today_rejects_before_loading(clock):
    with pytest.raises(DataSourceError, match="尚无可写入"):
        IngestionService.__new__(IngestionService).ingest_date(
            date(2026, 10, 20), date(2026, 10, 20)
        )


def test_pipeline_passes_stock_target_instead_of_partial_database_max(calendar, monkeypatch):
    calendar.execute(
        "INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH','2026-10-20',10)"
    )
    monkeypatch.setattr(IngestionService, "__init__", lambda self: None)
    monkeypatch.setattr(IngestionService, "update", lambda *a, **k: {"end": "2026-10-19", "ok": 1})
    captured = []

    def board(*a, target_end=None, **k):
        captured.append(target_end)
        return {"ok": True}

    monkeypatch.setattr(IngestionService, "ingest_board", board)
    result = DailyPipeline(calendar).run(quality=False)
    assert result["ok"] is True and result["run_date"] == "2026-10-19"
    assert captured == [date(2026, 10, 19)]


def test_fund_weekend_only_open_calendar_uses_friday(calendar, clock):
    clock("2026-10-18T16:00:00")
    service = BoardIngestService(calendar, source=SimpleNamespace())
    assert service._validate_fund_snapshot_date() == date(2026, 10, 16)


def test_large_source_window_keeps_only_requested_closed_dates(clock):
    # 约十年日线规模，验证响应过滤保持线性、顺序和输入不变。
    frame = pd.DataFrame({"trade_date": pd.date_range("2016-01-01", periods=4000), "close": 10.0})
    result = eod_dates.bound_bars(frame, date(2016, 10, 19), date(2026, 10, 20))
    assert result.trade_date.min().date() == date(2016, 10, 19)
    assert result.trade_date.max().date() == date(2026, 10, 19)
    assert len(frame) == 4000


def test_stock_ten_year_source_window_filters_and_persists(calendar, monkeypatch):
    """代表性单股十年规模，经过实际采集入口、清洗、股本合并与日线落表。"""
    dates = pd.bdate_range("2016-10-19", "2026-10-20")
    base = _bars("600519.SH").iloc[0].to_dict()
    frame = pd.DataFrame(
        [
            {
                **base,
                "trade_date": day.date(),
            }
            for day in dates
        ]
    )
    svc = IngestionService.__new__(IngestionService)
    svc.c, svc.repo = calendar, MarketRepository(calendar)
    svc.src = SimpleNamespace(name="akshare")
    svc.s = SimpleNamespace(datasource=SimpleNamespace(primary="akshare"))
    monkeypatch.setattr(svc, "_fetch_daily_with_fallback", lambda *a, **k: (frame, "akshare"))
    count = svc.ingest_one_daily("600519.SH", date(2016, 10, 19), date(2026, 10, 20), is_st=False)
    assert count == len(dates) - 1
    row = calendar.query_df("SELECT count(*) n, max(trade_date) d FROM daily_bar").iloc[0]
    assert row["n"] == count and row["d"].date() == date(2026, 10, 19)


def test_range_refetch_pins_actual_end_across_days(clock):
    context = SimpleNamespace(checkpoint={})
    context.set_checkpoint = lambda **data: context.checkpoint.update(data)
    svc = IngestionService.__new__(IngestionService)

    # 在加载股票池的入口截取日期；冻结发生在任何请求或写入之前。
    class Loaded(Exception):
        pass

    captured = []

    def load(*a, as_of=None):
        captured.append(as_of)
        raise Loaded()

    svc._stock_basic_from_db = load
    for instant in ["2026-10-20T12:00:00", "2026-10-21T16:00:00"]:
        clock(instant)
        with pytest.raises(Loaded):
            svc.ingest_date(date(2026, 10, 19), date(2026, 10, 20), ctx=context)
    assert captured == [date(2026, 10, 19), date(2026, 10, 19)]
    assert context.checkpoint["range_end"] == "2026-10-19"


def test_board_resume_range_enlargement_reloads_history(calendar):
    """同日扩大起始范围必须真实补入更早日线，同范围续跑仍能跳过。"""
    calendar.execute(
        "INSERT INTO board_dict(board_code,name,board_type,has_bar) "
        "VALUES ('309121','AI PC','concept',TRUE)"
    )
    frame = _bars().iloc[[0]].copy()
    frame = pd.concat([frame.assign(trade_date=date(2026, 10, 16)), frame], ignore_index=True)
    calls = []

    def fetch(*args):
        calls.append(args)
        return frame

    service = BoardIngestService(calendar, source=SimpleNamespace(get_board_bar=fetch))
    ctx = SimpleNamespace(checkpoint={}, check_cancel=lambda: None, log=lambda *a, **k: None)
    ctx.set_phase = lambda phase, **data: ctx.checkpoint.update(data)
    assert service.ingest_board_bar(date(2026, 10, 19), date(2026, 10, 19), ctx=ctx)["rows"] == 1
    assert service.ingest_board_bar(date(2026, 10, 16), date(2026, 10, 19), ctx=ctx)["rows"] == 2
    assert service.ingest_board_bar(date(2026, 10, 16), date(2026, 10, 19), ctx=ctx)["rows"] == 0
    assert len(calls) == 2
    assert calendar.query_df("SELECT count(*) n FROM board_bar").iloc[0]["n"] == 2
