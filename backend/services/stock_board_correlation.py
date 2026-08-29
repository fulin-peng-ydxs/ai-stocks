"""个股走势关联板块领域服务：累计归属与后续相关性能力的统一入口。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypedDict

import pandas as pd

from backend.indicators.stock_board_correlation import (
    CALENDAR_POINTS,
    REQUIRED_BENCHMARKS,
    CandidateRef,
    CorrelationInputError,
    PriceSeries,
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
            result[code]["membership_updated_at"] = _timestamp_text(
                row["membership_updated_at"]
            )
            if board_type == "industry":
                result[code]["industries"].append({
                    "board_code": board_code,
                    "name": str(row["name"]),
                    "board_type": "industry",
                })
            else:
                result[code]["concepts"].append({
                    "board_code": board_code,
                    "name": str(row["name"]),
                    "board_type": "concept",
                })
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

        board_codes = sorted({
            candidate.board_code
            for stock_candidates in candidates.values()
            for candidate in stock_candidates
        })
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
