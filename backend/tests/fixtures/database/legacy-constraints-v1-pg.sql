-- 已识别的旧 CHECK，只用于隔离门禁；初始化必须先验证目标约束再替换。
ALTER TABLE limit_ladder_task_ledger DROP CONSTRAINT limit_ladder_task_ledger_check;
ALTER TABLE limit_ladder_task_ledger ADD CONSTRAINT legacy_actor_check
    CHECK ((actor_kind='system' AND actor_user_id IS NULL)
        OR (actor_kind='user' AND tenant_id IS NOT NULL AND actor_user_id IS NOT NULL));
ALTER TABLE trade_discipline_checkin ADD CONSTRAINT legacy_checkin_check
    CHECK ((status='submitted' AND amended_at IS NULL) OR status='amended');
ALTER TABLE trade_discipline_rule ADD CONSTRAINT legacy_version_check
    CHECK (latest_version_no IS NULL OR latest_version_no>0);
