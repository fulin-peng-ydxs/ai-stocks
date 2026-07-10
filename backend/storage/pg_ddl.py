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

import os
import secrets

from backend.auth.constants import (
    ASSET_PUBLIC_PUBLISH_RESOURCE_CODES,
    ASSET_TENANT_PUBLISH_RESOURCE_CODES,
    BUSINESS_RESOURCE_CODES,
    ROLE_NORMAL,
    ROLE_PAID,
    ROLE_SYSTEM,
    ROLE_TENANT_ADMIN,
)
from backend.auth.security import hash_password
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.pg_ddl")

# 存量迁移与单测的默认归属落点（见 R3 迁移方案）
DEFAULT_TENANT_ID = "default"
DEFAULT_OWNER_USER_ID = "admin"

# 平台公共榜单归属（stage4·C1 已确认）：每日榜单公共读**有意固定**此归属（default/admin
# 平台槽），全员登录用户共享同一份、**不按当前用户过滤**；评分维护任务 / public-board CLI 以此归属
# 生产公共预设 score_snapshot。属"有意全局"（与 indicator_def / mark_stale_* 同类先例），**禁止**后续按
# 私有资产隔离铁律"纠正"为 get_current_owner()。个人自建方案结果仍纯私有（走 /board/compute +
# ScoreSnapshotRepo 按调用者归属）。
PUBLIC_BOARD_OWNER = (DEFAULT_TENANT_ID, DEFAULT_OWNER_USER_ID)

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
    role_code     TEXT NOT NULL DEFAULT 'normal',   -- system | tenant_admin | normal（阶段三迁 sys_role）
    perm_ver      INTEGER NOT NULL DEFAULT 0,        -- 权限版本号：权限/状态变更自增，旧 token 失效
    status        TEXT NOT NULL DEFAULT 'active',   -- active | disabled | locked
    last_login_at TIMESTAMP,
    created_at    TIMESTAMP DEFAULT now(),
    updated_at    TIMESTAMP,
    UNIQUE (account)
);
"""


# ── RBAC 平台表（阶段三；自然键、不带 tenant/owner 归属，与「平台表用自然键」一致）──
# 角色/菜单/资源三主体 + 用户-角色 / 角色-菜单 / 角色-资源三关联；关联表复合主键 +
# FK 删除策略（RESTRICT=有引用禁删由应用层先提示影响面；CASCADE=授权关系随主体消亡自动清）。

DDL_SYS_ROLE = """
CREATE TABLE IF NOT EXISTS sys_role (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'custom',   -- system|tenant_admin|normal|paid（系统内置）| custom（自建）
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,   -- 内置角色不可删
    is_locked   BOOLEAN NOT NULL DEFAULT FALSE,   -- 权限锁定（system 超管：全授权且不可改）
    description TEXT,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP,
    UNIQUE (code)
);
"""

DDL_SYS_MENU = """
CREATE TABLE IF NOT EXISTS sys_menu (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,
    code        TEXT NOT NULL,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'leaf',      -- group（分组，仅展开）| leaf（叶子，可导航）
    route_path  TEXT,                              -- 叶子的前端路由；分组为 NULL
    icon        TEXT,                              -- Element Plus 图标名（如 TrendCharts）；无则 NULL
    sort        INTEGER NOT NULL DEFAULT 0,
    visible     TEXT NOT NULL DEFAULT 'login',     -- login（登录可见）| system（仅系统管理员）
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP,
    UNIQUE (code),
    FOREIGN KEY (parent_id) REFERENCES sys_menu (id) ON DELETE RESTRICT
);
"""

DDL_SYS_RESOURCE = """
CREATE TABLE IF NOT EXISTS sys_resource (
    id          TEXT PRIMARY KEY,
    menu_id     TEXT NOT NULL,
    code        TEXT NOT NULL,                     -- 精确权限码（如 user:list）；全局唯一
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'api',       -- button（按钮级）| api（接口级）
    api_method  TEXT,                              -- 绑定接口方法（api 类型）
    api_path    TEXT,                              -- 绑定接口路径（api 类型）
    sort        INTEGER NOT NULL DEFAULT 0,
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP,
    UNIQUE (code),
    FOREIGN KEY (menu_id) REFERENCES sys_menu (id) ON DELETE RESTRICT
);
"""

DDL_SYS_USER_ROLE = """
CREATE TABLE IF NOT EXISTS sys_user_role (
    user_id     TEXT NOT NULL,
    role_id     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT now(),
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE RESTRICT
);
"""

DDL_SYS_ROLE_MENU = """
CREATE TABLE IF NOT EXISTS sys_role_menu (
    role_id     TEXT NOT NULL,
    menu_id     TEXT NOT NULL,
    PRIMARY KEY (role_id, menu_id),
    FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE CASCADE,
    FOREIGN KEY (menu_id) REFERENCES sys_menu (id) ON DELETE CASCADE
);
"""

DDL_SYS_ROLE_RESOURCE = """
CREATE TABLE IF NOT EXISTS sys_role_resource (
    role_id     TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    PRIMARY KEY (role_id, resource_id),
    FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE CASCADE,
    FOREIGN KEY (resource_id) REFERENCES sys_resource (id) ON DELETE CASCADE
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
    visibility  TEXT NOT NULL DEFAULT 'private',
    published_at TIMESTAMP,
    published_by TEXT,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    CHECK (visibility IN ('private', 'tenant', 'public')),
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
    visibility       TEXT NOT NULL DEFAULT 'private',
    published_at     TIMESTAMP,
    published_by     TEXT,
    created_at       TIMESTAMP,
    updated_at       TIMESTAMP,
    CHECK (visibility IN ('private', 'tenant', 'public')),
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
    visibility  TEXT NOT NULL DEFAULT 'private',
    published_at TIMESTAMP,
    published_by TEXT,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    CHECK (visibility IN ('private', 'tenant', 'public')),
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
    visibility  TEXT NOT NULL DEFAULT 'private',
    published_at TIMESTAMP,
    published_by TEXT,
    created_at  TIMESTAMP,
    finished_at TIMESTAMP,
    CHECK (visibility IN ('private', 'tenant', 'public')),
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


# ── 阶段五平台能力：审计日志 + 数据字典（平台级，无 owner 归属）──────────────

DDL_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id             TEXT PRIMARY KEY,
    event_time     TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id      TEXT,
    actor_user_id  TEXT,
    actor_account  TEXT,
    event_category TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    resource_code  TEXT,
    action         TEXT,
    target_type    TEXT,
    target_id      TEXT,
    target_label   TEXT,
    result         TEXT NOT NULL,
    status         TEXT NOT NULL,
    ip             TEXT,
    method         TEXT,
    path           TEXT,
    duration_ms    INTEGER,
    error_summary  TEXT,
    context        JSONB NOT NULL DEFAULT '{}'::jsonb,
    changes        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_DICT_TYPE = """
CREATE TABLE IF NOT EXISTS dict_type (
    id         TEXT PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    sort       INTEGER NOT NULL DEFAULT 100,
    remark     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_DICT_ITEM = """
CREATE TABLE IF NOT EXISTS dict_item (
    id         TEXT PRIMARY KEY,
    type_code  TEXT NOT NULL REFERENCES dict_type(code) ON DELETE RESTRICT,
    code       TEXT NOT NULL,
    label      TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    sort       INTEGER NOT NULL DEFAULT 100,
    remark     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (type_code, code)
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
    "audit_log": DDL_AUDIT_LOG,
    "dict_type": DDL_DICT_TYPE,
    "dict_item": DDL_DICT_ITEM,
}

# RBAC 平台表（建表顺序遵守 FK：先主体 role/menu，再 resource(引 menu)，最后三关联表）。
# 依赖 sys_user 已建（在 _OTHER_TABLES），故在主循环之后单独建。
_RBAC_TABLES: dict[str, str] = {
    "sys_role": DDL_SYS_ROLE,
    "sys_menu": DDL_SYS_MENU,
    "sys_resource": DDL_SYS_RESOURCE,
    "sys_user_role": DDL_SYS_USER_ROLE,
    "sys_role_menu": DDL_SYS_ROLE_MENU,
    "sys_role_resource": DDL_SYS_ROLE_RESOURCE,
}

# RBAC 二级索引（复合主键已覆盖主查询方向；这里补反向查询：按 role/menu/resource 反查引用）
_RBAC_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_sys_menu_parent_sort ON sys_menu (parent_id, sort)",
    "CREATE INDEX IF NOT EXISTS idx_sys_resource_menu ON sys_resource (menu_id)",
    "CREATE INDEX IF NOT EXISTS idx_sys_user_role_role ON sys_user_role (role_id)",
    "CREATE INDEX IF NOT EXISTS idx_sys_role_menu_menu ON sys_role_menu (menu_id)",
    "CREATE INDEX IF NOT EXISTS idx_sys_role_resource_resource ON sys_role_resource (resource_id)",
)

_STAGE5_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_audit_log_event_time ON audit_log (event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_time ON audit_log (tenant_id, event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_category_time ON audit_log (event_category, event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_type_time ON audit_log (event_type, event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_resource_time ON audit_log (resource_code, event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_result_time ON audit_log (result, event_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_dict_type_enabled_sort ON dict_type (enabled, sort, code)",
    "CREATE INDEX IF NOT EXISTS idx_dict_item_type_enabled_sort ON dict_item (type_code, enabled, sort, code)",
)

_STAGE6_VISIBILITY_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_screen_profile_visibility "
    "ON screen_profile (visibility, tenant_id, owner_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_trade_profile_visibility "
    "ON trade_profile (visibility, tenant_id, owner_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_backtest_run_visibility "
    "ON backtest_run (visibility, tenant_id, owner_user_id)",
)


# ── RBAC seed 数据（内置角色 / 菜单树 / 功能点 / 默认授权；均可在角色管理页调整）──
# 内置角色：id=code（稳定自然键，seed 幂等）。(code, name, kind, is_locked, description)
_SEED_ROLES: tuple[tuple[str, str, str, bool, str], ...] = (
    (ROLE_SYSTEM, "系统管理员", "system", True,
     "平台超级管理员：拥有全部菜单与功能权限（锁定不可改）"),
    (ROLE_TENANT_ADMIN, "租户管理员", "tenant_admin", False,
     "本租户管理员：管理本租户用户，使用全部业务功能"),
    (ROLE_NORMAL, "普通用户", "normal", False,
     "普通用户：使用行情/筛选/回测/训练等业务功能"),
    (ROLE_PAID, "付费用户", "paid", False,
     "付费用户（预留，阶段三无创建入口/配额）"),
)

# 菜单树 seed：承接前端 menuConfig（emoji→Element Plus 图标名），新增「系统管理→权限管理」子组。
# 每项 (code, title, icon(EP名|None), visible, children)；有 children→group（route_path=None），否则→leaf(route_path=code)。
# visible=system 仅系统管理员可见；「系统管理/权限管理」分组与「用户管理」用 login，
# 因租户管理员（非 system）经授权也要能进用户管理，其上级分组不能被 system-only 挡死。
_SEED_MENU_TREE: list = [
    ("quotes", "最新行情", "TrendCharts", "login", [
        ("/stocks", "个股行情", None, "login", []),
        ("/board", "每日榜单", None, "login", []),
    ]),
    ("/screen", "策略筛选", "Filter", "login", []),
    ("/backtest", "策略回测", "DataLine", "login", []),
    ("/training", "盘感训练", "Aim", "login", []),
    ("data", "数据管理", "FolderOpened", "system", [
        ("/data/overview", "数据概览", None, "system", []),
        ("/data/quality", "数据质量", None, "system", []),
        ("/data/ingest", "数据采集", None, "system", []),
        ("/data/schedule", "任务调度", None, "system", []),
    ]),
    ("system", "系统管理", "Setting", "login", [
        ("/system/config", "配置管理", "Files", "login", [
            ("/system/config/score", "评分规则", None, "login", []),
            ("/system/config/trade", "买卖指标", None, "login", []),
            ("/system/config/tech", "技术指标", None, "system", []),
            ("/system/config/system", "系统设置", None, "system", []),
        ]),
        ("layout", "布局配置", "Brush", "system", [
            ("/system/layout/presets", "预设管理", None, "system", []),
            ("/system/layout/pages", "页面布局", None, "system", []),
            ("/system/layout/components", "系统组件", None, "system", []),
        ]),
        ("permission", "权限管理", "Lock", "login", [
            ("/system/users", "用户管理", None, "login", []),
            ("/system/roles", "角色管理", None, "system", []),
            ("/system/menus", "菜单与功能", None, "system", []),
            ("/system/tenants", "租户管理", None, "system", []),
        ]),
        ("/system/audit", "审计日志", None, "login", []),
        ("/system/dicts", "数据字典", None, "system", []),
    ]),
]

# 功能点/资源 seed：精确权限码（§4.3）。(menu_code, code, name, type, method, path)；id=code（全局唯一）。
_SEED_RESOURCES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("/system/users", "user:list", "查看用户", "api", "GET", "/api/users"),
    ("/system/users", "user:create", "新建用户", "api", "POST", "/api/users"),
    ("/system/users", "user:update", "编辑用户", "api", "PUT", "/api/users/{id}"),
    ("/system/users", "user:disable", "启停/锁定用户", "api", "POST", "/api/users/{id}/status"),
    ("/system/users", "user:reset-password", "重置密码", "api", "POST", "/api/users/{id}/reset-password"),
    ("/system/users", "user:delete", "删除用户", "api", "DELETE", "/api/users/{id}"),
    ("/system/roles", "role:list", "查看角色", "api", "GET", "/api/roles"),
    ("/system/roles", "role:create", "新建角色", "api", "POST", "/api/roles"),
    ("/system/roles", "role:update", "编辑角色", "api", "PUT", "/api/roles/{id}"),
    ("/system/roles", "role:delete", "删除角色", "api", "DELETE", "/api/roles/{id}"),
    ("/system/roles", "role:assign-perm", "配置角色权限", "api", "PUT", "/api/roles/{id}/perms"),
    ("/system/menus", "menu:list", "查看菜单", "api", "GET", "/api/menus"),
    ("/system/menus", "menu:create", "新建菜单节点", "api", "POST", "/api/menus"),
    ("/system/menus", "menu:update", "编辑菜单节点", "api", "PUT", "/api/menus/{id}"),
    ("/system/menus", "menu:delete", "删除菜单节点", "api", "DELETE", "/api/menus/{id}"),
    ("/system/menus", "menu:reorder", "菜单排序", "api", "POST", "/api/menus/reorder"),
    ("/system/menus", "resource:list", "查看功能点", "api", "GET", "/api/resources"),
    ("/system/menus", "resource:create", "新建功能点", "api", "POST", "/api/resources"),
    ("/system/menus", "resource:update", "编辑功能点", "api", "PUT", "/api/resources/{id}"),
    ("/system/menus", "resource:delete", "删除功能点", "api", "DELETE", "/api/resources/{id}"),
    ("/system/tenants", "tenant:list", "查看租户", "api", "GET", "/api/tenants"),
    ("/system/tenants", "tenant:create", "新建租户", "api", "POST", "/api/tenants"),
    ("/system/tenants", "tenant:update", "编辑租户", "api", "PUT", "/api/tenants/{id}"),
    ("/system/tenants", "tenant:disable", "启停租户", "api", "POST", "/api/tenants/{id}/status"),
    ("/system/tenants", "tenant:delete", "删除租户", "api", "DELETE", "/api/tenants/{id}"),
    # ── 阶段四：13 存量业务路由资源码（stage4·R21，与 stage4-existing-routes/resource-codes.sql 一致）──
    # A) baseline 登录基线共享读（挂 login 叶子作 FK 锚点；运行时由 perm_resolver 强制注入，见 SHARED_RESOURCE_CODES）
    ("/board",  "layout:view",         "布局生效配置读（全站基线）", "api", "GET", "/api/layout/effective/{page_key}"),
    ("/board",  "trade-calendar:view", "交易日历读（全站基线）",     "api", "GET", "/api/data/trade-dates"),
    ("/screen", "indicator:registry",  "指标目录读（研究基线）",     "api", "GET", "/api/indicators/registry"),
    # B) 每日榜单（/board，login）
    ("/board", "board:view",         "查看每日榜单",     "api", "GET",  "/api/scores/top"),
    ("/board", "board:compute",      "榜单即时计算",     "api", "GET",  "/api/board/compute"),
    ("/system/config/score", "score:run", "评分方案打分", "api", "POST", "/api/score-profiles/run"),
    ("/board", "layout:user-config", "保存个人页面偏好", "api", "POST", "/api/layout/users/{page_key}"),
    # B) 策略筛选（/screen，login）
    ("/screen", "screen-profile:view",   "查看筛选方案", "api", "GET",    "/api/profiles"),
    ("/screen", "screen-profile:save",   "保存筛选方案", "api", "POST",   "/api/profiles"),
    ("/screen", "screen-profile:delete", "删除筛选方案", "api", "DELETE", "/api/profiles/{pid}"),
    ("/screen", "screen-profile:publish-tenant", "租户内公开筛选方案", "api", "POST", "/api/profiles/{pid}/visibility"),
    ("/screen", "screen-profile:publish-public", "全体公开筛选方案",   "api", "POST", "/api/profiles/{pid}/visibility"),
    ("/screen", "screen:run",            "运行策略筛选", "api", "POST",   "/api/screen/run"),
    # B) 个股行情 + 自选分组（/stocks，login）
    ("/stocks", "stocks:view",               "查看个股行情", "api", "GET",    "/api/stocks"),
    ("/stocks", "stocks:trade-eval",         "个股买卖评估", "api", "GET",    "/api/stocks/{code}/trade-eval"),
    ("/stocks", "stock-group:view",          "查看自选分组", "api", "GET",    "/api/stock-groups"),
    ("/stocks", "stock-group:create",        "新建自选分组", "api", "POST",   "/api/stock-groups"),
    ("/stocks", "stock-group:update",        "编辑自选分组", "api", "PATCH",  "/api/stock-groups/{gid}"),
    ("/stocks", "stock-group:delete",        "删除自选分组", "api", "DELETE", "/api/stock-groups/{gid}"),
    ("/stocks", "stock-group:member-update", "维护分组成员", "api", "POST",   "/api/stock-groups/{gid}/members"),
    # B) 策略回测（/backtest，login）
    ("/backtest", "backtest:view",   "查看回测记录", "api", "GET",    "/api/backtest/runs"),
    ("/backtest", "backtest:run",    "运行回测",     "api", "POST",   "/api/backtest/run"),
    ("/backtest", "backtest:robust", "稳健性测试",   "api", "POST",   "/api/backtest/robust"),
    ("/backtest", "backtest:delete", "删除回测记录", "api", "DELETE", "/api/backtest/runs/{run_id}"),
    ("/backtest", "backtest:publish-tenant", "租户内公开回测记录", "api", "POST", "/api/backtest/runs/{run_id}/visibility"),
    ("/backtest", "backtest:publish-public", "全体公开回测记录",   "api", "POST", "/api/backtest/runs/{run_id}/visibility"),
    # B) 盘感训练（/training，login）
    ("/training", "training:view",   "查看训练记录", "api", "GET",    "/api/training/sessions"),
    ("/training", "training:start",  "创建训练",     "api", "POST",   "/api/training/sessions"),
    ("/training", "training:trade",  "训练过程操作", "api", "POST",   "/api/training/sessions/{sid}/trade"),
    ("/training", "training:review", "保存训练复盘", "api", "PATCH",  "/api/training/sessions/{sid}/review"),
    ("/training", "training:delete", "删除训练",     "api", "DELETE", "/api/training/sessions/{sid}"),
    # C) 配置管理拆页：评分/买卖为业务可授权，技术指标/系统设置仍 system-only
    ("/system/config/score", "score-profile:view",           "查看评分方案",       "api", "GET",    "/api/score-profiles"),
    ("/system/config/score", "score-profile:save",           "保存评分方案",       "api", "POST",   "/api/score-profiles"),
    ("/system/config/score", "score-profile:delete",         "删除评分方案",       "api", "DELETE", "/api/score-profiles/{pid}"),
    ("/system/config/score", "score-profile:publish-tenant", "租户内公开评分方案", "api", "POST",   "/api/score-profiles/{pid}/visibility"),
    ("/system/config/score", "score-profile:publish-public", "全体公开评分方案",   "api", "POST",   "/api/score-profiles/{pid}/visibility"),
    ("/system/config/trade", "trade-profile:view",    "查看买卖方案",     "api", "GET",    "/api/trade-profiles"),
    ("/system/config/trade", "trade-profile:save",    "保存买卖方案",     "api", "POST",   "/api/trade-profiles"),
    ("/system/config/trade", "trade-profile:delete",  "删除买卖方案",     "api", "DELETE", "/api/trade-profiles/{pid}"),
    ("/system/config/trade", "trade-profile:preview", "买卖条件试算",     "api", "POST",   "/api/trade-profiles/preview"),
    ("/system/config/trade", "trade-profile:publish-tenant", "租户内公开买卖方案", "api", "POST", "/api/trade-profiles/{pid}/visibility"),
    ("/system/config/trade", "trade-profile:publish-public", "全体公开买卖方案",   "api", "POST", "/api/trade-profiles/{pid}/visibility"),
    ("/system/config/system", "config:view",           "查看系统配置",     "api", "GET",    "/api/config"),
    ("/system/config/system", "config:reload",         "重载系统配置",     "api", "POST",   "/api/config/reload"),
    ("/system/config/tech", "indicator:def-manage",  "技术指标定义维护", "api", "POST",   "/api/indicators/def"),
    # C) 布局平台配置（system-only）
    ("/system/layout/presets",    "layout:preset-manage", "布局预设管理", "api", "POST", "/api/layout/presets"),
    ("/system/layout/pages",      "layout:page-manage",   "页面布局管理", "api", "POST", "/api/layout/pages/{page_key}"),
    ("/system/layout/components", "layout:field-policy",  "组件字段策略", "api", "POST", "/api/layout/field-policies"),
    # C) 数据管理（system-only；整 router 另挂 require_system，此处补精确码供扫描/审计）
    ("/data/overview", "data:overview",        "数据概览",         "api", "GET",  "/api/data/overview"),
    ("/data/overview", "data-status:view",     "数据状态/更新日志", "api", "GET",  "/api/data/status"),
    ("/data/quality",  "data-quality:view",    "数据质量查看",     "api", "GET",  "/api/data/quality"),
    ("/data/quality",  "data-quality:fix",     "数据质量处置",     "api", "POST", "/api/data/quality/fix-batch"),
    ("/data/schedule", "data-schedule:manage", "任务调度管理",     "api", "POST", "/api/data/schedules"),
    ("/data/schedule", "data-source:test",     "数据源测试",       "api", "POST", "/api/data/sources/test"),
    ("/data/schedule", "data-settings:manage", "数据设置保存",     "api", "POST", "/api/data/settings"),
    ("/data/ingest",   "data-task:manage",     "采集任务管理",     "api", "POST", "/api/data/tasks"),
    # ── 阶段五：平台能力（审计 + 字典）──
    ("/system/audit", "audit:view", "查看审计日志", "api", "GET", "/api/audit"),
    ("/board", "dict:read", "字典消费读（全站基线）", "api", "GET", "/api/dict/items/public"),
    ("/system/dicts", "dict:view", "查看数据字典", "api", "GET", "/api/dict/types"),
    ("/system/dicts", "dict:type-manage", "维护字典类型", "api", "POST", "/api/dict/types"),
    ("/system/dicts", "dict:item-manage", "维护字典项", "api", "POST", "/api/dict/items"),
)

# 默认授权：业务页所有登录用户可用；用户管理授予租户管理员（管本租户用户）；system 由 resolver 判全量。
_BUSINESS_MENU_CODES: tuple[str, ...] = (
    "quotes", "/stocks", "/board", "/screen", "/backtest", "/training",
    "system", "/system/config", "/system/config/score", "/system/config/trade")
_TENANT_ADMIN_EXTRA_MENUS: tuple[str, ...] = (
    "system", "permission", "/system/users", "/system/audit")
_USER_RESOURCE_CODES: tuple[str, ...] = (
    "user:list", "user:create", "user:update",
    "user:disable", "user:reset-password", "user:delete")
_TENANT_ADMIN_EXTRA_RESOURCE_CODES: tuple[str, ...] = (
    "score-profile:publish-tenant", "audit:view", *ASSET_TENANT_PUBLISH_RESOURCE_CODES)
_STAGE4_BUSINESS_GRANTS_MARKER = "migration.stage4_business_grants_v2"
_STAGE5_PLATFORM_CAPABILITIES_MARKER = "migration.stage5_platform_capabilities_v1"
_STAGE6_ASSET_VISIBILITY_MARKER = "migration.stage6_asset_visibility_v1"

_STAGE5_APP_CONFIG_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("auth.require_email_code", "true"),
    ("auth.login_captcha_enabled", "false"),
    ("auth.captcha_after_fails", "3"),
    ("audit.retention_days", "90"),
)

_SEED_DICT_TYPES: tuple[tuple[str, str, int, str], ...] = (
    ("role_type", "角色类型", 10, "系统内置角色类型"),
    ("user_status", "用户状态", 20, "用户账号状态"),
    ("audit_event_type", "审计事件类型", 30, "审计日志事件分类"),
    ("audit_result", "审计结果", 40, "审计日志处理结果"),
    ("audit_status", "审计状态", 50, "审计日志处理状态"),
)

_SEED_DICT_ITEMS: tuple[tuple[str, str, str, int], ...] = (
    ("role_type", ROLE_SYSTEM, "系统管理员", 10),
    ("role_type", ROLE_TENANT_ADMIN, "租户管理员", 20),
    ("role_type", ROLE_NORMAL, "普通用户", 30),
    ("role_type", ROLE_PAID, "付费用户", 40),
    ("user_status", "active", "启用", 10),
    ("user_status", "disabled", "停用", 20),
    ("user_status", "locked", "锁定", 30),
    ("audit_event_type", "api", "接口", 10),
    ("audit_event_type", "task", "任务", 20),
    ("audit_event_type", "security", "安全", 30),
    ("audit_event_type", "rbac", "权限", 40),
    ("audit_event_type", "config", "配置", 50),
    ("audit_event_type", "dict", "字典", 60),
    ("audit_result", "success", "成功", 10),
    ("audit_result", "failed", "失败", 20),
    ("audit_result", "denied", "拒绝", 30),
    ("audit_status", "completed", "完成", 10),
    ("audit_status", "running", "处理中", 20),
    ("audit_status", "failed", "异常", 30),
    ("audit_status", "blocked", "已阻断", 40),
    ("audit_status", "skipped", "已跳过", 50),
)


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
    # RBAC 平台表（阶段三）：sys_user 已在上面建好，此处按 FK 顺序建 6 表
    for name, sql in _RBAC_TABLES.items():
        client.execute(sql)
        created.append(name)
        log.debug("PG RBAC 表已就绪: %s", name)
    for idx_sql in _RBAC_INDEXES:
        client.execute(idx_sql)
    for idx_sql in _STAGE5_INDEXES:
        client.execute(idx_sql)
    _upgrade_score_profile_visibility(client)
    _upgrade_stage6_asset_visibility(client)
    # layout 主键以 user_id 打头，补归属索引便于按 owner 统计；其余表复合主键已覆盖归属查询
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_layout_user_config_owner "
        "ON layout_user_config (tenant_id, owner_user_id)")
    # sys_user 认证列升级（既有库 CREATE TABLE IF NOT EXISTS 不会补列，需幂等 ALTER；stage2·T1）
    client.execute("ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS role_code TEXT NOT NULL DEFAULT 'normal'")
    client.execute("ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS perm_ver INTEGER NOT NULL DEFAULT 0")
    client.execute("ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP")
    # email 部分唯一：允许多个 NULL（未填邮箱），非空则全局唯一
    client.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sys_user_email "
        "ON sys_user (email) WHERE email IS NOT NULL")
    seed_default_tenant(client)   # 先补 admin=system 的 role_code，供 seed_rbac 建 user_role 用
    seed_rbac(client)             # 内置角色/菜单树/功能点/默认授权 + 存量用户按 role_code 补 user_role
    seed_stage5_platform_capabilities(client)
    seed_stage6_asset_visibility(client)
    return created


def _upgrade_score_profile_visibility(client: PostgresClient) -> None:
    """补齐评分方案公开能力字段并回填平台预设可见性。"""
    client.execute(
        "ALTER TABLE score_profile "
        "ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'")
    client.execute("ALTER TABLE score_profile ADD COLUMN IF NOT EXISTS published_at TIMESTAMP")
    client.execute("ALTER TABLE score_profile ADD COLUMN IF NOT EXISTS published_by TEXT")
    client.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        "SELECT 1 FROM pg_constraint WHERE conname='score_profile_visibility_check'"
        ") THEN "
        "ALTER TABLE score_profile ADD CONSTRAINT score_profile_visibility_check "
        "CHECK (visibility IN ('private', 'tenant', 'public')); "
        "END IF; END $$;")
    client.execute(
        "UPDATE score_profile SET visibility='public', "
        "published_at=COALESCE(published_at, updated_at, created_at, now()), "
        "published_by=COALESCE(published_by, %s) "
        "WHERE tenant_id=%s AND owner_user_id=%s AND is_preset IS TRUE",
        [DEFAULT_OWNER_USER_ID, *PUBLIC_BOARD_OWNER],
    )
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_score_profile_visibility "
        "ON score_profile (visibility, tenant_id, owner_user_id)")


def _add_visibility_columns(client: PostgresClient, table: str, constraint_name: str) -> None:
    """为用户资产表补 private/tenant/public 可见性字段，兼容既有库。"""
    client.execute(
        f"ALTER TABLE {table} "
        "ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'")
    client.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS published_at TIMESTAMP")
    client.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS published_by TEXT")
    client.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        f"SELECT 1 FROM pg_constraint WHERE conname='{constraint_name}'"
        ") THEN "
        f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
        "CHECK (visibility IN ('private', 'tenant', 'public')); "
        "END IF; END $$;",
    )


def _upgrade_stage6_asset_visibility(client: PostgresClient) -> None:
    """补齐阶段六资产公开 DDL：筛选/买卖/回测可见性与审计字段变更。"""
    _add_visibility_columns(client, "screen_profile", "screen_profile_visibility_check")
    _add_visibility_columns(client, "trade_profile", "trade_profile_visibility_check")
    _add_visibility_columns(client, "backtest_run", "backtest_run_visibility_check")
    client.execute(
        "ALTER TABLE audit_log "
        "ADD COLUMN IF NOT EXISTS changes JSONB NOT NULL DEFAULT '[]'::jsonb")
    for idx_sql in _STAGE6_VISIBILITY_INDEXES:
        client.execute(idx_sql)


def _resolve_admin_password() -> tuple[str, bool]:
    """取管理员初始密码：优先环境变量 AI_STOCKS_ADMIN_PASSWORD，缺失则随机生成。

    返回 (密码明文, 是否随机生成)。密钥不入码——只读环境变量；随机值仅首次 seed 时落哈希。
    """
    pwd = os.environ.get("AI_STOCKS_ADMIN_PASSWORD")
    if pwd:
        return pwd, False
    return secrets.token_urlsafe(12), True


def seed_default_tenant(client: PostgresClient | None = None) -> None:
    """幂等 seed 默认租户 + 平台管理员（存量迁移与单测的归属落点）。

    管理员 admin 为平台系统管理员（role_code=system），并补可登录的初始密码哈希（stage2·T1）：
    - 新建：直接带 system 角色 + 初始密码哈希。
    - 既有（stage1 seed 的无密码 admin）：提升为 system、补 password_hash（仅当为空，不覆盖已设密码）。
    密码取 AI_STOCKS_ADMIN_PASSWORD，缺失则随机生成并**告警打印一次**（仅开发态，提示尽快改密/设环境变量）。
    """
    client = client or get_pg_client()
    client.execute(
        "INSERT INTO sys_tenant (id, name, status) VALUES (%s, %s, 'active') "
        "ON CONFLICT (id) DO NOTHING",
        [DEFAULT_TENANT_ID, "默认租户"],
    )
    # admin 现状：password_hash 是否为空 + 当前角色（既有库经上面 ALTER 后 role_code 默认 'normal'）
    df = client.query_df(
        "SELECT (password_hash IS NULL) AS no_pwd, role_code FROM sys_user WHERE id=%s",
        [DEFAULT_OWNER_USER_ID])
    if df.empty:
        pwd, generated = _resolve_admin_password()
        client.execute(
            "INSERT INTO sys_user (id, tenant_id, account, role_code, password_hash, status) "
            "VALUES (%s, %s, %s, %s, %s, 'active') ON CONFLICT (id) DO NOTHING",
            [DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID, DEFAULT_OWNER_USER_ID,
             ROLE_SYSTEM, hash_password(pwd)],
        )
        _warn_generated_admin_pwd(pwd, generated)
    else:
        if df.iloc[0]["role_code"] != ROLE_SYSTEM:
            client.execute(
                "UPDATE sys_user SET role_code=%s WHERE id=%s",
                [ROLE_SYSTEM, DEFAULT_OWNER_USER_ID])
        if bool(df.iloc[0]["no_pwd"]):
            pwd, generated = _resolve_admin_password()
            client.execute(
                "UPDATE sys_user SET password_hash=%s WHERE id=%s AND password_hash IS NULL",
                [hash_password(pwd), DEFAULT_OWNER_USER_ID])
            _warn_generated_admin_pwd(pwd, generated)
    client.execute(
        "UPDATE sys_tenant SET admin_user_id=%s WHERE id=%s AND admin_user_id IS NULL",
        [DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID],
    )


def _warn_generated_admin_pwd(pwd: str, generated: bool) -> None:
    """随机生成管理员密码时告警打印一次（开发态），便于首次登录；设了环境变量则静默。"""
    if generated:
        log.warning(
            "未设置 AI_STOCKS_ADMIN_PASSWORD，已为管理员 admin 生成随机初始密码：%s "
            "（仅本次显示，请尽快登录改密或改用环境变量；生产部署务必显式设置）", pwd)


def _flatten_menu_tree(tree: list, parent_code: str | None = None) -> list[dict]:
    """把嵌套菜单树展平为插入行（父在子前，保证 FK parent_id 可满足）。

    sort 按同级序号 *10（留改序空间）；有 children 记 group（route_path=None），否则 leaf(route_path=code)。
    """
    rows: list[dict] = []
    for i, (code, title, icon, visible, children) in enumerate(tree, start=1):
        is_group = bool(children)
        rows.append({
            "code": code, "parent_code": parent_code, "title": title,
            "type": "group" if is_group else "leaf",
            "route_path": None if is_group else code,
            "icon": icon, "sort": i * 10, "visible": visible,
        })
        if children:
            rows.extend(_flatten_menu_tree(children, code))
    return rows


def seed_rbac(client: PostgresClient | None = None) -> None:
    """幂等 seed 内置角色 / 菜单树 / 功能点 / 默认授权，并按 role_code 为存量用户补 sys_user_role。

    幂等策略：主体（角色/菜单/资源）ON CONFLICT (id) DO NOTHING。sys_menu 是运行期数据库事实源，
    seed 只补缺失内置节点，不覆盖已有菜单的父级、类型、路由、标题、图标、排序或可见性，避免重启
    抹掉「菜单与功能」页维护过的导航结构；默认授权仅在该角色**尚无任何 role_menu** 时首次写入
    （避免覆盖管理员后续在角色页的手工调整）；user_role 追加式 ON CONFLICT DO NOTHING。
    system 角色 seed 全量授权仅供角色页展示（全选+锁定）；运行时 system 由 perm_resolver 判全量兜底。
    """
    client = client or get_pg_client()
    # 1) 内置角色（id=code）
    for code, name, kind, is_locked, desc in _SEED_ROLES:
        client.execute(
            "INSERT INTO sys_role (id, code, name, kind, is_builtin, is_locked, description) "
            "VALUES (%s, %s, %s, %s, TRUE, %s, %s) ON CONFLICT (id) DO NOTHING",
            [code, code, name, kind, is_locked, desc])
    # 2) 菜单树（父在子前）
    menu_rows = _flatten_menu_tree(_SEED_MENU_TREE)
    for m in menu_rows:
        client.execute(
            "INSERT INTO sys_menu (id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE) "
            "ON CONFLICT (id) DO NOTHING",
            [m["code"], m["parent_code"], m["code"], m["title"], m["type"],
             m["route_path"], m["icon"], m["sort"], m["visible"]])
    # 3) 功能点/资源（id=code）
    for i, (menu_code, code, name, rtype, method, path) in enumerate(_SEED_RESOURCES, start=1):
        client.execute(
            "INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE) ON CONFLICT (id) DO NOTHING",
            [code, menu_code, code, name, rtype, method, path, i * 10])
        if (
            code == "score:run"
            or code.startswith("score-profile:")
            or code.startswith("screen-profile:")
            or code.startswith("trade-profile:")
            or code.startswith("backtest:publish-")
            or code in {"config:view", "config:reload", "indicator:def-manage"}
        ):
            client.execute(
                "UPDATE sys_resource SET menu_id=%s, name=%s, type=%s, api_method=%s, "
                "api_path=%s, is_builtin=TRUE WHERE id=%s",
                [menu_code, name, rtype, method, path, code])
    # 4) 默认授权（首次 seed + 存量库一次性回填）
    _seed_role_grants(client, [m["code"] for m in menu_rows])
    _backfill_config_split_builtin_grants(client)
    _backfill_stage4_builtin_business_grants(client)
    # 5) 存量用户 → sys_user_role（按 role_code JOIN 已存在的内置角色）
    client.execute(
        "INSERT INTO sys_user_role (user_id, role_id) "
        "SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.code = u.role_code "
        "ON CONFLICT (user_id, role_id) DO NOTHING")


def _seed_role_grants(client: PostgresClient, all_menu_codes: list[str]) -> None:
    """为内置角色写默认菜单/功能授权（仅当该角色尚无 role_menu，避免覆盖后续手工调整）。"""
    all_resource_codes = [r[1] for r in _SEED_RESOURCES]
    business = list(_BUSINESS_MENU_CODES)
    # (role_id, 菜单码集, 资源码集)
    # 阶段四（R21/R28）：normal/paid/tenant_admin 默认授研究业务功能码（BUSINESS_RESOURCE_CODES）；
    # tenant_admin 另含用户管理码和租户公开评分方案码。baseline（SHARED_RESOURCE_CODES）不入授权（由 resolve 强制注入）；
    # system-only 码不授非 system（挂 visible='system' 菜单，system_only_resource_ids 拦截）。
    biz_res = list(BUSINESS_RESOURCE_CODES)
    grants: list[tuple[str, list[str], list[str]]] = [
        (ROLE_SYSTEM, all_menu_codes, all_resource_codes),
        (ROLE_TENANT_ADMIN, business + list(_TENANT_ADMIN_EXTRA_MENUS),
         list(_USER_RESOURCE_CODES) + list(_TENANT_ADMIN_EXTRA_RESOURCE_CODES) + biz_res),
        (ROLE_NORMAL, business, biz_res),
        (ROLE_PAID, business, biz_res),   # 付费角色预留：暂同普通用户业务页，后续可在角色页调整
    ]
    for role_id, menu_codes, resource_codes in grants:
        # system 角色：锁定、不可手工编辑，始终**幂等补齐全量**——保证新增菜单/功能点即时纳入其全授权
        # （否则存量库新增资源后 system 出现授权缺口，角色页无法全选+锁定；见 test_system_role_full_grants）。
        if role_id == ROLE_SYSTEM:
            menu_codes = client.query_df("SELECT id FROM sys_menu")["id"].tolist()
            resource_codes = client.query_df("SELECT id FROM sys_resource")["id"].tolist()
        # 其它内置角色：仅首次写默认授权，避免覆盖管理员在角色页的后续手工调整。
        if role_id != ROLE_SYSTEM:
            df = client.query_df(
                "SELECT 1 FROM sys_role_menu WHERE role_id=%s LIMIT 1", [role_id])
            if not df.empty:
                continue   # 已配置过 → 不覆盖
        for mid in menu_codes:
            client.execute(
                "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING", [role_id, mid])
        for rid in resource_codes:
            client.execute(
                "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING", [role_id, rid])


def _backfill_config_split_builtin_grants(client: PostgresClient) -> None:
    """配置管理拆页结构回填：仅发现旧 `/score-profiles` 菜单时迁移，不重复覆盖 sys_menu。"""
    legacy = client.query_df("SELECT 1 FROM sys_menu WHERE id=%s", ["/score-profiles"])
    if legacy.empty:
        return
    client.execute("DELETE FROM sys_role_menu WHERE menu_id=%s", ["/score-profiles"])
    client.execute("DELETE FROM sys_menu WHERE id=%s", ["/score-profiles"])
    client.execute(
        "UPDATE sys_menu SET parent_id=%s, title=%s, type=%s, route_path=NULL, icon=%s, "
        "visible=%s, is_builtin=TRUE WHERE id=%s",
        ["system", "配置管理", "group", "Files", "login", "/system/config"],
    )
def _backfill_stage4_builtin_business_grants(client: PostgresClient) -> None:
    """一次性补齐阶段四内置业务角色授权，并修正 R28 默认 publish 边界。

    不能依赖 _seed_role_grants 的“角色已有任意 role_menu 即跳过”策略，否则既有库拿不到
    阶段四新增业务码；也不能每次启动都重加，否则会覆盖管理员后续手工调整。用 app_config
    迁移标记保证只执行一次，执行后 bump 受影响用户 perm_ver。
    """
    marker = client.query_df("SELECT 1 FROM app_config WHERE key=%s", [_STAGE4_BUSINESS_GRANTS_MARKER])
    if not marker.empty:
        return

    business_menus = list(_BUSINESS_MENU_CODES)
    business_resources = list(BUSINESS_RESOURCE_CODES)
    changed = 0

    with client.transaction() as conn, conn.cursor() as cur:
        for role_id in (ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID):
            menus = business_menus + (list(_TENANT_ADMIN_EXTRA_MENUS) if role_id == ROLE_TENANT_ADMIN else [])
            resources = (
                business_resources
                + (
                    list(_USER_RESOURCE_CODES) + list(_TENANT_ADMIN_EXTRA_RESOURCE_CODES)
                    if role_id == ROLE_TENANT_ADMIN
                    else []
                )
            )
            for mid in menus:
                cur.execute(
                    "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    [role_id, mid],
                )
                changed += max(cur.rowcount, 0)
            for rid in resources:
                cur.execute(
                    "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    [role_id, rid],
                )
                changed += max(cur.rowcount, 0)

        cur.execute(
            "DELETE FROM sys_role_resource "
            "WHERE role_id IN (%s, %s) AND resource_id=%s",
            [ROLE_NORMAL, ROLE_PAID, "score-profile:publish-tenant"],
        )
        changed += max(cur.rowcount, 0)

        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s, %s))",
                [ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [_STAGE4_BUSINESS_GRANTS_MARKER, '{"applied":true}'],
        )


def seed_stage5_platform_capabilities(client: PostgresClient | None = None) -> None:
    """阶段五平台能力 seed：默认配置、首批字典、既有库 tenant_admin 审计授权回填。

    `dict:read` 是登录基线共享读码，运行时由 `perm_resolver.resolve` 注入，不落
    role_resource 授权行；迁移标记首次落地时 bump 非 system 有角色用户，让旧 token/perms
    快照失效后重新解析到新增 baseline。
    """
    client = client or get_pg_client()
    for key, value in _STAGE5_APP_CONFIG_DEFAULTS:
        client.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO NOTHING",
            [key, value],
        )
    for code, name, sort, remark in _SEED_DICT_TYPES:
        client.execute(
            "INSERT INTO dict_type (id, code, name, sort, remark) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING",
            [code, code, name, sort, remark],
        )
    for type_code, code, label, sort in _SEED_DICT_ITEMS:
        item_id = f"{type_code}:{code}"
        client.execute(
            "INSERT INTO dict_item (id, type_code, code, label, sort) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (type_code, code) DO NOTHING",
            [item_id, type_code, code, label, sort],
        )
    _backfill_stage5_platform_grants(client)


def _backfill_stage5_platform_grants(client: PostgresClient) -> None:
    """既有库阶段五权限回填：tenant_admin 审计入口 + 新 baseline 权限快照失效。"""
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_STAGE5_PLATFORM_CAPABILITIES_MARKER])
    if not marker.empty:
        return

    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            [ROLE_TENANT_ADMIN, "/system/audit"],
        )
        cur.execute(
            "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            [ROLE_TENANT_ADMIN, "audit:view"],
        )
        cur.execute(
            "UPDATE sys_user u SET perm_ver=perm_ver+1 "
            "WHERE EXISTS ("
            "  SELECT 1 FROM sys_user_role ur JOIN sys_role r ON r.id = ur.role_id "
            "  WHERE ur.user_id = u.id AND r.code <> %s"
            ") AND NOT EXISTS ("
            "  SELECT 1 FROM sys_user_role sur JOIN sys_role sr ON sr.id = sur.role_id "
            "  WHERE sur.user_id = u.id AND (sr.code = %s OR sr.kind = 'system')"
            ")",
            [ROLE_SYSTEM, ROLE_SYSTEM],
        )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [_STAGE5_PLATFORM_CAPABILITIES_MARKER, '{"applied":true}'],
        )


def seed_stage6_asset_visibility(client: PostgresClient | None = None) -> None:
    """阶段六资产公开权限回填：tenant_admin 获得租户公开，public 仅 system。"""
    client = client or get_pg_client()
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_STAGE6_ASSET_VISIBILITY_MARKER])
    if not marker.empty:
        return

    tenant_publish = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES)
    public_publish = list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    changed = 0
    with client.transaction() as conn, conn.cursor() as cur:
        for rid in tenant_publish:
            cur.execute(
                "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [ROLE_TENANT_ADMIN, rid],
            )
            changed += max(cur.rowcount, 0)

        cur.execute(
            "DELETE FROM sys_role_resource "
            "WHERE role_id IN (%s, %s) AND resource_id = ANY(%s)",
            [ROLE_NORMAL, ROLE_PAID, tenant_publish + public_publish],
        )
        changed += max(cur.rowcount, 0)

        cur.execute(
            "DELETE FROM sys_role_resource "
            "WHERE role_id=%s AND resource_id = ANY(%s)",
            [ROLE_TENANT_ADMIN, public_publish],
        )
        changed += max(cur.rowcount, 0)

        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s, %s))",
                [ROLE_TENANT_ADMIN, ROLE_NORMAL, ROLE_PAID],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [_STAGE6_ASSET_VISIBILITY_MARKER, '{"applied":true}'],
        )


def asset_pk_mismatches(client: PostgresClient | None = None) -> list[str]:
    """返回**已存在但主键与期望复合主键不一致**的资产表（旧单主键 schema 升级检测）。

    用于从早期 stage1（单列主键）升级：CREATE TABLE IF NOT EXISTS 不会改既有表主键，
    需经 recreate_asset_tables 重建。表不存在的不算（init 会建对）。
    """
    client = client or get_pg_client()
    existing = set(list_pg_tables(client))
    bad: list[str] = []
    for t, expected in ASSET_PK.items():
        if t not in existing:
            continue
        df = client.query_df(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) "
            "WHERE i.indrelid=%s::regclass AND i.indisprimary", [t])
        actual = set(df["attname"].tolist()) if not df.empty else set()
        if actual and actual != set(expected):
            bad.append(t)
    return bad


def recreate_asset_tables(client: PostgresClient | None = None) -> list[str]:
    """DROP + 重建全部资产表（从旧 schema 升级用；数据由 migrate-rbac 从 DuckDB 重载）。

    **破坏性**：会清空 PG 侧资产表。仅在确认数据源在 DuckDB（可重迁）时使用。
    """
    client = client or get_pg_client()
    for t in _ASSET_TABLES:
        client.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    log.warning("已 DROP %d 张资产表，准备按复合主键重建", len(_ASSET_TABLES))
    return init_pg_db(client)


def list_pg_tables(client: PostgresClient | None = None) -> list[str]:
    """列出 PG public schema 下所有表名。"""
    client = client or get_pg_client()
    df = client.query_df(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    )
    return df["table_name"].tolist() if not df.empty else []
