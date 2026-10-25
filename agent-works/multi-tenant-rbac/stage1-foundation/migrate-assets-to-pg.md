# 存量资产迁移：DuckDB → PostgreSQL（stage1·T3）

## 文档边界

本文维护旧版 DuckDB 私有资产迁入 PostgreSQL 的一次性升级操作、归属映射、校验与回滚限制；不适用于已有线上 PG 资产的日常同步或重建。当前双库与权限架构以 [平台架构](../../architecture/platform.md) 和 [RBAC 架构](../../architecture/system-rbac-tenant.md) 为准，环境与连接配置以 [环境配置架构](../../architecture/environment-configuration.md) 为准，迁移器行为以本文下方源码入口核对。

迁移器的表集合、覆盖语义或校验变化时同步本文及对应测试；执行前必须确认备份与目标库，因为 `--apply` 会删除目标表中 `default` 租户资产后重载。末节执行结果仅记录 2026-06-28 开发环境快照，不代表当前目标库已验证，也不构成再次执行授权。

## 文件
- 迁移器：[backend/services/migrate_rbac.py](../../../backend/services/migrate_rbac.py)
- 命令：`python -m backend.cli migrate-rbac`（默认 dry-run）/ `--apply`（实迁）
- 目标库结构：[backend/storage/pg_ddl.py](../../../backend/storage/pg_ddl.py)（`init_pg_db` 幂等建表）

## 用途
把 DuckDB 中现存的**用户私有资产**迁入 PostgreSQL，并补归属字段，全部归「默认租户 `default` + 平台管理员 `admin`」。行情/参考数据（stock_basic/daily_bar/index_bar/...）**不迁**，保留在 DuckDB。

## 执行时机
T2 双库改造完成、PG 资产表建好后，**上线前一次性执行**。务必先 dry-run 预演确认行数，再 `--apply`。执行期视为写任务，应停掉占用 DuckDB 的服务（`./start.sh stop`）。

## 迁移范围（20 资产表 + 平台配置）
screen_profile(+version) / score_profile(+version) / trade_profile(+version) / screen_result / score_result / stock_group(+member) / backtest_run/trade/equity/metrics / score_snapshot(+meta) / training_session/round/trade / layout_user_config；app_config（平台表）。

## 归属映射
- 通用：`tenant_id='default'`、`owner_user_id='admin'`。
- `training_session`：丢弃旧 `user_id` 预留列（PG 已无），归 admin。
- `layout_user_config`：`owner_user_id = 原 user_id`（user_id 即该层隔离键），`tenant_id='default'`。
- `app_config`：平台表无归属，`ON CONFLICT DO NOTHING` 载入（不清空、不覆盖）。

## 执行口径（幂等·可重跑）
每个归属表：先 `DELETE WHERE tenant_id='default'`（清掉历史迁移/测试残留），再整表载入 → 与 DuckDB 精确镜像。

**校验（可复跑，T3/T4）**：
- dry-run：逐表「源列经归属变换后 ⊆ PG 目标列」字段映射校验 + 归属列齐备，不写；有问题不放行。
- apply：用实际写入行数(rowcount)统计，迁后三重核对——**字段映射 / PG default 租户行数 == DuckDB 源行数 / 归属列非空**，任一不符 CLI 退出码非 0。
- 隔离物理底座：PG 归属表为**复合主键 `(tenant_id, owner_user_id, <业务键>)`**，不同 owner 同业务 id 不互相覆盖（回归用例 `test_*_same_id_different_owner_no_clobber` 守护）。

## 影响范围
- 仅写 PG 资产表；DuckDB 不改。
- 测试归属（tenant `pytest`）不受影响（迁移只动 `default` 租户）。

## 回滚方式
- DuckDB 原表**完整保留**（迁移只读不删），可作只读副本兜底。
- PG 侧可 `DELETE WHERE tenant_id='default'` 清空后重新 `--apply`。
- **不可逆点**：上线后用户在 PG 产生新数据（新建方案/回测/训练等）后，无法再简单回退到迁移前状态。

## 本次执行结果（dev 环境，2026-06-28）
源合计 ~6.98 万行，20 资产表迁移后**字段映射通过 / 行数逐表精确一致 / 归属列无空值**；app_config 平台表走合并语义、按 UI 后置可改不按行数判错。重启后应用各域（方案/分组/回测/训练/榜单）实时可见，跨库榜单（PG 快照 + DuckDB 名称内存合并）验证通过。

**T4 回归口径**：①迁移一致性 = 上述 migrate-rbac 三重核对（可复跑）。②「迁移前后结果一致」= 行情计算底座（DuckDB + pandas）**完全未变**、方案/快照为精确行级镜像，故选股/回测/榜单输入不变、输出一致；榜单实测读出迁移后真实数据。③性能：重计算仍在 DuckDB，PG 仅承担方案读 + 结果写，计算热路径无新增 I/O，未单独压测（无显著退化预期）。
