"""上市板块筛选的统一键值与中文事实映射。"""

from __future__ import annotations

LISTED_BOARD_LABELS = {
    "main": "主板",
    "star": "科创板",
    "gem": "创业板",
}

def parse_listed_board_keys(value: str | None) -> list[str]:
    """解析逗号分隔的上市板块键；空值表示不限板块。"""
    if not value:
        return []
    keys = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    invalid = [key for key in keys if key not in LISTED_BOARD_LABELS]
    if invalid:
        raise ValueError(f"不支持的上市板块：{','.join(invalid)}")
    return keys


def listed_board_labels(keys: list[str] | None) -> list[str]:
    return [LISTED_BOARD_LABELS[key] for key in (keys or []) if key in LISTED_BOARD_LABELS]
