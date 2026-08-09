# 开发计划：板块概念数据采集与展示

> 计划版本：2026-08-09（当日评审复核修订：表达式唯一索引可行性实测确认并补降级方案、候选 apply 写锁冲突语义、T8/T10 依赖收紧、菜单 seed 部署时序、审计文件路径修正、板块 E2E 数据夹具、两页 pageSize 合法值口径显式化、`DuckDBClient.transaction()` 原子性前置、T2 适配器封装口径对齐 research 附录已确认决策；二轮评审复核整改：T9 候选应用事务②补入 `member_count` 刷新、T10 拆分 T10a/T10b 消除 T8↔T10 双向依赖、T7 issue 判重与收敛策略补明确、T9 写锁冲突识别机制补明确、领涨股取数来源默认定为资金流 leader_stock（T8 明确，口径待确认）、列表页 pageSize 原型冲突差异说明补注、`board` 任务类型与既有榜单命名空间边界声明、§7.3 回滚基线内容与「回填 SQL 待 T10 产出后固化」声明、候选列表 board_type 过滤参数补入、板块字典核心能力展示口径承接、T7 不误删候选关联 open issue 的收敛边界；**三轮实测修正：`duckdb_max_lock_wait_time` 实测不存在（SET 抛 CatalogException）与跨进程写锁「立即失败」实测推翻锁等待模型，写锁冲突识别改为纯关键字归类；领涨股口径（资金流日 leader_stock 与涨幅日不一致的展示）转回待确认项；四轮实测修正「连接残留污染态」叙事不实——冲突仅发生在 connect 阶段、`_conn` 保持 None、锁释放后重试即自动恢复，无需显式释放连接**；T1 执行（2026-08-09）：契约逐项对照代码现状核验成立，补 R12 阈值 `Settings` 模型子模型字段一环（§7.4/T7）；**T2 执行（2026-08-09）：`ThsBoardSource` 适配器落地（16 单测绿 + 真源冒烟 375/90/成分/指数/资金流通过），实测发现成分股翻页第 6 页起必登录墙（`complete=False` 标不完整）与概念字典=分类页 351∪gn/index 前 3 页净增 24=375**；**登录态实测补充（2026-08-09 用户提供浏览器登录 cookie）：登录态解除详情页翻页登录墙（半导体取全 160 只 vs 无登录 100 只），适配器新增 `login_cookie` 参数 + `AI_STOCKS_THS_COOKIE` 环境变量支持、限速默认 ≥2s/次；数据中心 IP 连续请求仍触发动态风控（401/空页），`complete=False` 兜底保留**；**T3 执行（2026-08-09）：DuckDB 5 表 DDL + board 维度注册落地（`M_BOARD_TABLES` + `_DIMENSION_SEED`，17 用例全绿，表达式唯一索引 INSERT/UPDATE 两路径实测拦截，DuckDBClient 异常重建连接语义记录）**；**T4 执行（2026-08-09）：采集服务落地（`BoardIngestService` + `DuckDBClient.transaction()` + `ingest_board` 编排，10 用例全绿，diff/payload_hash 幂等/候选事务①/资金流映射/写锁归类）**；**T5 执行（2026-08-09）：`board` 异步任务类型注册（TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES + `_h_board` checkpoint=board_code + 前端「板块采集」标签，4 用例全绿）**；**T6 执行（2026-08-09）：CLI `board` 命令族 + daily 集成（`DailyPipeline.run(board=True)` + `--skip-board` + 失败隔离不阻塞主流程 + total_steps 同步，4 参数化用例全绿）**）
> 需求文档：[requirement.md](requirement.md)（2026-08-08 评审修订版，确认状态：无阻塞项）
> 上游文档：[requirement-closure.md](requirement-closure.md)、[research.md](research.md)
> 页面原型：[prototypes/sector-board.html](prototypes/sector-board.html)（列表页）、[prototypes/sector-detail.html](prototypes/sector-detail.html)（详情页），均已完整读取并作为前端拆解依据。

## 1. 需求来源与目标

- 需求文档：`agent-works/concept-industry-board/requirement.md`
- 功能目标：
  1. 数据采集：新增板块字典、板块成分股、板块指数、板块资金流四块数据采集（同花顺源），纳入现有采集闭环（CLI / 异步任务 / 每日流程 / 数据概览 / 数据质量）。
  2. 页面展示：「最新行情」下新增「板块行情」列表页 `/sectors` 与详情页 `/sectors/:code`，支撑「题材 → 板块 → 成分股 → 龙头」研究链路；数据质量页承接成分快照候选确认/丢弃闭环。列表/详情只展示具备核心数据（`has_members` 或 `has_bar`）的板块，资金流独有板块（仅 `has_fund_flow`）不进入展示（承接需求 §2.5 并集字典展示口径）。
- 本次不做：R15-R20、R24、R25（见 §3.3，原因以需求文档 §4.3 为唯一事实源）。
- 计划输出目录：`agent-works/concept-industry-board/plan.md`

## 2. 当前项目依据

- 采集基座：[async_task.py](../../backend/services/async_task.py)（`TASK_TYPES:28`、`WRITE_TASK_TYPES:31`、`TASK_CAPABILITIES:39`）；[ingest.py](../../backend/services/ingest.py)；[pipeline.py](../../backend/services/pipeline.py)（`DailyPipeline.run(skip_update, verify, quality)`，`total_steps` 在 :49，失败聚合 `ok = all(...)`）；[cli.py](../../backend/cli.py)（`daily` 命令 :418/:659）。
- 数据源抽象：[datasource/base.py](../../backend/datasource/base.py)（`DataSource:113`、`rate_limited:40`、`with_retry:71`）；现有 `akshare_source.py`/`baostock_source.py`；板块数据单独封装 `ThsBoardSource`（[datasource/ths_board.py](../../backend/datasource/ths_board.py)，T2 已落地），不进 `_source_for` 选源链。
- DDL 与维度：[ddl.py](../../backend/storage/ddl.py)（`_DIMENSION_SEED:708`，seed 在 :778 幂等）。
- 质检：[data_report.py](../../backend/services/data_report.py)（`data_quality_issue` 扫描与状态枚举 `open → fixing → resolved`、`ignored`）。
- 权限：[auth/constants.py](../../backend/auth/constants.py)（`SHARED_RESOURCE_CODES:27`、`BUSINESS_RESOURCE_CODES:38`）；[pg_ddl.py](../../backend/storage/pg_ddl.py)（`_SEED_MENU_TREE:781` quotes 下已有 `/stocks`、`/board`；`_SEED_RESOURCES:847` 起；`perm_ver` 契约 :82/:1298/:1401；回填 marker 幂等模式 :934/:1114，参照 `asset-publish-open.sql` 确定性基线恢复）。
- 前端基座：[pageRegistry.ts](../../frontend/src/layout/pageRegistry.ts)（`consumedComponentFields:51`、`componentMeta:59`、`groupTable` 嵌套 slot 模式 :204-257）；[page-template.md](../configurable-layout-system/page-template.md) 新页面固定流程；[DESIGN.md](../../DESIGN.md) §5 可配置布局系统。
- 页面样板：[StocksView.vue](../../frontend/src/views/StocksView.vue)（list）、[StockDetailView.vue](../../frontend/src/views/StockDetailView.vue)（detail）、[QualityView.vue](../../frontend/src/views/data/QualityView.vue)（质检列表复用）。
- 配置：[settings.py](../../backend/config/settings.py)（`get_effective_settings:372`）。
- 依赖核实：`py_mini_racer` 本机已可 import（随 akshare 传递依赖引入），生产直接 import 需在 `requirements.txt`/`pyproject.toml` 显式声明。
- 审计：[audit_repository.py](../../backend/storage/audit_repository.py) 现状为 best-effort（文件头注明「仅提供 best-effort 写入能力」，异常返回 `None`），本期沿用，不引入 outbox。

## 3. 实施范围

### 3.1 必须实现

R1、R2、R3、R4、R5、R6、R7、R8、R9、R10、R21、R22、R23（逐项映射见 §5）。

### 3.2 可选增强

| 需求编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R11 | 板块指数周期切换（1月/3月/半年/1年） | 本次纳入 | 待开始 | T12 | 详情页走势图周期分段 |
| R12 | 板块维度数据质量校验（成分数波动/指数缺口） | 本次纳入 | 待开始 | T4、T7、T13 | 阈值配置化 + 复用 `data_quality_issue` |
| R13 | 详情页成分股统一分页（`AppPagination` 默认 20，无 TopN 展开） | 本次纳入 | 待开始 | T8、T12 | 服务端分页接口 + 页面表格 |
| R14 | 板块资金流统计卡（即时净流入额） | 本次纳入 | 待开始 | T8、T12 | 详情页摘要卡 |

### 3.3 暂不实现

| 需求编号 | 需求项 | 开发状态 | 跳过原因 | 后续触发条件 |
| --- | --- | --- | --- | --- |
| R15 | 地域/风格板块 | 跳过 | 用户确认第一期只做概念+行业 | 用户需要地域/风格维度时 |
| R16 | 板块资金流历史趋势图 | 跳过 | 第一期只做统计卡数字 | 需要资金面趋势分析时 |
| R17 | 题材联动图谱 / 板块重叠分析 | 跳过 | 复杂跨板块分析，独立需求 | 需要板块间联动研究时 |
| R18 | 东财板块指数交叉验证 | 跳过 | 东财 push2 源不稳 | 东财恢复稳定时 |
| R19 | 板块成分作为筛选/回测条件 | 跳过 | 需筛选引擎扩展 + 回测层标注 | 板块接入回测联动时 |
| R20 | 板块强弱热力图 | 跳过 | 需图表组件扩展 | 需要全市场板块一屏总览时 |
| R24 | 审计可靠性提升（outbox/重试/对账） | 跳过 | 项目现无 outbox 设施，本期审计 best-effort | 需要审计不丢失时 |
| R25 | 同日候选替换（`superseded` + D-1 重建） | 跳过 | 本期冻结「每板块每日最多一个 applied」 | 需要修正当日成分快照时 |

## 4. 技术方案

整体按需求文档 §12 五阶段推进：契约 → 数据源与 DDL → 采集与质检 → API 与权限 → 页面。模块边界：

- **数据流**：`ThsBoardSource`（直连 `q.10jqka.com.cn` / `data.10jqka.com.cn`，复用 akshare 打包的 `ths.js` 经 `py_mini_racer` 生成 v cookie，不调用 akshare 板块接口）→ `BoardIngestService`（字典两阶段 / 成分快照 diff / 指数 / 资金流并集映射）→ DuckDB 5 表 → `BoardQueryService`（只读聚合，单次全查内存合并，遵循双库边界）→ `/api/sectors*` → 前端页面。
- **候选恢复闭环**（R2）：不完整快照/异常波动 → 同一 DuckDB 事务写 `board_member_candidate` + `data_quality_issue`（`member_surge_shrink`，open，跳过 fixing）→ 数据质量页确认应用（事务②：diff 落库 + 候选 applied + issue resolved + **同步刷新 `board_dict.member_count` 与 `member_history_start_date`**）或丢弃（事务③：候选 discarded + issue ignored）→ PG 审计 best-effort。`member_count` 为最近一次已应用完整快照的冗余值，两条刷新路径都走「**已应用**」判定：T4 完整快照 diff 落库路径与 T9 候选应用路径各刷一次，被拦截未应用的候选不改该值（R2 验收标准「member_count 与有效成员数一致」）。多语句原子事务依赖 T4 为 `DuckDBClient` 新增的 `transaction()` 上下文管理器（持进程内 RLock 跨 BEGIN..COMMIT，见 T4/T9）。
- **接口契约**：`/api/sectors` 参数白名单（`trade_date/board_type/sort_by/order/keyword/page/size`），`sort_by` 字段码 `pct_today|pct_5d|pct_10d|pct_20d|net_inflow|up_count`；统计口径（涨幅按收盘价比对、历史不足显示「—」不缩短周期、涨跌家数按成分股 `close` vs `pre_close` 且平盘/停牌/缺行情不计入）严格按需求 §6.2 契约要点实现；**领涨股及涨幅默认口径取 `board_fund_flow.leader_stock/leader_pct` 且与「即时净流入」同一 `(snapshot_date, period='即时')` 行（口径待确认项，见 §10.3）——无资金流数据的板块该列显示「—」**（不走「当日成分股涨幅第一」另行计算，口径单一）。
- **双口径边界（T8 必须遵守）**：列表/详情页的 **5日/10日/20日涨幅列与主排序周期（`pct_5d/pct_10d/pct_20d`）= 板块指数价格涨跌幅，T8 查询时从 `board_bar` 日线实时计算**（最近交易日收盘 vs N 个交易日前收盘，`trade_date <= D` 截面语义），**不是**从 `board_fund_flow` 周期表读取；`board_fund_flow` 的 3日/5日/10日/20日周期（含 `net_ratio` 阶段涨跌幅）是资金面数据、本期页面只展示「即时」、不参与价格排序（需求 §7.1「资金流 3/5/10/20 日数据继续采集但不受主排序控件控制」）。严禁把资金流周期表的 `net_ratio` 当价格涨幅用。
- **权限策略**：`sectors:view` 进 `BUSINESS_RESOURCE_CODES`（业务授权，非登录基线）；后端 `require_perm('sectors:view')` 守卫；采集/候选操作 system-only（`data-task:manage` / `data-quality:view|fix`）；既有库一次性回填授权 + 同事务 bump `perm_ver`（marker 幂等）。
- **兼容策略**：`board_bar` 存原值不套复权链；`stock_basic.concept` 不写；新增表与 seed 全部幂等；`ThsBoardSource` 限速 ≥1s/次 + 分批断点。
- **关键取舍**：资金流无稳定代码时按名称匹配，未匹配写质检不伪造代码；同日多候选冻结（表达式唯一索引兜底 + 事务内二次校验返回稳定错误码）；候选应用同步短事务不起异步任务。
- **表达式唯一索引可行性（2026-08-09 实测复核）**：`CREATE UNIQUE INDEX ... (CASE WHEN status='applied' THEN 1 ELSE NULL END)` 在本机 DuckDB 1.5.3 实测**创建成功且强制生效**——INSERT 与 UPDATE 路径均拦截第二条 applied（ConstraintException），多条 pending/discarded（表达式值为 NULL）同日并存，跨日/跨板块 applied 互不影响。设计可行，T3 单测作为版本回归验证点。**降级方案（仅当部署环境 DuckDB 版本拒绝表达式索引时启用）**：退化为纯事务内先查后写 + 明确接受无 DB 层兜底（并在此记录版本事实）；生成列 + UNIQUE 约束、部分索引（WHERE）两条替代路径经实测分别为 BinderException/NotImplementedException 不支持，不可用。

### 前端页面设计闭环

#### 页面定位

- 页面类型：P1 板块行情列表页（新增，list 原型）；P2 板块详情页（新增，detail 原型）；P3 数据质量页（更新页面，仅新增候选操作列，无布局重排）。
- 用户主流程：列表筛选/排序/搜索 → 点板块名进详情 → 看指数走势与成分股 → 跳个股行情；系统管理员在数据质量页确认/丢弃候选。
- 是否新页面：P1/P2 是；P3 改造已有页面（QualityView）。
- 是否改造已有页面：P3 是（仅表格列与操作扩展）。

#### 布局选型

- P1 选用原型：`list`。理由：单主表 + 顶部筛选 action 区，与 StocksView 同构；原型文件 `prototypes/sector-board.html` 即按 list 结构绘制。不需要新增布局原型。
- P2 选用原型：`detail`。理由：摘要区 + 主区 detail（图表 + 嵌套成分股表），与 StockDetailView 同构；原型文件 `prototypes/sector-detail.html`。不需要新增布局原型。
- 新增运行时复用组件：无（全复用 `AppDataTable`/`AppTableColumn`/`AppPagination`/`AppStateBlock`/`AppRowActions`/`PageSegmented`/`PageSettingsDrawer`/`TradeDatePicker`/`LayoutHost`/`usePageSettings`/`useEChartsTheme`；走势图为本页业务组件内 ECharts 实例，不沉淀通用组件）。
- 配置化接入：`sectors`、`sectors-detail` 两个 pageKey 进 pageRegistry；组件字段经 `componentMeta`/`consumedComponentFields`/`componentValueOf` 承载；业务偏好走 `usePageSettings`。

#### Slot 与组件设计

P1 `sectors`（list，`responsiveProfile: 'single-column'`，`minWidth=0`）：

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action | filter-bar | filter-bar | 否 | 不滚动 | 否 | TradeDatePicker + 概念/行业 PageSegmented + 主排序周期 PageSegmented + 名称搜索框（`el-input` 防抖） |
| main | table | data-table | 是 | 表体内部滚动 | 否 | 板块列表主表 + AppPagination |
| overlay | settings | settings-drawer | 否 | 抽屉内滚动 | 否 | 页面设置（布局/组件设置/业务选项） |

P2 `sectors-detail`（detail，`responsiveProfile: 'single-column'`）：

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action | toolbar | toolbar | 否 | 不滚动 | 否 | 面包屑返回 + 页面设置入口 |
| main | detail | detail | 是 | 低高度时主内容区整体滚动兜底 | 否 | 摘要区 + 走势图 + 成分股表容器 |
| main | memberTable | data-table（parentId: detail，order: 2） | 否 | 表体内部滚动 | 否 | 成分股表（嵌套 slot，对齐 groupTable 模式） |
| overlay | settings | settings-drawer | 否 | 抽屉内滚动 | 否 | 页面设置（图表周期业务选项 + memberTable 组件设置） |

#### 四态反馈设计

| 状态 | 页面 / 组件处理 | 复用组件 / 样式 | 结论 |
|---|---|---|---|
| ready / 价值态 | P1 主表 + 分页；P2 摘要 + 图表 + 成分股表 | AppDataTable / ECharts | 默认态 |
| loading / 加载态 | P1 `v-loading` 覆盖主表；P2 整页骨架/图表 loading | AppDataTable / 图表四态 | 符合 DESIGN §4 |
| empty / 空态 | P1「暂无板块数据，请先在数据采集页运行板块采集」；P2 图表/成分股表空态；板块不存在 → error 态「板块不存在或数据未采集」 | AppDataTable 空态 / AppStateBlock | 符合 DESIGN §4 |
| error / 异常态 | AppStateBlock error + 重试 | AppStateBlock | 符合 DESIGN §4 |

- 权限态：无 `sectors:view` → AppStateBlock permission 无权态（菜单不可见 + 路由 fail-closed + 接口 403）；无 `stocks:view` → 成分股名不可点 + hover 提示「无个股行情查看权限」。
- 自检结论：四态互斥，空态/错误态/重试入口均按 DESIGN 处理，无例外。

#### 控件与操作规范

- 主操作：P1 列头排序/翻页/点板块名；P2 周期切换/日期控件/翻页/返回；P3 行操作「确认应用」「丢弃」（`AppRowActions`，异步 `:loading`）。
- 纯图标操作：本期无新增纯图标操作；如有图标按钮一律 `AppIconButton`。
- 专用原生按钮例外：无。
- 自检结论：无随机按钮样式，无 Unicode 图标。

#### 字体与间距规范

- 新增或复用的语义类 / token：涨跌幅用 `--market-up/down-color`，数字右对齐；统计卡复用 DESIGN 统计项语义；不新增 token。
- 排版或间距特例：无。
- 自检结论：不使用负字距、不以 vw 缩放字号。

#### 主题底色规范

- 复用 DESIGN 颜色角色；图表经 `useEChartsTheme()` 消费统一主题；不新增色板。

### 4.1 页面 P1（板块行情列表页）技术实现

- 原型文件：`prototypes/sector-board.html`。承接区域：顶部 action 筛选区（概念/行业分段 → 日期控件 → 主排序周期分段 → 搜索框）、主表（列 = 名称 link/成分股数/上涨/下跌家数/今日/5日/10日/20日涨幅/即时净流入 + 数据日/领涨股）、表体内部滚动 + 分页条、设置抽屉（布局/每页条数/默认排序/默认类型/默认周期/列显隐/恢复默认）、四态演示态（数据/空/错误/加载）。
- 原型与需求差异说明：
  1. 原型用「上涨家数」「数据日」独立列展示，正式实现按需求 §7.1 合并为「上涨/下跌家数」列与「即时净流入(含数据日期)」列提示，列序以需求 §7.1.2 为准。
  2. **列表页 `pageSize` 合法值冲突**：原型 `sector-board.html` 设置抽屉每页条数选项为 **10/20/30/50**（含 30），需求 §7.1 配置表为 **10/20/50**（无 30）。正式实现按**需求口径 10/20/50**（列表页与详情页 10/20/30/50 不同口径，已在 §4.1 主表行加粗声明）；此取舍为计划 vs 原型的显式冲突，**按需求为准**，实施时无需再向用户确认（需求为当前事实源），但须在开发留痕中记录此差异。
  3. **领涨股取数来源**：原型列「领涨股及涨幅」，默认口径取 `board_fund_flow.leader_stock/leader_pct`（与即时净流入同一 `(snapshot_date, period='即时')` 行）；无资金流板块该列「—」（与需求 §6.2 空值处理一致，原型数据态不区分该场景）。**该口径在资金流日期 ≠ 涨幅日期时「展示资金流日领涨股」是否可接受为待确认项（见 §10.3）**。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 板块列表筛选（7.1.1） | R7、R10 | 默认概念板块 + 今日涨幅降序；切类型/周期/排序/搜索（≤50 字符防抖）；周期切换同步主排序字段；非涨幅排序取消周期高亮且 URL 不保留无效 period | action 区 `TradeDatePicker` + 两个 `PageSegmented` + `el-input` 防抖；筛选态写 URL query（`type/period/sort/order/keyword/page`）；偏好优先级 URL query > 已保存偏好 > 默认值 | SectorsView.vue、AppControlRow、PageSegmented、TradeDatePicker、usePageSettings | `GET /api/sectors`（白名单参数） | 加载 `v-loading`；空态引导去采集页；错误 AppStateBlock 重试；无权限 permission 态 | T11 |
| 板块列表主表（7.1.2） | R7 | 列头排序（涨跌幅列头同步周期控件）、服务端分页、仅点板块名进详情、列显隐 | AppDataTable growMain + AppTableColumn（语义角色，不声明宽度）+ AppPagination；`defaultSort/pageSize/hiddenColumns` 走 `componentValueOf('table', ...)`；**pageSize 合法值 10/20/50（列表页口径，与详情页 10/20/30/50 不同，实施以需求 §7.1 配置表为准）**；仅名称列渲染 router-link（携带来源 query 进详情 URL） | AppDataTable、AppTableColumn、AppPagination、pageRegistry `sectors` | `GET /api/sectors` | 空值列显示「—」；资金流列标注数据日期；分页越界回落 | T11 |

组件资产闭环（P1）：

| 页面/区域 | 运行时复用组件 | 布局或配置组件种类 | 组件配置字段/页面注册 | 设计规范或组件清单更新 | 真实消费与验证 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| P1 全页 | 复用 | 复用 | 新增 `sectors` pageKey 注册（action+main+overlay 自动补登） | 是：DESIGN.md `page-registry` 区块补一行 | SectorsView 真实消费 + pageRegistry.spec.ts 契约测试 | T11、T15 |

### 4.2 页面 P2（板块详情页）技术实现

- 原型文件：`prototypes/sector-detail.html`。承接区域：面包屑（板块行情 / 板块名 + 页面设置入口）、摘要区（名称 + 类型标签 + 统计行：成分股数/今日涨跌幅/上涨/下跌家数/今日净流入(含数据日)/领涨股及涨幅，无来源/代码副标题）、走势图工具条（日期控件 + 周期分段：近1月/近3月/近半年/近1年，默认近3月）、图表区（正式实现为 ECharts）、成分股表（代码/名称/现价/涨跌幅/换手，涨跌幅与代码列可排序，统一分页无 TopN）、设置抽屉（每页条数/默认排序/列显隐/图表周期/恢复默认）、六态演示（数据/空/错误/加载/无权/个股权限开关）、无权 hover tooltip。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 板块摘要卡（7.2.1） | R8、R14 | 名称/类型/成分数/今日涨幅/涨跌家数/即时净流入(含数据日期)/领涨股及涨幅；随路由 code 刷新 | 摘要区（DESIGN 统计项语义）；涨幅与净流入分别标注各自数据日期（board_bar 最近交易日 / fund_flow 最近 snapshot_date）；**领涨股默认取资金流同 snapshot 行 leader_stock（口径待确认，见 §10.3）** | SectorDetailView.vue | `GET /api/sectors/{code}` | 板块不存在 → error 态「板块不存在或数据未采集」；空值显示「—」 | T12 |
| 板块指数走势图（7.2.2） | R8、R11 | 默认近 3 月收盘线，原始连续指数；周期切换重新拉数；日期控件默认最新交易日可回看 | ECharts 线图（`useEChartsTheme()`，不引入新图表框架）；周期分段 + TradeDatePicker；`chartPeriod` 业务偏好走 `usePageSettings('sectors-detail', { chartPeriod: '3m' })`，非法值回落 3m | SectorDetailView.vue、ECharts、PageSegmented、TradeDatePicker | `GET /api/sectors/{code}/bars` | 图表 loading/空态/error 复用图表四态 | T12 |
| 成分股表（7.2.3） | R8、R9、R13 | 统一分页（默认 20，抽屉可配 10/20/30/50，**与列表页 10/20/50 口径不同**）；列头排序（默认涨跌幅降序）；有 `stocks:view` 点行跳 `/stocks/:code`，无权限行禁用 + hover 提示 | AppDataTable（嵌套 slot `memberTable`，parentId=detail）+ AppPagination；`componentValueOf('memberTable', ...)` 消费 pageSize/defaultSort/hiddenColumns；`hasPermission(auth, 'stocks:view')` 判定名称可点性，无权限渲染不可点文本 + tooltip | AppDataTable、AppPagination、pageRegistry `sectors-detail` | `GET /api/sectors/{code}/members?page=&size=`（size 默认 20） | 空态/错误重试；直接访问 `/stocks/:code` 路由守卫 fail-closed（现有机制） | T12 |
| 返回列表保留筛选态（R8） | R8 | 面包屑/返回按钮始终 `router.replace` 显式跳列表并带白名单校验后的来源 query；无/非法来源 query 落默认；不使用 `router.back()`；浏览器原生后退按 history 还原 | 列表 URL query 承载筛选态；进详情时来源 query 透传进详情 URL；返回前白名单校验（`type/period/sort/order/keyword/page`） | vue-router、SectorsView/SectorDetailView | - | 非法 query 逐字段丢弃落默认 | T12 |

组件资产闭环（P2）：

| 页面/区域 | 运行时复用组件 | 布局或配置组件种类 | 组件配置字段/页面注册 | 设计规范或组件清单更新 | 真实消费与验证 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| P2 全页 | 复用（走势图为本页业务组件内 ECharts 实例） | 复用 | 新增 `sectors-detail` pageKey 注册 + `memberTable` 嵌套 slot（componentMeta sortFields=pct/code；consumedComponentFields=pageSize/defaultSort/hiddenColumns） | 是：DESIGN.md `page-registry` 区块补一行 | SectorDetailView 真实消费 + pageRegistry.spec.ts 契约测试 | T12、T15 |

### 4.3 页面 P3（数据质量页，更新页面）技术实现

- 原型文件：不生成原型（需求明确：复用现有质检页结构，仅新增候选操作列，无布局重排；代码调研确认 QualityView 现有 AppDataTable + AppRowActions 结构可直接扩展，无复杂布局歧义，继承需求判断）。
- 变更区域：`member_surge_shrink` 问题行的候选 diff 行内展示（板块名/快照日/新增/退出/净变化数，可展开明细）+ 操作列两个动作；保留区域：现有筛选、分页、其他 issue 类型行不变。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 候选确认/丢弃 | R2、R12 | `member_surge_shrink` 待处理行提供「确认应用」「丢弃」；`apply_allowed=false` 禁用「确认应用」+ 提示「本期不支持同日替换」；确认弹窗展示 diff 摘要（含候选 `codes_json` 全量代码可展开明细）；完成后刷新列表 | QualityView.vue 扩展：候选经 `issue_id` 附着问题行内（不新增独立页面）；AppRowActions 两动作 + `:loading`；确认弹窗复用项目弹窗模式 | QualityView.vue、AppRowActions | `GET /api/data/board-candidates`（`status/board_type/page/size`）、`POST .../{id}/apply`、`POST .../{id}/discard` | 409 按 `error_code` 区分提示（`already_processed` → 「候选已被应用/丢弃」并刷新；`same_day_snapshot_already_applied` → 「本期不支持同日替换」并刷新）；`duckdb_write_unavailable` → 软失败提示不刷新；加载 v-loading、空态、错误 AppStateBlock 重试 | T13 |

组件资产闭环（P3）：复用现有质检页全部组件；不新增 pageKey、不新增组件种类、不新增配置字段；设计规范无需更新（无布局变化）；真实消费验证归 T13/T15。

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R1 | 板块字典采集（概念+行业并集）落 `board_dict` | ThsBoardSource.get_board_dict + 两阶段字典 seed/资金流并集补充 + 能力字段收口 + app_code(clid) 抓取 | T2、T4 | 待开始 | 一致 | |
| 必须实现 | R2 | 成分股快照采集 + 候选恢复闭环 | 快照 diff（[in_date,out_date)）+ 不完整快照保护 + payload_hash 幂等 + 候选表三事务 + 同日冻结 + best-effort 审计 + 候选接口 + 质检页操作 + **member_count 双应用路径刷新（T4 完整快照 + T9 候选应用）** | T2、T3、T4、T9、T13 | 待开始 | 一致（评审修订） | **member_count 应用路径已补入 T9 事务②**；「被拦截未应用候选不改该值」由 T9 集成测试断言 |
| 必须实现 | R3 | 板块指数采集落 `board_bar`（原值） | get_board_bar + 幂等 upsert + 5 年回填/每日增量 | T2、T4、T6 | 待开始 | 一致 | |
| 必须实现 | R4 | 板块资金流采集落 `board_fund_flow` | 概念+行业全周期采集 + 并集映射（未匹配写质检不伪造代码） | T2、T4 | 待开始 | 一致 | |
| 必须实现 | R5 | 板块采集异步任务（`board` 进任务中心） | TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES 注册 + `_h_board` + checkpoint=board_code + 任务中文标签 | T5 | 待开始 | 一致 | |
| 必须实现 | R6 | 板块维度注册 + 数据概览可见 | `_DIMENSION_SEED` 加 `board` 维度行（tables=4 表） | T3 | 待开始 | 一致 | |
| 必须实现 | R7 | 板块行情列表页 `/sectors` | SectorsView（筛选/主表/分页/列显隐/主排序周期语义）+ `/api/sectors` | T8、T11 | 待开始 | 一致 | |
| 必须实现 | R8 | 板块详情页 `/sectors/:code` + 返回保留筛选态 | SectorDetailView（摘要/走势图/成分股表）+ URL query 筛选态承载与显式返回 + 详情 3 接口 | T8、T12 | 待开始 | 一致 | |
| 必须实现 | R9 | 成分股跳转个股详情（权限感知） | `hasPermission('stocks:view')` 行可点性 + 禁用态 hover 提示 + 直接访问 fail-closed 验证 | T12、T15 | 待开始 | 一致 | |
| 必须实现 | R10 | 板块搜索 | 自由文本搜索框（el-input 防抖）+ 服务端 `keyword` 参数 + 无结果空态 | T8、T11 | 待开始 | 一致 | |
| 可选增强 | R11 | 走势图周期切换（1月/3月/半年/1年） | 周期分段 + bars 接口区间参数 + `chartPeriod` 偏好 | T12 | 待开始 | 一致 | 本次纳入 |
| 可选增强 | R12 | 板块维度质检（成分数波动/指数缺口） | data_report 新增板块规则 + 阈值配置化（Settings 模型/YAML/CONFIG_GROUPS 三环）+ issue 状态流转（候选跳过 fixing） | T4、T7、T13 | 待开始 | 一致 | 本次纳入 |
| 可选增强 | R13 | 详情页成分股统一分页 | members 接口服务端分页 + AppPagination + pageSize 组件字段 | T8、T12 | 待开始 | 一致 | 本次纳入 |
| 可选增强 | R14 | 详情页资金流统计卡 | 摘要卡即时净流入（最新 snapshot_date period=即时） | T8、T12 | 待开始 | 一致 | 本次纳入 |
| 必须实现 | R21 | 采集流程集成（daily/回填/增量/断点/失败隔离） | DailyPipeline 加 `board: bool = True` 步骤 + CLI `board --backfill/--update` + `--skip-board` + 失败清单与部分失败降级 + 参数化测试矩阵 | T5、T6 | 待开始 | 一致 | |
| 必须实现 | R22 | 页面/RBAC 接入 | 菜单/资源 seed + `sectors:view` 进 BUSINESS_RESOURCE_CODES + 既有库回填 + bump perm_ver + 路由守卫 + pageRegistry 登记 | T10a、T10b、T11、T12、T14 | 待开始 | 一致 | seed/回填拆分为 T10a（常量+seed）与 T10b（回填 SQL+权限测试） |
| 必须实现 | R23 | 页面配置闭环 | 两页 usePageSettings + 组件字段（pageSize/defaultSort/hiddenColumns）保存/读取/消费/回退 + 参数化矩阵 + 构建/布局/视口验收 | T11、T12、T14、T15 | 待开始 | 一致 | |
| 暂不实现 | R15 | 地域/风格板块 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 第一期只做概念+行业 |
| 暂不实现 | R16 | 资金流历史趋势图 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本期只做统计卡数字 |
| 暂不实现 | R17 | 题材联动图谱/重叠分析 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 独立后续需求 |
| 暂不实现 | R18 | 东财指数交叉验证 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 东财源不稳 |
| 暂不实现 | R19 | 板块成分作为筛选/回测条件 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 需筛选引擎+回测扩展 |
| 暂不实现 | R20 | 板块强弱热力图 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 需图表组件扩展 |
| 暂不实现 | R24 | 审计可靠性提升 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本期审计 best-effort |
| 暂不实现 | R25 | 同日候选替换 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本期冻结每日最多一个 applied |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：数据/权限/接口契约冻结

- 状态：待开始
- 依赖：无（需求已确认无阻塞项）
- 涉及文件/模块：本 plan.md §4/§7；需求文档 §6
- 目标：冻结 5 表 DDL 字段与约束（含 payload_hash CHECK、表达式唯一索引）、`/api/sectors*` 与候选接口契约、`sectors:view` 权限 seed 与回填方案、R12 阈值配置项。
- 操作：以本计划 §4 技术方案为契约文本，开发前对照需求 §6.1/§6.2 逐项核对；发现与代码现状冲突时回到用户确认。
- 产出：评审通过的契约（本计划章节）。
- 影响范围：后续全部任务。
- 边界与异常：契约变更需回到本任务修订。
- 验证方式：计划评审确认。
- 完成标准：契约无待确认阻塞项。
- 实际落地情况：已核验（2026-08-09 T1 执行）——5 表 DDL/接口/权限/配置契约逐项对照代码现状成立；补 1 处契约：R12 阈值需 `Settings` 模型加子模型字段（Pydantic default_factory），与 settings.yaml 节、CONFIG_GROUPS 白名单三者配套（见 §7.4）。

### 6.2 任务 T2：`ThsBoardSource` 数据源适配器

- 状态：待开始
- 依赖：T1
- 涉及文件/模块：`backend/datasource/ths_board.py`（新增，文件名对齐 research.md 附录建议结构）、`backend/datasource/base.py`（仅复用装饰器）、`requirements.txt`/`pyproject.toml`（显式声明 `py_mini_racer`）、`backend/tests/test_ths_board_source.py`（新增）
- 目标：封装同花顺板块取数：字典（概念/行业）、成分股（AJAX 翻页 + v cookie + 两种排序策略取多者）、指数日线、资金流（概念/行业 × 5 周期）、app_code(clid) 详情页抓取。
- 操作：新建**独立普通类** `ThsBoardSource`（**不继承 `DataSource`、不修改该抽象**——`DataSource` 的 5 个抽象方法全是个股时间序列接口，板块关系型数据硬塞会破坏抽象一致性；此口径承接 research.md 附录《同花顺板块适配器封装决策》与 requirement-closure.md §189 的已确认决策）；仅复用 base.py 的 `rate_limited(≥1s)`/`with_retry` 装饰器；由 `IngestionService` 直接持有实例，不进 `_source_for` 选源链。v cookie 经 `py_mini_racer` 执行 akshare 打包的 `ths.js` 生成（本机 akshare 1.18.64 实测含 `akshare/data/ths.js`、`akshare/stock_feature/ths.js`），401 时刷新 cookie 重试；翻页走路径参数 `page/N/ajax/1/`；分页完整性检测（缺页/请求失败标记不完整）；请求超时注入。
- 产出：适配器 + 单测（mock HTTP：v cookie 生成/401 刷新/翻页/两种排序取多者/不完整快照标记/资金流解析）。
- 影响范围：采集层（R1-R4 数据源）。
- 边界与异常：不调用 akshare 板块公开函数；不继承 `DataSource`、不并入 `AKShareSource`（research 附录备选方案已明确否决）；限流不低于 1s/次。
- 验证方式：`python -m pytest backend/tests/test_ths_board_source.py -q`。
- 完成标准：单测全绿；实测可拉通一个概念板块全部分页（人工冒烟，只读外部源不涉及 DuckDB 锁）。
- 实际落地情况：已实施（2026-08-09 T2 执行）——`backend/datasource/ths_board.py` 新建（独立普通类，复用 `rate_limited`/`with_retry`，经 `importlib.resources` 读 akshare 打包 `ths.js` 生成 v cookie）；`requirements.txt`/`pyproject.toml` 显式声明 `py_mini_racer>=0.8`；16 个单测全绿（mock HTTP：v cookie/401 刷新/翻页/两种排序取并集/登录墙截断标不完整/字典全量合并/指数解析/资金流解析）；真实冒烟通过：概念字典 375 / 行业 90 / AI PC 概念成分 50 / 半导体行业成分 100 / 指数日线 / 概念资金流 387 / 行业资金流 90。**实测发现 1：成分股翻页第 6 页起必触发同花顺登录墙**（HTTP 200 但返回 `upass...login` 跳转壳，单发第 6 页同样命中，非频率触发）——单板块最多稳定取 5 页（概念 50 只/行业 100 只），适配器对登录墙页标记 `complete=False`（数据可能被截断，供采集层走 R2 不完整快照保护），见 §10.1 新增风险。**实测发现 2：概念字典 = 分类页 351 ∪ `gn/index` 前 3 页净增 24 = 375**，适配器已按此合并（登录墙即停，比 akshare 空翻 39 页更省）。**实测发现 3（登录态解除登录墙，2026-08-09 用户提供浏览器登录 cookie 实测）**：登录态下详情页第 6 页正常返回数据（半导体完整 120 只），登录墙解除；代价是数据中心 IP 连续请求触发动态风控（401/空页），适配器新增 `login_cookie` 参数 + `AI_STOCKS_THS_COOKIE`/`_FILE` 环境变量支持（浏览器登录后复制，不硬编码不入库），限速默认提至 ≥2s/次。

### 6.3 任务 T3：DuckDB 5 表 DDL + 板块维度注册

- 状态：待开始
- 依赖：T1
- 涉及文件/模块：[ddl.py](../../backend/storage/ddl.py)（5 表 + `_DIMENSION_SEED` 加 `board` 行）、`backend/tests/`（DDL 幂等与约束测试）
- 目标：落地 `board_dict`/`board_member`/`board_bar`/`board_fund_flow`/`board_member_candidate`（字段按需求 §6.1，含 `payload_hash VARCHAR(64) CHECK (regexp_full_match(payload_hash, '[0-9a-f]{64}'))`、候选唯一约束 `(board_code, snapshot_date, payload_hash)`、表达式唯一索引 `uq_board_member_candidate_one_applied`）；`board` 维度 status=collected、tables=4 表。
- 操作：按 ddl.py 既有建表模式新增；DDL 幂等（重复 init 不报错，索引用 `CREATE UNIQUE INDEX IF NOT EXISTS`）；维度 seed 幂等。表达式唯一索引已于 2026-08-09 在 DuckDB 1.5.3 实测可行（含 UPDATE 路径强制），本任务单测作为版本回归验证点；若目标环境 DuckDB 版本拒绝该索引，按 §4「降级方案」执行（纯事务内先查后写 + 记录无 DB 层兜底），并在本任务「实际落地情况」记录版本事实。
- 产出：DDL + 单测（建表幂等、CHECK 拒绝大写/63/65 位/Base64、表达式唯一索引允许同日多 pending/discarded 但拒绝第二条 applied——INSERT 与 UPDATE 两路径都要测、维度行存在）。
- 影响范围：DuckDB schema；数据概览「数据资产表」新增一行。
- 边界与异常：无既有数据迁移（全新表）。
- 验证方式：单测 + 启动后数据概览接口可见 board 维度。
- 完成标准：5 表创建成功、约束生效、维度注册可见。
- 实际落地情况：已实施（2026-08-09 T3 执行）——`backend/storage/ddl.py` 新增 `M_BOARD_TABLES`（5 表：board_dict/board_member/board_bar/board_fund_flow/board_member_candidate，含 payload_hash CHECK `regexp_full_match`、候选唯一约束、表达式唯一索引 `uq_board_member_candidate_one_applied`）+ `_DIMENSION_SEED` 加 board 行 + `init_db` 注册；`backend/tests/test_ddl.py` 新增 7 个板块用例（建表幂等/维度行/CHECK 拒非法/同日同 hash 唯一/表达式索引 INSERT+UPDATE 两路径拦截/跨板块跨日 applied/双表 PK），共 17 用例全绿。**实测确认**：DuckDB 1.5.3 多语句 execute（表+索引）OK、表达式唯一索引 INSERT 与 UPDATE 两路径均拦截第二条 applied、pending/discarded 同日并存、跨日/跨板块 applied 互不影响（与 §4 支柱一致）；DuckDBClient `execute` 异常后 `_conn=None` 重建连接（:memory: 重建即空库，文件库不受影响），T9 事务需注意约束冲突后连接重建语义。

### 6.4 任务 T4：板块采集服务（字典/成分快照/指数/资金流 + 候选保存）

- 状态：待开始
- 依赖：T2、T3
- 涉及文件/模块：`backend/services/board_ingest.py`（新增，或并入 ingest.py 按既有分层取舍）、`backend/services/ingest.py`（`ingest_board(ctx)` 编排）、[duckdb_client.py](../../backend/storage/duckdb_client.py)（**新增 `transaction()` 上下文管理器**）、`backend/tests/test_board_ingest*.py`（新增）
- 目标：实现 R1-R4 采集逻辑与 R2 候选保存（原子事务①）。
- 操作：
  1. 字典两阶段：概念/行业字典 upsert（阶段一）→ 资金流并集补充 + `has_fund_flow`（阶段二）→ 能力字段与 `last_seen_at` 收口、`member_count` 在最近完整快照应用后刷新。
  2. 成分快照：逐板块 `get_board_members` → 完整性判定（缺页/失败/波动超 R12 阈值）→ 完整快照 diff 落库（`[in_date, out_date)`）+ 刷新 `member_count`/`member_history_start_date`（**仅「已应用」路径刷新，T4 负责完整快照直接落库路径，T9 负责候选确认应用路径**）；被拦截快照 → 计算 `payload_hash`（SHA-256，UTF-8，小写 hex 64，归一化代码 set+sorted）→ 同 hash 幂等四态 → 同一 DuckDB 事务写 `board_member_candidate` + `data_quality_issue`（open，fix_task_id=NULL）。
  3. 指数：幂等 upsert 原值；资金流：全周期 upsert + 名称匹配映射、未匹配写质检不伪造代码；净额=流入-流出校验。
  4. 单板块失败跳过记日志不中断，失败板块进入清单（供 T6）。
  5. `DuckDBClient.transaction()`：现有 `execute()` 按调用持 RLock，多语句 BEGIN..COMMIT 块之间会被其他线程 SQL 插入（破坏原子性）；新增上下文管理器在整个事务块内持 RLock，候选保存事务①与 T9 应用/丢弃事务②③统一走它。**写锁冲突识别机制（T4 与 T9 共用，2026-08-09 实测定稿）**：DuckDB 写锁是文件锁，跨进程冲突**立即失败**（实测 0.006s 抛 `IOException: Could not set lock on file ... Conflicting lock is held`），本机 DuckDB 1.5.3 **无锁等待配置**（`SET duckdb_max_lock_wait_time` 抛 `CatalogException: unrecognized configuration parameter`，已实测）；因此不设置任何锁等待超时，识别完全靠**异常消息关键字归类**——`duckdb_client` 的 `except Exception` 会把 connect/execute 抛的 IOException 包进 `StorageError`（实测消息含 "Could not set lock ... Conflicting lock"），`transaction()` 异常包装层匹配 `lock`/`Cannot open`/`Another client`/`busy` 关键字 → 归类为软失败 `duckdb_write_unavailable`，其余按普通 `StorageError` 500。**连接恢复语义（2026-08-09 实测，无需显式释放）**：写模式 connect 即获文件锁，冲突只发生在 connect 阶段（无「连接已建立后执行语句才冲突」的中间态）；`conn` property 仅在 connect 成功后赋值 `self._conn`，connect 抛异常时 `_conn` 保持 `None`，`execute/query_df` 的 `self._conn=None` 为幂等无害操作，`close()` 在 `_conn is None` 时跳过——锁释放后同一实例重试即自动重建连接恢复（实测 0.02s 成功），**无需显式释放连接**；`transaction()` 仅做关键字归类，不添加连接释放逻辑。现有同步短写先例（data_admin.py quality_reset/ignore）为单语句不受影响。
- 产出：采集服务 + `transaction()` 助手 + 单测（diff 区间语义、不完整快照不执行退出 diff、payload_hash 规范化与非法格式、同日多候选冻结、资金流映射与未匹配质检、member_count 刷新时机——**完整快照路径刷新、被拦截未应用候选不刷新、T9 应用后刷新（跨事务职责在 T9 单测断言）**、事务原子性——中途失败整体回滚、**跨进程写锁冲突归类 `duckdb_write_unavailable` 且锁释放后重试可恢复**）。
- 影响范围：DuckDB 5 表写入；`data_quality_issue` 新增 issue 类型 `member_surge_shrink`。
- 边界与异常：快照日期 = Asia/Shanghai 实际成功采集日期；成分股代码补交易所后缀对齐 `stock_basic.code`。
- 验证方式：`python -m pytest backend/tests/test_board_ingest*.py -q`（跑前先 `./start.sh status` 确认后端已停，结束按原状态恢复，遵守 DuckDB 锁规则）。
- 完成标准：R1-R4 验收标准中可用单测覆盖的部分全绿。
- 实际落地情况：已实施（2026-08-09 T4 执行）——`backend/services/board_ingest.py` 新建 `BoardIngestService`（字典两阶段 upsert / 成分快照 diff [in_date,out_date) / 候选保存事务① / 指数幂等 upsert / 资金流名称映射+未匹配写质检）；`backend/storage/duckdb_client.py` 新增 `transaction()` 上下文管理器（RLock 跨 BEGIN..COMMIT + 写锁关键字归类 `_LOCK_CONFLICT_RE` + 异常回滚 + 连接重建语义）；`backend/services/ingest.py` 新增 `ingest_board` 编排（单步骤失败隔离返回失败清单）。10 个单测全绿（diff 区间/不完整快照不退出 diff/payload_hash 规范化与幂等四态/波动拦截/member_count 刷新时机/事务原子性回滚/写锁关键字归类/资金流映射与未匹配质检）。`transaction()` 文件库实测：提交成功、中途失败整体回滚、连接重建后表仍在。

### 6.5 任务 T5：`board` 异步任务类型注册

- 状态：待开始
- 依赖：T4
- 涉及文件/模块：[async_task.py](../../backend/services/async_task.py)（TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES + `_h_board`）、[data.ts](../../frontend/src/api/data.ts)（任务类型中文标签「板块采集」）、`backend/tests/`（任务注册/取消/续跑测试）
- 目标：`board` 任务可创建/看进度/取消/续跑，checkpoint 粒度 board_code，断点续跑从上次 board_code 继续；纳入 DuckDB 写任务互斥。
- 操作：按现有任务类型同款模式注册；handler 调 `ingest_board(ctx)`；进度按 board_code 推进。**命名空间边界声明**：任务类型 `board` 与既有「每日榜单」的 `/board` 路由、`board:view`/`board:compute` 资源码、`board_bar` 等表名处于同一语义空间，但技术命名空间不同（task type vs resource code vs 表名），不构成功能冲突；代码/日志/运维中注意区分——任务类型用 `task.type='board'`，资源码用 `board:view`（榜单），接口用 `/api/sectors*`（板块行情），表用 `board_dict/board_member/...`（板块数据）。前端任务中文标签「板块采集」避免与「每日榜单」资源名混淆。
- 产出：任务注册 + 单测 + 前端标签。
- 影响范围：任务中心新增任务类型；无既有任务行为变化。
- 边界与异常：复用现有失败/中断/续跑机制。
- 验证方式：单测 + 任务中心页面创建板块采集任务人工确认（T15 回归覆盖）。
- 完成标准：R5 验收通过。
- 实际落地情况：已实施（2026-08-09 T5 执行）——`backend/services/async_task.py` 注册 `board` 任务类型（TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES + `_h_board` handler，checkpoint 粒度 board_code，done_codes 过滤续跑跳过已完成板块）；`frontend/src/api/data.ts` 加 `board` 到 TaskType 联合与 TASK_LABEL「板块采集」。4 个单测全绿（注册四要素/创建并后台执行/写任务互斥/续跑跳过 done_codes）。

### 6.6 任务 T6：CLI `board` 命令族 + daily 流程集成

- 状态：待开始
- 依赖：T4、T5
- 涉及文件/模块：[cli.py](../../backend/cli.py)（`board --backfill` / `board --update` / `daily --skip-board`）、[pipeline.py](../../backend/services/pipeline.py)（`run(..., board: bool = True)` + 步骤 + total_steps + 失败隔离）、`backend/tests/`（参数化测试矩阵）
- 目标：R21 全部语义落地。
- 操作：`DailyPipeline.run()` 新增 `board: bool = True`；板块步骤在「更新数据」之后顺序执行；`skip_update=True` 仍采集板块；`--skip-board` 跳过；`total_steps` 同步计入；板块步骤失败不提前 return、继续质检等后续步骤，但最终 `ok=false`；单板块失败记录清单并继续，步骤/任务最终标 `failed`，续跑仅重试失败项。
- 产出：CLI/管道改动 + 参数化测试矩阵（`board=True` 默认执行、`skip_update=True` 仍执行、`--skip-board` 确实跳过、板块失败后继续质检、最终状态与失败清单正确、`total_steps` 不出现 `3/2`）。
- 影响范围：每日流程、CLI；既有 `daily` 默认行为变化（新增板块步骤，默认开启）。
- 边界与异常：「不阻塞」= 不中断主流程执行，而非任务整体成功。
- 验证方式：参数化矩阵单测 + CLI 冒烟 `python -m backend.cli board --backfill`（5 表有数据）。
- 完成标准：R21 验收通过。
- 实际落地情况：已实施（2026-08-09 T6 执行）——`backend/services/pipeline.py` `DailyPipeline.run` 新增 `board: bool = True`（板块步骤在更新后顺序执行，`total_steps` 同步计入，`skip_update=True` 仍采集板块，板块失败不提前 return 继续质检但最终 `ok=false`）；`backend/cli.py` 新增 `board` 命令族（`--backfill`/`--update`）与 `daily --skip-board`。4 个参数化测试全绿（board 默认执行 / board=False 跳过 / 板块失败继续质检但 ok=false / total_steps 步骤分段正确）。

### 6.7 任务 T7：板块维度质检规则 + 阈值配置化

- 状态：待开始
- 依赖：T4（候选/issue 写入链路）
- 涉及文件/模块：[data_report.py](../../backend/services/data_report.py)（新增板块扫描规则）、`config/settings.yaml`（阈值基线：`relative_change_ratio=0.5`、`absolute_change_threshold=20`）、[settings.py](../../backend/config/settings.py)（**`Settings` 加 `board_quality` 子模型字段，Pydantic default_factory，T1 契约核验补充**）、`CONFIG_GROUPS` 白名单（PG `app_config` 覆盖，见 §7.4）、[settings.py](../../backend/config/settings.py)（`get_effective_settings()` 消费）、`backend/tests/`（质检规则与配置覆盖测试）
- 目标：R12——成分数异常波动扫描（`threshold = max(absolute, previous*ratio)`，`abs(cur-prev) >= threshold` 触发）与板块指数缺口扫描，写 `data_quality_issue`；候选流程状态流转 `open → resolved | ignored` 跳过 `fixing`。
- 操作：
  1. 复用现有质检扫描框架新增板块维度规则；阈值经配置覆盖层读取。
  2. **issue 判重与收敛策略（明确，承接现有 data_report 收敛模式）**：板块自动扫描类问题沿用现有「扫描前清上轮**未解决**的同类 open 问题 + 已 resolved/ignored 不动」收敛模式（data_report.py:444-447），反复跑不堆积。
  3. **边界（防止误删候选关联 issue）**：收敛 DELETE **只清板块自动扫描类**（如 `board_index_gap`），**绝不清理 `member_surge_shrink` 类 open issue**——`member_surge_shrink` 由采集拦截写入并关联 `pending` 候选，若被自动扫描清除会造成「候选 pending 而 issue 被删」的关联断裂。现有 data_report 收敛按 `issue_type` 集合白名单清理，新增板块自动扫描类型时保持该白名单排除 `member_surge_shrink`；`member_surge_shrink` 的生命周期只由候选事务②③驱动（applied→resolved / discarded→ignored）。
  4. **波动拦截与扫描共用同一阈值判断**（避免双口径）：T4 候选保存与 T7 扫描对「成分数波动」用同一 `threshold` 计算函数（T7 抽公共函数或共享配置消费）。
- 产出：质检规则 + 配置项 + 单测（阈值生效、配置覆盖生效、状态枚举合法流转、**收敛 DELETE 不误删 `member_surge_shrink` open issue、同板块同日同波动扫描不堆积新 issue**）。
- 影响范围：数据质量页出现板块质检问题；配置覆盖层新增白名单项。
- 边界与异常：波动拦截与 T4 候选保存共用同一阈值判断，避免双口径。
- 验证方式：单测 + 配置测试。
- 完成标准：R12 验收标准中扫描/阈值/状态流转部分通过。
- 实际落地情况：待实施

### 6.8 任务 T8：`/api/sectors*` 只读 API + 查询服务

- 状态：待开始
- 依赖：T4（数据来源）；**T10a（常量 + 资源 seed 前置部分）须先行或与 T8 同批交付**——T8 的 403/权限验收隐含依赖 `sectors:view` 进 `BUSINESS_RESOURCE_CODES` 与资源 seed，不可晚于 T8 收尾（T10a 依赖仅 T1，无环）
- 涉及文件/模块：`backend/api/sectors.py`（新增路由）、`backend/services/board_query.py`（新增查询服务）、`backend/main.py`（挂路由）、`backend/tests/test_sectors_api*.py`（新增）
- 目标：4 个只读接口（列表/详情/bars/members）按需求 §6.2 契约要点实现。
- 操作：参数白名单校验（未知参数 400）；`sort_by` 稳定字段码；统计口径（涨幅收盘价对比、历史不足「—」、涨跌家数口径、最新交易日双口径显式返回）；`trade_date` 截面语义；空值「—」；404/400/403；members 服务端分页（size 默认 20）；板块数 <600 单次全查内存合并（双库边界：只读 DuckDB，成分股现价/涨跌幅/换手取个股行情表同库关联）；**涨幅（pct_today/pct_5d/pct_10d/pct_20d）T8 查询时从 `board_bar` 实时计算，不从资金流周期表读（双口径边界见 §4）**；**领涨股默认取 `board_fund_flow.leader_stock/leader_pct` 且与「即时净流入」同一 `(snapshot_date, period='即时')` 行（该表每周期行各带 leader_stock/leader_pct，见需求 §6.1 表设计；口径待确认，见 §10.3）——无资金流数据的板块领涨股列显示「—」（空值口径，不走「当日成分股涨幅第一」另行计算，避免口径分裂）**；列表只展示 `has_members` 或 `has_bar` 为 true 的板块（承接需求 §2.5 并集字典展示口径）。
- 产出：接口 + 服务 + 单测/接口测试（口径与 DuckDB 对账）。
- 影响范围：新增只读接口，无既有接口变化。
- 边界与异常：不跨库 JOIN；资金流数据日期与涨幅数据日期分别返回。
- 验证方式：接口测试 + 与 DuckDB 抽验对账（涨幅/净流入/成分数）。
- 完成标准：R7-R10、R13、R14 的数据层验收通过。
- 实际落地情况：待实施

### 6.9 任务 T9：候选成分快照接口（查询/确认应用/丢弃）

- 状态：待开始
- 依赖：T4（候选表写入）、T7（issue 状态流转）
- 涉及文件/模块：`backend/api/data_admin.py` 或新增 `backend/api/board_candidates.py`（按既有 data 域分层取舍）、`backend/services/`（候选应用/丢弃服务 + best-effort 审计复用 `audit_service`，`resource_code='data-quality:fix'`）、`backend/tests/`（接口与事务测试）
- 目标：R2 恢复闭环 API——`GET /api/data/board-candidates`（默认 pending，可 status 过滤，字段含 `apply_allowed/block_reason`）、`POST .../{candidate_id}/apply`（事务② + 事务内二次校验）、`POST .../{candidate_id}/discard`（事务③）。
- 操作：
  1. **事务②（apply）原子内容**：`board_member` diff 落库（`[in_date,out_date)`）+ 候选置 `applied, applied_at` + issue 置 `resolved, resolved_at` + **`board_dict` 同步刷新 `member_count = <候选代码数>`、`member_history_start_date` 仅在为空（板块首次应用）时写 `snapshot_date`、已存在则不覆盖**。任一失败整体回滚，候选保留可重试；`member_count` 刷新与 diff 落库同事务，保证 R2「member_count 与有效成员数一致」在应用后即刻成立。
  2. **事务③（discard）原子内容**：候选置 `discarded` + issue 置 `ignored`，不触碰 `board_dict`。
  3. apply/discard 为同步短事务不起异步任务；409 `error_code` 区分 `already_processed`/`same_day_snapshot_already_applied`；审计 best-effort（失败 warning 不回滚业务）。
  4. **写锁冲突识别机制（明确，承接 T4 `transaction()`，2026-08-09 实测定稿）**：DuckDB 写锁是**文件锁**，跨进程冲突**立即失败**（实测 0.006s 抛 `IOException: Could not set lock ... Conflicting lock is held`），不存在"阻塞等待后超时"模型；本机 DuckDB 1.5.3 **无 `duckdb_max_lock_wait_time` 锁等待配置**（SET 抛 CatalogException，已实测），因此**不设置任何锁等待超时**。进程内并发由 `DuckDBClient` RLock 串行化（与 data_admin.py 既有同步短写先例一致）；跨进程占用（如 CLI `board --backfill` 独立进程持文件写锁）导致 connect 立即抛 IOException，`duckdb_client` 的 `except Exception` 将其包进 `StorageError`，`transaction()` 异常包装层**按消息关键字归类**（`lock`/`Cannot open`/`Another client`/`busy` → `duckdb_write_unavailable`，实测命中 `lock`；其余按普通 `StorageError` 500）。归类后接口按软失败口径返回 `error_code=duckdb_write_unavailable` + 提示「数据库写入暂不可用（采集/回填进行中或外部进程占用），请稍后重试」，候选保持 `pending` 可重试，不产生半成品状态。**连接恢复**：写模式 connect 即获文件锁、冲突只在 connect 阶段发生，`_conn` 保持 `None`，锁释放后同一实例重试即自动重建连接恢复，无需显式释放（实测确认，见 T4 操作 5）。
- 产出：接口 + 集成测试（**候选应用后 member_count 与有效成员数一致、member_history_start_date 首次写入、被拦截未应用候选不改 member_count**、同日第二候选 409、表达式索引竞态兜底、审计失败业务仍成功、写锁冲突返回 `duckdb_write_unavailable` 且候选状态不变）。
- 影响范围：数据管理域新增 3 个接口（system-only）。
- 边界与异常：DuckDB 事务失败整体回滚；PG 审计失败不补偿业务；同步写不占 `WRITE_TASK_TYPES` 任务槽（短事务，对齐既有 quality_reset/ignore 同步写先例），写锁冲突按上述 `duckdb_write_unavailable` 语义返回。
- 验证方式：接口/集成测试。
- 完成标准：R2 验收标准中接口部分通过（含成员数一致性断言）。
- 实际落地情况：待实施

### 6.10 任务 T10a：RBAC 常量 + seed（前置部分）

- 状态：待开始
- 依赖：T1（无其他依赖，供 T8/T9/T10b 先行消费，消除原 T8↔T10 双向依赖环）
- 涉及文件/模块：[constants.py](../../backend/auth/constants.py)（`BUSINESS_RESOURCE_CODES` 加 `sectors:view`）、[pg_ddl.py](../../backend/storage/pg_ddl.py)（`_SEED_MENU_TREE` quotes 下加 `/sectors` 子菜单 visible=login、`_SEED_RESOURCES` 加 `sectors:view` GET `/api/sectors*` 挂 `/sectors`）
- 目标：R22 后端 seed 部分——常量与 seed 幂等落地，使 T8 的 403/权限验收、T9 的 system-only 守卫可依赖。
- 操作：`sectors:view` 进 `BUSINESS_RESOURCE_CODES`；`_SEED_MENU_TREE` 在 quotes 下加「板块行情」子菜单；`_SEED_RESOURCES` 加 `sectors:view` 资源行；沿用既有 `ON CONFLICT (id) DO NOTHING` 幂等插入方式。**部署时序约束：菜单 seed 生效不得早于前端路由上线**——`_SEED_MENU_TREE` 加 `/sectors` 后，若前端未同批发布，菜单将指向不存在的路由；前后端必须同批发布（见 §9）。本任务只改代码内 seed，不产生迁移 SQL。
- 产出：常量 + seed 改动（随代码部署生效）。
- 影响范围：新库 PG sys_menu/sys_resource 新增行；`BUSINESS_RESOURCE_CODES` 扩展。**不涉及既有库回填**（既有库授权由 T10b 回填 SQL 处理）。
- 边界与异常：菜单 seed 对既有库仍须手动回填授权后才可见（T10b）。
- 验证方式：seed 幂等重跑 + `BUSINESS_RESOURCE_CODES` 常量测试。
- 完成标准：`sectors:view` 入业务授权集合；seed 幂等可重跑。
- 实际落地情况：待实施

### 6.10b 任务 T10b：RBAC 既有库回填 + 权限测试

- 状态：待开始
- 依赖：T10a（常量 + seed 已就位）、T8（接口就位后 403 断言才可测）
- 涉及文件/模块：`agent-works/concept-industry-board/sectors-view-grant.sql`（既有库一次性回填授权 + bump perm_ver，marker 幂等）、`agent-works/concept-industry-board/sectors-view-grant-rollback.sql`（回滚）、`backend/tests/`（路由扫描/权限测试）
- 目标：R22 后端回填与权限测试——既有库回填 `sectors:view` 授予 normal/tenant_admin；回填与 `perm_ver` 自增同一 PG 事务；接口 `require_perm` 守卫；无授权用户菜单不可见 + 路由守卫 fail-closed + 接口 403。
- 操作：沿用 `asset-publish-open` 迁移模式（确定性基线恢复，不依赖 marker 内容，marker 仅作幂等标记；见 pg_ddl.py:934）；路由扫描测试同步新增端点断言；权限测试覆盖有/无 `sectors:view`、有/无 `stocks:view`。
- 产出：回填/回滚 SQL + 权限测试。
- 影响范围：既有库 sys_role_resource/sys_user_role 授权关系 + 受影响用户 `perm_ver`（旧 token 失效重登，预期行为）。**全量用户 token 因 perm_ver 变化失效重登为预期副作用**。
- 边界与异常：回填 SQL 幂等可重复执行；回滚 SQL 恢复授权基线并 bump perm_ver。**回滚基线内容明确定义为**：执行前快照中 normal/tenant_admin 已持有的 `sectors:view` 授权（即回滚 SQL 只删除本回填新增的 `sectors:view` 授权行，不触碰其他既有授权；确定性基线为「无 `sectors:view` 授权的原始状态」，与 asset-publish-open 回滚同构）。**回滚 bump perm_ver 使全量受影响用户 token 二次失效**，属预期（与回填相同副作用），计划与回滚 SQL 注释中均需声明。
- 验证方式：权限测试（有/无 `sectors:view`、有/无 `stocks:view`）+ 回填 SQL 幂等重跑 + 路由扫描测试。
- 完成标准：R22 验收标准中后端部分通过。
- 实际落地情况：待实施

### 6.11 任务 T11：板块行情列表页 `/sectors`

- 状态：待开始
- 依赖：T8（接口）、T10a（常量 + seed）；开工前先按 page-template.md §1 把原型/组件选型结论同步用户（本计划 §4 已给推荐与理由）
- 涉及文件/模块：`frontend/src/views/SectorsView.vue`（新增，优先 `npm run scaffold-page -- --pageKey sectors --label 板块行情 --archetype list`）、`frontend/src/router/index.ts`（`/sectors`）、[pageRegistry.ts](../../frontend/src/layout/pageRegistry.ts)（`sectors` pageKey：slots/consumedComponentFields/componentMeta sortFields）、`frontend/src/api/sectors.ts`（新增 API 封装）、[DESIGN.md](../../DESIGN.md)（page-registry 区块登记）
- 目标：R7、R10 + R22/R23 列表页部分，逐项承接 §4.1 功能点表与原型区域。
- 操作：action 区四控件；主表列与排序周期联动语义（含非涨幅排序取消周期高亮、URL 不保留无效 period、切回涨跌幅用最近合法周期）；筛选态写 URL query；进详情仅点板块名并携带来源 query；`usePageSettings('sectors', { defaultPeriod:'today', defaultType:'concept' })` + `componentValueOf('table', ...)`；四态与权限态。
- 产出：页面 + 路由 + registry 登记 + API 封装 + Vitest（筛选态还原、排序周期联动、偏好优先级 URL>保存>默认、非法值回落）。
- 影响范围：新增页面与菜单可见入口；无既有页面变化。
- 边界与异常：搜索关键字 ≤50 字符；空值列「—」；窄视口主表内滚。
- 验证方式：Vitest + `npm test`（pageRegistry 契约）+ Playwright（T15）。
- 完成标准：R7、R10 验收通过；契约测试绿。
- 实际落地情况：待实施

### 6.12 任务 T12：板块详情页 `/sectors/:code`

- 状态：待开始
- 依赖：T8、T10a、T11（列表页来源 query 契约）
- 涉及文件/模块：`frontend/src/views/SectorDetailView.vue`（新增，`--pageKey sectors-detail --label 板块详情 --archetype detail`）、`frontend/src/router/index.ts`（`/sectors/:code`）、[pageRegistry.ts](../../frontend/src/layout/pageRegistry.ts)（`sectors-detail` + `memberTable` 嵌套 slot，parentId=detail）、`frontend/src/api/sectors.ts`、[DESIGN.md](../../DESIGN.md)（page-registry 登记）
- 目标：R8、R9、R11、R13、R14 + R22/R23 详情页部分，逐项承接 §4.2 功能点表与原型区域。
- 操作：摘要卡（含双数据日期标注）；走势图 ECharts（`useEChartsTheme`）+ 周期分段 + TradeDatePicker + `chartPeriod` 偏好；成分股表统一分页（嵌套 slot `memberTable`，componentMeta sortFields=pct/code，consumedComponentFields=pageSize/defaultSort/hiddenColumns）；`hasPermission('stocks:view')` 行可点性与 hover 提示；返回筛选态（面包屑/返回 `router.replace` 显式跳列表 + 白名单校验来源 query，不用 `router.back()`；浏览器原生后退不拦截）；`usePageSettings('sectors-detail', { chartPeriod:'3m' })`；图表紧凑稳定、成分股表主成长区表体内滚、低高度整体滚动兜底。
- 产出：页面 + registry 登记 + Vitest（返回筛选态有/无来源 query、权限行禁用、memberTable 字段消费、偏好回落）。
- 影响范围：新增页面；无既有页面变化。
- 边界与异常：板块不存在 → error 态；历史不足涨幅「—」不缩短周期。
- 验证方式：Vitest + `npm test` 契约 + Playwright（T15）。
- 完成标准：R8、R9、R11、R13、R14 验收通过；契约测试绿。
- 实际落地情况：待实施

### 6.13 任务 T13：数据质量页候选操作列

- 状态：待开始
- 依赖：T9（候选接口）、T7
- 涉及文件/模块：[QualityView.vue](../../frontend/src/views/data/QualityView.vue)（扩展）、`frontend/src/api/`（候选接口封装）、`frontend/src/views/__tests__/`（Vitest）
- 目标：R2/R12 页面闭环——`member_surge_shrink` 行候选 diff 展示与「确认应用」「丢弃」操作，承接 §4.3 功能点表。
- 操作：候选经 `issue_id` 附着问题行内；AppRowActions 两动作 + `:loading`；`apply_allowed=false` 禁用「确认应用」+ 提示；确认弹窗展示 diff 摘要（候选 `codes_json` 全量代码可展开明细，板块名/快照日/新增/退出/净变化数）；候选列表按 `board_type` 过滤（`GET /api/data/board-candidates` 支持 `status/board_type/page/size` 参数，承接需求 §6.2 候选接口契约）；409 按 `error_code` 区分提示并刷新；`duckdb_write_unavailable` 软失败提示「数据库写入暂不可用，请稍后重试」（不刷新、候选仍 pending）。
- 产出：页面扩展 + Vitest（动作可用性、409 两码提示、刷新行为）。
- 影响范围：QualityView 新增列与操作，无布局重排。
- 边界与异常：操作完成后刷新列表；PG 审计失败时接口返回业务成功 + warning，页面按成功处理。
- 验证方式：Vitest + 页面验收（T15）。
- 完成标准：R2/R12 页面部分验收通过。
- 实际落地情况：待实施

### 6.14 任务 T14：RBAC 前端接入与配置闭环端到端核对

- 状态：待开始
- 依赖：T10a、T10b、T11、T12、T13
- 涉及文件/模块：`frontend/src/router/index.ts`（守卫 meta 权限）、菜单 seed 消费（侧栏）、两页 `v-permission`（如涉及按钮级权限）、[system-rbac-tenant.md](../architecture/system-rbac-tenant.md) 验收清单
- 目标：R22/R23 端到端核对——菜单可见性与授权一致；无授权用户路由守卫 fail-closed；pageRegistry 两处登记与路由一致；两页配置闭环（保存/读取/消费/非法回退/恢复默认同时重置业务偏好与组件字段）；DESIGN.md page-registry 登记完整。
- 操作：按 system-rbac-tenant.md「新页面接入菜单和权限」清单逐项验收；组件字段契约测试；「恢复默认」同时调 `reset()` 与 `resetLayout`。
- 产出：核对结论 + 缺失修补。
- 影响范围：权限与配置正确性。
- 边界与异常：默认角色授权决策以 T10a seed 为准。
- 验证方式：`npm test`（契约/布局测试）+ 权限场景人工验收（用最小权限调试账号，先读 `agent-works/multi-tenant-rbac/test-users.md`）。
- 完成标准：R22、R23 验收标准中非 E2E 部分通过。
- 实际落地情况：待实施

### 6.15 任务 T15：E2E、构建、视口与回归验收

- 状态：待开始
- 依赖：T11、T12、T13、T14
- 涉及文件/模块：`frontend/e2e/`（新增 `sectors-*.spec.ts` 等）、[e2e guide](../e2e-automation/guide.md)、`frontend/dist`
- 目标：R7-R14、R22、R23 的页面级验收与全量回归。
- 操作：**板块 E2E 数据夹具先行**——测试 DuckDB 默认无板块数据，需按 `e2e_backtest_runs` 同款模式（`backend/devtools/` + `frontend/e2e/helpers/` + `AI_STOCKS_E2E_WRITE=1` 门控 + `/api/health/e2e` PG 指纹校验）提供板块列表/详情/候选的可清理 seed/cleanup 夹具；涉及 DuckDB 写的夹具与被测后端的读写模式拆分遵守 AGENTS.md E2E 门控规则。随后新增 Playwright 用例（稳定 `data-testid`/可访问名称/helper，不用坐标与脆弱 CSS）：列表切换/排序周期联动/搜索/分页/列显隐；详情摘要/走势图周期/成分股统一分页与排序；返回筛选态（面包屑显式跳列表还原 + 浏览器原生后退）；R9 权限两态（有/无 `stocks:view`）；质检页候选确认/丢弃；空态/错误态。`npm run build`；关键视口 1100×620 / 1366×768 / 1440×900 无文本溢出且详情表体可读；按 e2e guide 判断是否并入回归集。跑全量 E2E 前后按 AGENTS.md 端口/锁/限流门控规则准备后端（5181、`AI_STOCKS_E2E_LOGIN_BYPASS=1` 等）。
- 产出：E2E 用例 + 构建产物 + 视口验收记录 + 回归结果。
- 影响范围：交付质量门禁。
- 边界与异常：E2E 选择器只用稳定契约；回归结束后重启后端移除限流豁免。
- 验证方式：`cd frontend && npm run test:e2e`（含新用例与相关回归）+ `npm run build` + `python -m pytest backend/tests/ -q` 全量（遵守 DuckDB 锁规则）。
- 完成标准：需求文档 §11 验收标准全部通过；`npm run build` 与后端全量测试绿。
- 实际落地情况：待实施

## 7. 数据库与 SQL 计划

### 7.1 DuckDB（代码内 DDL，无独立 SQL 文件）

- 路径：[ddl.py](../../backend/storage/ddl.py)（5 表 + `_DIMENSION_SEED` board 行）。
- 用途：板块 5 表与维度注册。
- 执行时机：后端启动 DDL init 幂等执行（T3 随代码上线）。
- 影响范围：DuckDB schema 新增；无既有表变更、无数据迁移。
- 回滚方式：`DROP TABLE IF EXISTS board_dict, board_member, board_bar, board_fund_flow, board_member_candidate` + 删除维度 seed 行（新表无外部依赖，可安全回滚）。

### 7.2 PG seed（代码内幂等 seed）

- 路径：[pg_ddl.py](../../backend/storage/pg_ddl.py) `_SEED_MENU_TREE`/`_SEED_RESOURCES`（`/sectors` 菜单 + `sectors:view` 资源）。
- 执行时机：PG DDL init 幂等执行（T10a 随代码上线）；新库自动生效。
- 影响范围：sys_menu/sys_resource 新增行；新角色授权集合。
- 回滚方式：删除 seed 行 + 清理对应资源/菜单（须先执行 7.3 回滚 SQL 还原既有库授权）。

### 7.3 PG 既有库回填 SQL

- SQL 文件路径：`agent-works/concept-industry-board/sectors-view-grant.sql`（回填）、`agent-works/concept-industry-board/sectors-view-grant-rollback.sql`（回滚）。
- 用途：既有库为 normal/tenant_admin 角色一次性补授 `sectors:view`，同一 PG 事务 bump `perm_ver`；marker 幂等（沿用 asset-publish-open 模式，确定性基线恢复，不依赖 marker 内容）。
- **产物时点**：本阶段 SQL 文件尚不存在，为 T10b 交付物；本节描述为意图，**待 T10b 产出后固化**（届时把本节路径/字段/语句落为真实文件并回填本节）。
- 执行时机：T10a 代码部署后、T14 权限验收前，一次性执行；重复执行幂等。
- **回填基线（确定性）**：normal/tenant_admin 角色在**无 `sectors:view` 授权**的原始状态上新增该资源授权 + bump perm_ver；仅当确有新增才 bump（沿用 asset-publish-open `_backfill_asset_publish_open_v1` 的「changed 才 bump」模式，pg_ddl.py:1697-1699），避免空跑污染 perm_ver。
- 影响范围：sys_role_resource/sys_user_role 授权关系 + 受影响用户 `perm_ver`（旧 token 失效重登，预期行为）。
- 回滚方式：执行 rollback SQL **删除本回填新增的 `sectors:view` 授权行（恢复到「无该授权」的基线）+ bump `perm_ver`**，不触碰其他既有授权；**回滚 bump perm_ver 会使全量受影响用户 token 二次失效**（与回填相同副作用，预期且需在回滚 SQL 注释中声明）。不回滚已新增的 sys_menu/sys_resource seed 行（无害残留，菜单随代码回退消失）。
- SQL 文件要求：含总体/字段/执行语句注释，说明用途、影响范围、前置条件、回滚方式（协作红线）。

### 7.4 配置项

- 路径：`config/settings.yaml`（板块质检阈值基线）+ **`backend/config/settings.py` `Settings` 模型加子模型字段（Pydantic default_factory，与 YAML 节字段名对齐）** + `CONFIG_GROUPS` 白名单（`app_config.py`，PG `app_config` 在线覆盖）+ `get_effective_settings()` 消费（T7）。
- 执行时机：T7 随代码上线；默认值 `relative_change_ratio=0.5`、`absolute_change_threshold=20`。
- **契约要点（T1 核验补充）**：`get_effective_settings()` 先 YAML 再叠加 app_config 覆盖层，覆盖层按白名单 `CONFIG_GROUPS` 字段校验（`app_config.py:22-65`）；阈值须在 `Settings` 加子模型字段（如 `board_quality`），`settings.yaml` 加对应节、`CONFIG_GROUPS` 加对应 field 三个位置同步，缺任一环 `get_effective_settings()` 无法正确消费。
- 影响范围：质检扫描阈值；不调整时纯 YAML 基线生效。
- 回滚方式：删除 YAML 键与白名单项即回到无板块质检（规则代码同步移除）。

## 8. 测试与验证计划

- 单元测试：
  - 计划：T2 适配器单测；T3 DDL/约束单测；T4 采集逻辑单测（diff/hash/同日冻结/资金流映射/**member_count 刷新时机**/事务原子性/**写锁冲突关键字归类与重试恢复**）；T6 daily 参数化矩阵；T7 质检规则与配置覆盖（含收敛不误删 `member_surge_shrink`、**Settings 模型/YAML/CONFIG_GROUPS 三环覆盖生效**）；T8 统计口径（含领涨股来源）；前端 Vitest（筛选态、偏好优先级、memberTable 字段消费、返回 query 白名单校验）。
  - 具体完成情况：T2 已落地——`test_ths_board_source.py` 20 用例全绿（含登录态 4 例，2026-08-09）；T3 已落地——`test_ddl.py` 17 用例全绿（含板块表/CHECK/表达式唯一索引 7 例，2026-08-09）；T4 已落地——`test_board_ingest.py` 10 用例全绿（diff/hash 幂等/候选/事务原子性/写锁归类，2026-08-09）；T5 已落地——`test_data_mgmt_b.py` 板块任务 4 用例全绿（注册/执行/互斥/续跑，2026-08-09）；T6 已落地——`test_pipeline.py` 板块集成 4 用例全绿（默认执行/跳过/失败隔离/total_steps，2026-08-09）
- 接口测试：
  - 计划：T8 四接口口径对账（涨幅/净流入/成分数 vs DuckDB，含领涨股来源 `board_fund_flow.leader_stock` 与即时净流入同 snapshot 行，口径以 §10.3 待确认结果为准）；T9 候选三接口（409 两码、事务回滚、审计失败业务成功、写锁冲突 `duckdb_write_unavailable`、**应用后 member_count 一致 / member_history_start_date 首次写入 / 未应用候选不改值**）；T10a/T10b 权限（有/无 sectors:view、403）。**跨进程锁冲突集成测试（T4/T9 新增断言）**：独立子进程持写锁 → 被测进程写事务归类返回 `duckdb_write_unavailable` 且候选状态不变、锁释放后重试恢复。
  - 具体完成情况：待验证
- 页面/交互测试：
  - 计划：T15 Playwright（列表筛选/排序联动/搜索/分页/列显隐、详情走势图周期/成分股统一分页、返回筛选态两路径、R9 权限两态、质检页候选操作）。
  - 具体完成情况：待验证
- 组件资产闭环测试：
  - 计划：`sectors`/`sectors-detail` pageRegistry 契约测试（memberTable 嵌套 slot、consumedComponentFields 指向真实 slot）；两页组件字段保存/读取/非法回退/恢复默认参数化矩阵；DESIGN.md page-registry 登记核对。
  - 具体完成情况：待验证
- 权限与数据范围测试：
  - 计划：T10a/T10b 后端权限测试 + T14 前端菜单/守卫验收（最小权限调试账号，先读 `agent-works/multi-tenant-rbac/test-users.md`）；候选接口 system-only。
  - 具体完成情况：待验证
- 回归测试：
  - 计划：`python -m pytest backend/tests/ -q` 全量（先 `./start.sh status`→`./start.sh stop`，结束后按原状态恢复并确认 `/api/health=200`）；`npm test`；相关既有 E2E 回归。
  - 具体完成情况：待验证
- 异常与边界测试：
  - 计划：不完整快照不退出 diff、同 hash 幂等、同日第二候选 409 + 索引竞态兜底（INSERT 与 UPDATE 两路径）、payload_hash 非法格式、401 cookie 刷新、单板块失败继续与失败清单、历史不足「—」、空值列「—」、`transaction()` 原子性（中途失败整体回滚）、写锁冲突 `duckdb_write_unavailable`（候选状态不变可重试、**锁释放后重试可恢复**）、**member_count 双应用路径刷新与未应用不刷新**、**T7 收敛不误删 `member_surge_shrink` open issue**。
  - 具体完成情况：待验证
- 图示与原型一致性验证：P1/P2 实现对照 `prototypes/sector-board.html`/`prototypes/sector-detail.html` 的主要区域（action 筛选区/主表/分页/设置抽屉；摘要区/走势图工具条/图表/成分股表/抽屉/tooltip）、操作入口、关键状态（数据/空/错误/加载/无权/个股权限两态）与低高度退化；P3 无原型，按 QualityView 现状扩展核对。
- 配置闭环验证：`defaultPeriod/defaultType/chartPeriod` 偏好与 `pageSize/defaultSort/hiddenColumns` 组件字段可展示、保存、读取、实际生效、恢复默认、非法值回落并兼容旧值。
- 需求映射验证：§5 映射表逐项核对，R1-R14、R21-R23 均有任务与验证方式；R15-R20/R24/R25 均标跳过且有原因；无未解释的超范围开发内容。
- 页面功能点验证：§4.1/§4.2/§4.3 功能点表逐项有技术实现、任务编号、交互状态与异常处理验证。

## 9. 发布与回滚

- 发布前检查：后端全量测试绿（DuckDB 锁规则）；`npm test` + `npm run build` 绿；E2E 通过；回填 SQL 已评审；`.env.local` 环境确认 `AI_STOCKS_ENV`。
- 发布步骤：
  1. 部署后端代码（DDL/seed 幂等自动生效）→ `./start.sh restart` → `./start.sh status` 确认 `/api/health=200`。**注意：菜单 seed 生效不得早于前端路由上线，步骤 1 与步骤 3 必须同批发布**（否则菜单指向不存在的 `/sectors` 路由）。
  2. 执行 `sectors-view-grant.sql`（既有库回填，T10b 产物）。
  3. 部署前端 `frontend/dist`（`npm run build` 产物，与步骤 1 同批）。
  4. 系统管理员触发 `python -m backend.cli board --backfill`（或任务中心创建板块采集），确认 5 表数据与任务进度。
  5. 冒烟：列表页/详情页/数据概览/数据质量页。
- 配置或环境变量：无新增密钥；同花顺源为公开 HTTP，限速参数走代码常量；质检阈值走 YAML 基线（可选 app_config 覆盖）。
- 回滚方案：代码回退（前端 dist + 后端）→ 执行 `sectors-view-grant-rollback.sql`（删除本回填新增的 `sectors:view` 授权行 + bump perm_ver，恢复无该授权的基线；受影响用户 token 二次失效为预期）→ DuckDB 5 表可保留（只读接口随代码回退消失，数据无害残留）或按 §7.1 drop；维度 seed 行随代码回退消失。

## 10. 风险、假设与待确认项

### 10.1 风险

- 同花顺反爬升级（v cookie 脚本失效/限流加严）：`ths.js` 依赖 akshare 包内资源，akshare 升级可能破坏；缓解——适配器单测 mock 化 + 401 刷新重试 + 限速 ≥1s；失效时板块采集失败隔离不阻塞主流程（R21）。
- **成分股翻页限制与登录态解除（2026-08-09 T2 实测定稿）**：无登录态时详情页翻页第 6 页起必返回登录墙（HTTP 200 但内容为 `upass...login` 跳转壳，单发第 6 页同样命中，非 IP 频率触发），单板块最多稳定取 5 页（概念 50 只/行业 100 只）；**提供登录 cookie（`login_cookie` 参数 / `AI_STOCKS_THS_COOKIE` 环境变量，浏览器同花顺登录后复制）后登录墙解除**——冷 IP 下实测半导体第 6 页正常返回 20 只、完整取到 120 只，`complete` 判定回归正确（空页=真实尾页）。**代价：同花顺对数据中心 IP 的连续请求有动态风控**——请求量累积后返回空页/401，冷却短暂恢复、持续高频后 IP 被标记稳定 401（cookie 本身 sess_tk 30 天内有效，非凭证过期）。缓解：适配器限速默认 ≥2s/次 + 分批断点 + 登录态失败时 `complete=False` 走 R2 保护；长期大批量采集需评估 IP 轮换或进一步低频。
- `py_mini_racer` 当前为传递依赖：T2 显式声明消除升级漂移风险。
- app_code(clid) 需逐板块详情页抓取，采集耗时与失败率高于其他接口：失败不阻塞字典主体，`app_code` 允许为空后续补采。
- 既有库回填执行遗漏会导致老用户菜单不可见：发布步骤强制包含 SQL 执行与权限验收。
- E2E 全量回归的登录限流/DuckDB 读写锁门控配置遗漏：T15 操作步骤显式列出。
- 表达式唯一索引依赖 DuckDB 版本能力：本机 1.5.3 实测创建与强制均生效（2026-08-09 复核）；若部署环境旧版本拒绝，T3 单测在开发期暴露，按 §4 降级方案执行，不会带病上线。
- 写锁冲突识别靠异常消息关键字归类（2026-08-09 实测）：本机 DuckDB 1.5.3 **无锁等待配置**（`SET duckdb_max_lock_wait_time` 抛 CatalogException），跨进程冲突**立即失败**（0.006s 抛 `IOException: Could not set lock`，被 `duckdb_client` 包装进 `StorageError` 且消息含 `lock`，归类可命中）。已移除锁等待超时设计，仅保留关键字归类；若错误消息格式随 DuckDB 升级变化导致关键字漏配，最坏退化为 500 而非半成品状态，且 T4/T9 的跨进程锁冲突集成测试可尽早暴露。**连接恢复无需额外处理**：冲突只发生在 connect 阶段、`_conn` 保持 `None`，锁释放后同一实例重试即自动重建连接（实测确认），不存在需显式释放的残留连接。
- 列表页 `pageSize` 冲突按需求口径（10/20/50）实现，与原型 10/20/30/50 不同：需求为当前事实源，已声明为计划 vs 原型的显式取舍；若后续需求变更需回溯原型口径。
- 回填/回滚 SQL 待 T10b 产出后固化：发布计划 §7.3/§9 的描述为意图而非已定实现，T10b 交付时须回填固化并评审。

### 10.2 假设

- 板块成分股现价/涨跌幅/换手来自 DuckDB 个股行情表（与 `board_bar` 同库关联，不跨库 JOIN）；个股当日无行情时对应列显示「—」且不计入涨跌家数。
- `data_quality_issue` 无 `meta` 字段，候选经 `board_member_candidate.issue_id` 关联，不改既有 issue 表结构。
- 质检页候选列表入口复用 `GET /api/data/board-candidates`，QualityView 以 issue 为主入口、候选附着行内（需求 §7.3 已明确）。
- 任务中心「板块采集」前端中文标签改 `data.ts` 一处即可被任务中心各列表消费（与现有任务类型同款）。
- 领涨股及涨幅默认取 `board_fund_flow.leader_stock/leader_pct`（与即时净流入同一 `(snapshot_date, period='即时')` 行），无资金流板块领涨股为「—」（不走成分股涨幅第一另行计算，口径单一）；**该口径在资金流日期 ≠ 涨幅日期时展示「资金流日领涨股」是否为可接受口径，作为待确认项（见 §10.3）**。
- 列表/详情只展示 `has_members` 或 `has_bar` 为 true 的板块；仅 `has_fund_flow` 的资金流独有板块入字典但不进页面展示（承接需求 §2.5）。

### 10.3 待确认项

- 无阻塞待确认项。以下非阻塞项在实施中按既定口径执行，如有异议随时回到用户确认：
  - 采集服务落 `board_ingest.py` 新文件还是并入 `ingest.py`（T4 实施时按既有分层就近原则定，偏离时在开发留痕说明）。
  - 候选接口挂 `data_admin.py` 还是新建 `board_candidates.py`（T9 实施时同上）。
  - 列表页「上涨/下跌家数」列合并展示 vs 原型「上涨家数」单列（以需求 §7.1.2 为准，已在 §4.1 标注差异）。
  - 列表页 `pageSize` 合法值按需求 10/20/50（原型含 30，以需求为准，已在 §4.1 标注差异）。
  - 领涨股取数来源（**待确认，非既定**）：需求 §6.2 只定义响应含「领涨股」，未定义来源。默认口径为 `board_fund_flow.leader_stock/leader_pct` 且与即时净流入同一 `(snapshot_date, period='即时')` 行——但 §4.2 明确涨幅与净流入分别标注各自数据日期（`board_bar` 最近交易日 ≠ `board_fund_flow` 最近 snapshot_date），**当两日不同时，领涨股展示的是「资金流日领涨股」而非「涨幅日/今日强势股」**（资金流独有板块该列显示资金流日领涨股，列表默认按今日涨幅降序时榜首板块领涨股可能不是今日强势股，观感突兀）。是否接受该口径需用户确认；不接受则改为「按涨幅交易日成分股涨幅第一」另行实现。若后续需要「无资金流板块仍显示成分股涨幅第一」，同样需另行决策（当前默认口径下无资金流板块领涨股为空「—」）。
