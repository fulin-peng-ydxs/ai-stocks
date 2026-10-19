"""交易日历前瞻采集、运行告警与体检契约。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.services.data_verify import DataVerifier
from backend.services.ingest import IngestionService
from backend.services.trade_calendar_readiness import (
    calendar_request_end,
    inspect_trade_calendar,
)
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository


def test_calendar_request_end_reaches_next_natural_year_without_shrinking_explicit_range():
    as_of = date(2026, 8, 24)
    assert calendar_request_end(date(2026, 8, 24), as_of=as_of) == date(2027, 12, 31)
    assert calendar_request_end(date(2028, 3, 1), as_of=as_of) == date(2028, 3, 1)


def test_calendar_readiness_distinguishes_next_open_from_cross_year_coverage():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        client.execute(
            "INSERT INTO trade_calendar (trade_date,is_open) VALUES "
            "(DATE '2026-08-25',TRUE),(DATE '2026-12-31',TRUE)"
        )
        current_year_only = inspect_trade_calendar(client, as_of=date(2026, 8, 24))
        assert current_year_only["lifecycle_ready"] is True
        assert current_year_only["cross_year_ready"] is False

        client.execute(
            "INSERT INTO trade_calendar (trade_date,is_open) VALUES (DATE '2027-01-04',TRUE)"
        )
        ready = inspect_trade_calendar(client, as_of=date(2026, 8, 24))
        assert ready["next_open_date"] == date(2026, 8, 25)
        assert ready["max_open_date"] == date(2027, 1, 4)
        assert ready["cross_year_ready"] is True


def test_data_verifier_reports_calendar_lifecycle_and_cross_year_readiness():
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        client.execute(
            "INSERT INTO trade_calendar (trade_date,is_open) VALUES (DATE '2026-08-25',TRUE)"
        )
        verifier = DataVerifier(client, quiet=True)
        verifier.check_calendar_readiness(as_of=date(2026, 8, 24))
        assert verifier.results == [
            (
                "交易日历存在下一开市日",
                True,
                "检查日 2026-08-24，下一开市日 2026-08-25，最远开市日 2026-08-25",
            ),
            (
                "交易日历已覆盖下一自然年",
                True,
                "检查日 2026-08-24，下一开市日 2026-08-25，最远开市日 2026-08-25",
            ),
        ]

        assert verifier._structured[-1]["status"] == "warn"


def test_ingest_calendar_requests_extended_horizon_but_only_persists_source_facts(monkeypatch):
    requested: list[tuple[date, date]] = []

    class Source:
        name = "calendar-test"

        @staticmethod
        def get_trade_calendar(start: date, end: date) -> pd.DataFrame:
            requested.append((start, end))
            return pd.DataFrame([{"trade_date": date(2026, 8, 25), "is_open": True}])

    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        service = IngestionService.__new__(IngestionService)
        service.src = Source()
        service.c = client
        service.repo = MarketRepository(client)
        monkeypatch.setattr(
            "backend.services.ingest.calendar_request_end",
            lambda requested_end: date(2027, 12, 31),
        )

        assert service.ingest_calendar(date(2026, 8, 1), date(2026, 8, 24)) == 1
        assert requested == [(date(2026, 8, 1), date(2027, 12, 31))]
        persisted = client.query_df("SELECT trade_date FROM trade_calendar")
        assert persisted["trade_date"].dt.date.tolist() == [date(2026, 8, 25)]
        update_log = client.query_df(
            "SELECT date_end,detail FROM data_update_log WHERE table_name='trade_calendar'"
        ).iloc[0]
        assert update_log["date_end"].date() == date(2027, 12, 31)
        assert "最远开市日 2026-08-25" in update_log["detail"]
