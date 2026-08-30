"""T1: shared limit-up and point-in-time ST rule contracts."""

from __future__ import annotations

import math

import pytest

from backend.limit_ladder.rules import STStatusQuality, resolve_point_in_time_st
from backend.market_rules import (
    CloseLimitStatus,
    ListingBoard,
    PriceLimitApplicability,
    board_price_limit_pct,
    evaluate_close_limit_up,
    listing_board_for,
)


@pytest.mark.parametrize(
    ("board_pct", "is_st", "trade_date", "close", "expected_pct"),
    [
        (0.10, False, "2026-07-03", 11.00, 0.10),
        (0.10, True, "2026-07-03", 10.50, 0.05),
        (0.10, True, "2026-07-06", 11.00, 0.10),
        (0.20, True, "2026-07-06", 12.00, 0.20),
        (0.20, False, "2026-07-06", 12.00, 0.20),
    ],
)
def test_close_limit_rule_covers_normal_st_and_twenty_percent_boards(
    board_pct, is_st, trade_date, close, expected_pct
):
    result = evaluate_close_limit_up(
        close=close,
        pre_close=10,
        board_limit_pct=board_pct,
        is_st=is_st,
        trade_date=trade_date,
    )
    assert result.status is CloseLimitStatus.LIMIT_UP
    assert result.limit_pct == expected_pct
    assert result.is_publishable is True


def test_close_must_remain_sealed_at_rounded_limit_price():
    below = evaluate_close_limit_up(
        close=10.99,
        pre_close=10,
        board_limit_pct=0.10,
        is_st=False,
        trade_date="2026-08-28",
    )
    assert below.status is CloseLimitStatus.NOT_LIMIT_UP
    assert below.limit_price == 11.0


@pytest.mark.parametrize(
    ("board", "code", "expected"),
    [
        ("主板", None, ListingBoard.MAIN),
        (None, "301001.SZ", ListingBoard.CHINEXT),
        (None, "688981.SH", ListingBoard.STAR),
        (None, "920001.BJ", None),
        ("北交所", "600000.SH", None),
    ],
)
def test_listing_board_resolution_has_no_unknown_fallback(board, code, expected):
    resolved = listing_board_for(board=board, code=code)
    assert resolved is expected
    if resolved is not None:
        assert board_price_limit_pct(resolved) in {0.10, 0.20}


def test_missing_board_limit_ratio_blocks_publication():
    result = evaluate_close_limit_up(
        close=11,
        pre_close=10,
        board_limit_pct=None,
        is_st=False,
        trade_date="2026-08-28",
    )
    assert result.status is CloseLimitStatus.UNSUPPORTED_RULE
    assert result.reason == "LIMIT_PCT_MISSING"


def test_close_above_theoretical_limit_is_invalid_instead_of_limit_up():
    result = evaluate_close_limit_up(
        close=11.01,
        pre_close=10,
        board_limit_pct=0.10,
        is_st=False,
        trade_date="2026-08-28",
    )
    assert result.status is CloseLimitStatus.INVALID_PRICE
    assert result.reason == "CLOSE_ABOVE_LIMIT_PRICE"


def test_unknown_applicability_value_fails_closed():
    result = evaluate_close_limit_up(
        close=11,
        pre_close=10,
        board_limit_pct=0.10,
        is_st=False,
        trade_date="2026-08-28",
        applicability="invalid",  # type: ignore[arg-type]
    )
    assert result.status is CloseLimitStatus.UNSUPPORTED_RULE


@pytest.mark.parametrize(
    ("applicability", "expected", "publishable"),
    [
        (PriceLimitApplicability.NOT_APPLICABLE, CloseLimitStatus.NO_PRICE_LIMIT, True),
        (PriceLimitApplicability.UNKNOWN, CloseLimitStatus.UNSUPPORTED_RULE, False),
    ],
)
def test_special_day_rule_never_falls_back_to_normal_limit(
    applicability, expected, publishable
):
    result = evaluate_close_limit_up(
        close=11,
        pre_close=10,
        board_limit_pct=0.10,
        is_st=False,
        trade_date="2026-08-28",
        applicability=applicability,
    )
    assert result.status is expected
    assert result.is_limit_up is False
    assert result.is_publishable is publishable


@pytest.mark.parametrize("value", [None, 0, -1, math.nan, math.inf])
def test_invalid_price_blocks_snapshot_publication(value):
    result = evaluate_close_limit_up(
        close=value,
        pre_close=10,
        board_limit_pct=0.10,
        is_st=False,
        trade_date="2026-08-28",
    )
    assert result.status is CloseLimitStatus.INVALID_PRICE
    assert result.is_publishable is False


def test_suspension_is_a_publishable_non_limit_up_fact():
    result = evaluate_close_limit_up(
        close=None,
        pre_close=None,
        board_limit_pct=0.10,
        is_st=False,
        is_suspended=True,
    )
    assert result.status is CloseLimitStatus.SUSPENDED
    assert result.is_publishable is True


def test_accurate_st_fact_wins_over_current_name():
    status = resolve_point_in_time_st(
        name="普通名称",
        accurate_is_st=True,
        accurate_source="exchange_notice",
        accurate_source_ref="notice-1",
    )
    assert status.is_st is True
    assert status.quality is STStatusQuality.ACCURATE
    assert status.source == "exchange_notice"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("*ST示例", True), ("S*ST示例", True), ("st示例", True), ("BEST科技", False), (None, False)],
)
def test_name_fallback_is_always_marked_approximate(name, expected):
    status = resolve_point_in_time_st(name=name)
    assert status.is_st is expected
    assert status.quality is STStatusQuality.APPROXIMATE
    assert status.source == "stock_name"


def test_accurate_st_fact_requires_traceable_source():
    with pytest.raises(ValueError, match="requires accurate_source"):
        resolve_point_in_time_st(name="ST示例", accurate_is_st=True)
