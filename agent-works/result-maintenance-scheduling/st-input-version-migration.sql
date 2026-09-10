-- 榜单与连板天梯 ST 输入版本字段前向迁移。
--
-- 用途：让结果读取端比较“生成时 ST 版本”和“当前已发布 ST 版本”，只在真实变化时
--       复用原有懒重算入口。此脚本不创建任务、不修改调度依赖、不批量失效结果。
-- 执行时机：部署包含读取自检逻辑的后端代码前；应用初始化也会幂等执行同等 ALTER。
-- 前置条件：按下方数据库标注分段执行，禁止把整份脚本直接交给单个数据库；
--           分别连接正确的 PostgreSQL 资产库和 DuckDB 行情库，DuckDB 迁移时先停后端。
-- 影响范围：新增可空版本列、日期修订表及索引。存量结果 NULL 表示“未知版本”，
--           首次业务读取会按失效处理并自愈；不会改写已有结果明细。
-- 回滚：代码回滚后可保留新增列；若确认永久撤销，可在备份后执行文末注释中的 DROP COLUMN。

-- PostgreSQL：评分快照元数据。
ALTER TABLE score_snapshot_meta
    ADD COLUMN IF NOT EXISTS st_input_version TEXT;

-- DuckDB：连板天梯不可变快照及日期状态指针。
CREATE TABLE IF NOT EXISTS stock_st_status_date_revision (
    trade_date DATE PRIMARY KEY,          -- ST 事实所属交易日
    revision BIGINT NOT NULL CHECK (revision > 0), -- 有效变化的日期级单调修订号
    updated_at TIMESTAMP NOT NULL         -- 最近一次有效变化时间
);
ALTER TABLE limit_ladder_snapshot
    ADD COLUMN IF NOT EXISTS st_input_version VARCHAR;
ALTER TABLE limit_ladder_snapshot_state
    ADD COLUMN IF NOT EXISTS st_input_version VARCHAR;
CREATE INDEX IF NOT EXISTS idx_st_status_daily_date
    ON stock_st_status_daily (trade_date, updated_at);
CREATE INDEX IF NOT EXISTS idx_st_status_history_date
    ON stock_st_status_history (trade_date, changed_at);

-- 存量库初始化：事实行数覆盖首次写入，历史行数覆盖后续变更；已有修订行绝不覆盖。
INSERT INTO stock_st_status_date_revision (trade_date,revision,updated_at)
SELECT current.trade_date,
       count(*) + COALESCE(history.change_count,0),
       max(current.updated_at)
FROM stock_st_status_daily current
LEFT JOIN (
    SELECT trade_date,count(*) AS change_count
    FROM stock_st_status_history
    GROUP BY trade_date
) history ON history.trade_date=current.trade_date
WHERE NOT EXISTS (SELECT 1 FROM stock_st_status_date_revision)
GROUP BY current.trade_date,history.change_count
ON CONFLICT (trade_date) DO NOTHING;

-- 可选回滚（默认不要执行；仍须按 PG/DuckDB 标注分库执行，旧代码会忽略保留列）：
-- PostgreSQL：
-- ALTER TABLE score_snapshot_meta DROP COLUMN IF EXISTS st_input_version;
-- DuckDB：
-- ALTER TABLE limit_ladder_snapshot_state DROP COLUMN IF EXISTS st_input_version;
-- ALTER TABLE limit_ladder_snapshot DROP COLUMN IF EXISTS st_input_version;
-- DROP INDEX IF EXISTS idx_st_status_history_date;
-- DROP INDEX IF EXISTS idx_st_status_daily_date;
-- DROP TABLE IF EXISTS stock_st_status_date_revision;
