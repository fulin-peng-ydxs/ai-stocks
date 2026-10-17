-- 用途：交易纪律选股条件、持仓上限与打卡事实快照增量升级。
-- 时机：发布新版后端/前端前执行；后端 init_pg_db 同步幂等执行相同DDL。
-- 范围：仅新增字段和约束，不改菜单、权限、现有规则版本或打卡事实。
-- 回退：应用可回退；保留新增字段以保存已采集事实，不自动删列造成数据丢失。
BEGIN;
ALTER TABLE trade_discipline_rule_version ADD COLUMN IF NOT EXISTS max_positions INTEGER CHECK (max_positions > 0);
ALTER TABLE trade_discipline_rule_draft ADD COLUMN IF NOT EXISTS max_positions INTEGER CHECK (max_positions > 0);
ALTER TABLE trade_discipline_stock_rule ADD COLUMN IF NOT EXISTS price_min NUMERIC(20,4) CHECK (price_min > 0);
ALTER TABLE trade_discipline_stock_rule ADD COLUMN IF NOT EXISTS price_max NUMERIC(20,4) CHECK (price_max > 0);
ALTER TABLE trade_discipline_stock_rule ADD COLUMN IF NOT EXISTS st_filter TEXT NOT NULL DEFAULT 'any' CHECK (st_filter IN ('any','exclude','only'));
ALTER TABLE trade_discipline_stock_rule ADD COLUMN IF NOT EXISTS loss_filter TEXT NOT NULL DEFAULT 'any' CHECK (loss_filter IN ('any','exclude','only'));
ALTER TABLE trade_discipline_stock_rule ADD COLUMN IF NOT EXISTS st_risk_filter TEXT NOT NULL DEFAULT 'any' CHECK (st_risk_filter IN ('any','exclude','only'));
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='trade_discipline_stock_rule'::regclass AND conname='trade_discipline_stock_rule_price_bounds') THEN ALTER TABLE trade_discipline_stock_rule ADD CONSTRAINT trade_discipline_stock_rule_price_bounds CHECK (price_min IS NULL OR price_max IS NULL OR price_min <= price_max); END IF; END $$;
ALTER TABLE trade_discipline_draft_stock_rule ADD COLUMN IF NOT EXISTS price_min NUMERIC(20,4) CHECK (price_min > 0);
ALTER TABLE trade_discipline_draft_stock_rule ADD COLUMN IF NOT EXISTS price_max NUMERIC(20,4) CHECK (price_max > 0);
ALTER TABLE trade_discipline_draft_stock_rule ADD COLUMN IF NOT EXISTS st_filter TEXT NOT NULL DEFAULT 'any' CHECK (st_filter IN ('any','exclude','only'));
ALTER TABLE trade_discipline_draft_stock_rule ADD COLUMN IF NOT EXISTS loss_filter TEXT NOT NULL DEFAULT 'any' CHECK (loss_filter IN ('any','exclude','only'));
ALTER TABLE trade_discipline_draft_stock_rule ADD COLUMN IF NOT EXISTS st_risk_filter TEXT NOT NULL DEFAULT 'any' CHECK (st_risk_filter IN ('any','exclude','only'));
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='trade_discipline_draft_stock_rule'::regclass AND conname='trade_discipline_draft_stock_rule_price_bounds') THEN ALTER TABLE trade_discipline_draft_stock_rule ADD CONSTRAINT trade_discipline_draft_stock_rule_price_bounds CHECK (price_min IS NULL OR price_max IS NULL OR price_min <= price_max); END IF; END $$;
ALTER TABLE trade_discipline_checkin_revision ADD COLUMN IF NOT EXISTS peak_positions INTEGER CHECK (peak_positions >= 0);
ALTER TABLE trade_discipline_operation ADD COLUMN IF NOT EXISTS selection_facts JSONB;
COMMENT ON COLUMN trade_discipline_rule_version.max_positions IS '本套规则允许同时持有的不同股票数量上限，空表示不限';
COMMENT ON COLUMN trade_discipline_rule_draft.max_positions IS '本套规则允许同时持有的不同股票数量上限，空表示不限';
COMMENT ON COLUMN trade_discipline_stock_rule.price_min IS '买入成交价下限（元、原始价、含边界），空表示不限';
COMMENT ON COLUMN trade_discipline_stock_rule.price_max IS '买入成交价上限（元、原始价、含边界），空表示不限';
COMMENT ON COLUMN trade_discipline_stock_rule.st_filter IS '买入时ST条件：any不限、exclude排除、only仅限';
COMMENT ON COLUMN trade_discipline_stock_rule.loss_filter IS '买入时亏损条件：any不限、exclude排除、only仅限；事实由用户确认';
COMMENT ON COLUMN trade_discipline_stock_rule.st_risk_filter IS '买入时ST风险条件：any不限、exclude排除、only仅限；事实由用户确认';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.price_min IS '买入成交价下限（元、原始价、含边界），空表示不限';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.price_max IS '买入成交价上限（元、原始价、含边界），空表示不限';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.st_filter IS '买入时ST条件：any不限、exclude排除、only仅限';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.loss_filter IS '买入时亏损条件：any不限、exclude排除、only仅限；事实由用户确认';
COMMENT ON COLUMN trade_discipline_draft_stock_rule.st_risk_filter IS '买入时ST风险条件：any不限、exclude排除、only仅限；事实由用户确认';
COMMENT ON COLUMN trade_discipline_checkin_revision.peak_positions IS '用户确认的当日最大同时持仓股票数，含之前持仓；空表示旧记录未采集';
COMMENT ON COLUMN trade_discipline_operation.selection_facts IS '操作时点事实快照：is_st、st_as_of_date为服务端逐日ST数据；loss_status和st_risk_status为用户是/否/未知确认，null旧记录未采集';
COMMIT;
