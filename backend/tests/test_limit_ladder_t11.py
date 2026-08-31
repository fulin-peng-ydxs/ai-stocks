"""T11：连板天梯代表性规模入口的轻量契约测试。"""

from backend.devtools.benchmark_limit_ladder_pipeline import (
    TRADE_DATE,
    seed_scale_fixture,
)
from backend.services.limit_ladder_calculator import LimitLadderCalculator


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
