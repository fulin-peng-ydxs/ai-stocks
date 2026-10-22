"""交易纪律结构化条件：区分已知违规与事实未知，供提示和履约校验共用。"""

from typing import Any
from uuid import uuid4

from backend.common.exceptions import ValidationError

CHECKLIST_CATEGORIES = ("basic", "risk", "technical")


def prepare_checklist_items(value: Any) -> list[dict]:
    """草稿允许空正文，标识与分类始终有效；发布时再校验完整性。"""
    if not isinstance(value, list):
        raise ValidationError("检查项必须为列表")
    items, ids, orders = [], set(), set()
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, dict):
            raise ValidationError("检查项格式不正确")
        item_id = raw.get("item_id")
        if item_id is None:
            item_id = f"tdci_{uuid4().hex}"
        if not isinstance(item_id, str) or not item_id.strip() or item_id in ids:
            raise ValidationError("检查项标识不能为空或重复")
        source_category = raw.get("category", "technical")
        category = source_category
        if category == "other":
            category = "technical"  # 兼容旧客户端和草稿，不改写正式历史快照。
        if category not in CHECKLIST_CATEGORIES:
            raise ValidationError("检查项分类不正确")
        text = raw.get("text", "")
        if not isinstance(text, str):
            raise ValidationError("检查项内容必须为文本")
        order = raw.get("display_order", index)
        if type(order) is not int or order < 1 or (source_category, order) in orders:
            raise ValidationError("同分类检查项顺序必须为不重复的正整数")
        ids.add(item_id)
        orders.add((source_category, order))
        items.append(
            {"item_id": item_id, "category": category, "text": text.strip(), "display_order": order}
        )
    items.sort(
        key=lambda item: (CHECKLIST_CATEGORIES.index(item["category"]), item["display_order"])
    )
    for index, item in enumerate(items, 1):
        item["display_order"] = index
    return items


def prepare_checklist_results(rule: dict, operation: dict) -> list[dict] | None:
    """仅接收所选版本的完整人工核对，不把遗漏隐式解释为未知或符合。"""
    value = operation.get("checklist_results")
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValidationError("检查项核对结果必须为列表")
    items = rule.get("checklist_items") or []
    expected = {item["item_id"] for item in items} if operation.get("side") == "buy" else set()
    results = {}
    for result in value:
        if not isinstance(result, dict):
            raise ValidationError("检查项核对结果格式不正确")
        item_id, status = result.get("item_id"), result.get("status")
        if not isinstance(item_id, str) or item_id not in expected or item_id in results:
            raise ValidationError("检查项重复或不属于本笔买入所选规则版本")
        if status not in {"yes", "no", "unknown"}:
            raise ValidationError("检查项请选择符合、不符合或未知")
        results[item_id] = status
    if results.keys() != expected:
        raise ValidationError("请逐项核对选股条件，未查明可选未知")
    return (
        [{"item_id": item["item_id"], "status": results[item["item_id"]]} for item in items]
        if expected
        else None
    )


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
    results = {item["item_id"]: item["status"] for item in operation.get("checklist_results") or []}
    for item in rule.get("checklist_items") or []:
        status = results.get(item["item_id"])
        if status == "no":
            warnings.append(f"选股条件“{item['text']}”不符合")
        elif include_unknown and status != "yes":
            warnings.append(
                f"选股条件“{item['text']}”{'未知' if status == 'unknown' else '未记录'}，无法核对"
            )
    return warnings
