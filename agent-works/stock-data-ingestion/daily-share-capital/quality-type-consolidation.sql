-- 质量类型合并留痕。执行入口：正式 verify 扫描 / 股本同步任务，非启动时无条件改写。
-- 映射：mv_missing/mv_gap -> capital_gap；mv_invalid -> capital_invalid；data_gap -> history_data_gap。
-- 影响：仅旧 open 记录归档为 resolved，detail 保留 original_detail、merged_into 与“非数据已修复”说明。
-- 新类型按当前事实生成；已有 fixing、resolved、ignored 的身份不改，旧忽略按原范围继续生效。
-- PostgreSQL 调度定义不改写，执行时兼容旧参数；不启用关闭的调度。无 DDL 变更。
-- 事务与去重由 backend/dataquality/consolidation.py 和 data_report.py 执行，不手动复制 UPDATE 绕过复检。
-- 运行前：停服备份 DuckDB；本次备份目录 /Users/pengshuaifeng/ai-stocks-backups/quality-consolidation-20261019/。
-- 回滚：旧详情仍在台账；若需整库恢复须停写，并核对备份后新增数据，禁止直接覆盖丢弃后续采集成果。
-- 以下仅用于只读核对，线上服务持有文件锁时通过正式服务入口查询。
SELECT issue_type, status, count(*) AS issues
FROM data_quality_issue
WHERE issue_type IN ('mv_missing','mv_gap','mv_invalid','data_gap',
                     'capital_gap','capital_invalid','history_data_gap')
GROUP BY issue_type, status
ORDER BY issue_type, status;
