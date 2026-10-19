-- 迁移留痕；由 init_db/_migrate_special_day_event_types 检测旧 CHECK 后执行。
-- 不直接对已升级库重复执行；正式实现与幂等校验以 backend/storage/ddl.py 为准。
BEGIN TRANSACTION;
ALTER TABLE stock_special_trading_day RENAME TO special_day_migration_old;

CREATE TABLE IF NOT EXISTS stock_special_trading_day (
    code VARCHAR NOT NULL, -- 股票标准代码
    trade_date DATE NOT NULL, -- 仅在此交易日生效
    event_type VARCHAR NOT NULL CHECK (event_type IN ('delisting_first_day', 'resumption_no_limit')), -- 公告确认无涨跌幅限制
    announcement_date DATE NOT NULL CHECK (announcement_date <= trade_date), -- 公告日期
    source_ref VARCHAR NOT NULL, -- 官方公告链接
    note VARCHAR NOT NULL, -- 人工核验说明/撤销原因
    active BOOLEAN NOT NULL, -- false 表示已撤销，保留记录
    task_id VARCHAR NOT NULL, -- 维护任务，关联 PG async_task（服务层）
    updated_at TIMESTAMP NOT NULL, -- 最近维护时间
    PRIMARY KEY (code, trade_date)
);

INSERT INTO stock_special_trading_day SELECT * FROM special_day_migration_old;
DROP TABLE special_day_migration_old;
COMMIT;
