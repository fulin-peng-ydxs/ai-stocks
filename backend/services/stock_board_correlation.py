"""个股走势关联板块领域服务：累计归属与后续相关性能力的统一入口。"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, TypedDict

import pandas as pd

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
    code: str
    name: str
    fallback: bool


class StockRelatedBoards(TypedDict, total=False):
    as_of_date: str
    benchmark: RelatedBoardBenchmark
    industry: RelatedBoardWinner | None
    concept: RelatedBoardWinner | None
    unavailable_reason: Literal["as_of_mismatch"]


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


def _timestamp_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


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
    unknown = sorted(set(raw) - {"codes", "force"})
    if unknown:
        raise ValueError(f"个股走势关联板块任务不支持参数: {','.join(unknown)}")
    force = raw.get("force", False)
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
    return {"codes": codes, "force": force}


class StockBoardCorrelationService:
    """读取累计板块归属与当前冠军摘要，并编排版本化批量计算。"""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    def resolve_target_date(self, upper_bound: date | None = None) -> date:
        """取日历、个股、板块和指数四类数据均不晚于的最近开市日。"""
        maxima = self.c.query_df(
            "SELECT (SELECT max(trade_date) FROM daily_bar) AS daily_date, "
            "       (SELECT max(trade_date) FROM board_bar) AS board_date, "
            "       (SELECT max(trade_date) FROM index_bar) AS index_date"
        ).iloc[0]
        missing = [name for name, value in maxima.items() if value is None or pd.isna(value)]
        if missing:
            raise CorrelationInputError(f"目标日缺少数据事实源: {','.join(missing)}")
        ceiling = min(pd.Timestamp(value).date() for value in maxima.tolist())
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
            self.c.query_df("SELECT count(*) AS n FROM stock_board_correlation_state").iloc[0]["n"]
        )
        outside_winners = int(
            self.c.query_df(
                "SELECT count(*) AS n FROM stock_board_correlation "
                f"WHERE code NOT IN ({placeholders})",
                codes,
            ).iloc[0]["n"]
        )
        return state_count == len(codes) and outside_winners == 0

    def _current_scope_statistics(self, codes: list[str]) -> dict[str, Any]:
        """跳过计算时读取当前范围真实统计，避免把“未重算”误报成零冠军。"""
        placeholders = ",".join("?" for _ in codes)
        candidates = int(self.c.query_df(
            "SELECT count(*) AS n FROM board_member bm "
            "INNER JOIN board_dict bd ON bd.board_code=bm.board_code "
            f"WHERE bm.code IN ({placeholders}) "
            "AND bd.board_type IN ('industry','concept')",
            codes,
        ).iloc[0]["n"])
        champions = self.c.query_df(
            "SELECT board_type,count(*) AS n FROM stock_board_correlation "
            f"WHERE code IN ({placeholders}) GROUP BY board_type",
            codes,
        )
        champion_counts = {
            str(row["board_type"]): int(row["n"])
            for row in champions.to_dict("records")
        }
        state = self.c.query_df(
            "SELECT count(*) FILTER (WHERE NOT has_industry_champion "
            "AND NOT has_concept_champion) AS empty_count, "
            "count(*) FILTER (WHERE benchmark_fallback) AS fallback_count "
            "FROM stock_board_correlation_state "
            f"WHERE code IN ({placeholders})",
            codes,
        ).iloc[0]
        benchmarks = self.c.query_df(
            "SELECT benchmark_code,count(*) AS n FROM stock_board_correlation_state "
            f"WHERE code IN ({placeholders}) GROUP BY benchmark_code",
            codes,
        )
        return {
            "candidate_count": candidates,
            "industry_count": champion_counts.get("industry", 0),
            "concept_count": champion_counts.get("concept", 0),
            "empty_count": int(state["empty_count"] or 0),
            "fallback_count": int(state["fallback_count"] or 0),
            "benchmark_counts": {
                str(row["benchmark_code"]): int(row["n"])
                for row in benchmarks.to_dict("records")
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
        """完整计算目标范围，并在校验成功后原子替换两张当前态表。"""

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
            current = self._current_scope_statistics(targets)
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
        state_columns = ",".join(states.columns)
        champion_columns = ",".join(champions.columns)
        with (
            self.c.temp_view(states, "correlation_states") as state_view,
            self.c.temp_view(champions, "correlation_champions") as champion_view,
            self.c.transaction(),
        ):
            if full_scope:
                self._run_replace_statement("DELETE FROM stock_board_correlation")
                self._run_replace_statement("DELETE FROM stock_board_correlation_state")
            else:
                placeholders = ",".join("?" for _ in targets)
                self._run_replace_statement(
                    f"DELETE FROM stock_board_correlation WHERE code IN ({placeholders})",
                    targets,
                )
                self._run_replace_statement(
                    f"DELETE FROM stock_board_correlation_state WHERE code IN ({placeholders})",
                    targets,
                )
            self._run_replace_statement(
                f"INSERT INTO stock_board_correlation_state ({state_columns}) "
                f"SELECT {state_columns} FROM {state_view}"
            )
            self._run_replace_statement(
                f"INSERT INTO stock_board_correlation ({champion_columns}) "
                f"SELECT {champion_columns} FROM {champion_view}"
            )

    def get_membership(self, code: object) -> StockBoardMembership:
        normalized = normalize_stock_code(code)
        return self.get_memberships([normalized])[normalized]

    def get_memberships(self, codes: Iterable[object]) -> dict[str, StockBoardMembership]:
        """一次查询返回多股累计归属；无输入时不访问数据库。"""
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
        rows = self.c.query_df(
            "SELECT bm.code, bd.board_code, bd.name, bd.board_type, "
            "       max(bd.member_snapshot_at) OVER (PARTITION BY bm.code) "
            "           AS membership_updated_at "
            "FROM board_member bm "
            "INNER JOIN stock_basic sb ON sb.code = bm.code "
            "INNER JOIN board_dict bd ON bd.board_code = bm.board_code "
            f"WHERE bm.code IN ({placeholders}) "
            "  AND bd.board_type IN ('industry', 'concept') "
            "ORDER BY bm.code, CASE bd.board_type WHEN 'industry' THEN 0 ELSE 1 END, "
            "         bd.name, bd.board_code",
            normalized,
        )

        seen: set[tuple[str, str, str]] = set()
        for row in rows.to_dict("records"):
            code = str(row["code"])
            board_type = str(row["board_type"])
            board_code = str(row["board_code"])
            key = (code, board_type, board_code)
            if code not in result or key in seen:
                continue
            seen.add(key)
            result[code]["membership_updated_at"] = _timestamp_text(row["membership_updated_at"])
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
        """一次查询返回多股冠军摘要；逐代码业务日期缺失时按历史不匹配处理。"""
        normalized = normalize_stock_codes(codes)
        if not normalized:
            return {}

        protect_dates = isinstance(business_dates, Mapping) or business_dates is not None
        if isinstance(business_dates, Mapping):
            normalized_dates = {
                normalize_stock_code(code): (None if value is None else pd.Timestamp(value).date())
                for code, value in business_dates.items()
            }
        else:
            uniform_date = None if business_dates is None else pd.Timestamp(business_dates).date()
            normalized_dates = {code: uniform_date for code in normalized}

        placeholders = ",".join("?" for _ in normalized)
        rows = self.c.query_df(
            "SELECT s.code, s.as_of_date, s.benchmark_code, s.benchmark_fallback, "
            "       c.board_type, c.board_code, c.score, c.corr_20, c.corr_60, "
            "       c.sample_20, c.sample_60, c.confidence, bd.name AS board_name "
            "FROM stock_board_correlation_state s "
            "LEFT JOIN stock_board_correlation c ON c.code=s.code "
            "  AND c.as_of_date=s.as_of_date "
            "  AND c.algorithm_version=s.algorithm_version "
            "  AND c.benchmark_code=s.benchmark_code "
            "  AND c.benchmark_fallback=s.benchmark_fallback "
            "LEFT JOIN board_dict bd ON bd.board_code=c.board_code "
            "  AND bd.board_type=c.board_type "
            f"WHERE s.code IN ({placeholders}) "
            "ORDER BY s.code, CASE c.board_type WHEN 'industry' THEN 0 ELSE 1 END",
            normalized,
        )
        result: dict[str, StockRelatedBoards | None] = {code: None for code in normalized}
        for row in rows.to_dict("records"):
            code = str(row["code"])
            as_of_date = pd.Timestamp(row["as_of_date"]).date()
            summary = result.get(code)
            if summary is None:
                benchmark_code = str(row["benchmark_code"])
                summary = {
                    "as_of_date": str(as_of_date),
                    "benchmark": {
                        "code": benchmark_code,
                        "name": MarketBenchmarkService.name(benchmark_code),
                        "fallback": bool(row["benchmark_fallback"]),
                    },
                    "industry": None,
                    "concept": None,
                }
                business_date = normalized_dates.get(code)
                if protect_dates and business_date != as_of_date:
                    summary["unavailable_reason"] = "as_of_mismatch"
                result[code] = summary
            if "unavailable_reason" in summary:
                continue
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
        memberships = self.get_memberships(normalized)
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
