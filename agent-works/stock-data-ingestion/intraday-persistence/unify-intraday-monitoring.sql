-- 用途：将既有个股分时监控边界统一到最早真实分钟或已保存的历史边界。
-- 执行时机：升级启动由 backend/storage/ddl.py 的幂等迁移自动执行；
--   仅在人工维护确有需要时才在服务停服、确认无写任务后手动执行本文件。
-- 影响范围：DuckDB stock_intraday_monitor.monitoring_start；不改分钟、覆盖或任务数据。
-- 字段语义：monitoring_start 是全局质量范围的持久化下界，成功补采可前移，丢失不后移。
-- 前置条件：既有分时表已按 DDL 创建，需先备份数据库。
-- 回滚：需要升级前数据库备份或原监控日期快照；不能用当前源窗口猜测还原日期。
BEGIN TRANSACTION;

-- 兼容旧覆盖资产：补缺失的监控行，不覆盖任何既有日期。
INSERT INTO stock_intraday_monitor(code, monitoring_start)
SELECT code, min(trade_date)
FROM stock_intraday_coverage
GROUP BY code
ON CONFLICT DO NOTHING;

-- 用真实最早分钟和历史下界的较早者统一起点，禁止后移并隐藏历史缺失。
UPDATE stock_intraday_monitor
SET monitoring_start = least(
    monitoring_start,
    (SELECT min(d) FROM (
        SELECT min(trade_date) AS d FROM stock_intraday_bar
        UNION ALL
        SELECT min(monitoring_start) FROM stock_intraday_monitor
    ))
);

COMMIT;
