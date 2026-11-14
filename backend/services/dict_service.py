"""数据字典服务：CRUD、不可变 code、兜底枚举和变更审计。"""

from __future__ import annotations

import re
from typing import Any

from backend.auth.context import get_current_context
from backend.common.exceptions import NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.services.audit_service import AuditService
from backend.storage.dict_repository import DictRepository
from backend.storage.pg_ddl import _SEED_DICT_ITEMS

_CODE_RE = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
log = get_logger("services.dict")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_FALLBACK_ITEMS: dict[str, list[dict]] = {}
for _type_code, _code, _label, _sort, _color in _SEED_DICT_ITEMS:
    _FALLBACK_ITEMS.setdefault(_type_code, []).append({
        "type_code": _type_code,
        "code": _code,
        "label": _label,
        "color": _color,
        "enabled": True,
        "sort": _sort,
        "remark": None,
    })
for _items in _FALLBACK_ITEMS.values():
    _items.sort(key=lambda item: (item["sort"], item["code"]))


class DictService:
    def __init__(self, repo: DictRepository | None = None):
        self.repo = repo or DictRepository()

    def list_types(self, *, q: str | None, enabled: bool | None, page: int, size: int) -> dict:
        return self.repo.list_types(q=q, enabled=enabled, page=page, size=size)

    def create_type(
        self,
        *,
        code: str,
        name: str,
        enabled: bool = True,
        sort: int = 100,
        remark: str | None = None,
    ) -> dict:
        code = self._norm_code(code, "类型 code")
        name = self._required(name, "类型名称")
        if self.repo.get_type(code):
            raise ValidationError("字典类型 code 已存在")
        row = self.repo.create_type(code=code, name=name, enabled=enabled, sort=sort, remark=remark)
        self._audit("type_create", "dict_type", code, name)
        return row

    def update_type(
        self,
        code: str,
        *,
        body_code: str | None,
        name: str,
        enabled: bool,
        sort: int,
        remark: str | None,
    ) -> dict:
        code = self._norm_code(code, "类型 code")
        if body_code is not None and body_code != code:
            raise ValidationError("字典类型 code 创建后不可修改")
        cur = self._load_type(code)
        row = self.repo.update_type(
            code,
            name=self._required(name, "类型名称"),
            enabled=enabled,
            sort=sort,
            remark=remark,
        )
        self._audit(
            "type_update",
            "dict_type",
            code,
            row.get("name") or cur["name"],
            changes=AuditService.build_changes(
                cur,
                row,
                fields=("name", "enabled", "sort", "remark"),
            ),
        )
        return row

    def delete_type(self, code: str) -> None:
        code = self._norm_code(code, "类型 code")
        cur = self._load_type(code)
        if self.repo.count_items(code) > 0:
            raise ValidationError("该字典类型下仍有字典项，不能删除")
        self.repo.delete_type(code)
        self._audit("type_delete", "dict_type", code, cur["name"])

    def list_items(
        self,
        *,
        type_code: str,
        q: str | None,
        enabled: bool | None,
        page: int,
        size: int,
        sort_by: str = "sort",
        sort_order: str = "asc",
    ) -> dict:
        type_code = self._norm_code(type_code, "类型 code")
        self._load_type(type_code)
        return self.repo.list_items(
            type_code=type_code,
            q=q,
            enabled=enabled,
            page=page,
            size=size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def get_enabled_items(self, type_code: str) -> dict:
        raw_type_code = (type_code or "").strip()
        try:
            type_code = self._norm_code(type_code, "类型 code")
            kind = self.repo.get_type(type_code)
            if kind:
                items = self.repo.enabled_items(type_code) if kind["enabled"] else []
                return {
                    "type_code": type_code,
                    "items": items,
                    "fallback": False,
                    "version": self.repo.version(type_code),
                }
        except Exception:  # noqa: BLE001
            type_code = raw_type_code
        return {
            "type_code": type_code,
            "items": [dict(item) for item in _FALLBACK_ITEMS.get(type_code, [])],
            "fallback": True,
            "version": "builtin",
        }

    def create_item(
        self,
        *,
        type_code: str,
        code: str,
        label: str,
        color: str | None = None,
        enabled: bool = True,
        sort: int = 100,
        remark: str | None = None,
    ) -> dict:
        type_code = self._norm_code(type_code, "类型 code")
        code = self._norm_code(code, "字典项 code")
        self._load_type(type_code)
        if type_code == "trade_discipline_condition_category" and code in {"notes", "other"}:
            raise ValidationError("notes 和 other 为历史兼容保留编码，请使用其他分类编码")
        if self.repo.get_item(type_code, code):
            raise ValidationError("字典项 code 已存在")
        row = self.repo.create_item(
            type_code=type_code,
            code=code,
            label=self._required(label, "字典项标签"),
            color=self._norm_color(color),
            enabled=enabled,
            sort=sort,
            remark=remark,
        )
        self._audit("item_create", "dict_item", f"{type_code}:{code}", row["label"])
        return row

    def update_item(
        self,
        type_code: str,
        code: str,
        *,
        body_type_code: str | None,
        body_code: str | None,
        label: str,
        color: str | None,
        enabled: bool,
        sort: int,
        remark: str | None,
    ) -> dict:
        type_code = self._norm_code(type_code, "类型 code")
        code = self._norm_code(code, "字典项 code")
        if body_type_code is not None and body_type_code != type_code:
            raise ValidationError("字典项 type_code 创建后不可修改")
        if body_code is not None and body_code != code:
            raise ValidationError("字典项 code 创建后不可修改")
        cur = self._load_item(type_code, code)
        row = self.repo.update_item(
            type_code,
            code,
            label=self._required(label, "字典项标签"),
            color=self._norm_color(color),
            enabled=enabled,
            sort=sort,
            remark=remark,
        )
        self._audit(
            "item_update",
            "dict_item",
            f"{type_code}:{code}",
            row["label"],
            changes=AuditService.build_changes(
                cur,
                row,
                fields=("label", "color", "enabled", "sort", "remark"),
            ),
        )
        return row

    def delete_item(self, type_code: str, code: str) -> None:
        type_code = self._norm_code(type_code, "类型 code")
        code = self._norm_code(code, "字典项 code")
        cur = self._load_item(type_code, code)
        self.repo.delete_item(type_code, code)
        self._audit("item_delete", "dict_item", f"{type_code}:{code}", cur["label"])

    def _load_type(self, code: str) -> dict:
        row = self.repo.get_type(code)
        if row is None:
            raise NotFoundError("字典类型不存在")
        return row

    def _load_item(self, type_code: str, code: str) -> dict:
        row = self.repo.get_item(type_code, code)
        if row is None:
            raise NotFoundError("字典项不存在")
        return row

    @staticmethod
    def _norm_code(value: str, label: str) -> str:
        code = (value or "").strip()
        if not _CODE_RE.fullmatch(code):
            raise ValidationError(
                f"{label} 只能使用小写字母、数字、下划线、"
                "短横线或冒号，且以字母开头"
            )
        return code

    @staticmethod
    def _required(value: str | None, label: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValidationError(f"请填写{label}")
        return text

    @staticmethod
    def _norm_color(value: str | None) -> str | None:
        color = (value or "").strip()
        if not color:
            return None
        if not _COLOR_RE.fullmatch(color):
            raise ValidationError("字典项颜色只能使用 #RRGGBB 格式")
        return color.upper()

    @staticmethod
    def _audit(
        action: str,
        target_type: str,
        target_id: str,
        target_label: str | None,
        *,
        changes: list[dict[str, Any]] | None = None,
    ) -> None:
        try:
            ctx = get_current_context()
            AuditService().repo.record(
                event_category="dict",
                event_type="dict",
                action=action,
                result="success",
                status="completed",
                tenant_id=ctx.tenant_id if ctx else None,
                actor_user_id=ctx.user_id if ctx else None,
                resource_code=(
                    "dict:item-manage" if target_type == "dict_item" else "dict:type-manage"
                ),
                target_type=target_type,
                target_id=target_id,
                target_label=target_label,
                context={"action": action, "affected_count": 1},
                changes=changes,
            )
        except Exception as exc:  # 审计失败不回滚已提交的字典变更
            log.warning("字典变更审计写入失败：%s", exc, exc_info=True)
