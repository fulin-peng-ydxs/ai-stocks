"""交易纪律条件校验与提示；只提供事实差异，不替代用户履约自评。"""

from typing import Any

from backend.common.exceptions import ValidationError


def position_count(value: Any, *, label: str, minimum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= 2147483647:
        raise ValidationError(f"{label}必须为不小于 {minimum} 的整数")
    return value


def condition_warnings(rule: dict, operation: dict) -> list[str]:
    """仅对买入检查结构化条件；未知不视为符合，也不自动裁决违规。"""
    if operation.get("side") != "buy":
        return []
    warnings = []
    price = operation.get("price")
    low, high = rule.get("price_min"), rule.get("price_max")
    if low is not None or high is not None:
        if price is None:
            warnings.append("成交价未记录，无法核对股价条件")
        elif (low is not None and price < low) or (high is not None and price > high):
            warnings.append("成交价不符合股价条件")
    facts = operation.get("selection_facts") or {}
    for key, fact_key, label in (
        ("st_filter", "is_st", "ST状态"),
        ("loss_filter", "loss_status", "亏损状态"),
        ("st_risk_filter", "st_risk_status", "ST风险"),
    ):
        mode = rule.get(key, "any")
        if mode == "any":
            continue
        fact = facts.get(fact_key)
        if fact is None or fact == "unknown":
            warnings.append(f"{label}未知，无法核对")
        else:
            is_yes = fact is True or fact == "yes"
            if is_yes != (mode == "only"):
                warnings.append(f"{label}不符合选股条件")
    return warnings
