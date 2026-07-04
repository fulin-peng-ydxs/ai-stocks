-- 评分方案公开能力结构升级（幂等）
ALTER TABLE score_profile
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

ALTER TABLE score_profile
  ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

ALTER TABLE score_profile
  ADD COLUMN IF NOT EXISTS published_by TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'score_profile_visibility_check'
  ) THEN
    ALTER TABLE score_profile
      ADD CONSTRAINT score_profile_visibility_check
      CHECK (visibility IN ('private', 'tenant', 'public'));
  END IF;
END $$;

-- 平台内置预设作为全体公开方案，新用户不复制数据也能直接看到。
UPDATE score_profile
SET visibility = 'public',
    published_at = COALESCE(published_at, updated_at, created_at, now()),
    published_by = COALESCE(published_by, 'admin')
WHERE tenant_id = 'default'
  AND owner_user_id = 'admin'
  AND is_preset IS TRUE;

CREATE INDEX IF NOT EXISTS idx_score_profile_visibility
  ON score_profile (visibility, tenant_id, owner_user_id);
