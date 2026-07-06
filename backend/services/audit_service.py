"""审计日志服务：查询范围、默认窗口和上下文脱敏。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.auth.context import AuthContext
from backend.common.exceptions import AuthError, NotFoundError, ValidationError
from backend.common.logging import get_logger
from backend.config import get_effective_settings
from backend.storage.audit_repository import AuditRepository

log = get_logger("services.audit")

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
    "task_type",
    "job_name",
}
_SENSITIVE_TOKENS = ("password", "token", "secret", "captcha", "credential")
_TARGET_TYPE_LABELS = {
    "api": "接口",
    "async_task": "异步任务",
    "scheduled_job": "调度任务",
    "sys_user": "用户",
    "sys_role": "角色",
    "sys_menu": "菜单",
    "sys_resource": "功能点",
    "sys_tenant": "租户",
    "app_config": "系统设置",
    "dict_type": "字典类型",
    "dict_item": "字典项",
}


class AuditService:
    def __init__(self, repo: AuditRepository | None = None):
        self.repo = repo or AuditRepository()

    def list_logs(
        self,
        ctx: AuthContext,
        *,
        page: int,
        page_size: int,
        sort_by: str = "event_time",
        sort_order: str = "desc",
        **filters,
    ) -> dict:
        scoped = self._scoped_filters(ctx, filters)
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        data = self.repo.list_logs(
            filters=scoped,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        data["list"] = [self._sanitize_row(row) for row in data["list"]]
        data["size"] = data["page_size"]
        return data

    def summary(self, ctx: AuthContext, **filters) -> dict:
        scoped = self._scoped_filters(ctx, filters)
        data = self.repo.summary(filters=scoped)
        data["retention_days"] = get_effective_settings().audit.retention_days
        return data

    def detail(self, ctx: AuthContext, audit_id: str) -> dict:
        tenant_id = None if ctx.is_system else ctx.tenant_id
        row = self.repo.get(audit_id, tenant_id=tenant_id)
        if row is None:
            raise NotFoundError("审计日志不存在")
        return self._sanitize_row(row)

    def record_api_event(
        self,
        *,
        tenant_id: str | None,
        actor_user_id: str | None,
        resource_code: str | None,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int | None = None,
        ip: str | None = None,
    ) -> None:
        try:
            self.repo.record(
                event_category="api",
                event_type="api",
                action="request",
                result="success" if status_code < 400 else "failed",
                status="completed" if status_code < 400 else "failed",
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                resource_code=resource_code,
                target_type="api",
                target_id=f"{method} {path}",
                target_label=path,
                ip=ip,
                method=method,
                path=path,
                duration_ms=duration_ms,
                error_summary=None if status_code < 400 else f"HTTP {status_code}",
                context={"route": path, "permission_code": resource_code}
                if resource_code else {"route": path},
            )
        except Exception as e:  # noqa: BLE001
            log.warning("API 审计写入失败，已降级忽略: %s", e)

    def record_security_event(
        self,
        *,
        event_type: str,
        action: str,
        result: str,
        status: str,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        actor_account: str | None = None,
        resource_code: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        target_label: str | None = None,
        ip: str | None = None,
        method: str | None = None,
        path: str | None = None,
        error_summary: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.repo.record(
                event_category="security",
                event_type=event_type,
                action=action,
                result=result,
                status=status,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                actor_account=actor_account,
                resource_code=resource_code,
                target_type=target_type,
                target_id=target_id,
                target_label=target_label,
                ip=ip,
                method=method,
                path=path,
                error_summary=error_summary,
                context=context or {},
            )
        except Exception as e:  # noqa: BLE001
            log.warning("安全审计写入失败，已降级忽略: %s", e)

    def record_task_event(
        self,
        *,
        action: str,
        result: str,
        status: str,
        task_id: str,
        task_type: str | None = None,
        job_id: str | None = None,
        job_name: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        try:
            self.repo.record(
                event_category="task",
                event_type="task",
                action=action,
                result=result,
                status=status,
                target_type="async_task",
                target_id=task_id,
                target_label=job_name or task_type or task_id,
                error_summary=error_summary,
                context={
                    "task_id": task_id,
                    "job_id": job_id,
                    "action": action,
                },
            )
        except Exception as e:  # noqa: BLE001
            log.warning("任务审计写入失败，已降级忽略: %s", e)

    def record_scheduler_event(
        self,
        *,
        action: str,
        result: str,
        status: str,
        job_id: str,
        job_name: str | None = None,
        task_type: str | None = None,
        task_id: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        try:
            self.repo.record(
                event_category="task",
                event_type="scheduler",
                action=action,
                result=result,
                status=status,
                target_type="scheduled_job",
                target_id=job_id,
                target_label=job_name or job_id,
                error_summary=error_summary,
                context={
                    "job_id": job_id,
                    "task_id": task_id,
                    "task_type": task_type,
                    "job_name": job_name,
                    "action": action,
                },
            )
        except Exception as e:  # noqa: BLE001
            log.warning("调度审计写入失败，已降级忽略: %s", e)

    def record_rbac_event(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        target_label: str | None = None,
        resource_code: str | None = None,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        result: str = "success",
        status: str = "completed",
        affected_count: int = 1,
    ) -> None:
        try:
            self.repo.record(
                event_category="rbac",
                event_type="rbac",
                action=action,
                result=result,
                status=status,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                resource_code=resource_code,
                target_type=target_type,
                target_id=target_id,
                target_label=target_label,
                context={"action": action, "affected_count": affected_count},
            )
        except Exception as e:  # noqa: BLE001
            log.warning("RBAC 审计写入失败，已降级忽略: %s", e)

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
        out["target_description"] = cls._target_description(row)
        return out

    @staticmethod
    def _target_description(row: dict[str, Any]) -> str | None:
        parts: list[str] = []
        resource_name = row.get("resource_name")
        if resource_name:
            parts.append(str(resource_name))
        target_type = row.get("target_type")
        target_type_label = _TARGET_TYPE_LABELS.get(str(target_type)) if target_type else None
        if target_type_label and target_type_label not in parts:
            parts.append(target_type_label)
        if not parts and row.get("resource_code"):
            parts.append(str(row["resource_code"]))
        return " · ".join(parts) if parts else None

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
