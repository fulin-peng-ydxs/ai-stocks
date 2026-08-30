-- 连板天梯 PostgreSQL 日期任务协调账本与可靠审计 outbox 前向升级脚本。
-- 前置条件：完成 PG 备份；应用尚未启用天梯自动首算或管理员重算入口。
-- 执行时机：部署 T5 任务协调代码前；所有语句均可重复执行。
-- 影响范围：新增两张平台表，并为 audit_log 增加可空幂等事件键及唯一索引。
-- 回滚：先投递或导出 pending outbox，再删除新增对象；旧 audit_log 行不受影响。

BEGIN;

-- 先补兼容列；NULL 允许所有旧审计调用继续写入。
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS source_event_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_log_source_event_key
    ON audit_log (source_event_key) WHERE source_event_key IS NOT NULL;

-- 三种入口共享的日期任务账本；请求主体和来源在创建任务前冻结。
CREATE TABLE IF NOT EXISTS limit_ladder_task_ledger (
    command_id TEXT PRIMARY KEY,              -- 不可变命令 UUID
    task_id TEXT,                             -- DuckDB async_task.id
    trade_date DATE NOT NULL,                 -- 目标交易日
    source TEXT NOT NULL CHECK (source IN ('auto_first_load','auto_invalid_refresh','admin_recompute')), -- 触发来源
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('system','user')), -- 操作者类型
    tenant_id TEXT,                          -- 管理员所属租户；system 为空
    actor_user_id TEXT,                      -- 管理员稳定用户 ID；system 为空
    actor_account TEXT NOT NULL,             -- 创建时固化的权威账号
    trigger_tenant_id TEXT,                  -- 自动任务的触发请求租户
    trigger_user_id TEXT,                    -- 自动任务的触发请求用户
    trigger_account TEXT,                    -- 自动任务的触发请求账号
    request_ip TEXT,                         -- 服务端解析的请求 IP
    request_method TEXT,                     -- 请求方法
    request_path TEXT,                       -- 请求路径
    request_id TEXT,                         -- 请求追踪 ID
    status TEXT NOT NULL CHECK (status IN ('requested','running','succeeded','failed','interrupted')), -- 协调状态
    rule_version TEXT NOT NULL,              -- 涨停规则版本
    result_summary JSONB,                    -- 终态结果摘要
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0), -- 对账重试次数
    last_error TEXT,                         -- 最近错误摘要
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), -- 状态更新时间
    CHECK ((actor_kind='system' AND tenant_id IS NULL AND actor_user_id IS NULL
            AND actor_account='system:limit-ladder')
        OR (actor_kind='user' AND tenant_id IS NOT NULL AND actor_user_id IS NOT NULL))
);

-- 每个状态事件一行；payload 固化主体快照，投递终态时不重新推断操作者。
CREATE TABLE IF NOT EXISTS limit_ladder_audit_outbox (
    command_id TEXT NOT NULL REFERENCES limit_ladder_task_ledger(command_id) ON DELETE RESTRICT, -- 命令 ID
    event_type TEXT NOT NULL CHECK (event_type IN ('requested','running','succeeded','failed','interrupted')), -- 状态事件
    source_event_key TEXT NOT NULL,           -- audit_log 全局幂等键
    payload JSONB NOT NULL,                   -- 创建时固化的主体与请求快照
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','delivered')), -- 投递状态
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0), -- 投递重试次数
    next_retry_at TIMESTAMPTZ,                -- 下次允许投递时间
    last_error TEXT,                          -- 最近投递错误
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), -- 事件创建时间
    delivered_at TIMESTAMPTZ,                 -- 成功投递时间
    PRIMARY KEY (command_id, event_type), UNIQUE (source_event_key)
);

-- 仅活动态占用日期槽；任何终态都会释放同日新命令。
CREATE UNIQUE INDEX IF NOT EXISTS uq_limit_ladder_active_trade_date
    ON limit_ladder_task_ledger (trade_date) WHERE status IN ('requested','running');
CREATE UNIQUE INDEX IF NOT EXISTS uq_limit_ladder_task_id
    ON limit_ladder_task_ledger (task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_limit_ladder_outbox_delivery
    ON limit_ladder_audit_outbox (status, next_retry_at, created_at);

COMMIT;

-- 验证：重复执行本脚本；同日插入两条 requested 应被拒绝，首条转终态后新命令应成功。
-- 回滚前检查：SELECT * FROM limit_ladder_audit_outbox WHERE status='pending';
-- 回滚顺序：DROP TABLE limit_ladder_audit_outbox; DROP TABLE limit_ladder_task_ledger;
-- 再 DROP INDEX uq_audit_log_source_event_key; ALTER TABLE audit_log DROP COLUMN source_event_key;
