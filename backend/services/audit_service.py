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
    "retention_days",
    "cutoff",
    "skipped",
    "reason",
}
_SENSITIVE_TOKENS = ("password", "token", "secret", "captcha", "credential")
_CHANGE_SENSITIVE_TOKENS = ("password", "token", "secret", "credential")
_REDACTED_CHANGE_VALUE = "已变更"
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
    "backtest_run": "回测记录",
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

    @classmethod
    def build_changes(
        cls,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        *,
        fields: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """构造字段级 before/after 变更，跳过未变化字段并脱敏敏感字段。"""
        before = before or {}
        after = after or {}
        keys = list(fields) if fields is not None else sorted(set(before) | set(after))
        changes: list[dict[str, Any]] = []
        for field in keys:
            old = before.get(field)
            new = after.get(field)
            if cls._change_value_equal(old, new):
                continue
            changes.append({
                "field": str(field),
                "before": cls._sanitize_change_value(field, old),
                "after": cls._sanitize_change_value(field, new),
            })
        return changes

    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, Any]:
        """清理超出审计保留期的历史日志。

        清理任务是平台维护动作，不能影响主业务启动；因此本方法捕获异常并返回结果。
        """
        try:
            retention_days = int(get_effective_settings().audit.retention_days)
        except Exception as e:  # noqa: BLE001
            result = {
                "ok": False,
                "skipped": True,
                "reason": "invalid_retention_config",
                "retention_days": None,
                "affected_count": 0,
                "cutoff": None,
                "error": str(e),
            }
            self._record_cleanup_event(result=result, status="skipped", error_summary=str(e))
            log.warning("审计日志清理跳过：保留期配置读取失败: %s", e)
            return result
        if retention_days <= 0:
            result = {
                "ok": True,
                "skipped": True,
                "reason": "invalid_retention_days",
                "retention_days": retention_days,
                "affected_count": 0,
                "cutoff": None,
            }
            self._record_cleanup_event(result=result, status="skipped")
            log.warning("审计日志清理跳过：保留期配置非法 retention_days=%s", retention_days)
            return result

        base = now or datetime.now(timezone.utc)
        cutoff = base - timedelta(days=retention_days)
        result = {
            "ok": True,
            "skipped": False,
            "reason": None,
            "retention_days": retention_days,
            "affected_count": 0,
            "cutoff": cutoff.isoformat(),
        }
        try:
            affected = self.repo.delete_before(cutoff)
            result["affected_count"] = affected
            self._record_cleanup_event(result=result, status="completed")
            log.info("审计日志清理完成：cutoff=%s affected=%s", cutoff.isoformat(), affected)
            return result
        except Exception as e:  # noqa: BLE001
            failed = dict(result)
            failed.update({"ok": False, "reason": "cleanup_failed", "error": str(e)})
            self._record_cleanup_event(result=failed, status="failed", error_summary=str(e))
            log.warning("审计日志清理失败，已降级忽略: %s", e)
            return failed

    def _record_cleanup_event(
        self,
        *,
        result: dict[str, Any],
        status: str,
        error_summary: str | None = None,
    ) -> None:
        self.repo.record(
            event_category="task",
            event_type="audit_cleanup",
            action="cleanup_expired",
            result="success" if status in {"completed", "skipped"} else "failed",
            status=status,
            target_type="audit_log",
            target_id="audit_log",
            target_label="审计日志保留期清理",
            error_summary=error_summary,
            context={
                "action": "cleanup_expired",
                "retention_days": result.get("retention_days"),
                "cutoff": result.get("cutoff"),
                "affected_count": result.get("affected_count", 0),
                "skipped": bool(result.get("skipped")),
                "reason": result.get("reason"),
            },
        )

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
        changes: list[dict[str, Any]] | None = None,
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
                changes=self._sanitize_changes(changes),
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
        changes: list[dict[str, Any]] | None = None,
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
                changes=self._sanitize_changes(changes),
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
        changes: list[dict[str, Any]] | None = None,
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
                changes=self._sanitize_changes(changes),
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
        changes: list[dict[str, Any]] | None = None,
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
                changes=self._sanitize_changes(changes),
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
        out["changes"] = cls._sanitize_changes(row.get("changes"))
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

    @classmethod
    def _sanitize_changes(cls, changes: Any) -> list[dict[str, Any]]:
        if not isinstance(changes, list):
            return []
        out: list[dict[str, Any]] = []
        for item in changes:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            if not field:
                continue
            out.append({
                "field": field,
                "before": cls._sanitize_change_value(field, item.get("before")),
                "after": cls._sanitize_change_value(field, item.get("after")),
            })
        return out

    @classmethod
    def _sanitize_change_value(cls, field: str, value: Any) -> Any:
        lower = str(field).lower()
        if any(token in lower for token in _CHANGE_SENSITIVE_TOKENS):
            return _REDACTED_CHANGE_VALUE
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                clean[str(key)] = cls._sanitize_change_value(f"{field}.{key}", item)
            return clean
        if isinstance(value, list):
            return [cls._sanitize_change_value(field, item) for item in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    @staticmethod
    def _change_value_equal(left: Any, right: Any) -> bool:
        try:
            if left == right:
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            if left != left and right != right:  # noqa: PLR0124
                return True
        except Exception:  # noqa: BLE001
            return False
        return False
