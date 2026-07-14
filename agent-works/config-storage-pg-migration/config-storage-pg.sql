-- 配置存储迁移 PG 底座。
-- 用途：为布局平台配置和用户偏好新增 PostgreSQL 表，并把个人偏好资源码调整为登录基线自持久化能力。
-- 执行时机：后端服务停止后、正式执行 migrate-config-storage 前；也可由 init_pg_db() 幂等建表覆盖。
-- 影响范围：新增 PG 表、资源码 seed 和 baseline 授权清理；不修改 DuckDB 行情/分析表。
-- 回滚方式：首版回滚代码时保留新增 PG 表；如必须清理，可 DROP 新表并恢复 role_resource 显式授权，但会丢失迁移后产生的用户偏好。

-- 布局预设表：存平台级布局预设。config 保存 JSON 文本，schema_version 用于后续结构演进。
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

-- 页面布局默认表：按 page_key 存页面默认布局，preset_key 记录继承来源，config 保存页面覆盖 JSON。
CREATE TABLE IF NOT EXISTS layout_page_config (
    page_key       TEXT PRIMARY KEY,
    preset_key     TEXT,
    config         TEXT,
    schema_version INTEGER,
    updated_at     TIMESTAMP
);

-- 组件字段策略表：按 component_kind + field 限定字段允许出现的配置层级，allowed_layers 保存 JSON 数组文本。
CREATE TABLE IF NOT EXISTS layout_field_policy (
    component_kind TEXT,
    field          TEXT,
    allowed_layers TEXT,
    updated_at     TIMESTAMP,
    PRIMARY KEY (component_kind, field)
);

-- 用户偏好表：归属列 tenant_id/owner_user_id 取请求上下文；scope/page_key/pref_key 定位偏好；value 保存受限 JSON 文本。
CREATE TABLE IF NOT EXISTS user_preference (
    tenant_id      TEXT NOT NULL DEFAULT 'default',
    owner_user_id  TEXT NOT NULL DEFAULT 'admin',
    scope          TEXT NOT NULL,
    page_key       TEXT NOT NULL DEFAULT '',
    pref_key       TEXT NOT NULL,
    value          TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_user_id, scope, page_key, pref_key)
);

-- 资源 seed：layout:user-config 是当前用户页面布局/组件偏好写入能力，必须挂 login 可见菜单锚点。
-- 运行时由 SHARED_RESOURCE_CODES 强制注入，不写 role_resource。
INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin, created_at)
SELECT 'layout:user-config', '/board', 'layout:user-config', '保存个人页面偏好（基线）',
       'api', 'POST', '/api/layout/users/{page_key}', 805, TRUE, now()
WHERE EXISTS (SELECT 1 FROM sys_menu WHERE id = '/board')
ON CONFLICT (id) DO UPDATE SET
    menu_id = EXCLUDED.menu_id,
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    type = EXCLUDED.type,
    api_method = EXCLUDED.api_method,
    api_path = EXCLUDED.api_path,
    sort = EXCLUDED.sort,
    is_builtin = TRUE,
    updated_at = now();

-- 资源 seed：user-preference:manage 是当前用户非布局偏好写入能力，挂 login 可见菜单锚点。
INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin, created_at)
SELECT 'user-preference:manage', '/board', 'user-preference:manage', '保存个人通用偏好（基线）',
       'api', 'POST', '/api/user-preferences', 806, TRUE, now()
WHERE EXISTS (SELECT 1 FROM sys_menu WHERE id = '/board')
ON CONFLICT (id) DO UPDATE SET
    menu_id = EXCLUDED.menu_id,
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    type = EXCLUDED.type,
    api_method = EXCLUDED.api_method,
    api_path = EXCLUDED.api_path,
    sort = EXCLUDED.sort,
    is_builtin = TRUE,
    updated_at = now();

-- baseline 不落 role_resource；清理存量 layout:user-config 显式授权，避免角色页误以为它可反选。
DELETE FROM sys_role_resource
WHERE resource_id IN ('layout:user-config', 'user-preference:manage');
