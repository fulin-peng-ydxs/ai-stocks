"""个股走势关联板块 v1 纯算法。

所有收益都沿统一市场开市日历计算；缺少任一相邻收盘点时该区间缺失，绝不跨缺口桥接。
本模块不查询或写入数据库，便于固定夹具手算和后续任务原子编排。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise
from typing import Literal

import numpy as np

ALGORITHM_VERSION = "stock-board-correlation-v1"
CALENDAR_POINTS = 61
SHORT_WINDOW = 20
LONG_WINDOW = 60
MIN_SHORT_SAMPLES = 15
MIN_LONG_SAMPLES = 40
FALLBACK_BENCHMARK = "000001.SH"
REQUIRED_BENCHMARKS = frozenset({
    FALLBACK_BENCHMARK,
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
})

BoardType = Literal["industry", "concept"]
PriceSeries = Mapping[date, float | int | None]


class CorrelationInputError(ValueError):
    """统一日历或行情输入不满足算法完整性要求。"""


class BenchmarkDataError(CorrelationInputError):
    """最终上证兜底基准仍不满足 15/40 样本要求。"""


@dataclass(frozen=True)
class CandidateRef:
    board_code: str
    board_type: BoardType


@dataclass(frozen=True)
class CorrelationWinner:
    board_code: str
    board_type: BoardType
    score: float
    corr_20: float
    corr_60: float
    sample_20: int
    sample_60: int
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class StockCorrelationResult:
    code: str
    as_of_date: date
    algorithm_version: str
    benchmark_code: str
    benchmark_fallback: bool
    industry: CorrelationWinner | None
    concept: CorrelationWinner | None


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def normalize_calendar(calendar_dates: Sequence[object]) -> tuple[date, ...]:
    """规范为最近 61 个严格递增、互异的市场开市日。"""
    normalized = tuple(sorted({_as_date(value) for value in calendar_dates}))
    if len(normalized) < CALENDAR_POINTS:
        raise CorrelationInputError(
            f"相关性算法需要 {CALENDAR_POINTS} 个连续开市收盘点，实际 {len(normalized)} 个"
        )
    return normalized[-CALENDAR_POINTS:]


def _valid_price(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return np.isfinite(number) and number > 0


def build_market_returns(
    closes: PriceSeries,
    calendar_dates: Sequence[object],
) -> dict[date, float]:
    """按相邻市场开市日计算收益，结果键为区间结束日；缺口两侧都不生成收益。"""
    calendar = normalize_calendar(calendar_dates)
    returns: dict[date, float] = {}
    for previous_date, current_date in pairwise(calendar):
        previous = closes.get(previous_date)
        current = closes.get(current_date)
        if not (_valid_price(previous) and _valid_price(current)):
            continue
        value = float(current) / float(previous) - 1.0
        if np.isfinite(value):
            returns[current_date] = value
    return returns


def resolve_benchmark_code(board: str | None, code: str) -> tuple[str, bool]:
    """按上市板和交易所确定基准；无法识别时整股回退上证指数。"""
    if board == "主板" and code.endswith(".SH"):
        return FALLBACK_BENCHMARK, False
    if board == "主板" and code.endswith(".SZ"):
        return "399001.SZ", False
    if board == "创业板":
        return "399006.SZ", False
    if board == "科创板":
        return "000688.SH", False
    return FALLBACK_BENCHMARK, True


def winsorized_pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    """分别按 5%/95% 分位缩尾后计算 Pearson；常数或非有限序列无效。"""
    x = np.asarray(left, dtype=float)
    y = np.asarray(right, dtype=float)
    if len(x) != len(y) or len(x) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return None
    x_low, x_high = np.quantile(x, (0.05, 0.95))
    y_low, y_high = np.quantile(y, (0.05, 0.95))
    x = np.clip(x, x_low, x_high)
    y = np.clip(y, y_low, y_high)
    if np.isclose(np.std(x), 0.0, atol=1e-14) or np.isclose(np.std(y), 0.0, atol=1e-14):
        return None
    correlation = float(np.corrcoef(x, y)[0, 1])
    if not np.isfinite(correlation):
        return None
    # 浮点舍入可能产生 1.0000000000000002；收敛到 Pearson 理论域，匹配存储 CHECK。
    return max(-1.0, min(1.0, correlation))


def classify_confidence(
    sample_60: int,
    score: float,
    corr_20: float,
    corr_60: float,
) -> Literal["high", "medium", "low"]:
    same_sign = (corr_20 > 0 and corr_60 > 0) or (corr_20 < 0 and corr_60 < 0)
    if sample_60 >= 50 and score >= 0.70 and same_sign:
        return "high"
    if sample_60 >= MIN_LONG_SAMPLES and score >= 0.50:
        return "medium"
    return "low"


def _has_benchmark_samples(returns: Mapping[date, float], interval_dates: tuple[date, ...]) -> bool:
    short_dates = interval_dates[-SHORT_WINDOW:]
    return (
        sum(day in returns for day in short_dates) >= MIN_SHORT_SAMPLES
        and sum(day in returns for day in interval_dates) >= MIN_LONG_SAMPLES
    )


def _window_correlation(
    stock_returns: Mapping[date, float],
    board_returns: Mapping[date, float],
    benchmark_returns: Mapping[date, float],
    window_dates: Sequence[date],
    minimum_samples: int,
) -> tuple[float, int] | None:
    common_dates = [
        day
        for day in window_dates
        if day in stock_returns and day in board_returns and day in benchmark_returns
    ]
    if len(common_dates) < minimum_samples:
        return None
    stock_neutral = [stock_returns[day] - benchmark_returns[day] for day in common_dates]
    board_neutral = [board_returns[day] - benchmark_returns[day] for day in common_dates]
    correlation = winsorized_pearson(stock_neutral, board_neutral)
    if correlation is None:
        return None
    return correlation, len(common_dates)


def _candidate_result(
    candidate: CandidateRef,
    stock_returns: Mapping[date, float],
    board_returns: Mapping[date, float],
    benchmark_returns: Mapping[date, float],
    interval_dates: tuple[date, ...],
) -> CorrelationWinner | None:
    short = _window_correlation(
        stock_returns,
        board_returns,
        benchmark_returns,
        interval_dates[-SHORT_WINDOW:],
        MIN_SHORT_SAMPLES,
    )
    long = _window_correlation(
        stock_returns,
        board_returns,
        benchmark_returns,
        interval_dates,
        MIN_LONG_SAMPLES,
    )
    if short is None or long is None:
        return None
    corr_20, sample_20 = short
    corr_60, sample_60 = long
    score = 0.6 * corr_20 + 0.4 * corr_60
    if not np.isfinite(score):
        return None
    return CorrelationWinner(
        board_code=candidate.board_code,
        board_type=candidate.board_type,
        score=float(score),
        corr_20=float(corr_20),
        corr_60=float(corr_60),
        sample_20=sample_20,
        sample_60=sample_60,
        confidence=classify_confidence(sample_60, score, corr_20, corr_60),
    )


def pick_correlation_winner(
    results: Iterable[CorrelationWinner],
) -> CorrelationWinner | None:
    """按综合分、60日相关、60日样本和板块代码稳定决胜。"""
    ordered = sorted(
        results,
        key=lambda item: (-item.score, -item.corr_60, -item.sample_60, item.board_code),
    )
    return ordered[0] if ordered else None


def calculate_stock_correlations(
    *,
    code: str,
    board: str | None,
    calendar_dates: Sequence[object],
    stock_closes: PriceSeries,
    candidates: Iterable[CandidateRef],
    board_closes: Mapping[str, PriceSeries],
    benchmark_closes: Mapping[str, PriceSeries],
) -> StockCorrelationResult:
    """计算单股行业/概念冠军；最终基准不足时抛错，个股或候选不足只返回空冠军。"""
    calendar = normalize_calendar(calendar_dates)
    interval_dates = calendar[1:]
    mapped_benchmark, fallback = resolve_benchmark_code(board, code)
    mapped_returns = build_market_returns(
        benchmark_closes.get(mapped_benchmark, {}),
        calendar,
    )
    if not _has_benchmark_samples(mapped_returns, interval_dates):
        if mapped_benchmark == FALLBACK_BENCHMARK:
            raise BenchmarkDataError("上证指数不满足 20/60 日窗口最低样本 15/40")
        mapped_benchmark = FALLBACK_BENCHMARK
        fallback = True
        mapped_returns = build_market_returns(
            benchmark_closes.get(FALLBACK_BENCHMARK, {}),
            calendar,
        )
        if not _has_benchmark_samples(mapped_returns, interval_dates):
            raise BenchmarkDataError("上证指数不满足 20/60 日窗口最低样本 15/40")

    stock_returns = build_market_returns(stock_closes, calendar)
    by_type: dict[BoardType, list[CorrelationWinner]] = {"industry": [], "concept": []}
    seen: set[tuple[BoardType, str]] = set()
    for candidate in candidates:
        key = (candidate.board_type, candidate.board_code)
        if candidate.board_type not in by_type or key in seen:
            continue
        seen.add(key)
        candidate_closes = board_closes.get(candidate.board_code)
        if candidate_closes is None:
            continue
        result = _candidate_result(
            candidate,
            stock_returns,
            build_market_returns(candidate_closes, calendar),
            mapped_returns,
            interval_dates,
        )
        if result is not None:
            by_type[candidate.board_type].append(result)

    return StockCorrelationResult(
        code=code,
        as_of_date=calendar[-1],
        algorithm_version=ALGORITHM_VERSION,
        benchmark_code=mapped_benchmark,
        benchmark_fallback=fallback,
        industry=pick_correlation_winner(by_type["industry"]),
        concept=pick_correlation_winner(by_type["concept"]),
    )
