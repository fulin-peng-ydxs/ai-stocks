"""交易纪律规则生命周期服务。"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.trade_discipline_repository import TradeDisciplineRepository

SHANGHAI = ZoneInfo("Asia/Shanghai")
_ACTION_SUBTYPES = {
    "buy": {"open_position", "add_position"},
    "sell": {"liquidate", "do_t"},
}


def normalize_rule_name(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    display = unicodedata.normalize("NFKC", str(value)).strip()
    if not display:
        return None, None
    return display, display.casefold()


class TradeDisciplineService:
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
        return result

    def _prepare_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        name, normalized = normalize_rule_name(payload.get("name"))
        prepared: dict[str, Any] = {
            "name": name,
            "normalized_name": normalized,
            "capital": self._money(payload.get("capital")),
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
                    item["max_capital"] = self._money(item.get("max_capital"))
                    order_key = ("stock", item["display_order"])
                else:
                    action_type = item.get("action_type") or None
                    subtype = item.get("action_subtype") or None
                    item["action_type"] = action_type
                    item["action_subtype"] = subtype
                    if action_type is not None and action_type not in _ACTION_SUBTYPES:
                        raise ValidationError("操作方向不正确")
                    if subtype is not None and subtype not in set().union(
                        *_ACTION_SUBTYPES.values()
                    ):
                        raise ValidationError("操作类型不正确")
                    if (
                        action_type is not None
                        and subtype is not None
                        and subtype not in _ACTION_SUBTYPES[action_type]
                    ):
                        raise ValidationError("操作方向与类型不匹配")
                    order_key = (action_type, item["display_order"])
                if order_key in seen_order:
                    raise ValidationError("同类规则明细顺序不能重复")
                seen_order.add(order_key)
                prepared[kind].append(item)
        return prepared

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
            if not item.get("name") or not str(item.get("content") or "").strip():
                raise ValidationError("选股规则名称和内容不能为空")
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
            if action_type not in _ACTION_SUBTYPES or subtype not in _ACTION_SUBTYPES[action_type]:
                raise ValidationError("操作方向与类型不匹配")

    @staticmethod
    def _fingerprint(data: dict[str, Any]) -> tuple[Any, ...]:
        stocks = tuple(
            (
                x["detail_id"],
                x.get("name"),
                x.get("max_capital"),
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
        return data.get("name"), data.get("capital"), stocks, actions

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
                    "stock_rules": source_data["stock_rules"],
                    "action_rules": source_data["action_rules"],
                }
            )
            draft["normalized_name"] = normalized
            copied_id = self._id("tdr")
            self.repo.create_rule(conn, copied_id)
            copied = self.repo.lock_rule(conn, copied_id)
            self.repo.sync_name_claims(conn, copied_id, self._claims(copied, draft))
            self.repo.replace_draft(conn, copied_id, draft, 1, None)
        return self.get_rule(copied_id)

    def delete_rule(self, rule_id: str) -> None:
        with self.repo.transaction() as conn:
            self.repo.lock_rule(conn, rule_id)
            self.repo.delete_unpublished(conn, rule_id)
