"""交易日历前瞻采集目标与运行就绪度。

交易所未来休市安排属于外部事实，数据源尚未发布时不得用工作日推算。这里统一负责
“主动请求到下一自然年末”和“检查真实数据是否足够支撑下一交易日生命周期”，供采集、
启动告警和数据体检复用。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

SHANGHAI = ZoneInfo("Asia/Shanghai")


def calendar_request_end(requested_end: date, *, as_of: date | None = None) -> date:
    """返回采集请求上界，至少尝试覆盖当前日期的下一自然年末。"""
    today = as_of or datetime.now(SHANGHAI).date()
    return max(requested_end, date(today.year + 1, 12, 31))


def inspect_trade_calendar(client: Any, *, as_of: date | None = None) -> dict[str, Any]:
    """读取日历前瞻状态；只认数据源已入库的开市日，不推算未知日期。"""
    today = as_of or datetime.now(SHANGHAI).date()
    frame = client.query_df(
        "SELECT min(trade_date) FILTER (WHERE is_open AND trade_date > ?) AS next_open_date,"
        "max(trade_date) FILTER (WHERE is_open) AS max_open_date FROM trade_calendar",
        [today],
    )

    def as_date(value: Any) -> date | None:
        return None if value is None or pd.isna(value) else pd.Timestamp(value).date()

    next_open_date = as_date(frame.iloc[0]["next_open_date"])
    max_open_date = as_date(frame.iloc[0]["max_open_date"])
    return {
        "as_of": today,
        "next_open_date": next_open_date,
        "max_open_date": max_open_date,
        "lifecycle_ready": next_open_date is not None,
        "cross_year_ready": bool(max_open_date and max_open_date.year > today.year),
    }


def calendar_readiness_detail(readiness: dict[str, Any]) -> str:
    """生成不含敏感信息、可用于日志和体检报告的稳定说明。"""
    next_open = readiness["next_open_date"] or "无"
    max_open = readiness["max_open_date"] or "无"
    return f"检查日 {readiness['as_of']}，下一开市日 {next_open}，最远开市日 {max_open}"
