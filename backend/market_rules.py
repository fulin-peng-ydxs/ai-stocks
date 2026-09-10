"""A-share market trading rules shared by data quality and backtest code."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

MAIN_BOARD_ST_10_EFFECTIVE_DATE = date(2026, 7, 6)
MAIN_BOARD_ST_OLD_LIMIT = 0.05
MAIN_BOARD_REGISTRATION_EFFECTIVE_DATE = date(2023, 4, 10)
CHINEXT_REGISTRATION_EFFECTIVE_DATE = date(2020, 8, 24)
CENT = Decimal("0.01")


class PriceLimitApplicability(StrEnum):
    """Whether a security is subject to a daily price limit on a trade date."""

    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ListingBoard(StrEnum):
    MAIN = "主板"
    CHINEXT = "创业板"
    STAR = "科创板"


class CloseLimitStatus(StrEnum):
    """Stable close-limit result consumed by snapshots and completeness checks."""

    LIMIT_UP = "limit_up"
    NOT_LIMIT_UP = "not_limit_up"
    SUSPENDED = "suspended"
    NO_PRICE_LIMIT = "no_price_limit"
    UNSUPPORTED_RULE = "unsupported_rule"
    INVALID_PRICE = "invalid_price"


@dataclass(frozen=True, slots=True)
class CloseLimitResult:
    """Explainable result of evaluating whether the close is sealed at limit-up."""

    status: CloseLimitStatus
    limit_pct: float | None = None
    limit_price: float | None = None
    reason: str | None = None

    @property
    def is_limit_up(self) -> bool:
        return self.status is CloseLimitStatus.LIMIT_UP

    @property
    def is_publishable(self) -> bool:
        """Unknown rules and invalid prices must block an official snapshot."""
        return self.status not in {
            CloseLimitStatus.UNSUPPORTED_RULE,
            CloseLimitStatus.INVALID_PRICE,
        }


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return datetime.fromisoformat(str(value)).date()


def round_price_to_cent(value: float | Decimal) -> float:
    """Round an A-share price to cents using decimal half-up semantics."""
    if value is None:
        return float("nan")
    value_float = float(value)
    if not math.isfinite(value_float):
        return float("nan")
    rounded = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    return float(rounded)


def limit_prices(pre_close: float, pct: float) -> tuple[float, float]:
    """Return limit-up and limit-down prices rounded to cents."""
    pre = Decimal(str(pre_close))
    rate = Decimal(str(pct))
    up = (pre * (Decimal(1) + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
    down = (pre * (Decimal(1) - rate)).quantize(CENT, rounding=ROUND_HALF_UP)
    return float(up), float(down)


def price_limit_pct_for(
    board_limit_pct: float | None,
    is_st: bool,
    trade_date=None,
) -> float:
    """Effective price limit ratio for a stock on a trade date.

    Main-board ST/*ST stocks used 5% before 2026-07-06 and use 10% from
    2026-07-06 onward. ChiNext/STAR ST stocks keep their board-level 20% limit.
    When trade_date is omitted, keep the old 5% ST fallback to avoid pretending
    an unknown historical date is after the rule change.
    """
    board_pct = 0.10 if board_limit_pct is None else float(board_limit_pct)
    if not is_st:
        return board_pct
    if board_pct >= 0.20 - 1e-12:
        return board_pct
    d = _as_date(trade_date)
    if d is not None and d >= MAIN_BOARD_ST_10_EFFECTIVE_DATE:
        return board_pct
    return MAIN_BOARD_ST_OLD_LIMIT


def price_limit_pct_sql(
    board_limit_expr: str,
    is_st_expr: str,
    trade_date_expr: str,
) -> str:
    """Return the SQL form of :func:`price_limit_pct_for` for internal bulk checks.

    The expressions are supplied only by trusted backend code, never from request input.
    Keeping the cutoff and branch order here prevents large-table verification SQL from
    growing a second hard-coded market-rule implementation.
    """
    board = f"COALESCE(({board_limit_expr}),0.10)"
    cutoff = MAIN_BOARD_ST_10_EFFECTIVE_DATE.isoformat()
    return (
        "CASE "
        f"WHEN NOT COALESCE(({is_st_expr}),FALSE) THEN {board} "
        f"WHEN {board}>=0.20-1e-12 THEN {board} "
        f"WHEN CAST(({trade_date_expr}) AS DATE)>=DATE '{cutoff}' THEN {board} "
        f"ELSE {MAIN_BOARD_ST_OLD_LIMIT} END"
    )


def listing_board_for(*, board: str | None = None, code: str | None = None) -> ListingBoard | None:
    """Resolve the three supported listing boards without an unsafe default."""
    normalized = (board or "").strip().lower()
    aliases = {
        "主板": ListingBoard.MAIN,
        "main": ListingBoard.MAIN,
        "创业板": ListingBoard.CHINEXT,
        "chinext": ListingBoard.CHINEXT,
        "科创板": ListingBoard.STAR,
        "star": ListingBoard.STAR,
    }
    if normalized:
        return aliases.get(normalized)
    code6 = (code or "").split(".", 1)[0]
    if code6.startswith(("300", "301", "302", "303")):
        return ListingBoard.CHINEXT
    if code6.startswith(("688", "689")):
        return ListingBoard.STAR
    if code6.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return ListingBoard.MAIN
    return None


def board_price_limit_pct(board: ListingBoard) -> float:
    """Return the ordinary board-level ratio before point-in-time ST adjustment."""
    if not isinstance(board, ListingBoard):
        raise TypeError(f"unsupported listing board: {board}")
    return 0.20 if board in {ListingBoard.CHINEXT, ListingBoard.STAR} else 0.10


def ipo_price_limit_applicability(
    *,
    board: ListingBoard,
    list_date: date,
    listing_session_number: int,
) -> PriceLimitApplicability:
    """Resolve IPO-day price-limit applicability from supported exchange regimes.

    STAR stocks and registration-based ChiNext/main-board IPOs have no price limit
    for their first five trading sessions. Older main-board IPO first-day rules used
    a special ceiling that this EOD dataset cannot reconstruct, so that one session
    is deliberately ``UNKNOWN`` instead of being treated as an ordinary 10% day.
    """
    if listing_session_number < 1:
        raise ValueError("listing_session_number must be positive")
    if board is ListingBoard.STAR:
        return (
            PriceLimitApplicability.NOT_APPLICABLE
            if listing_session_number <= 5
            else PriceLimitApplicability.APPLICABLE
        )
    if board is ListingBoard.CHINEXT and list_date >= CHINEXT_REGISTRATION_EFFECTIVE_DATE:
        return (
            PriceLimitApplicability.NOT_APPLICABLE
            if listing_session_number <= 5
            else PriceLimitApplicability.APPLICABLE
        )
    if board is ListingBoard.MAIN and list_date >= MAIN_BOARD_REGISTRATION_EFFECTIVE_DATE:
        return (
            PriceLimitApplicability.NOT_APPLICABLE
            if listing_session_number <= 5
            else PriceLimitApplicability.APPLICABLE
        )
    if listing_session_number == 1:
        return PriceLimitApplicability.UNKNOWN
    return PriceLimitApplicability.APPLICABLE


def evaluate_close_limit_up(
    *,
    close: float | Decimal | None,
    pre_close: float | Decimal | None,
    board_limit_pct: float | None,
    is_st: bool,
    trade_date=None,
    applicability: PriceLimitApplicability = PriceLimitApplicability.APPLICABLE,
    is_suspended: bool = False,
) -> CloseLimitResult:
    """Evaluate an EOD close with the shared A-share price-limit rule.

    Callers must resolve listing-day or other special no-limit rules before invoking
    the evaluator. Passing ``UNKNOWN`` deliberately yields a non-publishable result;
    it never falls back to a normal 10% limit.
    """
    try:
        applicability = PriceLimitApplicability(applicability)
    except ValueError:
        return CloseLimitResult(
            CloseLimitStatus.UNSUPPORTED_RULE,
            reason="PRICE_LIMIT_APPLICABILITY_INVALID",
        )
    if is_suspended:
        return CloseLimitResult(CloseLimitStatus.SUSPENDED, reason="SUSPENDED")
    if applicability is PriceLimitApplicability.NOT_APPLICABLE:
        return CloseLimitResult(CloseLimitStatus.NO_PRICE_LIMIT, reason="NO_PRICE_LIMIT")
    if applicability is PriceLimitApplicability.UNKNOWN:
        return CloseLimitResult(
            CloseLimitStatus.UNSUPPORTED_RULE,
            reason="PRICE_LIMIT_APPLICABILITY_UNKNOWN",
        )
    if board_limit_pct is None:
        return CloseLimitResult(CloseLimitStatus.UNSUPPORTED_RULE, reason="LIMIT_PCT_MISSING")

    try:
        close_value = float(close)  # type: ignore[arg-type]
        pre_close_value = float(pre_close)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return CloseLimitResult(CloseLimitStatus.INVALID_PRICE, reason="PRICE_NOT_NUMERIC")
    if (
        not math.isfinite(close_value)
        or not math.isfinite(pre_close_value)
        or close_value <= 0
        or pre_close_value <= 0
    ):
        return CloseLimitResult(CloseLimitStatus.INVALID_PRICE, reason="PRICE_NOT_POSITIVE_FINITE")

    try:
        limit_pct = price_limit_pct_for(board_limit_pct, is_st, trade_date)
    except (TypeError, ValueError):
        return CloseLimitResult(CloseLimitStatus.UNSUPPORTED_RULE, reason="LIMIT_PCT_INVALID")
    if not math.isfinite(limit_pct) or not 0 < limit_pct < 1:
        return CloseLimitResult(CloseLimitStatus.UNSUPPORTED_RULE, reason="LIMIT_PCT_INVALID")

    limit_up, _ = limit_prices(pre_close_value, limit_pct)
    rounded_close = round_price_to_cent(close_value)
    if rounded_close > limit_up:
        return CloseLimitResult(
            CloseLimitStatus.INVALID_PRICE,
            limit_pct=limit_pct,
            limit_price=limit_up,
            reason="CLOSE_ABOVE_LIMIT_PRICE",
        )
    status = CloseLimitStatus.LIMIT_UP if rounded_close == limit_up else CloseLimitStatus.NOT_LIMIT_UP
    return CloseLimitResult(status, limit_pct=limit_pct, limit_price=limit_up)
