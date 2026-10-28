"""账户日结编排：统一实际成交、规则核对、初始化及最新日修正。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.services.trade_discipline_conditions import condition_violations, condition_warnings
from backend.services.trade_discipline_service import TradeDisciplineService
from backend.services.trade_ledger import (
    FINANCIAL_REPORT_PRECEDING_MONTHS,
    SHANGHAI,
    calculate_day,
    decimal_value,
    money,
    prepare_opening,
    trade_amount,
)
from backend.storage.trade_ledger_repository import TradeLedgerRepository


def json_value(value: Any) -> Any:
    """JSONB 中资金保持十进制字符串，时间显式含时区。"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


class TradeLedgerService:
    def __init__(self, repo: TradeLedgerRepository | None = None, market=None):
        self.repo = repo or TradeLedgerRepository()
        self.discipline = TradeDisciplineService(self.repo, market)

    def _rules(self, trade_date: date, conn=None, previous=None) -> list[dict]:
        if previous is not None:
            # 日结修正仍绑定原先版本，不能随管理页发布/归档发生漂移。
            return [self.repo.load_version(r["rule_id"], r["version_no"], conn=conn)
                    for r in previous["rules"]]
        result = []
        for row in self.discipline.list_rules_with_state(trade_date, conn=conn):
            version = row.get("effective_version")
            if row["effective_status"] == "active" and version:
                result.append(self.repo.load_version(row["id"], version["version_no"], conn=conn))
        return result

    def _names(self, positions: list[dict], trade_date: date) -> None:
        if any(not isinstance(p.get("stock_code"), str) or not p["stock_code"].strip() for p in positions):
            raise ValidationError("请选择具体股票")
        codes = sorted({p["stock_code"] for p in positions})
        if not codes:
            return
        frame = self.discipline.market.query_df(
            "SELECT code,name,list_date FROM stock_basic WHERE code IN ("
            + ",".join("?" for _ in codes) + ")", codes,
        )
        names = {r["code"]: r for r in frame.to_dict("records")}
        for position in positions:
            row = names.get(position["stock_code"])
            if row is None or (pd.notna(row["list_date"]) and pd.Timestamp(row["list_date"]).date() > trade_date):
                raise ValidationError(f"股票不存在或起算日尚未上市：{position['stock_code']}")
            position["stock_name"] = str(row["name"])

    @staticmethod
    def _validate_group(position: dict, rules: dict[str, dict]) -> None:
        """期初与非交易调整沿用相同归属，不能挂到已停用或不完整的规则分组。"""
        rid, sid = position.get("rule_id"), position.get("stock_rule_id")
        if rid or sid:
            version = rules.get(rid)
            if not version or sid not in {
                item["detail_id"] for item in version["stock_rules"] if item["enabled"]
            }:
                raise ValidationError("持仓分组不属于当日有效规则的启用选股项")

    def initialize(self, trade_date: date, positions: list[dict], cash, expected_revision: int) -> dict:
        self.discipline._require_trade_date(trade_date)
        prepared = prepare_opening(positions)
        self._names(prepared, trade_date)
        cash = None if cash in (None, "") else money(decimal_value(cash, "期初现金"))
        with self.repo.transaction() as conn:
            account = self.repo.account(conn, lock=True)
            if account["initialized_on"] is not None:
                raise ConflictError("账户已初始化，后续持仓变化请通过调整记录处理")
            if account["revision"] != expected_revision:
                raise ConflictError("账户已变化，请刷新后重试")
            rules = {r["rule_id"]: r for r in self._rules(trade_date, conn)}
            for position in prepared:
                self._validate_group(position, rules)
            self.repo.initialize(conn, trade_date, prepared, cash)
        return self.context(trade_date)

    def context(self, trade_date: date) -> dict:
        # 账户、日结和期初来自同一数据库快照，避免并发修正时读到半新半旧状态。
        with self.repo.transaction() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            account = self.repo.account(conn)
            day = self.repo.day(trade_date, conn)
            latest = self.repo.latest(conn)
            previous = self.repo.latest(conn, before=trade_date)
            snapshot = day["snapshot"] if day and not day["withdrawn"] else None
            opening = previous["snapshot"] if previous else None
            rules = self._rules(trade_date, conn, snapshot)
            initialized = account["initialized_on"] is not None
            before_initialization = initialized and trade_date < account["initialized_on"]
            can_edit = initialized and not before_initialization and (
                latest is None or trade_date >= latest["trade_date"]
            )
            shown_positions = [] if before_initialization else snapshot["positions"] if snapshot else [
                {**p, "available_quantity": p["quantity"]}
                for p in (opening["positions"] if opening else account.get("opening_positions", []))
            ]
            return json_value({
                "trade_date": trade_date, "account_revision": account["revision"],
                "initialized_on": account["initialized_on"], "can_edit": can_edit,
                "latest_trade_date": latest["trade_date"] if latest else None,
                "current_revision_no": day["current_revision_no"] if day else 0,
                "snapshot": snapshot, "rules": rules,
                "stock_options": self._supplement_stock_options(snapshot, trade_date),
                "opening_positions": [] if before_initialization else opening["positions"] if opening else account.get("opening_positions", []),
                "opening_cash": None if before_initialization else opening["cash"] if opening else account.get("opening_cash"),
                "positions": self._marked_positions(shown_positions, trade_date),
                "cash": None if before_initialization else snapshot["cash"] if snapshot else opening["cash"] if opening else account.get("opening_cash"),
            })

    def _supplement_stock_options(self, snapshot: dict | None, trade_date: date) -> list[dict]:
        """遗漏及非交易调整没有成交核验快照，按业务日批量补展示信息，不改历史事实。"""
        if snapshot is None:
            return []
        selected = {item["stock_code"]: item for item in [
            *snapshot["omissions"],
            *(event for event in snapshot["events"] if event.get("kind") != "trade"),
        ] if item.get("stock_code")}
        if not selected:
            return []
        statuses = self.discipline._st_statuses(trade_date, sorted(selected))
        return [{"code": code, "name": item.get("stock_name_snapshot") or item.get("stock_name") or code,
                 "board": None, "industry": None, "is_st": statuses.get(code),
                 "st_as_of_date": trade_date.isoformat()} for code, item in selected.items()]

    def _marked_positions(self, positions: list[dict], trade_date: date) -> list[dict]:
        """估值只读目标日及更早未复权收盘价，缺行情保留数量并明确空值。"""
        codes = sorted({p["stock_code"] for p in positions})
        if not codes:
            return []
        frame = self.discipline.market.query_df(
            "SELECT code,trade_date,close FROM daily_bar WHERE trade_date<=? AND close>0 AND isfinite(close) "
            "AND code IN (" + ",".join("?" for _ in codes) + ") "
            "QUALIFY row_number() OVER (PARTITION BY code ORDER BY trade_date DESC)=1",
            [trade_date, *codes],
        )
        quotes = {r["code"]: r for r in frame.to_dict("records")}
        result = []
        for position in positions:
            quote = quotes.get(position["stock_code"])
            value = None if quote is None else money(Decimal(str(quote["close"])) * Decimal(position["quantity"]))
            cost = position.get("cost")
            result.append({**position, "market_value": value,
                           "quote_date": None if quote is None else str(quote["trade_date"])[:10],
                           "unrealized_pnl": None if value is None or cost is None else money(Decimal(value) - Decimal(cost))})
        return result

    def _prepare(self, payload: dict, trade_date: date, rules: list[dict], previous=None) -> tuple[list, list]:
        raw_events = payload.get("events", [])
        if not isinstance(raw_events, list) or len(raw_events) > 3000:
            raise ValidationError("当日事件必须为列表且不超过3000条")
        rule_map = {r["rule_id"]: r for r in rules}
        events = []
        grouped: dict[str | None, list[dict]] = {}
        by_id = {}
        for raw in raw_events:
            if not isinstance(raw, dict):
                raise ValidationError("账本事件格式不正确")
            event = deepcopy(raw)
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 96 or event_id in by_id:
                raise ValidationError("事件标识不能为空、超过96字或重复")
            by_id[event_id] = event
            event["issues"], event["warnings"] = [], []
            event.pop("compliance_status", None)
            kind = event.get("kind", "trade")
            if kind == "trade":
                rid = event.get("rule_id") or None
                if rid is not None and rid not in rule_map:
                    raise ValidationError("成交关联规则不属于当日有效版本")
                grouped.setdefault(rid, []).append(event)
            elif kind in {"cash", "position"}:
                if event.get("rule_checks") or event.get("action_rule_id"):
                    raise ValidationError("非交易调整不能附加买卖操作规则核对")
                self._validate_group(event, rule_map)
                if kind == "cash" and event.get("rule_id"):
                    raise ValidationError("资金变动不关联选股分组")
                if kind == "position" or event.get("adjustment_type") == "dividend":
                    positions = [dict(event)]
                    self._names(positions, trade_date)
                    event["stock_name_snapshot"] = positions[0]["stock_name"]
                events.append(event)
            else:
                raise ValidationError("账本事件类型不正确")
        for rid, group in grouped.items():
            version = rule_map.get(rid)
            if version is None:
                version = {"stock_rules": [{"detail_id": "unplanned", "enabled": True}],
                           "action_rules": [{"detail_id": side, "enabled": True, "action_type": side}
                                            for side in ("buy", "sell")]}
            raw_operations = []
            for index, event in enumerate(group, 1):
                raw = dict(event, id=event["event_id"], display_order=index)
                if rid is None:
                    raw.update(stock_rule_id="unplanned", action_rule_id=event["side"], checklist_results=[])
                if event.get("amount_mode", "auto") == "auto":
                    raw["amount"] = money(trade_amount(
                        decimal_value(raw.get("price"), "价格", scale=4, positive=True),
                        decimal_value(raw.get("quantity"), "数量", scale=4, positive=True),
                    ))
                raw_operations.append(raw)
            prepared = self.discipline._prepare_operations(
                raw_operations, trade_date=trade_date, version=version,
                previous={"operations": [
                    event for event in (previous or {}).get("events", [])
                    if (event.get("selection_facts") or {}).get("is_st") is not None
                ]},
            )
            for operation, event in zip(prepared, group, strict=True):
                rule = next(r for r in version["stock_rules"] if r["detail_id"] == operation["stock_rule_id"])
                issues = condition_violations(rule, operation)
                warnings = [warning for warning in condition_warnings(rule, operation) if warning not in issues]
                action_matches = event.get("action_matches", True)
                if not isinstance(action_matches, bool):
                    raise ValidationError("买卖规则核对必须为符合/不符合")
                if rid is None:
                    issues.append("未按任何已设规则操作")
                elif not action_matches:
                    issues.append("不符合买卖操作规则")
                stock_matches = event.get("stock_matches", True)
                if not isinstance(stock_matches, bool):
                    raise ValidationError("补充选股条件核对必须为符合/不符合")
                if rid is not None and event["side"] == "buy" and not stock_matches:
                    issues.append("不符合补充选股条件")
                events.append({**event, **operation, "event_id": event["event_id"],
                               "kind": "trade", "rule_id": rid,
                               "stock_rule_id": operation["stock_rule_id"] if rid else None,
                               "action_rule_id": operation["action_rule_id"] if rid else None,
                               "display_order": event["display_order"], "issues": issues,
                               "warnings": warnings, "action_matches": action_matches,
                               "verification_source": {"conditions": "user_confirmed", "st": "server_daily"}})
        secondary: dict[str, list[tuple[dict, dict]]] = {}
        for event in events:
            if event.get("kind") != "trade":
                continue
            checks = event.get("rule_checks") or []
            if not isinstance(checks, list):
                raise ValidationError("关联规则核对必须为列表")
            seen_rules = {event.get("rule_id")}
            for check in checks:
                rid = check.get("rule_id") if isinstance(check, dict) else None
                if rid not in rule_map or rid in seen_rules:
                    raise ValidationError("同一成交的关联核对重复或不属于当日有效规则")
                seen_rules.add(rid)
                secondary.setdefault(rid, []).append((event, check))
        if sum(len(items) for items in secondary.values()) > 3000:
            raise ValidationError("当日附加规则核对不能超过3000项")
        for rid, pairs in secondary.items():
            version = rule_map[rid]
            raw = [{**event, **check, "id": f"check:{index}", "display_order": index}
                   for index, (event, check) in enumerate(pairs, 1)]
            prepared = self.discipline._prepare_operations(
                raw, trade_date=trade_date, version=version,
                previous={"operations": [event for event, _ in pairs]},
            )
            for (event, check), operation in zip(pairs, prepared, strict=True):
                stock_rule = next(r for r in version["stock_rules"] if r["detail_id"] == check["stock_rule_id"])
                issues = condition_violations(stock_rule, operation)
                warnings = [w for w in condition_warnings(stock_rule, operation) if w not in issues]
                matches = check.get("action_matches", True)
                if not isinstance(matches, bool):
                    raise ValidationError("关联买卖规则核对必须为符合/不符合")
                if not matches:
                    issues.append("不符合买卖操作规则")
                stock_matches = check.get("stock_matches", True)
                if not isinstance(stock_matches, bool):
                    raise ValidationError("关联选股条件核对必须为符合/不符合")
                if operation["side"] == "buy" and not stock_matches:
                    issues.append("不符合补充选股条件")
                check.update(issues=issues, warnings=warnings, selection_facts=operation["selection_facts"],
                             checklist_results=operation["checklist_results"], rule_name=version["name"])
        omissions = payload.get("omissions", [])
        if not isinstance(omissions, list) or len(omissions) > 3000:
            raise ValidationError("遗漏事项必须为列表且不超过3000条")
        omissions = [dict(item) if isinstance(item, dict) else item for item in omissions]
        seen = set()
        for omission in omissions:
            if not isinstance(omission, dict) or omission.get("kind") not in {"missed_buy", "missed_sell"}:
                raise ValidationError("遗漏事项仅支持应买未买、应卖未卖")
            if omission.get("rule_id") not in rule_map or not omission.get("stock_code"):
                raise ValidationError("漏买漏卖必须关联股票和当日有效规则")
            key = (omission["kind"], omission["rule_id"], omission["stock_code"])
            if key in seen:
                raise ValidationError("同股同规则的遗漏事项不能重复")
            seen.add(key)
        self._names(omissions, trade_date)
        return json_value(events), omissions

    def submit(self, trade_date: date, payload: dict, *, preview: bool = False) -> dict:
        return self._submit(trade_date, payload, preview=preview)

    def _submit(
        self, trade_date: date, payload: dict, *, preview: bool = False,
        quick_rule_id: str | None = None,
    ) -> dict:
        """快捷确认与正式提交共用账户锁及重算入口，确认范围仅由服务端决定。"""
        self.discipline._require_trade_date(trade_date)
        request_id = payload.get("request_id")
        if quick_rule_id is None and not preview and (
            not isinstance(request_id, str) or not request_id or len(request_id) > 96
        ):
            raise ValidationError("请提供有效幂等请求标识")
        digest = hashlib.sha256(json.dumps(json_value(payload), sort_keys=True).encode()).hexdigest()
        with self.repo.transaction() as conn:
            account = self.repo.account(conn, lock=True)
            if account["initialized_on"] is None:
                if quick_rule_id is not None:
                    raise ConflictError("请先进入交易打卡初始化真实期初持仓")
                raise ValidationError("请先初始化真实期初持仓，空仓也需要确认")
            if not preview and quick_rule_id is None:
                repeated = self.repo.request(request_id, conn)
                if repeated:
                    if repeated["payload_hash"] != digest or repeated["trade_date"] != trade_date:
                        raise ConflictError("同一请求标识不能提交不同内容")
                    return {**repeated["snapshot"], "revision_no": repeated["revision_no"], "idempotent": True}
            if quick_rule_id is None and account["revision"] != payload.get("expected_account_revision"):
                raise ConflictError("账户持仓已变化，请刷新后重新核对")
            latest = self.repo.latest(conn)
            if trade_date < account["initialized_on"] or (latest and trade_date < latest["trade_date"]):
                raise ConflictError("仅账户最新交易日可修正，历史漏单需先撤回后续日结")
            day = self.repo.day(trade_date, conn)
            revision = day["current_revision_no"] if day else 0
            if quick_rule_id is None and revision != payload.get("expected_revision", 0):
                raise ConflictError("日结已更新，请刷新后重试")
            current = day["snapshot"] if day and not day["withdrawn"] else None
            previous = self.repo.latest(conn, before=trade_date)
            rules = self._rules(trade_date, conn, current)
            confirmed_rule_ids = {rule["rule_id"] for rule in rules}
            if quick_rule_id is not None:
                if quick_rule_id not in confirmed_rule_ids:
                    raise NotFoundError("当日有效规则不存在")
                current_events = current["events"] if current else []
                current_omissions = current["omissions"] if current else []
                if any(
                    event.get("kind", "trade") == "trade" and (
                        event.get("rule_id") == quick_rule_id
                        or any(check["rule_id"] == quick_rule_id for check in event.get("rule_checks", []))
                    ) for event in current_events
                ) or any(item["rule_id"] == quick_rule_id for item in current_omissions):
                    raise ConflictError("本规则当日已有成交或遗漏事项，请进入正式打卡")
                # 无确认清单的旧快照沿用原来的整日确认口径，不猜测用户曾点击哪套规则。
                confirmed_rule_ids = set(current.get("confirmed_rule_ids", confirmed_rule_ids)) if current else set()
                if quick_rule_id in confirmed_rule_ids:
                    result = next((item for item in current["evaluations"] if item["rule_id"] == quick_rule_id), None)
                    if result and result["assessment"] == "complied":
                        return {"idempotent": True, "checkin_id": f"ledger:{trade_date}"}
                    raise ConflictError("本规则存在违规或待核对事项，请进入正式打卡")
                confirmed_rule_ids.add(quick_rule_id)
                request_id = f"quick:{trade_date}:{account['revision']}"
                payload = {"request_id": request_id, "events": current_events,
                           "omissions": current_omissions,
                           "review_note": current.get("review_note") if current else None,
                           "confirmed_rule_ids": sorted(confirmed_rule_ids)}
                digest = hashlib.sha256(json.dumps(json_value(payload), sort_keys=True).encode()).hexdigest()
            events, omissions = self._prepare(payload, trade_date, rules, current)
            # 稳定成交身份禁止在不同交易日复用；账户锁保证并发检查与写入原子。
            ids = [event["event_id"] for event in events]
            if ids:
                row = conn.execute(
                    "SELECT 1 FROM trade_discipline_ledger_day d "
                    "JOIN trade_discipline_ledger_revision r ON r.tenant_id=d.tenant_id "
                    "AND r.owner_user_id=d.owner_user_id AND r.account_id=d.account_id "
                    "AND r.trade_date=d.trade_date AND r.revision_no=d.current_revision_no, "
                    "LATERAL jsonb_array_elements(r.snapshot->'events') e "
                    "WHERE d.tenant_id=%s AND d.owner_user_id=%s AND d.account_id=%s "
                    "AND NOT d.withdrawn AND d.trade_date<>%s AND e->>'event_id'=ANY(%s) LIMIT 1",
                    [*self.repo.scope, trade_date, ids],
                ).fetchone()
                if row:
                    raise ConflictError("该成交已记入其他交易日，请勿重复记账")
            before = previous["snapshot"] if previous else None
            # 月末判定与规则生命周期复用同一个真实交易日历入口，每次核对只查询一次。
            next_trade_date = None
            if (trade_date.month in FINANCIAL_REPORT_PRECEDING_MONTHS
                    and any(r.get("restrict_financial_report_months", False) for r in rules)):
                next_trade_date = self.discipline._next_trade_date(trade_date)
            result = calculate_day(
                before["positions"] if before else account["opening_positions"], events, trade_date,
                opening_cash=before["cash"] if before else (
                    None if account["opening_cash"] is None else str(account["opening_cash"])
                ), rules=rules, omissions=omissions, next_trade_date=next_trade_date,
            )
            result.update(rules=json_value(rules), trade_date=trade_date.isoformat(),
                          review_note=self.discipline._optional_text(payload.get("review_note"), "复盘备注"),
                          created_at=datetime.now(SHANGHAI).isoformat())
            if quick_rule_id is not None:
                selected = next(item for item in result["evaluations"] if item["rule_id"] == quick_rule_id)
                if selected["assessment"] != "complied":
                    raise ConflictError("本规则已有持仓存在违规或待核对事项，请进入正式打卡")
            result["confirmed_rule_ids"] = sorted(confirmed_rule_ids)
            result["submission_source"] = "quick_no_operation" if quick_rule_id is not None else "workbench"
            for evaluation in result["evaluations"]:
                evaluation["confirmed"] = evaluation["rule_id"] in confirmed_rule_ids
                if not evaluation["confirmed"]:
                    evaluation.update(assessment=None, complete=False)
            if any(not item["confirmed"] for item in result["evaluations"]):
                result.update(assessment=None, complete=False)
            if not preview:
                self.repo.save(conn, trade_date, revision + 1, request_id, digest, result)
            return {**result, "revision_no": revision + (0 if preview else 1)}

    def withdraw(self, trade_date: date, expected_account_revision: int) -> dict:
        with self.repo.transaction() as conn:
            account = self.repo.account(conn, lock=True)
            latest = self.repo.latest(conn)
            if account["revision"] != expected_account_revision:
                raise ConflictError("账户已变化，请刷新后重试")
            if latest is None or latest["trade_date"] != trade_date:
                raise ConflictError("只能撤回账户最新日结")
            conn.execute(
                "UPDATE trade_discipline_ledger_day SET withdrawn=TRUE,updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND owner_user_id=%s AND account_id=%s AND trade_date=%s",
                [*self.repo.scope, trade_date],
            )
            conn.execute(
                "UPDATE trade_discipline_account SET revision=revision+1,updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s", self.repo.scope,
            )
        return self.context(trade_date)

    def revisions(self, trade_date: date, revision_no: int) -> dict:
        result = self.repo.day(trade_date, revision=revision_no)
        if result is None:
            raise NotFoundError("日结修订不存在")
        return json_value({**result, "stock_options": self._supplement_stock_options(result["snapshot"], trade_date)})

    def summary(self, trade_date: date) -> dict:
        self.discipline._require_trade_date(trade_date)
        context = self.context(trade_date)
        snapshot = context["snapshot"]
        evaluations = {r["rule_id"]: r for r in snapshot["evaluations"]} if snapshot else {}
        rules = []
        for rule in context["rules"]:
            result = evaluations.get(rule["rule_id"])
            confirmed = bool(result and result.get("confirmed", True))
            rules.append({
                "rule_id": rule["rule_id"], "rule_name": rule["name"],
                "version_no": rule["version_no"], "max_positions": rule.get("max_positions"),
                "effective_from_trade_date": trade_date.isoformat(),
                "checkin_id": f"ledger:{trade_date}" if confirmed else None,
                "current_revision_no": context["current_revision_no"] if confirmed else None,
                "assessment": result["assessment"] if result else None,
                "status": ("amended" if context["current_revision_no"] > 1
                           and snapshot.get("submission_source") != "quick_no_operation"
                           else "submitted") if confirmed else None,
                "no_operation": not any(
                    e["kind"] == "trade" and (e.get("rule_id") == rule["rule_id"] or any(
                        check["rule_id"] == rule["rule_id"] for check in e.get("rule_checks", [])
                    )) for e in snapshot["events"]
                ) if confirmed else None,
            })
        completed = sum(r["assessment"] is not None for r in rules)
        return {"trade_date": trade_date.isoformat(), "total": len(rules), "completed": completed,
                "pending": len(rules) - completed, "rules": rules,
                "account_initialized": context["initialized_on"] is not None}

    def quick_no_operation(self, rule_id: str, trade_date: date) -> dict:
        result = self._submit(trade_date, {}, quick_rule_id=rule_id)
        if result.get("idempotent"):
            return result
        return {"idempotent": False, "checkin_id": f"ledger:{trade_date}"}
