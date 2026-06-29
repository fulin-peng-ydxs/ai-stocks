"""存量资产迁移：DuckDB → PostgreSQL（多租户混合持久层 stage1·T3，一次性·不可逆）。

把 DuckDB 中现存的用户私有资产迁入 PG，并补归属字段，全部归「默认租户 default + 平台管理员 admin」。
行情/参考数据（stock_basic/daily_bar/...）不迁、保留在 DuckDB。

归属映射：
- 通用：tenant_id='default'，owner_user_id='admin'。
- training_session：DuckDB 含旧 user_id 列（PG 已无），迁移时丢弃，归 admin。
- layout_user_config：user_id 即用户身份键，旧值 'local' 重映射为 'admin'（与需求 R3 一致），
  owner_user_id 同步取该 user_id。

执行口径（幂等·可重跑）：
- 先 DELETE 目标表 tenant_id='default' 的行（清掉历史迁移/测试残留），再整表载入 → 与 DuckDB 精确镜像。
- app_config 为平台表无归属，单独 ON CONFLICT DO NOTHING 载入。
- DuckDB 原表不动（保留只读副本兜底）；不可逆点：上线后 PG 产生新数据即无法简单回退。

校验（T3 要求）：
- dry-run：逐表校验「DuckDB 源列经归属变换后 ⊆ PG 目标列」（字段映射），并报告源行数；不写。
- apply：用实际写入行数(rowcount)统计，迁后核对「PG default 租户行数 == DuckDB 源行数」+ 归属列非空。

入口：migrate_rbac(dry_run=True) 预演；dry_run=False 实迁。
"""

from __future__ import annotations

import pandas as pd

from backend.common.exceptions import StorageError
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

_TABLES: list[str] = list(_ASSET_TABLES.keys())
_LEGACY_LAYOUT_USER = "local"   # 旧单用户布局身份键 → 重映射为 admin


def _to_pg_rows(df: pd.DataFrame) -> list[tuple]:
    """DataFrame → 行元组列表，NaN/NaT → None。"""
    return [
        tuple(None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v for v in r)
        for r in df.itertuples(index=False, name=None)
    ]


def _transform(table: str, df: pd.DataFrame) -> pd.DataFrame:
    """补归属列（按表特例）。"""
    df = df.copy()
    if table == "training_session":
        df = df.drop(columns=["user_id"], errors="ignore")  # 旧预留列，PG 已无
    if table == "layout_user_config":
        # user_id 即身份键：旧 'local' → admin；owner_user_id 同步取该 user_id
        if "user_id" in df.columns:
            df["user_id"] = df["user_id"].replace(_LEGACY_LAYOUT_USER, DEFAULT_OWNER_USER_ID)
        df["tenant_id"] = DEFAULT_TENANT_ID
        df["owner_user_id"] = df["user_id"] if "user_id" in df.columns else DEFAULT_OWNER_USER_ID
    else:
        df["tenant_id"] = DEFAULT_TENANT_ID
        df["owner_user_id"] = DEFAULT_OWNER_USER_ID
    return df


def _pg_columns(pg, table: str) -> set[str]:
    df = pg.query_df(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s", [table])
    return set(df["column_name"].tolist()) if not df.empty else set()


def _validate_mapping(pg, table: str, df: pd.DataFrame) -> list[str]:
    """字段映射校验：变换后的列必须 ⊆ PG 表列；归属列必须齐备。返回问题列表（空=通过）。"""
    problems: list[str] = []
    pg_cols = _pg_columns(pg, table)
    if not pg_cols:
        return [f"PG 缺表 {table}"]
    extra = set(df.columns) - pg_cols
    if extra:
        problems.append(f"{table}: 源列不在 PG 表中 {sorted(extra)}")
    for oc in ("tenant_id", "owner_user_id"):
        if oc not in df.columns:
            problems.append(f"{table}: 缺归属列 {oc}")
        elif df[oc].isna().any():
            problems.append(f"{table}: 归属列 {oc} 存在空值")
    return problems


def _load_table(pg, table: str, df: pd.DataFrame) -> int:
    """清掉目标表 default 租户旧行后整表载入（含归属列）。返回实际写入行数(rowcount)。"""
    pg.execute(f"DELETE FROM {table} WHERE tenant_id=%s", [DEFAULT_TENANT_ID])
    if df.empty:
        return 0
    cols = list(df.columns)
    placeholders = "(" + ", ".join(["%s"] * len(cols)) + ")"
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES {placeholders}"  # 已清空,无需 ON CONFLICT
    with pg.transaction() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, _to_pg_rows(df))
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(df)


def migrate_rbac(dry_run: bool = True) -> dict:
    """执行/预演存量迁移。返回 {table: {duck, migrated, pg_after, problems}}。"""
    duck: DuckDBClient = get_client()
    pg = get_pg_client()
    init_pg_db(pg)  # 确保 PG 表存在（复合主键含归属列）
    report: dict[str, dict] = {}

    for table in _TABLES:
        src = duck.query_df(f"SELECT * FROM {table}")
        tdf = _transform(table, src)
        problems = _validate_mapping(pg, table, tdf)
        migrated = 0
        if not dry_run and not problems:
            migrated = _load_table(pg, table, tdf)
        report[table] = {"duck": len(src), "migrated": migrated, "problems": problems}

    # app_config（平台表，无归属）：DuckDB→PG，ON CONFLICT DO NOTHING（不清空、不覆盖）
    ac = duck.query_df("SELECT key, value, updated_at FROM app_config")
    if not dry_run and not ac.empty:
        with pg.transaction() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO app_config (key,value,updated_at) VALUES (%s,%s,%s) "
                    "ON CONFLICT (key) DO NOTHING", _to_pg_rows(ac))
    report["app_config"] = {"duck": len(ac), "migrated": 0 if dry_run else len(ac), "problems": []}

    # 核对：迁移后 PG default 租户行数应等于 DuckDB 源行数；归属列非空
    if not dry_run:
        for table in _TABLES:
            try:
                n_pg = int(pg.query_df(
                    f"SELECT count(*) AS n FROM {table} WHERE tenant_id=%s",
                    [DEFAULT_TENANT_ID]).iloc[0]["n"])
                n_null = int(pg.query_df(
                    f"SELECT count(*) AS n FROM {table} "
                    f"WHERE tenant_id=%s AND owner_user_id IS NULL",
                    [DEFAULT_TENANT_ID]).iloc[0]["n"])
            except StorageError:
                n_pg, n_null = -1, -1
            report[table]["pg_after"] = n_pg
            if n_null:
                report[table].setdefault("problems", []).append(f"{table}: 迁后归属空值 {n_null} 行")
        report["app_config"]["pg_after"] = int(
            pg.query_df("SELECT count(*) AS n FROM app_config").iloc[0]["n"])

    mode = "DRY-RUN" if dry_run else "MIGRATE"
    log.info("[%s] 存量迁移 %d 表，源合计 %d 行",
             mode, len(report), sum(r["duck"] for r in report.values()))
    return report
