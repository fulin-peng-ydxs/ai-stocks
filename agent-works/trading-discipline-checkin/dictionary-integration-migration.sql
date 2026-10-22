-- 用途：交易纪律买卖类型与选股检查项分类接入系统数据字典，增加类型名称快照。
-- 时机：数据库与后端先升级，随后发布前端；init_pg_db 执行同等幂等 DDL/seed。
-- 范围：仅补缺失字典、字典项和快照列；不将个人类型提升为公共数据，不回写正式版本/操作修订。
-- 回退：保留新增列和字典数据，旧应用无法正确展示自定义分类；回退期间应暂停规则及打卡写入。
BEGIN;
-- 名称在首次选用时由服务端写入，旧记录保持 NULL，读取时兼容旧编码。
ALTER TABLE trade_discipline_action_rule ADD COLUMN IF NOT EXISTS action_subtype_label TEXT;
ALTER TABLE trade_discipline_draft_action_rule ADD COLUMN IF NOT EXISTS action_subtype_label TEXT;
COMMENT ON COLUMN trade_discipline_action_rule.action_subtype_label IS '发布版本的买卖类型名称快照；旧版本为空时按旧编码兼容展示，不跟随字典改名';
COMMENT ON COLUMN trade_discipline_draft_action_rule.action_subtype_label IS '草稿的买卖类型名称快照，由服务端从字典或原明细生成，禁止信任客户端标签';
COMMENT ON COLUMN trade_discipline_stock_rule.checklist_items IS '版本化人工检查项：item_id稳定标识、category为选股分类字典编码、category_label分类名称快照；旧other读取兼容技术形态、text条件、display_order顺序；空数组表示未配置';
-- 字典为平台共享配置，管理权限沿用 dict:type-manage / dict:item-manage；普通业务用户仅消费。
INSERT INTO dict_type (id,code,name,sort,remark) VALUES ('trade_discipline_buy_type','trade_discipline_buy_type','交易纪律买入类型',60,'买入规则类型，编码固定，停用后旧版本保留') ON CONFLICT (code) DO NOTHING;
INSERT INTO dict_type (id,code,name,sort,remark) VALUES ('trade_discipline_sell_type','trade_discipline_sell_type','交易纪律卖出类型',70,'卖出规则类型，编码固定，停用后旧版本保留') ON CONFLICT (code) DO NOTHING;
INSERT INTO dict_type (id,code,name,sort,remark) VALUES ('trade_discipline_condition_category','trade_discipline_condition_category','选股检查项分类',80,'自定义人工检查项分类；notes保留给补充说明，不可用作分类编码') ON CONFLICT (code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_buy_type:open_position','trade_discipline_buy_type','open_position','建仓',10,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_buy_type:add_position','trade_discipline_buy_type','add_position','加仓',20,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_sell_type:liquidate','trade_discipline_sell_type','liquidate','清仓',10,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_sell_type:reduce_position','trade_discipline_sell_type','reduce_position','减仓',20,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_condition_category:basic','trade_discipline_condition_category','basic','基本条件',10,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_condition_category:risk','trade_discipline_condition_category','risk','风险排除',20,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
INSERT INTO dict_item (id,type_code,code,label,sort,color) VALUES ('trade_discipline_condition_category:technical','trade_discipline_condition_category','technical','技术形态',30,'#409EFF') ON CONFLICT (type_code,code) DO NOTHING;
COMMIT;
