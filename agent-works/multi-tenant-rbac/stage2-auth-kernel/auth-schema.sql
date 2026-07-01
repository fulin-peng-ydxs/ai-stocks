-- ============================================================================
-- 多租户 RBAC stage2 · T1：sys_user 认证列扩展 + admin seed 口径
-- ----------------------------------------------------------------------------
-- 文件路径：agent-works/multi-tenant-rbac/stage2-auth-kernel/auth-schema.sql
-- 用途：为认证内核扩展 sys_user（角色/权限版本/最后登录 + email 唯一），并记录管理员
--       初始密码 seed 口径。**事实源/执行入口是 backend/storage/pg_ddl.py::init_pg_db**
--       （启动期幂等执行）；本 SQL 为人读留痕与手工补执行兜底，二者须保持一致。
-- 执行时机：随后端启动 init_pg_db() 幂等执行（ALTER ... ADD COLUMN IF NOT EXISTS /
--           CREATE UNIQUE INDEX IF NOT EXISTS）；无需停机、可重复执行。
-- 影响范围：仅平台表 sys_user（自然键，无 tenant/owner 归属）；不动资产表（阶段一已复合主键）
--           与行情 DuckDB。
-- 回滚方式：新增列与索引均为 additive，可 DROP（无数据丢失风险，admin 密码可重 seed）。
--           **不涉及不可逆迁移**（区别于阶段一 R3 资产迁移）。
-- 说明：sys_role/sys_user_role/sys_menu/sys_resource/audit_log/dict_* 等表本阶段不建（阶段三/五）。
-- ============================================================================

-- 1) sys_user 认证列（既有库 CREATE TABLE IF NOT EXISTS 不补列，用幂等 ALTER）
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS role_code     TEXT NOT NULL DEFAULT 'normal';   -- system|tenant_admin|normal（阶段三迁 sys_role）
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS perm_ver      INTEGER NOT NULL DEFAULT 0;        -- 权限版本号：权限/状态变更自增，旧 token 失效
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP;                          -- 最后登录时间

-- 2) email 部分唯一索引：允许多个 NULL（未填邮箱），非空则全局唯一
CREATE UNIQUE INDEX IF NOT EXISTS idx_sys_user_email ON sys_user (email) WHERE email IS NOT NULL;

-- 3) 管理员 seed 口径（实际由 pg_ddl.seed_default_tenant 执行，密码不写入 SQL/代码）
--    - admin 提升为平台系统管理员：role_code='system'
--    - 初始密码取环境变量 AI_STOCKS_ADMIN_PASSWORD；缺失则随机生成并日志告警一次（仅开发态）
--    - 既有无密码 admin 仅在 password_hash 为空时补写，不覆盖已设密码
--    （此处不内联密码哈希；下方仅示意角色提升的等价 SQL）
UPDATE sys_user SET role_code = 'system' WHERE id = 'admin' AND role_code <> 'system';
