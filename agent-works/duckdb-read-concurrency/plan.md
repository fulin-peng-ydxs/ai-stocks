# DuckDB 读并发与任务运行态解耦开发计划

## 阶段一：DuckDB 单写多读

1. 在配置模型与 YAML 中加入读池大小、获取超时和慢查询阈值，并提供池大小环境变量 kill switch。
2. 保留 `get_client()` 兼容入口，新增显式 `get_write_client()`、`get_read_client()` 和统一关闭函数。
3. 读池惰性创建同配置独立连接；statement type 校验禁止写和多语句；统计 active/idle/query/timeout。
4. 将股票、方案试算、交易纪律股票选择、板块查询、天梯读模型、数据校验和市场基准等纯读入口切到读池。
5. 健康检查用 100ms 连接获取上限探测，并在 shutdown 关闭读池、写连接、PG 和 Redis。
6. 单测覆盖读取、写拒绝、多语句拒绝、池超时、kill switch 和 MVCC 已提交快照。

## 阶段二：任务运行态迁 PostgreSQL

1. PG 新增四张运行表和 `storage_migration`，JSON 字段用 JSONB，时间字段用 TIMESTAMPTZ；补状态约束、查询索引和非空 `trigger_event_id` 唯一索引。
2. 增加兼容客户端，将历史服务的 `?` 占位符转换为 psycopg 占位符；事务内复用同一连接，JSON 对象参数安全包装为 JSONB，naive 时间按 Asia/Shanghai 解释。
3. `AsyncTaskService` 拆分 runtime 与 market 两个客户端：任务/日志读写 PG，行情、质量问题和天梯快照仍读写 DuckDB。
4. 创建/续跑在 PG advisory transaction lock 内完成槽位判断和状态写入；终态与依赖事件同事务。
5. `ScheduledJobService` 使用运行态客户端；PG 事件通过 `FOR UPDATE SKIP LOCKED` 批量认领，忙时恢复 waiting，异常进入 failed。
6. 天梯协调器改为从 runtime client 查任务，用 market client 恢复 DuckDB 快照状态；保持服务层关联，不做跨库 JOIN。

## 迁移与回退

1. `task-runtime-storage status` 只读检查 marker 和两端数量。
2. `task-runtime-storage migrate` 默认 dry-run：校验无活动任务、无孤儿日志、全部 JSON 合法、PG 目标为空。
3. `migrate --apply` 在单 PG 事务内按调度→任务→日志→事件顺序复制，DuckDB naive 时间按上海时区转 UTC，最后写 marker；失败全部回滚。
4. 切换后不双写，DuckDB 旧表冻结保留。
5. `rollback --confirm-marker migration.task_runtime_pg_v1` 在停服态将 PG 全量事实原子写回 DuckDB，更新序列，再于 PG 单事务清空运行表并把 marker 改为 rolled_back；可据此重新执行正向迁移。

## 验证顺序

1. 记录后台原运行状态和 `/api/health` 活动任务数。
2. 安全停服，执行 dry-run，核对源/目标数量。
3. 执行正向迁移并核对四表数量、JSONB、TIMESTAMPTZ、日志等级。
4. 跑存储、任务、调度、天梯、健康检查聚焦测试，再跑后端全量测试。
5. 启动服务，验证 PG runtime、读池指标、任务列表/调度列表和天梯状态读取。
6. 做第三方视角自审：检查所有运行态引用、旧事实文档、错误回滚、停服守卫、敏感信息和无关改动。

## 实施记录

- 2026-09-09：首次 dry-run 得到 DuckDB `async_task=1105`、`task_log=65006`、`scheduled_job=15`、`scheduled_trigger_event=165`，PG 目标均为 0。
- 首次 apply 遇到 15 条历史 `warning` 等级日志，被新约束拒绝；事务完整回滚，四表和 marker 仍为 0。补充历史兼容约束后重跑成功，四表数量逐项一致，JSONB/TIMESTAMPTZ 类型核对通过。
- 自审补齐只读池临时视图的同连接固定、按请求日期补走势快照、单股默认最新日不隐式补算、项目托管 market client 与测试内存 runtime 隔离、JSONB 显式类型绑定、PG 事件停用收敛、迁移标记不可读 fail-closed，以及回退后可再次迁移的 PG 清空闭环。
- 全仓运行态引用复核进一步修正两处旁路：数据质量复位改为从 runtime client 判断绑定任务状态；关联板块 E2E 夹具拆分 market/runtime client，生产夹具的任务、日志和调度数据只写已校验的 PG，并验证专属命名空间写入后可零残留清理。
- 验证结果：相关聚焦回归 `227 passed`，最终后端整仓 `1368 passed`；新增存储文件 Ruff、Python 编译和 `git diff --check` 通过。迁移后 dev 服务恢复，`/api/health=200`，`task_runtime_backend=postgres`，读池 `size=4/idle=4/timeouts=0`，活跃任务为 0；24 个并发健康请求全部 200。
