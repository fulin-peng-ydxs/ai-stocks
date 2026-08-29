"""个股走势关联板块领域服务：累计归属与后续相关性能力的统一入口。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypedDict

import pandas as pd

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


def _timestamp_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


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
