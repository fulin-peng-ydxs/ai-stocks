"""用户偏好持久化仓库。

用于配置迁移后的非布局偏好和全局抽屉偏好。归属只来自请求上下文或显式构造参数，
HTTP API 不接受前端传入 userId/tenantId，避免把个人偏好表变成可越权写入入口。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from backend.auth.context import get_current_owner
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.storage.pg_ddl import DDL_USER_PREFERENCE

SCOPE_RE = re.compile(r"^(global|page|feature)$")
KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
MAX_VALUE_BYTES = 64 * 1024


class UserPreferenceValidationError(ValueError):
    """用户偏好校验失败。"""


def _validate_scope(scope: str) -> str:
    if not isinstance(scope, str) or not SCOPE_RE.fullmatch(scope):
        raise UserPreferenceValidationError("scope 仅允许 global/page/feature")
    return scope


def _validate_key(name: str, value: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return value
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        raise UserPreferenceValidationError(f"{name} 格式非法")
    return value


def _normalize_value(value: Any) -> str:
    if not isinstance(value, (dict, str, int, float, bool)) and value is not None:
        raise UserPreferenceValidationError("value 只允许 JSON 对象或标量")
    try:
        dumped = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError as e:
        raise UserPreferenceValidationError("value 必须是标准 JSON 值") from e
    if len(dumped.encode("utf-8")) > MAX_VALUE_BYTES:
        raise UserPreferenceValidationError("value 超过大小限制")
    return dumped


def _load_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class UserPreferenceRepo:
    """当前用户偏好仓库。"""

    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ):
        self.pg = pg or get_pg_client()
        self.pg.execute(DDL_USER_PREFERENCE)
        current_tenant, current_owner = get_current_owner()
        self.tenant_id = tenant_id or current_tenant
        self.owner_user_id = owner_user_id or current_owner

    def list(
        self,
        *,
        scope: str | None = None,
        page_key: str | None = None,
        pref_key: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["tenant_id=%s", "owner_user_id=%s"]
        params: list[Any] = [self.tenant_id, self.owner_user_id]
        if scope is not None:
            where.append("scope=%s")
            params.append(_validate_scope(scope))
        if page_key is not None:
            where.append("page_key=%s")
            params.append(_validate_key("page_key", page_key, allow_empty=True))
        if pref_key is not None:
            where.append("pref_key=%s")
            params.append(_validate_key("pref_key", pref_key))
        df = self.pg.query_df(
            "SELECT scope, page_key, pref_key, value, schema_version, updated_at "
            f"FROM user_preference WHERE {' AND '.join(where)} "
            "ORDER BY scope, page_key, pref_key",
            params,
        )
        return [self._row_to_pref(r) for _, r in df.iterrows()]

    def get(self, *, scope: str, page_key: str = "", pref_key: str) -> dict[str, Any] | None:
        rows = self.list(scope=scope, page_key=page_key, pref_key=pref_key)
        return rows[0] if rows else None

    def set(
        self,
        *,
        scope: str,
        page_key: str = "",
        pref_key: str,
        value: Any,
        schema_version: int = 1,
    ) -> dict[str, Any]:
        scope = _validate_scope(scope)
        page_key = _validate_key("page_key", page_key, allow_empty=True)
        pref_key = _validate_key("pref_key", pref_key)
        version = self._validate_schema_version(schema_version)
        dumped = _normalize_value(value)
        now = datetime.now()
        self.pg.execute(
            "INSERT INTO user_preference "
            "(tenant_id, owner_user_id, scope, page_key, pref_key, value, schema_version, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, scope, page_key, pref_key) DO UPDATE SET "
            "value=EXCLUDED.value, schema_version=EXCLUDED.schema_version, updated_at=EXCLUDED.updated_at",
            [
                self.tenant_id,
                self.owner_user_id,
                scope,
                page_key,
                pref_key,
                dumped,
                version,
                now,
            ],
        )
        return self.get(scope=scope, page_key=page_key, pref_key=pref_key) or {}

    def set_many(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            raise UserPreferenceValidationError("items 必须是数组")
        if len(items) > 100:
            raise UserPreferenceValidationError("单次最多保存 100 项偏好")
        saved: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                raise UserPreferenceValidationError("items 每项必须是对象")
            saved.append(
                self.set(
                    scope=item.get("scope", ""),
                    page_key=item.get("pageKey", item.get("page_key", "")) or "",
                    pref_key=item.get("prefKey", item.get("pref_key", "")),
                    value=item.get("value"),
                    schema_version=item.get("schemaVersion", item.get("schema_version", 1)),
                )
            )
        return saved

    @staticmethod
    def _validate_schema_version(schema_version: Any) -> int:
        if isinstance(schema_version, bool):
            raise UserPreferenceValidationError("schemaVersion 必须是正整数")
        try:
            version = int(schema_version)
        except (TypeError, ValueError):
            raise UserPreferenceValidationError("schemaVersion 必须是正整数")
        if version < 1:
            raise UserPreferenceValidationError("schemaVersion 必须是正整数")
        return version

    @staticmethod
    def _row_to_pref(row: Any) -> dict[str, Any]:
        return {
            "scope": row["scope"],
            "pageKey": row["page_key"],
            "prefKey": row["pref_key"],
            "value": _load_value(row["value"]),
            "schemaVersion": int(row["schema_version"] or 1),
            "updated_at": str(row["updated_at"]) if row["updated_at"] is not None else None,
        }
