-- 用途：统一租户名称、平台角色名称/角色码、菜单编码与用户账号/邮箱的规范化唯一性。
-- 执行时机：发布包含身份唯一性修复的版本时，由 init_pg_db() 幂等执行；本文件供人工复核和手工补执行。
-- 影响范围：sys_tenant.name、sys_role.name/code、sys_menu.code、sys_user.account/email 及六个唯一索引。
-- 前置条件：以下六类规范化重复查询结果必须为空；冲突必须由管理员确认真实归属后人工处理，禁止自动合并身份或资源。
-- 回滚方式：可删除新增的六个表达式唯一索引并恢复旧邮箱索引；身份字段已完成的 trim/lower 规范化不可恢复原大小写和空白，菜单存量值不改写。

BEGIN;

-- 租户名称、角色名称/标识、非空邮箱任一存在重复时 fail-closed，不继续建索引。
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM sys_tenant GROUP BY lower(btrim(name)) HAVING count(*) > 1
    ) THEN RAISE EXCEPTION '租户名称存在规范化重复，请先人工处理'; END IF;
    IF EXISTS (
        SELECT 1 FROM sys_role GROUP BY lower(btrim(name)) HAVING count(*) > 1
    ) THEN RAISE EXCEPTION '角色名称存在规范化重复，请先人工处理'; END IF;
    IF EXISTS (
        SELECT 1 FROM sys_role GROUP BY lower(btrim(code)) HAVING count(*) > 1
    ) THEN RAISE EXCEPTION '角色码存在规范化重复，请先人工处理'; END IF;
    IF EXISTS (
        SELECT 1 FROM sys_menu GROUP BY lower(btrim(code)) HAVING count(*) > 1
    ) THEN RAISE EXCEPTION '菜单编码存在规范化重复，请先人工处理'; END IF;
    IF EXISTS (
        SELECT 1 FROM sys_user GROUP BY lower(btrim(account)) HAVING count(*) > 1
    ) THEN RAISE EXCEPTION '用户账号存在规范化重复，请先人工处理'; END IF;
    IF EXISTS (
        SELECT 1 FROM sys_user WHERE nullif(btrim(email), '') IS NOT NULL
        GROUP BY lower(btrim(email)) HAVING count(*) > 1
    ) THEN RAISE EXCEPTION '用户邮箱存在规范化重复，请先人工处理'; END IF;
END $$;

UPDATE sys_tenant SET name=btrim(name) WHERE name<>btrim(name);
UPDATE sys_role SET name=btrim(name) WHERE name<>btrim(name);
UPDATE sys_role SET code=lower(btrim(code)) WHERE code<>lower(btrim(code));
UPDATE sys_user SET account=lower(btrim(account)) WHERE account<>lower(btrim(account));
UPDATE sys_user SET email=NULL WHERE email IS NOT NULL AND btrim(email)='';
UPDATE sys_user SET email=lower(btrim(email))
WHERE email IS NOT NULL AND email<>lower(btrim(email));

CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_tenant_name_normalized
ON sys_tenant ((lower(btrim(name))));
CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_role_name_normalized
ON sys_role ((lower(btrim(name))));
CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_role_code_normalized
ON sys_role ((lower(btrim(code))));
CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_menu_code_normalized
ON sys_menu ((lower(btrim(code))));
CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_user_account_normalized
ON sys_user ((lower(btrim(account))));
CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_user_email_normalized
ON sys_user ((lower(btrim(email)))) WHERE email IS NOT NULL;
DROP INDEX IF EXISTS idx_sys_user_email;

COMMIT;

-- 回滚（需单独确认后执行）：
-- DROP INDEX IF EXISTS uq_sys_tenant_name_normalized;
-- DROP INDEX IF EXISTS uq_sys_role_name_normalized;
-- DROP INDEX IF EXISTS uq_sys_role_code_normalized;
-- DROP INDEX IF EXISTS uq_sys_menu_code_normalized;
-- DROP INDEX IF EXISTS uq_sys_user_account_normalized;
-- DROP INDEX IF EXISTS uq_sys_user_email_normalized;
-- CREATE UNIQUE INDEX IF NOT EXISTS idx_sys_user_email ON sys_user (email) WHERE email IS NOT NULL;
