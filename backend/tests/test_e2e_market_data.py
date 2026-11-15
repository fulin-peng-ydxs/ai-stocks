"""共用 ST 夹具只能清理自身来源、代码和日期交集。"""

from datetime import date

from backend.devtools.e2e_market_data import cleanup_st_daily, seed_non_st_daily
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


def test_st_fixture_cleanup_preserves_other_codes_dates_and_sources():
    day, previous = date(2099, 7, 17), date(2099, 7, 16)
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        seed_non_st_daily(
            client, [("999901.SZ", day), ("999901.SZ", previous), ("999902.SZ", day)],
            source="e2e-owned",
        )
        seed_non_st_daily(client, [("999903.SZ", day)], source="e2e-other")
        assert cleanup_st_daily(
            client, ["999901.SZ", "999903.SZ"], day, day, source="e2e-owned",
        ) == 1
        remaining = client.query_df(
            "SELECT code,trade_date,source,is_st,quality FROM stock_st_status_daily ORDER BY code"
        )
        assert list(zip(remaining["code"], remaining["trade_date"].dt.date, remaining["source"])) == [
            ("999901.SZ", previous, "e2e-owned"), ("999902.SZ", day, "e2e-owned"),
            ("999903.SZ", day, "e2e-other"),
        ]
        assert not remaining["is_st"].any()
        assert set(remaining["quality"]) == {"accurate"}
