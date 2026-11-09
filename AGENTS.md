# Repository Guidelines

## 文档职责

- `AGENTS.md` 是本仓库 AI 协作与项目命令的权威入口；测试命令、验证选择和总维护清单统一维护在 [开发验证规范](agent-works/testing/guide.md)，README 只摘录使用路径所需命令。
- `CLAUDE.md` 只作为 Claude Code 薄入口，避免复制本文件内容；仓库事实以代码、`README.md`、`DESIGN.md` 和 `agent-works/architecture/` 为准。
- 页面开发使用 [DESIGN](DESIGN.md) 和 [页面模板](agent-works/configurable-layout-system/page-template.md)，布局与外观配置运行机制见 [前端布局实现](agent-works/architecture/frontend-layout.md)。
- 数据库实例、结构、初始化数据范围、升级与恢复及持续维护统一遵守 [数据库设计、初始化与演进](agent-works/architecture/database-lifecycle.md)，其他文档只维护导航或所属领域语义。
- 稳定执行约束变更更新本文件，领域实现变更更新对应事实文档，测试结果留在当次交付中。

## 项目概览

「复盘啦」是 EOD A 股趋势龙头研究系统，栈为 FastAPI + Vue 3 + DuckDB + PostgreSQL + Redis。行情/参考数据在 DuckDB 分析；用户资产、权限元数据、平台配置以及任务/日志/调度运行态在 PostgreSQL；Redis 存短状态、来源共享额度和已落库分时读取缓存。数据源为公开免费接口（AKShare / baostock），默认回填近 15 年主板、创业板、科创板，不含北交所。

## 代码结构

- 后端：`backend/api/` 放 REST 路由，`backend/services/` 放业务编排，`backend/storage/` 管理 DuckDB/PG/Redis 与 DDL，`backend/indicators/`、`screening/`、`scoring/`、`backtest/` 放领域逻辑，测试在 `backend/tests/`。
- 前端：`frontend/src/views/`、`components/`、`api/`、`layout/`、`stores/`。
- 配置与运行数据：`config/settings.yaml`、`data/`、`logs/`；环境变量、变量文件和数据库配置覆盖层见 `agent-works/architecture/environment-configuration.md`。
- 系统分层、存储及运行装配见 [系统架构](agent-works/architecture/system-architecture.md)，跨模块任务、调度和恢复见 [任务运行态](agent-works/architecture/task-runtime.md)；领域专题位于 `agent-works/architecture/`，前端设计规范为 `DESIGN.md`。

## 核心契约

- 防未来函数：指标和均线后向计算；选股只用 `<=T` 数据；回测 T 日选股、T+1 开盘成交；平台突破用 `shift(1)`。
- 防幸存者偏差：股票池按点时构造，包含当时存活但后来退市的股票；证券更码统一读取 `backend/market_identity.py` 的官方生效日，横截面排他纳入旧/新代码，连续图表与暖机不裁剪。
- 撮合口径：涨跌停价按板块/ST 计算，开盘封死不可成交，停牌顺延，退市强平，计佣金/印花/过户/方向性滑点。
- ST 口径：唯一事实为 `stock_st_status_daily` 的准确逐日记录；禁止按当前名称或 `daily_bar.is_st` 投影推断。采集发布、历史限幅及业务门禁统一消费 [ST 架构](agent-works/architecture/st-status.md)。
- 复权口径：前向收益与回测记账用后复权，成交性判定用原始价；复权查询统一 `COALESCE(adj_factor_clean, adj_factor)`，清洗因子不得写回 `adj_factor`。
- 股本与市值：展示、指标、筛选和回测统一读取逐日事实，禁止当前快照倒填历史；来源变更日期、计算优先级及跨源核验遵守 [个股采集](agent-works/architecture/stock-collection.md)，业务台账与来源提醒的分类遵守 [数据管理](agent-works/architecture/data-management.md)。
- 评分与验证：分层命中率必须扣同期全市场 base rate 并附样本量；技术指标是唯一原子定义，下游只组合引用，不硬编码字段。
- 双库边界：禁止跨库 JOIN。行情读 DuckDB，资产读写 PG；需要联合时在服务层分别取数后内存合并，并控制结果集规模。
- 数据库变更：新增或修改表、字段、约束、索引或 seed 必须按 [数据库接入流程](agent-works/architecture/database-lifecycle.md#接入扩展与变更影响) 同步新装 DDL、旧库升级、目录及初始化验收，合并前通过 `./start.sh database gate`；禁止手工建表或改写机器契约绕过迁移。
- 采集机制：个股 EOD 采集、日期收敛和十类安全方案见 `agent-works/architecture/stock-collection.md`；板块字典、成分、指数和资金流采集见 `agent-works/architecture/board-collection.md`。
- EOD 日期：个股、大盘指数、板块指数共用 `backend/services/eod_dates.py`；北京时间 15:30 前只写上一已收盘交易日及更早记录，收盘后仍须检查源端就绪。强制当日不能绕过收盘或休市边界；源响应不能越过请求区间。日常流程共享目标上界，续跑冻结实际日期与范围；资金流另受实时快照归属门禁约束，不能倒填任意历史日。
- 资产隔离：用户私有 PG 表必须带 `tenant_id + owner_user_id`；复合主键、`ON CONFLICT`、JOIN/子查询、UPDATE/DELETE/`max(seq)` 都必须带归属条件。归属取请求上下文，禁止信任前端传入。
- 鉴权边界：`AuthMiddleware` 默认 deny；白名单仅健康检查和认证接口。新增业务端点必须同步 `require_perm`/`require_system_perm`、`sys_resource` seed、SQL 留痕和路由扫描测试。
- 新页面接入：新增前端页面、系统页或可导航业务功能时，必须同步路由、菜单 seed、功能点 seed、后端守卫、按钮 `v-permission`、默认角色授权决策和租户归属；流程见 `agent-works/architecture/system-rbac-tenant.md`。
- 基础数据保护：初始化保留管理员可维护配置与人工授权，菜单覆盖和特殊迁移遵守 [初始化数据策略](agent-works/architecture/database-lifecycle.md#机制初始化数据范围与覆盖策略)，不以缺行、空授权或代码默认值变化推断覆盖授权。
- RBAC 口径：JWT 不携带角色/权限，权限以 PG 的用户/租户状态与 `perm_ver` 为准；授权变更与 `perm_ver` 自增必须同一 PG 事务提交。`layout:view`、`trade-calendar:view`、`indicator:registry` 是登录基线共享读，有角色的非 system 用户强制注入，无角色 fail-closed。
- 资产可见性：评分、筛选、买卖方案和回测记录支持 `private|tenant|public`；前端透传 opaque `profile_ref`/`run_ref`，榜单、筛选、回测和评分服务必须解析真实 owner；非 owner 公开资产只读，方案类资产可复制为自己的 private，公开回测只允许复用参数重跑。
- 长任务：采集、修复、重算等任务复用 [任务运行态](agent-works/architecture/task-runtime.md) 的创建、能力、日志、取消与恢复入口；DuckDB 写任务同一时间只允许一个，PG 资产写不受该互斥限制。
- 配置：环境变量、变量文件、YAML 基线和 `app_config` 覆盖层以 `agent-works/architecture/environment-configuration.md` 为准，不把临时研究参数写死进代码。

## 运行命令

服务起停一律走脚本；人工和 AI 不直接裸跑 `nohup`，不把临时日志写到 `/tmp`。

```bash
./start.sh                 # 后端 dev，127.0.0.1:8000 热重载
./start.sh prod            # 后端 prod，0.0.0.0:8000，托管 frontend/dist
./start.sh stop|restart|status|logs  # stop/restart 默认检查任务；确需中断时追加 --force
./start-web.sh             # 前端 5173，Vite HMR，首次自动 npm install
./start.sh database plan    # 实例预检（不写库）
./start.sh database check   # 目标库只读验收（须释放 DuckDB 文件锁）
./start.sh database gate    # 隔离数据库门禁（不访问业务库）

python -m backend.cli backfill
python -m backend.cli delisted --enrich
python -m backend.cli valuation
python -m backend.cli rebuild-price-factors
python -m backend.cli verify-data
python -m backend.cli verify-catalog
python -m backend.cli daily
```

CLI 入口是 `backend/cli.py`，FastAPI 装配在 `backend/main.py`。

旧库升级和存储回滚属于有前置条件的一次性维护，命令、数据影响及结果核对分别见 [用户资产迁移](agent-works/architecture/system-rbac-tenant.md#旧版用户资产的一次性迁移) 和 [任务运行态切换](agent-works/architecture/task-runtime.md#一次性升级与受控回滚)。这些操作不属于默认日常流程，单纯文档维护或 CLI 帮助校验不构成实际迁移授权，也不代表目标库已验证。

## 环境识别

- 调试前先执行 `./start.sh status`，再核对 `logs/backend-runtime.json` 的 `pid`、`mode` 与 `safeEnv.AI_STOCKS_ENV`（缺失时看 `safeEnv.ENV`）。只有 PID 与当前服务一致时，档案才代表该服务；缺失或不匹配时不能拿旧档案推断。`mode=dev|prod` 是启动方式，环境标记是调试工具守卫，两者不得混同。
- 本机环境身份持久化在 Git 忽略的 `.env.local`：用户已确认本地调试环境时设置 `AI_STOCKS_ENV=dev`，由 `start.sh` 统一加载；不依赖每次会话的 shell export，也不把“所有部署都是 dev”写成仓库默认。变量文件代表后续启动配置，已运行服务以有效运行档案为准；变更后通过脚本安全重启并确认健康状态。
- `dev-users --list` 提示环境 `<unset>` 时，先检查命令是否加载本机变量文件及其环境标记；用户已确认本地环境且无生产/共享目标冲突时，应补齐标记后重试，不能直接把参数缺失当作页面验收阻塞，也无需重复索要本地调试授权。真实环境不明或证据冲突时仍须停止调试写入并澄清。
- 完整配置语义与核查步骤见 `agent-works/architecture/environment-configuration.md`「环境身份与运行模式」。

## 测试用户

- 页面或接口权限验收需要固定调试账号时，先读 `agent-works/multi-tenant-rbac/test-users.md`，不要凭记忆猜账号、角色、权限或密码。
- `README.md` 里的 `admin` 是 `default` 租户平台系统管理员，密码来源和覆盖边界见 `agent-works/architecture/environment-configuration.md`；它只用于初始化、系统级运维和最高权限验收，不作为普通权限边界测试账号。
- 本地/测试库须明确设置 `AI_STOCKS_ENV=dev|test|local`，并通过 `./start.sh dev-users` 幂等创建或校准调试账号、`./start.sh dev-users --list` 查看当前账号；该入口与后端服务统一加载 `.env.local`，`--keep-password` 用于保留已有密码。E2E 自动写入口还必须传 `--expected-pg-fingerprint`，并在任何 DDL/账号写入前与被测后端常量时间比对。空值、未知环境、生产或共享公网环境一律禁止执行。
- `debug_*` 调试账号密码来源和生产禁用规则见 `agent-works/architecture/environment-configuration.md` 与 `agent-works/multi-tenant-rbac/test-users.md`；本地默认密码只允许用于开发测试，生产、共享公网或不确定环境禁止创建或使用这批账号。

## 开发访问

日常开发入口为前端 `5173`、后端 `8000`（仅本机），由 Vite 代理 `/api`，预览使用 HMR。

## 环境与版本

- Python `>=3.11`，本机常用 3.12；Ruff `line-length = 100`、`target-version = py311`。
- Node.js 建议 20 LTS；前端锁文件为 npm lockfile v3。
- 后端关键版本：FastAPI `>=0.110`、DuckDB `>=0.10`、PostgreSQL `>=14`、Redis `>=6`、pandas `>=2.2`、pytest `>=8.0`。
- 前端关键版本：Vue `^3.4`、Vite `^5.2`、TypeScript `^5.4`、Vitest `^1.6`、Element Plus `2.14.1`。
- 本地开发需先启动 PostgreSQL 与 Redis；生产/集成必须按 `agent-works/architecture/environment-configuration.md` 完成密钥、管理员初始密码和 PG/Redis 连接配置。

## 编码与测试

- 路由层保持薄封装，复杂业务放 `services/` 或领域模块；测试文件使用 `test_*.py`。
- 前端使用 Vue 3 Composition API + TypeScript，组件 PascalCase；API 封装在 `frontend/src/api/*.ts`，布局逻辑在 `frontend/src/layout/`。

## 协作与提交

- 除命令、代码、日志和原文外，面向用户输出使用简体中文。
- 改代码前先读同类实现并优先复用；偏离既有分层、命名、返回结构、异常、日志或配置方式时说明理由。
- 技术方案、交互设计或关键业务规则不确定时，先给推荐方案与理由让用户确认。
- 不在用户未要求时提交或推送；提交信息使用中文语义化风格，例如 `Agent 新增(基础功能): ...`。
- 不提交 `data/` 本地数据库、`logs/`、个人环境配置或密钥。`prod` 绑定 `0.0.0.0:8000`，公网部署必须配合反向代理、TLS、限流和运维访问控制。
