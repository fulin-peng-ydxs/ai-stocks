"""公开回测的 CI 空库前置材料与非空库拒写边界。"""

from datetime import datetime

import pytest

from backend.common.timeutil import SHANGHAI
from backend.devtools import e2e_backtest_runs as fixture
from backend.services.stock_st_status import StockSTStatusService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient


@pytest.mark.parametrize("suite,populated", [
    ("e2e-backtest", False), ("e2e-backtest", True), ("backend", False),
])
def test_ci_backtest_market_prepares_complete_material_or_refuses_existing_data(monkeypatch, suite, populated):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    monkeypatch.setenv("AI_STOCKS_CI_SUITE", suite)
    monkeypatch.setattr(
        fixture, "shanghai_now_naive",
        lambda: datetime(2026, 11, 15, 18, tzinfo=SHANGHAI).replace(tzinfo=None),
    )
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        if suite != "e2e-backtest":
            with pytest.raises(RuntimeError, match="仅供隔离 CI 专项"):
                fixture.seed_ci_market(client)
            assert client.query_df("SELECT count(*) n FROM daily_bar").iloc[0]["n"] == 0
            return
        if populated:
            client.execute("INSERT INTO stock_basic(code,name) VALUES ('600000.SH','保留')")
            with pytest.raises(RuntimeError, match="空临时库"):
                fixture.seed_ci_market(client)
            assert client.query_df("SELECT count(*) n FROM trade_calendar").iloc[0]["n"] == 0
            assert client.query_df("SELECT code FROM stock_basic")["code"].tolist() == ["600000.SH"]
            return
        result = fixture.seed_ci_market(client)
        assert result["stocks"] == 2
        assert result["trading_days"] > 100
        assert client.query_df("SELECT count(*) n FROM daily_bar").iloc[0]["n"] == result["bars"]
        last = client.query_df("SELECT max(trade_date) last_date FROM daily_bar").iloc[0]["last_date"].date()
        assert last.isoformat() == "2026-11-13"
        assert StockSTStatusService(client).status_map(last, ["996601.SZ", "996602.SZ"]) == {
            "996601.SZ": False, "996602.SZ": False,
        }
        with pytest.raises(RuntimeError, match="空临时库"):
            fixture.seed_ci_market(client)
