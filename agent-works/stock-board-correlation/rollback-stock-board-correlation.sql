-- 个股走势关联板块：DuckDB 当前态结构回滚脚本
--
-- 执行时机：确认应用版本已停止读写相关性结果，且需要撤销本功能数据结构时执行。
-- 前置条件：确认目标为行情 DuckDB，执行进程持有唯一写锁，并已按需备份派生结果。
-- 影响范围：只删除相关性冠军表和每股状态表；基础行情、板块、调度和权限数据不受影响。
-- 数据恢复：表内数据是可重算派生数据；重新执行正向脚本并运行后续计算任务即可恢复。

BEGIN TRANSACTION;

DROP TABLE IF EXISTS stock_board_correlation;
DROP TABLE IF EXISTS stock_board_correlation_state;

COMMIT;

-- 执行后验证（应返回 0 行）：
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'main'
--   AND table_name IN ('stock_board_correlation', 'stock_board_correlation_state');
