-- 用途：逐日股本及市值来源元数据。由 backend.storage.ddl.init_db 自动执行，禁止手工绕过。
-- 执行时机：备份后升级启动；影响 DuckDB 股本事实/最新投影/市值来源，PG 无结构变更。
-- 回滚：停止写任务与后端，恢复升级前 DuckDB 及对应代码；不要在线删除新表或来源列。
-- 股本单位股，trade_date 对齐日线；effective_date 生效日，available_date 真实公告日，仅作溯源。
-- 来源逐字段登记；total_mv_eligible 仅确认全为 A 股时为 true。

CREATE TABLE IF NOT EXISTS stock_share_capital_daily (
    code VARCHAR,
    trade_date DATE,
    total_share BIGINT,
    float_share BIGINT,
    total_source VARCHAR,
    float_source VARCHAR,
    total_effective_date DATE,
    float_effective_date DATE,
    total_available_date DATE,
    float_available_date DATE,
    total_mv_eligible BOOLEAN,
    updated_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (code, trade_date)
);

-- 最新投影的事实日期；旧值 NULL 表示未认证，不当作逐日股本使用。
ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS total_share_date DATE;
ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS float_share_date DATE;
-- computed: 前缀为计算来源；NULL 为来源尚未认证的历史值。
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS total_mv_source VARCHAR;
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS float_mv_source VARCHAR;

-- 补缺维度登记；已有管理员配置不覆盖。
INSERT INTO data_dimension_registry(dimension,name_cn,status,source,tables,descr)
VALUES ('share_capital','逐日股本','collected','东财/新浪','["stock_share_capital_daily"]',
        '同日总股本/流通A股及生效、可用日期；用于股本指标和缺失市值补算')
ON CONFLICT(dimension) DO NOTHING;

-- 原始事件归档：由同一 init_db 在备份后执行，不手工建表。
-- source_record 按来源变更日期生效，公告日期不限制历史使用。
-- 旧 history 表保留兼容结构但不再写入或查询；异步 rebuild_events_only 重放到统一逐日表并清理旧派生行。
-- 回滚须停服后恢复完整备份库和代码，不在线删除原始记录。

CREATE TABLE IF NOT EXISTS stock_share_capital_event (
    event_id VARCHAR PRIMARY KEY,
    code VARCHAR,
    source VARCHAR,
    effective_date DATE,
    available_date DATE,
    date_basis VARCHAR, -- source_record=来源变更日期，沿用至下一次变动
    change_reason VARCHAR,
    total_share BIGINT,
    float_share BIGINT,
    raw_payload VARCHAR,
    active BOOLEAN,
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_share_capital_history (
    code VARCHAR,
    trade_date DATE,
    total_share BIGINT,
    float_share BIGINT,
    total_source VARCHAR,
    float_source VARCHAR,
    total_effective_date DATE,
    float_effective_date DATE,
    total_available_date DATE,
    float_available_date DATE,
    total_basis VARCHAR,
    float_basis VARCHAR,
    total_event_id VARCHAR,
    float_event_id VARCHAR,
    total_mv DOUBLE,
    float_mv DOUBLE,
    total_mv_source VARCHAR,
    float_mv_source VARCHAR,
    updated_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (code,trade_date)
);


-- 市值统一：升级启动幂等新增接口证据列；不在启动迁移中扫描/重写千万行。
-- 前置：停止写任务并备份完整 DuckDB；业务数据重算走异步 share_capital_history/recalculate_only。
-- 影响：daily_metrics 计算值优先，原有效非计算值在任务中逐批归档；不修改股本、日线。
-- 回滚：停止任务及服务后恢复备份数据库和匹配代码，不在线删除证据列。
-- 接口原始总市值（元），用于核验与兜底
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS reported_total_mv DOUBLE;
-- 接口来源，legacy_unknown 为来源未认证旧值
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS reported_total_mv_source VARCHAR;
-- 同次接口价格，仅作核验；旧数据未知则为空
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS reported_total_close DOUBLE;
-- 接口原始流通市值（元），用于核验与兜底
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS reported_float_mv DOUBLE;
-- 接口来源，legacy_unknown 为来源未认证旧值
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS reported_float_mv_source VARCHAR;
-- 同次接口价格，仅作核验；旧数据未知则为空
ALTER TABLE daily_metrics ADD COLUMN IF NOT EXISTS reported_float_close DOUBLE;
