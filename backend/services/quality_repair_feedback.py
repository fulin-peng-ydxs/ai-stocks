"""质量修复的业务反馈：保留可读原因，技术原文仍由任务日志承接。"""

from __future__ import annotations

import re
from collections.abc import Callable

from backend.common.exceptions import DataQualityError, DataSourceError, StorageError

_TECHNICAL = re.compile(
    r"https?://|/(?:Users|home|var|private|tmp|opt)/|\bTraceback\b|"
    r"\b\w*(?:Error|Exception)\b|\bSQL\s*:|"
    r"\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s|[\[{]",
    re.IGNORECASE | re.ASCII,
)


def readable_repair_reason(value: object, fallback: str) -> str:
    """仅接受完整中文业务说明，不截取可能携带查询、路径或凭据的技术原文。"""
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    return (text if text and re.search(r"[\u3400-\u9fff]", text)
            and not _TECHNICAL.search(text) else fallback)


def repair_failure_reason(error: Exception) -> str:
    """按异常及其原因链给出可操作的说明；不将原始地址、SQL 或对象传给业务区。"""
    chain, seen = [], set()
    current = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    readable = readable_repair_reason(str(error), "")
    if readable:
        return readable
    # 类型可能被来源适配器包装；只识别固定错误特征并输出固定文案，不回显匹配文本。
    signature = " ".join(f"{type(item).__name__} {item}" for item in chain).lower()
    if any(isinstance(item, StorageError) or type(item).__module__.startswith(
        ("duckdb", "psycopg", "sqlite3")) for item in chain):
        return "数据读取或写入失败，修复未完成，请稍后重试"
    if any(isinstance(item, TimeoutError) for item in chain) or re.search(
        r"timeout|timed out|超时", signature
    ):
        return "数据源请求超时，未能完成取数，请稍后重试"
    if re.search(r"\b429\b|too many requests|限流", signature):
        return "数据源请求受到限流，请稍后重试"
    if re.search(r"\b(?:401|403)\b|forbidden|unauthorized", signature):
        return "数据源拒绝访问，请检查来源访问配置后重试"
    if any(isinstance(item, ConnectionError) for item in chain) or re.search(
        r"connection|connecterror|network|网络|连接", signature
    ):
        return "数据源连接失败，未能取得数据，请检查网络后重试"
    if any(isinstance(item, DataSourceError) for item in chain) or re.search(
        r"httperror|httpstatuserror|\bhttp\s+5\d\d\b", signature
    ):
        return "数据源请求失败，未能取得有效数据，请稍后重试"
    if any(isinstance(item, DataQualityError) for item in chain):
        return "取回的数据未通过质量校验，问题仍待处理"
    if any(isinstance(item, ValueError) for item in chain):
        return "修复参数或返回数据不符合要求，请核对问题日期和数据范围后重试"
    return "修复执行异常，未能完成处理，请稍后重试"


def repair_collection_reason(failures: list) -> str:
    """采集返回的失败列表逐项转译；只读已知 error 字段，不回显原始对象。"""
    reasons = []
    for item in failures[:20]:
        value = item.get("error") if isinstance(item, dict) else item
        # 板块采集已有三种固定结果格式；只解释机器约定，避免把 empty、years
        # 或内部字段公式当成无法说明的执行异常。
        years = re.fullmatch(r".*: years \[([0-9, ]+)\]", value) if isinstance(value, str) else None
        if years:
            reason = f"数据源未完成 {years[1]} 年的采集，目标范围仍有缺失"
        elif isinstance(value, str) and value.endswith(": empty"):
            reason = "数据源返回空数据，未能补齐目标日期"
        elif isinstance(value, str) and ": net_inflow=" in value:
            reason = "来源净流入与流入减流出的计算结果不一致，未写入异常记录"
        else:
            reason = repair_failure_reason(RuntimeError(str(value)))
        if reason not in reasons:
            reasons.append(reason)
    return "；".join(reasons) or "数据源未返回完整有效数据，请稍后重试"


def ensure_repair_collection(result: dict, label: str, log: Callable[[str, str], None]) -> None:
    """采集返回失败时保留原始日志，再抛出可读原因，供原恢复入口复位并计数。"""
    failures = result.get("failed")
    if failures:
        log(f"{label}：{failures}", "error")
        raise RuntimeError(f"{label}：{repair_collection_reason(failures)}")
