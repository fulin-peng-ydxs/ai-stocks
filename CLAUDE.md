# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 始终用**简体中文**与用户交互。本文件是给后续 Claude 实例的速查，详尽说明见 [README.md](README.md) 与 [`agent-works/architecture/`](agent-works/architecture/) 下各模块技术文档。

## 项目概述

「复盘啦」——本地单用户、**EOD（收盘后）** 的 A 股趋势龙头研究系统。单进程全栈：FastAPI 提供 REST 接口并在生产期托管前端构建产物（`frontend/dist`），数据落在嵌入式 DuckDB 单文件（`data/ai_stocks.duckdb`），无外部数据库 / 中间件依赖。

数据源为公开免费接口（AKShare / baostock），覆盖近 5 年、主板 / 创业板 / 科创板（不含北交所）。

## 版本要求

环境与依赖**有最低版本约束**，改依赖或排查环境问题时以此为准（完整清单见 [requirements.txt](requirements.txt) / [pyproject.toml](pyproject.toml) / [frontend/package.json](frontend/package.json)）：

- **Python `>=3.11`**（本机 3.12）；`ruff` target 为 `py311`，新语法不要超过 3.11。
- **后端核心**：FastAPI `>=0.110`、uvicorn[standard] `>=0.29`、watchfiles `>=0.21`（`serve --reload` 依赖，须显式安装）、pydantic `>=2.6`（v2，**禁用 v1 写法**）、pydantic-settings `>=2.2`、DuckDB `>=0.10`、pandas `>=2.2`、numpy `>=1.26`、akshare `>=1.13`、baostock `>=0.8.8`、APScheduler `>=3.10`。
- **Node**：Vite `^5` 要求 Node `^18.0.0 || >=20.0.0`（建议 20 LTS）；`package.json` 未声明 `engines`/`.nvmrc`，但低于此版本 `vue-tsc`/`vite build` 会失败。
- **前端**：Vite `^5`、Vue `^3.4`、TypeScript `^5.4`、Element Plus `^2.7`、ECharts `^5.5`、Pinia `^2.1`、vue-router `^4.3`、vue-tsc `^2`、axios `^1.7`。`package.json` 标注 `"type": "module"`（ESM）。
- **测试 / Lint**：pytest `>=8.0`、ruff `>=0.4`（line-length 100）。

## 常用命令

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
```

CLI 入口为 [backend/cli.py](backend/cli.py)，FastAPI 装配在 [backend/main.py](backend/main.py)。

### 端口约定（重要）

- 日常开发：前端 **5173**（唯一对外入口），后端 **8000** 仅本机，由 Vite 代理 `/api` 回 `127.0.0.1:8000`。
- 开发期改前端**不要** `npm run build`（那是无 HMR 的生产产物）；但**每次修改 `frontend/src` 后需 `npm run build`** 以保证生产产物同步。
- 自动化验证（AI 截图/交互核查）走**专用端口 5181**（`.claude/launch.json` 配置的 preview），**禁止抢占用户日常的 5173**。

## 架构与分层

请求路径：浏览器(Vue3 SPA) → REST `/api/**` → FastAPI 路由(`backend/api/`，薄层) → 编排层(`backend/services/`) + 领域引擎 → `storage` 点时安全仓库 → DuckDB。

领域引擎（`backend/` 下各包）：
- `indicators/` 指标引擎——**唯一原子定义**，动态计算 + 单次运行内存缓存，不落预计算表。
- `screening/` 条件 AST + 表达式 DSL 沙箱 + 筛选引擎。
- `scoring/` 阈值打分 + 动态权重评分模型 + 评分快照。
- `signals/` 买卖信号（由买卖方案推导）。
- `backtest/` 前向收益 / 信号质量 / 撮合 Broker / 事件驱动引擎 / 绩效。
- `datasource/` 数据源适配（限流·重试·超时·兜底·溯源）；`dataquality/` 入库清洗 + 四层质检；`scheduler/` APScheduler 定时调度。

模块依赖链：数据管理→DuckDB→指标引擎←配置管理；指标引擎→筛选/榜单→回测；数据全部经 `storage` 点时安全仓库读写。

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
- **UI 一致性**：涉及页面 / 组件 / 样式 / 布局 / 表格 / 列表 / 弹窗 / 抽屉改动，除常规校验外须对照根目录 `DESIGN.md` 做一致性核查（`DESIGN.md` 尚待建立，见 [agent-works/configurable-layout-system/plan.md](agent-works/configurable-layout-system/plan.md)）；与已有规范冲突视为未通过；未覆盖的场景先补齐规范或经用户确认，不临时自创口径。


## 开发契约（不可破坏）

修改功能前必读，细节见 [agent-works/architecture/platform.md](agent-works/architecture/platform.md)：

- **防未来函数**：指标/均线一律后向计算；选股只用 ≤T 数据，回测 T 日选股、**T+1 开盘成交**；平台突破用 `shift(1)`（AST 单测拦截 `shift(负)`）。
- **防幸存者偏差**：universe 点时构造，含"当时存活、后来退市"的票。
- **撮合不失真**：涨跌停价按板块 / ST 计算，开盘封死不可成交、停牌顺延、退市强平；计佣金 / 印花 / 过户 / 方向性滑点。
- **复权一致**：前向收益与回测记账统一**后复权(hfq)**，可成交性判定用**原始价**。源因子 `adj_factor` 用于 K 线前复权，`pre_close` 走独立清洗因子；复权查询统一走 `COALESCE(adj_factor_clean, adj_factor)`，清洗因子**不可写回** `adj_factor`。
- **base rate**：分层命中率必减同期全市场无条件命中率得超额，并附样本量。
- **统一基座**：技术指标是唯一原子定义，买卖/评分/筛选全部引用它组合，**不在下游硬编码字段**。
- **分层职责**：`api/` 只做参数校验与响应包装，业务逻辑放 `services/` 与领域引擎；一切读写经 `storage` 点时安全仓库；长耗时操作走 `async_task` 异步任务底座 + 进度。
- **配置即时生效**：阈值/权重/参数集中在 [config/settings.yaml](config/settings.yaml)，Web 表单改的进 `app_config` 覆盖层；**改参不写进代码**。
- **写库全局互斥**：采集/补数/修复/重算同一时间只能跑一个；遇 409 说明已有写任务在执行。

## 前端布局与交互契约

地图见 [DESIGN.md](DESIGN.md)「布局系统」章（原型清单 / 新建页 7 步 / 组件目录 / 落地坑）；原理稿 [ai-agent/前端布局自适应规范.md](ai-agent/前端布局自适应规范.md)（待全部页面迁完后退场）：

- **新页面走可配置布局系统**：新建/改造页面用 `<LayoutHost>` + `PageLayout` schema（`frontend/src/layout/`），声明原型与具名插槽，**不手写 `.v-page`/`.v-grow`/视口高度**；按 DESIGN.md §2 七步选定原型（关键方案先确认）并在 §7 登记。约束由 `layout/validator.ts` 机制性强制（开发期 `assertLayout` + `npm test`），不靠记忆。存量页未迁前仍遵守下列契约。
- **禁止整页滚动**：两层自适应模型（内部滚动→满足条件才重排多列→整区滚动兜底），遵守 `v-page` / `v-grow` / `v-scroll` 契约。
- **列表交互**：分页/排序走**服务端**，筛选变更**自动触发**，多选**跨页累积**。
- **弹出提示限制在页内**：tooltip / 弹出提示不得溢出到左侧菜单，只在内容区显示。
- **不加冗余按钮**：能点页面现有元素（如版本号 `vN`）触发的操作，就不要单独加按钮。
