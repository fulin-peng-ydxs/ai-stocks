# DuckDB 读并发与任务运行态解耦需求

## 背景与问题

当前后端曾由一个 DuckDB 连接和一把进程锁承载所有查询、任务状态、日志、调度事件和行情写入。它能保证线程安全，但会让无关查询串行等待；任务状态本身的频繁写入还会与行情单文件写锁耦合。连板天梯首次任务也曾因另一个板块写任务占用全局写槽而创建失败。

## 目标

1. 单后端进程内允许多个纯查询并行读取 DuckDB 已提交快照。
2. DuckDB 行情写入仍保持一个专用写连接和一个全局写任务槽，不引入并发写。
3. `async_task`、`task_log`、`scheduled_job`、`scheduled_trigger_event` 迁到 PostgreSQL，任务状态与日志更新不再争抢 DuckDB 文件锁。
4. 保存全部任务、调度和事件历史；日志继续执行 30 天、每任务最近 2000 条的既有保留规则。
5. 迁移过程无双写窗口、可预演、失败原子回滚，并提供带明确确认标记的反向回退。
6. 保持单后端进程部署；执行线程和协作取消状态暂不改为分布式执行器。

## 稳定契约

- 读池默认 4 个连接、获取超时 3 秒、慢查询阈值 500ms；环境变量可把池大小设为 0，退回旧单连接查询。
- 默认模式下读池连接与写连接使用相同 DuckDB 打开配置，存储层只允许单条 `SELECT`、读 PRAGMA 或 `EXPLAIN`；禁止 DDL/DML 和多语句。
- 任务存储默认 `auto`：仅 PG 的 `migration.task_runtime_pg_v1` 为 `applied` 时切到 PG。标记无法读取或强制 PG 时标记缺失都必须 fail-closed，禁止猜测回退导致双事实源。
- 任务创建的“查重 + 单写槽检查 + pending 插入”由 PG advisory transaction lock 跨进程串行化。
- 任务终态与依赖/重试事件同一 PG 事务提交；到期事件通过 `FOR UPDATE SKIP LOCKED` 原子认领。
- DuckDB 与 PG 禁止跨库 JOIN。任务执行器分别持有 runtime client 和 market client，在服务层用稳定 ID 关联。
- DuckDB 同名旧运行态表迁移后冻结保留，不删除；回退时以 PG 全量事实原子替换旧表，并在 PG 单事务中清空四张运行表、切换 marker，允许后续重新正向迁移。

## 验收标准

- 多个读连接可以同时查询，写事务未提交时读连接看到旧的已提交版本，提交后看到新版本。
- 读池写 SQL、多 SQL、池超时分别得到明确拒绝或 503。
- 正向迁移前后四表行数一致，JSON 为 JSONB，时间为 TIMESTAMPTZ，历史 `warning` 日志等级不丢失。
- 迁移中任意约束失败时 PG 四表和 marker 同时回滚。
- 服务启动后 `/api/health` 返回 `duckdb_pool`、`task_runtime_backend=postgres` 和可信 `active_task_count`。
- 原有任务、调度、天梯协调与启停安全测试通过；后台按测试前状态恢复。

## 非目标

- 不增加前端页面、按钮或布局变更。
- 不允许多个 DuckDB 写任务并行。
- 不在本阶段引入 Celery、消息队列、多 worker 或多副本执行。
