-- 用途：独立参考价证据、人工退市保护与停牌来源。正式迁移由 storage/ddl.py init_db 幂等执行。
-- 执行时机：停服备份后升级启动；不得把派生 pre_close 批量复制成独立参考价。
-- 影响：仅新增字段，不改原始价格/股本；来源参考价通过正式任务重新获取。
-- 回滚：停服并恢复升级前 DuckDB 备份及对应代码；不要只删除字段后运行新代码。
ALTER TABLE daily_bar ADD COLUMN IF NOT EXISTS reference_pre_close DOUBLE;
ALTER TABLE daily_bar ADD COLUMN IF NOT EXISTS reference_close DOUBLE;
ALTER TABLE daily_bar ADD COLUMN IF NOT EXISTS reference_source VARCHAR;
ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS delist_date_manual BOOLEAN DEFAULT false;
ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS delist_date_reported DATE;
ALTER TABLE stock_suspension ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE stock_suspension ADD COLUMN IF NOT EXISTS task_id VARCHAR;
