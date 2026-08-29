"""个股走势关联板块纯算法的确定性规模基准。

默认构造 5000 只股票、每股 10 个候选，共 50000 组候选关系。输入只存在内存，
不访问数据库或网络；固定随机种子使数据生成可复现。计时仅覆盖逐股相关计算，
输入夹具与共享板块/基准收益映射在计时和 ``tracemalloc`` 启动前完成。
"""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from backend.indicators.stock_board_correlation import (
    ALGORITHM_VERSION,
    CandidateRef,
    PriceSeries,
    calculate_stock_correlations,
    precompute_market_returns,
)

DEFAULT_STOCKS = 5000
DEFAULT_CANDIDATES = 10
DEFAULT_SEED = 20260829


@dataclass(frozen=True)
class BenchmarkFixture:
    dates: tuple[date, ...]
    stocks: dict[str, PriceSeries]
    candidates: tuple[CandidateRef, ...]
    boards: dict[str, PriceSeries]
    benchmarks: dict[str, PriceSeries]


@dataclass(frozen=True)
class BenchmarkResult:
    algorithm_version: str
    seed: int
    stocks: int
    candidates_per_stock: int
    candidate_relations: int
    elapsed_seconds: float
    candidate_throughput_per_second: float
    peak_python_alloc_mib: float


def _closes(dates: tuple[date, ...], returns: np.ndarray) -> dict[date, float]:
    values = [100.0]
    for value in returns:
        values.append(values[-1] * (1.0 + float(value)))
    return dict(zip(dates, values, strict=True))


def build_fixture(
    stock_count: int = DEFAULT_STOCKS,
    candidate_count: int = DEFAULT_CANDIDATES,
    seed: int = DEFAULT_SEED,
) -> BenchmarkFixture:
    """用固定种子构造 61 点有效行情；相同参数生成完全相同的输入。"""
    if stock_count < 1 or candidate_count < 1:
        raise ValueError("股票数和每股候选数必须大于 0")
    rng = np.random.default_rng(seed)
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(61))
    benchmark_returns = rng.normal(0.0002, 0.001, 60)
    benchmarks = {"000001.SH": _closes(dates, benchmark_returns)}
    boards: dict[str, PriceSeries] = {}
    candidates: list[CandidateRef] = []
    for index in range(candidate_count):
        board_code = f"BENCH{index:04d}"
        board_signal = rng.normal(0.0, 0.002, 60)
        boards[board_code] = _closes(dates, benchmark_returns + board_signal)
        candidates.append(
            CandidateRef(board_code, "industry" if index < candidate_count / 2 else "concept")
        )
    stocks = {
        f"{index:06d}.SH": _closes(
            dates,
            benchmark_returns + rng.normal(0.0, 0.002, 60),
        )
        for index in range(stock_count)
    }
    return BenchmarkFixture(dates, stocks, tuple(candidates), boards, benchmarks)


def run_benchmark(
    stock_count: int = DEFAULT_STOCKS,
    candidate_count: int = DEFAULT_CANDIDATES,
    seed: int = DEFAULT_SEED,
) -> BenchmarkResult:
    """执行一次规模基准并返回可序列化结果。"""
    fixture = build_fixture(stock_count, candidate_count, seed)
    board_returns = precompute_market_returns(fixture.boards, fixture.dates)
    benchmark_returns = precompute_market_returns(fixture.benchmarks, fixture.dates)
    tracemalloc.start()
    started = time.perf_counter()
    results = [
        calculate_stock_correlations(
            code=code,
            board="主板",
            calendar_dates=fixture.dates,
            stock_closes=stock_closes,
            candidates=fixture.candidates,
            board_closes=fixture.boards,
            benchmark_closes=fixture.benchmarks,
            board_returns=board_returns,
            benchmark_returns=benchmark_returns,
        )
        for code, stock_closes in fixture.stocks.items()
    ]
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    relation_count = len(results) * len(fixture.candidates)
    return BenchmarkResult(
        algorithm_version=ALGORITHM_VERSION,
        seed=seed,
        stocks=len(results),
        candidates_per_stock=len(fixture.candidates),
        candidate_relations=relation_count,
        elapsed_seconds=round(elapsed, 6),
        candidate_throughput_per_second=round(relation_count / elapsed, 3),
        peak_python_alloc_mib=round(peak / 1024 / 1024, 3),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks", type=int, default=DEFAULT_STOCKS)
    parser.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = _parser().parse_args(argv)
    result = asdict(run_benchmark(args.stocks, args.candidates, args.seed))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
