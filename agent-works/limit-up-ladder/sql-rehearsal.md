# 连板天梯 SQL 前向与回滚演练记录

## 演练结论

- 演练日期：2026-08-31。
- DuckDB：九张领域表前向脚本连续执行两次均成功，包含新增的快照窗口指标和失效 outbox；随后按逆依赖顺序删除，最终零残留。
- PostgreSQL：审计账本和 RBAC 前向脚本连续执行两次均成功且无重复数据；存在 pending outbox 时回滚按预期失败，投递完成后专项回滚成功。
- PG 回滚后两个 marker 均进入 `applied=false / rolled_back=true` tombstone，迁移创建的菜单、资源、授权、账本、outbox、共享审计索引与字段均按所有权记录清理。
- 演练使用临时 DuckDB 文件和随机隔离 PG schema；正常与异常路径结束后均已删除，不读写项目 `data/`，不修改共享菜单、权限、审计或业务数据。

## 演练范围

| 文件 | 数据库 | 验证内容 |
| --- | --- | --- |
| `limit-ladder-schema.sql` | DuckDB | 九表、约束、索引、重复前向、逆依赖删除 |
| `limit-ladder-audit-ledger.sql` | PostgreSQL | migration marker、对象所有权、两表、三个索引、共享审计兼容字段、重复前向 |
| `limit-ladder-rbac.sql` | PostgreSQL | 菜单、两个资源、默认角色授权、marker、`perm_ver` 失效、重复前向 |
| `rollback-limit-ladder.sql` | PostgreSQL | marker 校验、pending outbox 拦截、账本外引用保护、共享字段复用保护、正常回滚、tombstone |

## 执行环境与隔离方式

- DuckDB 使用 Python `tempfile.TemporaryDirectory` 创建独立文件，连接关闭后临时目录自动清理。
- PostgreSQL 复用本地配置连接，但只在 UUID 随机命名的独立 schema 中创建最小 RBAC/审计基线；所有 SQL 通过该 schema 的 `search_path` 执行。
- PostgreSQL 演练结束在 `finally` 中按已解析的随机 schema 精确执行 `DROP SCHEMA ... CASCADE`；未使用共享 `public` 对象。
- 本次没有执行文末可选的生产 DuckDB 数据删除操作；该操作仍要求停服、备份和人工确认永久撤销。

## 场景与结果

| 场景 | 预期 | 结果 |
| --- | --- | --- |
| DuckDB 前向执行两次 | 九表存在且无重复/报错 | 通过，9/9 |
| DuckDB 逆依赖删除 | 九表全部消失 | 通过，0 残留 |
| PG 审计前向执行两次 | marker、两表和索引幂等 | 通过 |
| PG RBAC 前向执行两次 | 1 个菜单、2 个资源、3 个 view 菜单授权、3 个 view 资源授权、1 个 recompute 授权 | 通过 |
| 管理员修改迁移创建的菜单身份后回滚 | 整体事务拒绝，不删除已修改节点 | 通过，命中严格身份保护 |
| pending outbox 回滚 | 事务失败且对象保留 | 通过，命中 fail-closed |
| outbox 投递后回滚 | 精确删除迁移自有对象并更新 marker | 通过 |
| 权限缓存失效 | system、tenant_admin、normal 用户 `perm_ver` 前向和回滚各自增一次 | 通过，最终均为 2 |
| 演练清理 | 临时文件与随机 schema 不残留 | 通过 |

## 演练中发现并修复的问题

原计划已经引用 `rollback-limit-ladder.sql`，但 T12 完成时文件尚未实际存在；同时原 `limit-ladder-audit-ledger.sql` 只有 `IF NOT EXISTS`，无法证明共享 `audit_log.source_event_key` 及其唯一索引是否由本迁移创建。若直接按注释删除，可能误删既有或后续复用的共享结构。

本阶段已完成以下修复：

- 新增专项回滚脚本，使用 RBAC 和审计两个 marker 作为唯一删除账本。
- 审计前向脚本新增独立 advisory lock，并记录共享列、索引和专用表的创建所有权。
- 回滚前检查 pending outbox、账本外角色授权、子菜单/额外资源和共享审计事件键；存在任一情况即整事务拒绝。
- 回滚只删除 marker 明确记录为本迁移创建的对象；预先存在的结构默认保留。
- 回滚角色授权后在同一事务中增加受影响用户的 `perm_ver`。

## 发布操作边界

1. 备份 PG 与 DuckDB，确认目标环境和 DuckDB 独占写条件。
2. 停止旧后端，依次执行 DuckDB schema、PG audit ledger、PG RBAC 三份前向 SQL。
3. 运行各脚本验证查询后发布后端与前端，重新登录刷新权限版本。
4. 回退代码时默认保留 DuckDB 快照/ST 历史；只有永久撤销并完成备份后才单独执行注释中的 DuckDB 删除段。
5. 执行 PG 专项回滚前必须在同一会话显式设置 `ai_stocks.confirm_menu_overwrite=CONFIRM_LIMIT_LADDER_ROLLBACK`，并先投递或导出 pending outbox；任何 fail-closed 异常均不得通过手工级联删除绕过。
