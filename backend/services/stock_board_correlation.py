"""个股走势关联板块领域服务：累计归属与后续相关性能力的统一入口。"""

from __future__ import annotations

import math
from collections.abc import Iterable
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
    resolve_benchmark_code,
)
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


class StockBoardCorrelationService:
    """读取公共市场板块归属；不把累计关系误称为当前有效关系。"""

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

    def compute_and_replace(
        self,
        codes: Iterable[object] | None = None,
        *,
        force: bool = False,
        upper_bound: date | None = None,
        computed_at: datetime | None = None,
    ) -> CorrelationRunResult:
        """完整计算目标范围，并在校验成功后原子替换两张当前态表。"""
        if not isinstance(force, bool):
            raise CorrelationInputError("force 必须为布尔值")
        target_date = self.resolve_target_date(upper_bound)
        targets, full_scope = self.resolve_target_codes(target_date, codes)
        if not force and self._target_is_current(targets, target_date, full_scope=full_scope):
            return CorrelationRunResult(
                target_date, len(targets), 0, 0, 0, 0, len(targets), {}, 0, False
            )

        bundle = self.load_correlation_inputs(targets, target_date)
        if bundle.as_of_date != target_date:
            raise CorrelationInputError("批量输入实际日期与目标日不一致")
        if set(bundle.stock_boards) != set(targets):
            missing = sorted(set(targets) - set(bundle.stock_boards))
            raise CorrelationInputError(f"批量输入缺少目标股票: {','.join(missing)}")

        results = [
            calculate_stock_correlations(
                code=code,
                board=bundle.stock_boards[code],
                calendar_dates=bundle.calendar_dates,
                stock_closes=bundle.stock_closes.get(code, {}),
                candidates=bundle.candidates.get(code, ()),
                board_closes=bundle.board_closes,
                benchmark_closes=bundle.benchmark_closes,
            )
            for code in targets
        ]
        # DuckDB computed_at 为无时区 TIMESTAMP，沿用仓库既有本地时间口径。
        timestamp = computed_at or datetime.now()  # noqa: DTZ005
        states, champions = self._build_and_validate_rows(
            targets,
            target_date,
            timestamp,
            results,
            bundle.stock_boards,
        )
        self._replace_rows(states, champions, targets, full_scope=full_scope)

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

    def load_correlation_inputs(
        self,
        codes: Iterable[object],
        as_of_date: date,
    ) -> LoadedCorrelationInputs:
        """固定次数批量加载 v1 算法输入，不计算、不写正式结果。"""
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
