-- 用途：任务调度直接下游的触发顺序（PostgreSQL 正式运行态）。
-- 执行时机：发布对应代码前停服执行，或由 init_pg_db 的幂等升级自动执行。
-- 影响范围：scheduled_job 顺序与 scheduled_trigger_event 新事件快照；不修改历史事件时间/状态。
-- 回退：先回退应用代码，再决定保留这两个兼容新增列；不自动删除用户顺序。
-- 表的中文业务说明、归属和策略由 backend/storage/catalog.py 维护，DuckDB 兼容 DDL 见 ddl.py。
BEGIN;
-- 同一上游下的优先级；NULL 仅用于存量初始化，普通编辑/启停不清空。
ALTER TABLE scheduled_job ADD COLUMN IF NOT EXISTS dependency_order INTEGER;
-- 事件生成时固化的批次触发顺序；历史事件补零，仍保留原有时间顺序。
ALTER TABLE scheduled_trigger_event ADD COLUMN IF NOT EXISTS dispatch_order INTEGER NOT NULL DEFAULT 0;
-- 只填缺失值；重复升级不覆盖用户已经保存的顺序。
WITH ranked AS (
    SELECT id, row_number() OVER (
        PARTITION BY dependency_job_id ORDER BY created_at, id
    ) - 1 AS position
    FROM scheduled_job WHERE trigger_mode='dependency'
)
UPDATE scheduled_job SET dependency_order=ranked.position
FROM ranked WHERE scheduled_job.id=ranked.id AND scheduled_job.dependency_order IS NULL;
-- 新端点 GET /api/data/schedules/{job_id}/downstream 和
-- PUT /api/data/schedules/{job_id}/downstream-order 复用 data-schedule:manage，
-- 不新增或覆盖任何菜单、功能点或默认角色授权。
COMMIT;
