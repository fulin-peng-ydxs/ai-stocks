"""板块自选仓库：仅持久化用户选择，行情与板块有效性由服务层从 DuckDB 合并。"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from backend.auth.context import get_current_owner
from backend.storage.pg_client import get_pg_client


class BoardWatchlistRepo:
    """按 tenant_id + owner_user_id 隔离的板块自选持久层。"""

    def __init__(
        self,
        pg=None,
        *,
        tenant_id: str | None = None,
        owner_user_id: str | None = None,
    ):
        self.pg = pg or get_pg_client()
        context_tenant, context_owner = get_current_owner()
        self.tenant_id = tenant_id or context_tenant
        self.owner_user_id = owner_user_id or context_owner

    @property
    def _own_params(self) -> list[str]:
        return [self.tenant_id, self.owner_user_id]

    def list(self) -> list[dict]:
        rows = self.pg.query_df(
            "SELECT board_code, board_name, board_type, added_at "
            "FROM board_watchlist WHERE tenant_id=%s AND owner_user_id=%s "
            "ORDER BY added_at DESC, board_code",
            self._own_params,
        )
        result: list[dict] = []
        for row in rows.to_dict("records"):
            added_at = row.get("added_at")
            result.append({
                "board_code": str(row["board_code"]),
                "name": str(row["board_name"]),
                "board_type": str(row["board_type"]),
                "added_at": (
                    None if added_at is None or pd.isna(added_at)
                    else pd.Timestamp(added_at).isoformat()
                ),
            })
        return result

    def add(self, board_code: str, board_name: str, board_type: str) -> bool:
        inserted = self.pg.execute(
            "INSERT INTO board_watchlist "
            "(tenant_id,owner_user_id,board_code,board_name,board_type,added_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, owner_user_id, board_code) DO NOTHING",
            [
                self.tenant_id,
                self.owner_user_id,
                board_code,
                board_name,
                board_type,
                datetime.now(UTC),
            ],
        )
        if inserted == 0:
            self.pg.execute(
                "UPDATE board_watchlist SET board_name=%s, board_type=%s "
                "WHERE tenant_id=%s AND owner_user_id=%s AND board_code=%s",
                [board_name, board_type, *self._own_params, board_code],
            )
        return inserted > 0

    def remove(self, board_code: str) -> bool:
        removed = self.pg.execute(
            "DELETE FROM board_watchlist "
            "WHERE tenant_id=%s AND owner_user_id=%s AND board_code=%s",
            [*self._own_params, board_code],
        )
        return removed > 0
