-- 用途：逐日股本及市值来源元数据。由 backend.storage.ddl.init_db 自动执行，禁止手工绕过。
-- 执行时机：备份后升级启动；影响 DuckDB 股本事实/最新投影/市值来源，PG 无结构变更。
-- 回滚：停止写任务与后端，恢复升级前 DuckDB 及对应代码；不要在线删除新表或来源列。
-- 股本单位股，trade_date 对齐日线；effective_date 生效日，available_date 公告可用日。
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
