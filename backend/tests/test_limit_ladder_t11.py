"""T11：连板天梯代表性规模入口的轻量契约测试。"""

from backend.devtools.benchmark_limit_ladder_pipeline import (
    TRADE_DATE,
    seed_scale_fixture,
)
from backend.services.limit_ladder_calculator import LimitLadderCalculator
from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService


def test_scale_fixture_loads_batched_market_inputs_and_20pct_boards(market):
    fixture = seed_scale_fixture(market, stock_count=200, trade_days=60)

    assert fixture["daily_bars"] == 12_000
    assert fixture["expected_limit_up_stocks"] == 9
    assert market.query_df("SELECT count(*) AS n FROM daily_bar").iloc[0]["n"] == 12_000
    assert set(market.query_df("SELECT DISTINCT price_limit_pct FROM stock_basic")[
        "price_limit_pct"
    ].tolist()) == {0.1, 0.2}

    calculation = LimitLadderCalculator(market).calculate(TRADE_DATE, window=60)
    assert len(calculation.stocks) == fixture["expected_limit_up_stocks"]
    assert calculation.summary["highest_board"] == fixture["expected_highest_board"]
    assert calculation.batch_query_count == 2


def test_scoped_history_publishes_with_large_unrequested_history(market):
    """大量无关历史不能进入候选行情或停牌反查；覆盖计算到快照发布的完整入口。"""
    fixture = seed_scale_fixture(market, stock_count=200, trade_days=60)
    market.execute("""
        INSERT INTO daily_bar (code,trade_date,open,high,low,close,pre_close,adj_factor)
        SELECT 'OUTSIDE_' || CAST(code AS VARCHAR),
               DATE '2000-01-01' + CAST(day AS INTEGER),10,10,10,10,10,1
        FROM range(2000) codes(code) CROSS JOIN range(250) days(day)
    """)
    assert market.query_df("SELECT count(*) AS n FROM daily_bar").iloc[0]["n"] == 512_000
    phases = []
    outcome = LimitLadderSnapshotService(market).materialize(
        TRADE_DATE, task_id="scoped-history-regression", phase_callback=phases.append,
    )
    assert outcome.status == "valid"
    assert phases == ["coverage", "calculation", "publication"]
    snapshot = market.query_df(
        "SELECT stock_count FROM limit_ladder_snapshot WHERE snapshot_id=?", [outcome.snapshot_id],
    ).iloc[0]
    assert snapshot["stock_count"] == fixture["expected_limit_up_stocks"]


def test_scale_entry_never_creates_background_tasks(monkeypatch, tmp_path):
    from backend.devtools.benchmark_limit_ladder_pipeline import run_scale_verification
    from backend.services.async_task import AsyncTaskService

    def reject_task(*args, **kwargs):
        raise AssertionError("隔离规模验证不能创建后台任务")

    monkeypatch.setattr(AsyncTaskService, "create", reject_task)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    report = run_scale_verification(stock_count=200, trade_days=60)
    assert report.passed and report.temporary_database_removed
