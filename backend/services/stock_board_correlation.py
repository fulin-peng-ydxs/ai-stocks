"""个股走势关联板块领域服务：累计归属与后续相关性能力的统一入口。"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Any, Literal, TypedDict

import pandas as pd

from backend.common.logging import get_logger
from backend.indicators.stock_board_correlation import (
    ALGORITHM_VERSION,
    CALENDAR_POINTS,
    FALLBACK_BENCHMARK,
    MIN_LONG_SAMPLES,
    MIN_SHORT_SAMPLES,
    REQUIRED_BENCHMARKS,
    CandidateRef,
    CorrelationInputError,
    CorrelationWinner,
    PriceSeries,
    StockCorrelationResult,
    calculate_stock_correlations,
    classify_confidence,
    precompute_market_returns,
    resolve_benchmark_code,
)
from backend.services.market_benchmark import MarketBenchmarkService
from backend.services.stock_codes import normalize_stock_code, normalize_stock_codes
from backend.storage.duckdb_client import DuckDBClient, get_client

log = get_logger("services.stock_board_correlation")


class BoardMembershipItem(TypedDict):
    board_code: str
    name: str
    board_type: Literal["industry", "concept"]


class StockBoardMembership(TypedDict):
    code: str
    membership_scope: Literal["cumulative"]
    membership_updated_at: str | None
    industries: list[BoardMembershipItem]
    concepts: list[BoardMembershipItem]


class RelatedBoardWinner(TypedDict):
    board_code: str
    name: str
    score: float
    corr_20: float
    corr_60: float
    sample_20: int
    sample_60: int
    confidence: Literal["high", "medium", "low"]


class RelatedBoardBenchmark(TypedDict):
    code: str | None
    name: str | None
    fallback: bool


class StockRelatedBoards(TypedDict, total=False):
    as_of_date: str | None
    benchmark: RelatedBoardBenchmark
    industry: RelatedBoardWinner | None
    concept: RelatedBoardWinner | None
    unavailable_reason: Literal["as_of_mismatch", "first_load_pending"]


@dataclass(frozen=True)
class LoadedCorrelationInputs:
    """T3 批量加载结果；价格映射仅含目标 61 日历点所在区间且不做收益桥接。"""

    as_of_date: date | None
    calendar_dates: tuple[date, ...]
    stock_boards: dict[str, str | None]
    stock_closes: dict[str, PriceSeries]
    candidates: dict[str, tuple[CandidateRef, ...]]
    board_closes: dict[str, PriceSeries]
    benchmark_closes: dict[str, PriceSeries]


@dataclass(frozen=True)
class CorrelationRunResult:
    """T4 同步编排结果；T5 在此基础上补任务阶段、耗时和失败统计。"""

    target_date: date
    target_count: int
    candidate_count: int
    industry_champion_count: int
    concept_champion_count: int
    empty_result_count: int
    skipped_count: int
    benchmark_counts: dict[str, int]
    fallback_count: int
    calculation_seconds: float
    write_seconds: float
    switched: bool


def _price_series_by_code(
    frame: pd.DataFrame,
    *,
    code_column: str,
    price_column: str,
) -> dict[str, PriceSeries]:
    result: dict[str, PriceSeries] = {}
    for row in frame.to_dict("records"):
        code = str(row[code_column])
        trade_date = pd.Timestamp(row["trade_date"]).date()
        price = row[price_column]
        result.setdefault(code, {})[trade_date] = (
            None if price is None or pd.isna(price) else float(price)
        )
    return result


def normalize_correlation_task_params(
    params: dict[str, Any] | None,
    *,
    client: DuckDBClient | None = None,
) -> dict[str, Any]:
    """规范任务/调度共用参数，并在保存时拒绝未知或项目范围外股票。"""
    if params is not None and not isinstance(params, dict):
        raise ValueError("个股走势关联板块任务参数必须是对象")
    raw = dict(params or {})
    unknown = sorted(set(raw) - {"codes", "force", "trade_date"})
    if unknown:
        raise ValueError(f"个股走势关联板块任务不支持参数: {','.join(unknown)}")
    force = raw.get("force", True)
    if not isinstance(force, bool):
        # API/调度校验统一以 ValueError 映射 400，不让类型错误逃逸成 500。
        raise ValueError("个股走势关联板块任务的 force 必须是布尔值")  # noqa: TRY004
    raw_codes = raw.get("codes")
    if raw_codes is None:
        codes: list[str] = []
    elif isinstance(raw_codes, str):
        code_parts = [part for part in raw_codes.split(",") if part.strip()]
        codes = normalize_stock_codes(code_parts)
    elif isinstance(raw_codes, Iterable) and not isinstance(raw_codes, (dict, bytes)):
        codes = normalize_stock_codes(raw_codes)
    else:
        raise ValueError("个股走势关联板块任务的 codes 必须是数组或逗号分隔文本")
    if codes and client is not None:
        StockBoardCorrelationService(client).validate_configured_codes(codes)
    raw_date = str(raw.get("trade_date") or "").strip()
    if raw_date:
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError("个股走势关联板块固定日期非法，须为 YYYY-MM-DD") from exc
    normalized: dict[str, Any] = {"codes": codes, "force": force}
    if raw_date:
        normalized["trade_date"] = raw_date
    return normalized


class StockBoardCorrelationService:
    """读取累计板块归属与当前冠军摘要，并编排版本化批量计算。"""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    def resolve_data_family_maxima(self) -> dict[str, date | None]:
        """返回个股、板块指数、宽基指数三类日线各自最新交易日；某数据族为空时该值为 None。"""
        maxima = self.c.query_df(
            "SELECT (SELECT max(trade_date) FROM daily_bar) AS daily_bar, "
            "       (SELECT max(trade_date) FROM board_bar) AS board_bar, "
            "       (SELECT max(trade_date) FROM index_bar) AS index_bar"
        ).iloc[0]
        return {
            name: (pd.Timestamp(value).date() if value is not None and not pd.isna(value) else None)
            for name, value in maxima.items()
        }

    def resolve_target_date(self, upper_bound: date | None = None) -> date:
        """取日历、个股、板块和指数四类数据均不晚于的最近开市日。"""
        maxima = self.resolve_data_family_maxima()
        missing = [name for name, value in maxima.items() if value is None]
        if missing:
            raise CorrelationInputError(f"目标日缺少数据事实源: {','.join(missing)}")
        ceiling = min(value for value in maxima.values())
        if upper_bound is not None:
            ceiling = min(ceiling, pd.Timestamp(upper_bound).date())
        calendar = self.c.query_df(
            "SELECT max(trade_date) AS target_date FROM trade_calendar "
            "WHERE is_open=true AND trade_date <= ?",
            [ceiling],
        ).iloc[0]["target_date"]
        if calendar is None or pd.isna(calendar):
            raise CorrelationInputError("共同数据日期之前没有可用开市日")
        return pd.Timestamp(calendar).date()

    def resolve_target_codes(
        self,
        as_of_date: date,
        codes: Iterable[object] | None = None,
    ) -> tuple[list[str], bool]:
        """构造点时全量池，或在任何写入前严格校验显式股票范围。"""
        normalized = normalize_stock_codes([] if codes is None else codes)
        full_scope = not normalized
        supported_boards = ("主板", "创业板", "科创板")
        if full_scope:
            rows = self.c.query_df(
                "SELECT code FROM stock_basic "
                "WHERE list_date <= ? AND (delist_date IS NULL OR delist_date > ?) "
                "  AND board IN ('主板', '创业板', '科创板') "
                "  AND regexp_matches(code, '^[0-9]{6}\\.(SH|SZ)$') "
                "ORDER BY code",
                [as_of_date, as_of_date],
            )
            targets = [str(value) for value in rows["code"].tolist()]
            if not targets:
                raise CorrelationInputError("目标日项目范围内的在市股票池为空")
            return targets, True

        placeholders = ",".join("?" for _ in normalized)
        rows = self.c.query_df(
            f"SELECT code, board, list_date, delist_date FROM stock_basic "
            f"WHERE code IN ({placeholders})",
            normalized,
        )
        by_code = {str(row["code"]): row for row in rows.to_dict("records")}
        errors: list[str] = []
        for code in normalized:
            row = by_code.get(code)
            if row is None:
                errors.append(f"{code}:未知股票")
                continue
            board = None if pd.isna(row["board"]) else str(row["board"])
            list_date = row["list_date"]
            delist_date = row["delist_date"]
            if board not in supported_boards:
                errors.append(f"{code}:不属于主板/创业板/科创板")
            if list_date is None or pd.isna(list_date):
                errors.append(f"{code}:缺少上市日期")
            elif pd.Timestamp(list_date).date() > as_of_date:
                errors.append(f"{code}:目标日尚未上市")
            if (
                delist_date is not None
                and not pd.isna(delist_date)
                and pd.Timestamp(delist_date).date() <= as_of_date
            ):
                errors.append(f"{code}:目标日已退市")
        if errors:
            raise CorrelationInputError("股票范围校验失败: " + "; ".join(errors))
        return normalized, False

    def validate_configured_codes(self, codes: Iterable[object]) -> list[str]:
        """调度保存期只校验存在性和项目板块；上市/退市点时状态留到执行期校验。"""
        normalized = normalize_stock_codes(codes)
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        rows = self.c.query_df(
            f"SELECT code, board FROM stock_basic WHERE code IN ({placeholders})",
            normalized,
        )
        by_code = {
            str(row["code"]): None if pd.isna(row["board"]) else str(row["board"])
            for row in rows.to_dict("records")
        }
        errors = []
        for code in normalized:
            if code not in by_code:
                errors.append(f"{code}:未知股票")
            elif by_code[code] not in ("主板", "创业板", "科创板"):
                errors.append(f"{code}:不属于主板/创业板/科创板")
        if errors:
            raise CorrelationInputError("股票范围校验失败: " + "; ".join(errors))
        return normalized

    def _target_is_current(
        self,
        codes: list[str],
        as_of_date: date,
        *,
        full_scope: bool,
    ) -> bool:
        placeholders = ",".join("?" for _ in codes)
        matched = self.c.query_df(
            "SELECT count(*) AS n FROM stock_board_correlation_state "
            f"WHERE code IN ({placeholders}) AND as_of_date=? AND algorithm_version=?",
            [*codes, as_of_date, ALGORITHM_VERSION],
        ).iloc[0]["n"]
        if int(matched) != len(codes):
            return False
        if not full_scope:
            return True
        state_count = int(
            self.c.query_df(
                "SELECT count(*) AS n FROM stock_board_correlation_state WHERE as_of_date=?",
                [as_of_date],
            ).iloc[0]["n"]
        )
        outside_winners = int(
            self.c.query_df(
                "SELECT count(*) AS n FROM stock_board_correlation "
                f"WHERE code NOT IN ({placeholders}) AND as_of_date=?",
                [*codes, as_of_date],
            ).iloc[0]["n"]
        )
        return state_count == len(codes) and outside_winners == 0

    def _current_scope_statistics(self, codes: list[str], as_of_date: date) -> dict[str, Any]:
        """跳过计算时读取该目标日范围真实统计，避免把“未重算”误报成零冠军。"""
        placeholders = ",".join("?" for _ in codes)
        candidates = int(
            self.c.query_df(
                "SELECT count(*) AS n FROM board_member bm "
                "INNER JOIN board_dict bd ON bd.board_code=bm.board_code "
                f"WHERE bm.code IN ({placeholders}) "
                "AND bd.board_type IN ('industry','concept') "
                "AND (bm.first_seen_date IS NULL OR bm.first_seen_date<=?)",
                [*codes, as_of_date],
            ).iloc[0]["n"]
        )
        champions = self.c.query_df(
            "SELECT board_type,count(*) AS n FROM stock_board_correlation "
            f"WHERE code IN ({placeholders}) AND as_of_date=? GROUP BY board_type",
            [*codes, as_of_date],
        )
        champion_counts = {
            str(row["board_type"]): int(row["n"]) for row in champions.to_dict("records")
        }
        state = self.c.query_df(
            "SELECT count(*) FILTER (WHERE NOT has_industry_champion "
            "AND NOT has_concept_champion) AS empty_count, "
            "count(*) FILTER (WHERE benchmark_fallback) AS fallback_count "
            "FROM stock_board_correlation_state "
            f"WHERE code IN ({placeholders}) AND as_of_date=?",
            [*codes, as_of_date],
        ).iloc[0]
        benchmarks = self.c.query_df(
            "SELECT benchmark_code,count(*) AS n FROM stock_board_correlation_state "
            f"WHERE code IN ({placeholders}) AND as_of_date=? GROUP BY benchmark_code",
            [*codes, as_of_date],
        )
        return {
            "candidate_count": candidates,
            "industry_count": champion_counts.get("industry", 0),
            "concept_count": champion_counts.get("concept", 0),
            "empty_count": int(state["empty_count"] or 0),
            "fallback_count": int(state["fallback_count"] or 0),
            "benchmark_counts": {
                str(row["benchmark_code"]): int(row["n"]) for row in benchmarks.to_dict("records")
            },
        }

    def compute_and_replace(
        self,
        codes: Iterable[object] | None = None,
        *,
        force: bool = False,
        upper_bound: date | None = None,
        computed_at: datetime | None = None,
        phase_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> CorrelationRunResult:
        """完整计算目标范围，并在校验成功后按目标交易日写入当天快照（不影响其它日）。"""

        def enter_phase(phase: str) -> None:
            if phase_callback is not None:
                phase_callback(phase)
            if cancel_check is not None:
                cancel_check()

        if not isinstance(force, bool):
            raise CorrelationInputError("force 必须为布尔值")
        enter_phase("read_candidates")
        target_date = self.resolve_target_date(upper_bound)
        targets, full_scope = self.resolve_target_codes(target_date, codes)
        if not force and self._target_is_current(targets, target_date, full_scope=full_scope):
            current = self._current_scope_statistics(targets, target_date)
            return CorrelationRunResult(
                target_date,
                len(targets),
                current["candidate_count"],
                current["industry_count"],
                current["concept_count"],
                current["empty_count"],
                len(targets),
                current["benchmark_counts"],
                current["fallback_count"],
                0.0,
                0.0,
                False,
            )

        enter_phase("load_prices")
        bundle = self.load_correlation_inputs(targets, target_date)
        if bundle.as_of_date != target_date:
            raise CorrelationInputError("批量输入实际日期与目标日不一致")
        if set(bundle.stock_boards) != set(targets):
            missing = sorted(set(targets) - set(bundle.stock_boards))
            raise CorrelationInputError(f"批量输入缺少目标股票: {','.join(missing)}")

        enter_phase("calculate")
        calculation_started = time.perf_counter()
        # 板块与指数行情已按唯一代码加载；收益也按唯一代码构造，避免按候选关系重复计算。
        board_returns = precompute_market_returns(bundle.board_closes, bundle.calendar_dates)
        benchmark_returns = precompute_market_returns(
            bundle.benchmark_closes,
            bundle.calendar_dates,
        )
        results = []
        for index, code in enumerate(targets):
            if index and index % 100 == 0 and cancel_check is not None:
                cancel_check()
            results.append(
                calculate_stock_correlations(
                    code=code,
                    board=bundle.stock_boards[code],
                    calendar_dates=bundle.calendar_dates,
                    stock_closes=bundle.stock_closes.get(code, {}),
                    candidates=bundle.candidates.get(code, ()),
                    board_closes=bundle.board_closes,
                    benchmark_closes=bundle.benchmark_closes,
                    board_returns=board_returns,
                    benchmark_returns=benchmark_returns,
                )
            )
        # DuckDB computed_at 为无时区 TIMESTAMP，沿用仓库既有本地时间口径。
        timestamp = computed_at or datetime.now()  # noqa: DTZ005
        enter_phase("validate")
        states, champions = self._build_and_validate_rows(
            targets,
            target_date,
            timestamp,
            results,
            bundle.stock_boards,
        )
        calculation_seconds = time.perf_counter() - calculation_started
        enter_phase("switch")
        write_started = time.perf_counter()
        self._replace_rows(states, champions, targets, full_scope=full_scope)
        write_seconds = time.perf_counter() - write_started

        benchmark_counts: dict[str, int] = {}
        for result in results:
            benchmark_counts[result.benchmark_code] = (
                benchmark_counts.get(result.benchmark_code, 0) + 1
            )
        industry_count = sum(result.industry is not None for result in results)
        concept_count = sum(result.concept is not None for result in results)
        return CorrelationRunResult(
            target_date=target_date,
            target_count=len(targets),
            candidate_count=sum(len(bundle.candidates.get(code, ())) for code in targets),
            industry_champion_count=industry_count,
            concept_champion_count=concept_count,
            empty_result_count=sum(
                result.industry is None and result.concept is None for result in results
            ),
            skipped_count=0,
            benchmark_counts=benchmark_counts,
            fallback_count=sum(result.benchmark_fallback for result in results),
            calculation_seconds=calculation_seconds,
            write_seconds=write_seconds,
            switched=True,
        )

    def _build_and_validate_rows(
        self,
        targets: list[str],
        target_date: date,
        computed_at: datetime,
        results: list[StockCorrelationResult],
        stock_boards: dict[str, str | None],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if len(results) != len(targets) or {item.code for item in results} != set(targets):
            raise CorrelationInputError("计算结果未完整覆盖目标股票范围")
        state_rows: list[dict[str, Any]] = []
        champion_rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            if result.as_of_date != target_date or result.algorithm_version != ALGORITHM_VERSION:
                raise CorrelationInputError(f"{result.code}:结果日期或算法版本不一致")
            if result.benchmark_code not in REQUIRED_BENCHMARKS:
                raise CorrelationInputError(f"{result.code}:实际基准非法")
            mapped_benchmark, mapped_fallback = resolve_benchmark_code(
                stock_boards.get(result.code), result.code
            )
            benchmark_is_consistent = (
                result.benchmark_code == mapped_benchmark
                and result.benchmark_fallback == mapped_fallback
            ) or (
                mapped_benchmark != FALLBACK_BENCHMARK
                and result.benchmark_code == FALLBACK_BENCHMARK
                and result.benchmark_fallback
            )
            if not benchmark_is_consistent:
                raise CorrelationInputError(f"{result.code}:实际基准与回退标记不一致")
            state_rows.append(
                {
                    "code": result.code,
                    "as_of_date": target_date,
                    "computed_at": computed_at,
                    "algorithm_version": ALGORITHM_VERSION,
                    "benchmark_code": result.benchmark_code,
                    "benchmark_fallback": result.benchmark_fallback,
                    "has_industry_champion": result.industry is not None,
                    "has_concept_champion": result.concept is not None,
                }
            )
            for expected_type, winner in (
                ("industry", result.industry),
                ("concept", result.concept),
            ):
                if winner is None:
                    continue
                if winner.board_type != expected_type:
                    raise CorrelationInputError(f"{result.code}:{expected_type}冠军类型错位")
                self._validate_winner(result.code, winner)
                key = (result.code, winner.board_type)
                if key in seen:
                    raise CorrelationInputError(f"{result.code}:{winner.board_type}冠军重复")
                seen.add(key)
                champion_rows.append(
                    {
                        "code": result.code,
                        "board_type": winner.board_type,
                        "board_code": winner.board_code,
                        "score": winner.score,
                        "corr_20": winner.corr_20,
                        "corr_60": winner.corr_60,
                        "sample_20": winner.sample_20,
                        "sample_60": winner.sample_60,
                        "confidence": winner.confidence,
                        "benchmark_code": result.benchmark_code,
                        "benchmark_fallback": result.benchmark_fallback,
                        "as_of_date": target_date,
                        "computed_at": computed_at,
                        "algorithm_version": ALGORITHM_VERSION,
                    }
                )

        board_refs = {(row["board_code"], row["board_type"]) for row in champion_rows}
        if board_refs:
            board_codes = sorted({code for code, _ in board_refs})
            placeholders = ",".join("?" for _ in board_codes)
            rows = self.c.query_df(
                f"SELECT board_code, board_type FROM board_dict "
                f"WHERE board_code IN ({placeholders})",
                board_codes,
            )
            actual = {
                (str(row["board_code"]), str(row["board_type"])) for row in rows.to_dict("records")
            }
            if actual != board_refs:
                missing = sorted(board_refs - actual)
                raise CorrelationInputError(f"冠军板块字典引用失效: {missing}")
        state_columns = [
            "code",
            "as_of_date",
            "computed_at",
            "algorithm_version",
            "benchmark_code",
            "benchmark_fallback",
            "has_industry_champion",
            "has_concept_champion",
        ]
        champion_columns = [
            "code",
            "board_type",
            "board_code",
            "score",
            "corr_20",
            "corr_60",
            "sample_20",
            "sample_60",
            "confidence",
            "benchmark_code",
            "benchmark_fallback",
            "as_of_date",
            "computed_at",
            "algorithm_version",
        ]
        return (
            pd.DataFrame(state_rows, columns=state_columns),
            pd.DataFrame(champion_rows, columns=champion_columns),
        )

    @staticmethod
    def _validate_winner(code: str, winner: CorrelationWinner) -> None:
        if winner.board_type not in ("industry", "concept"):
            raise CorrelationInputError(f"{code}:冠军类型非法")
        values = (winner.score, winner.corr_20, winner.corr_60)
        if not all(math.isfinite(value) and -1 <= value <= 1 for value in values):
            raise CorrelationInputError(f"{code}:冠军相关值非法")
        if winner.sample_20 < MIN_SHORT_SAMPLES or winner.sample_60 < MIN_LONG_SAMPLES:
            raise CorrelationInputError(f"{code}:冠军样本不足")
        expected_score = 0.6 * winner.corr_20 + 0.4 * winner.corr_60
        if not math.isclose(winner.score, expected_score, abs_tol=1e-12):
            raise CorrelationInputError(f"{code}:冠军综合分不一致")
        expected_confidence = classify_confidence(
            winner.sample_60, winner.score, winner.corr_20, winner.corr_60
        )
        if winner.confidence != expected_confidence:
            raise CorrelationInputError(f"{code}:冠军可信度不一致")

    def _run_replace_statement(self, sql: str, params: list[Any] | None = None) -> None:
        """事务内语句执行点，保留给故障注入验证；不得在外部单独调用。"""
        self.c.conn.execute(sql, params or [])

    def _replace_rows(
        self,
        states: pd.DataFrame,
        champions: pd.DataFrame,
        targets: list[str],
        *,
        full_scope: bool,
    ) -> None:
        """按目标交易日 upsert 两张快照表；先清除该日该批旧行，避免"合法空"残留旧冠军。

        targets/full_scope 仅作为写入目标范围的说明；先按 (code, as_of_date) 删除该日旧行
        再 upsert，既保证"该日无冠军的股票"被清掉旧冠军，也不影响其它交易日快照。
        """
        state_columns = ",".join(states.columns)
        champion_columns = ",".join(champions.columns)
        state_updates = ",".join(
            f"{col}=EXCLUDED.{col}" for col in states.columns if col not in ("code", "as_of_date")
        )
        champion_updates = ",".join(
            f"{col}=EXCLUDED.{col}"
            for col in champions.columns
            if col not in ("code", "board_type", "as_of_date")
        )
        # 本批统一目标日（states 行均含同一 as_of_date）。
        as_of_date = states["as_of_date"].iloc[0]
        placeholders = ",".join("?" for _ in targets)
        with (
            self.c.temp_view(states, "correlation_states") as state_view,
            self.c.temp_view(champions, "correlation_champions") as champion_view,
            self.c.transaction(),
        ):
            # 全量重算必须使目标日快照与点时股票池完全一致；范围重算只清本批代码。
            if full_scope:
                self._run_replace_statement(
                    "DELETE FROM stock_board_correlation WHERE as_of_date=?", [as_of_date]
                )
                self._run_replace_statement(
                    "DELETE FROM stock_board_correlation_state WHERE as_of_date=?", [as_of_date]
                )
            else:
                self._run_replace_statement(
                    f"DELETE FROM stock_board_correlation "
                    f"WHERE code IN ({placeholders}) AND as_of_date=?",
                    [*targets, as_of_date],
                )
                self._run_replace_statement(
                    f"DELETE FROM stock_board_correlation_state "
                    f"WHERE code IN ({placeholders}) AND as_of_date=?",
                    [*targets, as_of_date],
                )
            self._run_replace_statement(
                f"INSERT INTO stock_board_correlation_state ({state_columns}) "
                f"SELECT {state_columns} FROM {state_view} "
                f"ON CONFLICT (code, as_of_date) DO UPDATE SET {state_updates}"
            )
            self._run_replace_statement(
                f"INSERT INTO stock_board_correlation ({champion_columns}) "
                f"SELECT {champion_columns} FROM {champion_view} "
                f"ON CONFLICT (code, board_type, as_of_date) DO UPDATE SET {champion_updates}"
            )

    def get_membership(self, code: object) -> StockBoardMembership:
        normalized = normalize_stock_code(code)
        return self.get_memberships([normalized])[normalized]

    def get_memberships(
        self,
        codes: Iterable[object],
        as_of_date: date | None = None,
    ) -> dict[str, StockBoardMembership]:
        """一次查询返回多股累计归属；指定日期时排除明确在该日之后首次观测的关系。"""
        normalized = normalize_stock_codes(codes)
        if not normalized:
            return {}

        result: dict[str, StockBoardMembership] = {
            code: {
                "code": code,
                "membership_scope": "cumulative",
                "membership_updated_at": None,
                "industries": [],
                "concepts": [],
            }
            for code in normalized
        }
        placeholders = ",".join("?" for _ in normalized)
        date_clause = (
            " AND (bm.first_seen_date IS NULL OR bm.first_seen_date<=?) "
            if as_of_date is not None
            else " "
        )
        params: list[object] = [*normalized]
        if as_of_date is not None:
            params.append(pd.Timestamp(as_of_date).date())
        sql = (
            "SELECT bm.code, bd.board_code, bd.name, bd.board_type, "
            "       bd.member_snapshot_at "
            "FROM board_member bm "
            "INNER JOIN stock_basic sb ON sb.code = bm.code "
            "INNER JOIN board_dict bd ON bd.board_code = bm.board_code "
            f"WHERE bm.code IN ({placeholders}) "
            "  AND bd.board_type IN ('industry', 'concept') "
            + date_clause
            + "ORDER BY bm.code, CASE bd.board_type WHEN 'industry' THEN 0 ELSE 1 END, "
            "         bd.name, bd.board_code"
        )
        rows = self.c.query_df(sql, params)

        seen: set[tuple[str, str, str]] = set()
        latest_membership_at: dict[str, pd.Timestamp] = {}
        for row in rows.to_dict("records"):
            code = str(row["code"])
            if code not in result:
                continue
            snapshot_at = row.get("member_snapshot_at")
            if snapshot_at is not None and not pd.isna(snapshot_at):
                snapshot_ts = pd.Timestamp(snapshot_at)
                if snapshot_ts > latest_membership_at.get(code, pd.Timestamp.min):
                    latest_membership_at[code] = snapshot_ts
                    result[code]["membership_updated_at"] = snapshot_ts.isoformat()
            board_type = str(row["board_type"])
            board_code = str(row["board_code"])
            key = (code, board_type, board_code)
            if key in seen:
                continue
            seen.add(key)
            if board_type == "industry":
                result[code]["industries"].append(
                    {
                        "board_code": board_code,
                        "name": str(row["name"]),
                        "board_type": "industry",
                    }
                )
            else:
                result[code]["concepts"].append(
                    {
                        "board_code": board_code,
                        "name": str(row["name"]),
                        "board_type": "concept",
                    }
                )
        return result

    def get_related_boards(
        self,
        codes: Iterable[object],
        business_dates: date | str | Mapping[str, date | str | None] | None = None,
    ) -> dict[str, StockRelatedBoards | None]:
        """一次查询返回多股各业务日期的冠军快照摘要。

        业务日期匹配该日快照则返回该日冠军；该日无快照时只创建异步首次计算任务，
        不在查询请求内同步计算或写正式结果。逐代码业务日期缺失（Mapping 中为 None）
        时按 fail-closed 处理。
        """
        normalized = normalize_stock_codes(codes)
        if not normalized:
            return {}

        if isinstance(business_dates, Mapping):
            normalized_dates = {
                normalize_stock_code(code): (None if value is None else pd.Timestamp(value).date())
                for code, value in business_dates.items()
            }
        else:
            uniform_date = None if business_dates is None else pd.Timestamp(business_dates).date()
            normalized_dates = {code: uniform_date for code in normalized}
        protect_dates = isinstance(business_dates, Mapping) or business_dates is not None

        rows = self._query_related_boards_for_dates(normalized, normalized_dates, protect_dates)
        first_load_codes: set[str] = set()
        if protect_dates:
            missing = self._collect_missing_snapshot_codes(normalized, normalized_dates, rows)
            if missing:
                first_load_codes = self._enqueue_first_load_tasks(missing, normalized_dates)
        return self._assemble_related_boards(
            normalized,
            rows,
            protect_dates,
            first_load_codes=first_load_codes,
        )

    @staticmethod
    def _collect_missing_snapshot_codes(
        normalized: list[str],
        normalized_dates: Mapping[str, date | None],
        rows: pd.DataFrame,
    ) -> list[str]:
        """找出请求了具体业务日、但尚无该日状态快照的股票。"""
        have = {str(row["code"]) for row in rows.to_dict("records")}
        return [
            code
            for code in normalized
            if normalized_dates.get(code) is not None and code not in have
        ]

    def _enqueue_first_load_tasks(
        self,
        missing_codes: list[str],
        normalized_dates: Mapping[str, date | None],
    ) -> set[str]:
        """按日期和股票范围幂等创建首次计算任务，不恢复任何上游变化联动。"""
        from backend.services.async_task import AsyncTaskService, ConcurrentTaskError

        by_date: dict[date, list[str]] = {}
        for code in missing_codes:
            requested = normalized_dates.get(code)
            if requested is not None:
                by_date.setdefault(requested, []).append(code)

        pending: set[str] = set()
        try:
            tasks = AsyncTaskService(self.c)
        except Exception as exc:  # noqa: BLE001 -- 读取不能被任务基础设施故障拖垮
            log.warning("走势相关首次计算服务初始化失败: %s", exc)
            return pending
        for target_date, codes in by_date.items():
            scope = sorted(set(codes))
            scope_hash = sha256(",".join(scope).encode("utf-8")).hexdigest()[:20]
            event_id = (
                f"stock-board-correlation:first-load:{ALGORITHM_VERSION}:"
                f"{target_date.isoformat()}:{scope_hash}"
            )
            try:
                task_id = tasks.create(
                    "stock_board_correlation",
                    {
                        "codes": scope,
                        "force": True,
                        "trade_date": target_date.isoformat(),
                    },
                    trigger_source="system",
                    job_name="走势相关自动首次计算",
                    trigger_event_id=event_id,
                )
                task = tasks.get(task_id)
                if task and task.get("status") in {"pending", "running"}:
                    pending.update(scope)
            except ConcurrentTaskError as exc:
                # 只有上游数据已经具备计算条件时，写槽繁忙才属于真实等待态。
                # 数据族为空或所选日期尚未共同就绪时直接降级，避免页面把“不具备
                # 计算条件”误报为持续计算中。
                try:
                    available_date = self.resolve_target_date(upper_bound=target_date)
                except CorrelationInputError as input_exc:
                    log.info(
                        "走势相关首次计算不等待写槽 date=%s scope=%d reason=%s",
                        target_date,
                        len(scope),
                        input_exc,
                    )
                    continue
                if available_date != target_date:
                    log.info(
                        "走势相关首次计算不等待写槽 date=%s scope=%d available=%s",
                        target_date,
                        len(scope),
                        available_date,
                    )
                    continue
                pending.update(scope)
                log.info(
                    "走势相关首次计算等待写槽 date=%s scope=%d running=%s",
                    target_date,
                    len(scope),
                    exc.running_id,
                )
            except Exception as exc:  # noqa: BLE001 -- 任务基础设施异常时读取仍须可用
                log.warning(
                    "走势相关首次计算任务创建失败 date=%s scope=%d: %s",
                    target_date,
                    len(scope),
                    exc,
                )
        return pending

    def _query_related_boards_for_dates(
        self,
        normalized: list[str],
        normalized_dates: Mapping[str, date | None],
        protect_dates: bool,
    ) -> pd.DataFrame:
        """按每个 code 请求的业务日期取该日快照；未启用日期保护时取每 code 最新快照。"""
        base_select = (
            "SELECT s.code, s.as_of_date, s.benchmark_code, s.benchmark_fallback, "
            "       c.board_type, c.board_code, c.score, c.corr_20, c.corr_60, "
            "       c.sample_20, c.sample_60, c.confidence, bd.name AS board_name "
            "FROM stock_board_correlation_state s "
        )
        champion_join = (
            "LEFT JOIN stock_board_correlation c ON c.code=s.code AND c.as_of_date=s.as_of_date "
            "LEFT JOIN board_dict bd ON bd.board_code=c.board_code AND bd.board_type=c.board_type "
        )
        if protect_dates:
            wanted = pd.DataFrame(
                {
                    "code": normalized,
                    "as_of_date": [normalized_dates.get(code) for code in normalized],
                }
            )
            with self.c.temp_view(wanted, "wanted_snapshot_dates") as view:
                return self.c.query_df(
                    base_select
                    + f"JOIN {view} wanted ON wanted.code=s.code AND wanted.as_of_date=s.as_of_date "
                    + champion_join
                    + "ORDER BY s.code, CASE c.board_type WHEN 'industry' THEN 0 ELSE 1 END"
                )
        placeholders = ",".join("?" for _ in normalized)
        return self.c.query_df(
            base_select
            + "JOIN (SELECT code, max(as_of_date) AS mx FROM stock_board_correlation_state "
            f"WHERE code IN ({placeholders}) GROUP BY code) latest "
            "ON latest.code=s.code AND latest.mx=s.as_of_date "
            + champion_join
            + "ORDER BY s.code, CASE c.board_type WHEN 'industry' THEN 0 ELSE 1 END",
            normalized,
        )

    def _assemble_related_boards(
        self,
        normalized: list[str],
        rows: pd.DataFrame,
        protect_dates: bool,
        *,
        first_load_codes: set[str] | None = None,
    ) -> dict[str, StockRelatedBoards | None]:
        """把按日快照行组装成摘要；protect_dates 时无快照的 code 标 as_of_mismatch。"""
        pending_codes = first_load_codes or set()
        result: dict[str, StockRelatedBoards | None] = {code: None for code in normalized}
        for row in rows.to_dict("records"):
            code = str(row["code"])
            summary = result.get(code)
            if summary is None:
                benchmark_code = str(row["benchmark_code"])
                summary = {
                    "as_of_date": str(pd.Timestamp(row["as_of_date"]).date()),
                    "benchmark": {
                        "code": benchmark_code,
                        "name": MarketBenchmarkService.name(benchmark_code),
                        "fallback": bool(row["benchmark_fallback"]),
                    },
                    "industry": None,
                    "concept": None,
                }
                result[code] = summary
            board_type = row.get("board_type")
            board_name = row.get("board_name")
            if (
                board_type not in ("industry", "concept")
                or board_name is None
                or pd.isna(board_name)
            ):
                continue
            summary[board_type] = {
                "board_code": str(row["board_code"]),
                "name": str(board_name),
                "score": float(row["score"]),
                "corr_20": float(row["corr_20"]),
                "corr_60": float(row["corr_60"]),
                "sample_20": int(row["sample_20"]),
                "sample_60": int(row["sample_60"]),
                "confidence": str(row["confidence"]),
            }
        if protect_dates:
            for code in normalized:
                if result.get(code) is None:
                    first_load_pending = code in pending_codes
                    result[code] = {
                        "as_of_date": None,
                        "benchmark": {"code": None, "name": None, "fallback": False},
                        "industry": None,
                        "concept": None,
                        "unavailable_reason": (
                            "first_load_pending" if first_load_pending else "as_of_mismatch"
                        ),
                    }
        return result

    def attach_related_boards(
        self,
        rows: list[dict[str, Any]],
        business_dates: date | str | Mapping[str, date | str | None] | None,
    ) -> list[dict[str, Any]]:
        """给已形成的响应行批量附加摘要；非标准遗留代码安全退化为 null。"""
        normalized_by_raw: dict[str, str] = {}
        for row in rows:
            raw_code = str(row.get("code") or "")
            try:
                normalized_by_raw[raw_code] = normalize_stock_code(raw_code)
            except ValueError:
                row["related_boards"] = None
        filtered_dates = business_dates
        if isinstance(business_dates, Mapping):
            filtered_dates = {
                normalized: business_dates.get(raw_code, business_dates.get(normalized))
                for raw_code, normalized in normalized_by_raw.items()
            }
        summaries = self.get_related_boards(normalized_by_raw.values(), filtered_dates)
        for row in rows:
            raw_code = str(row.get("code") or "")
            normalized = normalized_by_raw.get(raw_code)
            row["related_boards"] = summaries.get(normalized) if normalized else None
        return rows

    def load_correlation_inputs(
        self,
        codes: Iterable[object],
        as_of_date: date,
    ) -> LoadedCorrelationInputs:
        """固定次数批量加载当前版本算法输入，不计算、不写正式结果。"""
        normalized = normalize_stock_codes(codes)
        if not normalized:
            return LoadedCorrelationInputs(None, (), {}, {}, {}, {}, {})

        target_date = pd.Timestamp(as_of_date).date()
        calendar_frame = self.c.query_df(
            "SELECT trade_date FROM ("
            "  SELECT trade_date FROM trade_calendar "
            "  WHERE is_open=true AND trade_date <= ? "
            f"  ORDER BY trade_date DESC LIMIT {CALENDAR_POINTS}"
            ") t ORDER BY trade_date",
            [target_date],
        )
        calendar_dates = tuple(
            pd.Timestamp(value).date() for value in calendar_frame["trade_date"].tolist()
        )
        if len(calendar_dates) != CALENDAR_POINTS:
            raise CorrelationInputError(
                f"相关性算法需要 {CALENDAR_POINTS} 个连续开市收盘点，实际 {len(calendar_dates)} 个"
            )
        actual_as_of = calendar_dates[-1]
        lower_date = calendar_dates[0]
        placeholders = ",".join("?" for _ in normalized)

        stock_frame = self.c.query_df(
            f"SELECT code, board FROM stock_basic WHERE code IN ({placeholders})",
            normalized,
        )
        stock_boards = {
            str(row["code"]): None if pd.isna(row["board"]) else str(row["board"])
            for row in stock_frame.to_dict("records")
        }
        memberships = self.get_memberships(normalized, target_date)
        candidates = {
            code: tuple(
                CandidateRef(item["board_code"], item["board_type"])
                for item in [*membership["industries"], *membership["concepts"]]
            )
            for code, membership in memberships.items()
            if code in stock_boards
        }

        stock_price_frame = self.c.query_df(
            "SELECT code, trade_date, "
            "       close * COALESCE(adj_factor_clean, adj_factor) AS adjusted_close "
            f"FROM daily_bar WHERE code IN ({placeholders}) "
            "  AND trade_date >= ? AND trade_date <= ? ORDER BY code, trade_date",
            [*normalized, lower_date, actual_as_of],
        )

        board_codes = sorted(
            {
                candidate.board_code
                for stock_candidates in candidates.values()
                for candidate in stock_candidates
            }
        )
        if board_codes:
            board_placeholders = ",".join("?" for _ in board_codes)
            board_price_frame = self.c.query_df(
                "SELECT board_code, trade_date, close FROM board_bar "
                f"WHERE board_code IN ({board_placeholders}) "
                "  AND trade_date >= ? AND trade_date <= ? ORDER BY board_code, trade_date",
                [*board_codes, lower_date, actual_as_of],
            )
        else:
            board_price_frame = pd.DataFrame(columns=["board_code", "trade_date", "close"])

        benchmark_codes = sorted(REQUIRED_BENCHMARKS)
        benchmark_placeholders = ",".join("?" for _ in benchmark_codes)
        benchmark_price_frame = self.c.query_df(
            "SELECT index_code, trade_date, close FROM index_bar "
            f"WHERE index_code IN ({benchmark_placeholders}) "
            "  AND trade_date >= ? AND trade_date <= ? ORDER BY index_code, trade_date",
            [*benchmark_codes, lower_date, actual_as_of],
        )
        return LoadedCorrelationInputs(
            as_of_date=actual_as_of,
            calendar_dates=calendar_dates,
            stock_boards=stock_boards,
            stock_closes=_price_series_by_code(
                stock_price_frame,
                code_column="code",
                price_column="adjusted_close",
            ),
            candidates=candidates,
            board_closes=_price_series_by_code(
                board_price_frame,
                code_column="board_code",
                price_column="close",
            ),
            benchmark_closes=_price_series_by_code(
                benchmark_price_frame,
                code_column="index_code",
                price_column="close",
            ),
        )
