-- ============================================================================
-- 多租户 RBAC 阶段三 · T1 权限数据模型 DDL 留痕（人读 + 手工补执行兜底）
--
-- 事实源：backend/storage/pg_ddl.py（DDL_SYS_ROLE/MENU/RESOURCE/USER_ROLE/ROLE_MENU/
--         ROLE_RESOURCE + seed_rbac()）。本文件与之保持一致，供审阅与应急手工执行。
--
-- 用途      ：新增 6 张 RBAC 平台表（角色/菜单/资源 + 用户-角色/角色-菜单/角色-资源）
--             + seed 内置角色/菜单树/功能点/默认授权 + 存量用户按 role_code 补 user_role。
-- 执行时机  ：随后端启动 init_pg_db() 幂等执行（CREATE TABLE/INDEX IF NOT EXISTS + seed
--             ON CONFLICT DO NOTHING）；无需单独手工执行，本文件仅留痕/应急。
-- 影响范围  ：仅新增平台表（自然键、不带 tenant/owner 归属）；不动资产表、行情 DuckDB、
--             sys_user.role_code（保留为兼容/兜底列，权限解析以 sys_user_role 为准）。
-- 归属隔离  ：RBAC 为平台级配置，与 app_config/indicator_def 一致用自然键、全局共享，
--             不带 tenant_id/owner_user_id（区别于用户资产表）。
-- 回滚方式  ：新表 additive。回滚前须 pg_dump 备份 6 表——DROP 会丢失已配置的
--             角色/菜单/授权/用户-角色数据（非零成本）；role_code 仍在，DROP 后权限退回
--             阶段二 system 粗守卫。无 schema 不可逆点，但有数据丢失成本。
-- ============================================================================

-- ── 主体表 ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sys_role (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'custom',   -- system|tenant_admin|normal|custom
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    is_locked   BOOLEAN NOT NULL DEFAULT FALSE,   -- system 超管：全授权且锁定不可改
    description TEXT,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP,
    UNIQUE (code)
);

CREATE TABLE IF NOT EXISTS sys_menu (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,
    code        TEXT NOT NULL,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'leaf',      -- group | leaf
    route_path  TEXT,
    icon        TEXT,                              -- Element Plus 图标名
    sort        INTEGER NOT NULL DEFAULT 0,
    visible     TEXT NOT NULL DEFAULT 'login',     -- login | system
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP,
    UNIQUE (code),
    FOREIGN KEY (parent_id) REFERENCES sys_menu (id) ON DELETE RESTRICT  -- 有子节点禁删
);

CREATE TABLE IF NOT EXISTS sys_resource (
    id          TEXT PRIMARY KEY,
    menu_id     TEXT NOT NULL,
    code        TEXT NOT NULL,                     -- 精确权限码（user:list 等），全局唯一
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'api',       -- button | api
    api_method  TEXT,
    api_path    TEXT,
    sort        INTEGER NOT NULL DEFAULT 0,
    is_builtin  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP,
    UNIQUE (code),
    FOREIGN KEY (menu_id) REFERENCES sys_menu (id) ON DELETE RESTRICT
);

-- ── 关联表（复合主键；删除策略见各 FK 注释）──────────────────────────────────

CREATE TABLE IF NOT EXISTS sys_user_role (
    user_id     TEXT NOT NULL,
    role_id     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT now(),
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE CASCADE,   -- 删用户清其角色关联
    FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE RESTRICT   -- 角色被用户引用禁删
);

CREATE TABLE IF NOT EXISTS sys_role_menu (
    role_id     TEXT NOT NULL,
    menu_id     TEXT NOT NULL,
    PRIMARY KEY (role_id, menu_id),
    FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE CASCADE,   -- 删角色清授权
    FOREIGN KEY (menu_id) REFERENCES sys_menu (id) ON DELETE CASCADE    -- 删菜单清授权
);

CREATE TABLE IF NOT EXISTS sys_role_resource (
    role_id     TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    PRIMARY KEY (role_id, resource_id),
    FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE CASCADE,
    FOREIGN KEY (resource_id) REFERENCES sys_resource (id) ON DELETE CASCADE
);

-- ── 二级索引（复合主键覆盖正向；下补反向查询：按 menu/role/resource 反查引用）─────

CREATE INDEX IF NOT EXISTS idx_sys_menu_parent_sort ON sys_menu (parent_id, sort);
CREATE INDEX IF NOT EXISTS idx_sys_resource_menu ON sys_resource (menu_id);
CREATE INDEX IF NOT EXISTS idx_sys_user_role_role ON sys_user_role (role_id);
CREATE INDEX IF NOT EXISTS idx_sys_role_menu_menu ON sys_role_menu (menu_id);
CREATE INDEX IF NOT EXISTS idx_sys_role_resource_resource ON sys_role_resource (resource_id);

-- ── seed（内置角色/菜单/功能点/默认授权/存量 user_role）──────────────────────
-- 完整 seed 逻辑见 backend/storage/pg_ddl.py::seed_rbac()。要点：
--   * 内置角色 3 个：system(锁定·全授权)/tenant_admin/normal；id=code。
--   * 菜单树承接前端 menuConfig（emoji→EP 图标名）+ 新增「系统管理→权限管理」子组
--     （用户管理/角色管理/菜单与功能/租户管理 4 叶子）。
--   * 功能点 24 个（user/role/menu/resource/tenant 各域精确码）；id=code。
--   * 默认授权（仅角色首次无授权时写，不覆盖后续手工调整）：
--       system      → 全部菜单 + 全部功能点（展示用；运行时由 perm_resolver 判全量兜底）
--       tenant_admin→ 业务页 + 系统管理/权限管理/用户管理 + user:* 功能点
--       normal → 业务页（行情/筛选/回测/训练）
--   * 存量用户：INSERT ... SELECT u.id, r.id FROM sys_user u JOIN sys_role r ON r.code=u.role_code。
