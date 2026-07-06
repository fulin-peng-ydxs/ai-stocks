-- 阶段六体验与其他资产公开能力结构升级（幂等）
-- 用途：为 R24 审计字段变更和 R28 筛选/买卖/回测公开能力补 PG 字段、约束和索引。
-- 执行时机：生产发布前随 init_pg_db() 等价迁移执行，或人工执行本 SQL。

ALTER TABLE audit_log
  ADD COLUMN IF NOT EXISTS changes JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE screen_profile
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

ALTER TABLE screen_profile
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

ALTER TABLE screen_profile
  ADD COLUMN IF NOT EXISTS published_by TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'screen_profile_visibility_check'
  ) THEN
    ALTER TABLE screen_profile
      ADD CONSTRAINT screen_profile_visibility_check
      CHECK (visibility IN ('private', 'tenant', 'public'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_screen_profile_visibility
  ON screen_profile (visibility, tenant_id, owner_user_id);

ALTER TABLE trade_profile
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

ALTER TABLE trade_profile
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

ALTER TABLE trade_profile
  ADD COLUMN IF NOT EXISTS published_by TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'trade_profile_visibility_check'
  ) THEN
    ALTER TABLE trade_profile
      ADD CONSTRAINT trade_profile_visibility_check
      CHECK (visibility IN ('private', 'tenant', 'public'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_trade_profile_visibility
  ON trade_profile (visibility, tenant_id, owner_user_id);

ALTER TABLE backtest_run
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

ALTER TABLE backtest_run
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

ALTER TABLE backtest_run
  ADD COLUMN IF NOT EXISTS published_by TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'backtest_run_visibility_check'
  ) THEN
    ALTER TABLE backtest_run
      ADD CONSTRAINT backtest_run_visibility_check
      CHECK (visibility IN ('private', 'tenant', 'public'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_backtest_run_visibility
  ON backtest_run (visibility, tenant_id, owner_user_id);

-- 回滚说明：
-- 1. 新增字段可保留不用，功能关闭时只需代码不消费。
-- 2. 若需撤回已公开资产，可执行：
--    UPDATE screen_profile SET visibility='private', published_at=NULL, published_by=NULL;
--    UPDATE trade_profile SET visibility='private', published_at=NULL, published_by=NULL;
--    UPDATE backtest_run SET visibility='private', published_at=NULL, published_by=NULL;
-- 3. audit_log.changes 为审计增强字段，保留无害；DROP COLUMN 会丢失字段级审计历史。
