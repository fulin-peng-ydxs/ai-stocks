"""项目支持范围内的 A 股代码规范化工具。"""

from __future__ import annotations

import re
from collections.abc import Iterable

STOCK_CODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ)$")


def normalize_stock_code(value: object) -> str:
    """去空、统一大写并校验带交易所后缀的沪深 A 股代码。"""
    code = str(value).strip().upper()
    if not STOCK_CODE_RE.fullmatch(code):
        raise ValueError(f"股票代码格式非法: {value}")
    return code


def normalize_stock_codes(values: Iterable[object]) -> list[str]:
    """按输入顺序规范化并去重；空迭代返回空列表。"""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = normalize_stock_code(value)
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    return normalized
