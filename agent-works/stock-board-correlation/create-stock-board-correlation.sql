-- 个股走势关联板块：DuckDB 当前态结构升级脚本
--
-- 执行时机：部署包含相关性计算服务的版本前执行；应用 init_db 也会幂等创建相同结构。
-- 前置条件：确认目标为行情 DuckDB，执行进程持有唯一写锁，且数据库不是只读模式。
-- 影响范围：只新增两张空表，不写冠军、调度、菜单、权限或其它初始化数据。
-- 验证方式：执行后检查 information_schema.tables 与 PRAGMA table_info；重复执行应成功。
-- 回滚方式：执行 rollback-stock-board-correlation.sql。回滚会删除这两张派生表及其中数据。

BEGIN TRANSACTION;

-- 每只股票的行业/概念各最多一个当前冠军，不保存候选或历史快照。
CREATE TABLE IF NOT EXISTS stock_board_correlation (
    code               VARCHAR NOT NULL,  -- 含交易所后缀的股票代码
    board_type         VARCHAR NOT NULL CHECK (board_type IN ('industry', 'concept')), -- 冠军类型
    board_code         VARCHAR NOT NULL,  -- 关联 board_dict 的冠军板块代码
    score              DOUBLE NOT NULL CHECK (isfinite(score) AND score BETWEEN -1 AND 1), -- 加权分
    corr_20            DOUBLE NOT NULL CHECK (isfinite(corr_20) AND corr_20 BETWEEN -1 AND 1), -- 20日相关
    corr_60            DOUBLE NOT NULL CHECK (isfinite(corr_60) AND corr_60 BETWEEN -1 AND 1), -- 60日相关
    sample_20          INTEGER NOT NULL CHECK (sample_20 >= 15), -- 20日有效样本数
    sample_60          INTEGER NOT NULL CHECK (sample_60 >= 40), -- 60日有效样本数
    confidence         VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')), -- 可信度
    benchmark_code     VARCHAR NOT NULL,  -- 实际使用的市场基准代码
    benchmark_fallback BOOLEAN NOT NULL DEFAULT FALSE, -- 是否整股回退上证指数
    as_of_date         DATE NOT NULL,     -- 本轮共同目标交易日
    computed_at        TIMESTAMP NOT NULL, -- 本轮成功计算时间
    algorithm_version  VARCHAR NOT NULL,  -- 算法版本
    PRIMARY KEY (code, board_type)
);

-- 每股最近一次成功处理状态；两类冠军均不存在也是合法结果。
CREATE TABLE IF NOT EXISTS stock_board_correlation_state (
    code                    VARCHAR PRIMARY KEY, -- 含交易所后缀的股票代码
    as_of_date              DATE NOT NULL,       -- 本轮共同目标交易日
    computed_at             TIMESTAMP NOT NULL,  -- 本轮成功处理时间
    algorithm_version       VARCHAR NOT NULL,    -- 算法版本
    benchmark_code          VARCHAR NOT NULL,    -- 实际使用的市场基准代码
    benchmark_fallback      BOOLEAN NOT NULL DEFAULT FALSE, -- 是否整股回退上证指数
    has_industry_champion   BOOLEAN NOT NULL DEFAULT FALSE, -- 是否存在行业冠军
    has_concept_champion    BOOLEAN NOT NULL DEFAULT FALSE  -- 是否存在概念冠军
);

COMMIT;

-- 执行后验证（按需取消注释）：
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'main'
--   AND table_name IN ('stock_board_correlation', 'stock_board_correlation_state');
-- PRAGMA table_info('stock_board_correlation');
-- PRAGMA table_info('stock_board_correlation_state');
