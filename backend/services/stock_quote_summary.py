"""个股详情最新行情摘要与 K 线日期对齐的历史市值。"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd

from backend.services.stock_codes import normalize_stock_code
from backend.storage import get_read_client
from backend.storage.duckdb_client import DuckDBClient


class StockQuoteSummaryService:
    """组装最新收盘摘要，并按已加载 K 线日期批量补充历史市值。"""

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

    def _serialize_market_values(
        self, row: dict[str, Any], *, basis: str
    ) -> dict[str, Any]:
        """报价与历史 K 线共用股本、市值及来源证据的序列化口径。"""
        value = {
            field: self._number(row[field], 0) if field.endswith("mv")
            else self._integer(row[field])
            for field in ("total_mv", "float_mv", "total_share", "float_share")
        }
        if basis == "historical":
            day = str(pd.Timestamp(row["trade_date"]).date())
            evidence = {}
            for field in ("total", "float"):
                item = {}
                for suffix in ("source", "effective_date", "available_date", "basis"):
                    raw = row[f"{field}_{suffix}"]
                    item[suffix] = (
                        None if pd.isna(raw)
                        else str(raw)[:10] if suffix.endswith("date") else str(raw)
                    )
                item["retrospective"] = bool(
                    item["available_date"] and item["available_date"] > day
                )
                source = row[f"{field}_mv_source"]
                item["mv_source"] = None if pd.isna(source) else source
                evidence[field] = item
            value["capital_evidence"] = evidence
        return value

    def get_market_values(
        self, code: object, trade_dates: list[date], *, basis: str = "point_in_time"
    ) -> dict[str, dict[str, Any]]:
        """批量读取 K 线对应日期的市值和股本；不复权、不向前填充历史缺口。"""
        normalized = normalize_stock_code(code)
        dates = list(dict.fromkeys(trade_dates))
        if len(dates) > 6000:
            raise ValueError("市值日期数量不能超过 6000")
        if not dates:
            return {}
        from backend.services.share_capital_history import historical_joins
        if basis not in ("historical", "point_in_time"):
            raise ValueError("股本口径仅支持 historical 或 point_in_time")
        joins = historical_joins(bounded=True)
        basis_fields = "'source_record' total_basis,'source_record' float_basis"
        rows = self.c.query_df(
            "SELECT b.trade_date,m.total_mv,m.float_mv,s.total_share,s.float_share,"
            "s.total_source,s.float_source,s.total_effective_date,s.float_effective_date,"
            "s.total_available_date,s.float_available_date,m.total_mv_source,m.float_mv_source," + basis_fields +
            " FROM (SELECT ? code,unnest(?::DATE[]) trade_date) b " + joins,
            [normalized, dates, *([normalized, min(dates), max(dates)] * 2)])
        result = {}
        for row in rows.to_dict("records"):
            day = str(pd.Timestamp(row["trade_date"]).date())
            result[day] = self._serialize_market_values(row, basis=basis)
        return result

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
            SELECT sb.code, sb.name, sb.board, sb.industry, shares.total_share, shares.float_share,
                   latest.trade_date, latest.open, latest.high, latest.low, latest.close,
                   latest.pre_close, latest.volume, latest.amount, latest.turnover_rate,
                   st.is_st,
                   metrics.total_mv, metrics.float_mv,
                   shares.total_source, shares.float_source,
                   shares.total_effective_date, shares.float_effective_date,
                   shares.total_available_date, shares.float_available_date,
                   metrics.total_mv_source, metrics.float_mv_source,
                   'source_record' AS total_basis, 'source_record' AS float_basis,
                   stats.sample_count, stats.average_volume
            FROM stock_basic sb
            LEFT JOIN latest_bar latest ON TRUE
            LEFT JOIN stock_share_capital_daily shares
              ON shares.code = sb.code AND shares.trade_date = latest.trade_date
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
        # 同一条报价 SQL 已拿到当日事实；只复用序列化，避免再扫一遍股本与市值大表。
        values = {} if pd.isna(trade_date) else self._serialize_market_values(
            row.to_dict(), basis="historical"
        )
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
            **values,
        }
