-- 技术指标四层治理字段迁移审计副本。
-- 用途：为 DuckDB indicator_def 增加业务层级、父指标和预设参数字段。
-- 执行时机：应用启动时由 backend/storage/ddl.py 的幂等迁移自动执行；不要手工绕过 DDL。
-- 影响范围：平台全局指标定义元数据，不改指标历史 key，不改用户方案。
-- 回滚：不建议删除列；旧版本会忽略新增列。确需物理回滚时先备份数据库并重建旧结构表。

ALTER TABLE indicator_def ADD COLUMN IF NOT EXISTS layer VARCHAR;
ALTER TABLE indicator_def ADD COLUMN IF NOT EXISTS parent_key VARCHAR;
ALTER TABLE indicator_def ADD COLUMN IF NOT EXISTS preset_params VARCHAR;

-- 历史自定义指标先按输出类型确定安全默认层级；内置指标在 seed 时校准为完整四层关系。
UPDATE indicator_def
SET layer = CASE WHEN dtype = 'bool' THEN 'signal' ELSE 'metric' END
WHERE layer IS NULL;
