"""连板天梯确定性全链路规模验证。

默认在临时 DuckDB 中构造 5200 只股票、61 个交易日，实际执行数据加载、完整性
门禁、计算、原子发布、动态窗口读取、CSV、失效后旧快照读取和重新发布。临时库在
成功或异常退出后都由上下文清理，不访问项目 ``data/``、PostgreSQL 或网络。
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.indicators.stock_board_correlation import ALGORITHM_VERSION
from backend.services.limit_ladder_calculator import LimitLadderCalculator
from backend.services.limit_ladder_query import LimitLadderFilters, LimitLadderQueryService
from backend.services.limit_ladder_snapshot import LimitLadderSnapshotService
from backend.storage.ddl import init_db
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.repository import MarketRepository

DEFAULT_STOCKS = 5200
DEFAULT_DAYS = 61
TRADE_DATE = date(2026, 8, 28)


class _EmptyTaskRepository:
    @staticmethod
    def get_latest_for_date(_trade_date: date):
        return None

    @staticmethod
    def get_active_for_date(_trade_date: date):
        return None


class _EmptyTaskService:
    @staticmethod
    def get(_task_id: str):
        return None


class _ReadOnlyCoordinator:
    """让隔离读模型不初始化 PG，同时保留真实查询服务代码路径。"""

    repository = _EmptyTaskRepository()
    tasks = _EmptyTaskService()


@dataclass(frozen=True, slots=True)
class LimitLadderScaleReport:
    fixture_stocks: int
    fixture_trade_days: int
    fixture_daily_bars: int
    expected_limit_up_stocks: int
    published_stocks: int
    highest_board: int | None
    batch_queries: int
    snapshot_versions: int
    csv_rows: int
    seed_seconds: float
    first_materialize_seconds: float
    first_query_seconds: float
    batch_verification_seconds: float
    invalidate_seconds: float
    stale_query_seconds: float
    second_materialize_seconds: float
    second_query_seconds: float
    total_seconds: float
    temporary_database_removed: bool
    passed: bool


def _codes(stock_count: int) -> tuple[list[str], np.ndarray, np.ndarray]:
    main_count = stock_count * 3 // 5
    gem_count = stock_count // 5
    codes: list[str] = []
    boards: list[str] = []
    limits: list[float] = []
    for index in range(stock_count):
        if index < main_count:
            codes.append(f"{600000 + index:06d}.SH")
            boards.append("主板")
            limits.append(0.10)
        elif index < main_count + gem_count:
            codes.append(f"{300000 + index - main_count:06d}.SZ")
            boards.append("创业板")
            limits.append(0.20)
        else:
            codes.append(f"{688000 + index - main_count - gem_count:06d}.SH")
            boards.append("科创板")
            limits.append(0.20)
    return codes, np.asarray(boards, dtype=object), np.asarray(limits, dtype=float)


def _insert_frame(client: DuckDBClient, table: str, frame: pd.DataFrame) -> None:
    with client.temp_view(frame, f"scale_{table}") as view:
        columns = ",".join(frame.columns)
        client.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {view}")


def seed_scale_fixture(
    client: DuckDBClient,
    *,
    stock_count: int = DEFAULT_STOCKS,
    trade_days: int = DEFAULT_DAYS,
) -> dict[str, Any]:
    """向传入的隔离库批量加载确定性全市场量级输入。"""
    if stock_count < 200:
        raise ValueError("规模夹具至少需要 200 只股票")
    if trade_days < 60:
        raise ValueError("规模夹具至少需要 60 个交易日")
    init_db(client)
    repository = MarketRepository(client)
    days = [TRADE_DATE - timedelta(days=trade_days - index - 1) for index in range(trade_days)]
    codes, boards, board_limits = _codes(stock_count)
    indexes = np.arange(stock_count)
    is_st = indexes % 97 == 0
    candidate = (indexes % 20 == 0) & ~is_st
    streaks = indexes // 20 % 5 + 1
    industries = np.asarray([f"规模行业{index % 20:02d}" for index in indexes], dtype=object)

    repository.upsert_trade_calendar(pd.DataFrame({"trade_date": days, "is_open": True}))
    repository.upsert_stock_basic(pd.DataFrame({
        "code": codes,
        "name": [
            f"*ST规模股票{index:04d}" if is_st[index] else f"规模股票{index:04d}"
            for index in indexes
        ],
        "board": boards,
        "list_date": date(2020, 1, 1),
        "industry": industries,
        "price_limit_pct": board_limits,
    }))

    row_indexes = np.repeat(indexes, trade_days)
    day_indexes = np.tile(np.arange(trade_days), stock_count)
    row_is_st = is_st[row_indexes]
    row_candidate = candidate[row_indexes]
    row_streaks = streaks[row_indexes]
    row_is_limit = row_candidate & (day_indexes >= trade_days - row_streaks)
    row_limits = np.where(row_is_st, 0.05, board_limits[row_indexes])
    closes = np.where(row_is_limit, 10.0 * (1.0 + row_limits), 10.0)
    one_word = row_is_limit & (row_indexes % 40 == 0)
    repository.upsert_daily_bar(pd.DataFrame({
        "code": np.repeat(np.asarray(codes, dtype=object), trade_days),
        "trade_date": np.tile(np.asarray(days, dtype=object), stock_count),
        "open": np.where(one_word, closes, 10.0),
        "high": closes,
        "low": np.where(one_word, closes, 10.0),
        "close": closes,
        "pre_close": 10.0,
        "volume": 100_000.0,
        "amount": 10_000_000.0 + row_indexes.astype(float),
        "adj_factor": 1.0,
        "turnover_rate": 1.0,
        "is_st": row_is_st,
        "is_suspended": False,
        "limit_status": row_is_limit.astype(int),
        "is_one_word": one_word,
    }))

    industry_codes = [f"SCALE_I_{index:02d}" for index in range(20)]
    concept_codes = [f"SCALE_C_{index:02d}" for index in range(30)]
    _insert_frame(client, "board_dict", pd.DataFrame({
        "board_code": industry_codes + concept_codes,
        "name": [f"规模行业{index:02d}" for index in range(20)]
        + [f"规模概念{index:02d}" for index in range(30)],
        "board_type": ["industry"] * 20 + ["concept"] * 30,
        "source": "limit-ladder-scale",
    }))
    _insert_frame(client, "board_member", pd.DataFrame({
        "board_code": [concept_codes[index % 30] for index in indexes],
        "code": codes,
    }))

    now = datetime(2026, 8, 28, 18, 0, tzinfo=UTC).replace(tzinfo=None)
    correlation_rows = []
    for index, code in enumerate(codes):
        correlation_rows.extend([
            (code, "industry", industry_codes[index % 20]),
            (code, "concept", concept_codes[index % 30]),
        ])
    correlation = pd.DataFrame(correlation_rows, columns=["code", "board_type", "board_code"])
    correlation = correlation.assign(
        score=0.8,
        corr_20=0.82,
        corr_60=0.76,
        sample_20=20,
        sample_60=60,
        confidence="high",
        benchmark_code="000001.SH",
        benchmark_fallback=False,
        as_of_date=TRADE_DATE,
        computed_at=now,
        algorithm_version=ALGORITHM_VERSION,
    )
    _insert_frame(client, "stock_board_correlation", correlation)
    # 同日冠军与发布状态必须成对准备，缺失状态会被真实读取入口当作首次计算。
    _insert_frame(client, "stock_board_correlation_state", pd.DataFrame({
        "code": codes,
        "as_of_date": TRADE_DATE,
        "computed_at": now,
        "algorithm_version": ALGORITHM_VERSION,
        "benchmark_code": "000001.SH",
        "benchmark_fallback": False,
        "has_industry_champion": True,
        "has_concept_champion": True,
    }))
    _insert_frame(client, "stock_st_status_daily", pd.DataFrame({
        "code": np.repeat(np.asarray(codes, dtype=object), trade_days),
        "trade_date": np.tile(np.asarray(days, dtype=object), stock_count),
        "is_st": row_is_st,
        "source": "scale_fixture",
        "source_ref": [f"scale-{index}" for index in row_indexes],
        "quality": "accurate",
        "captured_at": now,
        "updated_at": now,
    }))
    _insert_frame(client, "stock_st_status_date_revision", pd.DataFrame({
        "trade_date": days,
        "revision": stock_count,
        "updated_at": now,
    }))
    detail = json.dumps({
        "kind": "market_day_terminal",
        "run_id": "limit-ladder-scale",
        "expected": stock_count,
        "successful": stock_count,
        "failed": 0,
        "status": "success",
    }, ensure_ascii=False, sort_keys=True)
    client.execute(
        "INSERT INTO data_update_log "
        "(id,table_name,source,date_start,date_end,row_count,status,detail,updated_at) "
        "VALUES (nextval('seq_update_log'),'daily_bar','pipeline',?,?,?,?,?,?)",
        [TRADE_DATE, TRADE_DATE, stock_count * trade_days, "success", detail, now],
    )
    return {
        "codes": codes,
        "daily_bars": stock_count * trade_days,
        "expected_limit_up_stocks": int(candidate.sum()),
        "expected_highest_board": int(streaks[candidate].max()),
    }


def _timed(callable_):
    started = time.perf_counter()
    value = callable_()
    return value, time.perf_counter() - started


def run_scale_verification(
    *,
    stock_count: int = DEFAULT_STOCKS,
    trade_days: int = DEFAULT_DAYS,
) -> LimitLadderScaleReport:
    """运行隔离全链路并对发布、失效、重算和读取不变量做硬断言。"""
    total_started = time.perf_counter()
    report_data: dict[str, Any] = {}
    database_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="ai-stocks-limit-ladder-scale-") as temp_dir:
        database_path = Path(temp_dir) / "limit-ladder-scale.duckdb"
        with DuckDBClient(db_path=database_path) as client:
            fixture, seed_seconds = _timed(
                lambda: seed_scale_fixture(
                    client, stock_count=stock_count, trade_days=trade_days
                )
            )
            snapshot_service = LimitLadderSnapshotService(client)
            first, first_materialize_seconds = _timed(
                lambda: snapshot_service.materialize(
                    TRADE_DATE, task_id="limit-ladder-scale-first", window=60
                )
            )
            if first.status != "valid" or first.snapshot_id is None:
                raise RuntimeError(f"首次规模物化失败: {first.status}")
            query_service = LimitLadderQueryService(
                client,
                coordinator=_ReadOnlyCoordinator(),  # type: ignore[arg-type]
            )
            filters = LimitLadderFilters(window=60, ignore_st=False)
            first_query, first_query_seconds = _timed(
                lambda: query_service.query(TRADE_DATE, filters, trigger_missing=False)
            )
            if first_query["summary"]["stock_count"] != fixture["expected_limit_up_stocks"]:
                raise RuntimeError("首次读取股票数与规模夹具不一致")
            if first_query["summary"]["highest_board"] != fixture["expected_highest_board"]:
                raise RuntimeError("首次读取最高板与规模夹具不一致")
            if first_query["dynamic_window_status"] != "ready":
                raise RuntimeError("动态窗口在完整规模输入下发生降级")
            for kind in ("industry", "concept"):
                if sum(item["stock_count"] for item in first_query["hotspots"][kind]) != (
                    fixture["expected_limit_up_stocks"]
                ):
                    raise RuntimeError(f"{kind} 热点合计与可见股票数不一致")
            batch_calculation, batch_verification_seconds = _timed(
                lambda: LimitLadderCalculator(client).calculate(TRADE_DATE, window=60)
            )
            if batch_calculation.batch_query_count > 2:
                raise RuntimeError(
                    f"规模计算出现额外批次查询: {batch_calculation.batch_query_count}"
                )

            filename, csv_payload = query_service.export_csv(TRADE_DATE, filters)
            if filename != "limit-ladder-2026-08-28-60d.csv":
                raise RuntimeError("规模 CSV 文件名不符合契约")
            csv_rows = csv_payload.decode("utf-8-sig").count("\n") - 1
            if csv_rows != fixture["expected_limit_up_stocks"]:
                raise RuntimeError("规模 CSV 行数与查询集合不一致")

            invalidated, invalidate_seconds = _timed(
                lambda: snapshot_service.invalidate_dates(
                    [TRADE_DATE], reason="scale_verification"
                )
            )
            if invalidated != 1:
                raise RuntimeError("规模失效未命中当前快照")
            stale_query, stale_query_seconds = _timed(
                lambda: query_service.query(TRADE_DATE, filters, trigger_missing=False)
            )
            if stale_query["business_code"] != "SNAPSHOT_STALE":
                raise RuntimeError("失效后未保留旧成功快照读取")
            if stale_query["summary"] != first_query["summary"]:
                raise RuntimeError("失效读取改变了最后成功快照主体")

            second, second_materialize_seconds = _timed(
                lambda: snapshot_service.materialize(
                    TRADE_DATE, task_id="limit-ladder-scale-second", window=60
                )
            )
            if second.status != "valid" or second.snapshot_id in {None, first.snapshot_id}:
                raise RuntimeError("规模重算没有发布新的不可变版本")
            second_query, second_query_seconds = _timed(
                lambda: query_service.query(TRADE_DATE, filters, trigger_missing=False)
            )
            if second_query["business_code"] != "READY":
                raise RuntimeError("规模重算后读取未恢复 READY")
            snapshot_versions = int(client.query_df(
                "SELECT count(*) AS n FROM limit_ladder_snapshot WHERE trade_date=?",
                [TRADE_DATE],
            ).iloc[0]["n"])
            state = client.query_df(
                "SELECT status,current_snapshot_id FROM limit_ladder_snapshot_state "
                "WHERE trade_date=?",
                [TRADE_DATE],
            ).iloc[0]
            if snapshot_versions != 2 or state["current_snapshot_id"] != second.snapshot_id:
                raise RuntimeError("规模重算的版本数或原子指针不正确")

            report_data = {
                "fixture_stocks": stock_count,
                "fixture_trade_days": trade_days,
                "fixture_daily_bars": fixture["daily_bars"],
                "expected_limit_up_stocks": fixture["expected_limit_up_stocks"],
                "published_stocks": second_query["summary"]["stock_count"],
                "highest_board": second_query["summary"]["highest_board"],
                "batch_queries": batch_calculation.batch_query_count,
                "snapshot_versions": snapshot_versions,
                "csv_rows": csv_rows,
                "seed_seconds": seed_seconds,
                "first_materialize_seconds": first_materialize_seconds,
                "first_query_seconds": first_query_seconds,
                "batch_verification_seconds": batch_verification_seconds,
                "invalidate_seconds": invalidate_seconds,
                "stale_query_seconds": stale_query_seconds,
                "second_materialize_seconds": second_materialize_seconds,
                "second_query_seconds": second_query_seconds,
            }
    removed = database_path is not None and not database_path.exists()
    total_seconds = time.perf_counter() - total_started
    return LimitLadderScaleReport(
        **{
            key: round(value, 6) if key.endswith("_seconds") else value
            for key, value in report_data.items()
        },
        total_seconds=round(total_seconds, 6),
        temporary_database_removed=removed,
        passed=removed,
    )


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks", type=int, default=DEFAULT_STOCKS)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args(argv)
    payload = asdict(run_scale_verification(stock_count=args.stocks, trade_days=args.days))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if not payload["passed"]:
        raise SystemExit(1)
    return payload


if __name__ == "__main__":
    main()
