-- 分时持久化升级留痕（DuckDB）。
-- 执行时机：更新代码后，由 backend.storage.ddl.init_db 统一幂等建表；
-- 本文件用于审核，不在运行中的共享数据库手工执行建表。
-- 影响范围：新增全市场分钟事实、逐日覆盖与独立监控起点及来源证据，不修改日线/用户资产/调度配置。
-- 前置条件：按 start.sh 安全停服；本次只增量建表，随后启动会执行已登记 DDL。
-- 回滚：旧代码可忽略这些新增表；保留归档即可回退读取链路。不得默认 DROP 丢失历史。
-- 如确认不再需要归档，停服备份后由管理员另行处理，不提供自动破坏性回滚。

-- 新增分钟事实：价格不复权，成交量为手，时间为北京时间，采集时间为 UTC。

CREATE TABLE IF NOT EXISTS stock_intraday_bar (
    code VARCHAR NOT NULL,             -- 全市场股票代码
    trade_date DATE NOT NULL,          -- 北京时间交易日
    timestamp TIMESTAMP NOT NULL,     -- 北京时间分钟
    open DOUBLE,                      -- 源端开盘占位为 NULL
    high DOUBLE NOT NULL,             -- 分钟最高原始价
    low DOUBLE NOT NULL,              -- 分钟最低原始价
    close DOUBLE NOT NULL,            -- 分钟收盘原始价
    volume DOUBLE NOT NULL,           -- 分钟成交量，手
    amount DOUBLE NOT NULL,           -- 分钟成交额，元
    source VARCHAR NOT NULL,          -- sina / eastmoney / ths
    fetched_at TIMESTAMP NOT NULL,    -- UTC 采集时间
    PRIMARY KEY(code, trade_date, timestamp)
);

-- 新增逐日覆盖：监控起点来自任务范围，revision 只在行情事实变化时更新。

CREATE TABLE IF NOT EXISTS stock_intraday_coverage (
    code VARCHAR NOT NULL,            -- 监控股票
    trade_date DATE NOT NULL,         -- 预期应有分时的交易日
    point_count INTEGER DEFAULT 0,   -- 实际有效分钟点数
    status VARCHAR DEFAULT 'missing',-- ready / partial / missing
    source VARCHAR,                  -- 已归档日的来源
    fetched_at TIMESTAMP,            -- 已归档数据 UTC 采集时间
    attempted_at TIMESTAMP,          -- 最近归档尝试 UTC 时间
    failure_reason VARCHAR,          -- 空响应、请求失败或窗口过期
    diagnostics VARCHAR,             -- 清洗诊断 JSON
    revision VARCHAR,                -- 事实变化才更新的缓存修订令牌
    PRIMARY KEY(code, trade_date)
);

-- 新增独立监控起点：不依赖覆盖记录存续，不随近期源窗口滚动。
CREATE TABLE IF NOT EXISTS stock_intraday_monitor (
    code VARCHAR PRIMARY KEY,         -- 全市场股票代码，关联 stock_basic
    monitoring_start DATE NOT NULL,    -- 首次可采集窗口的首个交易日
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp -- UTC 建立时间
);

-- 旧归档升级：只为尚无独立起点的股票迁移，已有监控日期保持不变。
INSERT INTO stock_intraday_monitor(code,monitoring_start)
SELECT code,min(trade_date) FROM stock_intraday_coverage GROUP BY code
ON CONFLICT DO NOTHING;

-- 分钟维度登记：只补缺失，不覆盖已有配置。
INSERT INTO data_dimension_registry(dimension,name_cn,status,source,tables,descr)
VALUES ('intraday','分钟分时','partial','新浪/东财/同花顺',
        '["stock_intraday_bar","stock_intraday_coverage","stock_intraday_monitor"]',
        '已收盘1分钟不复权分时，独立采集、长期归档，覆盖从监控起点持续积累')
ON CONFLICT DO NOTHING;

-- 既有维度只追加新表关联，保留已有标题、来源、状态等人工维护属性。
UPDATE data_dimension_registry
SET tables=CAST(to_json(list_append(json_extract_string(tables,'$[*]'),'stock_intraday_monitor')) AS VARCHAR)
WHERE dimension='intraday'
  AND NOT list_contains(json_extract_string(tables,'$[*]'),'stock_intraday_monitor');

-- 来源证据升级：只记录真实请求；错误和空响应不覆盖最近有效窗口。

CREATE TABLE IF NOT EXISTS stock_intraday_source_state (
    code VARCHAR NOT NULL,          -- 监控股票
    source VARCHAR NOT NULL,        -- sina / eastmoney / ths
    checked_at TIMESTAMP NOT NULL,  -- 最近真实请求的 UTC 时间
    outcome VARCHAR NOT NULL,       -- ok / empty / error
    failure_reason VARCHAR,         -- 最近请求失败原因，不能当停牌证据
    evidence VARCHAR,               -- 最近有效响应的首尾、条数、逐日点数及缺失分钟 JSON
    task_id VARCHAR,                -- 最近请求所属采集或修复任务
    PRIMARY KEY(code, source)
);

-- 维度只追加证据表，保留人工维护的属性。
UPDATE data_dimension_registry
SET tables=CAST(to_json(list_append(json_extract_string(tables,'$[*]'),'stock_intraday_source_state')) AS VARCHAR)
WHERE dimension='intraday'
  AND NOT list_contains(json_extract_string(tables,'$[*]'),'stock_intraday_source_state');
