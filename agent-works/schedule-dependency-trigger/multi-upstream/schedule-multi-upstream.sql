-- 用途：新增多上游依赖关系，将存量单上游幂等补为依赖边。
-- 执行时机：服务安全停服后升级；正常部署由 pg_ddl.init_pg_db 自动执行同等 DDL/补缺。
-- 影响范围：PG scheduled_job_dependency；只读取 scheduled_job，不修改菜单、权限和任务历史。
-- 字段：upstream_job_id 上游任务；downstream_job_id 下游任务；dependency_order 此上游下的优先级。
-- 回滚：旧代码只能读取单上游。先在新版本页面将各任务上游收敛为至多一个，确认兼容投影正确，
-- 再停服回滚应用；关系表可保留。直接删除该表或降级应用会丢失/忽略额外上游，不提供无损自动回滚。
BEGIN;
-- 建立依赖边主键和反向检索索引，不覆盖已有定义。

CREATE TABLE IF NOT EXISTS scheduled_job_dependency (
    upstream_job_id TEXT NOT NULL,   -- 上游调度任务标识
    downstream_job_id TEXT NOT NULL, -- 下游调度任务标识
    dependency_order INTEGER NOT NULL, -- 此上游下的触发优先级
    PRIMARY KEY (upstream_job_id, downstream_job_id)
);
CREATE INDEX IF NOT EXISTS idx_schedule_dependency_downstream
    ON scheduled_job_dependency (downstream_job_id);

-- 只补缺失关系，保留用户已调整的独立排序；重复升级不重复建边。
INSERT INTO scheduled_job_dependency (upstream_job_id, downstream_job_id, dependency_order)
SELECT dependency_job_id, id, COALESCE(dependency_order, 0) FROM scheduled_job
WHERE trigger_mode='dependency' AND dependency_job_id IS NOT NULL
ON CONFLICT (upstream_job_id, downstream_job_id) DO NOTHING;
COMMIT;
