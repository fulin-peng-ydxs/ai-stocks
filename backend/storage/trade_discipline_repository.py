"""交易纪律规则仓库（PostgreSQL）。

所有查询均显式携带 tenant_id + owner_user_id；跨 PG/DuckDB 的业务编排由服务层完成，
本仓库只提供可组合进同一 PG 事务的规则、草稿、正式版本和生命周期事件原语。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import psycopg
from psycopg import errors
from psycopg.rows import dict_row

from backend.auth.context import get_current_owner
from backend.common.exceptions import ConflictError, NotFoundError
from backend.storage.pg_client import PostgresClient, get_pg_client


class TradeDisciplineRepository:
    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ):
        self.pg = pg or get_pg_client()
        ctx_tenant, ctx_owner = get_current_owner()
        self.tenant_id = tenant_id or ctx_tenant
        self.owner_user_id = owner_user_id or ctx_owner

    @property
    def owner(self) -> tuple[str, str]:
        return self.tenant_id, self.owner_user_id

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        with self.pg.transaction() as conn:
            yield conn

    @staticmethod
    def _one(cur: psycopg.Cursor) -> dict[str, Any] | None:
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def lock_rule(self, conn: psycopg.Connection, rule_id: str) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM trade_discipline_rule "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s AND deleted_at IS NULL "
                "FOR UPDATE",
                [*self.owner, rule_id],
            )
            row = self._one(cur)
        if row is None:
            raise NotFoundError("交易纪律规则不存在")
        return row

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        df = self.pg.query_df(
            "SELECT * FROM trade_discipline_rule "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s AND deleted_at IS NULL",
            [*self.owner, rule_id],
        )
        if df.empty:
            raise NotFoundError("交易纪律规则不存在")
        return df.iloc[0].to_dict()

    def list_rules(self) -> list[dict[str, Any]]:
        df = self.pg.query_df(
            "SELECT r.*, d.draft_revision, d.proposed_name, d.source_version_no "
            "FROM trade_discipline_rule r LEFT JOIN trade_discipline_rule_draft d "
            "ON d.tenant_id=r.tenant_id AND d.owner_user_id=r.owner_user_id AND d.rule_id=r.id "
            "WHERE r.tenant_id=%s AND r.owner_user_id=%s AND r.deleted_at IS NULL "
            "ORDER BY r.updated_at DESC, r.id",
            list(self.owner),
        )
        return df.to_dict("records")

    def create_rule(self, conn: psycopg.Connection, rule_id: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trade_discipline_rule "
                "(id,tenant_id,owner_user_id,status) VALUES (%s,%s,%s,'unpublished')",
                [rule_id, *self.owner],
            )

    def load_draft(
        self, rule_id: str, *, conn: psycopg.Connection | None = None
    ) -> dict[str, Any] | None:
        sql = (
            "SELECT * FROM trade_discipline_rule_draft "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s"
        )
        if conn is None:
            df = self.pg.query_df(sql, [*self.owner, rule_id])
            if df.empty:
                return None
            header = df.iloc[0].to_dict()
        else:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, [*self.owner, rule_id])
                header = self._one(cur)
            if header is None:
                return None
        header["name"] = header.get("proposed_name")
        header["stock_rules"] = self._load_details(
            "trade_discipline_draft_stock_rule", rule_id, None, conn
        )
        header["action_rules"] = self._load_details(
            "trade_discipline_draft_action_rule", rule_id, None, conn
        )
        return header

    def load_version(
        self,
        rule_id: str,
        version_no: int,
        *,
        conn: psycopg.Connection | None = None,
    ) -> dict[str, Any]:
        sql = (
            "SELECT * FROM trade_discipline_rule_version "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s AND version_no=%s"
        )
        params = [*self.owner, rule_id, version_no]
        if conn is None:
            df = self.pg.query_df(sql, params)
            header = None if df.empty else df.iloc[0].to_dict()
        else:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                header = self._one(cur)
        if header is None:
            raise NotFoundError("交易纪律规则版本不存在")
        header["stock_rules"] = self._load_details(
            "trade_discipline_stock_rule", rule_id, version_no, conn
        )
        header["action_rules"] = self._load_details(
            "trade_discipline_action_rule", rule_id, version_no, conn
        )
        return header

    def _load_details(
        self,
        table: str,
        rule_id: str,
        version_no: int | None,
        conn: psycopg.Connection | None,
    ) -> list[dict[str, Any]]:
        version_clause = " AND version_no=%s" if version_no is not None else ""
        sql = (
            f"SELECT * FROM {table} WHERE tenant_id=%s AND owner_user_id=%s "
            f"AND rule_id=%s{version_clause} ORDER BY display_order, detail_id"
        )
        params: list[Any] = [*self.owner, rule_id]
        if version_no is not None:
            params.append(version_no)
        if conn is None:
            return self.pg.query_df(sql, params).to_dict("records")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def replace_draft(
        self,
        conn: psycopg.Connection,
        rule_id: str,
        draft: dict[str, Any],
        revision: int,
        source_version_no: int | None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trade_discipline_rule_draft "
                "(rule_id,tenant_id,owner_user_id,draft_revision,proposed_name,normalized_name,"
                "capital,source_version_no) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id,owner_user_id,rule_id) DO UPDATE SET "
                "draft_revision=EXCLUDED.draft_revision, proposed_name=EXCLUDED.proposed_name, "
                "normalized_name=EXCLUDED.normalized_name, capital=EXCLUDED.capital, "
                "source_version_no=EXCLUDED.source_version_no, updated_at=now()",
                [
                    rule_id,
                    *self.owner,
                    revision,
                    draft.get("name"),
                    draft.get("normalized_name"),
                    draft.get("capital"),
                    source_version_no,
                ],
            )
            for table in (
                "trade_discipline_draft_stock_rule",
                "trade_discipline_draft_action_rule",
            ):
                cur.execute(
                    f"DELETE FROM {table} WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
                    [*self.owner, rule_id],
                )
            for item in draft.get("stock_rules", []):
                cur.execute(
                    "INSERT INTO trade_discipline_draft_stock_rule "
                    "(rule_id,tenant_id,owner_user_id,detail_id,name,max_capital,content,display_order,enabled) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        rule_id,
                        *self.owner,
                        item["detail_id"],
                        item.get("name"),
                        item.get("max_capital"),
                        item.get("content"),
                        item["display_order"],
                        item["enabled"],
                    ],
                )
            for item in draft.get("action_rules", []):
                cur.execute(
                    "INSERT INTO trade_discipline_draft_action_rule "
                    "(rule_id,tenant_id,owner_user_id,detail_id,name,action_type,action_subtype,"
                    "content,display_order,enabled) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        rule_id,
                        *self.owner,
                        item["detail_id"],
                        item.get("name"),
                        item.get("action_type"),
                        item.get("action_subtype"),
                        item.get("content"),
                        item["display_order"],
                        item["enabled"],
                    ],
                )

    def sync_name_claims(
        self,
        conn: psycopg.Connection,
        rule_id: str,
        claims: dict[str, str],
    ) -> None:
        """同步一条规则当前应持有的正式/草稿名称；先占新名再释放旧名。"""
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                for normalized, claimed in claims.items():
                    cur.execute(
                        "INSERT INTO trade_discipline_rule_name_claim "
                        "(tenant_id,owner_user_id,normalized_name,rule_id,claimed_name) "
                        "VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT (tenant_id,owner_user_id,normalized_name) DO UPDATE SET "
                        "claimed_name=EXCLUDED.claimed_name, updated_at=now() "
                        "WHERE trade_discipline_rule_name_claim.rule_id=EXCLUDED.rule_id "
                        "RETURNING rule_id",
                        [*self.owner, normalized, rule_id, claimed],
                    )
                    row = cur.fetchone()
                    if row is None or row["rule_id"] != rule_id:
                        raise ConflictError(f"规则名称已被占用：{claimed}")
                if claims:
                    cur.execute(
                        "DELETE FROM trade_discipline_rule_name_claim "
                        "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s "
                        "AND normalized_name <> ALL(%s)",
                        [*self.owner, rule_id, list(claims)],
                    )
                else:
                    cur.execute(
                        "DELETE FROM trade_discipline_rule_name_claim "
                        "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
                        [*self.owner, rule_id],
                    )
        except errors.UniqueViolation as exc:
            raise ConflictError("规则名称已被占用") from exc

    def delete_draft(self, conn: psycopg.Connection, rule_id: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trade_discipline_rule_draft "
                "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s",
                [*self.owner, rule_id],
            )

    def insert_version(
        self,
        conn: psycopg.Connection,
        rule_id: str,
        version_no: int,
        draft: dict[str, Any],
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trade_discipline_rule_version "
                "(rule_id,tenant_id,owner_user_id,version_no,name,normalized_name,capital) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [
                    rule_id,
                    *self.owner,
                    version_no,
                    draft["name"],
                    draft["normalized_name"],
                    draft["capital"],
                ],
            )
            for item in draft["stock_rules"]:
                cur.execute(
                    "INSERT INTO trade_discipline_stock_rule "
                    "(rule_id,tenant_id,owner_user_id,version_no,detail_id,name,max_capital,content,"
                    "display_order,enabled) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        rule_id,
                        *self.owner,
                        version_no,
                        item["detail_id"],
                        item["name"],
                        item.get("max_capital"),
                        item["content"],
                        item["display_order"],
                        item["enabled"],
                    ],
                )
            for item in draft["action_rules"]:
                cur.execute(
                    "INSERT INTO trade_discipline_action_rule "
                    "(rule_id,tenant_id,owner_user_id,version_no,detail_id,name,action_type,"
                    "action_subtype,content,display_order,enabled) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        rule_id,
                        *self.owner,
                        version_no,
                        item["detail_id"],
                        item["name"],
                        item["action_type"],
                        item["action_subtype"],
                        item["content"],
                        item["display_order"],
                        item["enabled"],
                    ],
                )

    def allocate_event(self, conn: psycopg.Connection, rule_id: str) -> tuple[int, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE trade_discipline_rule SET next_activation_seq=next_activation_seq+1, "
                "updated_at=now() WHERE tenant_id=%s AND owner_user_id=%s AND id=%s "
                "RETURNING next_activation_seq, clock_timestamp() AS occurred_at",
                [*self.owner, rule_id],
            )
            row = self._one(cur)
        if row is None:
            raise NotFoundError("交易纪律规则不存在")
        return int(row["next_activation_seq"]), row["occurred_at"]

    def insert_activation(
        self,
        conn: psycopg.Connection,
        *,
        activation_id: str,
        rule_id: str,
        event_seq: int,
        event_type: str,
        version_no: int,
        occurred_at: Any,
        effective_date: date,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trade_discipline_rule_activation "
                "(id,tenant_id,owner_user_id,rule_id,event_seq,event_type,version_no,occurred_at,"
                "activated_at,effective_from_trade_date) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    activation_id,
                    *self.owner,
                    rule_id,
                    event_seq,
                    event_type,
                    version_no,
                    occurred_at,
                    occurred_at,
                    effective_date,
                ],
            )

    def update_lifecycle(
        self,
        conn: psycopg.Connection,
        rule_id: str,
        *,
        status: str,
        name: str,
        normalized_name: str,
        latest_version_no: int,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE trade_discipline_rule SET status=%s,name=%s,normalized_name=%s,"
                "latest_version_no=%s,updated_at=now() "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s",
                [status, name, normalized_name, latest_version_no, *self.owner, rule_id],
            )

    def effective_activation(self, rule_id: str, trade_date: date) -> dict[str, Any] | None:
        df = self.pg.query_df(
            "SELECT * FROM trade_discipline_rule_activation "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s "
            "AND effective_from_trade_date<=%s "
            "ORDER BY effective_from_trade_date DESC,event_seq DESC LIMIT 1",
            [*self.owner, rule_id, trade_date],
        )
        return None if df.empty else df.iloc[0].to_dict()

    def delete_unpublished(self, conn: psycopg.Connection, rule_id: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trade_discipline_rule r WHERE r.tenant_id=%s "
                "AND r.owner_user_id=%s AND r.id=%s AND r.status='unpublished' "
                "AND NOT EXISTS (SELECT 1 FROM trade_discipline_rule_version v "
                "WHERE v.tenant_id=r.tenant_id AND v.owner_user_id=r.owner_user_id "
                "AND v.rule_id=r.id) AND NOT EXISTS (SELECT 1 FROM trade_discipline_checkin c "
                "WHERE c.tenant_id=r.tenant_id AND c.owner_user_id=r.owner_user_id "
                "AND c.rule_id=r.id)",
                [*self.owner, rule_id],
            )
            if cur.rowcount != 1:
                raise ConflictError("仅无正式版本、无打卡的未发布规则可删除")
