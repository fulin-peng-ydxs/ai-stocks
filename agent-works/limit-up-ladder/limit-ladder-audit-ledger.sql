-- 连板天梯 PostgreSQL 日期任务协调账本与可靠审计 outbox 前向升级脚本。
-- 前置条件：完成 PG 备份；应用尚未启用天梯自动首算或管理员重算入口。
-- 执行时机：部署 T5 任务协调代码前；事务、marker 与 advisory lock 保证可重复执行。
-- 影响范围：新增两张平台表，并为 audit_log 增加可空幂等事件键及唯一索引。
-- 回滚：使用 rollback-limit-ladder.sql；只删除本迁移实际创建且未被其他业务复用的对象。

BEGIN;

DO $$
DECLARE
    marker_key CONSTANT text := 'migration.limit_ladder_audit_ledger_v1';
    marker_value jsonb;
    created_audit_column boolean;
    created_audit_index boolean;
    created_ledger_table boolean;
    created_outbox_table boolean;
BEGIN
    PERFORM pg_advisory_xact_lock(8410010007);

    SELECT value::jsonb INTO marker_value FROM app_config WHERE key = marker_key;
    IF marker_value IS NOT NULL THEN
        IF coalesce((marker_value->>'version')::integer, 0) <> 1
            OR jsonb_typeof(marker_value->'created') IS DISTINCT FROM 'object'
            OR NOT coalesce(
                (marker_value->>'applied')::boolean
                <> (marker_value->>'rolled_back')::boolean,
                false
            ) THEN
            RAISE EXCEPTION '连板天梯审计账本 marker 非法，拒绝继续';
        END IF;
        RETURN;
    END IF;

    created_audit_column := NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema=current_schema()
          AND table_name='audit_log' AND column_name='source_event_key'
    );
    created_audit_index := NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname=current_schema() AND indexname='uq_audit_log_source_event_key'
    );
    created_ledger_table := to_regclass(current_schema() || '.limit_ladder_task_ledger') IS NULL;
    created_outbox_table := to_regclass(current_schema() || '.limit_ladder_audit_outbox') IS NULL;

    ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS source_event_key TEXT;
    CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_log_source_event_key
        ON audit_log (source_event_key) WHERE source_event_key IS NOT NULL;

    CREATE TABLE IF NOT EXISTS limit_ladder_task_ledger (
        command_id TEXT PRIMARY KEY,
        task_id TEXT,
        trade_date DATE NOT NULL,
        source TEXT NOT NULL CHECK (
            source IN ('auto_first_load','auto_invalid_refresh','admin_recompute')
        ),
        actor_kind TEXT NOT NULL CHECK (actor_kind IN ('system','user')),
        tenant_id TEXT,
        actor_user_id TEXT,
        actor_account TEXT NOT NULL,
        trigger_tenant_id TEXT,
        trigger_user_id TEXT,
        trigger_account TEXT,
        request_ip TEXT,
        request_method TEXT,
        request_path TEXT,
        request_id TEXT,
        status TEXT NOT NULL CHECK (
            status IN ('requested','running','succeeded','failed','interrupted')
        ),
        rule_version TEXT NOT NULL,
        result_summary JSONB,
        retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CHECK ((actor_kind='system' AND tenant_id IS NULL AND actor_user_id IS NULL
                AND actor_account='system:limit-ladder')
            OR (actor_kind='user' AND tenant_id IS NOT NULL AND actor_user_id IS NOT NULL))
    );

    CREATE TABLE IF NOT EXISTS limit_ladder_audit_outbox (
        command_id TEXT NOT NULL REFERENCES limit_ladder_task_ledger(command_id)
            ON DELETE RESTRICT,
        event_type TEXT NOT NULL CHECK (
            event_type IN ('requested','running','succeeded','failed','interrupted')
        ),
        source_event_key TEXT NOT NULL,
        payload JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','delivered')),
        retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
        next_retry_at TIMESTAMPTZ,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        delivered_at TIMESTAMPTZ,
        PRIMARY KEY (command_id, event_type),
        UNIQUE (source_event_key)
    );

    CREATE UNIQUE INDEX IF NOT EXISTS uq_limit_ladder_active_trade_date
        ON limit_ladder_task_ledger (trade_date) WHERE status IN ('requested','running');
    CREATE UNIQUE INDEX IF NOT EXISTS uq_limit_ladder_task_id
        ON limit_ladder_task_ledger (task_id) WHERE task_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_limit_ladder_outbox_delivery
        ON limit_ladder_audit_outbox (status, next_retry_at, created_at);

    INSERT INTO app_config (key,value,updated_at)
    VALUES (
        marker_key,
        jsonb_build_object(
            'version',1,
            'applied',true,
            'rolled_back',false,
            'created',jsonb_build_object(
                'audit_column',created_audit_column,
                'audit_index',created_audit_index,
                'ledger_table',created_ledger_table,
                'outbox_table',created_outbox_table
            )
        )::text,
        now()
    );
END $$;

COMMIT;

-- 验证：重复执行本脚本；同日插入两条 requested 应被拒绝，首条转终态后新命令应成功。
-- marker 的 created 字段记录迁移实际拥有的对象，回滚不得删除预先存在或已被复用的共享结构。
