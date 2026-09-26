"""个股行情页面的上市板块与股票状态筛选值解析。"""

from __future__ import annotations

STOCK_LISTED_BOARD_VALUES = ("主板", "创业板", "科创板")
STOCK_STATUS_VALUES = ("正常上市", "ST", "退市")


def parse_stock_board_values(value: str | None) -> list[str]:
    """解析个股行情的上市板块值，不与状态维度混用。"""
    if not value:
        return []
    values = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    invalid = [item for item in values if item not in STOCK_LISTED_BOARD_VALUES]
    if invalid:
        raise ValueError(f"不支持的个股板块：{','.join(invalid)}")
    return values


def parse_stock_status_values(value: str | None) -> list[str]:
    """解析正常上市/ST/退市状态；同维度内取并集。"""
    if not value:
        return []
    values = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    invalid = [item for item in values if item not in STOCK_STATUS_VALUES]
    if invalid:
        raise ValueError(f"不支持的股票状态：{','.join(invalid)}")
    return values
