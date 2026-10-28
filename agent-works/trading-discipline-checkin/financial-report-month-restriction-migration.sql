-- 用途：为交易纪律草稿和正式版本增加财报月份交易限制开关。
-- 前置/时机：既有交易纪律表已建立；先升级数据库及后端，再发布前端。
-- 影响：仅新增布尔字段及字段说明，旧规则默认关闭；不改归属、权限和历史快照。
-- 回退：保留新增列和已发布版本；旧应用不支持此规则，回退期间暂停规则及打卡写入。
BEGIN;
-- 每套纪律版本独立保存开关；旧规则保持关闭，不改写历史日结快照。
ALTER TABLE trade_discipline_rule_version ADD COLUMN IF NOT EXISTS restrict_financial_report_months BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE trade_discipline_rule_draft ADD COLUMN IF NOT EXISTS restrict_financial_report_months BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN trade_discipline_rule_version.restrict_financial_report_months IS '限制财报月份交易：3/7/9月各选股分组成本不超过分配资金的一半，月末最后交易日清仓，4/8/10月禁止持仓；默认关闭';
COMMENT ON COLUMN trade_discipline_rule_draft.restrict_financial_report_months IS '财报月份交易限制草稿开关，发布后按版本生效；默认关闭';
COMMIT;
