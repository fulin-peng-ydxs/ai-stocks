"""存量资产迁移：DuckDB → PostgreSQL（多租户混合持久层 stage1·T3，一次性·不可逆）。

把 DuckDB 中现存的用户私有资产迁入 PG，并补归属字段，全部归「默认租户 default + 平台管理员 admin」。
行情/参考数据（stock_basic/daily_bar/...）不迁、保留在 DuckDB。

归属映射：
- 通用：tenant_id='default'，owner_user_id='admin'。
- training_session：DuckDB 含旧 user_id 列（PG 已无），迁移时丢弃，归 admin。
- layout_user_config：owner_user_id = 原 user_id（user_id 即该层隔离键），tenant_id='default'。

执行口径（幂等·可重跑）：
- 先 DELETE 目标表 tenant_id='default' 的行（清掉历史迁移/测试残留），再整表载入 → 与 DuckDB 精确镜像。
- app_config 为平台表无归属，单独 ON CONFLICT DO NOTHING 载入。
- DuckDB 原表不动（保留只读副本兜底）；不可逆点：上线后 PG 产生新数据即无法简单回退。

入口：migrate_rbac(dry_run=True) 先看清单；dry_run=False 实迁；末尾自动核对行数。
"""

from __future__ import annotations

import pandas as pd

from backend.common.logging import get_logger
from backend.storage.duckdb_client import DuckDBClient, get_client
from backend.storage.pg_client import get_pg_client
from backend.storage.pg_ddl import (
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
    _ASSET_TABLES,
    init_pg_db,
)

log = get_logger("services.migrate_rbac")

# 迁移顺序（PG 未加外键，顺序不影响正确性；此处按域聚合便于阅读报告）
_TABLES: list[str] = list(_ASSET_TABLES.keys())


def _to_pg_rows(df: pd.DataFrame) -> list[tuple]:
    """DataFrame → 行元组列表，NaN/NaT → None。"""
    return [
        tuple(None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v for v in r)
        for r in df.itertuples(index=False, name=None)
    ]


def _load_table(pg, table: str, df: pd.DataFrame) -> int:
    """清掉目标表 default 租户旧行后整表载入（含归属列）。返回载入行数。"""
    pg.execute(f"DELETE FROM {table} WHERE tenant_id=%s", [DEFAULT_TENANT_ID])
    if df.empty:
        return 0
    cols = list(df.columns)
    placeholders = "(" + ", ".join(["%s"] * len(cols)) + ")"
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES {placeholders} "
           f"ON CONFLICT DO NOTHING")
    with pg.transaction() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, _to_pg_rows(df))
    return len(df)


def _transform(table: str, df: pd.DataFrame) -> pd.DataFrame:
    """补归属列（按表特例）。"""
    df = df.copy()
    if table == "training_session":
        df = df.drop(columns=["user_id"], errors="ignore")  # 旧预留列，PG 已无
    df["tenant_id"] = DEFAULT_TENANT_ID
    if table == "layout_user_config":
        df["owner_user_id"] = df["user_id"]                 # user_id 即该层隔离键
    else:
        df["owner_user_id"] = DEFAULT_OWNER_USER_ID
    return df


def migrate_rbac(dry_run: bool = True) -> dict:
    """执行/预演存量迁移。返回 {table: {duck, migrated, pg_after}}。"""
    duck: DuckDBClient = get_client()
    pg = get_pg_client()
    init_pg_db(pg)  # 确保 PG 表存在
    report: dict[str, dict] = {}

    for table in _TABLES:
        src = duck.query_df(f"SELECT * FROM {table}")
        n_src = len(src)
        migrated = 0
        if not dry_run:
            migrated = _load_table(pg, table, _transform(table, src))
        report[table] = {"duck": n_src, "migrated": migrated}

    # app_config（平台表，无归属）：DuckDB→PG，ON CONFLICT DO NOTHING（不清空、不覆盖）
    ac = duck.query_df("SELECT key, value, updated_at FROM app_config")
    if not dry_run and not ac.empty:
        with pg.transaction() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO app_config (key,value,updated_at) VALUES (%s,%s,%s) "
                    "ON CONFLICT (key) DO NOTHING", _to_pg_rows(ac))
    report["app_config"] = {"duck": len(ac), "migrated": 0 if dry_run else len(ac)}

    # 核对：迁移后 PG default 租户行数应等于 DuckDB 源行数
    if not dry_run:
        for table in _TABLES:
            n_pg = int(pg.query_df(
                f"SELECT count(*) AS n FROM {table} WHERE tenant_id=%s",
                [DEFAULT_TENANT_ID]).iloc[0]["n"])
            report[table]["pg_after"] = n_pg
        n_ac = int(pg.query_df("SELECT count(*) AS n FROM app_config").iloc[0]["n"])
        report["app_config"]["pg_after"] = n_ac

    mode = "DRY-RUN" if dry_run else "MIGRATE"
    log.info("[%s] 存量迁移 %d 表，源合计 %d 行",
             mode, len(report), sum(r["duck"] for r in report.values()))
    return report
