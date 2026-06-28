# 开发计划：阶段一 — 混合持久层与基础设施底座

> 上游需求：[../requirement.md](../requirement.md)（多租户多用户权限体系）第 12 章「建议开发顺序 · 阶段一」。
> 覆盖需求编号：**R1（混合持久层与基础设施）、R2（双库访问层）、R3（存量私有资产迁移）**。
> 本阶段是后续所有阶段的前置，且 R3 不可逆，须先稳。完成标准见末尾里程碑。

---

## 0. 本阶段技术决策（已定，低风险可推断；如不认可在开发前提出）

| 项 | 决策 | 理由 / 依据 |
| --- | --- | --- |
| PG 驱动 | **psycopg3（同步）+ 内置连接池 `psycopg_pool`** | 现有后端是同步栈（路由 `def`，跑 FastAPI 线程池，见 [backend/api/board.py](../../../backend/api/board.py)）；不引入 async 改造 |
| 数据访问风格 | **原生 SQL + 仓库类**，不引 ORM | 对齐现有 [backend/storage/repository.py](../../../backend/storage/repository.py) 与 `query_df` 模式（CLAUDE.md「复用与克制」） |
| Redis 客户端 | **redis-py（同步）+ 连接池** | 同步栈一致；本阶段仅建连接与健康自检，具体用途（限流/验证码/黑名单/perm_ver）在后续阶段消费 |
| `app_config` | **平台级配置迁 PG**；租户级配置（后续阶段）加 `tenant_id` | 多实例一致性 + 配置即时生效（CLAUDE.md「配置即时生效」） |
| 迁移归属落点 | 本阶段建 `sys_tenant`/`sys_user` **最小骨架**并 seed「默认租户 default + 平台管理员 admin」 | R3 迁移需要 `owner_user_id`/`tenant_id` 有真实落点；完整 RBAC/审计/字典表留各自阶段建 |
| 计算与 PG 关系 | **PG 不参与计算**：方案定义读一次、结果批量写；重计算仍在 DuckDB+pandas | 见需求文档 R2；计算热路径不碰 PG，性能不受影响 |
| 连接管理 | DuckDB 维持现状（按线程隔离、单写）；PG 用连接池；二者独立句柄 | 行情只读不参与写事务，无需跨库分布式事务 |

---

## 1. 阶段目标与范围

### 1.1 必须完成
- 引入 PostgreSQL（资产/权限/审计/字典库的物理底座）+ Redis（短状态库）+ 反向代理 HTTPS（部署文档与脚本）。
- 建立**双库访问层**：行情只读仓库（DuckDB，沿用）+ 资产读写仓库（PG，新建）+ `services/` 跨库编排约定。
- 将现存私有资产从 DuckDB **一次性迁移**到 PG 并补归属字段，归「默认租户 + 平台管理员」。
- 迁移后**回归验证**：回测/筛选/评分/榜单/盘感训练结果与迁移前一致。

### 1.2 本阶段不做（留后续阶段）
- 登录/JWT/鉴权中间件（阶段二）。
- 用户/角色/菜单/功能/租户的管理页面与完整 RBAC 表（阶段三）——本阶段只建 `sys_tenant`/`sys_user` 最小骨架供迁移落点。
- 日志审计、数据字典、配置管理拆页（阶段五）。
- 接口级/按钮级权限与前端登录态（阶段二/三/四）。

### 1.3 范围边界提醒
- 行情/参考数据（`stock_basic`/`daily_bar`/`daily_metrics`/`index_bar`/`trade_calendar`/`stock_suspension`/`data_*`/`indicator_def`）**留 DuckDB，不迁、不加归属**。
- 本阶段对外接口**行为不变**（尚未接鉴权），仅底层数据落点切换；用户感知应为"功能照旧"。

---

## 2. 架构设计

### 2.1 双库职责
```
┌─────────────── 计算/编排层 services/ + 领域引擎 ───────────────┐
│  读方案定义(PG,极小) → 重计算(DuckDB行情,pandas) → 批量写结果(PG) │
└───────────────────────────────────────────────────────────────┘
        │ 只读·大扫描                         │ 读写·小集合·并发
        ▼                                     ▼
  ┌──────────────┐                    ┌──────────────────┐
  │ DuckDB(行情)  │                    │ PostgreSQL(资产)  │
  │ 全局只读共享   │                    │ tenant+owner 隔离 │
  └──────────────┘                    └──────────────────┘
                                              ▲
                                        ┌─────┴─────┐
                                        │  Redis     │ 短状态(后续阶段消费)
                                        └───────────┘
```

### 2.2 目录与文件规划（新增/改动）
| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `backend/storage/pg_client.py` | 新增 | psycopg3 连接池封装，提供 `execute/query_df/transaction`，镜像 [duckdb_client.py](../../../backend/storage/duckdb_client.py) 风格 |
| `backend/storage/redis_client.py` | 新增 | redis-py 连接池封装 + 健康检查 |
| `backend/storage/pg_ddl.py` | 新增 | PG 建表：资产表（迁移目标）+ `sys_tenant`/`sys_user` 最小骨架；幂等 `CREATE TABLE IF NOT EXISTS` |
| `backend/storage/asset_repository.py` | 新增 | 资产读写仓库（PG）：方案/分组/回测结果/训练/布局/平台配置等 |
| `backend/storage/repository.py` | 保留 | `MarketRepository` 继续指向 DuckDB 行情，不动 |
| `backend/screening/profile.py` 等 | 改动 | 方案读写从 `self.c.query_df`（DuckDB）切到资产仓库（PG） |
| `backend/services/*` | 改动 | 跨库编排：先取方案(PG)→算(DuckDB)→写结果(PG)；禁跨库 JOIN |
| `config/settings.yaml` | 改动 | 新增 `postgres`/`redis` 段；连接串/密码走环境变量，不入库不入码 |
| `backend/config/*` | 改动 | settings 增加 PG/Redis 读取与默认值 |
| `requirements.txt` / `pyproject.toml` | 改动 | 新增 `psycopg[binary,pool]`、`redis` 及版本约束 |
| `backend/cli.py` | 改动 | 新增迁移命令 `migrate-rbac`（见 §4） |
| `agent-works/multi-tenant-rbac/stage1-foundation/migrate-assets-to-pg.sql` | 新增 | 迁移/回滚 SQL（按 CLAUDE.md DDL 红线归档） |
| `start.sh` / 部署文档 | 改动 | 反代 HTTPS、PG/Redis 依赖说明、启动自检 |
| `backend/tests/test_pg_client.py`、`test_dual_store.py`、`test_migrate_rbac.py` | 新增 | 连接、双库读写、迁移一致性测试 |

### 2.3 连接与并发
- DuckDB：维持现状（线程隔离 + 单写），仅用于行情只读 + 平台后台采集。
- PG：连接池（min/max 可配），FastAPI 同步端点在线程池中各取连接；写用事务。
- 启动自检：三类存储任一不通 → 明确启动错误（行情 DuckDB、PG 必需；Redis 必需）。

---

## 3. 任务分解（WBS）

> 顺序：T1（基础设施）→ T2（双库层）→ T3（迁移）→ T4（回归与文档）。每个任务给出验收点。

### T1 基础设施底座（R1）
- **T1.1** 依赖与配置：加 psycopg3/redis 依赖；`settings.yaml` 增 `postgres`/`redis` 段；连接串走环境变量。
  - 验收：缺环境变量时启动报清晰错误，不暴露密钥。
- **T1.2** `pg_client.py`：连接池 + `execute/query_df(返回 DataFrame)/transaction(上下文)` + 异常映射 `StorageError`。
  - 验收：单测建表/插入/查询/事务回滚通过。
- **T1.3** `redis_client.py`：连接池 + `ping` 健康检查（本阶段不接业务）。
  - 验收：`ping` 通；连接失败抛明确异常。
- **T1.4** 启动自检：`main.py`/`cli.py` 启动时校验 DuckDB+PG+Redis 连通性。
  - 验收：任一不通启动失败并打印诊断。
- **T1.5** 反代与部署：`start.sh`/部署文档补 HTTPS 终结、PG/Redis 起停说明。
  - 验收：部署文档可照做拉起完整链路。

### T2 双库访问层（R2）
- **T2.1** `pg_ddl.py`：建资产表（与迁移对象一一对应，加 `tenant_id`/`owner_user_id` + `(tenant_id, owner_user_id)` 索引）+ `sys_tenant`/`sys_user` 最小骨架。
  - 验收：幂等执行；表结构与需求文档 §6.1/§6.2 一致。
- **T2.2** `asset_repository.py`：实现方案/分组/回测结果/训练/布局/平台配置的 CRUD（PG），方法签名带归属参数（本阶段默认 default 租户/admin）。
  - 验收：单测 CRUD 通过；写入自动带归属。
- **T2.3** 改造领域读写引用点：`screening/profile.py`、score/trade profile、`stock_group`、`backtest` 结果落库、`training_service`、`layout_config` 由 DuckDB 切 PG。
  - 验收：各模块读写指向 PG，行情读仍走 DuckDB。
- **T2.4** `services/` 跨库编排约定：先取方案(PG)→算(DuckDB)→批量写结果(PG)；显式禁止跨库 JOIN，结果展示用内存 merge（top-N）。
  - 验收：榜单/回测展示走"PG 结果 + 内存 merge DuckDB 行情名"，无跨库 JOIN。
- **T2.5** 结果批量写：回测/评分结果用批量插入/COPY，非逐行。
  - 验收：大结果集写入性能可接受（基准对比）。

### T3 存量数据迁移（R3，不可逆）
- **T3.1** seed：建默认租户 `default` + 平台管理员 `admin`（最小行），作为归属落点。
- **T3.2** 迁移命令 `python -m backend.cli migrate-rbac`：DuckDB→PG，逐表读出补 `tenant_id=default`/`owner_user_id=admin` 写入；`layout_user_config.user_id="local"`→admin。
  - 迁移对象：见需求文档 §6.2（profiles 及版本表、分组、回测全套、screen/score_result、score_snapshot*、training*、layout_user_config、app_config 平台级）。
- **T3.3** dry-run 模式：先校验源行数、字段映射、外键完整性，输出报告但不写。
  - 验收：dry-run 报告列出每表预计迁移行数与潜在问题。
- **T3.4** 正式迁移 + 校验：迁移后逐表比对行数、外键、归属非空。
  - 验收：行数一致、外键完整、归属字段全非空。
- **T3.5** 回滚预案：DuckDB 原表**保留为只读副本不删**（迁移成功并回归通过后，单独决定何时停用）；PG 侧可清空重导。
  - 验收：回滚步骤文档化；不可逆点（上线后用户在 PG 产生新数据）明确标注。

### T4 回归与文档
- **T4.1** 回归测试：回测/筛选/评分/榜单/盘感训练在迁移后输出与迁移前**逐项一致**（同参数同输出）。
  - 验收：回归对比脚本全绿；【风险】重点防双库改造引入的结果偏差。
- **T4.2** 性能基准：典型回测/筛选/榜单计算耗时与迁移前对比，确认计算性能无显著退化。
  - 验收：计算耗时基本持平（PG 仅承担方案读 + 结果写）。
- **T4.3** 文档治理：改写 [CLAUDE.md](../../../CLAUDE.md)（删「无外部数据库/中间件依赖」、补 PG+Redis+反代与双库约束）、[README.md](../../../README.md)、`agent-works/architecture/`、版本约束清单。
  - 验收：后续 AI 按新契约可正确理解持久层。

---

## 4. 数据迁移方案（R3 细化，CLAUDE.md DDL 红线）

- **脚本路径**：`agent-works/multi-tenant-rbac/stage1-foundation/migrate-assets-to-pg.sql`（DDL/校验/回滚）+ `backend/cli.py::migrate-rbac`（编排，DuckDB 读 + PG 写）。
- **用途**：把 DuckDB 私有资产迁 PG 并补归属。
- **执行时机**：T2 完成、PG 资产表建好后，上线前一次性执行；先 dry-run 再正式。
- **影响范围**：仅私有资产表；行情表不动。
- **回滚方式**：DuckDB 原表保留只读副本；PG 可清空重导。**不可逆点**：上线后用户在 PG 写入新数据即无法简单回退。
- **归属规则**：全部 `tenant_id=default`、`owner_user_id=admin`；`layout_user_config.user_id="local"`→admin。
- **写库互斥**：迁移期视为写任务，遵守全局互斥，期间停止其他写任务/采集。

---

## 5. 风险与应对

| 风险 | 等级 | 应对 |
| --- | --- | --- |
| 双库改造导致选股/回测结果偏差 | 高 | T4.1 迁移前后逐项回归对比，作为放行硬门槛 |
| 跨库误用（JOIN/N+1） | 中 | T2.4 编排约定 + 评审；结果展示内存 merge 小集合 |
| 迁移不可逆 | 高 | dry-run + 校验 + DuckDB 原表保留；不可逆点文档化 |
| 同步栈下 PG 连接池配置不当 | 中 | 池大小可配 + 压测；线程池并发与池大小匹配 |
| 密钥泄露 | 中 | 连接串/密码走环境变量，不入库不入码不入日志 |
| 文档未同步致后续按旧契约开发 | 中 | T4.3 作为阶段交付物之一 |

---

## 6. 里程碑与验收

**阶段一完成 = 同时满足：**
1. PG/Redis/反代接入可用，启动自检通过（R1）。
2. 双库访问层建成：方案/结果走 PG，行情走 DuckDB，无跨库 JOIN（R2）。
3. 存量资产迁移完成，行数/外键/归属完整（R3）。
4. **回测/筛选/评分/榜单/盘感训练迁移后结果与迁移前一致**（核心放行门槛）。
5. 计算性能无显著退化（基准对比持平）。
6. CLAUDE.md/README/architecture/部署脚本同步更新。

达成后进入阶段二（认证与鉴权内核）。

---

## 7. 后续阶段衔接

- 本阶段建的 `sys_tenant`/`sys_user` 最小骨架，阶段三补全为完整用户/角色/租户管理（additive ALTER + 新表）。
- 本阶段 seed 的 default 租户/admin，阶段二登录后成为首个真实平台管理员账号。
- Redis 连接本阶段仅建底座，阶段二起承载限流/验证码/token 黑名单/perm_ver。
