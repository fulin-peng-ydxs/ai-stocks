"""PostgreSQL ledger/outbox persistence for limit-ladder date tasks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal

from backend.storage.pg_client import PostgresClient, get_pg_client

TaskSource = Literal["auto_first_load", "auto_invalid_refresh", "admin_recompute"]
ActorKind = Literal["system", "user"]
TaskStatus = Literal["requested", "running", "succeeded", "failed", "interrupted"]
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "interrupted"})


@dataclass(frozen=True, slots=True)
class LimitLadderTaskCommand:
    """Immutable identity and request snapshot captured before DuckDB task creation."""

    command_id: str
    trade_date: date
    source: TaskSource
    actor_kind: ActorKind
    actor_account: str
    rule_version: str
    tenant_id: str | None = None
    actor_user_id: str | None = None
    trigger_tenant_id: str | None = None
    trigger_user_id: str | None = None
    trigger_account: str | None = None
    request_ip: str | None = None
    request_method: str | None = None
    request_path: str | None = None
    request_id: str | None = None

    def validate(self) -> None:
        if self.actor_kind == "system" and (
            self.tenant_id is not None
            or self.actor_user_id is not None
            or self.actor_account != "system:limit-ladder"
        ):
            raise ValueError("system actor must use the isolated limit-ladder identity")
        if self.actor_kind == "user" and (not self.tenant_id or not self.actor_user_id):
            raise ValueError("user actor requires tenant_id and actor_user_id")
        if not self.actor_account.strip():
            raise ValueError("actor_account is required")


class LimitLadderTaskRepository:
    """Atomic ledger transitions with one idempotent audit outbox event per state."""

    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    def create_requested(self, command: LimitLadderTaskCommand) -> None:
        command.validate()
        payload = asdict(command)
        payload["trade_date"] = command.trade_date.isoformat()
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO limit_ladder_task_ledger (
                    command_id, trade_date, source, actor_kind, tenant_id,
                    actor_user_id, actor_account, trigger_tenant_id, trigger_user_id,
                    trigger_account, request_ip, request_method, request_path, request_id,
                    status, rule_version
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    'requested', %s
                )
                """,
                [
                    command.command_id, command.trade_date, command.source, command.actor_kind,
                    command.tenant_id, command.actor_user_id, command.actor_account,
                    command.trigger_tenant_id, command.trigger_user_id, command.trigger_account,
                    command.request_ip, command.request_method, command.request_path,
                    command.request_id, command.rule_version,
                ],
            )
            cur.execute(
                """
                INSERT INTO limit_ladder_audit_outbox (
                    command_id, event_type, source_event_key, payload
                ) VALUES (%s, 'requested', %s, %s::jsonb)
                ON CONFLICT (command_id, event_type) DO NOTHING
                """,
                [
                    command.command_id,
                    f"{command.command_id}:requested",
                    json.dumps({**payload, "status": "requested"}, ensure_ascii=False),
                ],
            )

    def get_active_for_date(self, trade_date: date) -> dict[str, Any] | None:
        df = self.pg.query_df(
            "SELECT * FROM limit_ladder_task_ledger "
            "WHERE trade_date=%s AND status IN ('requested','running') "
            "ORDER BY created_at LIMIT 1",
            [trade_date],
        )
        return None if df.empty else df.iloc[0].to_dict()

    def get(self, command_id: str) -> dict[str, Any] | None:
        df = self.pg.query_df(
            "SELECT * FROM limit_ladder_task_ledger WHERE command_id=%s",
            [command_id],
        )
        return None if df.empty else df.iloc[0].to_dict()

    def list_active(self) -> list[dict[str, Any]]:
        rows = self.pg.query_df(
            "SELECT * FROM limit_ladder_task_ledger "
            "WHERE status IN ('requested','running') ORDER BY created_at,command_id"
        )
        return rows.to_dict("records")

    def transition(
        self,
        *,
        command_id: str,
        status: TaskStatus,
        task_id: str | None = None,
        result_summary: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> bool:
        """Move forward once and enqueue an event from the frozen ledger identity."""
        if status == "requested":
            raise ValueError("requested is created by create_requested")
        summary_json = json.dumps(result_summary, ensure_ascii=False, default=str)
        allowed_from = ("requested",) if status == "running" else ("requested", "running")
        with self.pg.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE limit_ladder_task_ledger
                SET status=%s, task_id=COALESCE(%s, task_id), result_summary=%s::jsonb,
                    last_error=%s, updated_at=now()
                WHERE command_id=%s AND status = ANY(%s)
                """,
                [status, task_id, summary_json, last_error, command_id, list(allowed_from)],
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                """
                INSERT INTO limit_ladder_audit_outbox (
                    command_id, event_type, source_event_key, payload
                )
                SELECT command_id, %s, command_id || ':' || %s,
                    jsonb_build_object(
                        'command_id', command_id, 'task_id', task_id,
                        'trade_date', trade_date, 'source', source,
                        'actor_kind', actor_kind, 'tenant_id', tenant_id,
                        'actor_user_id', actor_user_id, 'actor_account', actor_account,
                        'trigger_tenant_id', trigger_tenant_id,
                        'trigger_user_id', trigger_user_id,
                        'trigger_account', trigger_account,
                        'request_ip', request_ip, 'request_method', request_method,
                        'request_path', request_path, 'request_id', request_id,
                        'status', status, 'rule_version', rule_version,
                        'result_summary', result_summary, 'last_error', last_error
                    )
                FROM limit_ladder_task_ledger WHERE command_id=%s
                ON CONFLICT (command_id, event_type) DO NOTHING
                """,
                [status, status, command_id],
            )
        return True

    def list_pending_outbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        df = self.pg.query_df(
            "SELECT * FROM limit_ladder_audit_outbox "
            "WHERE status='pending' AND (next_retry_at IS NULL OR next_retry_at<=now()) "
            "ORDER BY created_at LIMIT %s",
            [limit],
        )
        return df.to_dict("records")

    def mark_outbox_delivered(self, command_id: str, event_type: str) -> bool:
        affected = self.pg.execute(
            "UPDATE limit_ladder_audit_outbox SET status='delivered', delivered_at=now(), "
            "last_error=NULL WHERE command_id=%s AND event_type=%s AND status='pending'",
            [command_id, event_type],
        )
        return affected == 1

    def mark_outbox_retry(
        self,
        command_id: str,
        event_type: str,
        *,
        next_retry_at: datetime,
        error: str,
    ) -> bool:
        affected = self.pg.execute(
            "UPDATE limit_ladder_audit_outbox SET retry_count=retry_count+1, "
            "next_retry_at=%s, last_error=%s "
            "WHERE command_id=%s AND event_type=%s AND status='pending'",
            [next_retry_at, error, command_id, event_type],
        )
        return affected == 1
