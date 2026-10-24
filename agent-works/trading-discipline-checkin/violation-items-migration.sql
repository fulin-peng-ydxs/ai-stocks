-- 用途：为交易纪律打卡不可变修订补充结构化未履约事项。
-- 前置/时机：已有交易纪律表；新版后端/前端发布前执行，init_pg_db 同步幂等升级。
-- 影响：仅为 trade_discipline_checkin_revision 加列、校验及中文说明，不回填历史，不改权限。
-- 回退：保留字段及已采集事实；旧客户端无法维护事项，回退期间暂停打卡写入。
BEGIN;
-- 未履约事项只新增字段，禁止按历史原因或持仓数量回填。
ALTER TABLE trade_discipline_checkin_revision ADD COLUMN IF NOT EXISTS violation_items JSONB;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid='trade_discipline_checkin_revision'::regclass
          AND conname='td_revision_violation_items_check') THEN
        ALTER TABLE trade_discipline_checkin_revision
            ADD CONSTRAINT td_revision_violation_items_check
            CHECK (jsonb_typeof(violation_items) = 'array'
        AND violation_items <@ '["missed_buy","missed_sell","other"]'::jsonb
        AND jsonb_array_length(violation_items) <= 3);
    END IF;
END $$;
COMMENT ON COLUMN trade_discipline_checkin_revision.violation_items IS '未履约事项多选：missed_buy应买未买、missed_sell应卖未卖、other买卖操作未履约；NULL为旧记录未采集，空数组为未填事项，不计入成交';
COMMIT;
