-- 文件：agent-works/layout-config-productization/layout-field-policy.sql
-- 用途：可配置布局系统「字段开放策略」表。管理员在系统组件页收紧/放开
--       "某组件某字段可在哪几层（preset/page/user）覆盖"，是元配置（policy），
--       不参与运行时值合并、不构成第五层运行时优先级。
-- 执行时机：随后端启动由 backend/storage/ddl.py 的 init_db() 幂等创建
--           （已登记进 M4_TABLES，CREATE TABLE IF NOT EXISTS，无需手工执行）。
-- 影响范围：仅布局开放策略；缺表 / 缺行时回落代码声明的最大开放集
--           （COMPONENT_CONFIG_FIELDS_BY_KIND × COMPONENT_CONFIG_FIELD_RULES[field].layers）。
-- 回滚方式：DROP TABLE layout_field_policy；代码自动回落代码最大集，无数据耦合、无依赖外键。
-- 约束：allowed_layers 为 JSON 数组，取值必须是该 (kind, field) 代码最大集的非空子集，
--       越出最大集由 backend/storage/layout_config.py 的 set_field_policy 拒绝。

CREATE TABLE IF NOT EXISTS layout_field_policy (
    component_kind    VARCHAR,
    field             VARCHAR,
    allowed_layers    VARCHAR,      -- JSON 数组：preset/page/user 的非空子集
    updated_at        TIMESTAMP,
    PRIMARY KEY (component_kind, field)
);

-- 回滚：
-- DROP TABLE IF EXISTS layout_field_policy;
