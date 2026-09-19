from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from backend.storage.data_source_health_repository import DataSourceHealthRepository


class _Pg:
    def __init__(self):
        self.executed = None

    def query_df(self, sql, params):
        assert "WHERE source = ANY(%s)" in sql
        assert params == [["akshare"]]
        return pd.DataFrame([{
            "source": "akshare",
            "is_up": False,
            "last_test_at": datetime(2026, 9, 19, 20, 0, tzinfo=UTC),
            "last_success_at": datetime(2026, 9, 19, 19, 0, tzinfo=UTC),
            "failure_reason": "连接超时",
        }])

    def execute(self, sql, params):
        self.executed = (sql, params)


def test_health_repository_reads_persisted_status():
    result = DataSourceHealthRepository(_Pg()).list(["akshare"])["akshare"]
    assert result == {
        "up": False,
        "last_test_at": "2026-09-19T20:00:00+00:00",
        "last_success_at": "2026-09-19T19:00:00+00:00",
        "failure_reason": "连接超时",
    }


def test_health_repository_failure_does_not_overwrite_last_success():
    pg = _Pg()
    tested_at = datetime(2026, 9, 19, 20, 0, tzinfo=UTC)
    DataSourceHealthRepository(pg).record(
        "akshare", up=False, tested_at=tested_at, failure_reason="连接超时"
    )
    sql, params = pg.executed
    assert "ELSE data_source_health.last_success_at END" in sql
    assert params == ["akshare", False, tested_at, None, "连接超时", tested_at]
