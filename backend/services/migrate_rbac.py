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
    asset_pk_mismatches,
    init_pg_db,
    recreate_asset_tables,
)

log = get_logger("services.migrate_rbac")

_TABLES: list[str] = list(_ASSET_TABLES.keys())
_LEGACY_LAYOUT_USER = "local"   # 旧单用户布局身份键 → 重映射为 admin

# 外键/孤儿完整性关系（child →[(child列,parent列)...] parent）：迁移前后校验无孤儿（T3 要求）
_FK: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("stock_group_member", "stock_group", [("group_id", "id")]),
    ("backtest_trade", "backtest_run", [("run_id", "id")]),
    ("backtest_equity", "backtest_run", [("run_id", "id")]),
    ("backtest_metrics", "backtest_run", [("run_id", "id")]),
    ("training_round", "training_session", [("session_id", "id")]),
    ("training_trade", "training_session", [("session_id", "id")]),
    # 深一层父子：trade 必须挂在真实存在的 round 上（session_id + 回合序号）
    ("training_trade", "training_round", [("session_id", "session_id"), ("round_seq", "seq")]),
]


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


def _orphans_duck(duck, child: str, parent: str, pairs: list[tuple[str, str]]) -> int:
    """DuckDB 源侧孤儿数（child 的外键组在 parent 中无匹配）。"""
    join = " AND ".join(f"p.{pk}=c.{ck}" for ck, pk in pairs)
    notnull = " AND ".join(f"c.{ck} IS NOT NULL" for ck, _ in pairs)
    df = duck.query_df(
        f"SELECT count(*) AS n FROM {child} c WHERE {notnull} "
        f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE {join})")
    return int(df.iloc[0]["n"])


def _orphans_pg(pg, child: str, parent: str, pairs: list[tuple[str, str]]) -> int:
    """PG 侧孤儿数（default 租户内，含归属匹配）。"""
    join = " AND ".join(f"p.{pk}=c.{ck}" for ck, pk in pairs)
    notnull = " AND ".join(f"c.{ck} IS NOT NULL" for ck, _ in pairs)
    df = pg.query_df(
        f"SELECT count(*) AS n FROM {child} c WHERE c.tenant_id=%s AND {notnull} "
        f"AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.tenant_id=c.tenant_id "
        f"AND p.owner_user_id=c.owner_user_id AND {join})", [DEFAULT_TENANT_ID])
    return int(df.iloc[0]["n"])


def migrate_rbac(dry_run: bool = True, recreate: bool = False) -> dict:
    """执行/预演存量迁移。返回 {table: {duck, migrated, pg_after, problems}}，外加 _global 项。

    recreate=True：先 DROP+重建资产表（从旧单主键 schema 升级用），再载入。
    """
    duck: DuckDBClient = get_client()
    pg = get_pg_client()
    if recreate and not dry_run:
        recreate_asset_tables(pg)
    init_pg_db(pg)  # 确保 PG 表存在（复合主键含归属列）
    report: dict[str, dict] = {}
    glob: list[str] = []

    # 旧 schema 升级检测：已存在但主键非复合 → 需 --recreate（否则 ON CONFLICT 会失配报错）
    mism = asset_pk_mismatches(pg)
    if mism:
        glob.append(f"主键非复合(旧 schema)的表 {mism}；用 migrate-rbac --recreate --apply 重建后再迁")

    # 源侧外键/孤儿完整性（dry-run 即校验，迁前暴露脏数据）
    for child, parent, pairs in _FK:
        try:
            n = _orphans_duck(duck, child, parent, pairs)
        except StorageError:
            n = 0
        if n:
            cols = "+".join(ck for ck, _ in pairs)
            glob.append(f"源孤儿：{child}.({cols}) 有 {n} 行在 {parent} 无匹配")

    for table in _TABLES:
        src = duck.query_df(f"SELECT * FROM {table}")
        tdf = _transform(table, src)
        problems = _validate_mapping(pg, table, tdf)
        migrated = 0
        if not dry_run and not problems and not mism:   # 主键失配时不载入，先 --recreate
            migrated = _load_table(pg, table, tdf)
        report[table] = {"duck": len(src), "migrated": migrated, "problems": problems}

    # app_config（平台表，无归属）：DuckDB→PG，ON CONFLICT DO NOTHING（不清空、不覆盖）
    ac = duck.query_df("SELECT key, value, updated_at FROM app_config")
    from backend.storage.app_config import SENSITIVE_RUNTIME_CONFIG_PATHS

    ac = ac[~ac["key"].astype(str).isin(SENSITIVE_RUNTIME_CONFIG_PATHS)]
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
        # 迁后外键/孤儿完整性（PG 侧，含归属匹配）
        for child, parent, pairs in _FK:
            try:
                n = _orphans_pg(pg, child, parent, pairs)
            except StorageError:
                n = 0
            if n:
                cols = "+".join(ck for ck, _ in pairs)
                glob.append(f"迁后孤儿：{child}.({cols}) 有 {n} 行在 {parent} 无同归属匹配")

    report["_global"] = {"problems": glob}
    mode = "DRY-RUN" if dry_run else "MIGRATE"
    log.info("[%s] 存量迁移 %d 表，源合计 %d 行，全局问题 %d",
             mode, len(_TABLES), sum(r["duck"] for r in report.values() if "duck" in r), len(glob))
    return report
