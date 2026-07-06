"""数据字典仓库（阶段五平台能力）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pandas as pd

from backend.storage.pg_client import PostgresClient, get_pg_client

_DICT_ITEM_SORT_COLS = {
    "sort": "sort",
    "code": "code",
    "label": "label",
    "enabled": "enabled",
    "updated_at": "updated_at",
}


class DictRepository:
    def __init__(self, pg: PostgresClient | None = None):
        self.pg = pg or get_pg_client()

    def list_types(
        self,
        *,
        q: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        size: int = 50,
    ) -> dict:
        conds: list[str] = []
        params: list[Any] = []
        if q:
            like = f"%{q.strip()}%"
            conds.append("(code ILIKE %s OR name ILIKE %s)")
            params += [like, like]
        if enabled is not None:
            conds.append("enabled=%s")
            params.append(enabled)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        total = int(self.pg.query_df(
            f"SELECT count(*) AS n FROM dict_type {where}", params
        ).iloc[0]["n"])
        page = max(1, page)
        size = max(1, min(size, 200))
        rows = self.pg.query_df(
            f"SELECT id, code, name, enabled, sort, remark, created_at, updated_at "
            f"FROM dict_type {where} ORDER BY sort, code LIMIT %s OFFSET %s",
            params + [size, (page - 1) * size],
        )
        return {
            "total": total,
            "page": page,
            "size": size,
            "list": [self._row(r.to_dict()) for _, r in rows.iterrows()],
        }

    def get_type(self, code: str) -> dict | None:
        df = self.pg.query_df(
            "SELECT id, code, name, enabled, sort, remark, created_at, updated_at "
            "FROM dict_type WHERE code=%s",
            [code],
        )
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def create_type(
        self,
        *,
        code: str,
        name: str,
        enabled: bool,
        sort: int,
        remark: str | None,
    ) -> dict:
        now = datetime.now()
        self.pg.execute(
            "INSERT INTO dict_type (id, code, name, enabled, sort, remark, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [uuid.uuid4().hex, code, name, enabled, sort, remark, now, now],
        )
        return self.get_type(code)  # type: ignore[return-value]

    def update_type(
        self,
        code: str,
        *,
        name: str,
        enabled: bool,
        sort: int,
        remark: str | None,
    ) -> dict:
        self.pg.execute(
            "UPDATE dict_type SET name=%s, enabled=%s, sort=%s, remark=%s, updated_at=%s "
            "WHERE code=%s",
            [name, enabled, sort, remark, datetime.now(), code],
        )
        return self.get_type(code)  # type: ignore[return-value]

    def delete_type(self, code: str) -> None:
        self.pg.execute("DELETE FROM dict_type WHERE code=%s", [code])

    def count_items(self, type_code: str) -> int:
        return int(self.pg.query_df(
            "SELECT count(*) AS n FROM dict_item WHERE type_code=%s", [type_code]
        ).iloc[0]["n"])

    def list_items(
        self,
        *,
        type_code: str,
        q: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        size: int = 50,
        sort_by: str = "sort",
        sort_order: str = "asc",
    ) -> dict:
        conds = ["type_code=%s"]
        params: list[Any] = [type_code]
        if q:
            like = f"%{q.strip()}%"
            conds.append("(code ILIKE %s OR label ILIKE %s)")
            params += [like, like]
        if enabled is not None:
            conds.append("enabled=%s")
            params.append(enabled)
        where = "WHERE " + " AND ".join(conds)
        total = int(self.pg.query_df(
            f"SELECT count(*) AS n FROM dict_item {where}", params
        ).iloc[0]["n"])
        page = max(1, page)
        size = max(1, min(size, 500))
        sort_col = _DICT_ITEM_SORT_COLS.get(sort_by, "sort")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        rows = self.pg.query_df(
            f"SELECT id, type_code, code, label, enabled, sort, remark, created_at, updated_at "
            f"FROM dict_item {where} ORDER BY {sort_col} {direction} NULLS LAST, sort ASC, code ASC "
            "LIMIT %s OFFSET %s",
            params + [size, (page - 1) * size],
        )
        return {
            "total": total,
            "page": page,
            "size": size,
            "list": [self._row(r.to_dict()) for _, r in rows.iterrows()],
        }

    def get_item(self, type_code: str, code: str) -> dict | None:
        df = self.pg.query_df(
            "SELECT id, type_code, code, label, enabled, sort, remark, created_at, updated_at "
            "FROM dict_item WHERE type_code=%s AND code=%s",
            [type_code, code],
        )
        return self._row(df.iloc[0].to_dict()) if not df.empty else None

    def create_item(
        self,
        *,
        type_code: str,
        code: str,
        label: str,
        enabled: bool,
        sort: int,
        remark: str | None,
    ) -> dict:
        now = datetime.now()
        self.pg.execute(
            "INSERT INTO dict_item "
            "(id, type_code, code, label, enabled, sort, remark, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [uuid.uuid4().hex, type_code, code, label, enabled, sort, remark, now, now],
        )
        return self.get_item(type_code, code)  # type: ignore[return-value]

    def update_item(
        self,
        type_code: str,
        code: str,
        *,
        label: str,
        enabled: bool,
        sort: int,
        remark: str | None,
    ) -> dict:
        self.pg.execute(
            "UPDATE dict_item SET label=%s, enabled=%s, sort=%s, remark=%s, updated_at=%s "
            "WHERE type_code=%s AND code=%s",
            [label, enabled, sort, remark, datetime.now(), type_code, code],
        )
        return self.get_item(type_code, code)  # type: ignore[return-value]

    def delete_item(self, type_code: str, code: str) -> None:
        self.pg.execute("DELETE FROM dict_item WHERE type_code=%s AND code=%s", [type_code, code])

    def version(self, type_code: str) -> str | None:
        df = self.pg.query_df(
            "SELECT greatest(max(dt.updated_at), max(di.updated_at)) AS v "
            "FROM dict_type dt LEFT JOIN dict_item di ON di.type_code=dt.code "
            "WHERE dt.code=%s",
            [type_code],
        )
        if df.empty:
            return None
        v = df.iloc[0]["v"]
        if v is None or pd.isna(v):
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    @staticmethod
    def _row(row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in row.items():
            if v is None:
                out[k] = None
                continue
            try:
                if pd.isna(v):
                    out[k] = None
                    continue
            except (TypeError, ValueError):
                pass
            out[k] = v.isoformat() if hasattr(v, "isoformat") else v
        return out
