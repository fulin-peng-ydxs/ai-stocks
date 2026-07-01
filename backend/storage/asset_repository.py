"""资产库通用仓库（PostgreSQL，多租户混合持久层 stage1·T2）。

对应 [repository.py] 的 MarketRepository（DuckDB 行情库），本类承载**用户资产**的
通用批量幂等写（结果/快照/回测/训练等按日期或 run 批量落库的表）。

与 DuckDB 版差异：
- DuckDB 用 register_df + temp_view 做 INSERT...SELECT；PG 无此机制，改 executemany 多行 upsert。
- 自动注入 tenant_id/owner_user_id（归属）；冲突更新时**不覆盖归属列**（保留原主）。
- 占位符 %s；事务内批量执行。
"""

from __future__ import annotations

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client
from backend.auth.context import get_current_owner
from backend.storage.pg_ddl import ASSET_PK

log = get_logger("storage.asset_repository")

# 主键统一以 pg_ddl.ASSET_PK 为准（复合主键含归属列，保证 ON CONFLICT 按归属命中）
_OWNER_COLS = ("tenant_id", "owner_user_id")


class AssetRepository:
    def __init__(self, pg: PostgresClient | None = None, *, tenant_id: str | None = None,
                 owner_user_id: str | None = None):
        self.pg = pg or get_pg_client()
        _ctx_t, _ctx_o = get_current_owner()
        self.tenant_id = tenant_id or _ctx_t
        self.owner_user_id = owner_user_id or _ctx_o

    def upsert(self, table: str, df: pd.DataFrame, *, add_owner: bool = True) -> int:
        """把 df 幂等写入资产表（PG）。自动补归属列；按表主键 ON CONFLICT。返回写入行数。

        df 列必须 ⊆ 表列且含主键列（归属列由本方法补，无需在 df 中给出）。
        """
        if df is None or df.empty:
            return 0
        pk = ASSET_PK[table]
        df2 = df.copy()
        if add_owner:
            df2["tenant_id"] = self.tenant_id
            df2["owner_user_id"] = self.owner_user_id
        cols = list(df2.columns)
        # 冲突更新列：排除主键与归属列（归属不随重写变更）
        non_pk = [c for c in cols if c not in pk and c not in _OWNER_COLS]
        col_list = ", ".join(cols)
        placeholders = "(" + ", ".join(["%s"] * len(cols)) + ")"
        if non_pk:
            set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_pk)
            conflict = f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {set_clause}"
        else:
            conflict = f"ON CONFLICT ({', '.join(pk)}) DO NOTHING"
        sql = f"INSERT INTO {table} ({col_list}) VALUES {placeholders} {conflict}"
        # NaN/NaT → None，便于 psycopg 映射 NULL
        rows = [
            tuple(None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v for v in r)
            for r in df2[cols].itertuples(index=False, name=None)
        ]
        with self.pg.transaction() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
        return len(df2)
