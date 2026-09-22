"""多周期指标聚合与统一 MACD 口径。"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.indicators.compute import compute_macd
from backend.indicators.period import aggregate_period_closes, compute_period_macd


def _daily(dates: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"trade_date": pd.to_datetime(dates), "close": closes})


def test_period_closes_use_natural_boundaries_and_keep_incomplete_period():
    daily = _daily(
        ["2025-12-29", "2026-01-02", "2026-01-05", "2026-01-30", "2026-02-02"],
        [10, 11, 12, 13, 14],
    )

    weekly = aggregate_period_closes(daily, "week")
    monthly = aggregate_period_closes(daily, "month")
    yearly = aggregate_period_closes(daily, "year")

    assert weekly["trade_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-02", "2026-01-05", "2026-01-30", "2026-02-02",
    ]
    assert monthly["trade_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-12-29", "2026-01-30", "2026-02-02",
    ]
    assert yearly["trade_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-12-29", "2026-02-02",
    ]


@pytest.mark.parametrize("period", ["day", "week", "month", "year"])
def test_period_macd_reuses_atomic_formula(period):
    dates = pd.bdate_range("2020-01-01", periods=1800)
    daily = pd.DataFrame({"trade_date": dates, "close": range(1, len(dates) + 1)})
    aggregated = aggregate_period_closes(daily, period)
    actual = compute_period_macd(daily, period)
    expected = compute_macd(aggregated["close"])

    pd.testing.assert_series_equal(actual["macd_diff"], expected["macd_diff"])
    pd.testing.assert_series_equal(actual["macd_dea"], expected["macd_dea"])
    pd.testing.assert_series_equal(actual["macd_hist"], expected["macd_hist"])
    pd.testing.assert_series_equal(
        actual["macd_golden_cross"], expected["macd_golden_cross"]
    )
    pd.testing.assert_series_equal(actual["macd_dead_cross"], expected["macd_dead_cross"])


def test_period_macd_keeps_insufficient_history_nullable():
    daily = pd.DataFrame({
        "trade_date": pd.bdate_range("2026-01-01", periods=120),
        "close": range(1, 121),
    })
    monthly = compute_period_macd(daily, "month")

    assert monthly["macd_diff"].isna().all()
    assert monthly["macd_dea"].isna().all()
    assert monthly["macd_hist"].isna().all()


def test_period_macd_does_not_fill_a_missing_period_close_with_old_values():
    dates = pd.bdate_range("2025-01-01", periods=200)
    daily = pd.DataFrame({"trade_date": dates, "close": range(1, 201)})
    daily.loc[daily.index[-1], "close"] = None

    weekly = compute_period_macd(daily, "week")

    assert pd.isna(weekly.iloc[-1]["macd_diff"])
    assert pd.isna(weekly.iloc[-1]["macd_dea"])
    assert pd.isna(weekly.iloc[-1]["macd_hist"])
    assert pd.isna(weekly.iloc[-1]["macd_golden_cross"])
    assert pd.isna(weekly.iloc[-1]["macd_dead_cross"])
