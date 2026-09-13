-- 用途：为走势相关合法空结果补充结构化原因及候选最高共同样本数。
-- 执行时机：应用升级、相关性任务重新计算之前；语句可重复执行。
-- 影响：只扩展状态快照结构，不修改已有冠军和历史状态；历史行保持 NULL，重算后写入原因。
ALTER TABLE stock_board_correlation_state
    ADD COLUMN IF NOT EXISTS industry_empty_reason VARCHAR;
ALTER TABLE stock_board_correlation_state
    ADD COLUMN IF NOT EXISTS industry_max_sample_20 INTEGER;
ALTER TABLE stock_board_correlation_state
    ADD COLUMN IF NOT EXISTS industry_max_sample_60 INTEGER;
ALTER TABLE stock_board_correlation_state
    ADD COLUMN IF NOT EXISTS concept_empty_reason VARCHAR;
ALTER TABLE stock_board_correlation_state
    ADD COLUMN IF NOT EXISTS concept_max_sample_20 INTEGER;
ALTER TABLE stock_board_correlation_state
    ADD COLUMN IF NOT EXISTS concept_max_sample_60 INTEGER;

-- 回滚：以下字段均为可重算派生数据；确认旧版本应用已恢复后按相反顺序执行。
-- ALTER TABLE stock_board_correlation_state DROP COLUMN concept_max_sample_60;
-- ALTER TABLE stock_board_correlation_state DROP COLUMN concept_max_sample_20;
-- ALTER TABLE stock_board_correlation_state DROP COLUMN concept_empty_reason;
-- ALTER TABLE stock_board_correlation_state DROP COLUMN industry_max_sample_60;
-- ALTER TABLE stock_board_correlation_state DROP COLUMN industry_max_sample_20;
-- ALTER TABLE stock_board_correlation_state DROP COLUMN industry_empty_reason;
