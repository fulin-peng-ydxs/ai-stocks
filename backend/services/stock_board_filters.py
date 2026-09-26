"""个股行情页面的板块筛选值解析。"""

from __future__ import annotations

STOCK_BOARD_VALUES = frozenset({"主板", "创业板", "科创板", "ST", "退市"})


def parse_stock_board_values(value: str | None) -> list[str]:
    """解析个股行情原有板块值，不复用榜单或连板天梯的板块键。"""
    if not value:
        return []
    values = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    invalid = [item for item in values if item not in STOCK_BOARD_VALUES]
    if invalid:
        raise ValueError(f"不支持的个股板块：{','.join(invalid)}")
    return values
