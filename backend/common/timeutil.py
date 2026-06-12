"""时点工具：防未来函数的辅助（统一日期处理）。

注意：本系统强调"点时安全"——所有历史数据访问只能用 <= 基准日 T 的数据。
这里集中日期解析/格式化，避免各处手写出错。
"""

from __future__ import annotations

from datetime import date, datetime

DATE_FMT = "%Y-%m-%d"
DATE_FMT_COMPACT = "%Y%m%d"


def to_date(value: str | date | datetime) -> date:
    """把多种输入统一成 date。支持 'YYYY-MM-DD' / 'YYYYMMDD'。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, DATE_FMT_COMPACT).date()
    return datetime.strptime(s, DATE_FMT).date()


def fmt_date(d: date, compact: bool = False) -> str:
    """date -> 字符串。compact=True 输出 YYYYMMDD（部分数据源接口需要）。"""
    return d.strftime(DATE_FMT_COMPACT if compact else DATE_FMT)
