-- 交易纪律“部分履约”兼容迁移。
-- 用途：扩展总履约结果，并为每笔操作增加可空的履约状态快照。
-- 执行时机：发布包含部分履约能力的新后端前；应用启动的 PG schema 初始化也会幂等执行同等迁移。
-- 影响范围：仅 trade_discipline_checkin_revision 与 trade_discipline_operation；不改写历史业务数据。
-- 回滚说明：发布新数据前可删除新增约束和 compliance_status 字段并恢复旧 assessment 约束；
-- 一旦已有 partial 记录，回滚会丢失业务事实，必须先导出并人工转换，因此不提供自动破坏性回滚语句。

BEGIN;

-- 历史操作保持 NULL；只有部分履约的新修订会写 complied / breached。
ALTER TABLE trade_discipline_operation
    ADD COLUMN IF NOT EXISTS compliance_status TEXT;

-- 清理旧版自动命名的 assessment 校验，保留已升级后的稳定命名约束。
DO $$
DECLARE item RECORD;
BEGIN
    FOR item IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.conrelid = 'trade_discipline_checkin_revision'::regclass
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%assessment%'
          AND c.conname NOT IN (
              'td_revision_assessment_check',
              'td_revision_violation_detail_check'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE trade_discipline_checkin_revision DROP CONSTRAINT %I',
            item.conname
        );
    END LOOP;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'td_revision_assessment_check'
    ) THEN
        ALTER TABLE trade_discipline_checkin_revision
            ADD CONSTRAINT td_revision_assessment_check
            CHECK (assessment IN ('complied', 'partial', 'breached'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'td_revision_violation_detail_check'
    ) THEN
        ALTER TABLE trade_discipline_checkin_revision
            ADD CONSTRAINT td_revision_violation_detail_check
            CHECK (
                (assessment IN ('partial', 'breached')
                    AND btrim(coalesce(violation_detail, '')) <> '')
                OR (assessment = 'complied' AND violation_detail IS NULL)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'td_operation_compliance_status_check'
    ) THEN
        ALTER TABLE trade_discipline_operation
            ADD CONSTRAINT td_operation_compliance_status_check
            CHECK (
                compliance_status IS NULL
                OR compliance_status IN ('complied', 'breached')
            );
    END IF;
END $$;

COMMIT;
