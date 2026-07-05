"""审计日志服务：查询范围、默认窗口和上下文脱敏。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.auth.context import AuthContext
from backend.common.exceptions import AuthError, NotFoundError, ValidationError
from backend.config import get_effective_settings
from backend.storage.audit_repository import AuditRepository

_CONTEXT_ALLOW_KEYS = {
    "request_id",
    "permission_code",
    "task_id",
    "job_id",
    "action",
    "affected_count",
    "rate_limit_rule",
    "config_key",
    "config_keys",
    "route",
    "profile_ref",
    "data_scope",
}
_SENSITIVE_TOKENS = ("password", "token", "secret", "captcha", "credential")


class AuditService:
    def __init__(self, repo: AuditRepository | None = None):
        self.repo = repo or AuditRepository()

    def list_logs(
        self,
        ctx: AuthContext,
        *,
        page: int,
        page_size: int,
        **filters,
    ) -> dict:
        scoped = self._scoped_filters(ctx, filters)
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        data = self.repo.list_logs(filters=scoped, page=page, page_size=page_size)
        data["list"] = [self._sanitize_row(row) for row in data["list"]]
        data["size"] = data["page_size"]
        return data

    def summary(self, ctx: AuthContext, **filters) -> dict:
        return self.repo.summary(filters=self._scoped_filters(ctx, filters))

    def detail(self, ctx: AuthContext, audit_id: str) -> dict:
        tenant_id = None if ctx.is_system else ctx.tenant_id
        row = self.repo.get(audit_id, tenant_id=tenant_id)
        if row is None:
            raise NotFoundError("审计日志不存在")
        return self._sanitize_row(row)

    def _scoped_filters(self, ctx: AuthContext | None, filters: dict[str, Any]) -> dict[str, Any]:
        if ctx is None:
            raise AuthError("未登录")
        out = dict(filters)
        out["start_time"] = self._parse_time(out.get("start_time"))
        out["end_time"] = self._parse_time(out.get("end_time"))
        if out["start_time"] is None and out["end_time"] is None:
            retention_days = get_effective_settings().audit.retention_days
            out["end_time"] = datetime.now(timezone.utc)
            out["start_time"] = out["end_time"] - timedelta(days=retention_days)
        if not ctx.is_system:
            out["tenant_id"] = ctx.tenant_id
        return {k: v for k, v in out.items() if v not in (None, "")}

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError as e:
            raise ValidationError("时间格式不正确") from e

    @classmethod
    def _sanitize_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        context = row.get("context") if isinstance(row.get("context"), dict) else {}
        out["context"] = cls._sanitize_context(context)
        return out

    @classmethod
    def _sanitize_context(cls, context: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in context.items():
            k = str(key)
            lower = k.lower()
            if any(token in lower for token in _SENSITIVE_TOKENS):
                continue
            if k not in _CONTEXT_ALLOW_KEYS:
                continue
            clean[k] = cls._sanitize_value(value)
        return clean

    @classmethod
    def _sanitize_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                lower = str(key).lower()
                if any(token in lower for token in _SENSITIVE_TOKENS):
                    continue
                out[str(key)] = cls._sanitize_value(item)
            return out
        if isinstance(value, list):
            return [cls._sanitize_value(item) for item in value]
        return value
