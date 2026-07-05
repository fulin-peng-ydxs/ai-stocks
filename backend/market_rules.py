"""A-share market trading rules shared by data quality and backtest code."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP


MAIN_BOARD_ST_10_EFFECTIVE_DATE = date(2026, 7, 6)
MAIN_BOARD_ST_OLD_LIMIT = 0.05
CENT = Decimal("0.01")


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


def round_price_to_cent(value: float | int | Decimal) -> float:
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
    up = (pre * (Decimal("1") + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
    down = (pre * (Decimal("1") - rate)).quantize(CENT, rounding=ROUND_HALF_UP)
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
