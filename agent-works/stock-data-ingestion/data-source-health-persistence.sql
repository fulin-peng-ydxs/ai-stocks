-- 用途：持久化各外部数据源最近一次联通测试结果，避免页面刷新或后端重启后状态丢失。
-- 执行时机：应用升级启动时由 backend/storage/pg_ddl.py 幂等执行；本文件用于人工审计与受控迁移。
-- 影响范围：仅新增平台级运行态表，不修改行情、用户资产、权限或既有配置。
-- 回滚方式：确认无需保留联通测试记录后执行 DROP TABLE data_source_health；回滚会永久删除历史最近状态。

CREATE TABLE IF NOT EXISTS data_source_health (
    source          TEXT PRIMARY KEY,                   -- 数据源稳定标识
    is_up           BOOLEAN NOT NULL,                   -- 最近一次测试是否连通
    last_test_at    TIMESTAMPTZ NOT NULL,               -- 最近一次测试时间
    last_success_at TIMESTAMPTZ,                        -- 最近一次成功时间，失败测试不覆盖
    failure_reason  TEXT,                               -- 最近一次失败原因，成功时为空
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()  -- 记录更新时间
);
