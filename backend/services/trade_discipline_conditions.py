"""交易纪律结构化条件：区分已知违规与事实未知，供提示和履约校验共用。"""

from typing import Any

from backend.common.exceptions import ValidationError


def position_count(value: Any, *, label: str, minimum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= 2147483647:
        raise ValidationError(f"{label}必须为不小于 {minimum} 的整数")
    return value


def condition_warnings(rule: dict, operation: dict) -> list[str]:
    return _condition_issues(rule, operation, include_unknown=True)


def condition_violations(rule: dict, operation: dict) -> list[str]:
    """仅返回买入操作已确认的违规；未知事实不升级为违规。"""
    return _condition_issues(rule, operation, include_unknown=False)


def _condition_issues(rule: dict, operation: dict, *, include_unknown: bool) -> list[str]:
    if operation.get("side") != "buy":
        return []
    warnings = []
    price = operation.get("price")
    low, high = rule.get("price_min"), rule.get("price_max")
    if low is not None or high is not None:
        if price is None and include_unknown:
            warnings.append("成交价未记录，无法核对股价条件")
        elif price is not None and (
            (low is not None and price < low) or (high is not None and price > high)
        ):
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
            if include_unknown:
                warnings.append(f"{label}未知，无法核对")
        else:
            is_yes = fact is True or fact == "yes"
            if is_yes != (mode == "only"):
                warnings.append(f"{label}不符合选股条件")
    return warnings
