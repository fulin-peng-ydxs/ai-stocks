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

import json
import os
import secrets

from backend.auth.constants import (
    ASSET_PUBLIC_PUBLISH_RESOURCE_CODES,
    ASSET_TENANT_PUBLISH_RESOURCE_CODES,
    BUSINESS_RESOURCE_CODES,
    ROLE_NORMAL,
    ROLE_SYSTEM,
    ROLE_TENANT_ADMIN,
    TRADE_DISCIPLINE_RESOURCE_CODES,
)
from backend.auth.security import hash_password
from backend.common.logging import get_logger
from backend.storage.pg_client import PostgresClient, get_pg_client

log = get_logger("storage.pg_ddl")

# 存量迁移与单测的默认归属落点（见 R3 迁移方案）
DEFAULT_TENANT_ID = "default"
DEFAULT_OWNER_USER_ID = "admin"

# 平台公共榜单归属（stage4·C1 已确认）：每日榜单公共读**有意固定**此归属（default/admin
# 平台槽），全员登录用户共享同一份、**不按当前用户过滤**；榜单按需物化 / public-board CLI 以此归属
# 生产公共预设 score_snapshot，结果维护只显式标记快照 stale。属"有意全局"，**禁止**后续按
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
    updated_at    TIMESTAMP,
    deleted_at    TIMESTAMP                          -- 逻辑删除标记；非空=已删（与 status 正交）
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
    deleted_at    TIMESTAMP,                         -- 逻辑删除标记；非空=已删（与 status 正交）
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
    kind        TEXT NOT NULL DEFAULT 'custom',   -- system|tenant_admin|normal（系统内置）| custom（自建）
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

DDL_BOARD_WATCHLIST = f"""
CREATE TABLE IF NOT EXISTS board_watchlist (
{_OWN}    board_code  TEXT,
    board_name  TEXT NOT NULL,
    board_type  TEXT NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_user_id, board_code)
);
"""


# ── 交易纪律（私人规则、正式版本、生命周期事件与履约修订）──────────────

DDL_TRADE_DISCIPLINE_RULE = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_rule (
    id                  TEXT,
{_OWN}    name                TEXT,
    normalized_name     TEXT,
    status              TEXT NOT NULL DEFAULT 'unpublished',
    latest_version_no   INTEGER,
    next_activation_seq BIGINT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ,
    CHECK (status IN ('unpublished', 'active', 'archived')),
    CONSTRAINT td_rule_lifecycle_consistency_check
    CHECK ((status = 'unpublished' AND latest_version_no IS NULL)
        OR (status IN ('active', 'archived') AND latest_version_no > 0
            AND btrim(coalesce(name, '')) <> ''
            AND btrim(coalesce(normalized_name, '')) <> '')),
    CHECK (next_activation_seq >= 0),
    PRIMARY KEY (tenant_id, owner_user_id, id)
);
"""

DDL_TRADE_DISCIPLINE_RULE_NAME_CLAIM = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_rule_name_claim (
{_OWN}    normalized_name TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    claimed_name    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (btrim(normalized_name) <> ''),
    PRIMARY KEY (tenant_id, owner_user_id, normalized_name),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE CASCADE
);
"""

DDL_TRADE_DISCIPLINE_RULE_VERSION = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_rule_version (
    rule_id        TEXT,
{_OWN}    version_no     INTEGER,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    capital         NUMERIC(20, 2) NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (version_no > 0),
    CHECK (btrim(name) <> '' AND btrim(normalized_name) <> ''),
    CHECK (capital > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_STOCK_RULE = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_stock_rule (
    rule_id       TEXT,
{_OWN}    version_no    INTEGER,
    detail_id     TEXT,
    name          TEXT NOT NULL,
    max_capital   NUMERIC(20, 2),
    content       TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (btrim(name) <> '' AND btrim(content) <> ''),
    CHECK (display_order > 0),
    CHECK (NOT enabled OR (max_capital IS NOT NULL AND max_capital > 0)),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, version_no, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_ACTION_RULE = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_action_rule (
    rule_id       TEXT,
{_OWN}    version_no    INTEGER,
    detail_id     TEXT,
    name          TEXT NOT NULL,
    action_type   TEXT NOT NULL,
    action_subtype TEXT NOT NULL,
    content       TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (btrim(name) <> '' AND btrim(content) <> ''),
    CHECK (btrim(action_subtype) <> ''),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, version_no, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, version_no, action_type, display_order),
    UNIQUE (tenant_id, owner_user_id, rule_id, version_no, detail_id, action_type),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_RULE_DRAFT = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_rule_draft (
    rule_id        TEXT,
{_OWN}    draft_revision INTEGER NOT NULL DEFAULT 1,
    proposed_name  TEXT,
    normalized_name TEXT,
    capital         NUMERIC(20, 2),
    source_version_no INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (draft_revision > 0),
    CHECK (capital IS NULL OR capital >= 0),
    CHECK (source_version_no IS NULL OR source_version_no > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, source_version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_DRAFT_STOCK_RULE = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_draft_stock_rule (
    rule_id       TEXT,
{_OWN}    detail_id     TEXT,
    name          TEXT,
    max_capital   NUMERIC(20, 2),
    content       TEXT,
    display_order INTEGER NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (max_capital IS NULL OR max_capital >= 0),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule_draft
            (tenant_id, owner_user_id, rule_id) ON DELETE CASCADE
);
"""

DDL_TRADE_DISCIPLINE_DRAFT_ACTION_RULE = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_draft_action_rule (
    rule_id       TEXT,
{_OWN}    detail_id     TEXT,
    name          TEXT,
    action_type   TEXT,
    action_subtype TEXT,
    content       TEXT,
    display_order INTEGER NOT NULL,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (action_type IS NULL OR action_type IN ('buy', 'sell')),
    CHECK (action_subtype IS NULL OR btrim(action_subtype) <> ''),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, rule_id, detail_id),
    UNIQUE (tenant_id, owner_user_id, rule_id, action_type, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule_draft
            (tenant_id, owner_user_id, rule_id) ON DELETE CASCADE
);
"""

DDL_TRADE_DISCIPLINE_ACTION_SUBTYPE = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_action_subtype (
{_OWN}    normalized_name TEXT NOT NULL,
    name            TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (btrim(name) <> ''),
    CHECK (action_type IN ('buy', 'sell')),
    PRIMARY KEY (tenant_id, owner_user_id, normalized_name)
);
"""

DDL_TRADE_DISCIPLINE_RULE_ACTIVATION = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_rule_activation (
    id            TEXT,
{_OWN}    rule_id       TEXT NOT NULL,
    event_seq     BIGINT NOT NULL,
    event_type    TEXT NOT NULL,
    version_no    INTEGER NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    activated_at  TIMESTAMPTZ NOT NULL,
    effective_from_trade_date DATE NOT NULL,
    CHECK (event_seq > 0),
    CHECK (event_type IN ('publish', 'archive', 'restore')),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, rule_id, event_seq),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_CHECKIN = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_checkin (
    id                  TEXT,
{_OWN}    rule_id             TEXT NOT NULL,
    trade_date          DATE NOT NULL,
    current_revision_no INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'submitted',
    submission_source   TEXT NOT NULL DEFAULT 'workbench',
    submitted_at        TIMESTAMPTZ NOT NULL,
    amended_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (current_revision_no > 0),
    CHECK (status IN ('submitted', 'amended')),
    CONSTRAINT td_checkin_submission_source_check
    CHECK (submission_source IN ('workbench', 'quick_no_operation')),
    CONSTRAINT td_checkin_status_time_check
    CHECK ((status = 'submitted' AND amended_at IS NULL)
        OR (status = 'amended' AND amended_at IS NOT NULL)),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, rule_id, trade_date),
    FOREIGN KEY (tenant_id, owner_user_id, rule_id)
        REFERENCES trade_discipline_rule (tenant_id, owner_user_id, id) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_CHECKIN_REVISION = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_checkin_revision (
    checkin_id      TEXT,
{_OWN}    revision_no    INTEGER,
    rule_id         TEXT NOT NULL,
    version_no      INTEGER NOT NULL,
    revision_kind   TEXT NOT NULL,
    assessment      TEXT NOT NULL,
    no_operation    BOOLEAN NOT NULL,
    violation_detail TEXT,
    review_note     TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    CHECK (revision_no > 0),
    CHECK (revision_kind IN ('initial', 'amendment')),
    CONSTRAINT td_revision_kind_no_check
    CHECK ((revision_kind = 'initial' AND revision_no = 1)
        OR (revision_kind = 'amendment' AND revision_no > 1)),
    CONSTRAINT td_revision_assessment_check
    CHECK (assessment IN ('complied', 'partial', 'breached')),
    CONSTRAINT td_revision_violation_detail_check
    CHECK ((assessment IN ('partial', 'breached') AND btrim(coalesce(violation_detail, '')) <> '')
        OR (assessment = 'complied' AND violation_detail IS NULL)),
    PRIMARY KEY (tenant_id, owner_user_id, checkin_id, revision_no),
    UNIQUE (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no),
    FOREIGN KEY (tenant_id, owner_user_id, checkin_id)
        REFERENCES trade_discipline_checkin (tenant_id, owner_user_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no)
        REFERENCES trade_discipline_rule_version
            (tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_REASON = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_reason (
    id              TEXT,
{_OWN}    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    CHECK (btrim(name) <> '' AND btrim(normalized_name) <> ''),
    CHECK ((is_active AND deleted_at IS NULL) OR (NOT is_active AND deleted_at IS NOT NULL)),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, normalized_name)
);
"""

DDL_TRADE_DISCIPLINE_VIOLATION = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_violation (
    checkin_id    TEXT,
{_OWN}    revision_no  INTEGER,
    reason_code   TEXT,
    reason_id     TEXT,
    reason_name_snapshot TEXT NOT NULL,
    CHECK ((reason_code IS NOT NULL AND reason_id IS NULL)
        OR (reason_code IS NULL AND reason_id IS NOT NULL)),
    CHECK (btrim(reason_name_snapshot) <> ''),
    PRIMARY KEY (tenant_id, owner_user_id, checkin_id, revision_no),
    FOREIGN KEY (tenant_id, owner_user_id, checkin_id, revision_no)
        REFERENCES trade_discipline_checkin_revision
            (tenant_id, owner_user_id, checkin_id, revision_no) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, reason_id)
        REFERENCES trade_discipline_reason (tenant_id, owner_user_id, id) ON DELETE RESTRICT
);
"""

DDL_TRADE_DISCIPLINE_OPERATION = f"""
CREATE TABLE IF NOT EXISTS trade_discipline_operation (
    id             TEXT,
{_OWN}    checkin_id     TEXT NOT NULL,
    revision_no    INTEGER NOT NULL,
    rule_id         TEXT NOT NULL,
    version_no      INTEGER NOT NULL,
    stock_code      TEXT NOT NULL,
    stock_name_snapshot TEXT NOT NULL,
    side            TEXT NOT NULL,
    stock_rule_id   TEXT NOT NULL,
    action_rule_id  TEXT NOT NULL,
    price            NUMERIC(20, 4),
    quantity         NUMERIC(20, 4),
    amount           NUMERIC(20, 2),
    fee              NUMERIC(20, 2),
    operated_at      TIMESTAMPTZ,
    note             TEXT,
    compliance_status TEXT,
    display_order    INTEGER NOT NULL,
    CHECK (side IN ('buy', 'sell')),
    CONSTRAINT td_operation_compliance_status_check
    CHECK (compliance_status IS NULL OR compliance_status IN ('complied', 'breached')),
    CHECK (btrim(stock_code) <> '' AND btrim(stock_name_snapshot) <> ''),
    CHECK (price IS NULL OR price >= 0),
    CHECK (quantity IS NULL OR quantity >= 0),
    CHECK (amount IS NULL OR amount >= 0),
    CHECK (fee IS NULL OR fee >= 0),
    CHECK (display_order > 0),
    PRIMARY KEY (tenant_id, owner_user_id, id),
    UNIQUE (tenant_id, owner_user_id, checkin_id, revision_no, display_order),
    FOREIGN KEY (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no)
        REFERENCES trade_discipline_checkin_revision
            (tenant_id, owner_user_id, checkin_id, revision_no, rule_id, version_no) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no, stock_rule_id)
        REFERENCES trade_discipline_stock_rule
            (tenant_id, owner_user_id, rule_id, version_no, detail_id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, owner_user_id, rule_id, version_no, action_rule_id, side)
        REFERENCES trade_discipline_action_rule
            (tenant_id, owner_user_id, rule_id, version_no, detail_id, action_type) ON DELETE RESTRICT
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
    param_hash      TEXT,
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


# ── 布局配置与用户偏好 ────────────────────────────────────────────

DDL_LAYOUT_PRESET = """
CREATE TABLE IF NOT EXISTS layout_preset (
    key            TEXT PRIMARY KEY,
    name           TEXT,
    description    TEXT,
    config         TEXT,
    enabled        BOOLEAN,
    is_builtin     BOOLEAN,
    schema_version INTEGER,
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);
"""

DDL_LAYOUT_PAGE_CONFIG = """
CREATE TABLE IF NOT EXISTS layout_page_config (
    page_key       TEXT PRIMARY KEY,
    preset_key     TEXT,
    config         TEXT,
    schema_version INTEGER,
    updated_at     TIMESTAMP
);
"""

DDL_LAYOUT_FIELD_POLICY = """
CREATE TABLE IF NOT EXISTS layout_field_policy (
    component_kind TEXT,
    field          TEXT,
    allowed_layers TEXT,
    updated_at     TIMESTAMP,
    PRIMARY KEY (component_kind, field)
);
"""


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

DDL_USER_PREFERENCE = f"""
CREATE TABLE IF NOT EXISTS user_preference (
{_OWN}    scope          TEXT NOT NULL,
    page_key       TEXT NOT NULL DEFAULT '',
    pref_key       TEXT NOT NULL,
    value          TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_user_id, scope, page_key, pref_key)
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
    source_event_key TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DDL_LIMIT_LADDER_TASK_LEDGER = """
CREATE TABLE IF NOT EXISTS limit_ladder_task_ledger (
    command_id          TEXT PRIMARY KEY,
    task_id             TEXT,
    trade_date          DATE NOT NULL,
    source              TEXT NOT NULL CHECK (
        source IN ('auto_first_load', 'auto_invalid_refresh', 'admin_recompute')
    ),
    actor_kind          TEXT NOT NULL CHECK (actor_kind IN ('system', 'user')),
    tenant_id           TEXT,
    actor_user_id       TEXT,
    actor_account       TEXT NOT NULL,
    trigger_tenant_id   TEXT,
    trigger_user_id     TEXT,
    trigger_account     TEXT,
    request_ip          TEXT,
    request_method      TEXT,
    request_path        TEXT,
    request_id          TEXT,
    status              TEXT NOT NULL CHECK (
        status IN ('requested', 'running', 'succeeded', 'failed', 'interrupted')
    ),
    rule_version        TEXT NOT NULL,
    result_summary      JSONB,
    retry_count         INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (actor_kind = 'system' AND tenant_id IS NULL AND actor_user_id IS NULL
            AND actor_account = 'system:limit-ladder')
        OR (actor_kind = 'user' AND tenant_id IS NOT NULL AND actor_user_id IS NOT NULL)
    )
);
"""

DDL_LIMIT_LADDER_AUDIT_OUTBOX = """
CREATE TABLE IF NOT EXISTS limit_ladder_audit_outbox (
    command_id       TEXT NOT NULL REFERENCES limit_ladder_task_ledger(command_id) ON DELETE RESTRICT,
    event_type       TEXT NOT NULL CHECK (
        event_type IN ('requested', 'running', 'succeeded', 'failed', 'interrupted')
    ),
    source_event_key TEXT NOT NULL,
    payload          JSONB NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered')),
    retry_count      INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    next_retry_at    TIMESTAMPTZ,
    last_error       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at     TIMESTAMPTZ,
    PRIMARY KEY (command_id, event_type),
    UNIQUE (source_event_key)
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
    color      TEXT,
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
    "board_watchlist": ["tenant_id", "owner_user_id", "board_code"],
    "trade_discipline_rule": ["tenant_id", "owner_user_id", "id"],
    "trade_discipline_rule_name_claim": ["tenant_id", "owner_user_id", "normalized_name"],
    "trade_discipline_rule_version": ["tenant_id", "owner_user_id", "rule_id", "version_no"],
    "trade_discipline_stock_rule": [
        "tenant_id", "owner_user_id", "rule_id", "version_no", "detail_id"],
    "trade_discipline_action_subtype": [
        "tenant_id", "owner_user_id", "normalized_name"],
    "trade_discipline_action_rule": [
        "tenant_id", "owner_user_id", "rule_id", "version_no", "detail_id"],
    "trade_discipline_rule_draft": ["tenant_id", "owner_user_id", "rule_id"],
    "trade_discipline_draft_stock_rule": [
        "tenant_id", "owner_user_id", "rule_id", "detail_id"],
    "trade_discipline_draft_action_rule": [
        "tenant_id", "owner_user_id", "rule_id", "detail_id"],
    "trade_discipline_rule_activation": ["tenant_id", "owner_user_id", "id"],
    "trade_discipline_checkin": ["tenant_id", "owner_user_id", "id"],
    "trade_discipline_checkin_revision": [
        "tenant_id", "owner_user_id", "checkin_id", "revision_no"],
    "trade_discipline_reason": ["tenant_id", "owner_user_id", "id"],
    "trade_discipline_violation": [
        "tenant_id", "owner_user_id", "checkin_id", "revision_no"],
    "trade_discipline_operation": ["tenant_id", "owner_user_id", "id"],
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
    "user_preference": ["tenant_id", "owner_user_id", "scope", "page_key", "pref_key"],
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
    "board_watchlist": DDL_BOARD_WATCHLIST,
    "trade_discipline_rule": DDL_TRADE_DISCIPLINE_RULE,
    "trade_discipline_rule_name_claim": DDL_TRADE_DISCIPLINE_RULE_NAME_CLAIM,
    "trade_discipline_rule_version": DDL_TRADE_DISCIPLINE_RULE_VERSION,
    "trade_discipline_stock_rule": DDL_TRADE_DISCIPLINE_STOCK_RULE,
    "trade_discipline_action_subtype": DDL_TRADE_DISCIPLINE_ACTION_SUBTYPE,
    "trade_discipline_action_rule": DDL_TRADE_DISCIPLINE_ACTION_RULE,
    "trade_discipline_rule_draft": DDL_TRADE_DISCIPLINE_RULE_DRAFT,
    "trade_discipline_draft_stock_rule": DDL_TRADE_DISCIPLINE_DRAFT_STOCK_RULE,
    "trade_discipline_draft_action_rule": DDL_TRADE_DISCIPLINE_DRAFT_ACTION_RULE,
    "trade_discipline_rule_activation": DDL_TRADE_DISCIPLINE_RULE_ACTIVATION,
    "trade_discipline_checkin": DDL_TRADE_DISCIPLINE_CHECKIN,
    "trade_discipline_checkin_revision": DDL_TRADE_DISCIPLINE_CHECKIN_REVISION,
    "trade_discipline_reason": DDL_TRADE_DISCIPLINE_REASON,
    "trade_discipline_violation": DDL_TRADE_DISCIPLINE_VIOLATION,
    "trade_discipline_operation": DDL_TRADE_DISCIPLINE_OPERATION,
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
    "user_preference": DDL_USER_PREFERENCE,
}

# 无归属列的表（骨架 + 平台配置）
_OTHER_TABLES: dict[str, str] = {
    "sys_tenant": DDL_SYS_TENANT,
    "sys_user": DDL_SYS_USER,
    "app_config": DDL_APP_CONFIG,
    "layout_preset": DDL_LAYOUT_PRESET,
    "layout_page_config": DDL_LAYOUT_PAGE_CONFIG,
    "layout_field_policy": DDL_LAYOUT_FIELD_POLICY,
    "audit_log": DDL_AUDIT_LOG,
    "limit_ladder_task_ledger": DDL_LIMIT_LADDER_TASK_LEDGER,
    "limit_ladder_audit_outbox": DDL_LIMIT_LADDER_AUDIT_OUTBOX,
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

_LIMIT_LADDER_INDEXES: tuple[str, ...] = (
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_log_source_event_key "
        "ON audit_log (source_event_key) WHERE source_event_key IS NOT NULL"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_limit_ladder_active_trade_date "
        "ON limit_ladder_task_ledger (trade_date) WHERE status IN ('requested', 'running')"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_limit_ladder_task_id "
        "ON limit_ladder_task_ledger (task_id) WHERE task_id IS NOT NULL"
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_limit_ladder_outbox_delivery "
        "ON limit_ladder_audit_outbox (status, next_retry_at, created_at)"
    ),
)

_STAGE6_VISIBILITY_INDEXES: tuple[str, ...] = (
    ("CREATE INDEX IF NOT EXISTS idx_screen_profile_visibility "
     "ON screen_profile (visibility, tenant_id, owner_user_id)"),
    ("CREATE INDEX IF NOT EXISTS idx_trade_profile_visibility "
     "ON trade_profile (visibility, tenant_id, owner_user_id)"),
    ("CREATE INDEX IF NOT EXISTS idx_backtest_run_visibility "
     "ON backtest_run (visibility, tenant_id, owner_user_id)"),
)

_TRADE_DISCIPLINE_INDEXES: tuple[str, ...] = (
    ("CREATE INDEX IF NOT EXISTS idx_td_rule_owner_status "
     "ON trade_discipline_rule (tenant_id, owner_user_id, status, updated_at DESC) "
     "WHERE deleted_at IS NULL"),
    ("CREATE INDEX IF NOT EXISTS idx_td_activation_effective "
     "ON trade_discipline_rule_activation "
     "(tenant_id, owner_user_id, rule_id, effective_from_trade_date DESC, event_seq DESC)"),
    ("CREATE INDEX IF NOT EXISTS idx_td_checkin_history "
     "ON trade_discipline_checkin "
     "(tenant_id, owner_user_id, trade_date DESC, updated_at DESC)"),
    ("CREATE INDEX IF NOT EXISTS idx_td_revision_detail "
     "ON trade_discipline_checkin_revision "
     "(tenant_id, owner_user_id, checkin_id, revision_no DESC)"),
    ("CREATE INDEX IF NOT EXISTS idx_td_operation_stock "
     "ON trade_discipline_operation "
     "(tenant_id, owner_user_id, stock_code, checkin_id, revision_no)"),
    ("CREATE INDEX IF NOT EXISTS idx_td_violation_reason_name "
     "ON trade_discipline_violation "
     "(tenant_id, owner_user_id, lower(reason_name_snapshot), checkin_id, revision_no)"),
)

_TRADE_DISCIPLINE_POINTER_CONSTRAINTS: tuple[str, ...] = (
    ("DO $$ DECLARE item RECORD; BEGIN FOR item IN "
     "SELECT c.conname,c.conrelid FROM pg_constraint c WHERE c.contype='c' "
     "AND c.conrelid IN ('trade_discipline_action_rule'::regclass, "
     "'trade_discipline_draft_action_rule'::regclass) "
     "AND pg_get_constraintdef(c.oid) LIKE '%%action_subtype%%' LOOP "
     "EXECUTE format('ALTER TABLE %%s DROP CONSTRAINT %%I', item.conrelid::regclass, "
     "item.conname); END LOOP; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_action_type_check') THEN "
     "ALTER TABLE trade_discipline_action_rule ADD CONSTRAINT "
     "td_action_type_check CHECK (action_type IN ('buy','sell')); "
     "END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_action_subtype_nonblank_check') THEN "
     "ALTER TABLE trade_discipline_action_rule ADD CONSTRAINT "
     "td_action_subtype_nonblank_check CHECK (btrim(action_subtype) <> ''); "
     "END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_draft_action_subtype_nonblank_check') THEN "
     "ALTER TABLE trade_discipline_draft_action_rule ADD CONSTRAINT "
     "td_draft_action_subtype_nonblank_check "
     "CHECK (action_subtype IS NULL OR btrim(action_subtype) <> ''); "
     "END IF; END $$;"),
    ("ALTER TABLE trade_discipline_checkin ADD COLUMN IF NOT EXISTS "
     "submission_source TEXT NOT NULL DEFAULT 'workbench'"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_checkin_submission_source_check') THEN "
     "ALTER TABLE trade_discipline_checkin ADD CONSTRAINT td_checkin_submission_source_check "
     "CHECK (submission_source IN ('workbench','quick_no_operation')); END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_rule_lifecycle_consistency_check') THEN "
     "ALTER TABLE trade_discipline_rule "
     "ADD CONSTRAINT td_rule_lifecycle_consistency_check "
     "CHECK ((status='unpublished' AND latest_version_no IS NULL) "
     "OR (status IN ('active','archived') AND latest_version_no > 0 "
     "AND btrim(coalesce(name,'')) <> '' "
     "AND btrim(coalesce(normalized_name,'')) <> '')); END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_checkin_status_time_check') THEN "
     "ALTER TABLE trade_discipline_checkin "
     "ADD CONSTRAINT td_checkin_status_time_check "
     "CHECK ((status='submitted' AND amended_at IS NULL) "
     "OR (status='amended' AND amended_at IS NOT NULL)); END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_revision_kind_no_check') THEN "
     "ALTER TABLE trade_discipline_checkin_revision "
     "ADD CONSTRAINT td_revision_kind_no_check "
     "CHECK ((revision_kind='initial' AND revision_no=1) "
     "OR (revision_kind='amendment' AND revision_no>1)); END IF; END $$;"),
    ("ALTER TABLE trade_discipline_operation ADD COLUMN IF NOT EXISTS "
     "compliance_status TEXT"),
    ("DO $$ DECLARE item RECORD; BEGIN FOR item IN SELECT c.conname "
     "FROM pg_constraint c WHERE c.conrelid="
     "'trade_discipline_checkin_revision'::regclass AND c.contype='c' "
     "AND pg_get_constraintdef(c.oid) LIKE '%%assessment%%' "
     "AND c.conname NOT IN ('td_revision_assessment_check',"
     "'td_revision_violation_detail_check') LOOP EXECUTE format("
     "'ALTER TABLE trade_discipline_checkin_revision DROP CONSTRAINT %%I',"
     "item.conname); END LOOP; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_revision_assessment_check') THEN "
     "ALTER TABLE trade_discipline_checkin_revision ADD CONSTRAINT "
     "td_revision_assessment_check CHECK "
     "(assessment IN ('complied','partial','breached')); END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_revision_violation_detail_check') THEN "
     "ALTER TABLE trade_discipline_checkin_revision ADD CONSTRAINT "
     "td_revision_violation_detail_check CHECK "
     "((assessment IN ('partial','breached') AND "
     "btrim(coalesce(violation_detail,'')) <> '') OR "
     "(assessment='complied' AND violation_detail IS NULL)); END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_operation_compliance_status_check') THEN "
     "ALTER TABLE trade_discipline_operation ADD CONSTRAINT "
     "td_operation_compliance_status_check CHECK "
     "(compliance_status IS NULL OR "
     "compliance_status IN ('complied','breached')); END IF; END $$;"),
    ("DO $$ DECLARE item RECORD; BEGIN FOR item IN "
     "SELECT c.conname FROM pg_constraint c WHERE c.conrelid="
     "'trade_discipline_rule_name_claim'::regclass AND c.contype='u' AND "
     "(SELECT array_agg(a.attname ORDER BY k.ordinality) "
     "FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ordinality) "
     "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum)="
     "ARRAY['tenant_id','owner_user_id','rule_id']::name[] LOOP "
     "EXECUTE format('ALTER TABLE trade_discipline_rule_name_claim DROP CONSTRAINT %%I', "
     "item.conname); END LOOP; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_rule_latest_version_fk') THEN "
     "ALTER TABLE trade_discipline_rule ADD CONSTRAINT td_rule_latest_version_fk "
     "FOREIGN KEY (tenant_id, owner_user_id, id, latest_version_no) "
     "REFERENCES trade_discipline_rule_version "
     "(tenant_id, owner_user_id, rule_id, version_no) ON DELETE RESTRICT; END IF; END $$;"),
    ("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
     "WHERE conname='td_checkin_current_revision_fk') THEN "
     "ALTER TABLE trade_discipline_checkin ADD CONSTRAINT td_checkin_current_revision_fk "
     "FOREIGN KEY (tenant_id, owner_user_id, id, current_revision_no) "
     "REFERENCES trade_discipline_checkin_revision "
     "(tenant_id, owner_user_id, checkin_id, revision_no) "
     "DEFERRABLE INITIALLY DEFERRED; END IF; END $$;"),
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
)

# 菜单树 seed：承接前端 menuConfig（emoji→Element Plus 图标名），新增「系统管理→权限管理」子组。
# 每项 (code, title, icon(EP名|None), visible, children)；有 children→group（route_path=None），否则→leaf(route_path=code)。
# visible=system 仅系统管理员可见；「系统管理/权限管理」分组与「用户管理」用 login，
# 因租户管理员（非 system）经授权也要能进用户管理，其上级分组不能被 system-only 挡死。
_SEED_MENU_TREE: list = [
    ("quotes", "最新行情", "TrendCharts", "login", [
        ("/stocks", "个股行情", None, "login", []),
        ("/sectors", "板块行情", None, "login", []),
        ("/board", "每日榜单", None, "login", []),
        ("/limit-ladder", "连板天梯", None, "login", []),
    ]),
    ("/screen", "策略筛选", "Filter", "login", []),
    ("/backtest", "策略回测", "DataLine", "login", []),
    ("/training", "盘感训练", "Aim", "login", []),
    ("/trade-discipline", "交易纪律", "Checked", "login", []),
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
    # A) baseline 登录基线：共享读 + 当前用户自持久化偏好写。挂 login 叶子作 FK 锚点；
    #    运行时由 perm_resolver 强制注入，见 SHARED_RESOURCE_CODES。不得挂 visible='system' 菜单。
    ("/board",  "layout:view",         "布局生效配置读（全站基线）", "api", "GET", "/api/layout/effective/{page_key}"),
    ("/board",  "layout:user-config",  "保存个人页面偏好（基线）",   "api", "POST", "/api/layout/users/{page_key}"),
    ("/board",  "user-preference:manage", "保存个人通用偏好（基线）", "api", "POST", "/api/user-preferences"),
    ("/board",  "trade-calendar:view", "交易日历读（全站基线）",     "api", "GET", "/api/data/trade-dates"),
    ("/screen", "indicator:registry",  "指标目录读（研究基线）",     "api", "GET", "/api/indicators/registry"),
    # B) 每日榜单（/board，login）
    ("/board", "board:view",         "查看每日榜单",     "api", "POST", "/api/board/run"),
    ("/board", "board:compute",      "榜单即时计算",     "api", "GET",  "/api/board/compute"),
    # 连板天梯查看属于业务默认授权；管理员重算归属同一业务页，system-only 由资源元数据与接口硬守卫表达。
    ("/limit-ladder", "limit-ladder:view", "查看连板天梯", "api", "GET",
     "/api/limit-ladder/{trade_date}"),
    ("/limit-ladder", "limit-ladder:recompute", "重算连板天梯", "api", "POST",
     "/api/limit-ladder/{trade_date}/recompute"),
    ("/system/config/score", "score:run", "评分方案打分", "api", "POST", "/api/score-profiles/run"),
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
    # 板块行情（/sectors，login，板块概念 R22/T10a）
    ("/sectors", "sectors:view",             "查看板块行情", "api", "GET",    "/api/sectors"),
    ("/sectors", "sector-watchlist:view",    "查看板块自选", "api", "GET",    "/api/sectors/watchlist"),
    ("/sectors", "sector-watchlist:update", "维护板块自选", "api", "POST",   "/api/sectors/watchlist"),
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
    # 交易纪律由独立 marker 状态机创建和授权；通用 seed 循环会显式跳过这四项。
    ("/trade-discipline", "trade-discipline:view", "查看交易纪律", "api", "GET",
     "/api/trade-discipline/summary"),
    ("/trade-discipline", "trade-discipline:rule-manage", "维护交易规则", "api", "POST",
     "/api/trade-discipline/rules"),
    ("/trade-discipline", "trade-discipline:checkin-view", "查看履约记录", "api", "GET",
     "/api/trade-discipline/checkins"),
    ("/trade-discipline", "trade-discipline:checkin-submit", "提交履约记录", "api", "POST",
     "/api/trade-discipline/checkins"),
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
    "quotes", "/stocks", "/sectors", "/board", "/limit-ladder", "/screen", "/backtest", "/training",
    "system", "/system/config", "/system/config/score", "/system/config/trade")
_TENANT_ADMIN_EXTRA_MENUS: tuple[str, ...] = (
    "system", "permission", "/system/users")
_USER_RESOURCE_CODES: tuple[str, ...] = (
    "user:list", "user:create", "user:update",
    "user:disable", "user:reset-password", "user:delete")
_TENANT_ADMIN_EXTRA_RESOURCE_CODES: tuple[str, ...] = (
    *ASSET_TENANT_PUBLISH_RESOURCE_CODES,)
_STAGE4_BUSINESS_GRANTS_MARKER = "migration.stage4_business_grants_v2"
_SECTOR_WATCHLIST_GRANTS_MARKER = "migration.sector_watchlist_grants_v1"
_SECTOR_MENU_GRANTS_MARKER = "migration.sector_menu_grants_v1"
_STAGE5_PLATFORM_CAPABILITIES_MARKER = "migration.stage5_platform_capabilities_v1"
_STAGE6_ASSET_VISIBILITY_MARKER = "migration.stage6_asset_visibility_v1"
# 仅作「已应用」幂等标记；回滚采用确定性基线恢复（见 asset-publish-open.sql），不依赖 marker 内容。
_ASSET_PUBLISH_OPEN_MARKER = "migration.asset_publish_open_v2"
# 迁移并发互斥用的事务级 advisory lock key（固定常量，避免多实例并发启动时重复执行/重复 bump）
_ASSET_PUBLISH_OPEN_LOCK = 8410010002
_TENANT_ADMIN_AUDIT_REVOKE_MARKER = "migration.tenant_admin_audit_default_revoke_v1"
_DICT_ITEM_COLOR_BACKFILL_MARKER = "migration.dict_item_color_defaults_v1"
_CONFIG_SPLIT_MENU_DISCOVERY_MARKER = "migration.config_split_menu_discovery_v1"
_CONFIG_SPLIT_MENU_DISCOVERY_LOCK = 8410010006
_LIMIT_LADDER_RECOMPUTE_ANCHOR_MARKER = "migration.limit_ladder_recompute_anchor_v1"
_LIMIT_LADDER_RECOMPUTE_ANCHOR_LOCK = 8410010008
_LEGACY_SCORE_PROFILES_MENU_ID = "/score-profiles"
TRADE_DISCIPLINE_RBAC_MARKER = "migration.trade_discipline_default_grants_v1"
TRADE_DISCIPLINE_RBAC_LOCK = 8410010005
_TRADE_DISCIPLINE_MENU_ID = "/trade-discipline"
_TRADE_DISCIPLINE_MARKER_VERSION = 1

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

_SEED_DICT_ITEMS: tuple[tuple[str, str, str, int, str], ...] = (
    ("role_type", ROLE_SYSTEM, "系统管理员", 10, "#F56C6C"),
    ("role_type", ROLE_TENANT_ADMIN, "租户管理员", 20, "#409EFF"),
    ("role_type", ROLE_NORMAL, "普通用户", 30, "#67C23A"),
    ("user_status", "active", "启用", 10, "#67C23A"),
    ("user_status", "disabled", "停用", 20, "#909399"),
    ("user_status", "locked", "锁定", 30, "#F56C6C"),
    ("audit_event_type", "api", "接口", 10, "#67C23A"),
    ("audit_event_type", "task", "任务", 20, "#909399"),
    ("audit_event_type", "security", "安全", 30, "#F56C6C"),
    ("audit_event_type", "rbac", "权限", 40, "#67C23A"),
    ("audit_event_type", "config", "配置", 50, "#67C23A"),
    ("audit_event_type", "dict", "字典", 60, "#67C23A"),
    ("audit_result", "success", "成功", 10, "#67C23A"),
    ("audit_result", "failed", "失败", 20, "#F56C6C"),
    ("audit_result", "denied", "拒绝", 30, "#F56C6C"),
    ("audit_status", "completed", "完成", 10, "#67C23A"),
    ("audit_status", "running", "处理中", 20, "#E6A23C"),
    ("audit_status", "failed", "异常", 30, "#F56C6C"),
    ("audit_status", "blocked", "已阻断", 40, "#909399"),
    ("audit_status", "skipped", "已跳过", 50, "#909399"),
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
    # CREATE TABLE IF NOT EXISTS does not add columns to an existing audit table.
    client.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS source_event_key TEXT")
    for idx_sql in _LIMIT_LADDER_INDEXES:
        client.execute(idx_sql)
    for constraint_sql in _TRADE_DISCIPLINE_POINTER_CONSTRAINTS:
        client.execute(constraint_sql)
    for idx_sql in _TRADE_DISCIPLINE_INDEXES:
        client.execute(idx_sql)
    _protect_legacy_config_secrets(client)
    _upgrade_dict_item_color(client)
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
    # 逻辑删除列（既有库补列，幂等；与 status 正交）
    client.execute("ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP")
    client.execute("ALTER TABLE sys_tenant ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP")
    # email 部分唯一：允许多个 NULL（未填邮箱），非空则全局唯一
    client.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sys_user_email "
        "ON sys_user (email) WHERE email IS NOT NULL")
    seed_default_tenant(client)   # 先补 admin=system 的 role_code，供 seed_rbac 建 user_role 用
    seed_rbac(client)             # 内置角色/菜单树/功能点/默认授权 + 无角色存量用户补 user_role
    _remove_legacy_paid_role(client)
    seed_stage5_platform_capabilities(client)
    revoke_tenant_admin_audit_default_grants(client)
    seed_stage6_asset_visibility(client)
    _backfill_asset_publish_open_v1(client)
    # 评分快照 meta 参数指纹列（既有库补列，幂等）：指标参数变更后读取时按指纹判定失效，见 scoring/snapshot.py
    client.execute(
        "ALTER TABLE score_snapshot_meta ADD COLUMN IF NOT EXISTS param_hash TEXT")
    return created


def _protect_legacy_config_secrets(client: PostgresClient) -> None:
    """把历史敏感明文升级为密文，并原位脱敏关联审计。

    有主密钥时自动加密迁移；没有主密钥时删除历史明文，避免为了兼容继续暴露凭证。已经
    带版本前缀的密文保持不变。该检查不使用一次性 marker，可防滚动升级或旧工具回灌明文。
    """
    from backend.storage.app_config import (
        ENCRYPTED_CONFIG_PATHS,
        protect_serialized_config_value,
    )

    paths = sorted(ENCRYPTED_CONFIG_PATHS)
    if not paths:
        return
    lowered_paths = [path.lower() for path in paths]
    rows = client.query_df("SELECT key, value FROM app_config WHERE key = ANY(%s)", [paths])
    with client.transaction() as conn, conn.cursor() as cur:
        for _, row in rows.iterrows():
            key = str(row["key"])
            protected = protect_serialized_config_value(key, row["value"])
            if protected is None:
                cur.execute("DELETE FROM app_config WHERE key=%s", [key])
                log.warning("已删除无法安全迁移的敏感配置明文: %s", key)
            elif protected != row["value"]:
                cur.execute(
                    "UPDATE app_config SET value=%s, updated_at=now() WHERE key=%s",
                    [protected, key],
                )
        cur.execute(
            """
            UPDATE audit_log AS audit
            SET changes = (
                SELECT coalesce(jsonb_agg(
                    CASE
                        WHEN lower(item.value->>'field') = ANY(%s)
                        THEN item.value || jsonb_build_object(
                            'before', '已变更',
                            'after', '已变更'
                        )
                        ELSE item.value
                    END
                    ORDER BY item.ordinality
                ), '[]'::jsonb) AS value
                FROM jsonb_array_elements(coalesce(audit.changes, '[]'::jsonb))
                     WITH ORDINALITY AS item(value, ordinality)
            )
            WHERE EXISTS (
                SELECT 1
                FROM jsonb_array_elements(coalesce(audit.changes, '[]'::jsonb)) AS entry
                WHERE lower(entry->>'field') = ANY(%s)
            )
            """,
            [lowered_paths, lowered_paths],
        )


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
    _add_publish_consistency_check(client, "score_profile")
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_score_profile_visibility "
        "ON score_profile (visibility, tenant_id, owner_user_id)")


def _add_publish_consistency_check(client: PostgresClient, table: str) -> None:
    """加 DB 级发布字段一致性约束(P6):private 行不得带 published_at/published_by。

    先清洗历史/旁路脏写,避免加约束失败;约束用 pg_constraint 存在性判定,幂等。
    """
    constraint_name = f"{table}_publish_consistency_check"
    client.execute(
        f"UPDATE {table} SET published_at=NULL, published_by=NULL "
        "WHERE visibility='private' AND (published_at IS NOT NULL OR published_by IS NOT NULL)")
    client.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        f"SELECT 1 FROM pg_constraint WHERE conname='{constraint_name}'"
        ") THEN "
        f"ALTER TABLE {table} ADD CONSTRAINT {constraint_name} "
        "CHECK ((visibility='private' AND published_at IS NULL AND published_by IS NULL) "
        "OR visibility IN ('tenant', 'public')); "
        "END IF; END $$;",
    )


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
    _add_publish_consistency_check(client, table)


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


def _upgrade_dict_item_color(client: PostgresClient) -> None:
    """补齐字典项颜色列，并仅首次为内置字典项填充默认色。"""
    client.execute("ALTER TABLE dict_item ADD COLUMN IF NOT EXISTS color TEXT")
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_DICT_ITEM_COLOR_BACKFILL_MARKER])
    if not marker.empty:
        return
    for type_code, code, _label, _sort, color in _SEED_DICT_ITEMS:
        client.execute(
            "UPDATE dict_item SET color=%s "
            "WHERE type_code=%s AND code=%s AND color IS NULL",
            [color, type_code, code],
        )
    client.execute(
        "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO NOTHING",
        [_DICT_ITEM_COLOR_BACKFILL_MARKER, '{"applied":true}'],
    )


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


def _trade_discipline_resource_rows() -> tuple[tuple[str, str, str, str, str, str], ...]:
    """返回交易纪律固定资源契约，供独立 seed/校验共享。"""
    codes = set(TRADE_DISCIPLINE_RESOURCE_CODES)
    return tuple(row for row in _SEED_RESOURCES if row[1] in codes)


def _trade_discipline_marker_state(raw: object) -> tuple[str, dict | None]:
    """严格解析交易纪律 RBAC marker；未知结构一律判 invalid。"""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return "invalid", None
    if not isinstance(value, dict):
        return "invalid", None
    expected_keys = {
        "version", "applied", "rolled_back", "inserted_menu_ids",
        "inserted_resource_ids", "inserted_role_menus", "inserted_role_resources",
    }
    if (
        set(value) != expected_keys
        or type(value.get("version")) is not int
        or value["version"] != _TRADE_DISCIPLINE_MARKER_VERSION
    ):
        return "invalid", None
    if not isinstance(value.get("applied"), bool) or not isinstance(value.get("rolled_back"), bool):
        return "invalid", None
    list_keys = ("inserted_menu_ids", "inserted_resource_ids")
    if any(not isinstance(value.get(key), list) for key in list_keys):
        return "invalid", None
    if any(not isinstance(item, str) for key in list_keys for item in value[key]):
        return "invalid", None
    if len(value["inserted_menu_ids"]) != 1 or len(value["inserted_resource_ids"]) != 4:
        return "invalid", None
    pair_keys = ("inserted_role_menus", "inserted_role_resources")
    for key in pair_keys:
        rows = value.get(key)
        if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != 2
            or any(not isinstance(item, str) for item in row)
            for row in rows
        ):
            return "invalid", None
    if len(value["inserted_role_menus"]) != 3 or len(value["inserted_role_resources"]) != 12:
        return "invalid", None
    expected_roles = (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL)
    expected_resources = list(TRADE_DISCIPLINE_RESOURCE_CODES)
    if value["inserted_menu_ids"] != [_TRADE_DISCIPLINE_MENU_ID]:
        return "invalid", None
    if value["inserted_resource_ids"] != expected_resources:
        return "invalid", None
    if value["inserted_role_menus"] != [
        [role_id, _TRADE_DISCIPLINE_MENU_ID] for role_id in expected_roles
    ]:
        return "invalid", None
    if value["inserted_role_resources"] != [
        [role_id, resource_id]
        for role_id in expected_roles
        for resource_id in expected_resources
    ]:
        return "invalid", None
    if value["applied"] is True and value["rolled_back"] is False:
        return "applied", value
    if value["applied"] is False and value["rolled_back"] is True:
        return "rolled_back", value
    return "invalid", None


def _validate_trade_discipline_applied_cur(cur, _ledger: dict) -> None:
    """applied marker 只校验稳定身份，不冻结管理员可维护的菜单与功能点配置。"""
    cur.execute(
        "SELECT id, code FROM sys_menu WHERE id=%s",
        [_TRADE_DISCIPLINE_MENU_ID],
    )
    menu = cur.fetchone()
    expected_menu = (_TRADE_DISCIPLINE_MENU_ID, _TRADE_DISCIPLINE_MENU_ID)
    if menu != expected_menu:
        raise RuntimeError("交易纪律 RBAC marker 已应用，但菜单契约缺失或被占用")
    cur.execute(
        "SELECT count(*) FROM sys_menu WHERE id=%s OR code=%s",
        [_TRADE_DISCIPLINE_MENU_ID] * 2,
    )
    if cur.fetchone()[0] != 1:
        raise RuntimeError("交易纪律 RBAC marker 已应用，但菜单身份存在额外占用")
    for _, code, *_ in _trade_discipline_resource_rows():
        cur.execute(
            "SELECT id, code FROM sys_resource WHERE id=%s",
            [code],
        )
        if cur.fetchone() != (code, code):
            raise RuntimeError(f"交易纪律 RBAC marker 已应用，但资源契约异常: {code}")
    # normal/tenant_admin 的初始行是“默认授权”，管理员可在角色页撤销；重启不得补回或失败。
    # ledger 仍保留迁移最初插入的精确身份，供回滚时删除当前仍存在的同键行。


def _validate_trade_discipline_rollback_grants_cur(cur, ledger: dict) -> None:
    """回滚允许默认授权被撤销，但不得级联删除账本外自定义角色授权。"""
    expected_menus = set(map(tuple, ledger["inserted_role_menus"]))
    cur.execute(
        "SELECT role_id, menu_id FROM sys_role_menu WHERE menu_id = ANY(%s)",
        [ledger["inserted_menu_ids"]],
    )
    actual_menus = set(cur.fetchall())
    if not actual_menus <= expected_menus:
        raise RuntimeError("交易纪律菜单存在迁移账本外授权，拒绝级联回滚")
    expected_resources = set(map(tuple, ledger["inserted_role_resources"]))
    cur.execute(
        "SELECT role_id, resource_id FROM sys_role_resource WHERE resource_id = ANY(%s)",
        [ledger["inserted_resource_ids"]],
    )
    actual_resources = set(cur.fetchall())
    if not actual_resources <= expected_resources:
        raise RuntimeError("交易纪律资源存在迁移账本外授权，拒绝级联回滚")


def _clear_trade_discipline_perm_cache(_client: PostgresClient, user_ids: list[str]) -> None:
    """提交后 best-effort 清权限缓存；权威失效边界仍是事务内 perm_ver。"""
    if not user_ids:
        return
    try:
        from backend.auth.perm_resolver import clear_perms_cache

        clear_perms_cache(user_ids)
    except Exception:
        log.warning("交易纪律 RBAC 迁移清权限缓存失败（忽略）", exc_info=True)


def _seed_trade_discipline_rbac(client: PostgresClient | None = None) -> dict:
    """独立状态机写入交易纪律菜单、四资源和默认角色授权。"""
    client = client or get_pg_client()
    affected: list[str] = []
    result = {"state": "unknown", "inserted": 0, "affected_users": 0}
    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [TRADE_DISCIPLINE_RBAC_LOCK])
        cur.execute("SELECT value FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER])
        row = cur.fetchone()
        if row is not None:
            state, ledger = _trade_discipline_marker_state(row[0])
            if state == "rolled_back":
                return {"state": state, "inserted": 0, "affected_users": 0}
            if state != "applied" or ledger is None:
                raise RuntimeError("交易纪律 RBAC marker 非法，已 fail-closed")
            _validate_trade_discipline_applied_cur(cur, ledger)
            return {"state": state, "inserted": 0, "affected_users": 0}

        cur.execute(
            "SELECT id FROM sys_menu WHERE id=%s OR code=%s OR route_path=%s LIMIT 1",
            [_TRADE_DISCIPLINE_MENU_ID] * 3,
        )
        if cur.fetchone() is not None:
            raise RuntimeError("交易纪律菜单身份已被占用，拒绝自动收编")
        resource_ids = list(TRADE_DISCIPLINE_RESOURCE_CODES)
        cur.execute(
            "SELECT id FROM sys_resource WHERE id = ANY(%s) OR code = ANY(%s) LIMIT 1",
            [resource_ids, resource_ids],
        )
        if cur.fetchone() is not None:
            raise RuntimeError("交易纪律资源身份已被占用，拒绝自动收编")

        cur.execute(
            "INSERT INTO sys_menu "
            "(id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, NULL, %s, '交易纪律', 'leaf', %s, 'Checked', 50, 'login', TRUE) "
            "RETURNING id",
            [_TRADE_DISCIPLINE_MENU_ID] * 3,
        )
        inserted_menu_ids = [cur.fetchone()[0]]
        inserted_resource_ids: list[str] = []
        for index, (menu_id, code, name, rtype, method, path) in enumerate(
            _trade_discipline_resource_rows(), start=1
        ):
            cur.execute(
                "INSERT INTO sys_resource "
                "(id, menu_id, code, name, type, api_method, api_path, sort, is_builtin) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE) RETURNING id",
                [code, menu_id, code, name, rtype, method, path, index * 10],
            )
            inserted_resource_ids.append(cur.fetchone()[0])

        inserted_role_menus: list[list[str]] = []
        inserted_role_resources: list[list[str]] = []
        for role_id in (ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL):
            cur.execute(
                "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) RETURNING role_id, menu_id",
                [role_id, _TRADE_DISCIPLINE_MENU_ID],
            )
            inserted_role_menus.append(list(cur.fetchone()))
            for resource_id in inserted_resource_ids:
                cur.execute(
                    "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                    "RETURNING role_id, resource_id",
                    [role_id, resource_id],
                )
                inserted_role_resources.append(list(cur.fetchone()))

        ledger = {
            "version": _TRADE_DISCIPLINE_MARKER_VERSION,
            "applied": True,
            "rolled_back": False,
            "inserted_menu_ids": inserted_menu_ids,
            "inserted_resource_ids": inserted_resource_ids,
            "inserted_role_menus": inserted_role_menus,
            "inserted_role_resources": inserted_role_resources,
        }
        cur.execute(
            "UPDATE sys_user u SET perm_ver=perm_ver+1 WHERE "
            "u.role_code=%s OR EXISTS (SELECT 1 FROM sys_user_role ur "
            "WHERE ur.user_id=u.id AND ur.role_id = ANY(%s)) RETURNING u.id",
            [ROLE_SYSTEM, [ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL]],
        )
        affected = [row[0] for row in cur.fetchall()]
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now())",
            [TRADE_DISCIPLINE_RBAC_MARKER, json.dumps(ledger, ensure_ascii=False)],
        )
        result = {
            "state": "applied",
            "inserted": len(inserted_menu_ids) + len(inserted_resource_ids)
            + len(inserted_role_menus) + len(inserted_role_resources),
            "affected_users": len(affected),
            "marker": ledger,
        }
    _clear_trade_discipline_perm_cache(client, affected)
    return result


def _rollback_trade_discipline_rbac(client: PostgresClient | None = None) -> dict:
    """按 marker 实际插入账本确定性回滚交易纪律 RBAC，业务表保持不动。"""
    client = client or get_pg_client()
    affected: list[str] = []
    result: dict = {}
    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [TRADE_DISCIPLINE_RBAC_LOCK])
        cur.execute("SELECT value FROM app_config WHERE key=%s", [TRADE_DISCIPLINE_RBAC_MARKER])
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("交易纪律 RBAC marker 不存在，拒绝破坏性回滚")
        state, ledger = _trade_discipline_marker_state(row[0])
        if state == "rolled_back" and ledger is not None:
            return {"state": state, "deleted": 0, "affected_users": 0, "marker": ledger}
        if state != "applied" or ledger is None:
            raise RuntimeError("交易纪律 RBAC marker 非法，拒绝破坏性回滚")
        _validate_trade_discipline_applied_cur(cur, ledger)
        _validate_trade_discipline_rollback_grants_cur(cur, ledger)

        deleted = 0
        for role_id, resource_id in reversed(ledger["inserted_role_resources"]):
            cur.execute(
                "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
                [role_id, resource_id],
            )
            deleted += max(cur.rowcount or 0, 0)
        for role_id, menu_id in reversed(ledger["inserted_role_menus"]):
            cur.execute(
                "DELETE FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
                [role_id, menu_id],
            )
            deleted += max(cur.rowcount or 0, 0)
        for resource_id in reversed(ledger["inserted_resource_ids"]):
            cur.execute("DELETE FROM sys_resource WHERE id=%s", [resource_id])
            deleted += max(cur.rowcount or 0, 0)
        for menu_id in reversed(ledger["inserted_menu_ids"]):
            cur.execute("DELETE FROM sys_menu WHERE id=%s", [menu_id])
            deleted += max(cur.rowcount or 0, 0)

        cur.execute(
            "UPDATE sys_user u SET perm_ver=perm_ver+1 WHERE "
            "u.role_code=%s OR EXISTS (SELECT 1 FROM sys_user_role ur "
            "WHERE ur.user_id=u.id AND ur.role_id = ANY(%s)) RETURNING u.id",
            [ROLE_SYSTEM, [ROLE_SYSTEM, ROLE_TENANT_ADMIN, ROLE_NORMAL]],
        )
        affected = [row[0] for row in cur.fetchall()]
        tombstone = {**ledger, "applied": False, "rolled_back": True}
        cur.execute(
            "UPDATE app_config SET value=%s, updated_at=now() WHERE key=%s",
            [json.dumps(tombstone, ensure_ascii=False), TRADE_DISCIPLINE_RBAC_MARKER],
        )
        result = {
            "state": "rolled_back", "deleted": deleted,
            "affected_users": len(affected), "marker": tombstone,
        }
    _clear_trade_discipline_perm_cache(client, affected)
    return result


def seed_rbac(client: PostgresClient | None = None) -> None:
    """幂等 seed 内置角色 / 菜单树 / 功能点 / 默认授权，并为无角色存量用户补 sys_user_role。

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
    _seed_menu_rows(client, menu_rows, excluded_codes={_TRADE_DISCIPLINE_MENU_ID})
    # 3) 功能点/资源（id=code）
    _seed_resource_rows(
        client,
        _SEED_RESOURCES,
        excluded_codes=set(TRADE_DISCIPLINE_RESOURCE_CODES),
    )
    _migrate_limit_ladder_recompute_anchor(client)
    # 4) 默认授权（首次 seed + 存量库一次性回填）
    _seed_role_grants(client, [m["code"] for m in menu_rows])
    _record_config_split_legacy_menu_state(client)
    _backfill_stage4_builtin_business_grants(client)
    _backfill_sector_watchlist_grants(client)
    _backfill_sector_menu_grants(client)
    # 5) 仅为尚无任何角色的存量用户按遗留 role_code 补角色。sys_user_role 是权限事实源；
    # 已有自定义角色时不得再追加 role_code=normal，否则每次启动都会扩大最小权限账号的授权。
    client.execute(
        "INSERT INTO sys_user_role (user_id, role_id) "
        "SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.code = u.role_code "
        "WHERE NOT EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id) "
        "ON CONFLICT (user_id, role_id) DO NOTHING")
    _seed_trade_discipline_rbac(client)


def _seed_menu_rows(
    client: PostgresClient,
    menu_rows: list[dict],
    *,
    excluded_codes: set[str] | None = None,
) -> None:
    """只补缺失菜单；现有行的全部运行时配置由数据库保留。"""
    excluded_codes = excluded_codes or set()
    for m in menu_rows:
        if m["code"] in excluded_codes:
            continue
        client.execute(
            "INSERT INTO sys_menu (id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE) "
            "ON CONFLICT (id) DO NOTHING",
            [m["code"], m["parent_code"], m["code"], m["title"], m["type"],
             m["route_path"], m["icon"], m["sort"], m["visible"]])


def _seed_resource_rows(
    client: PostgresClient,
    resource_rows: tuple[tuple[str, str, str, str, str, str], ...],
    *,
    excluded_codes: set[str] | None = None,
) -> None:
    """只补缺失功能点；现有绑定、名称、接口描述和排序不由启动 seed 覆盖。"""
    excluded_codes = excluded_codes or set()
    for i, (menu_code, code, name, rtype, method, path) in enumerate(resource_rows, start=1):
        if code in excluded_codes:
            continue
        client.execute(
            "INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE) ON CONFLICT (id) DO NOTHING",
            [code, menu_code, code, name, rtype, method, path, i * 10])


def _migrate_limit_ladder_recompute_anchor(client: PostgresClient) -> None:
    """把历史默认锚点从“数据采集”迁回“连板天梯”，并保留管理员自定义归属。

    旧实现借 system 菜单表达 system-only，导致权限码出现在错误的管理分组。迁移只改仍保持旧默认
    `/data/ingest` 的内置资源；已在正确位置时幂等通过，其他归属视为管理员自定义并原样保留。
    """
    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_LIMIT_LADDER_RECOMPUTE_ANCHOR_LOCK])
        cur.execute(
            "SELECT 1 FROM app_config WHERE key=%s",
            [_LIMIT_LADDER_RECOMPUTE_ANCHOR_MARKER],
        )
        if cur.fetchone():
            return
        cur.execute(
            "SELECT menu_id, is_builtin FROM sys_resource "
            "WHERE id=%s AND code=%s FOR UPDATE",
            ["limit-ladder:recompute", "limit-ladder:recompute"],
        )
        row = cur.fetchone()
        state = "missing"
        previous_menu_id = None
        if row:
            previous_menu_id = row[0]
            if row[0] == "/data/ingest" and bool(row[1]):
                cur.execute(
                    "UPDATE sys_resource SET menu_id=%s, updated_at=now() WHERE id=%s",
                    ["/limit-ladder", "limit-ladder:recompute"],
                )
                state = "migrated"
            elif row[0] == "/limit-ladder":
                state = "already_current"
            else:
                state = "preserved_custom"
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO NOTHING",
            [
                _LIMIT_LADDER_RECOMPUTE_ANCHOR_MARKER,
                json.dumps(
                    {"applied": True, "state": state, "previous_menu_id": previous_menu_id},
                    ensure_ascii=False,
                ),
            ],
        )


def _remove_legacy_paid_role(client: PostgresClient) -> None:
    """幂等移除历史付费角色，受影响用户迁移为普通用户并立即失效旧权限快照。

    角色关联是权限事实源，迁移先给受影响用户补 normal，再删除历史角色。`role_code` 只作为
    登录响应兼容字段，按迁移后的真实角色优先级重新归一，避免同时拥有 system/tenant_admin
    的用户被错误降级。
    """
    legacy_code = "paid"
    affected_df = client.query_df(
        "SELECT DISTINCT u.id FROM sys_user u "
        "LEFT JOIN sys_user_role ur ON ur.user_id=u.id "
        "LEFT JOIN sys_role r ON r.id=ur.role_id "
        "WHERE u.role_code=%s OR r.code=%s OR r.kind=%s",
        [legacy_code, legacy_code, legacy_code],
    )
    affected = affected_df["id"].tolist() if not affected_df.empty else []

    with client.transaction() as conn, conn.cursor() as cur:
        if affected:
            cur.execute(
                "INSERT INTO sys_user_role (user_id, role_id) "
                "SELECT id, %s FROM sys_user WHERE id=ANY(%s) "
                "ON CONFLICT (user_id, role_id) DO NOTHING",
                [ROLE_NORMAL, affected],
            )
        cur.execute(
            "DELETE FROM sys_user_role WHERE role_id IN ("
            "SELECT id FROM sys_role WHERE code=%s OR kind=%s)",
            [legacy_code, legacy_code],
        )
        cur.execute(
            "DELETE FROM sys_role WHERE code=%s OR kind=%s",
            [legacy_code, legacy_code],
        )
        if affected:
            cur.execute(
                "UPDATE sys_user u SET role_code=CASE "
                "WHEN EXISTS (SELECT 1 FROM sys_user_role ur JOIN sys_role r ON r.id=ur.role_id "
                "  WHERE ur.user_id=u.id AND (r.code=%s OR r.kind='system')) THEN %s "
                "WHEN EXISTS (SELECT 1 FROM sys_user_role ur JOIN sys_role r ON r.id=ur.role_id "
                "  WHERE ur.user_id=u.id AND r.code=%s) THEN %s "
                "ELSE %s END, perm_ver=perm_ver+1 "
                "WHERE u.id=ANY(%s)",
                [
                    ROLE_SYSTEM,
                    ROLE_SYSTEM,
                    ROLE_TENANT_ADMIN,
                    ROLE_TENANT_ADMIN,
                    ROLE_NORMAL,
                    affected,
                ],
            )
        cur.execute(
            "DELETE FROM dict_item WHERE type_code='role_type' AND code=%s",
            [legacy_code],
        )

    if affected:
        from backend.auth.perm_resolver import clear_perms_cache

        clear_perms_cache(affected)
        log.info("历史角色已移除，%d 个用户已迁移为普通用户", len(affected))


# ── 发布权策略状态机（统一裁决，所有写入者共同消费）──────────────────────────
# marker(_ASSET_PUBLISH_OPEN_MARKER) 的四态；发布权是**安全边界**，非法/冲突状态一律 fail-closed。
_PUBLISH_STATE_MISSING = "missing"        # 从未应用（新装）→ 正向迁移可应用；seed 按放开授
_PUBLISH_STATE_APPLIED = "applied"        # 已放开发布权
_PUBLISH_STATE_ROLLED_BACK = "rolled_back"  # 已回滚（tombstone）→ seed 落 C4 基线、正向迁移 no-op
_PUBLISH_STATE_INVALID = "invalid"        # marker 损坏/结构冲突 → fail-closed，按已回滚保守处理


def _publish_policy_state_cur(cur) -> str:
    """在**调用方事务的同一 cursor** 内读取发布权策略状态（四态）。

    发布权写入者（`_seed_role_grants` / `seed_stage6_asset_visibility` / `_backfill` / `rollback`）
    必须先取共享 advisory lock、再用本函数在同一事务读状态，避免「事务外读旧状态 → 并发回滚提交 →
    据旧状态写回发布权」的竞态。非法 JSON / 非 dict / applied 与 rolled_back 冲突 → INVALID（fail-closed）。
    """
    cur.execute("SELECT value FROM app_config WHERE key=%s", [_ASSET_PUBLISH_OPEN_MARKER])
    row = cur.fetchone()
    if row is None:
        return _PUBLISH_STATE_MISSING
    raw = row[0]
    try:
        val = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return _PUBLISH_STATE_INVALID
    if not isinstance(val, dict):
        return _PUBLISH_STATE_INVALID
    rolled_back = val.get("rolled_back")
    applied = val.get("applied")
    if rolled_back is True and applied is False:
        return _PUBLISH_STATE_ROLLED_BACK
    if applied is True and "rolled_back" not in val:
        return _PUBLISH_STATE_APPLIED
    return _PUBLISH_STATE_INVALID  # 冲突/未知结构 → fail-closed


def _publish_suppressed(state: str) -> bool:
    """是否应抑制发布权授予（fail-closed）：已回滚或状态非法/冲突都不放开。"""
    return state in (_PUBLISH_STATE_ROLLED_BACK, _PUBLISH_STATE_INVALID)


def _seed_role_grants(client: PostgresClient, all_menu_codes: list[str]) -> None:
    """为内置角色写默认菜单/功能授权（仅当该角色尚无 role_menu，避免覆盖后续手工调整）。

    非系统内置角色（normal/tenant_admin）的整份默认授权在**共享 advisory lock + 单事务**内完成：
    锁内读发布策略状态门控发布码（回滚/非法态落 C4 基线），菜单+资源+发布码原子写入，授权确有变化
    则同事务 bump 该角色用户 perm_ver（perm_resolver 硬契约）。这样即便与回滚并发、或被清空菜单后
    重新触发本函数，也不会绕过 tombstone 复活发布权、不会留半成品、不会与 token 权限版本脱节。
    """
    business = list(_BUSINESS_MENU_CODES)
    biz_res = list(BUSINESS_RESOURCE_CODES)
    tenant_pub = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES)
    public_pub = list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)

    # system 角色：锁定、不可手工编辑，始终**幂等补齐全量**（含发布码，system 恒全授、不受回滚影响）。
    sys_menus = client.query_df("SELECT id FROM sys_menu")["id"].tolist()
    sys_res = client.query_df("SELECT id FROM sys_resource")["id"].tolist()
    for mid in sys_menus:
        client.execute("INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) "
                       "ON CONFLICT DO NOTHING", [ROLE_SYSTEM, mid])
    for rid in sys_res:
        client.execute("INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                       "ON CONFLICT DO NOTHING", [ROLE_SYSTEM, rid])

    # 非系统内置角色：仅首次（role_menu 空）写默认授权；发布码在锁内按发布策略状态门控。
    # 非发布资源码（发布码单独按状态追加）：
    #   tenant_admin = 用户管理码 + 租户扩展码 + 业务码；normal = 业务码。
    nonpublish = [
        (ROLE_TENANT_ADMIN, business + list(_TENANT_ADMIN_EXTRA_MENUS),
         list(_USER_RESOURCE_CODES) + list(_TENANT_ADMIN_EXTRA_RESOURCE_CODES) + biz_res),
        (ROLE_NORMAL, business, list(biz_res)),
    ]
    bumped_roles: list[str] = []
    for role_id, menu_codes, resource_codes in nonpublish:
        with client.transaction() as conn, conn.cursor() as cur:
            # 与 seed_stage6 / backfill / rollback 同一把锁串行：杜绝并发写发布权竞态
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [_ASSET_PUBLISH_OPEN_LOCK])
            cur.execute("SELECT 1 FROM sys_role_menu WHERE role_id=%s LIMIT 1", [role_id])
            if cur.fetchone() is not None:
                continue  # 已配置过 → 不覆盖（空事务提交）
            # grant_changed 统计**菜单 + 资源 + 发布码**任一实际插入——菜单也是授权，只清空菜单
            # （资源完整）重授时 perm_ver 也必须变，否则菜单权限扩大却与 token 版本脱节（perm_resolver 硬契约）。
            grant_changed = 0
            for mid in menu_codes:
                cur.execute("INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) "
                            "ON CONFLICT DO NOTHING", [role_id, mid])
                grant_changed += max(cur.rowcount or 0, 0)
            for rid in resource_codes:
                cur.execute("INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                            "ON CONFLICT DO NOTHING", [role_id, rid])
                grant_changed += max(cur.rowcount or 0, 0)
            # 发布码：锁内读状态门控（fail-closed）——回滚/非法态下 normal 无发布码、tenant_admin 仅 tenant
            if _publish_suppressed(_publish_policy_state_cur(cur)):
                pub_codes = tenant_pub if role_id == ROLE_TENANT_ADMIN else []
            else:
                pub_codes = tenant_pub + public_pub
            for rid in pub_codes:
                cur.execute("INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                            "ON CONFLICT DO NOTHING", [role_id, rid])
                grant_changed += max(cur.rowcount or 0, 0)
            if grant_changed:  # 任一授权（菜单/资源/发布码）变化 → 同事务 bump 该角色用户 perm_ver
                cur.execute("UPDATE sys_user SET perm_ver=perm_ver+1 "
                            "WHERE id IN (SELECT user_id FROM sys_user_role WHERE role_id=%s)", [role_id])
                bumped_roles.append(role_id)
    # 提交后 best-effort 清受影响用户 perms 缓存（纯优化，权威在 perm_ver；失败仅告警）
    if bumped_roles:
        try:
            affected = client.query_df(
                "SELECT user_id FROM sys_user_role WHERE role_id = ANY(%s)",
                [bumped_roles])["user_id"].tolist()
            if affected:
                from backend.auth.perm_resolver import clear_perms_cache
                clear_perms_cache(affected)
        except Exception:
            log.warning("_seed_role_grants: 清 perms 缓存失败（忽略，权威在 perm_ver）", exc_info=True)


def _record_config_split_legacy_menu_state(client: PostgresClient) -> None:
    """一次性记录旧配置菜单状态；启动只观测，不删除或覆盖任何运行时菜单。"""
    legacy_detected = False
    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_CONFIG_SPLIT_MENU_DISCOVERY_LOCK])
        cur.execute(
            "SELECT 1 FROM app_config WHERE key=%s",
            [_CONFIG_SPLIT_MENU_DISCOVERY_MARKER],
        )
        marker_exists = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM sys_menu WHERE id=%s", [_LEGACY_SCORE_PROFILES_MENU_ID])
        legacy_detected = cur.fetchone() is not None
        if not marker_exists:
            marker = {
                "version": 1,
                "recorded": True,
                "menu_overwrite": False,
                "legacy_detected_at_recording": legacy_detected,
            }
            cur.execute(
                "INSERT INTO app_config (key,value,updated_at) VALUES (%s,%s,now())",
                [_CONFIG_SPLIT_MENU_DISCOVERY_MARKER, json.dumps(marker, ensure_ascii=False)],
            )
    if legacy_detected:
        log.warning(
            "检测到旧菜单 %s；启动已保留现状，请由系统管理员在菜单管理中显式迁移并留审计",
            _LEGACY_SCORE_PROFILES_MENU_ID,
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
        for role_id in (ROLE_TENANT_ADMIN, ROLE_NORMAL):
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

        # 注：原此处 DELETE normal 的 score-profile:publish-tenant（R28 收紧发布边界）已随
        # asset-ownership-refactor C4/R4 放开普通用户发布而移除；发布码统一由
        # _seed_role_grants（新装）+ _backfill_asset_publish_open_v1（存量回填）授予。

        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s))",
                [ROLE_TENANT_ADMIN, ROLE_NORMAL],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [_STAGE4_BUSINESS_GRANTS_MARKER, '{"applied":true}'],
        )


def _backfill_sector_watchlist_grants(client: PostgresClient) -> None:
    """为既有内置业务角色一次性补齐板块自选权限，并失效旧权限快照。"""
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_SECTOR_WATCHLIST_GRANTS_MARKER])
    if not marker.empty:
        return

    resource_codes = ["sector-watchlist:view", "sector-watchlist:update"]
    changed = 0
    with client.transaction() as conn, conn.cursor() as cur:
        for role_id in (ROLE_TENANT_ADMIN, ROLE_NORMAL):
            for resource_id in resource_codes:
                cur.execute(
                    "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    [role_id, resource_id],
                )
                changed += max(cur.rowcount or 0, 0)
        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s))",
                [ROLE_TENANT_ADMIN, ROLE_NORMAL],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO NOTHING",
            [_SECTOR_WATCHLIST_GRANTS_MARKER, '{"applied":true}'],
        )


def _backfill_sector_menu_grants(client: PostgresClient) -> None:
    """为既有内置业务角色一次性补齐「板块行情」菜单授权，并失效旧权限快照。

    板块概念 T8 把 `/sectors` 菜单加进 `_BUSINESS_MENU_CODES`，但存量库的 stage4 菜单回填
    （migration.stage4_business_grants_v2）早已 applied，不会补授后加入的菜单；T10b 的
    sectors_view_v1 迁移也只补了资源码 sectors:view、漏了菜单码 /sectors。结果 normal 有接口
    权限却看不到「板块行情」菜单入口（路由守卫按授权菜单 fail-closed 重定向）。本迁移补菜单码、
    幂等一次，与所有默认授权迁移一致：不保留迁移后角色管理页的人工增删（不删除任何既有授权）。
    """
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_SECTOR_MENU_GRANTS_MARKER])
    if not marker.empty:
        return

    changed = 0
    inserted_roles: list[str] = []
    with client.transaction() as conn, conn.cursor() as cur:
        for role_id in (ROLE_TENANT_ADMIN, ROLE_NORMAL):
            cur.execute(
                "INSERT INTO sys_role_menu (role_id, menu_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [role_id, "/sectors"],
            )
            inserted = max(cur.rowcount or 0, 0)
            changed += inserted
            if inserted:
                inserted_roles.append(role_id)
        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s))",
                [ROLE_TENANT_ADMIN, ROLE_NORMAL],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO NOTHING",
            [_SECTOR_MENU_GRANTS_MARKER, json.dumps({
                "applied": True,
                "inserted_roles": inserted_roles,
            })],
        )


def seed_stage5_platform_capabilities(client: PostgresClient | None = None) -> None:
    """阶段五平台能力 seed：默认配置、首批字典、既有库权限快照失效。

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
    for type_code, code, label, sort, color in _SEED_DICT_ITEMS:
        item_id = f"{type_code}:{code}"
        client.execute(
            "INSERT INTO dict_item (id, type_code, code, label, sort, color) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (type_code, code) DO NOTHING",
            [item_id, type_code, code, label, sort, color],
        )
    _backfill_stage5_platform_grants(client)


def _backfill_stage5_platform_grants(client: PostgresClient) -> None:
    """既有库阶段五权限回填：新增 baseline 权限快照失效，不覆盖角色授权。"""
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_STAGE5_PLATFORM_CAPABILITIES_MARKER])
    if not marker.empty:
        return

    with client.transaction() as conn, conn.cursor() as cur:
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


def revoke_tenant_admin_audit_default_grants(client: PostgresClient | None = None) -> None:
    """一次性撤销历史版本默认塞给 tenant_admin 的审计菜单/资源授权。

    审计日志仍保留为可授权菜单和资源；系统管理员需要时应在角色页显式授权。
    迁移只执行一次，避免后续管理员手工授权给某个角色后被启动逻辑反复删除。
    """
    client = client or get_pg_client()
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_TENANT_ADMIN_AUDIT_REVOKE_MARKER])
    if not marker.empty:
        return

    changed = 0
    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sys_role_menu WHERE role_id=%s AND menu_id=%s",
            [ROLE_TENANT_ADMIN, "/system/audit"],
        )
        changed += max(cur.rowcount, 0)
        cur.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id=%s",
            [ROLE_TENANT_ADMIN, "audit:view"],
        )
        changed += max(cur.rowcount, 0)
        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS ("
                "  SELECT 1 FROM sys_user_role ur "
                "  WHERE ur.user_id = u.id AND ur.role_id = %s"
                ") AND NOT EXISTS ("
                "  SELECT 1 FROM sys_user_role sur JOIN sys_role sr ON sr.id = sur.role_id "
                "  WHERE sur.user_id = u.id AND (sr.code = %s OR sr.kind = 'system')"
                ")",
                [ROLE_TENANT_ADMIN, ROLE_SYSTEM],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [_TENANT_ADMIN_AUDIT_REVOKE_MARKER, '{"applied":true}'],
        )


def seed_stage6_asset_visibility(client: PostgresClient | None = None) -> None:
    """阶段六资产公开权限回填。

    历史版本此处只授 tenant_admin 租户公开（public 仅 system）；C4/R4 放开后本函数改为给
    tenant_admin 授 tenant + public 全部发布码（见下方循环），normal 发布码由 _seed_role_grants
    （新装）+ _backfill_asset_publish_open_v1（存量回填，marker v2）授予。
    """
    client = client or get_pg_client()
    marker = client.query_df(
        "SELECT 1 FROM app_config WHERE key=%s", [_STAGE6_ASSET_VISIBILITY_MARKER])
    if not marker.empty:
        return

    tenant_publish = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES)
    public_publish = list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    changed = 0
    with client.transaction() as conn, conn.cursor() as cur:
        # 与 seed_role_grants / backfill / rollback 同一把锁串行；发布策略状态在锁内、同事务读取，
        # 杜绝「事务外读旧状态 → 并发回滚提交 → 据旧状态补回 public」竞态。
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_ASSET_PUBLISH_OPEN_LOCK])
        # 消费统一发布策略状态：已回滚/非法态（fail-closed）只授 C4 基线的 tenant，不补 public
        if _publish_suppressed(_publish_policy_state_cur(cur)):
            publish_codes = tenant_publish
        else:
            publish_codes = tenant_publish + public_publish
        # C4/R4：tenant_admin 默认获得 tenant + public 全部发布码（原仅 tenant）。
        # 原「DELETE normal 全部发布码」「DELETE tenant_admin public 发布码」两处收紧已移除；
        # normal 发布码由 _seed_role_grants（新装）+ _backfill_asset_publish_open_v1（存量回填）授予。
        for rid in publish_codes:
            cur.execute(
                "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [ROLE_TENANT_ADMIN, rid],
            )
            changed += max(cur.rowcount, 0)

        if changed:
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s))",
                [ROLE_TENANT_ADMIN, ROLE_NORMAL],
            )
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
            [_STAGE6_ASSET_VISIBILITY_MARKER, '{"applied":true}'],
        )


def _backfill_asset_publish_open_v1(client: PostgresClient | None = None) -> None:
    """asset-ownership-refactor C4/R4：存量库回填「放开普通用户发布权」。

    stage4/stage6 的收紧迁移（DELETE 掉 normal 发布码、tenant_admin 的 public 发布码）在存量库
    已随各自 marker 落地，编辑那两个函数只影响新装；存量库须由本迁移把 8 个 tenant/public 发布码
    补授给 normal 与 tenant_admin（ON CONFLICT DO NOTHING，幂等），并在同一事务 bump 受影响用户
    perm_ver，使旧权限快照失效、下次解析拿到发布权。

    **可逆性（确定性基线恢复）**：本次是**默认角色策略变更**，发布权在多处 seed（新装 `_seed_role_grants`、
    存量 `seed_stage6_asset_visibility`、本回填）写入，无法用「本迁移实际新增行」账本覆盖全部来源。
    回滚因此采用确定性基线恢复：把 normal/tenant_admin 的发布码恢复到 C4 前默认策略（见
    asset-publish-open.sql）。与所有默认策略迁移一致，**不保留迁移后经角色管理页做的人工增删**。

    **并发安全**：marker 判定与写入全在**同一事务**内，并先取事务级 advisory lock 串行化多实例
    并发启动；marker 已存在则整段 no-op；仅当确有新增才 bump perm_ver。
    """
    client = client or get_pg_client()
    publish_codes = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES) + list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    with client.transaction() as conn, conn.cursor() as cur:
        # 事务级 advisory lock：多实例并发启动时串行执行本迁移，随事务提交/回滚自动释放
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_ASSET_PUBLISH_OPEN_LOCK])
        # marker 判定移入锁内：marker 存在即整段 no-op。**含回滚 tombstone**——回滚不删 marker，
        # 故回滚后当前版本重启、init 再跑本迁移时因 marker 存在而 no-op，发布权不被自动复活。
        cur.execute("SELECT 1 FROM app_config WHERE key=%s", [_ASSET_PUBLISH_OPEN_MARKER])
        if cur.fetchone() is not None:
            return

        changed = 0
        for role_id in (ROLE_NORMAL, ROLE_TENANT_ADMIN):
            for rid in publish_codes:
                cur.execute(
                    "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    [role_id, rid],
                )
                if cur.rowcount and cur.rowcount > 0:  # 确有新增（既有则被 DO NOTHING 跳过）
                    changed += cur.rowcount

        if changed:  # 仅当确有新增才 bump，避免空跑污染 perm_ver
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s))",
                [ROLE_NORMAL, ROLE_TENANT_ADMIN],
            )
        # marker 首次写入用普通 INSERT（锁内已确认不存在）：仅记「已应用」，回滚不依赖其内容
        cur.execute(
            "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now())",
            [_ASSET_PUBLISH_OPEN_MARKER, json.dumps({"applied": True})],
        )


def rollback_asset_publish_open_v1(client: PostgresClient | None = None) -> None:
    """回滚 C4/R4 发布权放开：确定性恢复 **C4 前默认角色策略**（应急/测试用，不在 seed 序列自动执行）。

    C4 前基线：normal 无任何发布码；tenant_admin 仅 4 个 tenant 发布码（由 stage6 授予）、无 public。
    因此回滚在同一 advisory-lock 事务内：
      - normal：删全部 8 个发布码；
      - tenant_admin：删 4 个 public 码，并 `ON CONFLICT DO NOTHING` **补齐 4 个 tenant 码**
        （若迁移期间被人工移除也一并恢复到基线）；
      - 仅当确有增删才 bump perm_ver；最后把 marker 改写成 **tombstone** `{"applied":false,"rolled_back":true}`。
    与所有默认策略迁移一致：恢复默认策略、**不保留迁移后经角色管理页做的人工增删**。

    **持久性（关键）**：回滚**不删除 marker**，而是留 tombstone。正向迁移 `_backfill_asset_publish_open_v1`
    以「marker 存在即 no-op」为准，故回滚后即使当前版本重启、init 再跑正向迁移，也不会复活发布权
    （若删 marker，重启会因 marker 缺失重新授权 → 回滚被自动反向覆盖）。**重新启用发布权须显式操作**：
    删除该 tombstone 后再跑正向迁移。marker 缺失（从未应用）或已是 tombstone → 整段 no-op。
    """
    client = client or get_pg_client()
    tenant_codes = list(ASSET_TENANT_PUBLISH_RESOURCE_CODES)
    public_codes = list(ASSET_PUBLIC_PUBLISH_RESOURCE_CODES)
    all_codes = tenant_codes + public_codes
    with client.transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [_ASSET_PUBLISH_OPEN_LOCK])
        # 锁内读状态：MISSING（从未应用）/ ROLLED_BACK（已回滚）→ no-op；APPLIED/INVALID → 恢复基线
        state = _publish_policy_state_cur(cur)
        if state in (_PUBLISH_STATE_MISSING, _PUBLISH_STATE_ROLLED_BACK):
            return  # 无可回滚 / 已回滚 → 整段 no-op（二次回滚安全）

        changed = 0
        # normal：删全部 8 发布码（基线无发布权）
        cur.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id = ANY(%s)",
            [ROLE_NORMAL, all_codes])
        changed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        # tenant_admin：删 4 个 public 码
        cur.execute(
            "DELETE FROM sys_role_resource WHERE role_id=%s AND resource_id = ANY(%s)",
            [ROLE_TENANT_ADMIN, public_codes])
        changed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        # tenant_admin：补齐 4 个 tenant 码到基线（幂等）
        for rid in tenant_codes:
            cur.execute(
                "INSERT INTO sys_role_resource (role_id, resource_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                [ROLE_TENANT_ADMIN, rid])
            changed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        if changed:  # 仅当确有增删才 bump
            cur.execute(
                "UPDATE sys_user u SET perm_ver=perm_ver+1 "
                "WHERE EXISTS (SELECT 1 FROM sys_user_role ur WHERE ur.user_id=u.id "
                "AND ur.role_id IN (%s, %s))",
                [ROLE_NORMAL, ROLE_TENANT_ADMIN])
        # tombstone：留 marker 但标记已回滚，使正向迁移重启后 no-op、发布权不被自动复活
        cur.execute(
            "UPDATE app_config SET value=%s, updated_at=now() WHERE key=%s",
            [json.dumps({"applied": False, "rolled_back": True}), _ASSET_PUBLISH_OPEN_MARKER])


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
