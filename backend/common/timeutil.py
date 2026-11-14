"""时点工具：防未来函数的辅助（统一日期处理）。

注意：本系统强调"点时安全"——所有历史数据访问只能用 <= 基准日 T 的数据。
这里集中日期解析/格式化及兼容业务存储的北京时间，避免各处手写出错。
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from time import strptime
from zoneinfo import ZoneInfo

DATE_FMT = "%Y-%m-%d"
DATE_FMT_COMPACT = "%Y%m%d"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now_naive() -> datetime:
    """北京时间墙上时间，兼容既有 TIMESTAMP/JSON；绝对时点仍显式使用 UTC。"""
    return datetime.now(SHANGHAI).replace(tzinfo=None)


def to_date(value: str | date | datetime) -> date:
    """把多种输入统一成 date。支持 'YYYY-MM-DD' / 'YYYYMMDD'。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return date(*strptime(s, DATE_FMT_COMPACT)[:3])
    return date(*strptime(s, DATE_FMT)[:3])


def fmt_date(d: date, compact: bool = False) -> str:
    """date -> 字符串。compact=True 输出 YYYYMMDD（部分数据源接口需要）。"""
    return d.strftime(DATE_FMT_COMPACT if compact else DATE_FMT)


def years_before(end: date, years: int) -> date:
    """自然年回溯，闰日落到目标年的二月末，不使用 365 天近似。"""
    year = end.year - years
    return end.replace(year=year, day=min(end.day, monthrange(year, end.month)[1]))
