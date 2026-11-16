"""公开回测与个股图表共用的 CI 空库材料、拒写与回滚边界。"""

from datetime import date, datetime

import pytest

from backend.common.exceptions import StorageError
from backend.common.timeutil import SHANGHAI
from backend.devtools import e2e_backtest_runs as fixture
from backend.devtools import e2e_market_data
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


@pytest.mark.parametrize("suite,populated", [("e2e-stocks", False), ("e2e-stocks", True), ("backend", False)])
def test_stock_chart_market_has_both_benchmarks_and_keeps_existing_data(monkeypatch, suite, populated):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    monkeypatch.setenv("AI_STOCKS_CI_SUITE", suite)
    end = date(2026, 11, 14)
    with DuckDBClient(db_path=":memory:") as client:
        init_db(client)
        if populated:
            client.execute("INSERT INTO stock_basic(code,name) VALUES ('600000.SH','保留')")
        if populated or suite != "e2e-stocks":
            with pytest.raises(RuntimeError, match="空临时库" if populated else "仅供隔离 CI 专项"):
                e2e_market_data.seed_ci_market(client, suite="e2e-stocks", end=end)
            assert client.query_df("SELECT count(*) n FROM daily_bar").iloc[0]["n"] == 0
            assert client.query_df("SELECT count(*) n FROM stock_basic").iloc[0]["n"] == int(populated)
            return
        result = e2e_market_data.seed_ci_market(client, suite="e2e-stocks", end=end,
                                             benchmark_codes=("000905.SH", "000300.SH"))
        assert result["stocks"] == 2 and result["trading_days"] > 100
        counts = client.query_df("SELECT index_code,count(*) n FROM index_bar GROUP BY index_code")
        assert dict(zip(counts["index_code"], counts["n"])) == {
            "000905.SH": result["trading_days"], "000300.SH": result["trading_days"],
        }
        assert client.query_df("SELECT count(*) n FROM stock_st_status_daily").iloc[0]["n"] == result["bars"]


def test_shared_ci_market_rolls_back_all_material_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_STOCKS_ENV", "test")
    monkeypatch.setenv("AI_STOCKS_E2E_WRITE", "1")
    monkeypatch.setenv("AI_STOCKS_CI_SUITE", "e2e-stocks")

    def fail(*_args, **_kwargs):
        raise RuntimeError("ST material failure")

    monkeypatch.setattr(e2e_market_data, "seed_non_st_daily", fail)
    # 失败后公共客户端重建连接，持久化临时文件才能核验原事务的回滚结果。
    with DuckDBClient(db_path=str(tmp_path / "market.duckdb")) as client:
        init_db(client)
        with pytest.raises(StorageError, match="ST material failure") as failure:
            e2e_market_data.seed_ci_market(client, suite="e2e-stocks", end=date(2026, 11, 14))
        assert isinstance(failure.value.__cause__, RuntimeError)
        for table in ("stock_basic", "trade_calendar", "daily_bar", "daily_metrics", "index_bar", "stock_st_status_daily"):
            assert client.query_df(f"SELECT count(*) n FROM {table}").iloc[0]["n"] == 0
