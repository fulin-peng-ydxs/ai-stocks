-- 用途：交易纪律分类检查项与逐项核对快照增量迁移。
-- 时机：升级数据库和后端后再发布前端；init_pg_db 幂等执行相同 SQL。
-- 范围：两个选股规则表、操作表；不改已有业务值、归属、菜单或授权。
-- 回退：保留新增字段与快照；旧应用无法编辑新检查项，回退期间应暂停规则编辑和打卡写入；不删列以免丢失事实。
BEGIN;
-- 检查项只扩展规则快照，不从旧文本拆分或重写历史记录。
ALTER TABLE trade_discipline_stock_rule ADD COLUMN IF NOT EXISTS checklist_items JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(checklist_items) = 'array');
ALTER TABLE trade_discipline_draft_stock_rule ADD COLUMN IF NOT EXISTS checklist_items JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(checklist_items) = 'array');
ALTER TABLE trade_discipline_operation ADD COLUMN IF NOT EXISTS checklist_results JSONB CHECK (jsonb_typeof(checklist_results) = 'array');
-- 原正文现为可选补充说明；只替换旧正文非空约束，保留名称和其它约束。
ALTER TABLE trade_discipline_stock_rule ALTER COLUMN content DROP NOT NULL;
DO $$ DECLARE old_constraint RECORD; BEGIN
    FOR old_constraint IN SELECT conname FROM pg_constraint
        WHERE conrelid='trade_discipline_stock_rule'::regclass AND contype='c'
        AND position('btrim(content)' in pg_get_constraintdef(oid)) > 0
    LOOP
        EXECUTE 'ALTER TABLE trade_discipline_stock_rule DROP CONSTRAINT ' || quote_ident(old_constraint.conname);
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid='trade_discipline_stock_rule'::regclass
        AND conname='trade_discipline_stock_rule_name_required') THEN
        ALTER TABLE trade_discipline_stock_rule ADD CONSTRAINT trade_discipline_stock_rule_name_required CHECK (btrim(name) <> '');
    END IF;
END $$;
COMMENT ON COLUMN trade_discipline_stock_rule.checklist_items IS '版本化人工检查项：item_id稳定标识、category基本/风险/技术；旧other读取兼容技术形态、text条件、display_order顺序；空数组表示未配置';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.checklist_items IS '草稿人工检查项，与正式版本同结构；发布前允许空正文，旧文本不自动拆分';
COMMENT ON COLUMN trade_discipline_operation.checklist_results IS '买入逐项人工核对快照：item_id属于所选版本规则、status为yes符合/no不符合/unknown未知；空表示未记录或不适用';
COMMENT ON COLUMN trade_discipline_stock_rule.content IS '选股规则补充说明，保留原文换行，不参与逐项自动判定';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.content IS '草稿选股规则补充说明，保留原文换行';
COMMIT;
