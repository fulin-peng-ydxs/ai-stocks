"""EOD 采集的统一北京时间、日历解析和写入日期边界。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from backend.common.exceptions import DataSourceError

SHANGHAI = ZoneInfo("Asia/Shanghai")
EOD_READY_TIME = time(15, 30)


def shanghai_now() -> datetime:
    """各入口共享的北京时间时钟，也用于确定性边界测试。"""
    return datetime.now(SHANGHAI)


def time_cutoff() -> date:
    """日历解析前的时间上界；历史请求无需为每只股票重复查询交易日历。"""
    now = shanghai_now()
    return now.date() - timedelta(days=1) if now.time() < EOD_READY_TIME else now.date()


def cap_end(requested: date, *, strict: bool = False) -> date:
    """普通请求收敛到收盘上界；强制当日及冻结目标不能绕过时间保护。"""
    cutoff = time_cutoff()
    if strict and requested > cutoff:
        raise DataSourceError(
            f"目标{requested}尚未达到EOD采集时点（北京时间15:30），当前上界{cutoff}"
        )
    return min(requested, cutoff)


def is_open_day(client, day: date) -> bool:
    """兼容全日期与仅开市日日历；缺行只有处于已覆盖区间内才能判为休市。"""
    row = client.query_df(
        "SELECT min(trade_date) AS lo, max(trade_date) AS hi, "
        "max(is_open) FILTER (WHERE trade_date=?) AS opened FROM trade_calendar",
        [day],
    ).iloc[0]
    if pd.notna(row["opened"]):
        return bool(row["opened"])
    if (
        pd.notna(row["lo"])
        and pd.notna(row["hi"])
        and pd.Timestamp(row["lo"]).date() <= day <= pd.Timestamp(row["hi"]).date()
    ):
        return False
    raise DataSourceError(f"交易日历未覆盖{day}，无法确认EOD采集日期")


def latest_open_day(client, through: date) -> date:
    """从已入库日历选择开市日，缺少事实时明确失败。"""
    value = client.query_df(
        "SELECT max(trade_date) AS d FROM trade_calendar WHERE is_open AND trade_date<=?",
        [through],
    ).iloc[0]["d"]
    if pd.isna(value):
        raise DataSourceError(f"交易日历缺少{through}及之前的开市日，无法确认EOD采集日期")
    return pd.Timestamp(value).date()


def resolve_end(client, requested: date | None = None, *, force: bool = False) -> date:
    """先守住收盘时间，再按真实日历选目标日；强制只允许已收盘的开市日。"""
    requested = requested or shanghai_now().date()
    opened = is_open_day(client, min(requested, shanghai_now().date()))
    end = cap_end(requested, strict=force)
    if force and not opened:
        raise DataSourceError(f"目标{requested}不是开市日，不能强制写入当日EOD")
    return latest_open_day(client, end)


def bound_bars(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """源端响应不能越过请求区间或当前收盘上界；只在存在越界行时复制数据。"""
    if frame is None or frame.empty:
        return frame
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    mask = (dates >= start) & (dates <= cap_end(end))
    return frame if mask.all() else frame.loc[mask].copy()


def cap_range(start: date, end: date) -> date:
    end = cap_end(end)
    if start > end:
        raise DataSourceError(f"请求区间{start}起尚无可写入的已收盘EOD数据，当前上界{end}")
    return end
