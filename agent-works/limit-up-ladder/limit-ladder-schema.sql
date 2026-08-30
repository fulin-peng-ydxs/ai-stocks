-- 连板天梯 DuckDB 领域表前向升级脚本。
-- 前置条件：停止持有目标 DuckDB 写锁的后端进程，并完成数据库备份。
-- 执行时机：启用连板天梯 ST 采集或快照计算代码前；可重复执行。
-- 影响范围：仅新增点时 ST、不可变快照及聚合表，不修改行情和任务中心表。
-- 回滚：默认保留事实数据；确认永久撤销且已备份后，按文末逆依赖顺序删除。

BEGIN TRANSACTION;

-- 每只股票在每个交易日唯一的当前 ST 事实；quality 防止近似事实伪装为准确事实。
CREATE TABLE IF NOT EXISTS stock_st_status_daily (
    code VARCHAR NOT NULL,             -- 股票代码（含交易所后缀）
    trade_date DATE NOT NULL,          -- 点时交易日
    is_st BOOLEAN NOT NULL,            -- 当日是否风险警示
    source VARCHAR NOT NULL,            -- 权威来源或近似来源
    source_ref VARCHAR,                 -- 来源记录引用
    quality VARCHAR NOT NULL CHECK (quality IN ('accurate', 'approximate')),
    captured_at TIMESTAMP NOT NULL,     -- 首次捕获时间
    updated_at TIMESTAMP NOT NULL,      -- 当前事实更新时间
    PRIMARY KEY (code, trade_date)
);

-- ST 事实发生值、来源或质量变化时追加的不可变历史。
CREATE TABLE IF NOT EXISTS stock_st_status_history (
    version_id VARCHAR PRIMARY KEY,       -- 不可变版本 ID
    code VARCHAR NOT NULL,                -- 股票代码
    trade_date DATE NOT NULL,             -- 受影响交易日
    old_is_st BOOLEAN,                    -- 变更前状态；首次写入为空
    new_is_st BOOLEAN NOT NULL,           -- 变更后状态
    old_source VARCHAR,                   -- 变更前来源
    new_source VARCHAR NOT NULL,          -- 变更后来源
    old_source_ref VARCHAR,               -- 变更前来源引用
    new_source_ref VARCHAR,               -- 变更后来源引用
    old_quality VARCHAR CHECK (old_quality IS NULL OR old_quality IN ('accurate', 'approximate')), -- 变更前质量
    new_quality VARCHAR NOT NULL CHECK (new_quality IN ('accurate', 'approximate')), -- 变更后质量
    change_reason VARCHAR NOT NULL,       -- 变更原因
    changed_at TIMESTAMP NOT NULL,        -- 变更时间
    task_id VARCHAR                        -- 产生变更的任务 ID
);

-- 日期级发布状态和当前成功版本指针；失败或失效时不清除 current_snapshot_id。
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_state (
    trade_date DATE PRIMARY KEY,
    status VARCHAR NOT NULL CHECK (status IN ('calculating','valid','invalid','recalculating','failed')),
    current_snapshot_id VARCHAR,          -- 当前最后成功快照 ID
    last_success_at TIMESTAMP,            -- 最近成功发布时间
    task_id VARCHAR,                      -- 当前/最近计算任务 ID
    rule_version VARCHAR NOT NULL,        -- 涨停规则版本
    upstream_fingerprint VARCHAR,         -- 上游事实指纹
    failure_summary VARCHAR,              -- 最近失败摘要
    invalid_reason VARCHAR,               -- 失效原因
    updated_at TIMESTAMP NOT NULL         -- 状态更新时间
);

-- 每次成功发布的不可变版本元数据；stock_count=0 表达门禁闭合后的合法空快照。
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot (
    snapshot_id VARCHAR PRIMARY KEY,      -- 不可变快照 ID
    trade_date DATE NOT NULL,             -- 业务交易日
    rule_version VARCHAR NOT NULL,        -- 涨停规则版本
    computed_at TIMESTAMP NOT NULL,       -- 计算完成时间
    stock_count INTEGER NOT NULL CHECK (stock_count >= 0), -- 涨停股票数
    has_approx_st BOOLEAN NOT NULL,       -- 是否含近似 ST 事实
    coverage_json VARCHAR NOT NULL,       -- 完整性门禁摘要 JSON
    source_version VARCHAR NOT NULL       -- 上游来源版本
);

-- 成功快照内的股票事实，冻结名称、板块、ST、板位、成交额和行业归属。
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_stock (
    snapshot_id VARCHAR NOT NULL,         -- 所属快照 ID
    code VARCHAR NOT NULL,                -- 股票代码
    name VARCHAR NOT NULL,                -- 名称快照
    board VARCHAR NOT NULL,               -- 上市板块
    price_limit_pct DOUBLE NOT NULL CHECK (price_limit_pct > 0), -- 当日适用比例
    is_st BOOLEAN NOT NULL,               -- 当日 ST 状态
    st_quality VARCHAR NOT NULL CHECK (st_quality IN ('accurate', 'approximate')), -- ST 质量
    st_source VARCHAR NOT NULL,            -- ST 来源
    is_one_word BOOLEAN NOT NULL,          -- 是否一字板
    consecutive_days INTEGER NOT NULL CHECK (consecutive_days >= 1), -- 连续板高度
    amount DOUBLE NOT NULL CHECK (isfinite(amount) AND amount >= 0), -- 当日成交额
    industry_name VARCHAR NOT NULL,        -- 单一权威行业名
    industry_board_code VARCHAR,           -- 唯一精确匹配时的行业板块码
    source_version VARCHAR NOT NULL,       -- 上游来源版本
    PRIMARY KEY (snapshot_id, code)
);

-- R10 快照概念多归属；与查询时读取的最新走势相关概念分离。
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_concept (
    snapshot_id VARCHAR NOT NULL,          -- 所属快照 ID
    code VARCHAR NOT NULL,                 -- 股票代码
    board_code VARCHAR NOT NULL,           -- 概念板块码
    board_name VARCHAR NOT NULL,           -- 概念名称快照
    source_version VARCHAR NOT NULL,       -- 概念来源版本
    PRIMARY KEY (snapshot_id, code, board_code)
);

-- 对完整快照的行业/概念聚合校验结果；筛选聚合由服务层重算。
CREATE TABLE IF NOT EXISTS limit_ladder_snapshot_aggregate (
    snapshot_id VARCHAR NOT NULL,          -- 所属快照 ID
    group_type VARCHAR NOT NULL CHECK (group_type IN ('industry', 'concept')), -- 行业或概念
    group_key VARCHAR NOT NULL,             -- 稳定分组键
    group_name VARCHAR NOT NULL,            -- 分组显示名
    stock_count INTEGER NOT NULL CHECK (stock_count >= 0), -- 股票数
    PRIMARY KEY (snapshot_id, group_type, group_key)
);

CREATE INDEX IF NOT EXISTS idx_st_status_history_code_date
    ON stock_st_status_history (code, trade_date, changed_at);
CREATE INDEX IF NOT EXISTS idx_limit_ladder_snapshot_date
    ON limit_ladder_snapshot (trade_date, computed_at);
CREATE INDEX IF NOT EXISTS idx_limit_ladder_stock_snapshot
    ON limit_ladder_snapshot_stock (snapshot_id, consecutive_days);

COMMIT;

-- 验证：查询 information_schema.tables 确认上述七张表存在，并重复执行本脚本验证幂等。
-- 确认永久删除时的逆依赖回滚顺序：aggregate、concept、stock、state、snapshot、history、daily。
