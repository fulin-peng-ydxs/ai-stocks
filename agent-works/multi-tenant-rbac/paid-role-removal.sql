-- 用途：从既有 PostgreSQL 数据中移除历史付费角色，并把受影响用户平滑迁移为普通用户。
-- 执行时机：发布包含角色整改代码的版本时执行；应用启动也会幂等执行同等迁移。
-- 影响范围：sys_user、sys_user_role、sys_role、sys_role_menu、sys_role_resource、dict_item。
-- 前置条件：sys_role 中存在 normal 系统内置角色；执行前应完成数据库备份。
-- 回滚说明：本迁移删除角色及授权关系，无法无损自动回滚；如需恢复，只能从执行前备份还原。

BEGIN;

CREATE TEMP TABLE _paid_role_affected_users ON COMMIT DROP AS
SELECT DISTINCT u.id
FROM sys_user u
LEFT JOIN sys_user_role ur ON ur.user_id = u.id
LEFT JOIN sys_role r ON r.id = ur.role_id
WHERE u.role_code = 'paid' OR r.code = 'paid' OR r.kind = 'paid';

-- 先保留受影响用户的基本业务访问能力。
INSERT INTO sys_user_role (user_id, role_id)
SELECT id, 'normal'
FROM _paid_role_affected_users
ON CONFLICT (user_id, role_id) DO NOTHING;

-- 解除用户与历史角色的关联，随后删除角色；角色菜单和功能授权由外键级联清理。
DELETE FROM sys_user_role
WHERE role_id IN (
    SELECT id FROM sys_role WHERE code = 'paid' OR kind = 'paid'
);

DELETE FROM sys_role
WHERE code = 'paid' OR kind = 'paid';

-- 兼容字段按用户当前真实角色重新归一，并使旧令牌失效。
UPDATE sys_user u
SET role_code = CASE
        WHEN EXISTS (
            SELECT 1 FROM sys_user_role ur
            JOIN sys_role r ON r.id = ur.role_id
            WHERE ur.user_id = u.id AND (r.code = 'system' OR r.kind = 'system')
        ) THEN 'system'
        WHEN EXISTS (
            SELECT 1 FROM sys_user_role ur
            JOIN sys_role r ON r.id = ur.role_id
            WHERE ur.user_id = u.id AND r.code = 'tenant_admin'
        ) THEN 'tenant_admin'
        ELSE 'normal'
    END,
    perm_ver = perm_ver + 1
WHERE u.id IN (SELECT id FROM _paid_role_affected_users);

DELETE FROM dict_item
WHERE type_code = 'role_type' AND code = 'paid';

COMMIT;
