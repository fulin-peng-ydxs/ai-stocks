# 存量资产迁移：DuckDB → PostgreSQL（stage1·T3）

> 跨库迁移（DuckDB 读 + PG 写），无法用纯 SQL 表达，实现为 Python 迁移器 + CLI 命令。
> 本文档履行 CLAUDE.md「DDL/迁移变更说明」：文件路径、用途、执行时机、影响范围、回滚方式、不可逆原因。

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
每个归属表：先 `DELETE WHERE tenant_id='default'`（清掉历史迁移/测试残留），再整表载入 → 与 DuckDB 精确镜像。完成后自动核对「PG default 租户行数 == DuckDB 源行数」。

## 影响范围
- 仅写 PG 资产表；DuckDB 不改。
- 测试归属（tenant `pytest`）不受影响（迁移只动 `default` 租户）。

## 回滚方式
- DuckDB 原表**完整保留**（迁移只读不删），可作只读副本兜底。
- PG 侧可 `DELETE WHERE tenant_id='default'` 清空后重新 `--apply`。
- **不可逆点**：上线后用户在 PG 产生新数据（新建方案/回测/训练等）后，无法再简单回退到迁移前状态。

## 本次执行结果（dev 环境，2026-06-28）
源合计 ~6.98 万行，20 资产表迁移后行数**逐表精确一致**；app_config 源 0 行（清理冒烟残留后对齐）。重启后应用各域（方案/分组/回测/训练/榜单）实时可见，跨库榜单（PG 快照 + DuckDB 名称内存合并）验证通过。
