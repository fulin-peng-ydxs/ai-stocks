"""个股详情头部所需的最新行情、市值与股本只读摘要。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from backend.services.stock_codes import normalize_stock_code
from backend.storage import get_read_client
from backend.storage.duckdb_client import DuckDBClient


class StockQuoteSummaryService:
    """一次查询组装个股最新收盘摘要，避免页面重复拉取行情和估值。"""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_read_client()

    @staticmethod
    def _number(value: object, digits: int | None = None) -> float | None:
        if value is None or pd.isna(value):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return round(number, digits) if digits is not None else number

    @staticmethod
    def _integer(value: object) -> int | None:
        if value is None or pd.isna(value):
            return None
        return int(value)

    def get(self, code: object) -> dict[str, Any]:
        normalized = normalize_stock_code(code)
        rows = self.c.query_df(
            """
            WITH latest_bar AS (
                SELECT trade_date, open, high, low, close, pre_close, volume, amount,
                       turnover_rate
                FROM daily_bar
                WHERE code = ?
                ORDER BY trade_date DESC
                LIMIT 1
            ), prior_volumes AS (
                SELECT b.volume
                FROM daily_bar b, latest_bar latest
                WHERE b.code = ? AND b.trade_date < latest.trade_date
                  AND b.volume IS NOT NULL AND b.volume > 0
                ORDER BY b.trade_date DESC
                LIMIT 5
            ), prior_volume_stats AS (
                SELECT count(*) AS sample_count, avg(volume) AS average_volume
                FROM prior_volumes
            )
            SELECT sb.code, sb.name, sb.board, sb.industry, sb.total_share, sb.float_share,
                   latest.trade_date, latest.open, latest.high, latest.low, latest.close,
                   latest.pre_close, latest.volume, latest.amount, latest.turnover_rate,
                   st.is_st,
                   metrics.total_mv, metrics.float_mv,
                   stats.sample_count, stats.average_volume
            FROM stock_basic sb
            LEFT JOIN latest_bar latest ON TRUE
            LEFT JOIN daily_metrics metrics
              ON metrics.code = sb.code AND metrics.trade_date = latest.trade_date
            LEFT JOIN stock_st_status_daily st
              ON st.code = sb.code AND st.trade_date = latest.trade_date
            LEFT JOIN prior_volume_stats stats ON TRUE
            WHERE sb.code = ?
            """,
            [normalized, normalized, normalized],
        )
        if rows.empty:
            return {
                "code": normalized,
                "name": None,
                "board": None,
                "industry": None,
                "is_st": None,
                "trade_date": None,
                "open": None,
                "high": None,
                "low": None,
                "close": None,
                "pre_close": None,
                "volume": None,
                "amount": None,
                "turnover_rate": None,
                "volume_ratio": None,
                "total_mv": None,
                "float_mv": None,
                "total_share": None,
                "float_share": None,
                "pe_ttm": None,
            }

        row = rows.iloc[0]
        volume = self._number(row["volume"])
        average_volume = self._number(row["average_volume"])
        sample_count = self._integer(row["sample_count"]) or 0
        volume_ratio = (
            round(volume / average_volume, 2)
            if sample_count == 5 and volume is not None and average_volume and average_volume > 0
            else None
        )
        trade_date = row["trade_date"]
        return {
            "code": normalized,
            "name": None if pd.isna(row["name"]) else str(row["name"]),
            "board": None if pd.isna(row["board"]) else str(row["board"]),
            "industry": None if pd.isna(row["industry"]) else str(row["industry"]),
            "is_st": None if pd.isna(row["is_st"]) else bool(row["is_st"]),
            "trade_date": None if pd.isna(trade_date) else str(pd.Timestamp(trade_date).date()),
            "open": self._number(row["open"], 3),
            "high": self._number(row["high"], 3),
            "low": self._number(row["low"], 3),
            "close": self._number(row["close"], 3),
            "pre_close": self._number(row["pre_close"], 3),
            "volume": self._integer(row["volume"]),
            "amount": self._number(row["amount"], 0),
            "turnover_rate": self._number(row["turnover_rate"], 2),
            "volume_ratio": volume_ratio,
            "total_mv": self._number(row["total_mv"], 0),
            "float_mv": self._number(row["float_mv"], 0),
            "total_share": self._integer(row["total_share"]),
            "float_share": self._integer(row["float_share"]),
            # 当前数据源未建立稳定市盈率口径，保留契约位置但不伪造值。
            "pe_ttm": None,
        }
