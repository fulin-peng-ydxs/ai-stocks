# 需求闭环分析:板块概念数据采集与展示

> 闭环日期：2026-08-08　修订日期：2026-08-08（评审后同步七项补充决策与权限修正）
> 上游调研：[research.md](research.md)
> 数据源选型（已定）：**同花顺**（唯一可独立闭环「板块字典 + 成分股 + 板块指数 + 资金流」的源，见 research.md）
> 本文件是需求闭环文档，不是正式需求文档；正式 `requirement.md` 已生成并引用本文件确认结论。

> **实施校准（2026-08-09）**：下文保留 2026-08-08 的需求推演过程；当前有效实现以本文件 §12 和 `requirement.md` §14 为准。成分模型已从区间 diff/候选恢复改为「只进不出 + 完整快照闸门」，现行库为 4 张板块表。

---

## 1. 需求理解

把「同花顺板块概念数据」完整接入「复盘啦」系统，分两半：

1. **数据采集**：新增板块数据采集（板块字典、板块成分股、板块指数行情、板块资金流），纳入现有数据采集闭环，接入后与无此数据时**操作无感**——自动随每日流程采集、数据概览自动可见、任务中心可追踪、数据质量可监控。
2. **页面展示**：在「最新行情」菜单下新增子菜单「板块行情」，展示板块强弱，用于题材轮动判断、龙头甄别、资金情绪观察。

## 2. 业务目标

- **采集侧**：把板块字典、成分股归属、板块指数、板块资金流四块数据周期性落入 DuckDB，复用现有采集体系（异步任务、写库互斥、数据概览注册表、数据质量），零人工干预进入每日流程。
- **展示侧**：让投资者在「最新行情」下直接看板块强弱，支撑「题材→龙头」研究链路（板块排行 → 板块详情 → 成分股 → 个股行情）。

## 3. 用户角色、权限与使用场景

| 角色 | 板块数据权限 | 使用场景 |
|---|---|---|
| 普通用户 | 已登录且被授予 `sectors:view`（业务授权集合） | 看板块涨幅榜/资金流、进详情看成分股与指数走势、跳个股 |
| 租户管理员 | 同普通用户（**无数据管理权限**） | 同上；不可见采集/任务/概览 |
| 系统管理员 | 全部 + 数据管理(system) | 在数据采集页触发板块采集/回填、任务中心看进度、数据概览看板块维度 |

**权限修正记录（2026-08-08，二次修订）**：
- 初稿曾误把「触发采集/看任务/看概览」归给租户管理员。核实 `pg_ddl.py:788` 数据管理菜单整体 `visible=system`、`sys_menu.visible` 仅 `login|system` 两值，**租户管理员看不到数据管理**。修正为：采集侧 system-only。
- 二修核实：`sectors:view` **不是登录基线**。登录基线是 [auth/constants.py:27](../../backend/auth/constants.py) `SHARED_RESOURCE_CODES` 强制注入的共享读；普通业务权限须加入 `BUSINESS_RESOURCE_CODES`（constants.py:38），新库随 seed 授予 normal/tenant_admin，**既有库须一次性回填并 bump `perm_ver`**（system-rbac-tenant.md §237-243）。
- 成分股跳转权限感知（R9）：无 `stocks:view` 时成分股数据仍可见，名称/代码渲染为不可点击文本 + hover 提示「无个股行情查看权限」，不执行路由跳转；直接访问 `/stocks/:code` 路由与接口仍 fail-closed。

## 4. 完整业务闭环

### 主链路（采集侧）

```
DailyPipeline.run()
  └─ 新增步骤「板块数据」: IngestionService.ingest_board(ctx)
       ├─ 1. 板块字典刷新  board_dict   (概念+行业并集, 含路径code+app_code(clid)+能力字段)
       ├─ 2. 成分股快照    board_member (逐板块分页取, 完整快照只进不出幂等新增)
       ├─ 3. 板块指数回填  board_bar    (同花顺原始连续指数, 首次全量 + 每日增量)
       └─ 4. 板块资金流    board_fund_flow (概念+行业, 即时/3日/5日/10日/20日全周期采集)
```

- 每日 `daily` 命令自动跑（与「更新数据」步骤并列），失败**不阻塞**行情更新主流程（板块是增强数据）。单板块失败时继续处理剩余板块，但步骤与异步任务最终标 `failed`、DailyPipeline 最终 `ok=false`，并返回失败板块清单供定向续跑。
- 手动路径：数据采集页选「板块采集」/「板块回填」任务 → 任务中心 → 进度/取消/续跑（复用 async_task）。

### 主链路（展示侧）

```
「最新行情」→「板块行情」 → 板块列表页
  ├─ 概念/行业分段 + 主排序周期(今日/5日/10日/20日, 仅控制涨跌幅主排序) + 资金流列(固定即时净流入+数据日)
  ├─ 点板块名 → 板块详情页
  │    ├─ 板块指数走势图(周期切换)
  │    ├─ 统计卡(成分数/涨跌家数/即时净流入/领涨股)
  │    └─ 成分股列表(统一分页; 有 stocks:view 可跳个股, 无则禁用)
  └─ 搜索框按名称检索
```

### 状态流转

- `board_dict` / `board_member` / `board_bar` / `board_fund_flow` 均幂等 upsert，PK 见 research.md §5.1。
- 成分股按 `(board_code, code)` 只进不出累积；完整快照仅新增从未出现的关系，不删除、不做退出 diff。
- **不完整快照保护**：单板块分页不完整或请求失败时整趟不落库，写 `board_member_incomplete` 问题；完整采集时原子刷新 `member_count/member_snapshot_at` 并收敛该问题。

### 失败处理与回退

- 采集失败：async_task 标 failed 并保留已成功工作单元 checkpoint → 数据概览显示板块覆盖/鲜活度/未闭环问题 → 可在采集页或任务中心续跑。
- 单板块成分股/指数取数失败：跳过该板块记日志，不中断整体；不完整成分快照整趟不落库。
- 页面数据缺失：板块列表空态「板块数据未采集，请先在数据采集页运行板块采集」。

## 5. 完整功能点清单

### A. 采集侧（system-only，复用现有闭环）

| 功能点 | 目标 | 入口 | 关键操作 | 系统反馈 | 状态变化 | 异常处理 |
|---|---|---|---|---|---|---|
| A1 板块字典采集 | 落 `board_dict`（概念+行业并集 + 能力字段） | 采集页/每日流程 | 拉同花顺概念+行业字典，与资金流源并集合并 | 写入N条 | 幂等 upsert | 失败记日志不中断 |
| A2 成分股快照采集 | 落 `board_member` | 同上 | 逐板块翻页取成分，完整快照 `ON CONFLICT DO NOTHING` | 本次新增X | `(board_code, code)` 只进不出累积 | 不完整快照整趟不落库并写 `board_member_incomplete` |
| A3 板块指数采集 | 落 `board_bar`（同花顺原始指数） | 同上 | 首次全量回填+每日增量 | 写入N条 | 幂等 upsert | 单板块失败跳过 |
| A4 板块资金流采集 | 落 `board_fund_flow`（概念+行业, 多周期） | 同上 | 拉概念/行业资金流排行；有稳定代码时按代码映射，概念资金流无代码时按名称映射 | 写入N条 | 幂等 upsert | 未匹配写质检, 不伪造代码 |
| A5 异步任务 | 板块任务进任务中心 | 数据采集页 | 创建任务/看进度/取消/续跑 | 任务状态流转 | async_task | 复用现有机制 |
| A6 维度注册 | 数据概览可见 | seed/概览页 | `data_dimension_registry` 加 `board` 维度并聚合板块统计 | 维度行 + 4 表行数、类型数、覆盖、最新日期、问题分类、最近更新 | collected | 统计失败降级，不影响其他维度 |
| A7 数据质量与修复 | 指数缺口/成分不完整/资金流未匹配闭环 | 质检流程 | 扫描 `board_index_gap`；采集写 `board_member_incomplete`/`board_fund_unmatched`；fix 分派对应重采 | 写/更新 `data_quality_issue` + 异步修复任务 | `open → fixing → resolved`，仅复检通过才 resolved | 失败或复检未通过回 open；失败工作单元不记完成 checkpoint |

### B. 展示侧（业务授权集合，非登录基线）

| 功能点 | 目标 | 入口 | 关键操作 | 系统反馈 | 状态变化 | 异常处理 |
|---|---|---|---|---|---|---|
| B1 板块列表页 | 看板块强弱总览 | 最新行情→板块行情 | 概念/行业切换、周期切换、资金流排序 | 排行列表 | 筛选态 | 空态引导采集 |
| B2 板块搜索 | 快速定位板块 | 列表页搜索框 | 输入名称 | 过滤结果 | 筛选态 | 无结果空态 |
| B3 板块详情页 | 看板块全景 | 仅点板块名 | 指数走势/成分股/领涨股 | 卡片+图表+表格 | — | 数据缺失降级 |
| B4 成分股跳转 | 联动个股 | 详情页点成分股 | 跳 `/stocks/:code` | 个股详情 | 路由跳转 | 复用 stocks:view |

## 6. 页面闭环草案

**新增 2 个页面，均严格遵守 DESIGN.md 可配置布局系统**（红线）。

### 板块行情列表页 `/sectors`（`list` 原型）
- **入口**：「最新行情」菜单新增「板块行情」子菜单（与 `/stocks`、`/board` 并列）。
- **结构**：
  - action 区：`AppControlRow`——概念/行业分段、**主排序周期分段**（今日/5日/10日/20日，仅控制涨跌幅主排序字段，默认降序）、名称自由文本搜索（`el-input` + 防抖）。按净流入或上涨家数排序时取消周期高亮，切回涨跌幅排序恢复最近一次合法周期。
  - main 区：`AppDataTable`（growMain），列：板块名称(link)、成分股数、上涨/下跌家数、**今日/5日/10日/20日涨幅**、即时净流入（含数据日）、领涨股及涨幅。点击涨跌幅列头同步当前周期。
  - 展示口径：今日涨幅相对上一交易日，5/10/20 日涨幅相对对应交易日前收盘，历史不足显示「—」；涨/跌家数按最近板块交易日有效成分股的个股收盘与前收比较，平盘、停牌和缺行情不计入涨/跌。
- **数据来源**：`board_dict` join `board_bar`（涨幅计算）+ `board_fund_flow`（即时净流入）+ `board_member` 成分计数。
- **四态**：empty→引导去采集页；error→`AppStateBlock` 带重试；loading→`v-loading`。
- **权限**：`sectors:view`（业务授权集合，非登录基线），无权限→permission 无权态。
- **pageRegistry**：登记 `sectors`，走 `scaffold-page` 或手写 `PageLayout`，同步 page-registry marker。

### 板块详情页 `/sectors/:code`（`detail` 原型）
- **结构**：
  - 摘要卡：板块名称、类型标签（概念/行业）、**路径 code + App code(clid)**、成分股数、今日涨幅、**上涨/下跌家数**、即时净流入（含数据日）、**领涨股及涨幅**。
  - 指数走势图：ECharts，经 `components/chartTheme.ts::useEChartsTheme()` 消费主题；周期切换（近1月/3月/半年/1年），原始连续指数。
  - 成分股表：`AppDataTable`（embedded），代码/名称/现价/涨跌幅/换手，按涨幅排序，**统一分页（无 TopN 展开/收起）**；有 `stocks:view` 时点击跳个股，无权限时名称禁用 + hover 提示，不跳转。
- **联动**：详情返回列表保留筛选态；成分股跳 `/stocks/:code` 复用 `stocks:view`。

### 权限边界
- `sectors:view` 挂 login 菜单 + **进 `BUSINESS_RESOURCE_CODES` 业务授权集合**（普通用户/租户管理员可看）；既有库一次性回填 + bump `perm_ver`。
- 采集管理走 system（数据管理菜单）。
- 成分股跳转需 `stocks:view`；无权限时禁用链接 + hover 提示，直接访问路由 fail-closed。
- 新页面需同步：路由、菜单 seed、功能点 seed、后端守卫 `require_perm`、按钮 `v-permission`、默认角色授权决策、租户归属（见 `agent-works/architecture/system-rbac-tenant.md`）。

## 7. 已确认的关键决策（共十一项，无剩余阻塞项）

### 4 项基础决策

| # | 确认项 | 决策 | 依据 |
|---|---|---|---|
| 1 | 展示范围 | **只做概念+行业**，地域/风格暂不纳入 | 用户决策 |
| 2 | 资金流是否纳入第一期 | **纳入**（实测同花顺概念387+行业90可用） | 用户决策 + 实测 `stock_fund_flow_concept/industry` 可用 |
| 3 | 板块指数口径 | **存同花顺原始连续指数**；页面周期切换只改变查看区间，不代表复权处理 | 实测同花顺指数天然连续、无除权概念，接口无复权参数 |
| 4 | 页面布局方式 | **严格走 DESIGN.md 可配置布局系统**（红线）：`LayoutHost` + pageRegistry + page-template 闭环 | DESIGN.md §5/§7 + 用户红线要求 |

### 七项补充决策（2026-08-08 评审后）

| # | 决策项 | 结论 |
|---|---|---|
| 5 | 周期控件语义 | 今日/5日/10日/20日**仅控制涨跌幅主排序字段**（默认降序）；表格补对应 20日涨幅列；点击涨跌幅列头同步当前周期；资金流固定展示最新交易日「即时净流入」并标注数据日；资金流 3日/5日/10日/20日继续采集但不受本控件控制，避免一控件混合两套口径 |
| 6 | 成分股落库 | **2026-08-09 实施修订**：`board_member` 采用 `(board_code, code)` 只进不出累积；完整快照幂等新增，不完整快照整趟不落库；用 `member_snapshot_at` 标识最近一次完整采集 |
| 7 | 字典与资金流集合差异 | **2026-08-09 实施修订**：不采用并集字典——资金流源无稳定代码，资金流独有板块不进 `board_dict`，未匹配写 `board_fund_unmatched` 质检不伪造代码（见 requirement.md §2.5/R4）；`source` 恒为 `ths`，能力差异用 `has_members`/`has_bar`/`has_fund_flow`/`member_history_start_date`/`last_seen_at` 字段 |
| 8 | 质量规则 | **2026-08-09 实施修订**：成分数变化不再作为异常；质量规则保留 `board_index_gap`，并由采集层产生 `board_member_incomplete`、`board_fund_unmatched`；状态沿用 `open/fixing/resolved/ignored` |
| 9 | 历史不可回溯 | 本期**不改回测**；在 `board_dict.member_history_start_date` 保存板块级可信起始日（非每条成员重复字段）；接口可返回该字段；后续接入筛选/回测时再对早于该日期的查询拒绝或警告 |
| 10 | 成分股跳转权限 | 无 `stocks:view` 时成分股数据仍可见，名称/代码渲染为不可点击文本 + hover 提示「无个股行情查看权限」，不执行路由跳转；直接输入 `/stocks/:code` 路由与接口仍 fail-closed |
| 11 | 双代码体系 | 同花顺概念板块有两套代码：**路径 code（30xxxx，如 AI PC=309121，取数/跳转统一用它）** 与 **App clid（88xxxx，如 AI PC=886071，手机 App 显示）**。主键用路径 code；`board_dict.app_code` 存 clid（逐板块详情页抓取，375 概念需额外 1 请求/板块），供用户与手机 App 核对。行业板块 clid=路径 code。概念资金流接口只返回名称无代码，映射按名称匹配 |

## 8. 已确认的非阻塞设计结论（无剩余确认项）

| # | 确认项 | 处理 |
|---|---|---|
| 1 | 列表默认排序 | 今日涨幅（情绪主线）为默认主排序周期，5日/10日/20日可切换 |
| 2 | 概念375个分页 | 服务端分页（复用 `AppPagination`），配合搜索框 |
| 3 | 详情页成分股展示 | 统一分页（`AppPagination` 默认每页 20，抽屉可配），用户要求改项目统一模式 |
| 4 | 板块字典当前成分数 | 完整快照时刷新 `member_count/member_snapshot_at`；列表/详情使用当前快照数，成分明细接口 `total` 是只进不出累计关系数 |
| 5 | 采集频率 | 每日流程自动跑 + 手动「板块回填」全量重跑 |
| 6 | 板块数据质量校验 | 指数缺口扫描 + 成分不完整/资金流未匹配采集问题纳入质检与异步修复；不做成分数波动质检 |
| 7 | 页面风格 | **严格继承 DESIGN.md 全部规范**（用户要求"越统一越丰富越好"） |
| 8 | 资金流 3日/5日/10日/20日 | 继续采集（`board_fund_flow` 全周期），页面本期只展示即时，后续可加筛选 |

## 9. 范围划分

### 必须实现
- R1-R10：板块字典、成分关系、指数、资金流、采集任务、数据概览、列表、详情、权限感知跳转和搜索。
- R21-R23：采集流程集成（daily/回填/断点）、页面/RBAC 接入（菜单/资源/授权回填/perm_ver）和页面配置闭环。
- 菜单/路由/权限：`/sectors` 路由、`sectors:view` 进业务授权集合（非登录基线）+ 既有库回填 + bump `perm_ver`、page-registry 登记、菜单 seed、功能点 seed

### 建议实现（处理状态）
- R11 板块指数周期切换：`本次纳入`
- R12 板块维度数据质量校验：`本次纳入`
- R13 成分股统一分页（无 TopN 展开，`AppPagination` 默认 20 抽屉可配）：`本次纳入`
- R14 板块资金流统计卡（详情页摘要）：`本次纳入`

### 暂不实现
- R15 地域/风格板块：第一期只做概念+行业。
- R16 板块资金流历史趋势图：第一期只展示统计卡数字。
- R17 题材联动图谱 / 板块重叠分析：后续独立需求。
- R18 东财板块指数交叉验证：源不稳定，后续再评估。
- R19 板块成分作为筛选/回测条件：需回测层起点护栏，本期不改回测。
- R20 板块强弱热力图：需图表组件扩展。
- R24 审计可靠性提升：项目现无 outbox 设施，本期维持 best-effort。
- R25 同日候选替换：已随候选机制删除而废弃。

## 10. 推断依据与推断决策

- **菜单归属「最新行情」**：依据 `pg_ddl.py:781` 现有 `quotes` 菜单下已挂 `/stocks`、`/board`，板块行情同属「看行情」域。
- **采集无感接入**：依据 `async_task.py` 的 TASK_TYPES/WRITE_TASK_TYPES/TASK_LABEL、`ddl.py:706` 的 `_DIMENSION_SEED`、`pipeline.py` 的 `DailyPipeline.run` 三步结构。板块新增任务类型 + 维度注册 + daily 加一步即可无感。
- **数据源封装**：依据 research.md 附录，单独封装 `ThsBoardSource`（`backend/datasource/ths_board.py`），**直连同花顺 `q.10jqka.com.cn` / `data.10jqka.com.cn`，不走 akshare 公开函数**（akshare 仅调研验证用）；复用 `base.py` 的 `rate_limited`/`with_retry`，内部处理 `v_cookie()`（复用 akshare 打包的 ths.js 反爬脚本）与 AJAX 翻页；不进 `_source_for` 选源链，由 `IngestionService` 直接持有。
- **页面架构**：严格按 DESIGN.md，新增页面走 `LayoutHost` + pageRegistry + page-template 闭环（用户红线）。
- **权限边界**：采集侧 system-only（数据管理菜单 `visible=system`）；展示侧 `sectors:view` 进 `BUSINESS_RESOURCE_CODES` 业务授权集合（非登录基线），新库 seed 授予 normal/tenant_admin，既有库一次性回填 + bump `perm_ver`（依据 auth/constants.py + system-rbac-tenant.md）。
- **页面配置契约**：业务偏好走 `usePageSettings`（`scope='page' + pref_key='settings'` 单个对象，对齐 usePageSettings.ts）；表格字段走 `layout_user_config`；`responsiveProfile` 用 `single-column`（pageRegistry 枚举，非 list/detail）；两页 `supportsPageSettings !== false` → `overlay:settings-drawer` 自动补登；偏好优先级 `URL query > 已保存偏好 > 默认值`。
- **现行恢复事务**：候选恢复机制已废弃。完整成分快照落库、`member_count/member_snapshot_at` 刷新和活跃 `board_member_incomplete` 收敛在同一 DuckDB 事务中；指数缺口和资金流未匹配通过异步 fix 重采后复检，只有复检通过才 resolved。PG 审计仍为 best-effort，不引入 outbox。

## 11. 后续建议

- **保存条件**：已满足（4 项基础决策 + 七项补充决策全部确认，权限边界已二修）。本文件即闭环文档。
- **正式 `requirement.md` 已生成**：基于本文件确认结论，含 DDL、接口契约、权限 seed、页面原型 `prototypes/`。本文档与 `requirement.md` 保持同步。

## 12. 当前闭环实施结论（2026-08-09）

- 采集侧已对齐现有数据管理全链路：CLI、daily、异步任务、写互斥、采集页、调度、任务中心、数据源状态、维度目录、概览、质量扫描与修复均已承接板块类型。
- 失败闭环已细化到真实工作单元：字典类型、成分/指数板块、资金流类型+周期；部分失败保持 failed 和 checkpoint，可只续跑未成功项。
- 概览不再只有维度注册行，已展示板块规模、覆盖、最新日期、问题分类和最近更新，并可跳转采集。
- 展示侧后端 `/api/sectors*` 与 RBAC 已完成；`/sectors`、`/sectors/:code` 前端页面及页面配置闭环仍未完成，继续按正式需求和开发计划实施。
