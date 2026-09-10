# Repository Guidelines

## 文档职责

- `AGENTS.md` 是本仓库 AI 协作的项目级入口，只保留当前有效、会影响执行的稳定规则。
- `CLAUDE.md` 只作为 Claude Code 薄入口，避免复制本文件内容；仓库事实以代码、`README.md`、`DESIGN.md` 和 `agent-works/architecture/` 为准。
- 功能需求、计划、开发留痕、业务核查和 SQL 归档放入 `agent-works/{feature-slug}/`；同一功能复用同一目录。
- 前端页面规范以 `DESIGN.md` 和 `agent-works/configurable-layout-system/page-template.md` 为入口，不在本文件重复细则。

## 项目概览

「复盘啦」是 EOD A 股趋势龙头研究系统，栈为 FastAPI + Vue 3 + DuckDB + PostgreSQL + Redis。行情/参考数据在 DuckDB 分析；用户资产、权限元数据、平台配置以及任务/日志/调度运行态在 PostgreSQL；Redis 存短状态。数据源为公开免费接口（AKShare / baostock），覆盖近 5 年主板、创业板、科创板，不含北交所。

## 代码结构

- 后端：`backend/api/` 放 REST 路由，`backend/services/` 放业务编排，`backend/storage/` 管理 DuckDB/PG/Redis 与 DDL，`backend/indicators/`、`screening/`、`scoring/`、`backtest/` 放领域逻辑，测试在 `backend/tests/`。
- 前端：`frontend/src/views/`、`components/`、`api/`、`layout/`、`stores/`。
- 配置与运行数据：`config/settings.yaml`、`data/`、`logs/`；环境变量、变量文件和数据库配置覆盖层见 `agent-works/architecture/environment-configuration.md`。
- 架构文档：`agent-works/architecture/`；前端设计规范：`DESIGN.md`。

## 核心契约

- 防未来函数：指标和均线后向计算；选股只用 `<=T` 数据；回测 T 日选股、T+1 开盘成交；平台突破用 `shift(1)`。
- 防幸存者偏差：股票池按点时构造，包含当时存活但后来退市的股票。
- 撮合口径：涨跌停价按板块/ST 计算，开盘封死不可成交，停牌顺延，退市强平，计佣金/印花/过户/方向性滑点。
- ST 口径：唯一事实为 `stock_st_status_daily` 的准确逐日记录；禁止按当前名称或 `daily_bar.is_st` 投影推断。主板 ST 2026-07-06 前 5%、当日起 10%，创业板/科创板 20%；完整链路见 `agent-works/architecture/st-status.md`。
- 复权口径：前向收益与回测记账用后复权，成交性判定用原始价；复权查询统一 `COALESCE(adj_factor_clean, adj_factor)`，清洗因子不得写回 `adj_factor`。
- 评分与验证：分层命中率必须扣同期全市场 base rate 并附样本量；技术指标是唯一原子定义，下游只组合引用，不硬编码字段。
- 双库边界：禁止跨库 JOIN。行情读 DuckDB，资产读写 PG；需要联合时在服务层分别取数后内存合并，并控制结果集规模。
- 数据表接入：新增或修改表必须同步对应 DDL、表级中文业务元数据、归属/来源/关系、显式鲜活度与质量策略以及字段中文名/说明；不适用策略也必须登记。合并前执行 `python -m backend.cli verify-catalog`，禁止手工建表绕过 DDL。完整流程见 `agent-works/architecture/data-management.md`。
- 资产隔离：用户私有 PG 表必须带 `tenant_id + owner_user_id`；复合主键、`ON CONFLICT`、JOIN/子查询、UPDATE/DELETE/`max(seq)` 都必须带归属条件。归属取请求上下文，禁止信任前端传入。
- 鉴权边界：`AuthMiddleware` 默认 deny；白名单仅健康检查和认证接口。新增业务端点必须同步 `require_perm`/`require_system_perm`、`sys_resource` seed、SQL 留痕和路由扫描测试。
- 新页面接入：新增前端页面、系统页或可导航业务功能时，必须同步路由、菜单 seed、功能点 seed、后端守卫、按钮 `v-permission`、默认角色授权决策和租户归属；流程见 `agent-works/architecture/system-rbac-tenant.md`。
- 菜单初始化：`sys_menu` / `sys_resource` 是运行时事实源；启动 seed、普通升级 SQL 和测试只允许补缺失行，禁止默认覆盖或删除现有父级、标题、类型、路由、图标、排序、可见性及功能点配置。确需覆盖时必须由系统管理员通过管理页面/API 显式操作并留 before/after 审计，或使用带独立 marker、确认口令和事务的专项迁移。
- RBAC 口径：JWT 不携带角色/权限，权限以 PG 的用户/租户状态与 `perm_ver` 为准；授权变更与 `perm_ver` 自增必须同一 PG 事务提交。`layout:view`、`trade-calendar:view`、`indicator:registry` 是登录基线共享读，有角色的非 system 用户强制注入，无角色 fail-closed。
- 资产可见性：评分、筛选、买卖方案和回测记录支持 `private|tenant|public`；前端透传 opaque `profile_ref`/`run_ref`，榜单、筛选、回测和评分服务必须解析真实 owner；非 owner 公开资产只读，方案类资产可复制为自己的 private，公开回测只允许复用参数重跑。
- 长任务：采集、修复、重算等写库任务走 `async_task`；DuckDB 写任务同一时间只允许一个，PG 资产写不受该互斥限制。
- 配置：环境变量、变量文件、YAML 基线和 `app_config` 覆盖层以 `agent-works/architecture/environment-configuration.md` 为准，不把临时研究参数写死进代码。

## 运行命令

服务起停一律走脚本；人工和 AI 不直接裸跑 `nohup`，不把临时日志写到 `/tmp`。

```bash
./start.sh                 # 后端 dev，127.0.0.1:8000 热重载
./start.sh prod            # 后端 prod，0.0.0.0:8000，托管 frontend/dist
./start.sh stop|restart|status|logs  # stop/restart 默认检查任务；确需中断时追加 --force
./start-web.sh             # 前端 5173，Vite HMR，首次自动 npm install

python -m pytest backend/tests/ -q
python -m pytest backend/tests/test_xxx.py::test_name -q

cd frontend && npm run build && cd ..

python -m backend.cli backfill
python -m backend.cli delisted --enrich
python -m backend.cli valuation
python -m backend.cli rebuild-price-factors
python -m backend.cli verify-data
python -m backend.cli verify-catalog
python -m backend.cli daily
python -m backend.cli task-runtime-storage status|migrate
```

CLI 入口是 `backend/cli.py`，FastAPI 装配在 `backend/main.py`。

跑后端测试前先判断是否会访问项目`data/ai_stocks.duckdb`：
只要测试会启动 FastAPI、触发 DuckDB 初始化、访问行情/数据管理/布局接口、异步任务、数据采集、质检、回测或任何可能拿 DuckDB 文件锁的链路，就必须先执行 `./start.sh status` 确认后台状态，再用`./start.sh stop` 停掉后端；

测试通过或结束后，按测试前状态用 `./start.sh` 重启，并用
`./start.sh status` 确认 `/api/health=200`。禁止在后台服务仍持有 DuckDB 锁时硬跑相关测试；不得直接裸杀进程，除非脚本停服失败且用户明确同意。

## 测试用户

- 页面或接口权限验收需要固定调试账号时，先读 `agent-works/multi-tenant-rbac/test-users.md`，不要凭记忆猜账号、角色、权限或密码。
- `README.md` 里的 `admin` 是 `default` 租户平台系统管理员，密码来源和覆盖边界见 `agent-works/architecture/environment-configuration.md`；它只用于初始化、系统级运维和最高权限验收，不作为普通权限边界测试账号。
- 本地/测试库须明确设置 `AI_STOCKS_ENV=dev|test|local`，并通过 `./start.sh dev-users` 幂等创建或校准调试账号、`./start.sh dev-users --list` 查看当前账号；该入口与后端服务统一加载 `.env.local`，`--keep-password` 用于保留已有密码。E2E 自动写入口还必须传 `--expected-pg-fingerprint`，并在任何 DDL/账号写入前与被测后端常量时间比对。空值、未知环境、生产或共享公网环境一律禁止执行。
- `debug_*` 调试账号密码来源和生产禁用规则见 `agent-works/architecture/environment-configuration.md` 与 `agent-works/multi-tenant-rbac/test-users.md`；本地默认密码只允许用于开发测试，生产、共享公网或不确定环境禁止创建或使用这批账号。
- 页面和接口测试按场景选择最小权限账号验证，不要默认用系统管理员账号覆盖权限态、空权限态或 fail-closed 场景。
- pytest 继续使用用例内临时用户，不依赖固定调试账号。
- 涉及平台级菜单、功能点、角色授权或 `app_config` 的 pytest 必须使用随机临时身份并精确清理，禁止删除、重建或改写真实内置菜单/功能点；无法命名空间隔离时必须使用独立测试库，不得用写死默认值“恢复”共享开发库。

## 端口与构建

- 日常开发入口：前端 `5173`，后端 `8000` 仅本机，由 Vite 代理 `/api`。
- 自动化截图/交互验证用专用端口 `5181`，禁止抢占用户日常的 `5173`。
- 前端开发预览使用 HMR，不用 `npm run build` 代替开发服务器。只有构建配置、依赖、路由或懒加载、全局资源、生产产物受影响，执行发布门禁，或用户明确要求时才运行 `npm run build`；普通文案、局部模板、组件逻辑和样式改动按风险运行定向测试或临时页面复核。源码未再次变化时不得重复构建。
- Playwright E2E 不是页面改动的默认验收手段，也不能证明计算规则、数据口径、任务重试或后端异常闭环正确；这些必须先由领域/服务/API 测试和代表性真实入口验证。只有满足 `agent-works/e2e-automation/guide.md` 全部准入条件的浏览器独有关键链路才新增或执行 E2E；普通改动禁止默认跑模块整组、全量或多视口。Playwright 固定使用 `5181`，后端由 `./start.sh` 管理；首次缺少浏览器时执行 `cd frontend && npm run test:e2e:install`。
- 临时复核、探索排查、截图、视觉确认和普通点击验证默认使用 AI 内置浏览器。用户未明确指定时，禁止连接其个人 Chrome、Edge 或其他外部浏览器；内置浏览器不可用时先说明，不自动切换。具体准入、选择器和命令见 `agent-works/e2e-automation/guide.md`。

## 环境与版本

- Python `>=3.11`，本机常用 3.12；Ruff `line-length = 100`、`target-version = py311`。
- Node.js 建议 20 LTS；前端锁文件为 npm lockfile v3。
- 后端关键版本：FastAPI `>=0.110`、DuckDB `>=0.10`、PostgreSQL `>=14`、Redis `>=6`、pandas `>=2.2`、pytest `>=8.0`。
- 前端关键版本：Vue `^3.4`、Vite `^5.2`、TypeScript `^5.4`、Vitest `^1.6`、Element Plus `^2.7`。
- 本地开发需先启动 PostgreSQL 与 Redis；生产/集成必须按 `agent-works/architecture/environment-configuration.md` 完成密钥、管理员初始密码和 PG/Redis 连接配置。

## 编码与测试

- 路由层保持薄封装，复杂业务放 `services/` 或领域模块；测试文件使用 `test_*.py`。
- 前端使用 Vue 3 Composition API + TypeScript，组件 PascalCase；API 封装在 `frontend/src/api/*.ts`，布局逻辑在 `frontend/src/layout/`。
- 新增后端领域逻辑优先补服务/领域单测；涉及数据口径、防未来函数、DDL、回测撮合、权限和资产隔离时必须覆盖边界。
- 涉及全量批处理、超长参数列表、窗口/聚合 SQL 或明确规模门槛时，小夹具之外必须补代表性规模回归；阶段验收还需通过真实入口或等价数据规模覆盖输入加载、计算与落表，纯算法基准和 Mock 响应不能替代该链路。
- 新增布局、校验、配置合并或权限消费逻辑时，同步补充 Vitest。
- 涉及页面、组件、样式、表格、弹窗、抽屉时，计划必须说明是否触发页面设计闭环和组件/布局维护矩阵。
- 页面改动按风险选择定向 Vitest、必要的构建或内置浏览器临时复核；Playwright 的新增、更新和执行统一遵守 `agent-works/e2e-automation/guide.md`，不因已有 E2E 覆盖就自动运行整组回归。
- `./start.sh e2e-backtest-run seed|cleanup` 是回测 Playwright E2E 的可清理公开回测夹具（`backend/devtools/e2e_backtest_runs.py`，经 `frontend/e2e/helpers/backtestRuns.ts` 调用）：以固定调试账号显式归属真实跑一条跨 owner 公开策略回测（`e2e_bt_` 前缀 + opaque run_ref）或按前缀精确清理（含 backtest_run_reuse 审计）。同 `dev-users` 受 `AI_STOCKS_ENV=dev|test|local` + `AI_STOCKS_E2E_WRITE=1` 双重门控，并经 `/api/health/e2e` 的 PG 指纹校验防误写他库。因 DuckDB 单文件写锁互斥，夹具进程独占写锁时被测后端必须以 `AI_STOCKS_DUCKDB_READ_ONLY=1` 只读启动；该 spec 与需 DuckDB 写的其余 E2E 须分开运行（读写模式跑全量排除此 spec，只读模式单跑此 spec）。
- `./start.sh e2e-board-data seed|cleanup` 是板块工作台的确定性 DuckDB 夹具，仅写 `E2E9*` 板块、`9999*.SZ` 股票和 2099 年固定行情；同样受本地环境 + `AI_STOCKS_E2E_WRITE=1` 双重门控。只有满足 E2E 准入条件时才使用 `npm run test:e2e:sectors`；普通聚焦回归必须向脚本透传 `--project`、spec 或 `--grep`，不得默认执行三视口整组。脚本负责停服、夹具生命周期和恢复原后端状态。
- `./start.sh e2e-stock-board-correlation seed|cleanup --expected-pg-fingerprint <64位十六进制>` 是个股走势关联板块的确定性 PG + DuckDB 夹具：PG 写 `default/debug_system` 归属下固定 `e2e_sbc_*` 评分/筛选方案、快照和任务运行态，DuckDB 只写 `9977*.SZ`、`E2ECORR_*`、`E2E相关-*` 与 2097 年固定行情/当前冠军；同样受本地环境、`AI_STOCKS_E2E_WRITE=1` 与被测后端 PG 指纹三重门控。聚焦回归统一使用 `cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:stock-board-correlation`，脚本负责账号校准、运行态/停止态停服分支、夹具生命周期、PG/DuckDB 零残留检查和原后端运行档案恢复。
- `./start.sh e2e-trade-discipline seed|cleanup --expected-pg-fingerprint <64位十六进制>` 是交易纪律的确定性 PG + DuckDB 夹具，仅写 `debug_tenant` 固定调试账号归属下 `e2e_td_`/`E2E纪律-`/`E2E类型-` 前缀数据和 DuckDB 的 `9988*.SZ`、2098 年固定交易日；两个动作均要求本地环境、`AI_STOCKS_E2E_WRITE=1`、后端 `/api/health/e2e` 指纹与夹具直连 PG 一致，并须在后端停服时执行。聚焦回归只使用 `cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:trade-discipline`，脚本负责指纹、账号校准、服务切换、夹具清理，并按 `start.sh` 生成的不含密钥运行档案恢复原模式、环境文件、安全开关和 PG 目标；档案只保存额外项目环境变量的不可逆摘要，恢复前还须核对环境文件与这些摘要。原服务运行但档案缺失或不匹配时必须在停服前 fail-closed。
- 跑**全量 Playwright**（多 spec 三视口并行）时，被测后端还须额外 `AI_STOCKS_E2E_LOGIN_BYPASS=1`：三视口为独立 worker 进程，各自密集 `POST /auth/login`（同源 127.0.0.1），不豁免会撞 `login_rate_per_min`（默认 10/min）单 IP 限流导致大面积登录失败。该豁免三重门控（环境白名单 + `AI_STOCKS_E2E_WRITE=1` + 本变量），仅放开 login 的 IP 限流，回归结束后重启后端移除。
- 完整设计验收统一执行 `cd frontend && AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design`；其 Playwright 阶段由 `scripts/run-design-e2e.sh` 按普通读写、板块夹具、关联板块夹具、交易纪律夹具、公开回测只读五组串行编排，禁止把不同固定日期夹具同时 seed 后跑单轮全量。入口负责快照和恢复原后端参数，任何一组失败均执行精确清理。

## 协作与提交

- 除命令、代码、日志和原文外，面向用户输出使用简体中文。
- 改代码前先读同类实现并优先复用；偏离既有分层、命名、返回结构、异常、日志或配置方式时说明理由。
- 最近一次 `git pull` 操作时间：2026-09-10 21:15:00 CST。
- 技术方案、交互设计或关键业务规则不确定时，先给推荐方案与理由让用户确认。
- 不在用户未要求时提交或推送；提交信息使用中文语义化风格，例如 `Agent 新增(基础功能): ...`。
- 不提交 `data/` 本地数据库、`logs/`、个人环境配置或密钥。`prod` 绑定 `0.0.0.0:8000`，公网部署必须配合反向代理、TLS、限流和运维访问控制。
