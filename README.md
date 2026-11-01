# 复盘啦 · A 股趋势龙头研究系统

「复盘啦」面向收盘后的 A 股复盘、筛选、历史验证和持续跟踪，将行情质量、技术指标、评分与买卖方案串成可解释的研究流程。行情覆盖主板、创业板和科创板，不含北交所；公开免费数据源的默认历史回填目标为近 15 年，实际可用范围以源端覆盖和质量报告为准。

本文维护产品概览、环境准备、最小使用路径、常用任务及文档导航。命令和执行条件以 [AGENTS](AGENTS.md) 为权威入口，系统与模块机制由 [架构正文](agent-works/architecture/system-architecture.md) 维护，界面契约由 [DESIGN](DESIGN.md) 维护。需求闭环、需求、计划和阶段记录不作为当前事实来源，也不纳入本文持续引用。

仅供个人研究，不构成投资建议。

## 可以完成什么

| 研究任务 | 入口与产出 | 技术正文 |
| --- | --- | --- |
| 找当日强势股票 | 每日榜单：按可见评分方案排序，查看综合分、评级与分项解释 | [选股与榜单](agent-works/architecture/screening-and-board.md) |
| 复盘涨停梯队 | 连板天梯：按交易日查看板位、活跃度和走势相关热点，进入个股分析 | [连板天梯](agent-works/architecture/limit-ladder.md) |
| 验证选股条件 | 策略筛选：组合指标或表达式，保存方案并查看候选池 | [选股与榜单](agent-works/architecture/screening-and-board.md) |
| 验证策略与评分 | 策略回测／评分验证：净值、绩效、逐笔成交、分层与超额命中率 | [回测](agent-works/architecture/backtest.md) |
| 跟踪个股和股票篮子 | 个股查询／详情／分组：走势对比、K 线/量能/MACD、买卖信号和已归档分时 | [个股与分组](agent-works/architecture/stocks-and-groups.md)、[分时归档](agent-works/architecture/stock-intraday.md) |
| 理解股票与板块同步性 | 个股、榜单、筛选和天梯中的走势关联：冠军板块、相关度、样本和截止日 | [走势关联](agent-works/architecture/stock-board-correlation.md) |
| 研究行业与概念 | 板块工作台／详情：指数对比、资金流及成分股钻取 | [板块采集与消费](agent-works/architecture/board-collection.md) |
| 配置研究方法 | 配置管理：技术指标、评分方案和买卖方案；方案支持版本、可见范围及复制 | [配置定义](agent-works/architecture/config-definitions.md)、[技术指标](agent-works/architecture/technical-indicators.md) |
| 检查与修复数据 | 数据管理：概览、采集、质量台账、修复复检及定时调度 | [数据管理](agent-works/architecture/data-management.md) |
| 记录交易纪律 | 私人规则、真实持仓和成交、自动履约判断、最新日修正及历史修订 | [交易纪律](agent-works/architecture/trade-discipline.md) |
| 练习盘感 | 随机股票盲测、逐日揭示与 T+1 撮合，查看结算和成长记录 | [盘感训练](agent-works/architecture/market-sense-training.md) |
| 管理平台 | 用户、角色、菜单/功能点、租户、系统参数和布局配置 | [权限与租户](agent-works/architecture/system-rbac-tenant.md)、[环境配置](agent-works/architecture/environment-configuration.md)、[DESIGN](DESIGN.md) |

一条日常使用路径是：**更新收盘数据 → 处理质量问题 → 查看榜单或筛选候选 → 回测验证 → 放入分组跟踪**。技术指标是统一原子定义，下游方案组合引用；需要授权的入口以当前账号菜单和功能码为准。

## 从环境准备到首次访问

### 准备依赖和本机配置

后端使用 Python ≥3.11、FastAPI、DuckDB、PostgreSQL ≥14 和 Redis ≥6；前端使用 Vue 3、TypeScript、Element Plus 和 Vite，建议 Node.js 20 LTS。依赖版本以 [Python 清单](requirements.txt)、[项目配置](pyproject.toml) 和 [前端清单](frontend/package.json) 为准。

先启动并准备 PostgreSQL 数据库/角色与 Redis；再在仓库根目录安装依赖并复制变量模板：

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.local.example .env.local
```

按 [环境与配置加载](agent-works/architecture/environment-configuration.md) 设置 JWT 密钥、PG/Redis 连接及管理员初始密码。本机变量文件不提交；已有 `.env.local` 时直接核对，不能用模板覆盖个人配置。前端安装会校验并应用依赖兼容补丁，不应跳过安装脚本。

### 启动、访问和停止

```bash
./start.sh
./start-web.sh
./start.sh status
```

浏览器打开 `http://localhost:5173`。开发模式由 Vite 将 `/api` 代理到 `127.0.0.1:8000`，前后端分别热更新；生产模式由后端托管前端产物。模式和环境身份的区别见 [系统架构](agent-works/architecture/system-architecture.md#运行装配与生命周期)。

`status` 应显示当前进程、健康响应和存储/任务状态；页面能登录并加载授权菜单才形成首次访问路径。后端日志为 `logs/backend.log`，前端日志为 `logs/frontend.log`；通过脚本的 `logs` 动作跟踪，归档与保留策略见 [环境配置](agent-works/architecture/environment-configuration.md#文件日志归档与清理)。

停止对应服务使用：

```bash
./start-web.sh stop
./start.sh stop
```

后端停止或重启遇到活跃任务、无法可信读取任务状态时会拒绝；先在数据管理查看任务，只有明确接受中断时才使用 AGENTS 声明的强制选项。不要裸杀进程或同时运行争用 DuckDB 文件锁的 CLI 写入。

### 登录账号与权限

`default` 租户的 `admin` 是平台系统管理员，用于初始化和系统级管理。初始密码来源及已有密码不覆盖规则见 [环境配置](agent-works/architecture/environment-configuration.md)；不要将其作为普通权限测试账号。

本地权限验收使用按场景配置的 `debug_*`，维护方式和当前账号见 [测试用户清单](agent-works/multi-tenant-rbac/test-users.md)。评分、筛选、买卖方案和回测的共享范围受资产可见性与后端授权共同约束，非 owner 的公开资产只读。

旧版 DuckDB 部署升级时，先按适用场景处理 [用户资产迁移](agent-works/architecture/system-rbac-tenant.md#旧版用户资产的一次性迁移) 和 [任务运行态切换/回滚](agent-works/architecture/task-runtime.md#一次性升级与受控回滚)，再恢复服务；两种迁移不能互相替代，也不是每次启动都要执行的初始化步骤。

## 数据准备与日常研究

### 首次准备行情

首次进入数据管理，先查看覆盖范围与缺口，再选择所需采集方案。全历史建库可能耗时较长；CLI 批处理与 Web 共用服务，但直接运行 CLI 不会自动加载 `.env.local`，须事先准备其需要的环境变量，且写库前按 AGENTS 检查并安全停止后端。

仓库根目录的首次数据准备顺序为：

```bash
python -m backend.cli backfill
python -m backend.cli delisted --enrich
python -m backend.cli valuation
python -m backend.cli rebuild-price-factors
python -m backend.cli verify-data
```

依次准备日线及前置数据、退市股历史、估值、干净复权因子及正确性体检；完成后恢复原服务状态。成功不能仅看命令结束，还要看质量报告是否仍有关键缺口。历史股本使用页面的逐日股本补采能力，详细方案、来源覆盖与断点边界见 [个股采集](agent-works/architecture/stock-collection.md)；ST、板块和分钟分别见 [ST 事实](agent-works/architecture/st-status.md)、[板块采集](agent-works/architecture/board-collection.md)、[分时归档](agent-works/architecture/stock-intraday.md)。

### 每日收盘后

1. 数据管理 → 数据采集 → 个股采集 → 日常同步，查看冻结的目标日期、进度和任务汇总；需要自动化时配置定时调度。
2. 数据质量中定位待处理问题，修复后复检；来源不可得或请求成功都不能当作问题已解决。
3. 打开每日榜单或策略筛选，选择方案并查看分项及候选；需要验证时进入回测。
4. 将重点股票加入分组跟踪，或在交易纪律记录真实持仓和成交。

应急批处理可在满足相同环境、文件锁和服务恢复要求后运行 `python -m backend.cli daily`。任务的互斥、取消、续跑、依赖和重试解释见 [任务运行态](agent-works/architecture/task-runtime.md)，页面使用和质量口径见 [数据管理](agent-works/architecture/data-management.md)。

榜单与天梯按各自版本协议读取或自愈，走势关联缺失快照时发起首次计算；采集不会自动批量重算所有研究结果。需要提前维护或指定范围重算时，使用数据管理的结果维护或显式调度，详见所属模块正文。

## 开发、验证与生产访问

后端代码从 `backend/main.py`、`api/`、`services/` 和领域模块定位，存储及 DDL 在 `backend/storage/`；前端页面在 `frontend/src/views/`，共享组件在 `components/`，配置布局在 `layout/`。完整分层与数据所有权见 [系统架构](agent-works/architecture/system-architecture.md)。

常用检查从仓库根目录执行，范围和准入以 AGENTS 为准：

```bash
cd frontend && npm run check && cd ..
python -m pytest backend/tests/ -q
```

前端快检包含静态规范、布局契约和类型检查，不连接后端；构建与 GitHub 检查的职责见 [构建与 CI 门禁](agent-works/architecture/system-architecture.md#构建与-ci-门禁)。后端全量命令仅作入口说明；日常按变更风险选择定向测试，可能访问 DuckDB 时须先确认状态、安全停服并在结束后恢复。页面设计流程见 [页面模板](agent-works/configurable-layout-system/page-template.md)，浏览器验证与夹具流程见 [E2E 指南](agent-works/e2e-automation/guide.md)，普通改动不默认执行全量 E2E。

需要生产产物或发布门禁时执行：

```bash
cd frontend && npm run build && cd ..
./start.sh prod
./start.sh status
```

浏览器访问 `http://localhost:8000` 或部署地址。生产启动方式监听 `0.0.0.0:8000` 并托管 `frontend/dist`，公网部署还需反向代理、TLS、限流和运维访问控制；密钥、真实 SMTP 与连接配置按环境配置正文准备。停止、健康检查和活跃任务保护沿用启动脚本。

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 页面空白或 API 404 | 开发访问 5173；确认 Vite 代理；生产检查 `frontend/dist` 和后端静态托管 |
| 后端启动失败 | `./start.sh status`、`./start.sh logs`；核对三类存储及 DuckDB 文件占用 |
| 创建任务返回 409 | 已有 DuckDB 写任务；到任务列表查看，完成后再提交 |
| 读取返回 503 | 区分鉴权依赖故障与 DuckDB 读池繁忙，按日志定位 |
| 榜单日期或结果异常 | 先核对行情、ST 发布、质量台账和方案版本，再按所属模块判断是否维护结果 |
| 历史市值／股本仍缺失 | 查看逐股缺口与来源证据，按个股采集选择补采方案，不能按当前股本倒填 |
| 分时无数据 | 查询只读取已归档事实；在数据管理查看监控范围、采集和质量问题，不从查询页临时取源 |
| 回测耗时长 | 按范围、候选规模和表达式定位；当前回测 API 的同步执行边界见回测正文 |

## 文档归属与深入阅读

| 入口 | 权威内容 |
| --- | --- |
| [AGENTS](AGENTS.md)／[CLAUDE](CLAUDE.md) | 项目协作与命令／Claude 薄入口 |
| [系统架构](agent-works/architecture/system-architecture.md) | 分层、运行单元、数据流、持久层和故障边界 |
| [任务运行态](agent-works/architecture/task-runtime.md) | 后台任务、调度、可靠事件、取消续跑和恢复 |
| [环境配置](agent-works/architecture/environment-configuration.md) | 变量、YAML、PG 覆盖层、运行档案、日志与生效规则 |
| [权限与租户](agent-works/architecture/system-rbac-tenant.md) | 认证、授权、资产归属及新功能接入 |
| [数据管理](agent-works/architecture/data-management.md) | 数据目录、质量策略、问题台账和修复复检；源协议归对应采集专题 |
| [DESIGN](DESIGN.md)／[页面模板](agent-works/configurable-layout-system/page-template.md) | 设计契约／页面实施模板与维护清单 |
| [E2E 指南](agent-works/e2e-automation/guide.md)／[测试用户](agent-works/multi-tenant-rbac/test-users.md) | 验证准入、执行生命周期／固定调试身份 |

领域主题从上方功能表进入，各事实正文只维护所属内容。开发阶段文档保留原有历史与未决状态，归档识别及停止同步统一遵守全局文档边界规范。
