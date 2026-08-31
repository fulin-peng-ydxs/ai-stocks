-- 板块成员首次观测日期升级
--
-- 用途：为累计、只进不出的 board_member 增加首次完整采集业务日，使历史相关性计算
--       排除明确在目标日之后才首次观测到的关系。
-- 执行时机：应用启动 init_db 会自动幂等执行；仅在自动初始化不可用时停服后手工执行。
-- 影响范围：只增加 nullable 字段，不回填存量行。NULL 存量关系按业务约定视为历史已存在，
--           任意历史目标日均可参与；升级后新关系由采集服务写 first_seen_date。
-- 前置条件：确认目标为行情 DuckDB，并确保没有其它 DuckDB 写进程。
-- 回滚：通常无需回滚；若必须撤销，停服备份后执行
--       ALTER TABLE board_member DROP COLUMN first_seen_date;
--       该操作会永久丢失升级后记录的首次观测日期。

BEGIN TRANSACTION;

ALTER TABLE board_member ADD COLUMN IF NOT EXISTS first_seen_date DATE;

COMMIT;

-- 验证：
-- SELECT name, type FROM pragma_table_info('board_member') WHERE name='first_seen_date';
