"""PostgreSQL 建表 DDL（多租户混合持久层 stage1·T2）。

职责边界（与 [ddl.py] 的 DuckDB 行情库分工）：
- 本文件只建**用户私有资产 + 平台元数据**表，全部落 PG。
- 行情/参考数据（stock_basic/daily_bar/daily_metrics/index_bar/...）与运维/质检/调度
  （async_task/task_log/scheduled_job/data_*）**仍在 DuckDB**，不在此处。

归属与隔离（R9，**物理底座**）：
- 资产表统一加 tenant_id + owner_user_id，且**主键以归属列打头**（复合主键
  `(tenant_id, owner_user_id, <业务键>)`）：不同 owner 用同一业务 id 不会互相覆盖/串改，
  ON CONFLICT 也按归属命中各自的行。这是隔离的物理保证，不能只靠查询层 WHERE。
- app_config 为**平台级**配置（仅系统管理员、无归属列）。
- layout_user_config 的 user_id 即用户身份，主键 (user_id, page_key) 已天然隔离。
- sys_tenant/sys_user 为**最小骨架**，完整 RBAC 表在阶段三补全。

类型映射（DuckDB→PG）：VARCHAR→TEXT，DOUBLE→DOUBLE PRECISION，TINYINT→SMALLINT，
其余 BIGINT/INTEGER/BOOLEAN/DATE/TIMESTAMP 同名。

入口：init_pg_db(client) 幂等建全部表 + seed 默认租户/平台管理员。
"""

from __future__ import annotations

from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.pg_ddl")

# 存量迁移与单测的默认归属落点（见 R3 迁移方案）
DEFAULT_TENANT_ID = "default"
DEFAULT_OWNER_USER_ID = "admin"

# 资产表统一归属列（紧跟业务键之后；与复合主键配合）
_OWN = (
    "    tenant_id      TEXT NOT NULL DEFAULT 'default',\n"
    "    owner_user_id  TEXT NOT NULL DEFAULT 'admin',\n"
)


# ── 最小用户/租户骨架（阶段三补全完整 RBAC）──────────────────────

DDL_SYS_TENANT = """
CREATE TABLE IF NOT EXISTS sys_tenant (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | disabled
    admin_user_id TEXT,
    created_at    TIMESTAMP DEFAULT now(),
    updated_at    TIMESTAMP
);
"""

DDL_SYS_USER = """
CREATE TABLE IF NOT EXISTS sys_user (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    account       TEXT NOT NULL,
    email         TEXT,
    password_hash TEXT,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | disabled | locked
    created_at    TIMESTAMP DEFAULT now(),
    updated_at    TIMESTAMP,
    UNIQUE (account)
);
"""


# ── 筛选 / 评分 / 买卖方案及版本（用户资产）────────────────────────

DDL_SCREEN_PROFILE = f"""
CREATE TABLE IF NOT EXISTS screen_profile (
    id          TEXT,
{_OWN}    name        TEXT,
    version     INTEGER,
    expression  TEXT,
    params      TEXT,
    is_preset   BOOLEAN,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_SCREEN_PROFILE_VERSION = f"""
CREATE TABLE IF NOT EXISTS screen_profile_version (
    id          TEXT,
{_OWN}    version     INTEGER,
    name        TEXT,
    expression  TEXT,
    saved_at    TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id, version)
);
"""

DDL_SCORE_PROFILE = f"""
CREATE TABLE IF NOT EXISTS score_profile (
    id               TEXT,
{_OWN}    name             TEXT,
    version          INTEGER,
    items            TEXT,
    grade_thresholds TEXT,
    is_preset        BOOLEAN,
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_SCORE_PROFILE_VERSION = f"""
CREATE TABLE IF NOT EXISTS score_profile_version (
    id               TEXT,
{_OWN}    version          INTEGER,
    name             TEXT,
    items            TEXT,
    grade_thresholds TEXT,
    saved_at         TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id, version)
);
"""

DDL_TRADE_PROFILE = f"""
CREATE TABLE IF NOT EXISTS trade_profile (
    id          TEXT,
{_OWN}    name        TEXT,
    version     INTEGER,
    buy_tree    TEXT,
    sell_tree   TEXT,
    backstop    TEXT,
    is_preset   BOOLEAN,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_TRADE_PROFILE_VERSION = f"""
CREATE TABLE IF NOT EXISTS trade_profile_version (
    id          TEXT,
{_OWN}    version     INTEGER,
    name        TEXT,
    buy_tree    TEXT,
    sell_tree   TEXT,
    backstop    TEXT,
    saved_at    TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id, version)
);
"""


# ── 筛选 / 评分结果（用户资产，按日期+方案+code）────────────────────

DDL_SCREEN_RESULT = f"""
CREATE TABLE IF NOT EXISTS screen_result (
    run_date    DATE,
{_OWN}    profile_id  TEXT,
    code        TEXT,
    hit         BOOLEAN,
    matched     TEXT,
    snapshot    TEXT,
    PRIMARY KEY (tenant_id, owner_user_id, run_date, profile_id, code)
);
"""

DDL_SCORE_RESULT = f"""
CREATE TABLE IF NOT EXISTS score_result (
    trade_date  DATE,
{_OWN}    model_id    TEXT,
    code        TEXT,
    total_score DOUBLE PRECISION,
    sub_scores  TEXT,
    rank        INTEGER,
    grade       TEXT,
    buy_point   TEXT,
    risk_flags  TEXT,
    PRIMARY KEY (tenant_id, owner_user_id, trade_date, model_id, code)
);
"""


# ── 自选分组（用户资产）────────────────────────────────────────────

DDL_STOCK_GROUP = f"""
CREATE TABLE IF NOT EXISTS stock_group (
    id          TEXT,
{_OWN}    name        TEXT,
    group_date  DATE,
    description TEXT,
    color       TEXT,
    is_default  BOOLEAN,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_STOCK_GROUP_MEMBER = f"""
CREATE TABLE IF NOT EXISTS stock_group_member (
    group_id    TEXT,
{_OWN}    code        TEXT,
    add_date    DATE,
    note        TEXT,
    PRIMARY KEY (tenant_id, owner_user_id, group_id, code)
);
"""


# ── 回测结果（用户资产）────────────────────────────────────────────

DDL_BACKTEST_RUN = f"""
CREATE TABLE IF NOT EXISTS backtest_run (
    id          TEXT,
{_OWN}    kind        TEXT,
    profile_id  TEXT,
    model_id    TEXT,
    score_profile_id TEXT,
    trade_profile_id TEXT,
    score_profile_version INTEGER,
    profile_version       INTEGER,
    trade_profile_version INTEGER,
    signature   TEXT,
    date_start  DATE,
    date_end    DATE,
    params      TEXT,
    status      TEXT,
    detail      TEXT,
    created_at  TIMESTAMP,
    finished_at TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_BACKTEST_TRADE = f"""
CREATE TABLE IF NOT EXISTS backtest_trade (
    run_id        TEXT,
{_OWN}    seq           INTEGER,
    code          TEXT,
    entry_date    DATE,
    entry_price   DOUBLE PRECISION,
    exit_date     DATE,
    exit_price    DOUBLE PRECISION,
    exit_reason   TEXT,
    exit_detail   TEXT,
    shares        BIGINT,
    return_pct    DOUBLE PRECISION,
    pnl           DOUBLE PRECISION,
    hold_days     INTEGER,
    grade         TEXT,
    entry_score   DOUBLE PRECISION,
    entry_rank    INTEGER,
    entry_pick_rank INTEGER,
    entry_pool    INTEGER,
    PRIMARY KEY (tenant_id, owner_user_id, run_id, seq)
);
"""

DDL_BACKTEST_EQUITY = f"""
CREATE TABLE IF NOT EXISTS backtest_equity (
    run_id           TEXT,
{_OWN}    trade_date       DATE,
    equity           DOUBLE PRECISION,
    cash             DOUBLE PRECISION,
    position_value   DOUBLE PRECISION,
    n_positions      INTEGER,
    drawdown         DOUBLE PRECISION,
    benchmark_equity DOUBLE PRECISION,
    PRIMARY KEY (tenant_id, owner_user_id, run_id, trade_date)
);
"""

DDL_BACKTEST_METRICS = f"""
CREATE TABLE IF NOT EXISTS backtest_metrics (
    run_id          TEXT,
{_OWN}    total_return    DOUBLE PRECISION,
    annual_return   DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    max_dd_days     INTEGER,
    annual_vol      DOUBLE PRECISION,
    sharpe          DOUBLE PRECISION,
    calmar          DOUBLE PRECISION,
    sortino         DOUBLE PRECISION,
    win_rate        DOUBLE PRECISION,
    profit_factor   DOUBLE PRECISION,
    avg_hold_days   DOUBLE PRECISION,
    n_trades        INTEGER,
    benchmark_return DOUBLE PRECISION,
    excess_return   DOUBLE PRECISION,
    hit_rate_by_grade TEXT,
    extra           TEXT,
    PRIMARY KEY (tenant_id, owner_user_id, run_id)
);
"""


# ── 评分快照（用户资产，惰性物化）──────────────────────────────────

DDL_SCORE_SNAPSHOT = f"""
CREATE TABLE IF NOT EXISTS score_snapshot (
    trade_date      DATE,
{_OWN}    profile_id      TEXT,
    profile_version INTEGER,
    code            TEXT,
    total_score     DOUBLE PRECISION,
    grade           TEXT,
    rank            INTEGER,
    sub_scores      TEXT,
    PRIMARY KEY (tenant_id, owner_user_id, trade_date, profile_id, profile_version, code)
);
"""

DDL_SCORE_SNAPSHOT_META = f"""
CREATE TABLE IF NOT EXISTS score_snapshot_meta (
    trade_date      DATE,
{_OWN}    profile_id      TEXT,
    profile_version INTEGER,
    computed_at     TIMESTAMP,
    stale           BOOLEAN,
    n_codes         INTEGER,
    PRIMARY KEY (tenant_id, owner_user_id, trade_date, profile_id, profile_version)
);
"""


# ── 盘感训练（用户资产）────────────────────────────────────────────

DDL_TRAINING_SESSION = f"""
CREATE TABLE IF NOT EXISTS training_session (
    id              TEXT,
{_OWN}    mode            TEXT,
    range_start     DATE,
    range_end       DATE,
    n_rounds        INTEGER,
    window_days     INTEGER,
    initial_capital DOUBLE PRECISION,
    filters         TEXT,
    fee_enabled     BOOLEAN,
    status          TEXT,
    cur_round       INTEGER,
    total_return    DOUBLE PRECISION,
    score           DOUBLE PRECISION,
    grade           TEXT,
    win_rate        DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    n_trades        INTEGER,
    review_note     TEXT,
    created_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_TRAINING_ROUND = f"""
CREATE TABLE IF NOT EXISTS training_round (
    session_id      TEXT,
{_OWN}    seq             INTEGER,
    code            TEXT,
    start_date      DATE,
    end_date        DATE,
    window_days     INTEGER,
    base_factor     DOUBLE PRECISION,
    price_limit_pct DOUBLE PRECISION,
    cursor_date     DATE,
    cursor_idx      INTEGER,
    status          TEXT,
    cash            DOUBLE PRECISION,
    pos_shares      BIGINT,
    pos_cost        DOUBLE PRECISION,
    pos_avg_price   DOUBLE PRECISION,
    pending         TEXT,
    realized_pnl    DOUBLE PRECISION,
    round_return    DOUBLE PRECISION,
    benchmark_return DOUBLE PRECISION,
    final_equity    DOUBLE PRECISION,
    PRIMARY KEY (tenant_id, owner_user_id, session_id, seq)
);
"""

DDL_TRAINING_TRADE = f"""
CREATE TABLE IF NOT EXISTS training_trade (
    session_id      TEXT,
{_OWN}    round_seq       INTEGER,
    seq             INTEGER,
    side            TEXT,
    decide_date     DATE,
    fill_date       DATE,
    rel_day         INTEGER,
    price           DOUBLE PRECISION,
    hands           INTEGER,
    shares          BIGINT,
    amount          DOUBLE PRECISION,
    fee             DOUBLE PRECISION,
    pnl             DOUBLE PRECISION,
    return_pct      DOUBLE PRECISION,
    reason          TEXT,
    auto_close      BOOLEAN,
    PRIMARY KEY (tenant_id, owner_user_id, session_id, round_seq, seq)
);
"""


# ── 布局用户层（用户资产；user_id 即身份，天然隔离）────────────────

DDL_LAYOUT_USER_CONFIG = f"""
CREATE TABLE IF NOT EXISTS layout_user_config (
    user_id        TEXT,
{_OWN}    page_key       TEXT,
    config         TEXT,
    schema_version INTEGER,
    updated_at     TIMESTAMP,
    PRIMARY KEY (user_id, page_key)
);
"""


# ── 平台级配置覆盖层（仅系统管理员；无归属列）──────────────────────

DDL_APP_CONFIG = """
CREATE TABLE IF NOT EXISTS app_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP
);
"""


# 归属表 → 复合主键（含归属列）。asset_repository / 各仓库 ON CONFLICT 必须与此一致。
ASSET_PK: dict[str, list[str]] = {
    "screen_profile": ["tenant_id", "owner_user_id", "id"],
    "screen_profile_version": ["tenant_id", "owner_user_id", "id", "version"],
    "score_profile": ["tenant_id", "owner_user_id", "id"],
    "score_profile_version": ["tenant_id", "owner_user_id", "id", "version"],
    "trade_profile": ["tenant_id", "owner_user_id", "id"],
    "trade_profile_version": ["tenant_id", "owner_user_id", "id", "version"],
    "screen_result": ["tenant_id", "owner_user_id", "run_date", "profile_id", "code"],
    "score_result": ["tenant_id", "owner_user_id", "trade_date", "model_id", "code"],
    "stock_group": ["tenant_id", "owner_user_id", "id"],
    "stock_group_member": ["tenant_id", "owner_user_id", "group_id", "code"],
    "backtest_run": ["tenant_id", "owner_user_id", "id"],
    "backtest_trade": ["tenant_id", "owner_user_id", "run_id", "seq"],
    "backtest_equity": ["tenant_id", "owner_user_id", "run_id", "trade_date"],
    "backtest_metrics": ["tenant_id", "owner_user_id", "run_id"],
    "score_snapshot": ["tenant_id", "owner_user_id", "trade_date", "profile_id", "profile_version", "code"],
    "score_snapshot_meta": ["tenant_id", "owner_user_id", "trade_date", "profile_id", "profile_version"],
    "training_session": ["tenant_id", "owner_user_id", "id"],
    "training_round": ["tenant_id", "owner_user_id", "session_id", "seq"],
    "training_trade": ["tenant_id", "owner_user_id", "session_id", "round_seq", "seq"],
    "layout_user_config": ["user_id", "page_key"],
}

# 表 DDL（建表用）
_ASSET_TABLES: dict[str, str] = {
    "screen_profile": DDL_SCREEN_PROFILE,
    "screen_profile_version": DDL_SCREEN_PROFILE_VERSION,
    "score_profile": DDL_SCORE_PROFILE,
    "score_profile_version": DDL_SCORE_PROFILE_VERSION,
    "trade_profile": DDL_TRADE_PROFILE,
    "trade_profile_version": DDL_TRADE_PROFILE_VERSION,
    "screen_result": DDL_SCREEN_RESULT,
    "score_result": DDL_SCORE_RESULT,
    "stock_group": DDL_STOCK_GROUP,
    "stock_group_member": DDL_STOCK_GROUP_MEMBER,
    "backtest_run": DDL_BACKTEST_RUN,
    "backtest_trade": DDL_BACKTEST_TRADE,
    "backtest_equity": DDL_BACKTEST_EQUITY,
    "backtest_metrics": DDL_BACKTEST_METRICS,
    "score_snapshot": DDL_SCORE_SNAPSHOT,
    "score_snapshot_meta": DDL_SCORE_SNAPSHOT_META,
    "training_session": DDL_TRAINING_SESSION,
    "training_round": DDL_TRAINING_ROUND,
    "training_trade": DDL_TRAINING_TRADE,
    "layout_user_config": DDL_LAYOUT_USER_CONFIG,
}

# 无归属列的表（骨架 + 平台配置）
_OTHER_TABLES: dict[str, str] = {
    "sys_tenant": DDL_SYS_TENANT,
    "sys_user": DDL_SYS_USER,
    "app_config": DDL_APP_CONFIG,
}


def init_pg_db(client: PostgresClient | None = None) -> list[str]:
    """幂等建全部 PG 资产/骨架表 + (tenant_id, owner_user_id) 索引，并 seed 默认租户/管理员。

    返回已建表名列表。可重复执行（CREATE TABLE/INDEX IF NOT EXISTS）。
    """
    client = client or get_pg_client()
    created: list[str] = []
    for name, sql in {**_OTHER_TABLES, **_ASSET_TABLES}.items():
        client.execute(sql)
        created.append(name)
        log.debug("PG 表已就绪: %s", name)
    # layout 主键以 user_id 打头，补归属索引便于按 owner 统计；其余表复合主键已覆盖归属查询
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_layout_user_config_owner "
        "ON layout_user_config (tenant_id, owner_user_id)")
    seed_default_tenant(client)
    return created


def seed_default_tenant(client: PostgresClient | None = None) -> None:
    """幂等 seed 默认租户 + 平台管理员（存量迁移与单测的归属落点）。"""
    client = client or get_pg_client()
    client.execute(
        "INSERT INTO sys_tenant (id, name, status) VALUES (%s, %s, 'active') "
        "ON CONFLICT (id) DO NOTHING",
        [DEFAULT_TENANT_ID, "默认租户"],
    )
    client.execute(
        "INSERT INTO sys_user (id, tenant_id, account, status) "
        "VALUES (%s, %s, %s, 'active') ON CONFLICT (id) DO NOTHING",
        [DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID, DEFAULT_OWNER_USER_ID],
    )
    client.execute(
        "UPDATE sys_tenant SET admin_user_id=%s WHERE id=%s AND admin_user_id IS NULL",
        [DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID],
    )


def list_pg_tables(client: PostgresClient | None = None) -> list[str]:
    """列出 PG public schema 下所有表名。"""
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    )
    return df["table_name"].tolist() if not df.empty else []
