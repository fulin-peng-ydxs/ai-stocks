"""交易账本仓库：所有读写、冲突及修订引用均携带真实归属。"""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.storage.trade_discipline_repository import TradeDisciplineRepository


class TradeLedgerRepository(TradeDisciplineRepository):
    account_id = "default"

    @property
    def scope(self) -> tuple[str, str, str]:
        return (*self.owner, self.account_id)

    def account(self, conn: psycopg.Connection | None = None, *, lock: bool = False) -> dict:
        with self.pg.cursor_in(conn) as raw, raw.connection.cursor(row_factory=dict_row) as cur:
            if lock:
                cur.execute(
                    "INSERT INTO trade_discipline_account (tenant_id,owner_user_id,id) "
                    "VALUES (%s,%s,%s) ON CONFLICT (tenant_id,owner_user_id,id) DO NOTHING",
                    self.scope,
                )
            cur.execute(
                "SELECT * FROM trade_discipline_account "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s"
                + (" FOR UPDATE" if lock else ""), self.scope,
            )
            return dict(cur.fetchone() or {"initialized_on": None, "revision": 0})

    def day(self, trade_date: date, conn=None, revision: int | None = None) -> dict | None:
        with self.pg.cursor_in(conn) as raw, raw.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT d.trade_date,d.current_revision_no,d.withdrawn,r.revision_no,r.snapshot "
                "FROM trade_discipline_ledger_day d JOIN trade_discipline_ledger_revision r "
                "ON r.tenant_id=d.tenant_id AND r.owner_user_id=d.owner_user_id "
                "AND r.account_id=d.account_id AND r.trade_date=d.trade_date "
                "AND r.revision_no=COALESCE(%s,d.current_revision_no) "
                "WHERE d.tenant_id=%s AND d.owner_user_id=%s AND d.account_id=%s AND d.trade_date=%s",
                [revision, *self.scope, trade_date],
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def latest(self, conn=None, *, before: date | None = None) -> dict | None:
        with self.pg.cursor_in(conn) as raw, raw.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT trade_date FROM trade_discipline_ledger_day "
                "WHERE tenant_id=%s AND owner_user_id=%s AND account_id=%s AND NOT withdrawn "
                + ("AND trade_date<%s " if before else "") + "ORDER BY trade_date DESC LIMIT 1",
                [*self.scope, *([before] if before else [])],
            )
            row = cur.fetchone()
            return self.day(row["trade_date"], conn) if row else None

    def initialize(self, conn, trade_date: date, positions: list[dict], cash: str | None) -> None:
        conn.execute(
            "UPDATE trade_discipline_account SET initialized_on=%s,opening_positions=%s,"
            "opening_cash=%s,revision=revision+1,updated_at=clock_timestamp() "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
            [trade_date, Jsonb(positions), cash, *self.scope],
        )

    def request(self, request_id: str, conn) -> dict | None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT trade_date,revision_no,payload_hash,snapshot "
                "FROM trade_discipline_ledger_revision "
                "WHERE tenant_id=%s AND owner_user_id=%s AND account_id=%s AND request_id=%s",
                [*self.scope, request_id],
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def save(self, conn, trade_date, revision, request_id, payload_hash, snapshot):
        conn.execute(
            "INSERT INTO trade_discipline_ledger_day "
            "(tenant_id,owner_user_id,account_id,trade_date,current_revision_no) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,owner_user_id,account_id,trade_date) "
            "DO UPDATE SET current_revision_no=EXCLUDED.current_revision_no,withdrawn=FALSE,"
            "updated_at=clock_timestamp()", [*self.scope, trade_date, revision],
        )
        conn.execute(
            "INSERT INTO trade_discipline_ledger_revision "
            "(tenant_id,owner_user_id,account_id,trade_date,revision_no,request_id,payload_hash,snapshot) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [*self.scope, trade_date, revision, request_id, payload_hash, Jsonb(snapshot)],
        )
        conn.execute(
            "UPDATE trade_discipline_account SET revision=revision+1,updated_at=clock_timestamp() "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s", self.scope,
        )

    def history(
        self, *, limit: int = 20, offset: int = 0,
        assessment: str | None = None, stock_code: str | None = None,
        rule_id: str | None = None, date_from: date | None = None, date_to: date | None = None,
        sort_order: str = "desc",
        include_withdrawn: bool = False,
    ) -> dict[str, Any]:
        if sort_order not in {"asc", "desc"}:
            raise ValueError("交易日排序方向不正确")
        filters, parameters = [], list(self.scope)
        if not include_withdrawn:
            filters.append("NOT d.withdrawn")
        if assessment:
            filters.append("r.snapshot->>'assessment' IS NULL" if assessment == "pending"
                           else "r.snapshot->>'assessment'=%s")
            if assessment != "pending":
                parameters.append(assessment)
        if stock_code:
            filters.append("(EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot->'events') e "
                           "WHERE e->>'stock_code'=%s) OR EXISTS "
                           "(SELECT 1 FROM jsonb_array_elements(r.snapshot->'omissions') o "
                           "WHERE o->>'stock_code'=%s))")
            parameters.extend([stock_code, stock_code])
        if rule_id:
            filters.append("EXISTS (SELECT 1 FROM jsonb_array_elements(r.snapshot->'evaluations') e "
                           "WHERE e->>'rule_id'=%s)")
            parameters.append(rule_id)
        for value, operator in ((date_from, ">="), (date_to, "<=")):
            if value:
                filters.append(f"d.trade_date{operator}%s")
                parameters.append(value)
        base = (
            "FROM trade_discipline_ledger_day d JOIN trade_discipline_ledger_revision r "
            "ON r.tenant_id=d.tenant_id AND r.owner_user_id=d.owner_user_id "
            "AND r.account_id=d.account_id AND r.trade_date=d.trade_date "
            "AND r.revision_no=d.current_revision_no "
            "WHERE d.tenant_id=%s AND d.owner_user_id=%s AND d.account_id=%s "
            + ("AND " + " AND ".join(filters) if filters else "")
        )
        with self.pg.transaction() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT count(*) AS n " + base, parameters)
            total = cur.fetchone()["n"]
            cur.execute(
                "SELECT d.trade_date,d.current_revision_no,d.withdrawn,"
                "(r.snapshot-'events'-'positions'-'opening_positions'-'rules'-'omissions') "
                "|| jsonb_build_object('events','[]'::jsonb,'positions','[]'::jsonb,"
                "'opening_positions','[]'::jsonb,'rules','[]'::jsonb,'omissions','[]'::jsonb,"
                "'operation_count',(SELECT count(*) FROM jsonb_array_elements(r.snapshot->'events') e "
                "WHERE e->>'kind'='trade')) AS snapshot " + base +
                f" ORDER BY d.trade_date {sort_order.upper()} LIMIT %s OFFSET %s", [*parameters, limit, offset],
            )
            return {"total": total, "list": [dict(row) for row in cur.fetchall()]}
