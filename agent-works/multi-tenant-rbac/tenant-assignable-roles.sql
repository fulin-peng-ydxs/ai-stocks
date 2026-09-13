-- 用途：把“租户管理员可分配哪些平台角色”从代码常量迁移为 sys_role.tenant_assignable。
-- 执行时机：升级包含该字段的版本时执行一次；应用启动 DDL 会幂等执行同一迁移。
-- 影响范围：sys_role 表结构及存量角色的首次默认值，不改角色授权和用户-角色关系。
-- 默认口径：tenant_admin、normal 可下放；system 和存量自定义角色不下放。
-- 回滚：先停止使用 tenant_assignable 的应用版本，再执行文末回滚语句；回滚不会改用户现有角色。

BEGIN;

ALTER TABLE sys_role ADD COLUMN IF NOT EXISTS tenant_assignable BOOLEAN;

UPDATE sys_role
SET tenant_assignable = CASE
    WHEN code IN ('tenant_admin', 'normal') THEN TRUE
    ELSE FALSE
END
WHERE tenant_assignable IS NULL;

ALTER TABLE sys_role ALTER COLUMN tenant_assignable SET DEFAULT FALSE;
ALTER TABLE sys_role ALTER COLUMN tenant_assignable SET NOT NULL;

COMMIT;

-- 验证：system 必须为 false；允许租户分配的其他角色应符合平台配置预期。
SELECT id, code, name, kind, tenant_assignable
FROM sys_role
ORDER BY kind, name;

-- 回滚（仅在旧应用版本不读取该列后执行）：
-- ALTER TABLE sys_role DROP COLUMN tenant_assignable;
