"""市场基准指数查询；板块与个股页面共享数据口径，权限仍由各自路由控制。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.config import get_effective_settings
from backend.storage.duckdb_client import DuckDBClient
from backend.storage.duckdb_client import get_read_client as get_client

BENCHMARK_NAMES = {
    "000905.SH": "中证 500",
    "000300.SH": "沪深 300",
    "000001.SH": "上证指数",
    "000688.SH": "科创 50",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
}


def configured_benchmark_codes() -> list[str]:
    """返回系统启用的市场基准代码，保持配置顺序并去重。"""
    cfg = get_effective_settings().backtest
    return list(dict.fromkeys([cfg.benchmark_main, *cfg.benchmark_others]))


class MarketBenchmarkService:
    """按系统允许列表读取市场指数，避免板块和个股路由复制查询与白名单。"""

    def __init__(self, client: DuckDBClient | None = None):
        self.c = client or get_client()

    @staticmethod
    def validate_code(index_code: str) -> None:
        allowed = set(configured_benchmark_codes())
        if index_code not in allowed:
            raise ValueError(f"不支持的指数基准: {index_code}")

    def get_range(self, index_code: str, start: date, end: date) -> list[dict]:
        self.validate_code(index_code)
        df = self.c.query_df(
            "SELECT trade_date, open, high, low, close, volume, amount FROM index_bar "
            "WHERE index_code = ? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            [index_code, start, end],
        )
        return self._rows(df)

    def get_lookback(self, index_code: str, end: date, lookback: int) -> list[dict]:
        self.validate_code(index_code)
        df = self.c.query_df(
            "SELECT trade_date, open, high, low, close, volume, amount FROM ("
            "SELECT trade_date, open, high, low, close, volume, amount "
            "FROM index_bar WHERE index_code = ? AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT ?) t ORDER BY trade_date",
            [index_code, end, lookback],
        )
        return self._rows(df)

    @staticmethod
    def _rows(df: pd.DataFrame) -> list[dict]:
        def number(value, *, integer: bool = False):
            if value is None or pd.isna(value):
                return None
            return int(value) if integer else float(value)

        return [
            {
                "trade_date": str(pd.Timestamp(row["trade_date"]).date()),
                "open": number(row["open"]),
                "high": number(row["high"]),
                "low": number(row["low"]),
                "close": number(row["close"]),
                "volume": number(row["volume"], integer=True),
                "amount": number(row["amount"]),
            }
            for _, row in df.iterrows()
        ]

    @staticmethod
    def name(index_code: str) -> str:
        return BENCHMARK_NAMES.get(index_code, index_code)
