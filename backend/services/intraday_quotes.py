"""分时查询只读取 DuckDB 事实及其 Redis 缓存，不触发采集。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from backend.storage import get_read_client, get_redis_client


class IntradayServiceUnavailable(RuntimeError):
    """分时服务暂时不可用。"""


class IntradayQuoteService:
    def __init__(self, market=None, redis_client=None) -> None:
        self.market = market or get_read_client()
        self.redis = redis_client if redis_client is not None else get_redis_client().client

    def get(self, code: str, trade_date: date) -> dict:
        from backend.services.intraday_archive import IntradayArchiveService

        archive = IntradayArchiveService(self.market)
        saved = archive.read(code, trade_date, self.redis)
        metadata = self._local_metadata(code, trade_date)
        metadata.update(archive.bounds(code), archived=bool(saved))
        if saved:
            metadata.update(
                status=saved["status"],
                source=saved["source"],
                fetched_at=saved["fetched_at"],
                points=self._points(saved["rows"]),
            )
        else:
            metadata["status"] = "no_data"
        return metadata

    def _local_metadata(self, code: str, trade_date: date) -> dict:
        name_df = self.market.query_df("SELECT name FROM stock_basic WHERE code = ?", [code])
        name = None if name_df.empty else str(name_df.iloc[0]["name"])
        metadata = {
            "code": code,
            "name": name,
            "trade_date": str(trade_date),
            "frequency": "1m",
            "status": "ready",
            "source": None,
            "fetched_at": None,
            "supported_start": None,  # 兼容旧接口；源窗口说明统一由数据管理提供。
            "supported_end": None,
            "pre_close": None,
            "turnover_rate": None,
            "points": [],
        }
        if name is None:
            metadata["status"] = "no_data"
            return metadata
        bar_df = self.market.query_df(
            "SELECT pre_close, turnover_rate FROM daily_bar "
            "WHERE code = ? AND trade_date = ? LIMIT 1",
            [code, trade_date],
        )
        if bar_df.empty:
            metadata["status"] = "no_data"
            return metadata
        value = bar_df.iloc[0]["pre_close"]
        metadata["pre_close"] = None if value is None or pd.isna(value) else float(value)
        turnover = bar_df.iloc[0]["turnover_rate"]
        metadata["turnover_rate"] = (
            None if turnover is None or pd.isna(turnover) else float(turnover)
        )
        return metadata

    @staticmethod
    def _points(rows: list[list]) -> list[dict]:
        amount_sum = 0.0
        volume_sum = 0.0
        points: list[dict] = []
        for timestamp, open_, high, low, close, volume, amount in rows:
            volume_lots = float(volume)
            amount_value = float(amount)
            volume_sum += max(volume_lots, 0.0)
            amount_sum += max(amount_value, 0.0)
            average = amount_sum / (volume_sum * 100) if volume_sum > 0 else None
            points.append(
                {
                    "time": timestamp[11:16],
                    "open": None if open_ is None or pd.isna(open_) else round(float(open_), 4),
                    "high": round(float(high), 4),
                    "low": round(float(low), 4),
                    "close": round(float(close), 4),
                    "volume": round(volume_lots, 2),
                    "amount": round(amount_value, 2),
                    "average_price": None if average is None else round(average, 4),
                }
            )
        return points
