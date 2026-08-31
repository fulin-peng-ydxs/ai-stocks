"""个股走势关联板块摘要读取的确定性 DuckDB 基准。

默认在内存 DuckDB 构造 5000 只状态和 10000 行行业/概念冠军，预热后连续测量
1/50/200 只股票的批量摘要读取。每轮同时记录 SQL 次数，避免只看耗时而漏掉 N+1。
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from backend.services.stock_board_correlation import StockBoardCorrelationService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient

DEFAULT_STOCKS = 5000
DEFAULT_ROUNDS = 50
DEFAULT_WARMUPS = 5
READ_SCALES = (1, 50, 200)
THRESHOLDS_MS = {1: 10.0, 50: 20.0, 200: 50.0}
AS_OF_DATE = date(2026, 8, 28)


class _CountingClient:
    def __init__(self, delegate: DuckDBClient):
        self.delegate = delegate
        self.query_count = 0

    def query_df(self, sql: str, params: list[Any] | None = None):
        self.query_count += 1
        return self.delegate.query_df(sql, params)

    def temp_view(self, frame, name: str):
        return self.delegate.temp_view(frame, name)


@dataclass(frozen=True)
class ReadScaleResult:
    codes: int
    rounds: int
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    sql_queries_per_round: int
    threshold_ms: float
    passed: bool


@dataclass(frozen=True)
class ReadBenchmarkReport:
    fixture_stocks: int
    fixture_champions: int
    warmups: int
    results: tuple[ReadScaleResult, ...]

    @property
    def passed(self) -> bool:
        return all(item.passed and item.sql_queries_per_round == 1 for item in self.results)


def _codes(stock_count: int) -> list[str]:
    return [f"{970000 + index:06d}.SZ" for index in range(stock_count)]


def seed_read_fixture(client: DuckDBClient, stock_count: int = DEFAULT_STOCKS) -> list[str]:
    """构造固定当前态读取规模；只用于传入的隔离 DuckDB。"""
    if stock_count < max(READ_SCALES):
        raise ValueError(f"读取基准至少需要 {max(READ_SCALES)} 只股票")
    init_db(client)
    codes = _codes(stock_count)
    client.conn.executemany(
        "INSERT INTO stock_basic (code,name) VALUES (?,?)",
        [(code, f"读取基准股票{index:04d}") for index, code in enumerate(codes, 1)],
    )
    client.conn.executemany(
        "INSERT INTO board_dict (board_code,name,board_type) VALUES (?,?,?)",
        [
            ("BENCH_READ_I", "读取基准行业", "industry"),
            ("BENCH_READ_C", "读取基准概念", "concept"),
        ],
    )
    client.conn.executemany(
        "INSERT INTO stock_board_correlation_state VALUES "
        "(?, ?, TIMESTAMP '2026-08-29 10:00:00', 'stock-board-correlation-v2', "
        "'000001.SH', false, true, true)",
        [(code, AS_OF_DATE) for code in codes],
    )
    champion_rows = []
    for code in codes:
        champion_rows.extend(
            [
                (
                    code, "industry", "BENCH_READ_I", 0.82, 0.86, 0.76, 20, 60, "high",
                    "000001.SH", False, AS_OF_DATE,
                ),
                (
                    code, "concept", "BENCH_READ_C", 0.64, 0.68, 0.58, 20, 60, "medium",
                    "000001.SH", False, AS_OF_DATE,
                ),
            ]
        )
    client.conn.executemany(
        "INSERT INTO stock_board_correlation "
        "(code,board_type,board_code,score,corr_20,corr_60,sample_20,sample_60,confidence,"
        "benchmark_code,benchmark_fallback,as_of_date,computed_at,algorithm_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,TIMESTAMP '2026-08-29 10:00:00',"
        "'stock-board-correlation-v2')",
        champion_rows,
    )
    return codes


def _percentile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def run_read_benchmark(
    *,
    stock_count: int = DEFAULT_STOCKS,
    rounds: int = DEFAULT_ROUNDS,
    warmups: int = DEFAULT_WARMUPS,
) -> ReadBenchmarkReport:
    if rounds < 1 or warmups < 0:
        raise ValueError("rounds 必须大于 0，warmups 不能小于 0")
    with DuckDBClient(db_path=":memory:") as client:
        codes = seed_read_fixture(client, stock_count)
        counting = _CountingClient(client)
        service = StockBoardCorrelationService(counting)  # type: ignore[arg-type]
        results: list[ReadScaleResult] = []
        for scale in READ_SCALES:
            selected = codes[:scale]
            for _ in range(warmups):
                service.get_related_boards(selected, AS_OF_DATE)
            timings: list[float] = []
            query_deltas: list[int] = []
            for _ in range(rounds):
                before = counting.query_count
                started = time.perf_counter_ns()
                summaries = service.get_related_boards(selected, AS_OF_DATE)
                timings.append((time.perf_counter_ns() - started) / 1_000_000)
                query_deltas.append(counting.query_count - before)
                if len(summaries) != scale:
                    raise RuntimeError(f"读取规模异常：期望 {scale}，实际 {len(summaries)}")
            p50 = statistics.median(timings)
            p95 = _percentile_nearest_rank(timings, 0.95)
            sql_queries = max(query_deltas)
            threshold = THRESHOLDS_MS[scale]
            results.append(
                ReadScaleResult(
                    codes=scale,
                    rounds=rounds,
                    p50_ms=round(p50, 3),
                    p95_ms=round(p95, 3),
                    min_ms=round(min(timings), 3),
                    max_ms=round(max(timings), 3),
                    sql_queries_per_round=sql_queries,
                    threshold_ms=threshold,
                    passed=p95 <= threshold and sql_queries == 1,
                )
            )
        return ReadBenchmarkReport(
            fixture_stocks=stock_count,
            fixture_champions=stock_count * 2,
            warmups=warmups,
            results=tuple(results),
        )


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks", type=int, default=DEFAULT_STOCKS)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--enforce", action="store_true", help="未达到耗时或 SQL 门槛时退出失败")
    args = parser.parse_args(argv)
    report = run_read_benchmark(
        stock_count=args.stocks,
        rounds=args.rounds,
        warmups=args.warmups,
    )
    payload = {**asdict(report), "passed": report.passed}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if args.enforce and not report.passed:
        raise SystemExit(1)
    return payload


if __name__ == "__main__":
    main()
