# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 始终用**简体中文**与用户交互。本文件是给后续 Claude 实例的速查，详尽说明见 [README.md](README.md) 与 [`agent-works/architecture/`](agent-works/architecture/) 下各模块技术文档。

## 项目概述

「复盘啦」——**EOD（收盘后）** 的 A 股趋势龙头研究系统，正从本地单用户向**公网多租户 SaaS** 演进。全栈：FastAPI 提供 REST 接口并在生产期托管前端构建产物（`frontend/dist`）。

**持久层已改为混合架构（阶段一已落地，见 [agent-works/multi-tenant-rbac/](agent-works/multi-tenant-rbac/)）**：
- **行情/参考数据**（全市场近 5 年只读 reference）留**嵌入式 DuckDB 单文件**（`data/ai_stocks.duckdb`），分析查询的列存底座。
- **用户私有资产**（方案/分组/回测/训练/评分快照/布局偏好等）+ **平台配置/权限元数据**落 **PostgreSQL**（并发写、多实例、按 `tenant_id`+`owner_user_id` 隔离）。
- **Redis** 作短状态库（限流/验证码/token 黑名单/权限版本号，阶段二起消费）。

> 认证与 RBAC（登录/角色/菜单/租户管理）属**阶段二/三**，尚未建设；当前所有资产归属默认 `default` 租户 / `admin` 用户。

数据源为公开免费接口（AKShare / baostock），覆盖近 5 年、主板 / 创业板 / 科创板（不含北交所）。

## 版本要求

环境与依赖**有最低版本约束**，改依赖或排查环境问题时以此为准（完整清单见 [requirements.txt](requirements.txt) / [pyproject.toml](pyproject.toml) / [frontend/package.json](frontend/package.json)）：

- **Python `>=3.11`**（本机 3.12）；`ruff` target 为 `py311`，新语法不要超过 3.11。
- **后端核心**：FastAPI `>=0.110`、uvicorn[standard] `>=0.29`、watchfiles `>=0.21`（`serve --reload` 依赖，须显式安装）、pydantic `>=2.6`（v2，**禁用 v1 写法**）、pydantic-settings `>=2.2`、DuckDB `>=0.10`、pandas `>=2.2`、numpy `>=1.26`、akshare `>=1.13`、baostock `>=0.8.8`、APScheduler `>=3.10`。
- **持久层中间件**（混合持久层 stage1 起）：**PostgreSQL `>=14`**（资产/权限/审计/字典库）、**Redis `>=6`**（短状态库）；驱动 `psycopg[binary,pool] >=3.1`（**同步**，匹配现有线程池模型，禁 async 化）、`redis >=5.0`。连接走 `config/settings.yaml` 的 `postgres`/`redis` 段，**密码走环境变量**（`AI_STOCKS_PG_PASSWORD` / `AI_STOCKS_PG_DSN` / `AI_STOCKS_REDIS_URL`），不入库不入码。
- **Node**：Vite `^5` 要求 Node `^18.0.0 || >=20.0.0`（建议 20 LTS）；`package.json` 未声明 `engines`/`.nvmrc`，但低于此版本 `vue-tsc`/`vite build` 会失败。
- **前端**：Vite `^5`、Vue `^3.4`、TypeScript `^5.4`、Element Plus `^2.7`、ECharts `^5.5`、Pinia `^2.1`、vue-router `^4.3`、vue-tsc `^2`、axios `^1.7`。`package.json` 标注 `"type": "module"`（ESM）。
- **测试 / Lint**：pytest `>=8.0`、ruff `>=0.4`（line-length 100）。

## 常用命令

**前置：PostgreSQL 与 Redis 须先运行**（后端启动期 `_check_storages` 三库连通性自检，任一不通即启动失败）。本机开发用 Homebrew：`brew services start postgresql@16 redis`；PG 库/角色 `ai_stocks`（localhost `trust` 免密；公网部署改 pg_hba 走密码 + 设 `AI_STOCKS_PG_PASSWORD`）。

服务起停一律走脚本，**禁止裸 `nohup` 或写 `/tmp`**：

```bash
./start.sh                 # 后端 dev，127.0.0.1:8000 热重载（默认）
./start.sh prod            # 后端绑 0.0.0.0:8000 托管 frontend/dist
./start.sh stop|restart|status|logs
./start-web.sh             # 前端 5173，Vite HMR（首次自动 npm install）

# 测试（先停掉占用 DuckDB 的服务，否则单文件被锁）
python -m pytest backend/tests/ -q
python -m pytest backend/tests/test_xxx.py::test_name -q   # 单测

cd frontend && npm run build && cd ..   # 生产产物进 frontend/dist（vue-tsc 类型检查 + vite build）

# 数据准备（首次按序，依赖不可反）
python -m backend.cli backfill              # 全市场近 5 年日线回填（断点续跑）
python -m backend.cli delisted --enrich     # 退市股历史 + 上市/退市日（防幸存者）
python -m backend.cli valuation             # 总市值 / 总股本（--fill-gaps 回补缺口）
python -m backend.cli rebuild-price-factors # 重建清洗复权因子 / pre_close / 涨跌停（不联网）
python -m backend.cli verify-data           # 只读体检 PASS/FAIL
python -m backend.cli daily                 # 一键日常：增量更新→质检→（可选）体检

# 多租户混合持久层（stage1）
python -m backend.cli migrate-rbac          # 存量资产 DuckDB→PG 一次性迁移：默认 dry-run 预演
python -m backend.cli migrate-rbac --apply  # 实迁（先停占用 DuckDB 的服务；DuckDB 原表保留兜底）
python -m backend.cli migrate-rbac --recreate --apply  # 旧单主键 schema 升级：DROP+重建资产表(复合主键)再迁
```

CLI 入口为 [backend/cli.py](backend/cli.py)，FastAPI 装配在 [backend/main.py](backend/main.py)。

### 端口约定（重要）

- 日常开发：前端 **5173**（唯一对外入口），后端 **8000** 仅本机，由 Vite 代理 `/api` 回 `127.0.0.1:8000`。
- 开发期改前端**不要** `npm run build`（那是无 HMR 的生产产物）；但**每次修改 `frontend/src` 后需 `npm run build`** 以保证生产产物同步。
- 自动化验证（AI 截图/交互核查）走**专用端口 5181**（`.claude/launch.json` 配置的 preview），**禁止抢占用户日常的 5173**。

## 架构与分层

请求路径：浏览器(Vue3 SPA) → REST `/api/**` → FastAPI 路由(`backend/api/`，薄层) → 编排层(`backend/services/`) + 领域引擎 → `storage` 仓库层 → 行情 DuckDB + 资产 PostgreSQL（+ Redis 短状态）。

**双库访问层（混合持久层 stage1）**——`storage/` 下分工：
- 行情只读：`duckdb_client.py` + `repository.py`（`MarketRepository`，占位符 `?`）。
- 资产读写：`pg_client.py`（psycopg3 同步连接池，占位符 `%s`）+ `asset_repository.py`（通用批量 upsert，自动注 `tenant_id`/`owner_user_id`）+ 各域仓库（`screening/profile.py`、`scoring/`、`signals/`、`backtest_service.py`、`training_service.py`、`stock_group.py`、`layout_config.py` 用户层、`app_config.py`）。
- 短状态：`redis_client.py`。
- 建表：DuckDB 走 `ddl.py::init_db`；PG 走 `pg_ddl.py::init_pg_db`（启动期幂等执行 + seed 默认租户/管理员）。
- **铁律：禁跨库 JOIN**。需行情+资产联合时，先各取再按 code 内存合并（结果集保持 top-N/单日小集合，如榜单 = PG 评分 ⊕ DuckDB 名称）。
- 各资产仓库构造**第一位参仍为 market(DuckDB) client**（兼容历史 `Repo(c)` 调用），PG client 内部经 `get_pg_client()` 获取。归属上下文 auth 未落地前默认 `default`/`admin`。

领域引擎（`backend/` 下各包）：
- `indicators/` 指标引擎——**唯一原子定义**，动态计算 + 单次运行内存缓存，不落预计算表。
- `screening/` 条件 AST + 表达式 DSL 沙箱 + 筛选引擎。
- `scoring/` 阈值打分 + 动态权重评分模型 + 评分快照。
- `signals/` 买卖信号（由买卖方案推导）。
- `backtest/` 前向收益 / 信号质量 / 撮合 Broker / 事件驱动引擎 / 绩效。
- `datasource/` 数据源适配（限流·重试·超时·兜底·溯源）；`dataquality/` 入库清洗 + 四层质检；`scheduler/` APScheduler 定时调度。

模块依赖链：数据管理→DuckDB(行情)→指标引擎←配置管理；指标引擎→筛选/榜单→回测；行情读经 `storage` 点时安全仓库(DuckDB)，用户资产读写经资产仓库(PG)。

## AI 协作约束（通用红线）

- **改代码前先同步**：准备改代码前，若距上次 `git pull` 超 2 小时，先 `git pull --rebase` 成功再改；冲突先解决再继续。
- **关键方案先确认**：涉及技术方案、交互设计或关键实现决策，先给推荐选项 + 理由让用户确认再开发；不确定的业务规则不写死，显式确认。
- **文档归档**：AI 生成文档默认进 `./agent-works/`；属于具体功能/需求时进 `./agent-works/{feature-slug}/`，同一功能的计划 / 留痕 / 核查 / SQL 复用同一目录；不在项目根目录散落 Markdown（除非用户明确指定）。
- **slug 命名**：小写 kebab-case 且表达业务含义；禁用 `feature`/`update`/`code-change` 等泛名；用过的 slug 沿用；中文业务名不稳定时先给建议 slug 等确认。
- **语言与会话命名**：除命令 / 代码 / 日志 / 原文外一律简体中文（见文首）；新会话首次回复后把会话名改为中文 `{业务名称-动作}`。
- **复用与克制**：新增 / 修改前先参考项目已有同类实现并优先复用；保持布局 / UI / 目录 / 命名 / 分层 / 返回结构 / 异常 / 日志 / 配置一致，偏离须说明原因；避免无必要的新依赖 / 新抽象 / 过度封装 / 硬编码。
- **注释**：优先用清晰命名与结构表意；复杂业务规则、状态流转、权限边界、兼容逻辑、性能取舍、异常兜底、外部系统约束必须注释；禁止复述代码的低价值注释。
- **性能与资源**：考虑数据量 / 调用频率 / 事务范围 / 查询复杂度 / 缓存 / 资源释放；避免 N+1、大对象一次性加载、重复远程调用、无限增长集合、阻塞式长任务、资源泄漏。
- **DDL/SQL 变更说明**：涉及 DuckDB 结构 / 初始化 / 迁移时，须写明文件路径、用途、执行时机、影响范围、回滚方式或不可回滚原因（默认路径 `./agent-works/{feature-slug}/{sql-purpose}.sql`）；不得只写"需要执行 SQL"。
- **前端变更**：涉及页面 / 组件 / 样式 / 布局 / 表格 / 列表 / 弹窗 / 抽屉时，以 [DESIGN.md](DESIGN.md) 和 [page-template.md](agent-works/configurable-layout-system/page-template.md) 为前端规范入口；计划必须说明是否触发页面设计闭环和维护矩阵。


## 开发契约（不可破坏）

修改功能前必读，细节见 [agent-works/architecture/platform.md](agent-works/architecture/platform.md)：

- **防未来函数**：指标/均线一律后向计算；选股只用 ≤T 数据，回测 T 日选股、**T+1 开盘成交**；平台突破用 `shift(1)`（AST 单测拦截 `shift(负)`）。
- **防幸存者偏差**：universe 点时构造，含"当时存活、后来退市"的票。
- **撮合不失真**：涨跌停价按板块 / ST 计算，开盘封死不可成交、停牌顺延、退市强平；计佣金 / 印花 / 过户 / 方向性滑点。
- **复权一致**：前向收益与回测记账统一**后复权(hfq)**，可成交性判定用**原始价**。源因子 `adj_factor` 用于 K 线前复权，`pre_close` 走独立清洗因子；复权查询统一走 `COALESCE(adj_factor_clean, adj_factor)`，清洗因子**不可写回** `adj_factor`。
- **base rate**：分层命中率必减同期全市场无条件命中率得超额，并附样本量。
- **统一基座**：技术指标是唯一原子定义，买卖/评分/筛选全部引用它组合，**不在下游硬编码字段**。
- **分层职责**：`api/` 只做参数校验与响应包装，业务逻辑放 `services/` 与领域引擎；行情读经点时安全仓库(DuckDB)、用户资产读写经资产仓库(PG)，**禁跨库 JOIN**（详见「架构与分层 · 双库访问层」）；长耗时操作走 `async_task` 异步任务底座 + 进度。
- **资产归属与隔离**：用户私有资产表（PG）一律带 `tenant_id`+`owner_user_id`，读写按归属过滤、写入自动注归属；行情等全市场只读 reference（DuckDB）不带归属、全局共享；**禁止前端传归属字段越权**（归属一律取自上下文/默认）。隔离落地三条铁律（stage1 三轮评审血泪，违反即跨租户串数据）：①**物理主键须复合** `(tenant_id, owner_user_id, 业务键)`，单 `id` 主键会被他人同 id 覆盖；`ON CONFLICT` 必须命中复合键。②**读侧每一个跨资产表 JOIN / 相关子查询都必须带** `AND a.tenant_id=b.tenant_id AND a.owner_user_id=b.owner_user_id`——只按业务 id 关联会产生跨 owner 笛卡尔串数据（只补写侧 PK 不够）。③删除/更新/`max(seq)` 等**每条**资产 SQL 都要带归属过滤，别依赖业务键“看起来唯一”。平台表（`indicator_def`/`app_config`/layout preset·page·policy/`sys_*`）用自然键、不带归属。`mark_stale_*`/`stats()` 等行情变更触发的全局失效是**有意不带归属**（影响所有租户）。
- **配置即时生效**：阈值/权重/参数集中在 [config/settings.yaml](config/settings.yaml)，Web 表单改的进 `app_config` 覆盖层（**平台级，已迁 PG**，`get_effective_settings` 合并）；**改参不写进代码**。
- **写库互斥仅限 DuckDB**：全市场采集/补数/修复/重算同一时间只能跑一个（DuckDB 单写进程，遇 409 说明已有写任务）；用户资产并发写在 PG，不受该互斥限制（这正是混合持久层的目的）。
