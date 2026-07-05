-- ============================================================================
-- 多租户 RBAC 阶段五（stage5-platform-capabilities）平台能力表结构与默认数据
-- ----------------------------------------------------------------------------
-- 执行时机：
--   - 开发/测试：部署阶段五代码后执行，或由 init_pg_db() 幂等建表与 seed。
--   - 生产：备份 PG 后，在 resource-codes.sql 前执行，确保字典/审计表已就绪。
--
-- 影响范围：
--   - 新增 PG 表：audit_log、dict_type、dict_item。
--   - 新增索引：审计查询维度索引、字典启用/排序索引。
--   - 新增 app_config 默认项与首批内置字典枚举。
--
-- 回滚：
--   - 未产生业务数据前可 DROP TABLE dict_item、dict_type、audit_log，并删除本文件新增 app_config key。
--   - 已产生审计/字典数据后不建议 DROP，优先保留表并下线入口，避免丢失历史记录。
--
-- 事务：
--   - 整体单事务，重复执行不重复插入默认项。
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS audit_log (
    id             TEXT PRIMARY KEY,
    event_time     TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id      TEXT,
    actor_user_id  TEXT,
    actor_account  TEXT,
    event_category TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    resource_code  TEXT,
    action         TEXT,
    target_type    TEXT,
    target_id      TEXT,
    target_label   TEXT,
    result         TEXT NOT NULL,
    status         TEXT NOT NULL,
    ip             TEXT,
    method         TEXT,
    path           TEXT,
    duration_ms    INTEGER,
    error_summary  TEXT,
    context        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_time
  ON audit_log (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_time
  ON audit_log (tenant_id, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_category_time
  ON audit_log (event_category, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_type_time
  ON audit_log (event_type, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource_time
  ON audit_log (resource_code, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_result_time
  ON audit_log (result, event_time DESC);

CREATE TABLE IF NOT EXISTS dict_type (
    id         TEXT PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    sort       INTEGER NOT NULL DEFAULT 100,
    remark     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dict_item (
    id         TEXT PRIMARY KEY,
    type_code  TEXT NOT NULL REFERENCES dict_type(code) ON DELETE RESTRICT,
    code       TEXT NOT NULL,
    label      TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    sort       INTEGER NOT NULL DEFAULT 100,
    remark     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (type_code, code)
);

CREATE INDEX IF NOT EXISTS idx_dict_type_enabled_sort
  ON dict_type (enabled, sort, code);
CREATE INDEX IF NOT EXISTS idx_dict_item_type_enabled_sort
  ON dict_item (type_code, enabled, sort, code);

INSERT INTO app_config (key, value, updated_at) VALUES
  ('auth.require_email_code', 'true', now()),
  ('auth.login_captcha_enabled', 'false', now()),
  ('auth.captcha_after_fails', '3', now()),
  ('audit.retention_days', '90', now())
ON CONFLICT (key) DO NOTHING;

INSERT INTO dict_type (id, code, name, sort, remark) VALUES
  ('role_type', 'role_type', '角色类型', 10, '系统内置角色类型'),
  ('user_status', 'user_status', '用户状态', 20, '用户账号状态'),
  ('audit_event_type', 'audit_event_type', '审计事件类型', 30, '审计日志事件分类'),
  ('audit_result', 'audit_result', '审计结果', 40, '审计日志处理结果'),
  ('audit_status', 'audit_status', '审计状态', 50, '审计日志处理状态')
ON CONFLICT (code) DO NOTHING;

INSERT INTO dict_item (id, type_code, code, label, sort) VALUES
  ('role_type:system', 'role_type', 'system', '系统管理员', 10),
  ('role_type:tenant_admin', 'role_type', 'tenant_admin', '租户管理员', 20),
  ('role_type:normal', 'role_type', 'normal', '普通用户', 30),
  ('role_type:paid', 'role_type', 'paid', '付费用户', 40),
  ('user_status:active', 'user_status', 'active', '启用', 10),
  ('user_status:disabled', 'user_status', 'disabled', '停用', 20),
  ('user_status:locked', 'user_status', 'locked', '锁定', 30),
  ('audit_event_type:api', 'audit_event_type', 'api', '接口', 10),
  ('audit_event_type:task', 'audit_event_type', 'task', '任务', 20),
  ('audit_event_type:security', 'audit_event_type', 'security', '安全', 30),
  ('audit_event_type:rbac', 'audit_event_type', 'rbac', '权限', 40),
  ('audit_event_type:config', 'audit_event_type', 'config', '配置', 50),
  ('audit_event_type:dict', 'audit_event_type', 'dict', '字典', 60),
  ('audit_result:success', 'audit_result', 'success', '成功', 10),
  ('audit_result:failed', 'audit_result', 'failed', '失败', 20),
  ('audit_result:denied', 'audit_result', 'denied', '拒绝', 30),
  ('audit_status:completed', 'audit_status', 'completed', '完成', 10),
  ('audit_status:running', 'audit_status', 'running', '处理中', 20),
  ('audit_status:failed', 'audit_status', 'failed', '异常', 30),
  ('audit_status:blocked', 'audit_status', 'blocked', '已阻断', 40),
  ('audit_status:skipped', 'audit_status', 'skipped', '已跳过', 50)
ON CONFLICT (type_code, code) DO NOTHING;

COMMIT;
