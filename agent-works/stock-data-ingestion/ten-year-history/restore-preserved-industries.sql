-- 用途：恢复本次基础资料刷新因源端漏返而清空的两条行业，不覆盖任何非空值。
-- 执行时机：后端经 start.sh 安全停止，DuckDB 独占连接；备份已验证 SHA-256 与可读性。
-- 来源：2026-10-19 修复前 market.duckdb；两条原始值均为 J67资本市场服务。
-- 影响：仅 601198.SH、601059.SH 的 industry，其他字段和股票不变。
-- 回滚：仅在确认无后续行业更新时，将这两条恢复值改回 NULL；通常应保留已核实的备份值。
ATTACH '/Users/pengshuaifeng/ai-stocks-backups/ten-year-history-repair-20261019/market.duckdb' AS repair_backup (READ_ONLY);
BEGIN TRANSACTION;
UPDATE stock_basic AS current
SET industry = prior.industry
FROM repair_backup.stock_basic AS prior
WHERE current.code = prior.code
  AND current.code IN ('601198.SH', '601059.SH')
  AND current.industry IS NULL
  AND prior.industry IS NOT NULL;
COMMIT;
DETACH repair_backup;
