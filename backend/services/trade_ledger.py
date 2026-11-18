"""交易账本的纯计算：成交只记一次，规则评价与持仓记账相互独立。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any
from zoneinfo import ZoneInfo

from backend.common.exceptions import ValidationError

SHANGHAI = ZoneInfo("Asia/Shanghai")
CALCULATION_VERSION = "ledger-v4"
FINANCIAL_REPORT_MONTHS = (4, 8, 10)
FINANCIAL_REPORT_PRECEDING_MONTHS = (3, 7, 9)
CENT = Decimal("0.01")


def decimal_value(value: Any, label: str, *, scale: int = 2, positive: bool = False) -> Decimal:
    """金额及股数在进入账本前统一校验，拒绝布尔、非有限数及超精度输入。"""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"{label}格式不正确") from exc
    if (
        isinstance(value, bool) or not result.is_finite()
        or result < 0 or (positive and result == 0)
        or result.as_tuple().exponent < -scale or result >= Decimal(10) ** (20 - scale)
    ):
        raise ValidationError(f"{label}必须为{'正' if positive else '非负'}数，最多{scale}位小数")
    return result


def money(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 50
        return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def trade_amount(price: Decimal, quantity: Decimal) -> Decimal:
    """乘法和按分舍入共用高精度上下文，越界按输入错误处理，不泄漏计算异常。"""
    with localcontext() as context:
        context.prec = 50
        result = (price * quantity).quantize(CENT, rounding=ROUND_HALF_UP)
    return decimal_value(result, "成交金额", positive=True)


def position_cost(raw: dict, quantity: Decimal, total_field: str) -> str | None:
    """新输入按成本单价计算；兼容历史总成本，双传时拒绝互相矛盾的事实。"""
    total = raw.get(total_field)
    price = raw.get("cost_price")
    if price in (None, ""):
        return None if total in (None, "") else money(decimal_value(total, "总成本"))
    price = decimal_value(price, "成本单价", scale=4)
    with localcontext() as context:
        context.prec = 50
        computed = money(decimal_value(money(price * quantity), "总成本"))
    if total not in (None, "") and decimal_value(total, "总成本") != Decimal(computed):
        raise ValidationError("总成本与成本单价乘数量不一致")
    return computed


def assessment(compliant: int, breached: int, *, complete: bool = True) -> str | None:
    """未核实与三类履约结论分开，不用预填值或缺失数据制造合规结论。"""
    if not complete:
        return None
    if not breached:
        return "complied"
    return "partial" if compliant else "breached"


def prepare_opening(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for raw in positions:
        code = str(raw.get("stock_code") or "").strip()
        key = (code, raw.get("rule_id") or None, raw.get("stock_rule_id") or None)
        if not code or key in seen:
            raise ValidationError("期初股票不能为空，同一股票及规则分组不能重复")
        seen.add(key)
        quantity = decimal_value(raw.get("quantity"), "期初数量", scale=4, positive=True)
        result.append({
            "stock_code": code,
            "stock_name": str(raw.get("stock_name") or code),
            "quantity": str(quantity),
            "available_quantity": str(quantity),
            "cost": position_cost(raw, quantity, "cost"),
            "rule_id": raw.get("rule_id") or None,
            "stock_rule_id": raw.get("stock_rule_id") or None,
        })
    return result


def _apply_split(positions: list[dict], event: dict, quantity: Decimal) -> None:
    """拆并股只改变份额，保持成本；未指定分组时按原股数分摊到同股各分组。"""
    selected = [p for p in positions if p["stock_code"] == event["stock_code"]
                and Decimal(p["quantity"]) > 0
                and (not event.get("rule_id") or (
                    p.get("rule_id") == event["rule_id"]
                    and p.get("stock_rule_id") == event.get("stock_rule_id")
                ))]
    total = sum((Decimal(p["quantity"]) for p in selected), Decimal(0))
    after = total + (quantity if event["side"] == "buy" else -quantity)
    if total <= 0 or after <= 0:
        raise ValidationError("拆并股须有原持仓，调整后数量必须大于零")
    if event.get("amount") not in (None, "", "0") and decimal_value(event["amount"], "拆并股成本") != 0:
        raise ValidationError("拆并股不改变总成本，无需填写增加成本")
    with localcontext() as context:
        context.prec = 50
        remainder = after
        for index, position in enumerate(selected):
            before = Decimal(position["quantity"])
            current = remainder if index == len(selected) - 1 else (
                before * after / total
            ).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            if current <= 0:
                raise ValidationError("拆并股后的分组股数低于最小精度，请先核对分组")
            available = Decimal(position["available_quantity"])
            position["available_quantity"] = str(current if available == before else min(current, (
                available * after / total
            ).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)))
            position["quantity"] = str(current)
            remainder -= current


def calculate_day(
    opening: list[dict[str, Any]],
    events: list[dict[str, Any]],
    trade_date: date,
    *,
    opening_cash: str | None = None,
    rules: list[dict[str, Any]] | None = None,
    omissions: list[dict[str, Any]] | None = None,
    next_trade_date: date | None = None,
) -> dict[str, Any]:
    """从日初重新计算整日，修正时替换有效快照而非叠加旧修订的影响。

    不同规则下的同股成本分组保持独立，账户及每套规则的只数分别去重；
    规则上限只核对其主记账归属，附加核对不转移或复制持仓。
    卖出可跨分组扣减，但优先扣减所选分组，随后按固定顺序分摊。
    """
    positions = deepcopy(opening)
    for position in positions:
        position["available_quantity"] = position["quantity"]
    cash = None if opening_cash is None else Decimal(opening_cash)
    ordered = []
    ids: set[str] = set()
    orders: set[int] = set()
    for raw in events:
        event = deepcopy(raw)
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in ids:
            raise ValidationError("成交/调整标识不能为空或重复")
        ids.add(event_id)
        sequence = event.get("display_order")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0 or sequence in orders:
            raise ValidationError("成交/调整顺序必须为不重复的正整数")
        orders.add(sequence)
        try:
            timestamp = event.get("operated_at")
            timestamp = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp
            if not isinstance(timestamp, datetime):
                raise TypeError()
            timestamp = timestamp.replace(tzinfo=SHANGHAI) if timestamp.tzinfo is None else timestamp
            timestamp = timestamp.astimezone(SHANGHAI)
            if timestamp.date() != trade_date:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise ValidationError("每笔成交/调整必须填写当日实际时间") from exc
        event["operated_at"] = timestamp.isoformat()
        ordered.append((timestamp, sequence, event))
    ordered.sort(key=lambda item: (item[0], item[1]))

    def held_codes(rule_id: str | None = None) -> set[str]:
        return {p["stock_code"] for p in positions if Decimal(p["quantity"]) > 0
                and (rule_id is None or p.get("rule_id") == rule_id)}

    def cost_for(rule_id: str | None = None, stock_rule_id: str | None = None) -> Decimal | None:
        selected = [p for p in positions if Decimal(p["quantity"]) > 0
                    and (rule_id is None or p.get("rule_id") == rule_id)
                    and (stock_rule_id is None or p.get("stock_rule_id") == stock_rule_id)]
        if any(p["cost"] is None for p in selected):
            return None
        return sum((Decimal(p["cost"]) for p in selected), Decimal(0))

    peak = len(held_codes())
    buy_total = sell_total = fees = realized = Decimal(0)
    capital_flow = dividend = Decimal(0)
    realized_complete = True
    output = []
    rules = rules or []
    rule_map = {rule["rule_id"]: rule for rule in rules}
    # 清仓期限必须由已入库的下一真实交易日确定；纯计算也拒绝缺失或越月日历。
    clear_by_close = False
    if (trade_date.month in FINANCIAL_REPORT_PRECEDING_MONTHS
            and any(r.get("restrict_financial_report_months", False) for r in rules)):
        if (next_trade_date is None or next_trade_date <= trade_date
                or next_trade_date.year != trade_date.year
                or next_trade_date.month not in (trade_date.month, trade_date.month + 1)):
            raise ValidationError("财报月份清仓核对缺少有效的下一交易日，请补齐交易日历")
        clear_by_close = next_trade_date.month in FINANCIAL_REPORT_MONTHS
    rule_peaks = {rid: len(held_codes(rid)) for rid in rule_map}
    daily_issues: dict[str, list[str]] = {r["rule_id"]: [] for r in rules}
    daily_warnings: dict[str, list[str]] = {r["rule_id"]: [] for r in rules}

    def limits(
        rule: dict[str, Any], *, previous_count: int | None = None,
        stock_rule_ids: set[str | None] | None = None,
    ) -> tuple[list[str], list[str]]:
        issues, warnings = [], []
        limit = rule.get("max_positions")
        count = len(held_codes(rule["rule_id"]))
        # 期初超限单独记录；其后仅新增股票导致只数上升时归到该笔，原股票加仓不重复计数。
        if limit is not None and count > limit and (previous_count is None or count > previous_count):
            issues.append(f"本规则持仓{count}只，超过上限{limit}只")
        restricted = rule.get("restrict_financial_report_months", False)
        if restricted and trade_date.month in FINANCIAL_REPORT_MONTHS:
            # 禁持按数量裁决，不要求成本/行情；期初留仓和新增持仓分别归集。
            if count:
                issues.append(f"{trade_date.month}月为财报禁持月份，本规则仍有持仓，须保持空仓")
            return issues, warnings
        half_capital = restricted and trade_date.month in FINANCIAL_REPORT_PRECEDING_MONTHS
        stock_rules = {s["detail_id"]: s for s in rule.get("stock_rules", [])
                       if s.get("enabled", True)}
        if half_capital:
            unmatched = {p.get("stock_rule_id") for p in positions
                         if p.get("rule_id") == rule["rule_id"] and Decimal(p["quantity"]) > 0
                         and (stock_rule_ids is None or p.get("stock_rule_id") in stock_rule_ids)
                         and p.get("stock_rule_id") not in stock_rules}
            if unmatched:
                warnings.append("财报月份前月持仓分组无法匹配有效资金上限，半仓限制待核对")
        for stock_rule in stock_rules.values():
            sid = stock_rule["detail_id"]
            if stock_rule_ids is not None and sid not in stock_rule_ids:
                continue
            maximum = stock_rule.get("max_capital")
            if maximum is None or (half_capital and Decimal(str(maximum)) <= 0):
                if half_capital and any(p.get("rule_id") == rule["rule_id"]
                                       and p.get("stock_rule_id") == sid
                                       and Decimal(p["quantity"]) > 0 for p in positions):
                    warnings.append(f"{stock_rule['name']}缺少有效资金上限，半仓限制待核对")
                continue
            value = cost_for(rule["rule_id"], sid)
            if value is None:
                warnings.append(f"{stock_rule['name']}持仓成本未完整录入，资金占用待核对")
            elif half_capital and value * 2 > Decimal(str(maximum)):
                # 比较时不把一半预算四舍五入到分，避免奇数分预算被多放行半分。
                issues.append(f"{stock_rule['name']}持仓成本{money(value)}元，"
                              f"超过财报月份前月持仓成本限额（资金上限{maximum}元的50%）")
            elif not half_capital and value > Decimal(str(maximum)):
                issues.append(f"{stock_rule['name']}持仓成本{money(value)}元，超过资金上限")
        return issues, warnings

    for rule in rules:
        daily_issues[rule["rule_id"]], daily_warnings[rule["rule_id"]] = limits(rule)

    for _, _, event in ordered:
        kind = event.get("kind", "trade")
        issues = list(event.get("issues") or [])
        warnings = list(event.get("warnings") or [])
        rule_id = event.get("rule_id")
        if kind == "cash":
            amount = decimal_value(event.get("amount"), "资金变动金额", positive=True)
            category = event.get("adjustment_type")
            if event.get("direction") is None and category in {"deposit", "withdrawal", "dividend"}:
                event["direction"] = "out" if category == "withdrawal" else "in"
            if event.get("direction") not in {"in", "out"} or not str(event.get("note") or "").strip():
                raise ValidationError("资金调整必须填写转入/转出和原因")
            category = event.get("adjustment_type")
            if category not in {"deposit", "withdrawal", "dividend", "other"}:
                raise ValidationError("资金变动必须明确入金、出金、分红或其他调整")
            if (category in {"deposit", "dividend"} and event["direction"] != "in"
                    or category == "withdrawal" and event["direction"] != "out"):
                raise ValidationError("资金变动类别与方向不一致")
            if category == "dividend":
                dividend += amount
            elif category in {"deposit", "withdrawal"}:
                capital_flow += amount if category == "deposit" else -amount
            event["amount"] = money(amount)
            if cash is not None:
                cash += amount if event["direction"] == "in" else -amount
        elif kind in {"trade", "position"}:
            previous_count = len(held_codes(rule_id)) if rule_id in rule_map else None
            code = str(event.get("stock_code") or "").strip()
            if not code:
                raise ValidationError("股票不能为空")
            quantity = decimal_value(event.get("quantity"), "数量", scale=4, positive=True)
            side = event.get("side")
            if side not in {"buy", "sell"}:
                raise ValidationError("买卖/调整方向不正确")
            fee = Decimal(0)
            if kind == "trade":
                price = decimal_value(event.get("price"), "成交价格", scale=4, positive=True)
                computed = trade_amount(price, quantity)
                mode = event.get("amount_mode", "auto")
                if mode not in {"auto", "manual"}:
                    raise ValidationError("成交金额来源不正确")
                amount = computed if mode == "auto" else decimal_value(
                    event.get("amount"), "实际成交金额", positive=True,
                )
                if amount <= 0:
                    raise ValidationError("成交金额必须大于零")
                fee = decimal_value(event.get("fee"), "交易费用")
                event.update(price=str(price), amount=money(amount), computed_amount=money(computed),
                             amount_mode=mode, fee=money(fee))
                fees += fee
                if cash is not None:
                    cash += -(amount + fee) if side == "buy" else amount - fee
                if side == "buy":
                    buy_total += amount
                else:
                    sell_total += amount
            else:
                if not str(event.get("note") or "").strip():
                    raise ValidationError("持仓调整必须填写原因")
                category = event.get("adjustment_type")
                if category not in {"transfer", "bonus", "split", "correction"}:
                    raise ValidationError("持仓调整必须明确转入转出、送股、拆并股或核对修正")
                if category == "bonus" and side != "buy":
                    raise ValidationError("送股只能增加数量，减少数量请使用核对修正")
                if category in {"bonus", "split"} and (
                    event.get("cost_price") is not None
                    or event.get("amount") is not None and decimal_value(event["amount"], "调整成本") != 0
                ):
                    raise ValidationError("送股和拆并股不增加总成本")
                raw_cost = ("0" if category in {"bonus", "split"} else
                            position_cost(event, quantity, "amount") if side == "buy" else None)
                amount = None if raw_cost is None else decimal_value(
                    raw_cost, "调整成本",
                )
                event["amount"] = None if amount is None else money(amount)
            event["quantity"] = str(quantity)
            if kind == "position" and event.get("adjustment_type") == "split":
                _apply_split(positions, event, quantity)
            elif side == "buy":
                matching = next((p for p in positions if p["stock_code"] == code
                                 and p.get("rule_id") == rule_id
                                 and p.get("stock_rule_id") == event.get("stock_rule_id")), None)
                if matching is None:
                    matching = {"stock_code": code, "stock_name": event.get("stock_name_snapshot", code),
                                "quantity": "0", "available_quantity": "0", "cost": "0.00",
                                "rule_id": rule_id, "stock_rule_id": event.get("stock_rule_id")}
                    positions.append(matching)
                matching["quantity"] = str(Decimal(matching["quantity"]) + quantity)
                matching["cost"] = None if matching["cost"] is None or amount is None else money(
                    Decimal(matching["cost"]) + amount + fee,
                )
                if kind == "position":
                    matching["available_quantity"] = str(
                        Decimal(matching["available_quantity"]) + quantity,
                    )
            else:
                candidates = sorted(
                    [p for p in positions if p["stock_code"] == code],
                    key=lambda p: (p.get("rule_id") != rule_id,
                                   p.get("stock_rule_id") != event.get("stock_rule_id"),
                                   str(p.get("rule_id")), str(p.get("stock_rule_id"))),
                )
                quantity_field = "available_quantity" if kind == "trade" else "quantity"
                available = sum((Decimal(p[quantity_field]) for p in candidates), Decimal(0))
                if quantity > available:
                    raise ValidationError(f"{code}可卖/可调减数量不足：可用{available}，本笔{quantity}")
                remaining = quantity
                sold_cost = Decimal(0)
                cost_complete = True
                for position in candidates:
                    take = min(remaining, Decimal(position[quantity_field]))
                    if take == 0:
                        continue
                    before = Decimal(position["quantity"])
                    if position["cost"] is None:
                        cost_complete = False
                    else:
                        total_cost = Decimal(position["cost"])
                        removed = total_cost if take == before else (
                            total_cost * take / before
                        ).quantize(CENT, rounding=ROUND_HALF_UP)
                        position["cost"] = money(total_cost - removed)
                        sold_cost += removed
                    position["quantity"] = str(before - take)
                    position["available_quantity"] = str(max(Decimal(0), Decimal(position["available_quantity"]) - take))
                    remaining -= take
                    if remaining == 0:
                        break
                if kind == "trade":
                    realized_complete &= cost_complete
                    if cost_complete:
                        realized += amount - fee - sold_cost
            peak = max(peak, len(held_codes()))
            rule = rule_map.get(rule_id)
            if rule is not None:
                rule_peaks[rule_id] = max(rule_peaks[rule_id], len(held_codes(rule_id)))
            # 只有主记账分组增加持仓/成本；其他规则及附加核对不承接本笔的持仓限制。
            if (rule is not None and side == "buy"
                    and not (kind == "position" and event.get("adjustment_type") == "split")):
                found, pending = limits(rule, previous_count=previous_count,
                                        stock_rule_ids={event.get("stock_rule_id")})
                if kind == "trade":
                    issues.extend(found)
                    warnings.extend(pending)
                else:
                    daily_issues[rule_id].extend(found)
                    daily_warnings[rule_id].extend(pending)
        else:
            raise ValidationError("账本事件类型不正确")
        event["primary_issues"] = list(dict.fromkeys(issues))
        event["primary_warnings"] = list(dict.fromkeys(warnings))
        for check in event.get("rule_checks", []):
            issues.extend(f"{check.get('rule_name', check['rule_id'])}：{issue}" for issue in check["issues"])
            warnings.extend(f"{check.get('rule_name', check['rule_id'])}：{warning}" for warning in check["warnings"])
        event["issues"] = list(dict.fromkeys(issues))
        event["warnings"] = list(dict.fromkeys(warnings))
        event["compliance_status"] = assessment(0, len(issues), complete=not warnings) if kind == "trade" else None
        output.append(event)

    positions = [p for p in positions if Decimal(p["quantity"]) > 0]
    if clear_by_close:
        for rule in rules:
            if rule.get("restrict_financial_report_months", False) and held_codes(rule["rule_id"]):
                daily_issues[rule["rule_id"]].append(
                    "今日为财报月份前最后一个交易日，本规则当日结束后仍有持仓，未按要求清仓"
                )
    evaluations = []
    omissions = omissions or []
    for rule in rules:
        rid = rule["rule_id"]
        applicable = []
        for event in output:
            if event.get("kind", "trade") != "trade":
                continue
            if event.get("rule_id") == rid:
                applicable.append({"issues": event["primary_issues"], "warnings": event["primary_warnings"]})
            applicable.extend(check for check in event.get("rule_checks", []) if check["rule_id"] == rid)
        missed = [o for o in omissions if o.get("rule_id") == rid]
        issues = list(dict.fromkeys(daily_issues[rid]))
        warnings = list(dict.fromkeys(daily_warnings[rid]))
        complete = not warnings and all(not e["warnings"] for e in applicable)
        positive = sum(not e["issues"] and not e["warnings"] for e in applicable)
        negative = sum(bool(e["issues"]) for e in applicable) + len(missed) + len(issues)
        evaluations.append({"rule_id": rid, "version_no": rule["version_no"], "rule_name": rule["name"],
                            "assessment": assessment(positive, negative, complete=complete),
                            "complete": complete, "issues": issues, "warnings": warnings,
                            "peak_positions": rule_peaks[rid],
                            "compliant_count": positive, "breached_count": negative})
    trades = [e for e in output if e.get("kind", "trade") == "trade"]
    complete = all(not e["warnings"] for e in trades) and all(e["complete"] for e in evaluations)
    positive = sum(e["compliance_status"] == "complied" for e in trades)
    negative = sum(bool(e["issues"]) for e in trades) + len(omissions) + sum(
        len(e["issues"]) for e in evaluations
    )
    return {"calculation_version": CALCULATION_VERSION, "currency": "CNY", "events": output, "positions": positions,
            "opening_positions": deepcopy(opening), "peak_positions": peak,
            "cash": None if cash is None else money(cash), "opening_cash": opening_cash,
            "buy_amount": money(buy_total), "sell_amount": money(sell_total), "fee": money(fees),
            "net_outflow": money(buy_total - sell_total + fees),
            "capital_flow": money(capital_flow), "dividend": money(dividend),
            "realized_pnl": money(realized) if realized_complete else None,
            "assessment": assessment(positive, negative, complete=complete), "complete": complete,
            "evaluations": evaluations, "omissions": omissions}
