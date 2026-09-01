"""个股增量截止日回退回归。

只验证日期收敛与缺口收口边界，不访问真实数据源。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import backend.storage.duckdb_client as dc
from backend.services import data_report
from backend.services.ingest import IngestionService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = DuckDBClient(db_path=str(tmp_path / "update-fallback.duckdb"))
    init_db(c)
    monkeypatch.setattr(dc, "_client", c)
    yield c
    c.close()


class _LogCtx:
    def __init__(self):
        self.logs: list[tuple[str, str]] = []

    def log(self, message, level="info"):
        self.logs.append((level, str(message)))


def _service(client, get_daily_bar) -> IngestionService:
    svc = IngestionService.__new__(IngestionService)
    svc.repo = SimpleNamespace(c=client)
    svc.src = SimpleNamespace(get_daily_bar=get_daily_bar)
    return svc


def _seed_calendar(client, rows: list[tuple[date, bool]]) -> None:
    frame = pd.DataFrame(rows, columns=["trade_date", "is_open"])
    client.register_df("_fallback_calendar", frame)
    client.execute(
        "INSERT INTO trade_calendar (trade_date, is_open) "
        "SELECT trade_date, is_open FROM _fallback_calendar"
    )
    client.unregister("_fallback_calendar")


def test_trading_day_not_ready_falls_back_to_previous_open_day(client):
    today = date(2026, 8, 28)
    previous = today - timedelta(days=1)
    _seed_calendar(client, [(previous, True), (today, True)])
    svc = _service(client, lambda *_: pd.DataFrame())
    ctx = _LogCtx()

    target = svc._resolve_update_end(today, [f"{i:06d}.SZ" for i in range(100)], None, ctx)

    assert target == previous
    assert any("未完全就绪" in message and str(previous) in message
               for _, message in ctx.logs)


def test_selected_codes_not_ready_also_fall_back(client):
    today = date(2026, 8, 28)
    previous = today - timedelta(days=1)
    _seed_calendar(client, [(previous, True), (today, True)])
    svc = _service(client, lambda *_: pd.DataFrame())

    target = svc._resolve_update_end(today, ["600000.SH"], ["600000.SH"], _LogCtx())

    assert target == previous


def test_non_trading_day_falls_back_without_readiness_probe(client):
    closed_day = date(2026, 8, 29)
    previous = closed_day - timedelta(days=1)
    _seed_calendar(client, [(previous, True), (closed_day, False)])

    def fail_if_probed(*_):
        raise AssertionError("非交易日不应执行源端就绪探测")

    svc = _service(client, fail_if_probed)
    target = svc._resolve_update_end(
        closed_day, [f"{i:06d}.SZ" for i in range(100)], None, _LogCtx()
    )

    assert target == previous


def test_force_current_day_bypasses_fallback_and_readiness_probe(client):
    closed_day = date(2026, 8, 29)
    previous = closed_day - timedelta(days=1)
    _seed_calendar(client, [(previous, True), (closed_day, False)])

    def fail_if_probed(*_):
        raise AssertionError("强制当日不应执行源端就绪探测")

    ctx = _LogCtx()
    svc = _service(client, fail_if_probed)
    target = svc._resolve_update_end(
        closed_day,
        [f"{i:06d}.SZ" for i in range(100)],
        None,
        ctx,
        force_current_day=True,
    )

    assert target == closed_day
    assert any("强制采集当日" in message for _, message in ctx.logs)


def test_automatic_gap_reconcile_respects_fallback_target(client, monkeypatch):
    requested = date(2026, 8, 28)
    target = requested - timedelta(days=1)
    monkeypatch.setattr(
        data_report.DataIntegrityReport,
        "missing_days_for",
        lambda self, code: [requested],
    )
    svc = _service(client, lambda *_: pd.DataFrame())

    def fail_if_collected(*_, **__):
        raise AssertionError("回退后的缺口收口不得再请求当天")

    svc.ingest_one_daily = fail_if_collected
    result = svc.reconcile_gaps("000001.SZ", confirm=False, through=target)

    assert result == {"miss": [], "backfilled": [], "confirmed": 0, "rows": 0}


def test_update_valuation_respects_fallback_target(client, monkeypatch):
    """市值补采必须沿用已回退的本轮目标日，不能重新取全库最新日。"""
    from backend.config import get_effective_settings

    target = date(2026, 8, 27)
    svc = IngestionService.__new__(IngestionService)
    svc.s = get_effective_settings()
    svc.c = client
    svc.repo = MarketRepository(client)
    svc.src = SimpleNamespace(name="fake")
    svc.ingest_calendar = lambda *_, **__: 0
    svc._resolve_update_end = lambda *_, **__: target
    svc._ingest_indices_incremental = lambda *_, **__: 0
    svc.ingest_valuation = lambda *_, **__: {"total_mv_rows": 0}
    svc._mark_snapshots_stale = lambda **kwargs: 0
    monkeypatch.setattr(data_report.DataIntegrityReport, "gapped_codes", lambda self: [])
    captured: dict[str, date] = {}

    def capture_latest(*_, trade_date=None, **__):
        captured["trade_date"] = trade_date
        return {"total_mv_rows": 0}

    svc.ingest_valuation_latest = capture_latest
    svc.update(concurrency=1)

    assert captured["trade_date"] == target
