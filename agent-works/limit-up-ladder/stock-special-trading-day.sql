-- 用途：特殊交易日事实表，随 init_db 幂等执行；不直接写入业务事实。
-- 前置：DuckDB 独占写连接。影响：新增参考表，无历史价格改写。
-- 回滚：先回退消费者，再备份并删除本表；已发布快照需重新校验，不能仅删表恢复。
CREATE TABLE IF NOT EXISTS stock_special_trading_day (
    code VARCHAR NOT NULL, -- 股票标准代码
    trade_date DATE NOT NULL, -- 仅在此交易日生效
    event_type VARCHAR NOT NULL CHECK (event_type = 'delisting_first_day'), -- 退市整理首日
    announcement_date DATE NOT NULL CHECK (announcement_date <= trade_date), -- 公告日期
    source_ref VARCHAR NOT NULL, -- 官方公告链接
    note VARCHAR NOT NULL, -- 人工核验说明/撤销原因
    active BOOLEAN NOT NULL, -- false 表示已撤销，保留记录
    task_id VARCHAR NOT NULL, -- 维护任务，关联 PG async_task（服务层）
    updated_at TIMESTAMP NOT NULL, -- 最近维护时间
    PRIMARY KEY (code, trade_date)
);
