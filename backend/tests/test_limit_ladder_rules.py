"""T1: shared limit-up and point-in-time ST rule contracts."""

from __future__ import annotations

import math
from datetime import date

import pytest

from backend.market_rules import (
    CloseLimitStatus,
    ListingBoard,
    PriceLimitApplicability,
    board_price_limit_pct,
    evaluate_close_limit_up,
    ipo_price_limit_applicability,
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
    ("board", "list_date", "session", "expected"),
    [
        (ListingBoard.STAR, "2019-07-22", 5, PriceLimitApplicability.NOT_APPLICABLE),
        (ListingBoard.STAR, "2019-07-22", 6, PriceLimitApplicability.APPLICABLE),
        (ListingBoard.CHINEXT, "2020-08-24", 1, PriceLimitApplicability.NOT_APPLICABLE),
        (ListingBoard.MAIN, "2023-04-10", 5, PriceLimitApplicability.NOT_APPLICABLE),
        (ListingBoard.MAIN, "2023-04-07", 1, PriceLimitApplicability.UNKNOWN),
        (ListingBoard.MAIN, "2023-04-07", 2, PriceLimitApplicability.APPLICABLE),
    ],
)
def test_ipo_price_limit_applicability_is_regime_and_session_aware(
    board, list_date, session, expected
):
    assert ipo_price_limit_applicability(
        board=board,
        list_date=date.fromisoformat(list_date),
        listing_session_number=session,
    ) is expected


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
