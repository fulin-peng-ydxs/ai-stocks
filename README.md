# 复盘啦 · A 股趋势龙头研究系统

「复盘啦」面向收盘后的 A 股复盘、筛选、历史验证和持续跟踪，将行情质量、技术指标、评分与买卖方案串成可解释的研究流程。行情覆盖主板、创业板和科创板，不含北交所；公开免费数据源的默认历史回填目标为近 15 年，实际可用范围以源端覆盖和质量报告为准。

开发参考：[协作与项目命令](AGENTS.md) · [验证与总维护清单](agent-works/testing/guide.md) · [页面实施模板](agent-works/configurable-layout-system/page-template.md) · [设计规则](DESIGN.md)。

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
| 管理平台 | 用户、角色、菜单/功能点、租户、系统参数和布局配置 | [权限与租户](agent-works/architecture/system-rbac-tenant.md)、[环境配置](agent-works/architecture/environment-configuration.md)、DESIGN |

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

## 项目目录

主要源码、配置、工具和文档入口如下。后端按技术分层与领域拆分；前端页面在 `views/`，跨页面能力在组件、组合逻辑和布局目录中维护。

```text
ai-stocks/
├── backend/                        后端应用与领域实现
│   ├── main.py                     FastAPI 应用装配与生命周期
│   ├── cli.py                      数据准备、采集、修复和校验的 CLI 入口
│   ├── api/                        REST 路由、请求校验与服务调用
│   ├── services/                   业务编排、采集流程、后台任务和结果查询
│   ├── auth/                       身份上下文、JWT、会话、权限解析与守卫
│   ├── security/                   平台敏感配置加解密
│   ├── config/                     配置模型、覆盖加载与来源请求配置
│   ├── common/                     异常、日志、时间、请求和邮件等共用工具
│   ├── datasource/                 AKShare、baostock 等来源适配与请求控制
│   ├── dataquality/                质量检查、问题整合与忽略规则
│   ├── storage/                    DuckDB / PostgreSQL / Redis 访问与 DDL
│   ├── indicators/                 原子指标定义、注册、计算与周期处理
│   ├── screening/                  选股条件、表达式、方案与筛选引擎
│   ├── scoring/                    评分模型、方案与结果快照
│   ├── signals/                    买卖方案、买点信号与风险规则
│   ├── backtest/                   回测引擎、撮合、收益与稳健性评估
│   ├── groups/                     股票分组与板块自选
│   ├── limit_ladder/               连板天梯使用的点时 ST 状态规则
│   ├── scheduler/                  定时调度与任务触发
│   ├── market_identity.py          证券更码与历史身份映射
│   ├── market_rules.py             交易板块、ST 与涨跌停规则
│   ├── price_adjustment.py         价格复权共用计算
│   ├── devtools/                   本地调试账号、测试夹具与性能诊断工具
│   └── tests/                      后端领域、服务、API 与存储测试及夹具
├── frontend/                       Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── main.ts / App.vue       应用挂载与根组件
│   │   ├── views/                  业务页面、数据管理与系统管理页面
│   │   ├── components/             图表、表格、指标、方案等共享组件
│   │   ├── composables/            查询、偏好、任务轮询与交互等组合逻辑
│   │   ├── layout/                 配置布局引擎、容器组件与布局契约
│   │   ├── api/                    API 客户端与按业务划分的请求封装
│   │   ├── router/                 路由注册、页面跳转与访问控制
│   │   ├── stores/                 Pinia 全局状态
│   │   ├── directives/             权限、键盘操作等自定义指令
│   │   ├── styles/                 全局样式与共用视觉规则
│   │   ├── constants/              分页等共享常量
│   │   ├── types/                  TypeScript 类型定义
│   │   └── utils/                  通用工具与数据处理辅助
│   ├── e2e/                       Playwright 场景、辅助方法与夹具
│   ├── scripts/                   静态规范检查、契约门禁与页面脚手架
│   ├── patches/                   前端依赖补丁
│   ├── public/                    直接发布的静态资源
│   └── package.json               前端依赖与 npm 命令入口
├── config/settings.yaml           非敏感配置基线
├── scripts/                       环境加载、日志及专项验证运行脚本
├── .github/workflows/             GitHub CI 检查定义
├── agent-works/architecture/       当前系统架构与模块技术说明
├── AGENTS.md / CLAUDE.md           项目 AI 协作规范与 Claude 薄入口
├── DESIGN.md                      前端设计规范
├── pyproject.toml                 Python 依赖、工具与测试配置
├── .env.local.example             本机环境变量示例
├── start.sh                       后端启动、停止、状态和日志入口
├── start-web.sh                   前端开发服务入口
├── data/                          本地行情库与导出等运行数据（不提交）
└── logs/                          运行日志与运行档案（不提交）
```

前端单元与契约测试就近放在 `src/` 各目录的 `__tests__/` 中，浏览器场景位于 `frontend/e2e/`。盘感训练、交易纪律、板块关联等功能的编排可从 `backend/services/` 和对应 `backend/api/` 入口定位，并非每项业务都对应独立的后端顶层目录。

代码分层、模块依赖与数据所有权见 [系统架构](agent-works/architecture/system-architecture.md)，具体机制从该文档进入所属模块正文；开发命令和执行条件以 AGENTS 为准。

## 开发、验证与生产访问

以下为常用检查示例，从仓库根目录执行：

```bash
cd frontend && npm run check && cd ..
python -m pytest backend/tests/test_xxx.py::test_name -q  # 替换为受影响的真实用例
```

前端快检无需后端，不代表全部前端或后端测试。后端示例须替换为实际用例，运行前先按验证规范处理数据库隔离与 DuckDB 服务锁。

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
| AGENTS／[CLAUDE](CLAUDE.md) | 项目协作与命令／Claude 薄入口 |
| [系统架构](agent-works/architecture/system-architecture.md) | 分层、运行单元、数据流、持久层和故障边界 |
| [任务运行态](agent-works/architecture/task-runtime.md) | 后台任务、调度、可靠事件、取消续跑和恢复 |
| [环境配置](agent-works/architecture/environment-configuration.md) | 变量、YAML、PG 覆盖层、运行档案、日志与生效规则 |
| [前端布局实现](agent-works/architecture/frontend-layout.md) | 布局与外观的加载、合并、字段策略、保存、恢复及失败边界 |
| [权限与租户](agent-works/architecture/system-rbac-tenant.md) | 认证、授权、资产归属及新功能接入 |
| [数据管理](agent-works/architecture/data-management.md) | 数据目录、质量策略、问题台账和修复复检；源协议归对应采集专题 |
| [E2E 指南](agent-works/e2e-automation/guide.md)／[测试用户](agent-works/multi-tenant-rbac/test-users.md) | 验证准入、执行生命周期／固定调试身份 |

领域主题从上方功能表进入，各事实正文只维护所属内容。开发阶段文档保留原有历史与未决状态，归档识别及停止同步统一遵守全局协作约束。
