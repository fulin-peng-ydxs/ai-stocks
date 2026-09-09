-- 任务运行态 PostgreSQL 结构归档。
-- 权威执行入口为 backend/storage/pg_ddl.py::init_pg_db；本文件用于审查和运维留痕。

CREATE TABLE IF NOT EXISTS storage_migration (
    marker TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('applied', 'rolled_back')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS async_task (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('pending','running','done','failed','interrupted')),
    progress DOUBLE PRECISION NOT NULL DEFAULT 0,
    message TEXT,
    result JSONB,
    trigger_source TEXT,
    job_id TEXT,
    job_name TEXT,
    chain_id TEXT,
    parent_task_id TEXT,
    trigger_event_id TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    execution_attempt INTEGER NOT NULL DEFAULT 1,
    cancel_requested_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS task_log (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES async_task(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('info','warn','warning','error')),
    message TEXT NOT NULL,
    UNIQUE (task_id, seq)
);

CREATE TABLE IF NOT EXISTS scheduled_job (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    freq_type TEXT,
    freq_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    trigger_mode TEXT NOT NULL DEFAULT 'time' CHECK (trigger_mode IN ('time','dependency')),
    dependency_job_id TEXT,
    dependency_condition TEXT,
    dependency_delay JSONB NOT NULL DEFAULT '{"value":0,"unit":"minute"}'::jsonb,
    retry_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    trading_day_only BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMPTZ,
    last_task_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_trigger_event (
    id TEXT PRIMARY KEY,
    chain_id TEXT,
    source_task_id TEXT NOT NULL,
    source_attempt INTEGER NOT NULL DEFAULT 1,
    source_status TEXT NOT NULL,
    target_job_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('dependency','retry')),
    trigger_condition TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    due_at TIMESTAMPTZ NOT NULL,
    dispatched_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (
        status IN ('waiting','dispatching','dispatched','cancelled','exhausted','failed')
    ),
    task_id TEXT,
    job_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_async_task_trigger_event
    ON async_task (trigger_event_id) WHERE trigger_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_async_task_status_created
    ON async_task (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_async_task_type_status
    ON async_task (task_type, status);
CREATE INDEX IF NOT EXISTS idx_task_log_task_seq ON task_log (task_id, seq);
CREATE INDEX IF NOT EXISTS idx_task_log_ts ON task_log (ts);
CREATE INDEX IF NOT EXISTS idx_scheduled_job_enabled
    ON scheduled_job (enabled, trigger_mode);
CREATE INDEX IF NOT EXISTS idx_scheduled_event_due
    ON scheduled_trigger_event (status, due_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_event_target
    ON scheduled_trigger_event (target_job_id, created_at DESC);
