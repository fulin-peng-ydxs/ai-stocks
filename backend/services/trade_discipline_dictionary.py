"""交易纪律字典消费：候选取全局字典，历史名称只取版本快照。"""

from backend.common.exceptions import ValidationError
from backend.storage.dict_repository import DictRepository

BUY_TYPES = "trade_discipline_buy_type"
SELL_TYPES = "trade_discipline_sell_type"
CONDITION_CATEGORIES = "trade_discipline_condition_category"
_LEGACY_TYPE_LABELS = {
    "open_position": "建仓",
    "add_position": "加仓",
    "liquidate": "清仓",
    "reduce_position": "减仓",
    "do_t": "做 T",
}
_LEGACY_CATEGORY_LABELS = {"basic": "基本条件", "risk": "风险排除", "technical": "技术形态"}


def action_snapshot_label(row: dict) -> str | None:
    """旧记录缺标签时使用当时的内置名称或原值，不读取现行字典改名。"""
    code = row.get("action_subtype")
    return row.get("action_subtype_label") or _LEGACY_TYPE_LABELS.get(code) or code


def category_snapshot_label(row: dict) -> str:
    code = "technical" if row["category"] == "other" else row["category"]
    return row.get("category_label") or _LEGACY_CATEGORY_LABELS.get(code) or code


class TradeDisciplineDictionary:
    def __init__(self, pg):
        self.repo = DictRepository(pg)

    def items(self, type_code: str) -> list[dict]:
        # 不吞数据库错误；字典类型停用或清空时不能偷偷恢复内置可选项。
        kind = self.repo.get_type(type_code)
        if not kind or not kind["enabled"]:
            return []
        return self.repo.enabled_items(type_code)

    def resolve(self, draft: dict, previous: dict | None = None) -> None:
        """新引用必须启用；原明细的旧引用可保留，客户端不能伪造名称快照。"""
        previous = previous or {}
        old_actions = {row["detail_id"]: row for row in previous.get("action_rules", [])}
        options = {
            side: {row["code"]: row["label"] for row in self.items(code)}
            for side, code in (("buy", BUY_TYPES), ("sell", SELL_TYPES))
        }
        for row in draft["action_rules"]:
            code, side = row.get("action_subtype"), row.get("action_type")
            old = old_actions.get(row["detail_id"], {})
            unchanged = (
                code and code == old.get("action_subtype") and side == old.get("action_type")
            )
            if unchanged:
                row["action_subtype_label"] = action_snapshot_label(old)
            elif code:
                label = options.get(side, {}).get(code)
                if label is None:
                    raise ValidationError(
                        "请选择当前方向已启用的买卖类型；新增类型请在数据字典维护"
                    )
                row["action_subtype_label"] = label
            else:
                row["action_subtype_label"] = None
        categories = {row["code"]: row["label"] for row in self.items(CONDITION_CATEGORIES)}
        old_stocks = {row["detail_id"]: row for row in previous.get("stock_rules", [])}
        for stock in draft["stock_rules"]:
            old_items = {
                row["item_id"]: row
                for row in old_stocks.get(stock["detail_id"], {}).get("checklist_items", [])
            }
            for row in stock["checklist_items"]:
                old = old_items.get(row["item_id"], {})
                old_category = (
                    "technical" if old.get("category") == "other" else old.get("category")
                )
                if row["category"] == old_category:
                    row["category_label"] = category_snapshot_label(old)
                elif row["category"] in categories:
                    row["category_label"] = categories[row["category"]]
                else:
                    raise ValidationError("请选择已启用的选股检查项分类；新增分类请在数据字典维护")
