"""已核实的同一证券更码事实：点时股票池与历史取源共用，保留连续研究序列。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True, slots=True)
class StockCodeChange:
    """旧代码的排他结束日等于新代码的启用日；股份权利连续，区别于吸收合并。"""

    previous_code: str
    current_code: str
    effective_date: date
    evidence_url: str


STOCK_CODE_CHANGES = (
    StockCodeChange(
        "000022.SZ", "001872.SZ", date(2018, 12, 26),
        "https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF",
    ),
    StockCodeChange(
        "000043.SZ", "001914.SZ", date(2019, 12, 16),
        "https://static.cninfo.com.cn/finalpage/2019-12-20/1207179183.PDF",
    ),
    StockCodeChange(
        "300114.SZ", "302132.SZ", date(2025, 2, 17),
        "https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/"
        "cedb693a-f5ee-4463-9682-ea33d406b569.PDF",
    ),
)
IDENTITY_VERSION = hashlib.sha256(json.dumps([
    (x.previous_code, x.current_code, x.effective_date.isoformat(), x.evidence_url)
    for x in STOCK_CODE_CHANGES
], ensure_ascii=False).encode()).hexdigest()[:16]


def canonical_stock_code(code: str) -> str:
    """返回登记链的最终研究代码，用于读取同一证券的连续收益序列。"""
    for _ in range(len(STOCK_CODE_CHANGES) + 1):
        change = next((x for x in STOCK_CODE_CHANGES if x.previous_code == code), None)
        if change is None:
            return code
        code = change.current_code
    raise ValueError("证券代码更码事实存在环")


def trading_code_at(code: str, day: date) -> str:
    """同一证券在指定日期的真实交易代码；不以当前名称或价格相似度推断身份。"""
    day = pd.Timestamp(day).date()
    for _ in range(len(STOCK_CODE_CHANGES) + 1):
        change = next((x for x in STOCK_CODE_CHANGES if (
            x.previous_code == code and day >= x.effective_date
        ) or (x.current_code == code and day < x.effective_date)), None)
        if change is None:
            return code
        code = (change.current_code if day >= change.effective_date else change.previous_code)
    raise ValueError("证券代码更码事实存在环")


def source_code_periods(code: str, start: date, end: date) -> list[tuple]:
    """按已核实启用日分段取准确身份事实，不拼接价格或复权因子。"""
    if end < start:
        return []
    changes = [x for x in STOCK_CODE_CHANGES
               if canonical_stock_code(x.current_code) == canonical_stock_code(code)]
    if not changes:
        return [(code, start, end, None)]
    evidence = "|".join(x.evidence_url for x in changes)
    cuts = sorted({x.effective_date for x in changes if start < x.effective_date <= end})
    cursor, result = start, []
    for cut in cuts:
        result.append((trading_code_at(code, cursor), cursor, cut - timedelta(days=1), evidence))
        cursor = cut
    result.append((trading_code_at(code, cursor), cursor, end, evidence))
    return result


def trading_code_active_sql(code_expression: str, date_expression: str) -> str:
    """内部可信 SQL 表达式使用的点时代码谓词；事实与向量入口使用同一切换日期。"""
    invalid = []
    for change in STOCK_CODE_CHANGES:
        cutoff = f"DATE '{change.effective_date.isoformat()}'"
        invalid.extend([
            f"({code_expression}='{change.previous_code}' AND {date_expression}>={cutoff})",
            f"({code_expression}='{change.current_code}' AND {date_expression}<{cutoff})",
        ])
    return "NOT (" + " OR ".join(invalid) + ")" if invalid else "TRUE"


def trading_code_on_sql(day: date, code_expression: str = "code") -> str:
    """日期值统一规范成 DATE 字面量，调用方无需重复维护多个日期绑定参数。"""
    return trading_code_active_sql(code_expression, f"DATE '{pd.Timestamp(day).date().isoformat()}'")


def filter_trading_codes(frame: pd.DataFrame) -> pd.DataFrame:
    """横截面只保留当时生效的代码；原始连续行情和指标暖机输入不裁剪。"""
    if frame.empty:
        return frame
    dates = pd.to_datetime(frame["trade_date"])
    keep = dates.notna()
    for change in STOCK_CODE_CHANGES:
        cutoff = pd.Timestamp(change.effective_date)
        keep &= ~(frame["code"].eq(change.previous_code) & dates.ge(cutoff))
        keep &= ~(frame["code"].eq(change.current_code) & dates.lt(cutoff))
    return frame.loc[keep]
