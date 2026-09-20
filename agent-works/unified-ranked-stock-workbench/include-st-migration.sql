BEGIN;

ALTER TABLE score_profile
    ADD COLUMN IF NOT EXISTS include_st BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE score_profile_version
    ADD COLUMN IF NOT EXISTS include_st BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE score_profile SET include_st = TRUE WHERE include_st IS NULL;
UPDATE score_profile_version SET include_st = TRUE WHERE include_st IS NULL;

-- 评分母集进入参数指纹；迁移后旧快照只失效、不在启动时集中重算。
UPDATE score_snapshot_meta SET stale = TRUE;

COMMIT;
