-- 板块自选持久化与默认权限回填。
-- 用途：为既有 PostgreSQL 库补齐用户级板块自选表，并给内置普通用户/租户管理员角色授予板块自选权限。
-- 前置条件：已存在 sys_resource、sys_role、sys_role_resource、sys_user_role、sys_user、app_config。
-- 执行时机：部署包含板块自选接口与前端页面的版本时；应用启动的 init_pg_db 会幂等执行同等变更。
-- 影响范围：新增 board_watchlist 表；可能增加两条角色资源授权并递增受影响用户 perm_ver。
-- 回滚：执行文件末尾 ROLLBACK 区段。回滚会删除板块自选数据且使相关用户 token 失效，不可恢复成员数据。

BEGIN;

CREATE TABLE IF NOT EXISTS board_watchlist (
    tenant_id      TEXT NOT NULL DEFAULT 'default',
    owner_user_id  TEXT NOT NULL DEFAULT 'admin',
    board_code     TEXT NOT NULL,
    board_name     TEXT NOT NULL,
    board_type     TEXT NOT NULL,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, owner_user_id, board_code)
);

INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin)
VALUES
    ('sector-watchlist:view', '/sectors', 'sector-watchlist:view', '查看板块自选', 'api', 'GET', '/api/sectors/watchlist', 100000, TRUE),
    ('sector-watchlist:update', '/sectors', 'sector-watchlist:update', '维护板块自选', 'api', 'POST', '/api/sectors/watchlist', 100010, TRUE)
ON CONFLICT (id) DO NOTHING;

WITH inserted AS (
    INSERT INTO sys_role_resource (role_id, resource_id)
    SELECT role_id, resource_id
    FROM (VALUES
        ('normal', 'sector-watchlist:view'),
        ('normal', 'sector-watchlist:update'),
        ('tenant_admin', 'sector-watchlist:view'),
        ('tenant_admin', 'sector-watchlist:update')
    ) AS grants(role_id, resource_id)
    ON CONFLICT DO NOTHING
    RETURNING role_id
), affected_roles AS (
    SELECT DISTINCT role_id FROM inserted
)
UPDATE sys_user u
SET perm_ver = perm_ver + 1
WHERE EXISTS (
    SELECT 1 FROM sys_user_role ur
    JOIN affected_roles ar ON ar.role_id = ur.role_id
    WHERE ur.user_id = u.id
);

INSERT INTO app_config (key, value, updated_at)
VALUES ('migration.sector_watchlist_grants_v1', '{"applied":true}', now())
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- ROLLBACK（需明确接受板块自选数据不可恢复后单独执行）：
-- BEGIN;
-- WITH removed AS (
--     DELETE FROM sys_role_resource
--     WHERE role_id IN ('normal', 'tenant_admin')
--       AND resource_id IN ('sector-watchlist:view', 'sector-watchlist:update')
--     RETURNING role_id
-- ), affected_roles AS (
--     SELECT DISTINCT role_id FROM removed
-- )
-- UPDATE sys_user u SET perm_ver = perm_ver + 1
-- WHERE EXISTS (
--     SELECT 1 FROM sys_user_role ur
--     JOIN affected_roles ar ON ar.role_id = ur.role_id
--     WHERE ur.user_id = u.id
-- );
-- DELETE FROM app_config WHERE key = 'migration.sector_watchlist_grants_v1';
-- DROP TABLE IF EXISTS board_watchlist;
-- DELETE FROM sys_resource WHERE id IN ('sector-watchlist:view', 'sector-watchlist:update');
-- COMMIT;
