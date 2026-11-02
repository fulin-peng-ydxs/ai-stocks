"""Cross-store coordination and reliable audit delivery for limit-ladder date tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pandas as pd

from backend.auth.context import AuthContext
from backend.common.request import trusted_client_ip
from backend.services.limit_ladder_snapshot import RULE_VERSION
from backend.services.limit_ladder_task_policy import (
    QUEUE_TIMEOUT_REASON,
    LimitLadderQueueTimeoutError,
    queue_deadline,
)
from backend.storage.audit_repository import AuditRepository
from backend.storage.limit_ladder_task_repository import (
    LimitLadderTaskCommand,
    LimitLadderTaskRepository,
    TaskSource,
)
from backend.storage.user_repository import UserRepository

_LOCK_NAME = "limit-ladder-task-reconcile-v1"
_MAX_CREATE_ATTEMPTS = 3
_ORPHAN_AFTER = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class ServerRequestSnapshot:
    ip: str | None
    method: str | None
    path: str | None
    request_id: str

    @classmethod
    def capture(cls, request: Any | None) -> ServerRequestSnapshot:
        return cls(
            ip=trusted_client_ip(request) if request is not None else None,
            method=str(request.method) if request is not None else None,
            path=str(request.url.path) if request is not None else None,
            request_id=uuid4().hex,
        )


@dataclass(frozen=True, slots=True)
class DateTaskResult:
    command_id: str
    task_id: str | None
    status: str
    reused: bool


class LimitLadderTaskCoordinator:
    """Create one active command per date and reconcile DuckDB execution to PG facts."""

    def __init__(
        self,
        *,
        repository: LimitLadderTaskRepository | None = None,
        task_service=None,
        audit_repository: AuditRepository | None = None,
        user_repository: UserRepository | None = None,
    ):
        self.repository = repository or LimitLadderTaskRepository()
        self.pg = self.repository.pg
        if task_service is None:
            from backend.services.async_task import AsyncTaskService

            task_service = AsyncTaskService()
        self.tasks = task_service
        self.audit = audit_repository or AuditRepository(self.pg)
        self.users = user_repository or UserRepository(self.pg)

    def ensure_date_task(
        self,
        trade_date: date,
        *,
        source: TaskSource,
        auth_context: AuthContext | None = None,
        request: Any | None = None,
    ) -> DateTaskResult:
        request_snapshot = ServerRequestSnapshot.capture(request)
        last_error: Exception | None = None
        for _ in range(_MAX_CREATE_ATTEMPTS):
            command = self._build_command(
                trade_date,
                source=source,
                auth_context=auth_context,
                request=request_snapshot,
            )
            try:
                self.repository.create_requested(command)
            except Exception as exc:  # noqa: BLE001 -- unique/storage errors share wrapper
                active = self.repository.get_active_for_date(trade_date)
                if active is not None:
                    duck_task = (
                        self._duck_task_for_command(str(active["command_id"]))
                        if getattr(self.tasks, "c", None) is not None
                        else None
                    )
                    mapped = None if duck_task is None else self._duck_status(duck_task)
                    if mapped in {"succeeded", "failed", "interrupted"}:
                        self.repository.transition(
                            command_id=str(active["command_id"]),
                            status=mapped,
                            task_id=str(duck_task["id"]),
                            result_summary=self._task_summary(duck_task),
                            last_error=(
                                str(duck_task.get("message") or "")
                                if mapped in {"failed", "interrupted"}
                                else None
                            ),
                        )
                        if mapped in {"failed", "interrupted"}:
                            from backend.services.limit_ladder_snapshot import (
                                LimitLadderSnapshotService,
                            )

                            LimitLadderSnapshotService(
                                getattr(self.tasks, "market", self.tasks.c)
                            ).recover_interrupted_task(
                                str(duck_task["id"]),
                                summary=(
                                    str(duck_task.get("message") or "")
                                    or "计算任务已中断，等待重新创建"
                                ),
                            )
                        self.dispatch_outbox()
                        continue
                    if mapped is None and str(active["status"]) == "requested":
                        task_id = self._submit_requested(active)
                        if task_id is not None:
                            return DateTaskResult(str(active["command_id"]), task_id, "requested", True)
                        active = self.repository.get(str(active["command_id"]))
                    return self._result(active, reused=True)
                last_error = exc
                continue

            self.dispatch_outbox()
            task_id = self._submit_requested(self.repository.get(command.command_id))
            latest = self.repository.get(command.command_id)
            return DateTaskResult(command.command_id, task_id, str(latest["status"]), False)
        if last_error is not None:
            raise last_error
        raise RuntimeError("failed to acquire limit ladder date task slot")

    def _submit_requested(self, command: dict[str, Any]) -> str | None:
        """复用运行态创建幂等与单写门禁；繁忙时保留 PG 请求供定时协调器派发。"""
        from backend.services.async_task import ConcurrentTaskError

        command_id = str(command["command_id"])
        source = str(command["source"])
        try:
            return self.tasks.create(
                "limit_ladder_recompute",
                {
                    "command_id": command_id,
                    "trade_date": str(command["trade_date"]),
                    "source": source,
                    "queue_deadline_at": queue_deadline(command["created_at"]).isoformat(),
                },
                trigger_source="manual" if source == "admin_recompute" else "system",
                job_name=self._source_label(source),
                trigger_event_id=command_id,
            )
        except ConcurrentTaskError:
            # 等待不占用 async_task 的 pending 写槽位，不产生失败审计；重启后仍能派发。
            return None
        except LimitLadderQueueTimeoutError:
            self.repository.transition(
                command_id=command_id, status="failed", last_error=QUEUE_TIMEOUT_REASON,
            )
            self.dispatch_outbox()
            return None
        except Exception as exc:
            self.repository.transition(command_id=command_id, status="failed", last_error=str(exc))
            self.dispatch_outbox()
            raise

    def mark_running(self, command_id: str, task_id: str) -> bool:
        changed = self.repository.transition(
            command_id=command_id,
            status="running",
            task_id=task_id,
        )
        self.dispatch_outbox()
        return changed

    def mark_terminal(
        self,
        command_id: str,
        *,
        status: str,
        task_id: str,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        if status not in {"succeeded", "failed", "interrupted"}:
            raise ValueError(f"unsupported limit ladder terminal status: {status}")
        changed = self.repository.transition(
            command_id=command_id,
            status=status,
            task_id=task_id,
            result_summary=summary,
            last_error=error,
        )
        self.dispatch_outbox()
        return changed

    def dispatch_outbox(self, *, limit: int = 100) -> dict[str, int]:
        delivered = failed = 0
        for row in self.repository.list_pending_outbox(limit=limit):
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = {}
            payload = payload if isinstance(payload, dict) else {}
            try:
                event_type = str(row["event_type"])
                audit_id = self.audit.record(
                    event_category="task",
                    event_type="limit_ladder_task",
                    resource_code="limit-ladder:recompute",
                    action=event_type,
                    result="success" if event_type in {"requested", "running", "succeeded"} else "failed",
                    status=event_type,
                    tenant_id=payload.get("tenant_id"),
                    actor_user_id=payload.get("actor_user_id"),
                    actor_account=payload.get("actor_account"),
                    target_type="async_task",
                    target_id=payload.get("task_id") or payload.get("command_id"),
                    target_label=str(payload.get("trade_date") or ""),
                    ip=payload.get("request_ip"),
                    method=payload.get("request_method"),
                    path=payload.get("request_path"),
                    error_summary=payload.get("last_error"),
                    context=payload,
                    source_event_key=str(row["source_event_key"]),
                )
                if audit_id is None:
                    raise RuntimeError("audit repository did not persist the outbox event")
                if self.repository.mark_outbox_delivered(
                    str(row["command_id"]), event_type
                ):
                    delivered += 1
            except Exception as exc:  # noqa: BLE001 -- durable retry must catch sink failures
                retry_count = int(row.get("retry_count") or 0) + 1
                delay = min(3600, 30 * (2 ** min(retry_count, 7)))
                self.repository.mark_outbox_retry(
                    str(row["command_id"]),
                    str(row["event_type"]),
                    next_retry_at=datetime.now(UTC) + timedelta(seconds=delay),
                    error=str(exc)[:1000],
                )
                failed += 1
        return {"delivered": delivered, "failed": failed}

    def reconcile(
        self,
        *,
        startup_at: datetime | None = None,
        now: datetime | None = None,
    ) -> dict[str, int | bool]:
        now = now or datetime.now(UTC)
        cutoff = startup_at or (now - _ORPHAN_AFTER)
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", [_LOCK_NAME])
            if not bool(cur.fetchone()[0]):
                return {
                    "locked": False,
                    "updated": 0,
                    "snapshot_recovered": 0,
                    "delivered": 0,
                    "failed": 0,
                }
            updated = 0
            snapshot_recovered = 0
            for command in self.repository.list_active():
                duck_task = self._duck_task_for_command(str(command["command_id"]))
                if duck_task is not None:
                    mapped = self._duck_status(duck_task)
                    if mapped == "running":
                        updated += int(self.repository.transition(
                            command_id=str(command["command_id"]),
                            status="running",
                            task_id=str(duck_task["id"]),
                        ))
                    elif mapped is not None:
                        updated += int(self.repository.transition(
                            command_id=str(command["command_id"]),
                            status=mapped,
                            task_id=str(duck_task["id"]),
                            result_summary=self._task_summary(duck_task),
                            last_error=(
                                str(duck_task.get("message") or "")
                                if mapped in {"failed", "interrupted"}
                                else None
                            ),
                        ))
                        if mapped in {"failed", "interrupted"}:
                            from backend.services.limit_ladder_snapshot import (
                                LimitLadderSnapshotService,
                            )

                            snapshot_recovered += LimitLadderSnapshotService(
                                getattr(self.tasks, "market", self.tasks.c)
                            ).recover_interrupted_task(
                                str(duck_task["id"]),
                                summary=(
                                    str(duck_task.get("message") or "")
                                    or "计算任务已中断，等待重新创建"
                                ),
                            )
                    continue
                if str(command["status"]) == "requested":
                    # requested 没有运行态行表示尚未获得写槽位，不适用孤儿超时。
                    # create() 以 command_id 幂等，和首个请求并发也不会创建双份任务。
                    try:
                        task_id = self._submit_requested(command)
                        updated += int(task_id is not None)
                    except Exception:  # 已记录真实失败，继续协调其它日期。
                        updated += 1
                    continue
                created_at = self._as_datetime(command.get("created_at"))
                if created_at is not None and created_at <= cutoff:
                    updated += int(self.repository.transition(
                        command_id=str(command["command_id"]),
                        status="failed",
                        last_error="task runtime row missing during reconciliation",
                    ))
            dispatch = self.dispatch_outbox()
            return {
                "locked": True,
                "updated": updated,
                "snapshot_recovered": snapshot_recovered,
                "delivered": dispatch["delivered"],
                "failed": dispatch["failed"],
            }

    def _build_command(
        self,
        trade_date: date,
        *,
        source: TaskSource,
        auth_context: AuthContext | None,
        request: ServerRequestSnapshot,
    ) -> LimitLadderTaskCommand:
        if source not in {"auto_first_load", "auto_invalid_refresh", "admin_recompute"}:
            raise ValueError(f"unsupported limit ladder task source: {source}")
        actor_kind = "system"
        tenant_id = actor_user_id = None
        actor_account = "system:limit-ladder"
        trigger_tenant_id = trigger_user_id = trigger_account = None
        if source == "admin_recompute":
            if auth_context is None or not auth_context.is_system:
                raise ValueError("admin recompute requires a system authentication context")
            user = self._resolved_user(auth_context)
            actor_kind = "user"
            tenant_id = auth_context.tenant_id
            actor_user_id = auth_context.user_id
            actor_account = str(user["account"])
        elif auth_context is not None:
            user = self._resolved_user(auth_context)
            trigger_tenant_id = auth_context.tenant_id
            trigger_user_id = auth_context.user_id
            trigger_account = str(user["account"])
        return LimitLadderTaskCommand(
            command_id=uuid4().hex,
            trade_date=trade_date,
            source=source,
            actor_kind=actor_kind,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_account=actor_account,
            trigger_tenant_id=trigger_tenant_id,
            trigger_user_id=trigger_user_id,
            trigger_account=trigger_account,
            request_ip=request.ip,
            request_method=request.method,
            request_path=request.path,
            request_id=request.request_id,
            rule_version=RULE_VERSION,
        )

    def _resolved_user(self, context: AuthContext) -> dict:
        user = self.users.get_by_id(context.user_id)
        if user is None or str(user.get("tenant_id")) != context.tenant_id:
            raise ValueError("authenticated user identity cannot be resolved from PostgreSQL")
        account = str(user.get("account") or "").strip()
        if not account:
            raise ValueError("authenticated user account is empty")
        return user

    def _duck_task_for_command(self, command_id: str) -> dict | None:
        rows = self.tasks.c.query_df(
            "SELECT * FROM async_task WHERE trigger_event_id=? ORDER BY created_at LIMIT 1",
            [command_id],
        )
        if rows.empty:
            return None
        from backend.services.async_task import _row

        return _row(rows.iloc[0])

    @staticmethod
    def _duck_status(task: dict[str, Any]) -> str | None:
        status = {
            "pending": "running",
            "running": "running",
            "done": "succeeded",
            "failed": "failed",
            "interrupted": "interrupted",
        }.get(str(task.get("status")))
        if status != "succeeded":
            return status
        result = task.get("result")
        if isinstance(result, dict) and (
            result.get("ok") is False
            or result.get("snapshot_status") not in {None, "valid"}
        ):
            return "failed"
        return "succeeded"

    @staticmethod
    def _task_summary(task: dict) -> dict[str, Any] | None:
        result = task.get("result")
        return result if isinstance(result, dict) else None

    @staticmethod
    def _as_datetime(value) -> datetime | None:
        if value is None or pd.isna(value):
            return None
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.to_pydatetime()

    @staticmethod
    def _result(row: dict, *, reused: bool) -> DateTaskResult:
        task_id = row.get("task_id")
        return DateTaskResult(
            command_id=str(row["command_id"]),
            task_id=None if task_id is None or pd.isna(task_id) else str(task_id),
            status=str(row["status"]),
            reused=reused,
        )

    @staticmethod
    def _source_label(source: str) -> str:
        return {
            "auto_first_load": "连板天梯自动首算",
            "auto_invalid_refresh": "连板天梯失效刷新",
            "admin_recompute": "连板天梯管理员重算",
        }[source]
