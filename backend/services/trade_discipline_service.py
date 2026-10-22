"""交易纪律规则生命周期服务。"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.services.trade_discipline_conditions import (
    condition_violations,
    condition_warnings,
    position_count,
    prepare_checklist_items,
    prepare_checklist_results,
)
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.trade_discipline_repository import TradeDisciplineRepository

SHANGHAI = ZoneInfo("Asia/Shanghai")
_BUILTIN_ACTION_SUBTYPES: tuple[tuple[str, str, str], ...] = (
    ("open_position", "建仓", "buy"),
    ("add_position", "加仓", "buy"),
    ("liquidate", "清仓", "sell"),
    ("reduce_position", "减仓", "sell"),
)
_LEGACY_ACTION_SUBTYPES: tuple[tuple[str, str, str], ...] = (
    ("do_t", "做 T", "sell"),
)
_SUPPORTED_ACTION_SUBTYPES = _BUILTIN_ACTION_SUBTYPES + _LEGACY_ACTION_SUBTYPES
_BUILTIN_SUBTYPE_SIDE = {value: side for value, _label, side in _SUPPORTED_ACTION_SUBTYPES}
_BUILTIN_SUBTYPE_ALIASES = {
    unicodedata.normalize("NFKC", alias).strip().casefold(): (value, side)
    for value, label, side in _SUPPORTED_ACTION_SUBTYPES
    for alias in (value, label)
}
_BUILTIN_SUBTYPE_VALUES = {
    unicodedata.normalize("NFKC", value).strip().casefold()
    for value, _label, _side in _SUPPORTED_ACTION_SUBTYPES
}
BUILTIN_VIOLATION_REASONS: tuple[tuple[str, str], ...] = (
    ("impulsive_trade", "冲动交易"),
    ("stock_rule_violation", "未按选股规则"),
    ("buy_rule_violation", "未按买入规则"),
    ("sell_rule_violation", "未按卖出规则"),
    ("capital_limit_exceeded", "超出资金上限"),
    ("missed_required_action", "应执行但未执行"),
    ("unplanned_operation", "计划外操作"),
    ("other", "其他"),
)


def normalize_rule_name(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    display = unicodedata.normalize("NFKC", str(value)).strip()
    if not display:
        return None, None
    return display, display.casefold()


class TradeDisciplineService:
    _DECIMAL_MAX_DIGITS = 20

    def __init__(
        self,
        repo: TradeDisciplineRepository | None = None,
        market: DuckDBClient | None = None,
    ):
        self.repo = repo or TradeDisciplineRepository()
        self.market = market or get_client()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"

    @staticmethod
    def _money(value: Any, *, allow_none: bool = True) -> Decimal | None:
        if value is None or value == "":
            if allow_none:
                return None
            raise ValidationError("金额不能为空")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("金额格式不正确") from exc
        if not result.is_finite() or result < 0 or result.as_tuple().exponent < -2:
            raise ValidationError("金额必须为非负且最多保留两位小数")
        if result >= Decimal(10) ** (TradeDisciplineService._DECIMAL_MAX_DIGITS - 2):
            raise ValidationError("金额整数部分最多 18 位")
        return result

    def _prepare_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        name, normalized = normalize_rule_name(payload.get("name"))
        prepared: dict[str, Any] = {
            "name": name,
            "normalized_name": normalized,
            "capital": self._money(payload.get("capital")),
            "max_positions": position_count(
                payload.get("max_positions"), label="最大同时持仓数", minimum=1
            ),
            "stock_rules": [],
            "action_rules": [],
        }
        for kind in ("stock_rules", "action_rules"):
            seen_ids: set[str] = set()
            seen_order: set[tuple[Any, int]] = set()
            for index, raw in enumerate(payload.get(kind) or [], start=1):
                item = dict(raw)
                item["detail_id"] = str(item.get("detail_id") or self._id("tdd"))
                if item["detail_id"] in seen_ids:
                    raise ValidationError("规则明细标识不能重复")
                seen_ids.add(item["detail_id"])
                if isinstance(item.get("display_order", index), bool):
                    raise ValidationError("规则明细顺序必须为正整数")
                try:
                    item["display_order"] = int(item.get("display_order", index))
                except (TypeError, ValueError) as exc:
                    raise ValidationError("规则明细顺序必须为正整数") from exc
                if item["display_order"] <= 0:
                    raise ValidationError("规则明细顺序必须为正整数")
                enabled = item.get("enabled", True)
                if not isinstance(enabled, bool):
                    raise ValidationError("规则明细启用状态必须为布尔值")
                item["enabled"] = enabled
                item["name"] = (
                    unicodedata.normalize("NFKC", str(item["name"])).strip()
                    if item.get("name") is not None
                    else None
                )
                content = item.get("content")
                if content is not None and not isinstance(content, str):
                    raise ValidationError("规则内容必须为文本")
                item["content"] = content
                if kind == "stock_rules":
                    item["checklist_items"] = prepare_checklist_items(raw.get("checklist_items", []))
                    item["max_capital"] = self._money(item.get("max_capital"))
                    for key in ("price_min", "price_max"):
                        item[key] = self._decimal(item.get(key), places=4, label="股价")
                        if item[key] is not None and item[key] <= 0:
                            raise ValidationError("股价上下限必须大于 0")
                    if (
                        item["price_min"] is not None and item["price_max"] is not None
                        and item["price_min"] > item["price_max"]
                    ):
                        raise ValidationError("股价下限不能大于上限")
                    for key in ("st_filter", "loss_filter", "st_risk_filter"):
                        item[key] = item.get(key, "any")
                        if item[key] not in {"any", "exclude", "only"}:
                            raise ValidationError("选股条件必须为不限、排除或仅限")
                    order_key = ("stock", item["display_order"])
                else:
                    action_type = item.get("action_type") or None
                    subtype = (
                        unicodedata.normalize("NFKC", str(item["action_subtype"])).strip()
                        if item.get("action_subtype") is not None
                        else None
                    )
                    builtin = _BUILTIN_SUBTYPE_ALIASES.get(subtype.casefold()) if subtype else None
                    if builtin:
                        subtype = builtin[0]
                    item["action_type"] = action_type
                    item["action_subtype"] = subtype
                    if action_type is not None and action_type not in {"buy", "sell"}:
                        raise ValidationError("操作方向不正确")
                    if subtype is not None and len(subtype) > 40:
                        raise ValidationError("操作类型最多 40 个字符")
                    if builtin and action_type is not None and builtin[1] != action_type:
                        raise ValidationError("操作方向与类型不匹配")
                    order_key = (action_type, item["display_order"])
                if order_key in seen_order:
                    raise ValidationError("同类规则明细顺序不能重复")
                seen_order.add(order_key)
                prepared[kind].append(item)
        return prepared

    @staticmethod
    def _action_subtype_claims(draft: dict[str, Any]) -> list[dict[str, str]]:
        claims: dict[str, dict[str, str]] = {}
        for item in draft["action_rules"]:
            subtype = item.get("action_subtype")
            side = item.get("action_type")
            if not subtype or not side:
                continue
            if subtype in _BUILTIN_SUBTYPE_SIDE:
                continue
            normalized = unicodedata.normalize("NFKC", str(subtype)).strip().casefold()
            previous = claims.get(normalized)
            if previous and previous["action_type"] != side:
                raise ValidationError(f"类型名称不能同时用于买入和卖出：{subtype}")
            claims[normalized] = {
                "normalized_name": normalized,
                "name": str(subtype),
                "action_type": str(side),
            }
        return list(claims.values())

    @staticmethod
    def _claims(rule: dict[str, Any], draft: dict[str, Any] | None) -> dict[str, str]:
        claims: dict[str, str] = {}
        if rule.get("normalized_name"):
            claims[str(rule["normalized_name"])] = str(rule["name"])
        if draft and draft.get("normalized_name"):
            claims[str(draft["normalized_name"])] = str(draft["name"])
        return claims

    @staticmethod
    def _validate_publish(draft: dict[str, Any]) -> None:
        if not draft.get("name"):
            raise ValidationError("规则名称不能为空")
        capital = draft.get("capital")
        if capital is None or capital <= 0:
            raise ValidationError("总资金必须大于 0")
        enabled_stocks = [x for x in draft["stock_rules"] if x["enabled"]]
        enabled_actions = [x for x in draft["action_rules"] if x["enabled"]]
        if not enabled_stocks:
            raise ValidationError("至少启用一条选股规则")
        if not any(x.get("action_type") == "buy" for x in enabled_actions):
            raise ValidationError("至少启用一条买入规则")
        if not any(x.get("action_type") == "sell" for x in enabled_actions):
            raise ValidationError("至少启用一条卖出规则")
        total = Decimal(0)
        for item in draft["stock_rules"]:
            if not item.get("name"):
                raise ValidationError("选股规则名称不能为空")
            checklist = item.get("checklist_items") or []
            if any(not entry["text"] for entry in checklist):
                raise ValidationError("检查项内容不能为空，请填写或删除空项")
            has_condition = bool(checklist) or any(
                item.get(key) is not None for key in ("price_min", "price_max")
            ) or any(item.get(key, "any") != "any" for key in (
                "st_filter", "loss_filter", "st_risk_filter"
            ))
            if not has_condition and not str(item.get("content") or "").strip():
                raise ValidationError("选股规则至少填写一项条件或补充说明")
            if item["enabled"]:
                maximum = item.get("max_capital")
                if maximum is None or maximum <= 0 or maximum > capital:
                    if maximum is not None and maximum > capital:
                        excess = maximum - capital
                        raise ValidationError(
                            f"选股规则“{item['name']}”资金上限超出总资金 {excess:.2f} 元"
                        )
                    raise ValidationError(f"选股规则“{item['name']}”资金上限必须大于 0")
                total += maximum
        if total > capital:
            names = "、".join(str(x["name"]) for x in enabled_stocks)
            raise ValidationError(
                f"启用的选股规则（{names}）资金上限合计超出总资金 {total - capital:.2f} 元"
            )
        for item in draft["action_rules"]:
            if not item.get("name") or not str(item.get("content") or "").strip():
                raise ValidationError("操作规则名称和内容不能为空")
            action_type = item.get("action_type")
            subtype = item.get("action_subtype")
            if action_type not in {"buy", "sell"} or not subtype:
                raise ValidationError("操作方向和类型不能为空")
            if subtype in _BUILTIN_SUBTYPE_SIDE and _BUILTIN_SUBTYPE_SIDE[subtype] != action_type:
                raise ValidationError("操作方向与类型不匹配")

    @staticmethod
    def _fingerprint(data: dict[str, Any]) -> tuple[Any, ...]:
        stocks = tuple(
            (
                x["detail_id"],
                x.get("name"),
                x.get("max_capital"),
                x.get("price_min"),
                x.get("price_max"),
                x.get("st_filter", "any"),
                x.get("loss_filter", "any"),
                x.get("st_risk_filter", "any"),
                tuple((entry["item_id"], entry["category"], entry["text"], entry["display_order"])
                      for entry in x.get("checklist_items") or []),
                x.get("content"),
                x["display_order"],
                x["enabled"],
            )
            for x in sorted(
                data["stock_rules"], key=lambda item: (item["display_order"], item["detail_id"])
            )
        )
        actions = tuple(
            (
                x["detail_id"],
                x.get("name"),
                x.get("action_type"),
                x.get("action_subtype"),
                x.get("content"),
                x["display_order"],
                x["enabled"],
            )
            for x in sorted(
                data["action_rules"],
                key=lambda item: (
                    item.get("action_type") or "",
                    item["display_order"],
                    item["detail_id"],
                ),
            )
        )
        return data.get("name"), data.get("capital"), data.get("max_positions"), stocks, actions

    def _next_trade_date(self, occurred_at: Any) -> date:
        action_date = occurred_at.astimezone(SHANGHAI).date()
        df = self.market.query_df(
            "SELECT trade_date FROM trade_calendar WHERE is_open AND trade_date > ? "
            "ORDER BY trade_date LIMIT 1",
            [action_date],
        )
        if df.empty:
            raise ValidationError("交易日历缺少动作日后的下一开市日")
        value = df.iloc[0]["trade_date"]
        if isinstance(value, datetime):
            return value.date()
        return value if type(value) is date else value.to_pydatetime().date()

    def create_rule(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        draft = self._prepare_draft(payload or {})
        rule_id = self._id("tdr")
        with self.repo.transaction() as conn:
            self.repo.create_rule(conn, rule_id)
            rule = self.repo.lock_rule(conn, rule_id)
            self.repo.sync_name_claims(conn, rule_id, self._claims(rule, draft))
            self.repo.claim_action_subtypes(conn, self._action_subtype_claims(draft))
            self.repo.replace_draft(conn, rule_id, draft, 1, None)
        return self.get_rule(rule_id)

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        rule = self.repo.get_rule(rule_id)
        rule["draft"] = self.repo.load_draft(rule_id)
        rule["latest_version"] = None
        if rule.get("latest_version_no"):
            rule["latest_version"] = self.repo.load_version(rule_id, int(rule["latest_version_no"]))
        return rule

    def list_rules(self) -> list[dict[str, Any]]:
        return self.repo.list_rules()

    def list_action_subtypes(self) -> list[dict[str, Any]]:
        saved = self.repo.list_action_subtypes()
        by_name = {
            unicodedata.normalize("NFKC", str(item["name"])).strip().casefold(): {
                **item,
                "builtin": False,
            }
            for item in saved
            # 新增全局默认类型前可能已有同名自定义候选；全局项必须成为唯一展示项。
            if unicodedata.normalize("NFKC", str(item["name"])).strip().casefold()
            not in _BUILTIN_SUBTYPE_ALIASES
        }
        for value, label, side in _BUILTIN_ACTION_SUBTYPES:
            by_name.setdefault(
                value.casefold(),
                {
                    "name": value,
                    "label": label,
                    "action_type": side,
                    "builtin": True,
                },
            )
        return sorted(
            by_name.values(),
            key=lambda item: (
                item["action_type"],
                not item.get("builtin", False),
                item.get("label") or item["name"],
            ),
        )

    def delete_action_subtype(self, name: str) -> dict[str, str]:
        display, normalized = normalize_rule_name(name)
        if not display or not normalized:
            raise ValidationError("买卖类型名称不能为空")
        if normalized in _BUILTIN_SUBTYPE_VALUES:
            raise ValidationError("全局默认买卖类型不可删除")
        try:
            removed = self.repo.delete_action_subtype(normalized)
        except NotFoundError as exc:
            # 全局项的中文标签不是目录主键，但 API 仍需给出明确的不可删除语义。
            if normalized in _BUILTIN_SUBTYPE_ALIASES:
                raise ValidationError("全局默认买卖类型不可删除") from exc
            raise
        return {
            "name": str(removed["name"]),
            "action_type": str(removed["action_type"]),
        }

    @staticmethod
    def _lifecycle_state(row: dict[str, Any], trade_date: date | None) -> dict[str, Any]:
        """把批量查询的扁平事件列整理为稳定的双状态 DTO。"""
        def value(key: str) -> Any:
            current = row.get(key)
            return None if current is None or pd.isna(current) else current

        management_seq = value("management_event_seq")
        effective_seq = value("effective_event_seq")
        effective_type = value("effective_event_type")
        management_event = None
        if management_seq is not None:
            management_event = {
                "event_type": value("management_event_type"),
                "event_seq": int(management_seq),
                "version_no": int(value("management_version_no")),
                "occurred_at": value("management_occurred_at"),
                "activated_at": value("management_activated_at"),
                "effective_from_trade_date": value(
                    "management_effective_from_trade_date"
                ),
            }
        effective_version = None
        effective_version_no = value("effective_version_no")
        if effective_type is not None and effective_type != "archive":
            effective_version = {
                "version_no": int(effective_version_no),
                "name": value("effective_version_name"),
                "capital": value("effective_version_capital"),
            }
        return {
            "as_of_trade_date": trade_date,
            "management_status": row["status"],
            "latest_management_event": management_event,
            "has_pending_management_action": management_seq != effective_seq,
            "effective_status": (
                "unpublished" if effective_type is None
                else "archived" if effective_type == "archive"
                else "active"
            ),
            "effective_event_seq": int(effective_seq) if effective_seq is not None else None,
            "effective_from_trade_date": value("effective_from_trade_date"),
            "effective_version": effective_version,
        }

    def list_rules_with_state(self, trade_date: date | None) -> list[dict[str, Any]]:
        rows = self.repo.list_rules_with_lifecycle(trade_date)
        hidden = {
            "management_event_type", "management_event_seq", "management_version_no",
            "management_occurred_at", "management_activated_at",
            "management_effective_from_trade_date", "effective_event_type",
            "effective_event_seq", "effective_version_no", "effective_from_trade_date",
            "effective_version_name", "effective_version_capital",
        }
        return [
            {**{key: value for key, value in row.items() if key not in hidden},
             **self._lifecycle_state(row, trade_date)}
            for row in rows
        ]

    def get_rule_with_state(self, rule_id: str, trade_date: date | None) -> dict[str, Any]:
        rows = self.repo.list_rules_with_lifecycle(trade_date, rule_id=rule_id)
        if not rows:
            raise NotFoundError("交易纪律规则不存在")
        state = self._lifecycle_state(rows[0], trade_date)
        detail = self.get_rule(rule_id)
        effective = state["effective_version"]
        if effective is not None:
            state["effective_version"] = self.repo.load_version(
                rule_id, int(effective["version_no"])
            )
        return {**detail, **state}

    def open_draft(self, rule_id: str) -> dict[str, Any]:
        with self.repo.transaction() as conn:
            rule = self.repo.lock_rule(conn, rule_id)
            if rule["status"] == "archived":
                raise ConflictError("已归档规则不能编辑")
            existing = self.repo.load_draft(rule_id, conn=conn)
            if existing is not None:
                return existing
            if rule["status"] != "active" or not rule["latest_version_no"]:
                raise ConflictError("未发布规则必须保留草稿")
            version = self.repo.load_version(rule_id, int(rule["latest_version_no"]), conn=conn)
            draft = {
                "name": version["name"],
                "normalized_name": version["normalized_name"],
                "capital": version["capital"],
                "max_positions": version.get("max_positions"),
                "stock_rules": version["stock_rules"],
                "action_rules": version["action_rules"],
            }
            self.repo.replace_draft(conn, rule_id, draft, 1, int(rule["latest_version_no"]))
            self.repo.sync_name_claims(conn, rule_id, self._claims(rule, draft))
            return self.repo.load_draft(rule_id, conn=conn) or {}

    def save_draft(
        self, rule_id: str, payload: dict[str, Any], *, expected_revision: int
    ) -> dict[str, Any]:
        draft = self._prepare_draft(payload)
        with self.repo.transaction() as conn:
            rule = self.repo.lock_rule(conn, rule_id)
            if rule["status"] == "archived":
                raise ConflictError("已归档规则不能编辑")
            current = self.repo.load_draft(rule_id, conn=conn)
            if current is None:
                raise NotFoundError("工作草稿不存在，请先创建草稿")
            if int(current["draft_revision"]) != expected_revision:
                raise ConflictError("草稿已被其他操作更新，请刷新后重试")
            self.repo.sync_name_claims(conn, rule_id, self._claims(rule, draft))
            self.repo.claim_action_subtypes(conn, self._action_subtype_claims(draft))
            self.repo.replace_draft(
                conn,
                rule_id,
                draft,
                expected_revision + 1,
                current.get("source_version_no"),
            )
        return self.repo.load_draft(rule_id) or {}

    def discard_draft(self, rule_id: str) -> dict[str, Any]:
        with self.repo.transaction() as conn:
            rule = self.repo.lock_rule(conn, rule_id)
            if rule["status"] != "active":
                raise ConflictError("仅已发布规则可放弃草稿")
            self.repo.delete_draft(conn, rule_id)
            self.repo.sync_name_claims(conn, rule_id, self._claims(rule, None))
        return self.get_rule(rule_id)

    def publish_rule(self, rule_id: str, *, expected_revision: int) -> dict[str, Any]:
        with self.repo.transaction() as conn:
            rule = self.repo.lock_rule(conn, rule_id)
            if rule["status"] == "archived":
                raise ConflictError("已归档规则不能发布")
            draft = self.repo.load_draft(rule_id, conn=conn)
            if draft is None:
                raise NotFoundError("工作草稿不存在")
            if int(draft["draft_revision"]) != expected_revision:
                raise ConflictError("草稿已被其他操作更新，请刷新后重试")
            self._validate_publish(draft)
            latest_no = int(rule["latest_version_no"] or 0)
            if latest_no:
                latest = self.repo.load_version(rule_id, latest_no, conn=conn)
                if self._fingerprint(draft) == self._fingerprint(latest):
                    self.repo.delete_draft(conn, rule_id)
                    self.repo.sync_name_claims(conn, rule_id, self._claims(rule, None))
                    return {"changed": False, "rule_id": rule_id, "version_no": latest_no}
            version_no = latest_no + 1
            self.repo.insert_version(conn, rule_id, version_no, draft)
            event_seq, occurred_at = self.repo.allocate_event(conn, rule_id)
            effective_date = self._next_trade_date(occurred_at)
            self.repo.insert_activation(
                conn,
                activation_id=self._id("tda"),
                rule_id=rule_id,
                event_seq=event_seq,
                event_type="publish",
                version_no=version_no,
                occurred_at=occurred_at,
                effective_date=effective_date,
            )
            self.repo.update_lifecycle(
                conn,
                rule_id,
                status="active",
                name=draft["name"],
                normalized_name=draft["normalized_name"],
                latest_version_no=version_no,
            )
            self.repo.delete_draft(conn, rule_id)
            formal_rule = dict(rule, name=draft["name"], normalized_name=draft["normalized_name"])
            self.repo.sync_name_claims(conn, rule_id, self._claims(formal_rule, None))
        return {
            "changed": True,
            "rule_id": rule_id,
            "version_no": version_no,
            "event_seq": event_seq,
            "effective_from_trade_date": effective_date,
        }

    def _lifecycle_event(self, rule_id: str, event_type: str) -> dict[str, Any]:
        with self.repo.transaction() as conn:
            rule = self.repo.lock_rule(conn, rule_id)
            expected_status = "active" if event_type == "archive" else "archived"
            target_status = "archived" if event_type == "archive" else "active"
            if rule["status"] != expected_status:
                raise ConflictError(f"当前规则状态不能执行{event_type}")
            if event_type == "archive" and self.repo.load_draft(rule_id, conn=conn) is not None:
                raise ConflictError("归档前必须先发布或放弃工作草稿")
            event_seq, occurred_at = self.repo.allocate_event(conn, rule_id)
            effective_date = self._next_trade_date(occurred_at)
            version_no = int(rule["latest_version_no"])
            self.repo.insert_activation(
                conn,
                activation_id=self._id("tda"),
                rule_id=rule_id,
                event_seq=event_seq,
                event_type=event_type,
                version_no=version_no,
                occurred_at=occurred_at,
                effective_date=effective_date,
            )
            self.repo.update_lifecycle(
                conn,
                rule_id,
                status=target_status,
                name=rule["name"],
                normalized_name=rule["normalized_name"],
                latest_version_no=version_no,
            )
        return {
            "rule_id": rule_id,
            "event_type": event_type,
            "event_seq": event_seq,
            "version_no": version_no,
            "effective_from_trade_date": effective_date,
        }

    def archive_rule(self, rule_id: str) -> dict[str, Any]:
        return self._lifecycle_event(rule_id, "archive")

    def restore_rule(self, rule_id: str) -> dict[str, Any]:
        return self._lifecycle_event(rule_id, "restore")

    def effective_version(self, rule_id: str, trade_date: date) -> dict[str, Any] | None:
        self.repo.get_rule(rule_id)
        event = self.repo.effective_activation(rule_id, trade_date)
        if event is None or event["event_type"] == "archive":
            return None
        return self.repo.load_version(rule_id, int(event["version_no"]))

    def copy_rule(self, rule_id: str, *, source: str = "published") -> dict[str, Any]:
        if source not in {"published", "draft"}:
            raise ValidationError("复制来源必须是 published 或 draft")
        with self.repo.transaction() as conn:
            rule = self.repo.lock_rule(conn, rule_id)
            if source == "draft":
                source_data = self.repo.load_draft(rule_id, conn=conn)
                if source_data is None:
                    raise NotFoundError("工作草稿不存在")
            else:
                if not rule["latest_version_no"]:
                    raise NotFoundError("正式版本不存在")
                source_data = self.repo.load_version(
                    rule_id, int(rule["latest_version_no"]), conn=conn
                )
            base = str(source_data.get("name") or "未命名规则")
            suffix = 1
            while True:
                candidate = f"{base}-副本" if suffix == 1 else f"{base}-副本{suffix}"
                name, normalized = normalize_rule_name(candidate)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM trade_discipline_rule_name_claim "
                        "WHERE tenant_id=%s AND owner_user_id=%s AND normalized_name=%s",
                        [*self.repo.owner, normalized],
                    )
                    if cur.fetchone() is None:
                        break
                suffix += 1
            draft = self._prepare_draft(
                {
                    "name": name,
                    "capital": source_data.get("capital"),
                    "max_positions": source_data.get("max_positions"),
                    "stock_rules": source_data["stock_rules"],
                    "action_rules": source_data["action_rules"],
                }
            )
            draft["normalized_name"] = normalized
            # 副本是独立规则，检查项不能复用来源的标识或可变对象。
            for stock_rule in draft["stock_rules"]:
                for entry in stock_rule["checklist_items"]:
                    entry["item_id"] = self._id("tdci")
            copied_id = self._id("tdr")
            self.repo.create_rule(conn, copied_id)
            copied = self.repo.lock_rule(conn, copied_id)
            self.repo.sync_name_claims(conn, copied_id, self._claims(copied, draft))
            self.repo.claim_action_subtypes(conn, self._action_subtype_claims(draft))
            self.repo.replace_draft(conn, copied_id, draft, 1, None)
        return self.get_rule(copied_id)

    def delete_rule(self, rule_id: str) -> None:
        with self.repo.transaction() as conn:
            self.repo.lock_rule(conn, rule_id)
            self.repo.delete_unpublished(conn, rule_id)

    # ── T3：打卡、原因、操作与历史 ────────────────────────────────

    @staticmethod
    def _decimal(
        value: Any,
        *,
        places: int,
        label: str,
    ) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValidationError(f"{label}格式不正确")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"{label}格式不正确") from exc
        if not result.is_finite() or result < 0:
            raise ValidationError(f"{label}不能为负数")
        if result.as_tuple().exponent < -places:
            raise ValidationError(f"{label}最多保留 {places} 位小数")
        integer_digits = TradeDisciplineService._DECIMAL_MAX_DIGITS - places
        if result >= Decimal(10) ** integer_digits:
            raise ValidationError(f"{label}整数部分最多 {integer_digits} 位")
        return result

    def _require_trade_date(self, trade_date: date) -> None:
        if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
            raise ValidationError("履约日期格式不正确")
        exists = self.market.query_df(
            "SELECT 1 FROM daily_bar WHERE trade_date=? LIMIT 1", [trade_date]
        )
        if exists.empty:
            raise ValidationError("履约日期不是已有行情交易日")

    @staticmethod
    def _optional_text(value: Any, label: str) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValidationError(f"{label}必须为文本")
        return value

    def _prepare_operations(
        self,
        raw_operations: list[dict[str, Any]],
        *,
        trade_date: date,
        version: dict[str, Any],
        previous: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        enabled_stocks = {
            str(item["detail_id"]): item for item in version["stock_rules"] if bool(item["enabled"])
        }
        enabled_actions = {
            str(item["detail_id"]): item
            for item in version["action_rules"]
            if bool(item["enabled"])
        }
        prepared: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_orders: set[int] = set()
        for index, raw in enumerate(raw_operations, start=1):
            if not isinstance(raw, dict):
                raise ValidationError("操作记录格式不正确")
            item = dict(raw)
            operation_id = str(item.get("id") or self._id("tdo"))
            if operation_id in seen_ids:
                raise ValidationError("操作记录标识不能重复")
            seen_ids.add(operation_id)
            raw_order = item.get("display_order", index)
            if isinstance(raw_order, bool):
                raise ValidationError("操作顺序必须为正整数")
            try:
                display_order = int(raw_order)
            except (TypeError, ValueError) as exc:
                raise ValidationError("操作顺序必须为正整数") from exc
            if display_order <= 0 or display_order in seen_orders:
                raise ValidationError("操作顺序必须为互不重复的正整数")
            seen_orders.add(display_order)
            side = item.get("side")
            if side not in {"buy", "sell"}:
                raise ValidationError("操作方向必须为 buy 或 sell")
            stock_rule_id = str(item.get("stock_rule_id") or "")
            action_rule_id = str(item.get("action_rule_id") or "")
            if stock_rule_id not in enabled_stocks:
                raise ValidationError("操作关联的选股规则不存在、未启用或不属于绑定版本")
            action_rule = enabled_actions.get(action_rule_id)
            if action_rule is None or action_rule["action_type"] != side:
                raise ValidationError("操作关联的买卖规则不存在、未启用、方向错误或不属于绑定版本")
            stock_code = unicodedata.normalize("NFKC", str(item.get("stock_code") or "")).strip()
            if not stock_code:
                raise ValidationError("股票代码不能为空")
            operated_at = item.get("operated_at")
            if isinstance(operated_at, str):
                try:
                    operated_at = datetime.fromisoformat(operated_at)
                except ValueError as exc:
                    raise ValidationError("操作时间格式不正确") from exc
            if operated_at is not None:
                if not isinstance(operated_at, datetime):
                    raise ValidationError("操作时间格式不正确")
                if operated_at.tzinfo is None:
                    operated_at = operated_at.replace(tzinfo=SHANGHAI)
                if operated_at.astimezone(SHANGHAI).date() != trade_date:
                    raise ValidationError("操作时间必须落在履约交易日")
            facts = {}
            stock_rule = enabled_stocks[stock_rule_id]
            checklist_results = prepare_checklist_results(stock_rule, item)
            for key, condition_key in (
                ("loss_status", "loss_filter"), ("st_risk_status", "st_risk_filter")
            ):
                status = item.get(key)
                if status is not None and status not in {"yes", "no", "unknown"}:
                    raise ValidationError("选股事实必须为是、否或未知")
                if side == "buy" and stock_rule.get(condition_key, "any") != "any" and status is None:
                    raise ValidationError("请明确选择亏损/ST风险事实，未查明可选未知")
                facts[key] = status if side == "buy" else None
            prepared.append(
                {
                    "id": operation_id,
                    "stock_code": stock_code,
                    # 名称在批量验证股票主数据后由服务端覆盖，禁止信任客户端快照。
                    "stock_name_snapshot": "",
                    "selection_facts": facts,
                    "checklist_results": checklist_results,
                    "side": side,
                    "stock_rule_id": stock_rule_id,
                    "action_rule_id": action_rule_id,
                    "price": self._decimal(item.get("price"), places=4, label="成交价格"),
                    "quantity": self._decimal(item.get("quantity"), places=4, label="成交数量"),
                    "amount": self._decimal(item.get("amount"), places=2, label="成交金额"),
                    "fee": self._decimal(item.get("fee"), places=2, label="交易费用"),
                    "operated_at": operated_at,
                    "note": self._optional_text(item.get("note"), "操作说明"),
                    "compliance_status": item.get("compliance_status"),
                    "display_order": display_order,
                }
            )
        codes = sorted({item["stock_code"] for item in prepared})
        if codes:
            placeholders = ",".join("?" for _ in codes)
            frame = self.market.query_df(
                "SELECT code,name,list_date,delist_date FROM stock_basic "
                f"WHERE code IN ({placeholders})",
                codes,
            )
            stocks = {
                str(row["code"]): row
                for row in frame.astype(object).where(pd.notna(frame), None).to_dict("records")
            }
            missing = [code for code in codes if code not in stocks]
            if missing:
                raise ValidationError(f"股票代码不存在：{'、'.join(missing)}")
            not_listed = [
                code for code in codes
                if stocks[code]["list_date"] is not None
                and pd.Timestamp(stocks[code]["list_date"]).date() > trade_date
            ]
            if not_listed:
                raise ValidationError(f"履约日期尚未上市：{'、'.join(not_listed)}")
            delisted = [
                code for code in codes
                if stocks[code]["delist_date"] is not None
                and trade_date >= pd.Timestamp(stocks[code]["delist_date"]).date()
            ]
            if delisted:
                raise ValidationError(f"履约日期已经退市：{'、'.join(delisted)}")
            for item in prepared:
                item["stock_name_snapshot"] = str(stocks[item["stock_code"]]["name"] or "").strip()
                if not item["stock_name_snapshot"]:
                    raise ValidationError(f"股票名称缺失：{item['stock_code']}")
        # 同一交易日同一股票的ST快照在修正时沿用；只批量读取尚无快照的股票。
        old_facts = {
            item["stock_code"]: item["selection_facts"]
            for item in (previous or {}).get("operations", []) if item.get("selection_facts")
        }
        statuses = self._st_statuses(trade_date, [code for code in codes if code not in old_facts])
        for item in prepared:
            previous_facts = old_facts.get(item["stock_code"])
            item["selection_facts"].update({
                "is_st": (
                    previous_facts.get("is_st") if previous_facts
                    else statuses.get(item["stock_code"])
                ),
                "st_as_of_date": trade_date.isoformat(),
            })
        return prepared

    def _st_statuses(self, trade_date: date, codes: list[str]) -> dict[str, bool]:
        if not codes:
            return {}
        from backend.services.stock_st_status import StockSTStatusService, STStatusNotReadyError

        try:
            return StockSTStatusService(self.market).status_map(trade_date, codes)
        except STStatusNotReadyError:
            return {}

    def _prepare_checkin(
        self,
        payload: dict[str, Any],
        *,
        trade_date: date,
        version: dict[str, Any],
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        peak_positions = position_count(
            payload.get("peak_positions"), label="当日最大同时持仓数", minimum=0
        )
        if version.get("max_positions") is not None and peak_positions is None:
            raise ValidationError("本套规则限制持仓数量，请填写当日最大同时持仓数")
        assessment = payload.get("assessment")
        if assessment not in {"complied", "partial", "breached"}:
            raise ValidationError("用户自评必须为 complied、partial 或 breached")
        no_operation = payload.get("no_operation")
        if not isinstance(no_operation, bool):
            raise ValidationError("是否无操作必须为布尔值")
        raw_operations = payload.get("operations") or []
        if not isinstance(raw_operations, list):
            raise ValidationError("操作记录必须为数组")
        if assessment == "partial" and no_operation:
            raise ValidationError("部分履约必须填写实际操作")
        if assessment == "partial" and not raw_operations:
            raise ValidationError("部分履约至少需要一条操作")
        if no_operation and raw_operations:
            raise ValidationError("今日无操作与操作记录互斥")
        if not no_operation and not raw_operations:
            raise ValidationError("未选择今日无操作时至少填写一条操作")
        violation_detail = payload.get("violation_detail")
        reason_values = []
        for field in ("reason_code", "reason_id", "reason_text"):
            value = payload.get(field)
            if value is not None and not isinstance(value, str):
                raise ValidationError("未履约原因必须是单个文本或原因标识")
            reason_values.append(value)
        selected_reasons = sum(
            value is not None and str(value).strip() != "" for value in reason_values
        )
        has_violation = assessment in {"partial", "breached"}
        if has_violation:
            if not isinstance(violation_detail, str) or not violation_detail.strip():
                raise ValidationError("部分履约或未履约时必须填写详细说明")
            if selected_reasons != 1:
                raise ValidationError("部分履约或未履约时必须且只能选择一个原因")
        else:
            if selected_reasons or (violation_detail is not None and str(violation_detail).strip()):
                raise ValidationError("已履约不能填写未履约原因或详细说明")
            violation_detail = None
        operations = self._prepare_operations(
            raw_operations, trade_date=trade_date, version=version, previous=previous
        )
        operation_statuses = [item.get("compliance_status") for item in operations]
        if assessment == "partial":
            if any(status not in {"complied", "breached"} for status in operation_statuses):
                raise ValidationError("部分履约时每笔操作都必须选择履约状态")
        elif any(status is not None for status in operation_statuses):
            raise ValidationError("仅部分履约可以填写单笔操作履约状态")
        # ST 使用服务端逐日事实/既有修订快照；不信任前端的自评或 ST 标记。
        stock_rules = {item["detail_id"]: item for item in version["stock_rules"]}
        violations = []
        limit = version.get("max_positions")
        if limit is not None and peak_positions is not None and peak_positions > limit:
            violations.append(f"当日最大同时持仓 {peak_positions} 只，超过规则上限 {limit} 只")
        for index, operation in enumerate(operations, start=1):
            issues = condition_violations(stock_rules[operation["stock_rule_id"]], operation)
            violations.extend(f"操作 {index}：{issue}" for issue in issues)
            if issues and operation.get("compliance_status") == "complied":
                raise ValidationError(f"操作 {index} 存在规则违规，不能选择已履约：{'；'.join(issues)}")
        if assessment == "complied" and violations:
            raise ValidationError(f"存在规则违规，不能选择已履约：{'；'.join(violations)}")
        return {
            "peak_positions": peak_positions,
            "assessment": assessment,
            "no_operation": no_operation,
            "violation_detail": violation_detail,
            "review_note": self._optional_text(payload.get("review_note"), "复盘说明"),
            "reason_code": payload.get("reason_code"),
            "reason_id": payload.get("reason_id"),
            "reason_text": payload.get("reason_text"),
            "operations": operations,
        }

    def _resolve_reason(
        self,
        conn: psycopg.Connection,
        prepared: dict[str, Any],
    ) -> dict[str, str | None] | None:
        if prepared["assessment"] not in {"partial", "breached"}:
            return None
        builtins = {code: name for code, name in BUILTIN_VIOLATION_REASONS}
        normalized_builtins = {
            normalize_rule_name(name)[1]: (code, name) for code, name in BUILTIN_VIOLATION_REASONS
        }
        if prepared.get("reason_code"):
            code = str(prepared["reason_code"])
            if code not in builtins:
                raise ValidationError("内置未履约原因不存在")
            return {"reason_code": code, "reason_id": None, "name": builtins[code]}
        if prepared.get("reason_id"):
            row = self.repo.get_active_reason(str(prepared["reason_id"]), conn=conn)
            return {"reason_code": None, "reason_id": str(row["id"]), "name": str(row["name"])}
        name, normalized = normalize_rule_name(str(prepared.get("reason_text") or ""))
        if name is None or normalized is None:
            raise ValidationError("未履约原因不能为空")
        builtin = normalized_builtins.get(normalized)
        if builtin is not None:
            return {"reason_code": builtin[0], "reason_id": None, "name": builtin[1]}
        row = self.repo.upsert_reason(
            conn,
            reason_id=self._id("tdreason"),
            name=name,
            normalized_name=normalized,
        )
        return {"reason_code": None, "reason_id": str(row["id"]), "name": str(row["name"])}

    def _write_revision(
        self,
        conn: psycopg.Connection,
        *,
        checkin_id: str,
        revision_no: int,
        rule_id: str,
        version_no: int,
        prepared: dict[str, Any],
    ) -> None:
        reason = self._resolve_reason(conn, prepared)
        self.repo.insert_revision(
            conn,
            checkin_id=checkin_id,
            revision_no=revision_no,
            rule_id=rule_id,
            version_no=version_no,
            assessment=prepared["assessment"],
            no_operation=prepared["no_operation"],
            violation_detail=prepared["violation_detail"],
            review_note=prepared["review_note"],
            peak_positions=prepared.get("peak_positions"),
        )
        if reason is not None:
            self.repo.insert_violation(
                conn,
                checkin_id=checkin_id,
                revision_no=revision_no,
                reason_code=reason["reason_code"],
                reason_id=reason["reason_id"],
                reason_name=str(reason["name"]),
            )
        self.repo.insert_operations(
            conn,
            checkin_id=checkin_id,
            revision_no=revision_no,
            rule_id=rule_id,
            version_no=version_no,
            operations=prepared["operations"],
        )

    def _decorate_revision(self, revision: dict[str, Any]) -> dict[str, Any]:
        operations = revision.get("operations") or []
        trade_date = pd.Timestamp(revision["trade_date"]).date()
        statuses: dict[str, bool] = {}
        legacy_operations = [item for item in operations if not item.get("selection_facts")]
        if legacy_operations:
            from backend.services.stock_st_status import (
                StockSTStatusService,
                STStatusNotReadyError,
            )

            try:
                statuses = StockSTStatusService(self.market).status_map(
                    trade_date, sorted({str(item["stock_code"]) for item in legacy_operations})
                )
            except STStatusNotReadyError:
                # 交易纪律可保留既有操作快照；展示事实缺失时明确返回未知，不阻断复盘。
                statuses = {}
        for operation in operations:
            facts = operation.get("selection_facts")
            operation["is_st"] = facts.get("is_st") if facts else statuses.get(str(operation["stock_code"]))
            operation["st_as_of_date"] = facts.get("st_as_of_date") if facts else trade_date.isoformat()
            operation["loss_status"] = facts.get("loss_status") if facts else None
            operation["st_risk_status"] = facts.get("st_risk_status") if facts else None
            operation["condition_warnings"] = condition_warnings(operation, operation)
            operation["financial_complete"] = all(
                operation.get(field) is not None
                for field in ("price", "quantity", "amount", "fee", "operated_at")
            )
        revision["financial_complete"] = bool(revision.get("no_operation")) or all(
            operation["financial_complete"] for operation in operations
        )
        return revision

    def submit_checkin(
        self,
        rule_id: str,
        trade_date: date,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_trade_date(trade_date)
        with self.repo.transaction() as conn:
            self.repo.lock_rule(conn, rule_id)
            existing = self.repo.get_checkin_by_rule_date(
                rule_id, trade_date, conn=conn, for_update=True
            )
            if existing is not None:
                raise ConflictError("该规则在此交易日已经提交过打卡，请使用修正")
            event = self.repo.effective_activation(rule_id, trade_date, conn=conn)
            if event is None or event["event_type"] == "archive":
                raise ValidationError("该日期尚无生效规则版本")
            version_no = int(event["version_no"])
            version = self.repo.load_version(rule_id, version_no, conn=conn)
            prepared = self._prepare_checkin(payload, trade_date=trade_date, version=version)
            checkin_id = self._id("tdc")
            self.repo.create_checkin(
                conn,
                checkin_id=checkin_id,
                rule_id=rule_id,
                trade_date=trade_date,
                submission_source="workbench",
            )
            self._write_revision(
                conn,
                checkin_id=checkin_id,
                revision_no=1,
                rule_id=rule_id,
                version_no=version_no,
                prepared=prepared,
            )
            result = self.repo.load_revision(checkin_id, 1, conn=conn)
        return self._decorate_revision(result)

    def amend_checkin(
        self,
        checkin_id: str,
        payload: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        identity = self.repo.get_checkin_by_id(checkin_id)
        trade_date = identity["trade_date"]
        self._require_trade_date(trade_date)
        with self.repo.transaction() as conn:
            self.repo.lock_rule(conn, str(identity["rule_id"]))
            checkin = self.repo.get_checkin_by_id(checkin_id, conn=conn, for_update=True)
            if int(checkin["current_revision_no"]) != expected_revision:
                raise ConflictError("打卡已被其他操作修正，请刷新后重试")
            current = self.repo.load_revision(checkin_id, expected_revision, conn=conn)
            version_no = int(current["version_no"])
            version = self.repo.load_version(str(checkin["rule_id"]), version_no, conn=conn)
            prepared = self._prepare_checkin(
                payload, trade_date=trade_date, version=version, previous=current
            )
            new_revision = expected_revision + 1
            self._write_revision(
                conn,
                checkin_id=checkin_id,
                revision_no=new_revision,
                rule_id=str(checkin["rule_id"]),
                version_no=version_no,
                prepared=prepared,
            )
            self.repo.advance_checkin_revision(
                conn,
                checkin_id,
                expected_revision=expected_revision,
                new_revision=new_revision,
            )
            result = self.repo.load_revision(checkin_id, new_revision, conn=conn)
        return self._decorate_revision(result)

    def quick_no_operation(
        self, rule_id: str, trade_date: date, *, peak_positions: int | None = None
    ) -> dict[str, Any]:
        peak_positions = position_count(
            peak_positions, label="当日最大同时持仓数", minimum=0
        )
        self._require_trade_date(trade_date)
        with self.repo.transaction() as conn:
            self.repo.lock_rule(conn, rule_id)
            existing = self.repo.get_checkin_by_rule_date(
                rule_id, trade_date, conn=conn, for_update=True
            )
            if existing is not None:
                result = self.repo.load_revision(
                    str(existing["id"]), int(existing["current_revision_no"]), conn=conn
                )
                same_quick_submission = (
                    existing.get("submission_source") == "quick_no_operation"
                    and existing.get("status") == "submitted"
                    and int(existing["current_revision_no"]) == 1
                    and result.get("assessment") == "complied"
                    and bool(result.get("no_operation"))
                    and not result.get("operations")
                    and result.get("peak_positions") == peak_positions
                )
                if same_quick_submission:
                    result["idempotent"] = True
                    return self._decorate_revision(result)
                conflict = ConflictError("该规则在此交易日已有正式记录，请进入工作台处理")
                conflict.data = {
                    "checkin_id": str(existing["id"]),
                    "rule_id": rule_id,
                    "trade_date": str(trade_date),
                }
                raise conflict
            event = self.repo.effective_activation(rule_id, trade_date, conn=conn)
            if event is None or event["event_type"] == "archive":
                raise ValidationError("该日期尚无生效规则版本")
            checkin_id = self._id("tdc")
            version_no = int(event["version_no"])
            version = self.repo.load_version(rule_id, version_no, conn=conn)
            prepared = self._prepare_checkin(
                {"assessment": "complied", "no_operation": True, "operations": [],
                 "peak_positions": peak_positions},
                trade_date=trade_date, version=version,
            )
            self.repo.create_checkin(
                conn,
                checkin_id=checkin_id,
                rule_id=rule_id,
                trade_date=trade_date,
                submission_source="quick_no_operation",
            )
            self._write_revision(
                conn,
                checkin_id=checkin_id,
                revision_no=1,
                rule_id=rule_id,
                version_no=version_no,
                prepared=prepared,
            )
            result = self.repo.load_revision(checkin_id, 1, conn=conn)
            result["idempotent"] = False
        return self._decorate_revision(result)

    def get_checkin_context(self, rule_id: str, trade_date: date) -> dict[str, Any]:
        self._require_trade_date(trade_date)
        self.repo.get_rule(rule_id)
        existing = self.repo.get_checkin_by_rule_date(rule_id, trade_date)
        if existing is not None:
            revision = self.repo.load_revision(
                str(existing["id"]), int(existing["current_revision_no"])
            )
            version = self.repo.load_version(rule_id, int(revision["version_no"]))
            return {
                "trade_date": trade_date,
                "version": version,
                "checkin": self._decorate_revision(revision),
            }
        version = self.effective_version(rule_id, trade_date)
        if version is None:
            raise ValidationError("该日期尚无生效规则版本")
        return {"trade_date": trade_date, "version": version, "checkin": None}

    def get_revision(self, checkin_id: str, revision_no: int) -> dict[str, Any]:
        checkin = self.repo.get_checkin_by_id(checkin_id)
        revision = self.repo.load_revision(checkin_id, revision_no)
        revision["rule_version"] = self.repo.load_version(
            str(checkin["rule_id"]), int(revision["version_no"])
        )
        return self._decorate_revision(revision)

    def list_checkins(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "trade_date",
        sort_order: str = "desc",
        **filters: Any,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        assessment = filters.get("assessment")
        if assessment is not None and assessment not in {"complied", "partial", "breached"}:
            raise ValidationError("履约结果筛选值不正确")
        if sort_by != "trade_date":
            raise ValidationError("履约历史排序字段不正确")
        if sort_order not in {"asc", "desc"}:
            raise ValidationError("履约历史排序方向不正确")
        return self.repo.list_checkins(
            filters=filters,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def list_reasons(self) -> list[dict[str, Any]]:
        builtins = [
            {"code": code, "id": None, "name": name, "builtin": True}
            for code, name in BUILTIN_VIOLATION_REASONS
        ]
        custom = [
            {"code": None, "id": row["id"], "name": row["name"], "builtin": False}
            for row in self.repo.list_active_reasons()
        ]
        return builtins + custom

    def delete_reason(self, reason_id: str) -> None:
        self.repo.delete_reason(reason_id)

    def summary(self, trade_date: date) -> dict[str, Any]:
        self._require_trade_date(trade_date)
        rules = self.repo.checkin_summary(trade_date)
        completed = sum(row.get("checkin_id") is not None for row in rules)
        return {
            "trade_date": trade_date,
            "total": len(rules),
            "completed": completed,
            "pending": len(rules) - completed,
            "rules": rules,
        }
