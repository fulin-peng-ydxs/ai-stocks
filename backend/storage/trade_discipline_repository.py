"""交易纪律规则仓库（PostgreSQL）。

所有查询均显式携带 tenant_id + owner_user_id；跨 PG/DuckDB 的业务编排由服务层完成，
本仓库只提供可组合进同一 PG 事务的规则、草稿、正式版本和生命周期事件原语。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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

    @staticmethod
    def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
        """把 pandas 为 SQL NULL 生成的 NaN/NaT 还原为 API 可序列化的 None。"""
        return [
            {key: None if value is None or pd.isna(value) else value for key, value in row.items()}
            for row in df.to_dict("records")
        ]

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

    def list_action_subtypes(self) -> list[dict[str, Any]]:
        """返回当前归属者已保存的买卖类型候选，归一化名称在数据库中唯一。"""
        df = self.pg.query_df(
            "SELECT name,action_type FROM trade_discipline_action_subtype "
            "WHERE tenant_id=%s AND owner_user_id=%s ORDER BY action_type,name",
            list(self.owner),
        )
        return self._records(df)

    def delete_action_subtype(self, normalized_name: str) -> dict[str, Any]:
        """删除当前归属者的自定义候选；规则与版本保存名称快照，不做级联修改。"""
        with self.transaction() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "DELETE FROM trade_discipline_action_subtype "
                "WHERE tenant_id=%s AND owner_user_id=%s AND normalized_name=%s "
                "RETURNING name,action_type",
                [*self.owner, normalized_name],
            )
            row = self._one(cur)
        if row is None:
            raise NotFoundError("自定义买卖类型不存在或已删除")
        return row

    def claim_action_subtypes(
        self,
        conn: psycopg.Connection,
        items: list[dict[str, str]],
    ) -> None:
        """事务内登记类型；同一归一化名称不能同时属于买入和卖出。"""
        with conn.cursor(row_factory=dict_row) as cur:
            for item in items:
                cur.execute(
                    "INSERT INTO trade_discipline_action_subtype "
                    "(tenant_id,owner_user_id,normalized_name,name,action_type) "
                    "VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (tenant_id,owner_user_id,normalized_name) DO UPDATE SET "
                    "name=EXCLUDED.name,updated_at=now() "
                    "WHERE trade_discipline_action_subtype.action_type=EXCLUDED.action_type "
                    "RETURNING action_type",
                    [*self.owner, item["normalized_name"], item["name"], item["action_type"]],
                )
                if cur.fetchone() is None:
                    raise ConflictError(f"类型名称已用于另一方向：{item['name']}")

    def list_rules_with_lifecycle(
        self,
        trade_date: date | None,
        *,
        rule_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """批量返回规则、最新管理事件和目标日有效事件，避免 API 按规则 N+1 查询。"""
        rule_filter = " AND r.id=%s" if rule_id is not None else ""
        params: list[Any] = [
            *self.owner,
            *self.owner,
            trade_date,
            *self.owner,
        ]
        if rule_id is not None:
            params.append(rule_id)
        df = self.pg.query_df(
            "WITH latest_management AS ("
            "SELECT DISTINCT ON (rule_id) rule_id,event_type,event_seq,version_no,"
            "occurred_at,activated_at,effective_from_trade_date "
            "FROM trade_discipline_rule_activation WHERE tenant_id=%s AND owner_user_id=%s "
            "ORDER BY rule_id,event_seq DESC), effective AS ("
            "SELECT DISTINCT ON (rule_id) rule_id,event_type,event_seq,version_no,"
            "effective_from_trade_date FROM trade_discipline_rule_activation "
            "WHERE tenant_id=%s AND owner_user_id=%s AND effective_from_trade_date<=%s "
            "ORDER BY rule_id,effective_from_trade_date DESC,event_seq DESC) "
            "SELECT r.*,d.draft_revision,d.proposed_name,d.source_version_no,"
            "lm.event_type AS management_event_type,lm.event_seq AS management_event_seq,"
            "lm.version_no AS management_version_no,lm.occurred_at AS management_occurred_at,"
            "lm.activated_at AS management_activated_at,"
            "lm.effective_from_trade_date AS management_effective_from_trade_date,"
            "ef.event_type AS effective_event_type,ef.event_seq AS effective_event_seq,"
            "ef.version_no AS effective_version_no,"
            "ef.effective_from_trade_date AS effective_from_trade_date,"
            "ev.name AS effective_version_name,ev.capital AS effective_version_capital "
            "FROM trade_discipline_rule r LEFT JOIN trade_discipline_rule_draft d "
            "ON d.tenant_id=r.tenant_id AND d.owner_user_id=r.owner_user_id AND d.rule_id=r.id "
            "LEFT JOIN latest_management lm ON lm.rule_id=r.id "
            "LEFT JOIN effective ef ON ef.rule_id=r.id "
            "LEFT JOIN trade_discipline_rule_version ev ON ev.tenant_id=r.tenant_id "
            "AND ev.owner_user_id=r.owner_user_id AND ev.rule_id=r.id "
            "AND ev.version_no=ef.version_no "
            "WHERE r.tenant_id=%s AND r.owner_user_id=%s AND r.deleted_at IS NULL"
            f"{rule_filter} ORDER BY r.updated_at DESC,r.id",
            params,
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
                "capital,source_version_no,max_positions) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id,owner_user_id,rule_id) DO UPDATE SET "
                "draft_revision=EXCLUDED.draft_revision, proposed_name=EXCLUDED.proposed_name, "
                "normalized_name=EXCLUDED.normalized_name, capital=EXCLUDED.capital, "
                "max_positions=EXCLUDED.max_positions, "
                "source_version_no=EXCLUDED.source_version_no, updated_at=now()",
                [
                    rule_id,
                    *self.owner,
                    revision,
                    draft.get("name"),
                    draft.get("normalized_name"),
                    draft.get("capital"),
                    source_version_no,
                    draft.get("max_positions"),
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
                    "(rule_id,tenant_id,owner_user_id,detail_id,name,max_capital,content,display_order,enabled,"
                    "price_min,price_max,st_filter,loss_filter,st_risk_filter,checklist_items) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        rule_id,
                        *self.owner,
                        item["detail_id"],
                        item.get("name"),
                        item.get("max_capital"),
                        item.get("content"),
                        item["display_order"],
                        item["enabled"],
                        item.get("price_min"),
                        item.get("price_max"),
                        item.get("st_filter", "any"),
                        item.get("loss_filter", "any"),
                        item.get("st_risk_filter", "any"),
                        Jsonb(item.get("checklist_items", [])),
                    ],
                )
            for item in draft.get("action_rules", []):
                cur.execute(
                    "INSERT INTO trade_discipline_draft_action_rule "
                    "(rule_id,tenant_id,owner_user_id,detail_id,name,action_type,action_subtype,"
                    "content,display_order,enabled,action_subtype_label) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                        item.get("action_subtype_label"),
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
                "(rule_id,tenant_id,owner_user_id,version_no,name,normalized_name,capital,max_positions) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    rule_id,
                    *self.owner,
                    version_no,
                    draft["name"],
                    draft["normalized_name"],
                    draft["capital"],
                    draft.get("max_positions"),
                ],
            )
            for item in draft["stock_rules"]:
                cur.execute(
                    "INSERT INTO trade_discipline_stock_rule "
                    "(rule_id,tenant_id,owner_user_id,version_no,detail_id,name,max_capital,content,"
                    "display_order,enabled,price_min,price_max,st_filter,loss_filter,st_risk_filter,checklist_items) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                        item.get("price_min"),
                        item.get("price_max"),
                        item.get("st_filter", "any"),
                        item.get("loss_filter", "any"),
                        item.get("st_risk_filter", "any"),
                        Jsonb(item.get("checklist_items", [])),
                    ],
                )
            for item in draft["action_rules"]:
                cur.execute(
                    "INSERT INTO trade_discipline_action_rule "
                    "(rule_id,tenant_id,owner_user_id,version_no,detail_id,name,action_type,"
                    "action_subtype,content,display_order,enabled,action_subtype_label) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                        item.get("action_subtype_label"),
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

    def effective_activation(
        self,
        rule_id: str,
        trade_date: date,
        *,
        conn: psycopg.Connection | None = None,
    ) -> dict[str, Any] | None:
        sql = (
            "SELECT * FROM trade_discipline_rule_activation "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s "
            "AND effective_from_trade_date<=%s "
            "ORDER BY effective_from_trade_date DESC,event_seq DESC LIMIT 1"
        )
        params = [*self.owner, rule_id, trade_date]
        if conn is None:
            df = self.pg.query_df(sql, params)
            return None if df.empty else df.iloc[0].to_dict()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return self._one(cur)

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

    # ── T3：打卡、不可变修订、原因与操作 ──────────────────────────

    def get_checkin_by_rule_date(
        self,
        rule_id: str,
        trade_date: date,
        *,
        conn: psycopg.Connection | None = None,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        sql = (
            "SELECT * FROM trade_discipline_checkin "
            "WHERE tenant_id=%s AND owner_user_id=%s AND rule_id=%s AND trade_date=%s"
            + (" FOR UPDATE" if for_update else "")
        )
        params = [*self.owner, rule_id, trade_date]
        if conn is None:
            df = self.pg.query_df(sql, params)
            return None if df.empty else df.iloc[0].to_dict()
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return self._one(cur)

    def get_checkin_by_id(
        self,
        checkin_id: str,
        *,
        conn: psycopg.Connection | None = None,
        for_update: bool = False,
    ) -> dict[str, Any]:
        sql = (
            "SELECT * FROM trade_discipline_checkin "
            "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s"
            + (" FOR UPDATE" if for_update else "")
        )
        params = [*self.owner, checkin_id]
        if conn is None:
            df = self.pg.query_df(sql, params)
            row = None if df.empty else df.iloc[0].to_dict()
        else:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                row = self._one(cur)
        if row is None:
            raise NotFoundError("履约打卡不存在")
        return row

    def create_checkin(
        self,
        conn: psycopg.Connection,
        *,
        checkin_id: str,
        rule_id: str,
        trade_date: date,
        submission_source: str = "workbench",
    ) -> dict[str, Any]:
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "INSERT INTO trade_discipline_checkin "
                    "(id,tenant_id,owner_user_id,rule_id,trade_date,current_revision_no,status,"
                    "submission_source,submitted_at) "
                    "VALUES (%s,%s,%s,%s,%s,1,'submitted',%s,clock_timestamp()) "
                    "RETURNING *",
                    [checkin_id, *self.owner, rule_id, trade_date, submission_source],
                )
                row = self._one(cur)
        except errors.UniqueViolation as exc:
            raise ConflictError("该规则在此交易日已经提交过打卡") from exc
        if row is None:
            raise ConflictError("打卡创建失败")
        return row

    def advance_checkin_revision(
        self,
        conn: psycopg.Connection,
        checkin_id: str,
        *,
        expected_revision: int,
        new_revision: int,
    ) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE trade_discipline_checkin SET current_revision_no=%s,status='amended',"
                "amended_at=clock_timestamp(),updated_at=now() "
                "WHERE tenant_id=%s AND owner_user_id=%s AND id=%s "
                "AND current_revision_no=%s RETURNING *",
                [new_revision, *self.owner, checkin_id, expected_revision],
            )
            row = self._one(cur)
        if row is None:
            raise ConflictError("打卡已被其他操作修正，请刷新后重试")
        return row

    def insert_revision(
        self,
        conn: psycopg.Connection,
        *,
        checkin_id: str,
        revision_no: int,
        rule_id: str,
        version_no: int,
        assessment: str,
        no_operation: bool,
        violation_detail: str | None,
        review_note: str | None,
        peak_positions: int | None = None,
        violation_items: list[str] | None = None,
    ) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO trade_discipline_checkin_revision "
                "(checkin_id,tenant_id,owner_user_id,revision_no,rule_id,version_no,"
                "revision_kind,assessment,no_operation,violation_detail,review_note,peak_positions,violation_items,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()) RETURNING *",
                [
                    checkin_id,
                    *self.owner,
                    revision_no,
                    rule_id,
                    version_no,
                    "initial" if revision_no == 1 else "amendment",
                    assessment,
                    no_operation,
                    violation_detail,
                    review_note,
                    peak_positions,
                    Jsonb(violation_items) if violation_items is not None else None,
                ],
            )
            row = self._one(cur)
        if row is None:
            raise ConflictError("打卡修订创建失败")
        return row

    def insert_violation(
        self,
        conn: psycopg.Connection,
        *,
        checkin_id: str,
        revision_no: int,
        reason_code: str | None,
        reason_id: str | None,
        reason_name: str,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trade_discipline_violation "
                "(checkin_id,tenant_id,owner_user_id,revision_no,reason_code,reason_id,"
                "reason_name_snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                [
                    checkin_id,
                    *self.owner,
                    revision_no,
                    reason_code,
                    reason_id,
                    reason_name,
                ],
            )

    def insert_operations(
        self,
        conn: psycopg.Connection,
        *,
        checkin_id: str,
        revision_no: int,
        rule_id: str,
        version_no: int,
        operations: list[dict[str, Any]],
    ) -> None:
        with conn.cursor() as cur:
            for item in operations:
                cur.execute(
                    "INSERT INTO trade_discipline_operation "
                    "(id,tenant_id,owner_user_id,checkin_id,revision_no,rule_id,version_no,"
                    "stock_code,stock_name_snapshot,side,stock_rule_id,action_rule_id,price,"
                    "quantity,amount,fee,operated_at,note,compliance_status,display_order,selection_facts,checklist_results) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [
                        item["id"],
                        *self.owner,
                        checkin_id,
                        revision_no,
                        rule_id,
                        version_no,
                        item["stock_code"],
                        item["stock_name_snapshot"],
                        item["side"],
                        item["stock_rule_id"],
                        item["action_rule_id"],
                        item.get("price"),
                        item.get("quantity"),
                        item.get("amount"),
                        item.get("fee"),
                        item.get("operated_at"),
                        item.get("note"),
                        item.get("compliance_status"),
                        item["display_order"],
                        Jsonb(item["selection_facts"]) if item.get("selection_facts") else None,
                        Jsonb(item["checklist_results"]) if item.get("checklist_results") else None,
                    ],
                )

    def get_active_reason(self, reason_id: str, *, conn: psycopg.Connection) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM trade_discipline_reason WHERE tenant_id=%s "
                "AND owner_user_id=%s AND id=%s AND is_active",
                [*self.owner, reason_id],
            )
            row = self._one(cur)
        if row is None:
            raise NotFoundError("自定义未履约原因不存在或已删除")
        return row

    def upsert_reason(
        self,
        conn: psycopg.Connection,
        *,
        reason_id: str,
        name: str,
        normalized_name: str,
    ) -> dict[str, Any]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO trade_discipline_reason "
                "(id,tenant_id,owner_user_id,name,normalized_name,is_active) "
                "VALUES (%s,%s,%s,%s,%s,TRUE) "
                "ON CONFLICT (tenant_id,owner_user_id,normalized_name) DO UPDATE SET "
                "name=EXCLUDED.name,is_active=TRUE,deleted_at=NULL,updated_at=now() RETURNING *",
                [reason_id, *self.owner, name, normalized_name],
            )
            row = self._one(cur)
        if row is None:
            raise ConflictError("自定义原因保存失败")
        return row

    def list_active_reasons(self) -> list[dict[str, Any]]:
        df = self.pg.query_df(
            "SELECT id,name,normalized_name,created_at,updated_at "
            "FROM trade_discipline_reason WHERE tenant_id=%s AND owner_user_id=%s "
            "AND is_active ORDER BY updated_at DESC,id",
            list(self.owner),
        )
        return df.to_dict("records")

    def delete_reason(self, reason_id: str) -> None:
        with self.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE trade_discipline_reason SET is_active=FALSE,deleted_at=clock_timestamp(),"
                "updated_at=now() WHERE tenant_id=%s AND owner_user_id=%s AND id=%s AND is_active",
                [*self.owner, reason_id],
            )
            if cur.rowcount != 1:
                raise NotFoundError("自定义未履约原因不存在或已删除")

    def load_revision(
        self,
        checkin_id: str,
        revision_no: int,
        *,
        conn: psycopg.Connection | None = None,
    ) -> dict[str, Any]:
        sql = (
            "SELECT rv.*,c.trade_date,c.status AS checkin_status,c.current_revision_no,"
            "c.submitted_at,c.amended_at,v.name AS rule_name,v.capital,v.max_positions,"
            "vio.reason_code,vio.reason_id,vio.reason_name_snapshot "
            "FROM trade_discipline_checkin_revision rv "
            "JOIN trade_discipline_checkin c ON c.tenant_id=rv.tenant_id "
            "AND c.owner_user_id=rv.owner_user_id AND c.id=rv.checkin_id "
            "JOIN trade_discipline_rule_version v ON v.tenant_id=rv.tenant_id "
            "AND v.owner_user_id=rv.owner_user_id AND v.rule_id=rv.rule_id "
            "AND v.version_no=rv.version_no "
            "LEFT JOIN trade_discipline_violation vio ON vio.tenant_id=rv.tenant_id "
            "AND vio.owner_user_id=rv.owner_user_id AND vio.checkin_id=rv.checkin_id "
            "AND vio.revision_no=rv.revision_no "
            "WHERE rv.tenant_id=%s AND rv.owner_user_id=%s "
            "AND rv.checkin_id=%s AND rv.revision_no=%s"
        )
        params = [*self.owner, checkin_id, revision_no]
        if conn is None:
            df = self.pg.query_df(sql, params)
            row = None if df.empty else df.iloc[0].to_dict()
        else:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                row = self._one(cur)
        if row is None:
            raise NotFoundError("打卡修订不存在")
        row["operations"] = self._load_operations(checkin_id, revision_no, conn=conn)
        return row

    def _load_operations(
        self,
        checkin_id: str,
        revision_no: int,
        *,
        conn: psycopg.Connection | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT op.*,sr.name AS stock_rule_name,ar.name AS action_rule_name,"
            "ar.action_subtype,sr.price_min,sr.price_max,sr.st_filter,sr.loss_filter,sr.st_risk_filter,sr.checklist_items "
            "FROM trade_discipline_operation op "
            "JOIN trade_discipline_stock_rule sr ON sr.tenant_id=op.tenant_id "
            "AND sr.owner_user_id=op.owner_user_id AND sr.rule_id=op.rule_id "
            "AND sr.version_no=op.version_no AND sr.detail_id=op.stock_rule_id "
            "JOIN trade_discipline_action_rule ar ON ar.tenant_id=op.tenant_id "
            "AND ar.owner_user_id=op.owner_user_id AND ar.rule_id=op.rule_id "
            "AND ar.version_no=op.version_no AND ar.detail_id=op.action_rule_id "
            "WHERE op.tenant_id=%s AND op.owner_user_id=%s "
            "AND op.checkin_id=%s AND op.revision_no=%s ORDER BY op.display_order,op.id"
        )
        params = [*self.owner, checkin_id, revision_no]
        if conn is None:
            return self.pg.query_df(sql, params).to_dict("records")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def list_checkins(
        self,
        *,
        filters: dict[str, Any],
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
    ) -> dict[str, Any]:
        where = ["c.tenant_id=%s", "c.owner_user_id=%s"]
        params: list[Any] = [*self.owner]
        scalar_filters = {
            "date_from": ("c.trade_date >= %s", filters.get("date_from")),
            "date_to": ("c.trade_date <= %s", filters.get("date_to")),
            "rule_id": ("c.rule_id = %s", filters.get("rule_id")),
            "assessment": ("rv.assessment = %s", filters.get("assessment")),
            "no_operation": ("rv.no_operation = %s", filters.get("no_operation")),
        }
        for clause, value in scalar_filters.values():
            if value is not None:
                where.append(clause)
                params.append(value)
        if filters.get("amended") is not None:
            where.append("c.status = %s")
            params.append("amended" if filters["amended"] else "submitted")
        if filters.get("stock"):
            where.append(
                "EXISTS (SELECT 1 FROM trade_discipline_operation opf "
                "WHERE opf.tenant_id=c.tenant_id AND opf.owner_user_id=c.owner_user_id "
                "AND opf.checkin_id=c.id AND opf.revision_no=c.current_revision_no "
                "AND (opf.stock_code ILIKE %s OR opf.stock_name_snapshot ILIKE %s))"
            )
            pattern = f"%{filters['stock']}%"
            params.extend([pattern, pattern])
        if filters.get("reason"):
            where.append("vio.reason_name_snapshot ILIKE %s")
            params.append(f"%{filters['reason']}%")
        where_sql = " AND ".join(where)
        from_sql = (
            "FROM trade_discipline_checkin c "
            "JOIN trade_discipline_checkin_revision rv ON rv.tenant_id=c.tenant_id "
            "AND rv.owner_user_id=c.owner_user_id AND rv.checkin_id=c.id "
            "AND rv.revision_no=c.current_revision_no "
            "JOIN trade_discipline_rule_version v ON v.tenant_id=rv.tenant_id "
            "AND v.owner_user_id=rv.owner_user_id AND v.rule_id=rv.rule_id "
            "AND v.version_no=rv.version_no "
            "LEFT JOIN trade_discipline_violation vio ON vio.tenant_id=rv.tenant_id "
            "AND vio.owner_user_id=rv.owner_user_id AND vio.checkin_id=rv.checkin_id "
            "AND vio.revision_no=rv.revision_no "
        )
        total = int(
            self.pg.query_df(f"SELECT count(*) AS n {from_sql} WHERE {where_sql}", params).iloc[0][
                "n"
            ]
        )
        sort_columns = {"trade_date": "c.trade_date"}
        sort_column = sort_columns[sort_by]
        direction = "ASC" if sort_order == "asc" else "DESC"
        rows = self.pg.query_df(
            "SELECT c.id,c.rule_id,c.trade_date,c.status,c.current_revision_no,c.submitted_at,"
            "c.amended_at,c.updated_at,rv.version_no,rv.assessment,rv.no_operation,"
            "v.name AS rule_name,vio.reason_name_snapshot,"
            "(SELECT count(*) FROM trade_discipline_operation opc "
            "WHERE opc.tenant_id=c.tenant_id AND opc.owner_user_id=c.owner_user_id "
            "AND opc.checkin_id=c.id AND opc.revision_no=c.current_revision_no) AS operation_count "
            f"{from_sql} WHERE {where_sql} "
            f"ORDER BY {sort_column} {direction},c.updated_at {direction},c.id {direction} "
            "LIMIT %s OFFSET %s",
            params + [page_size, (page - 1) * page_size],
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "list": self._records(rows),
        }

    def checkin_summary(self, trade_date: date) -> list[dict[str, Any]]:
        df = self.pg.query_df(
            "WITH latest_event AS (SELECT DISTINCT ON (a.rule_id) a.rule_id,a.version_no,"
            "a.event_type,a.effective_from_trade_date,a.event_seq "
            "FROM trade_discipline_rule_activation a WHERE a.tenant_id=%s "
            "AND a.owner_user_id=%s AND a.effective_from_trade_date<=%s "
            "ORDER BY a.rule_id,a.effective_from_trade_date DESC,a.event_seq DESC) "
            "SELECT r.id AS rule_id,v.name AS rule_name,le.version_no,"
            "le.effective_from_trade_date,c.id AS checkin_id,c.current_revision_no,c.status,"
            "rv.assessment,rv.no_operation,v.max_positions FROM latest_event le "
            "JOIN trade_discipline_rule r ON r.tenant_id=%s AND r.owner_user_id=%s "
            "AND r.id=le.rule_id AND r.deleted_at IS NULL "
            "JOIN trade_discipline_rule_version v ON v.tenant_id=%s AND v.owner_user_id=%s "
            "AND v.rule_id=le.rule_id AND v.version_no=le.version_no "
            "LEFT JOIN trade_discipline_checkin c ON c.tenant_id=%s AND c.owner_user_id=%s "
            "AND c.rule_id=le.rule_id AND c.trade_date=%s "
            "LEFT JOIN trade_discipline_checkin_revision rv ON rv.tenant_id=c.tenant_id "
            "AND rv.owner_user_id=c.owner_user_id AND rv.checkin_id=c.id "
            "AND rv.revision_no=c.current_revision_no WHERE le.event_type<>'archive' "
            "ORDER BY v.name,r.id",
            [
                *self.owner,
                trade_date,
                *self.owner,
                *self.owner,
                *self.owner,
                trade_date,
            ],
        )
        return df.to_dict("records")
