# 开发计划：板块概念数据采集与展示

> 计划版本：2026-08-09（当日评审复核修订：表达式唯一索引可行性实测确认并补降级方案、候选 apply 写锁冲突语义、T8/T10 依赖收紧、菜单 seed 部署时序、审计文件路径修正、板块 E2E 数据夹具、两页 pageSize 合法值口径显式化、`DuckDBClient.transaction()` 原子性前置、T2 适配器封装口径对齐 research 附录已确认决策；二轮评审复核整改：T9 候选应用事务②补入 `member_count` 刷新、T10 拆分 T10a/T10b 消除 T8↔T10 双向依赖、T7 issue 判重与收敛策略补明确、T9 写锁冲突识别机制补明确、领涨股取数来源默认定为资金流 leader_stock（T8 明确，口径待确认）、列表页 pageSize 原型冲突差异说明补注、`board` 任务类型与既有榜单命名空间边界声明、§7.3 回滚基线内容与「回填 SQL 待 T10 产出后固化」声明、候选列表 board_type 过滤参数补入、板块字典核心能力展示口径承接、T7 不误删候选关联 open issue 的收敛边界；**三轮实测修正：`duckdb_max_lock_wait_time` 实测不存在（SET 抛 CatalogException）与跨进程写锁「立即失败」实测推翻锁等待模型，写锁冲突识别改为纯关键字归类；领涨股口径（资金流日 leader_stock 与涨幅日不一致的展示）转回待确认项；四轮实测修正「连接残留污染态」叙事不实——冲突仅发生在 connect 阶段、`_conn` 保持 None、锁释放后重试即自动恢复，无需显式释放连接**；T1 执行（2026-08-09）：契约逐项对照代码现状核验成立，补 R12 阈值 `Settings` 模型子模型字段一环（§7.4/T7）；**T2 执行（2026-08-09）：`ThsBoardSource` 适配器落地（16 单测绿 + 真源冒烟 375/90/成分/指数/资金流通过），实测发现成分股翻页第 6 页起必登录墙（`complete=False` 标不完整）与概念字典=分类页 351∪gn/index 前 3 页净增 24=375**；**登录态实测补充（2026-08-09 用户提供浏览器登录 cookie）：登录态解除详情页翻页登录墙（半导体取全 160 只 vs 无登录 100 只，登录后随日期在 120~160 间波动），适配器新增 `login_cookie` 参数 + `AI_STOCKS_THS_COOKIE` 环境变量支持、限速改走 `ths_board.min_interval_sec` 配置（默认 1.0s/次，早期中间态曾 ≥2s/次，配置化后统一为默认 1.0 可调）；数据中心 IP 连续请求仍触发动态风控（401/空页），`complete=False` 兜底保留**；**T3 执行（2026-08-09）：DuckDB 5 表 DDL + board 维度注册落地（`M_BOARD_TABLES` + `_DIMENSION_SEED`，17 用例全绿，表达式唯一索引 INSERT/UPDATE 两路径实测拦截，DuckDBClient 异常重建连接语义记录）**；**T4 执行（2026-08-09）：采集服务落地（`BoardIngestService` + `DuckDBClient.transaction()` + `ingest_board` 编排，10 用例全绿，diff/payload_hash 幂等/候选事务①/资金流映射/写锁归类）**；**T5 执行（2026-08-09）：`board` 异步任务类型注册（TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES + `_h_board` checkpoint=board_code + 前端「板块采集」标签，4 用例全绿）**；**T6 执行（2026-08-09）：CLI `board` 命令族 + daily 集成（`DailyPipeline.run(board=True)` + `--skip-board` + 失败隔离不阻塞主流程 + total_steps 同步，4 参数化用例全绿）**；**指数历史年限修正（2026-08-09 实测）：`d.` 域指数仅近 3 年（2024 起，2021-2023 404），R3「回填 5 年」修正为「回填源端可用年限」，`ingest_board` 回填起点 2021→2024；各板块起始日不同属正常**；**T7 执行（2026-08-09）：板块质检落地（`scan_board_quality` 成分数波动+指数缺口扫描，Settings/YAML/CONFIG_GROUPS 三环阈值配置，SCAN_ISSUE_TYPES 收敛含板块类型且不含 member_surge_shrink，4 用例全绿）**；**深度体检修复（2026-08-09）：①增量/全量语义 `ingest_board(mode=)` 区分 backfill/update（指数补 5 天/资金流只采即时 vs 全量回填/全周期）；②双口径阈值修复（T4 拦截与 T7 扫描统一读 get_effective_settings().board_quality，删除硬编码常量）**；**配置口径修订（2026-08-09 用户反馈）：①`board_quality`（板块质检阈值）为低频稳定参数，从系统设置 Web 表单移除——不再进 CONFIG_GROUPS 覆盖层白名单，仅 YAML 基线（Settings 模型 + settings.yaml），「其他」tab 随之消失；②同花顺限流配置化：新增 `ths_board` 配置段（min_interval_sec/timeout_sec/max_retries/retry_backoff_sec），独立于通用 `datasource.*` 限流（同花顺是独立反爬直连源，频率限制更敏感），挂「数据治理」tab 可 Web 覆盖，`ThsBoardSource` 从 `get_effective_settings().ths_board` 注入（对齐 akshare/baostock 模式，显式入参优先）**；**成分模型改为「只进不出」（2026-08-09 用户拍板）：①`board_member` 主键 `(board_code, code)`，每行一只成分股累积，完整快照 `INSERT ON CONFLICT DO NOTHING`，**不 diff、不删除、不候选**；②完整性即闸门——`complete=False` 整趟不落库、`data_update_log` 记 failed + 写 `board_member_incomplete` issue（数据质量页逐板块重采闭环）；③**整条候选机制删除**：`board_member_candidate` 表、`member_surge_shrink`/`board_member_wave` issue 类型、`/api/data/board-candidates` 接口、数据质量页候选确认/丢弃（T9/T13 取消）；④`scan_board_quality` 只保留指数缺口扫描；⑤采集页「指定板块」搜索修复为板块语义（新增 `/api/data/boards` 搜索接口）；⑥既有 103 板块成分数据保留并标 `board_member_incomplete` 待重采，362 未采板块由重采补齐，数据留痕标 failed；⑦需求文档 R2/R12/R25/验收/里程碑同步修订**；**T8 执行（2026-08-09）：`/api/sectors*` 只读 API 落地（`BoardQueryService` 四查询 + `sectors.py` 四接口，涨幅从 board_bar 实时计算、涨跌家数口径、404/400/403，test_sectors_api 8 用例全绿 + 端到端 465 板块实测）；T10a/T10b 同批交付（`sectors:view` 进业务授权 + `/sectors` 菜单/资源 seed + sectors-view-grant.sql 回填 + RBAC 权限测试，normal 用户 403→200）**；**成分更新周频（2026-08-10 用户拍板）：①成分股不随每日增量更新，按 `member_update_interval_days`（默认 7，`ths_board` 配置段新增字段 + 系统设置「同花顺板块」tab 可调）跳过未到期板块；②跳过条件 = `member_snapshot_at` 存在且距今 < 间隔（`member_snapshot_at IS NULL` 从未完整落库必须拉），跳过记 `skipped` 不计失败/不打 failed 日志/不写 `board_member_incomplete` 质检；③`force=True`（质量修复重采、`backfill` 初始化、CLI `--force-members`）绕过间隔；④`ingest_board_members`/`ingest_board` 增 force 参数，`ingest_board` 的 backfill 默认强制；⑤质量修复链路 async_task `board_member_incomplete` 重采改 force=True 防止被跳过；⑥测试适配：既有全量语义测试加 force=True，新增周频跳过单测（test_board_ingest 18 用例全绿）；⑦需求 R2 同步修订**；**自审复核整改（2026-08-10）：①全链路闭环 11 项偏差修复（取消穿透/部分失败语义/复检口径/severity 契约/scan 事务/缓存解耦/fund 忽略豁免/fund checkpoint 范围/指定板块绕周频/名称补全/前端 query 与调度校验）；②遗留治理：fund checkpoint 旧格式迁移 + 前端 query 清理；③资金流独有板块字典口径更新（R4 §2.5）：实测链接带真实路径 code → `_upsert_fund_only_boards` 补字典，需求/计划文档同步修订**）
> 当前校准：2026-08-14，新增 T16/R26 与 T17 页面敏感配置加密恢复；§11.1 仅归档失效验证，§11.2 是当前 HEAD 唯一验收事实；上一行是历史实施流水，不作为当前状态事实源。
> 需求文档：[requirement.md](requirement.md)（2026-08-14 校准版，确认状态：无阻塞项）
> 上游文档：[requirement-closure.md](requirement-closure.md)、[research.md](research.md)
> 页面原型：[prototypes/sector-board.html](prototypes/sector-board.html)（列表页）、[prototypes/sector-detail.html](prototypes/sector-detail.html)（详情页），均已完整读取并作为前端拆解依据。

## 1. 需求来源与目标

- 需求文档：`agent-works/concept-industry-board/requirement.md`
- 功能目标：
  1. 数据采集：新增板块字典、板块成分股、板块指数、板块资金流四块数据采集（同花顺源），纳入现有采集闭环（CLI / 异步任务 / 每日流程 / 数据概览 / 数据质量）。
  2. 页面展示：「最新行情」下新增「板块行情」列表页 `/sectors` 与详情页 `/sectors/:code`，支撑「题材 → 板块 → 成分股 → 龙头」研究链路；数据质量页承接 `board_member_incomplete` 成分重采闭环（候选确认/丢弃已废弃，2026-08-09 只进不出改造）。列表/详情只展示具备核心数据（`has_members` 或 `has_bar`）的板块，资金流独有板块（仅 `has_fund_flow`）不进入展示。
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

R1、R2、R3、R4、R5、R6、R7、R8、R9、R10、R21、R22、R23、R26（逐项映射见 §5）。

### 3.2 可选增强

| 需求编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R11 | 板块指数统一 K 线范围、市场指数基准、周期内横向缩放与图表高度拖拽 | 本次纳入 | 已完成 | T12 | 快捷周期的数据与缩放边界对齐；中证 500/沪深 300/不对比指数；超额涨跌提示；K线/量能高度分隔线 |
| R12 | 板块维度数据质量校验（指数缺口） | 本次纳入 | 已完成 | T7 | 复用 `data_quality_issue` |
| R13 | 详情页成分股统一分页（`AppPagination` 默认 20，无 TopN 展开） | 本次纳入 | 已完成 | T8、T12 | members 服务端分页/排序与详情表已落地 |
| R14 | 板块资金流统计卡（即时净流入额） | 本次纳入 | 已完成 | T8、T12 | 详情摘要指标条已落地 |
| R26 | 板块原始连续指数 MACD 副图 | 本次纳入 | 已完成 | T12、T15、T16 | 列表 K 线模式与详情复用工作区；标题、指标口径和 E2E 已补齐 |

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
| R25 | 同日候选替换（`superseded` + D-1 重建） | 跳过 | **已废弃（2026-08-09 只进不出改造）**：候选机制整条删除，无「同日替换」语义 | 原为候选机制补充需求 |

## 4. 技术方案

整体按需求文档 §12 五阶段推进：契约 → 数据源与 DDL → 采集与质检 → API 与权限 → 页面。模块边界：

- **数据流**：`ThsBoardSource`（直连 `q.10jqka.com.cn` / `data.10jqka.com.cn`，复用 akshare 打包的 `ths.js` 经 `py_mini_racer` 生成 v cookie，不调用 akshare 板块接口）→ `BoardIngestService`（字典两阶段 / 成分快照只进不出 / 指数 / 资金流名称映射）→ DuckDB 4 表 → `BoardQueryService`（全市场列表批量聚合；详情/自选把 board_codes 谓词下推到各事实表，遵循双库边界）→ `/api/sectors*` → 前端页面。
- **成分采集完整性闭环**（R2，只进不出）：完整快照（`complete=True`）`INSERT ON CONFLICT DO NOTHING` 落库 + 刷新 `member_count`；不完整快照（`complete=False`）整趟不落库 → `data_update_log` failed + 写 `board_member_incomplete` issue → 数据质量页「重采成分」（fix 分派重采该板块，完整后合并）。**候选机制已废弃**（2026-08-09 只进不出改造，见 T9/T13）。
- **接口契约**：`/api/sectors` 参数白名单（`trade_date/board_type/sort_by/order/keyword/page/size`），`sort_by` 字段码 `pct_today|pct_5d|pct_10d|pct_20d|net_inflow|up_count`；统计口径（涨幅按收盘价比对、历史不足显示「—」不缩短周期、涨跌家数按成分股 `close` vs `pre_close` 且平盘/停牌/缺行情不计入）严格按需求 §6.2 契约要点实现；**领涨股及涨幅按行情截面日有效成分股 `pct_chg` 最大者计算，停牌/缺有效前收排除，同涨幅按成交额降序、股票代码升序决胜；资金流源自带领涨字段仅原始留存**。
- **双口径边界（T8 必须遵守）**：列表/详情页的 **5日/10日/20日涨幅列与可排序涨跌幅字段（`pct_5d/pct_10d/pct_20d`）= 板块指数价格涨跌幅，T8 查询时从 `board_bar` 日线实时计算**（最近交易日收盘 vs N 个交易日前收盘，`trade_date <= D` 截面语义），**不是**从 `board_fund_flow` 周期表读取；`board_fund_flow` 的 3日/5日/10日/20日周期（含 `net_ratio` 阶段涨跌幅）是资金面数据、本期页面只展示「即时」、不参与价格排序（需求 §7.1「资金流 3/5/10/20 日数据继续采集但不参与价格排序」）。严禁把资金流周期表的 `net_ratio` 当价格涨幅用。
- **权限策略**：`sectors:view` 进 `BUSINESS_RESOURCE_CODES`（业务授权，非登录基线）；后端 `require_perm('sectors:view')` 守卫；采集操作 system-only（`data-task:manage` / `data-quality:view|fix`）；既有库一次性回填授权 + 同事务 bump `perm_ver`（marker 幂等）。
- **兼容策略**：`board_bar` 存原值不套复权链；`stock_basic.concept` 不写；新增表与 seed 全部幂等；`ThsBoardSource` 限速 ≥1s/次 + 分批断点。
- **关键取舍**：资金流无稳定代码时按名称匹配，未匹配写 `board_fund_unmatched` 质检不伪造代码；成分「只进不出」累积，完整快照才落库，候选机制废弃（2026-08-09 只进不出改造）。
- **🔴 表达式唯一索引已废弃（2026-08-09 只进不出改造）**：本条为候选机制时期的历史可行性记录（`CREATE UNIQUE INDEX ... (CASE WHEN status='applied' ...)` 控制每板块每日最多一个 applied 候选），随候选表删除已无对应索引，不再适用。保留仅作历史留档。

### 前端页面设计闭环

#### 页面定位

- 页面类型：P1 板块行情列表页（新增，list 原型）；P2 板块详情页（新增，detail 原型）。**P3 数据质量页候选操作列已废弃（2026-08-09 只进不出改造，见 T13）**——质量页经 `board_member_incomplete` 重采闭环恢复成分采集。
- 用户主流程：列表筛选/排序/搜索 → 点行切换观察板块 → 当前观察区查看详情 → 看指数走势与成分股 → 跳个股行情；系统管理员在数据质量页对 `board_member_incomplete` 行「重采成分」。
- 是否新页面：P1/P2 是；P3 改造已有页面（QualityView）。
- 是否改造已有页面：P3 是（仅表格列与操作扩展）。

#### 布局选型

- P1 选用原型：`list`。理由：单主表 + 顶部筛选 action 区，与 StocksView 同构；原型文件 `prototypes/sector-board.html` 即按 list 结构绘制。不需要新增布局原型。
- P2 选用原型：`detail`。理由：摘要区 + 主区 detail（图表 + 嵌套成分股表），与 StockDetailView 同构；原型文件 `prototypes/sector-detail.html`。不需要新增布局原型。
- 新增运行时复用组件：无（全复用 `AppDataTable`/`AppTableColumn`/`AppPagination`/`AppStateBlock`/`AppRowActions`/`PageSegmented`/`PageSettingsDrawer`/`TradeDatePicker`/`LayoutHost`/`usePageSettings`/`useEChartsTheme`；走势图为本页业务组件内 ECharts 实例，不沉淀通用组件）。
- 配置化接入：`sectors`、`sectors-detail` 两个 pageKey 进 pageRegistry；组件字段经 `componentMeta`/`consumedComponentFields`/`componentValueOf` 承载；业务偏好走 `usePageSettings`。

#### Slot 与组件设计

P1 `sectors`（master-detail，`responsiveProfile: 'mixed-panel'`，`minWidth=0`）：

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action | filter-bar | filter-bar | 否 | 不滚动 | 否 | 板块类型 `el-select`（全部/概念/行业）+ TradeDatePicker + 名称搜索框（`el-input` 防抖）+ 查询主命令按钮 |
| main | table | wide-table | 是 | 表体纵向滚动、列超宽时横向滚动 | 否 | 板块排行宽表 + AppPagination |
| overlay | settings | settings-drawer | 否 | 抽屉内滚动 | 否 | 页面设置（布局/组件设置/业务选项） |

P2 `sectors-detail`（detail，`responsiveProfile: 'single-column'`）：

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action | toolbar | toolbar | 否 | 不滚动 | 否 | 面包屑返回 + 页面设置入口 |
| main | detail | detail | 是 | 低高度时主内容区整体滚动兜底 | 否 | 摘要区 + 走势图 + 成分股表容器 |
| main | memberTable | data-table（parentId: detail，order: 2） | 否 | 表体内部滚动 | 否 | 成分股表（嵌套 slot，对齐 groupTable 模式） |
| overlay | settings | settings-drawer | 否 | 抽屉内滚动 | 否 | 页面设置（图表高度比例自动保存 + memberTable 组件设置） |

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

- 主操作：P1 列头排序/翻页/点行切换/勾选附加对比/查看当前板块详情；P2 周期切换/日期控件/翻页/返回；P3 对 `board_member_incomplete` / `board_index_gap` / `board_fund_unmatched` 问题复用质量页「修复」动作（异步 `:loading`）。
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

- 原型文件：`prototypes/sector-board.html`。当前承接区域：顶部筛选区（全市场/自选、板块类型、日期、搜索）、板块排行（默认板块/今日涨幅/5日涨幅/10日涨幅/即时净流入）、可收起的同屏走势区、标题说明、表体内部滚动与分页、设置抽屉和数据/空/错误/加载四态。原型只提供信息架构参考，当前重构后的同屏列表与图表交互为实现事实源。
- 原型与需求差异说明：
  1. 排行表默认展示板块/今日涨幅/5日涨幅/10日涨幅/即时净流入，类型与成分数合并到名称单元格；20日涨幅和多周期净流入通过设置启用，列总宽超过排行区域时由 `wide-table` 提供常显横向滚动条。当前观察摘要展示今日/5/10/20日涨幅、即时净流入和涨跌家数；列表与图表同屏，点行只切换观察对象，排行标题右上角的固定按钮可收起右侧分析区为全宽排行并保留上下文，同一位置负责再次展开。
  2. 列表页 `pageSize` 使用全局 `PAGE_SIZE_OPTIONS=[20,50,100,200]`；详情成分股保持业务专属 10/20/30/50。
  3. **领涨股取数来源**：按所选行情交易日有效成分股 `pct_chg` 最大者计算；停牌、缺收盘或缺有效前收者排除，同涨幅按成交额降序、代码升序稳定决胜。资金流源字段不参与页面口径。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 板块列表筛选（7.1.1） | R7、R10 | 默认全部板块 + 今日涨幅降序；切类型/排序/搜索（≤50 字符防抖） | action 区板块类型 `el-select`（全部/概念/行业）+ `TradeDatePicker` + `el-input` 防抖 + 查询主命令按钮；筛选态写 URL query（`type/sort/order/keyword/page`，`type` 为全部时省略）；偏好优先级 URL query > 已保存偏好 > 默认值 | SectorsView.vue、AppControlRow、TradeDatePicker、usePageSettings | `GET /api/sectors`（白名单参数） | 加载 `v-loading`；空态引导去采集页；错误 AppStateBlock 重试；无权限 permission 态 | T11 |
| 板块排行与观察联动（7.1.2） | R7 | 列头排序、服务端分页、点行切换当前板块、勾选附加对比、列显隐、宽表横向滚动、收起/展开走势分析、标题说明 | `AppDataTable(kind=wide-table)` + AppPagination 与右侧走势图组成 master-detail；列宽由全局 `AppTableColumn` 根据语义、表头长度、排序控件、同行元信息与主内容前置控件推导，资金日期使用标准 `header-meta` 同行表头；`defaultSort/pageSize/hiddenColumns` 走 `componentValueOf('table', ...)`；每个 `componentMeta.columns` 候选必须进入真实显隐判断；分析区展开状态走 `usePageSettings`；切换按钮固定在排行标题右上角；说明复用 `HelpTip`；「查看详情」位于当前观察身份区 | AppDataTable、AppTableColumn、AppPagination、SectorCompareChart、HelpTip、pageRegistry `sectors` | `GET /api/sectors` | 空值列显示「—」；资金流列标注数据日期；表头不换行并与主内容对齐；列超宽时滚动条常显且可真实横移；分页越界回落；收起不清空观察和对比状态 | T11 |

组件资产闭环（P1）：

| 页面/区域 | 运行时复用组件 | 布局或配置组件种类 | 组件配置字段/页面注册 | 设计规范或组件清单更新 | 真实消费与验证 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| P1 全页 | 复用 | 复用 | 新增 `sectors` pageKey 注册（action+main+overlay 自动补登） | 是：DESIGN.md `page-registry` 区块补一行 | SectorsView 真实消费 + pageRegistry.spec.ts 契约测试 | T11、T15 |

### 4.2 页面 P2（板块详情页）技术实现

- 原型文件：`prototypes/sector-detail.html`。保留摘要、图表、成分股三层结构；图表范围按用户统一要求改为全局 `KlineRangeSelect`（近 60/120/250 日/全部），指数区复用个股详情 `StockChartWorkspace` 的 K 线 + 量能双面板和高度分隔拖拽，不沿用原型的月/季/半年/年分段。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 板块摘要卡（7.2.1） | R8、R14 | 名称/类型/成分数/今日涨幅/涨跌家数/即时净流入(含数据日期)/领涨股及涨幅；随路由 code 刷新 | 摘要区（DESIGN 统计项语义）；涨幅与净流入分别标注各自数据日期；领涨股按行情截面日有效成分股涨幅第一计算 | SectorDetailView.vue | `GET /api/sectors/{code}` | 板块不存在 → error 态「板块不存在或数据未采集」；空值显示「—」 | T12 |
| 板块指数走势图（7.2.2） | R8、R11 | 默认近 120 日；范围与个股统一；横向缩放限制在当前周期；走势默认对比中证 500，可切沪深 300/不对比；**多口径对比（2026-08-13 修订）**：头部指标槽点击切换，趋势指标折线、截面指标柱状，累计涨跌双基期；K 线高度可调整 | 列表/详情复用 `klineRangeQueryStart` 预取并按交易点精确截断，板块走势与指数基准共享截断日期；`SectorCompareChart` 按 `metric` 折线/柱状两分支，趋势指标以虚线区分市场指数并在 tooltip 计算超额涨跌，截面指标柱状且不叠加指数；累计·近一年基期强制 250 交易日区间；指标口径纯函数在 `utils/sectorCompare.ts`；详情复用 `StockChartWorkspace` + `KlineRangeSelect` + `useStockChartPreferences`，K 线与量能联动，高度比例单独持久化 | SectorsView.vue、SectorDetailView.vue、StockChartWorkspace、SectorCompareChart、KlineRangeSelect、AppFilterSelect | `GET /api/sectors/{code}/bars`、`GET /api/sectors/benchmarks/{index_code}/bars` | 板块走势失败进入图表错误态；基准失败降级显示板块走势并在图表脚注明 | T12 |
| 成分股表（7.2.3） | R8、R9、R13 | 统一分页（默认 20，抽屉可配 10/20/30/50）；列头排序（默认涨跌幅降序）；有 `stocks:view` 点行跳 `/stocks/:code`，无权限行禁用 + hover 提示；从个股返回原板块详情 | AppDataTable（嵌套 slot `memberTable`，parentId=detail）+ AppPagination；进入个股前通过共享 `stockSet` 写入当前成分股集合及 `route.fullPath` 返回地址，覆盖其它页面遗留集合；`componentValueOf('memberTable', ...)` 消费 pageSize/defaultSort/hiddenColumns | AppDataTable、AppPagination、stockSet、pageRegistry `sectors-detail` | `GET /api/sectors/{code}/members?page=&size=`（size 默认 20） | 空态/错误重试；直接访问 `/stocks/:code` 路由守卫 fail-closed（现有机制） | T12 |
| 返回列表保留筛选态（R8） | R8 | 面包屑/返回按钮始终 `router.replace` 显式跳列表并带白名单校验后的来源 query；无/非法来源 query 落默认；不使用 `router.back()`；浏览器原生后退按 history 还原 | 列表 URL query 承载筛选态；进详情时来源 query 透传进详情 URL；返回前白名单校验（`type/sort/order/keyword/page`） | vue-router、SectorsView/SectorDetailView | - | 非法 query 逐字段丢弃落默认 | T12 |

组件资产闭环（P2）：

| 页面/区域 | 运行时复用组件 | 布局或配置组件种类 | 组件配置字段/页面注册 | 设计规范或组件清单更新 | 真实消费与验证 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| P2 全页 | 复用（走势图为本页业务组件内 ECharts 实例） | 复用 | 新增 `sectors-detail` pageKey 注册 + `memberTable` 嵌套 slot（componentMeta sortFields=pct/code；consumedComponentFields=pageSize/defaultSort/hiddenColumns） | 是：DESIGN.md `page-registry` 区块补一行 | SectorDetailView 真实消费 + pageRegistry.spec.ts 契约测试 | T12、T15 |

### 4.3 页面 P3（数据质量页）技术实现

- **🔴 候选操作列已废弃（2026-08-09 只进不出改造，见 T13）**：数据质量页不再有候选确认/丢弃功能。成分采集完整性由 `board_member_incomplete` issue + 质量页「重采成分」（fix 分派）闭环恢复。
- 变更区域：无（质量页保留现有结构，`board_member_incomplete` 行可触发「重采成分」恢复动作）。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 成分采集不完整重采 | R2 | `board_member_incomplete` 待处理行提供「重采成分」动作；完成后刷新列表 | QualityView 复用现有列表，`board_member_incomplete` 行触发 fix（重采该板块成分） | QualityView.vue | `POST /api/data/quality/{id}/fix` | fix 任务执行；加载/空态/错误复用现有 | T13（原候选列废弃，替代为重采） |

组件资产闭环（P3）：复用现有质检页全部组件；不新增 pageKey、不新增组件种类、不新增配置字段；设计规范无需更新（无布局变化）；真实消费验证归 T15。

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R1 | 板块字典采集（概念+行业并集）落 `board_dict` | ThsBoardSource.get_board_dict + 两阶段字典 seed/资金流并集补充 + 能力字段收口 + app_code(clid) 抓取 | T2、T4 | 已完成 | 一致 | T2/T4 已落地（数据源+采集服务） |
| 必须实现 | R2 | 板块成分股快照采集（只进不出） | 完整快照 `(board_code, code)` 累积 + 完整性即闸门（不完整不落库）+ `member_count` 刷新 + `board_member_incomplete` 重采闭环 | T2、T3、T4 | 已完成 | 一致（2026-08-09 只进不出修订；2026-08-10 周频修订） | T2/T3/T4 已落地；**候选机制（T9/T13）已废弃**——成分模型改只进不出后删除候选表/接口/质检页操作，替代为 `board_member_incomplete` issue + fix 重采；**成分更新周频（2026-08-10）**：`member_snapshot_at` 距今 ≥ `member_update_interval_days`（默认 7，`ths_board` 配置可调）或 IS NULL 才重拉，未到期记 `skipped` 跳过（不计失败/不写质检），`force=True`（质量修复/backfill/CLI `--force-members`）绕过 |
| 必须实现 | R3 | 板块指数采集落 `board_bar`（原值） | get_board_bar + 幂等 upsert + 源端可用年限回填（实测近 3 年，2024 起）/每日增量 | T2、T4、T6 | 已完成 | 一致 | T2/T4/T6 已落地；**源端指数历史仅近 3 年（2021-2023 404），各板块起始日不同属正常** |
| 必须实现 | R4 | 板块资金流采集落 `board_fund_flow` | 概念+行业全周期采集 + 并集映射（未匹配写质检不伪造代码） | T2、T4 | 已完成 | 一致（2026-08-10 口径更新） | T2/T4 已落地；资金流独有板块：链接带真实路径 code → `_upsert_fund_only_boards` 补字典（has_fund_flow=true，不进页面展示）；无稳定代码 → `board_fund_unmatched` 质检 |
| 必须实现 | R5 | 板块采集异步任务（`board` 进任务中心） | TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES 注册 + `_h_board` + 按字典类型/板块/资金流周期 checkpoint + 任务中文标签 | T5 | 已完成 | 一致 | T5 已落地；部分失败保留 checkpoint，失败任务可续跑 |
| 必须实现 | R6 | 板块维度注册 + 数据概览可见 | `_DIMENSION_SEED` 加 `board` 维度行（tables=4 表）+ 数据管理概览板块统计卡 | T3 + 本轮复核修复 | 已完成 | 一致 | 除维度行外，概览已展示表行数、概念/行业数、成分/指数/资金流覆盖、最新日期、未闭环问题和最近更新 |
| 必须实现 | R7 | 板块行情列表页 `/sectors` | SectorsView（筛选/主表/分页/列显隐/列头排序语义）+ `/api/sectors` | T8、T11 | 已完成 | 一致 | T8 `/api/sectors` 列表接口 + T11 SectorsView 页面均已落地；分页走全局 `PAGE_SIZE_OPTIONS`（2026-08-11 纠偏） |
| 必须实现 | R8 | 板块详情页 `/sectors/:code` + 返回保留筛选态 | SectorDetailView（摘要/走势图/成分股表）+ URL query 筛选态承载与显式返回 + 详情 3 接口 | T8、T12 | 已完成 | 一致 | T8 接口与 T12 页面均已落地，显式返回、浏览器历史和菜单最近详情恢复已覆盖 |
| 必须实现 | R9 | 成分股跳转个股详情（权限感知） | `hasPermission('stocks:view')` 行可点性 + 禁用态 hover 提示 + 直接访问 fail-closed 验证 | T12、T14、T15 | 已完成 | 一致 | T14 新增 `debug_sectors_only` 最小权限身份，真实浏览器验证成分股禁用且直达个股路由 fail-closed |
| 必须实现 | R10 | 板块搜索 | 自由文本搜索框（el-input 防抖）+ 服务端 `keyword` 参数 + 无结果空态 | T8、T11 | 已完成 | 一致 | T8 服务端 keyword + T11 搜索框（≤50 字符防抖）均已落地 |
| 可选增强 | R11 | 统一 K 线范围与高度拖拽 | 全局范围选项 + 行情多图工作区 + 高度比例持久化 | T12 | 已完成 | 一致 | 本次纳入 |
| 可选增强 | R12 | 板块维度数据质检（指数缺口） | data_report 板块指数缺口扫描 + 复用 `data_quality_issue` | T7 | 已完成 | 一致（2026-08-09 只进不出修订） | 本次纳入；成分数波动不再质检（源端重组非错误），`board_member_incomplete` 覆盖采集完整性 |
| 可选增强 | R13 | 详情页成分股统一分页 | members 接口服务端分页 + AppPagination + pageSize 组件字段 | T8、T12 | 已完成 | 一致 | members 服务端分页、AppPagination 与 pageSize 配置闭环已落地 |
| 可选增强 | R14 | 详情页资金流统计卡 | 摘要卡即时净流入（最新 snapshot_date period=即时） | T8、T12 | 已完成 | 一致 | 详情摘要已展示即时净流入及独立资金日期 |
| 必须实现 | R21 | 采集流程集成（daily/回填/增量/断点/失败隔离） | DailyPipeline 加 `board: bool = True` 步骤 + CLI `board --backfill/--update` + `--skip-board` + 类型/指定板块/阶段范围 + 失败清单与部分失败降级 + 参数化测试矩阵 | T5、T6 + 本轮复核修复 | 已完成 | 一致 | daily、CLI、任务中心、采集页和调度页已对齐；`ok=false` 正确落 failed，成功单元不重复续跑 |
| 必须实现 | R22 | 页面/RBAC 接入 | 菜单/资源 seed + `sectors:view` 进 BUSINESS_RESOURCE_CODES + 既有库回填 + bump perm_ver + 路由守卫 + pageRegistry 登记 | T10a、T10b、T11、T12、T14 | 已完成 | 一致 | 菜单、资源、接口守卫、默认授权、详情子路由、按钮 `v-permission` 与最小权限浏览器验收已闭环 |
| 必须实现 | R23 | 页面配置闭环 | 两页业务偏好、全局 K 线范围、`chart.minHeight` 与表格组件字段保存/读取/消费/回退 + 构建/布局/三视口验收 | T11、T12、T14、T15 | 已完成 | 一致 | pageRegistry、前后端字段守门、抽屉渲染、页面真实消费、单测、构建和三视口 E2E 已闭环 |
| 暂不实现 | R15 | 地域/风格板块 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 第一期只做概念+行业 |
| 暂不实现 | R16 | 资金流历史趋势图 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本期只做统计卡数字 |
| 暂不实现 | R17 | 题材联动图谱/重叠分析 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 独立后续需求 |
| 暂不实现 | R18 | 东财指数交叉验证 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 东财源不稳 |
| 暂不实现 | R19 | 板块成分作为筛选/回测条件 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 需筛选引擎+回测扩展 |
| 暂不实现 | R20 | 板块强弱热力图 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 需图表组件扩展 |
| 暂不实现 | R24 | 审计可靠性提升 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 本期审计 best-effort |
| 已废弃 | R25 | 同日候选替换 | 已废弃（2026-08-09 只进不出改造） | - | 跳过 | 废弃 | 候选机制整条删除 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：数据/权限/接口契约冻结

- 状态：已完成（2026-08-09 T1 执行）
- 依赖：无（需求已确认无阻塞项）
- 涉及文件/模块：本 plan.md §4/§7；需求文档 §6
- 目标：冻结 4 表 DDL 字段与约束、`/api/sectors*` 接口契约、`sectors:view` 权限 seed 与回填方案、板块指数缺口质检规则。**候选机制契约已删除（2026-08-09 只进不出改造，见 T9/T13 废弃说明）**。
- 操作：以本计划 §4 技术方案为契约文本，开发前对照需求 §6.1/§6.2 逐项核对；发现与代码现状冲突时回到用户确认。
- 产出：评审通过的契约（本计划章节）。
- 影响范围：后续全部任务。
- 边界与异常：契约变更需回到本任务修订。
- 验证方式：计划评审确认。
- 完成标准：契约无待确认阻塞项。
- 实际落地情况：已核验（2026-08-09 T1 执行）——5 表 DDL/接口/权限/配置契约逐项对照代码现状成立；补 1 处契约：R12 阈值需 `Settings` 模型加子模型字段（Pydantic default_factory），与 settings.yaml 节、CONFIG_GROUPS 白名单三者配套（见 §7.4）。**🔴 只进不出改造后契约为 4 表**（候选表删除），本条为 T1 当时快照。

### 6.2 任务 T2：`ThsBoardSource` 数据源适配器

- 状态：已完成（2026-08-09 T2 执行）
- 依赖：T1
- 涉及文件/模块：`backend/datasource/ths_board.py`（新增，文件名对齐 research.md 附录建议结构）、`backend/datasource/base.py`（仅复用装饰器）、`requirements.txt`/`pyproject.toml`（显式声明 `py_mini_racer`）、`backend/tests/test_ths_board_source.py`（新增）
- 目标：封装同花顺板块取数：字典（概念/行业）、成分股（AJAX 翻页 + v cookie + 两种排序策略取多者）、指数日线、资金流（概念/行业 × 5 周期）、app_code(clid) 详情页抓取。
- 操作：新建**独立普通类** `ThsBoardSource`（**不继承 `DataSource`、不修改该抽象**——`DataSource` 的 5 个抽象方法全是个股时间序列接口，板块关系型数据硬塞会破坏抽象一致性；此口径承接 research.md 附录《同花顺板块适配器封装决策》与 requirement-closure.md §189 的已确认决策）；仅复用 base.py 的 `rate_limited(≥1s)`/`with_retry` 装饰器；由 `IngestionService` 直接持有实例，不进 `_source_for` 选源链。v cookie 经 `py_mini_racer` 执行 akshare 打包的 `ths.js` 生成（本机 akshare 1.18.64 实测含 `akshare/data/ths.js`、`akshare/stock_feature/ths.js`），401 时刷新 cookie 重试；翻页走路径参数 `page/N/ajax/1/`；分页完整性检测（缺页/请求失败标记不完整）；请求超时注入。
- 产出：适配器 + 单测（mock HTTP：v cookie 生成/401 刷新/翻页/两种排序取多者/不完整快照标记/资金流解析）。
- 影响范围：采集层（R1-R4 数据源）。
- 边界与异常：不调用 akshare 板块公开函数；不继承 `DataSource`、不并入 `AKShareSource`（research 附录备选方案已明确否决）；限流不低于 1s/次。
- 验证方式：`python -m pytest backend/tests/test_ths_board_source.py -q`。
- 完成标准：单测全绿；实测可拉通一个概念板块全部分页（人工冒烟，只读外部源不涉及 DuckDB 锁）。
- 实际落地情况：已实施（2026-08-09 T2 执行）——`backend/datasource/ths_board.py` 新建（独立普通类，复用 `rate_limited`/`with_retry`，经 `importlib.resources` 读 akshare 打包 `ths.js` 生成 v cookie）；`requirements.txt`/`pyproject.toml` 显式声明 `py_mini_racer>=0.8`；16 个单测全绿（mock HTTP：v cookie/401 刷新/翻页/两种排序取并集/登录墙截断标不完整/字典全量合并/指数解析/资金流解析）；真实冒烟通过：概念字典 375 / 行业 90 / AI PC 概念成分 50 / 半导体行业成分 100 / 指数日线 / 概念资金流 387 / 行业资金流 90。**实测发现 1：成分股翻页第 6 页起必触发同花顺登录墙**（HTTP 200 但返回 `upass...login` 跳转壳，单发第 6 页同样命中，非频率触发）——单板块最多稳定取 5 页（概念 50 只/行业 100 只），适配器对登录墙页标记 `complete=False`（数据可能被截断，供采集层走 R2 不完整快照保护），见 §10.1 新增风险。**实测发现 2：概念字典 = 分类页 351 ∪ `gn/index` 前 3 页净增 24 = 375**，适配器已按此合并（登录墙即停，比 akshare 空翻 39 页更省）。**实测发现 3（登录态解除登录墙，2026-08-09 用户提供浏览器登录 cookie 实测）**：登录态下详情页第 6 页正常返回数据（半导体完整 120 只），登录墙解除；代价是数据中心 IP 连续请求触发动态风控（401/空页），适配器新增 `login_cookie` 参数 + `AI_STOCKS_THS_COOKIE`/`_FILE` 环境变量支持（浏览器登录后复制，不硬编码不入库），限速默认 1s/次且改走 `ths_board.min_interval_sec` 配置（2026-08-09 配置化：见版本注记，`ThsBoardSource` 从 `get_effective_settings().ths_board` 注入）。

### 6.3 任务 T3：DuckDB 5 表 DDL + 板块维度注册

- 状态：已完成（2026-08-09 T3 执行；只进不出改造后删候选表）
- 依赖：T1
- 涉及文件/模块：[ddl.py](../../backend/storage/ddl.py)（4 表 + `_DIMENSION_SEED` 加 `board` 行）、`backend/tests/`（DDL 幂等与约束测试）
- 目标：落地 `board_dict`/`board_member`/`board_bar`/`board_fund_flow` 4 表（字段按需求 §6.1；`board_member` 为只进不出 `(board_code, code)` 主键，候选表已废弃删除）+ `member_snapshot_at` 列；`board` 维度 status=collected、tables=4 表。
- 操作：按 ddl.py 既有建表模式新增；DDL 幂等（重复 init 不报错）；维度 seed 幂等。候选机制（payload_hash/表达式唯一索引）已废弃，见版本注记「只进不出改造」。
- 产出：DDL + 单测（建表幂等、board_member `(board_code, code)` 主键冲突拒绝、维度行存在）。
- 影响范围：DuckDB schema；数据概览「数据资产表」新增一行。
- 边界与异常：无既有数据迁移（全新表）。
- 验证方式：单测 + 启动后数据概览接口可见 board 维度。
- 完成标准：4 表创建成功、主键约束生效、维度注册可见。
- 实际落地情况：已实施（2026-08-09 T3 执行）——`backend/storage/ddl.py` 新增 `M_BOARD_TABLES`（5 表：board_dict/board_member/board_bar/board_fund_flow/board_member_candidate，含 payload_hash CHECK `regexp_full_match`、候选唯一约束、表达式唯一索引 `uq_board_member_candidate_one_applied`）+ `_DIMENSION_SEED` 加 board 行 + `init_db` 注册；`backend/tests/test_ddl.py` 新增 7 个板块用例（建表幂等/维度行/CHECK 拒非法/同日同 hash 唯一/表达式索引 INSERT+UPDATE 两路径拦截/跨板块跨日 applied/双表 PK），共 17 用例全绿。**🔴 2026-08-09 只进不出改造后本任务产物已变更**：`board_member` 改 `(board_code, code)` 主键、`board_member_candidate` 表删除、候选约束/表达式索引移除，当前为 4 表（见版本注记）；本条为 T3 当时的历史快照。

### 6.4 任务 T4：板块采集服务（字典/成分快照/指数/资金流）

- 状态：已完成（2026-08-09 T4 执行；只进不出改造后成分改为累积落库）
- 依赖：T2、T3
- 涉及文件/模块：`backend/services/board_ingest.py`（新增，或并入 ingest.py 按既有分层取舍）、`backend/services/ingest.py`（`ingest_board(ctx)` 编排）、[duckdb_client.py](../../backend/storage/duckdb_client.py)（**新增 `transaction()` 上下文管理器**）、`backend/tests/test_board_ingest*.py`（新增）
- 目标：实现 R1-R4 采集逻辑与 R2 候选保存（原子事务①）。
- 操作：
  1. 字典两阶段：概念/行业字典 upsert（阶段一）→ 资金流补充并集映射 + `has_fund_flow`（阶段二）→ 能力字段与 `last_seen_at` 收口、`member_count` 在完整快照落库后刷新。
  2. 成分快照（只进不出）：逐板块 `get_board_members` → 完整性判定（缺页/失败/登录墙标 `complete=False`）→ 完整快照 `INSERT ON CONFLICT (board_code, code) DO NOTHING` 落库 + 刷新 `member_count`/`member_history_start_date`；**不完整快照整趟不落库**，`data_update_log` failed + 写 `board_member_incomplete` issue（质量页重采闭环）。**候选机制已废弃**（2026-08-09 只进不出改造，见 T9）。
  3. 指数：幂等 upsert 原值；资金流：全周期 upsert + 名称匹配映射、未匹配写质检不伪造代码；净额=流入-流出校验。
  4. 单板块失败跳过记日志不中断，失败板块进入清单（供 T6）。
  5. `DuckDBClient.transaction()`：现有 `execute()` 按调用持 RLock，多语句 BEGIN..COMMIT 块之间会被其他线程 SQL 插入（破坏原子性）；新增上下文管理器在整个事务块内持 RLock，多语句写块（如成分落库 + member_count 刷新）统一走它。**写锁冲突识别机制（T4 定稿，2026-08-09 实测）**：DuckDB 写锁是文件锁，跨进程冲突**立即失败**（实测 0.006s 抛 `IOException: Could not set lock on file ... Conflicting lock is held`），本机 DuckDB 1.5.3 **无锁等待配置**（`SET duckdb_max_lock_wait_time` 抛 `CatalogException: unrecognized configuration parameter`，已实测）；因此不设置任何锁等待超时，识别完全靠**异常消息关键字归类**——`duckdb_client` 的 `except Exception` 会把 connect/execute 抛的 IOException 包进 `StorageError`（实测消息含 "Could not set lock ... Conflicting lock"），`transaction()` 异常包装层匹配 `lock`/`Cannot open`/`Another client`/`busy` 关键字 → 归类为软失败 `duckdb_write_unavailable`，其余按普通 `StorageError` 500。**连接恢复语义（2026-08-09 实测，无需显式释放）**：写模式 connect 即获文件锁，冲突只发生在 connect 阶段（无「连接已建立后执行语句才冲突」的中间态）；`conn` property 仅在 connect 成功后赋值 `self._conn`，connect 抛异常时 `_conn` 保持 `None`，`execute/query_df` 的 `self._conn=None` 为幂等无害操作，`close()` 在 `_conn is None` 时跳过——锁释放后同一实例重试即自动重建连接恢复（实测 0.02s 成功），**无需显式释放连接**；`transaction()` 仅做关键字归类，不添加连接释放逻辑。现有同步短写先例（data_admin.py quality_reset/ignore）为单语句不受影响。
- 产出：采集服务 + `transaction()` 助手 + 单测（只进不出落库 ON CONFLICT 幂等、不完整快照不落库、资金流映射与未匹配质检、member_count 刷新、事务原子性——中途失败整体回滚、**跨进程写锁冲突归类 `duckdb_write_unavailable` 且锁释放后重试可恢复**）。
- 影响范围：DuckDB 4 表写入；`data_quality_issue` 新增 issue 类型 `board_member_incomplete`。
- 边界与异常：快照日期 = Asia/Shanghai 实际成功采集日期；成分股代码补交易所后缀对齐 `stock_basic.code`。
- 验证方式：`python -m pytest backend/tests/test_board_ingest*.py -q`（跑前先 `./start.sh status` 确认后端已停，结束按原状态恢复，遵守 DuckDB 锁规则）。
- 完成标准：R1-R4 验收标准中可用单测覆盖的部分全绿。
- 实际落地情况：已实施（2026-08-09 T4 执行）——`backend/services/board_ingest.py` 新建 `BoardIngestService`（字典两阶段 upsert / 成分快照 diff [in_date,out_date) / 候选保存事务① / 指数幂等 upsert / 资金流名称映射+未匹配写质检）；`backend/storage/duckdb_client.py` 新增 `transaction()` 上下文管理器（RLock 跨 BEGIN..COMMIT + 写锁关键字归类 `_LOCK_CONFLICT_RE` + 异常回滚 + 连接重建语义）；`backend/services/ingest.py` 新增 `ingest_board` 编排（单步骤失败隔离返回失败清单）。10 个单测全绿（diff 区间/不完整快照不退出 diff/payload_hash 规范化与幂等四态/波动拦截/member_count 刷新时机/事务原子性回滚/写锁关键字归类/资金流映射与未匹配质检）。`transaction()` 文件库实测：提交成功、中途失败整体回滚、连接重建后表仍在。**🔴 2026-08-09 只进不出改造后本任务产物已变更**：成分改为 `(board_code, code)` 累积落库、删候选/diff/payload_hash，见 T9 废弃说明与版本注记。

### 6.5 任务 T5：`board` 异步任务类型注册

- 状态：已完成（2026-08-09 T5 执行）
- 依赖：T4
- 涉及文件/模块：[async_task.py](../../backend/services/async_task.py)（TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES + `_h_board`）、[data.ts](../../frontend/src/api/data.ts)（任务类型中文标签「板块采集」）、`backend/tests/`（任务注册/取消/续跑测试）
- 目标：`board` 任务可创建/看进度/取消/续跑，checkpoint 按字典类型、成分/指数板块代码及资金流类型+周期记录，续跑跳过已成功工作单元；纳入 DuckDB 写任务互斥。
- 操作：按现有任务类型同款模式注册；handler 调 `ingest_board(ctx)`；进度按 board_code 推进。**命名空间边界声明**：任务类型 `board` 与既有「每日榜单」的 `/board` 路由、`board:view`/`board:compute` 资源码、`board_bar` 等表名处于同一语义空间，但技术命名空间不同（task type vs resource code vs 表名），不构成功能冲突；代码/日志/运维中注意区分——任务类型用 `task.type='board'`，资源码用 `board:view`（榜单），接口用 `/api/sectors*`（板块行情），表用 `board_dict/board_member/...`（板块数据）。前端任务中文标签「板块采集」避免与「每日榜单」资源名混淆。
- 产出：任务注册 + 单测 + 前端标签。
- 影响范围：任务中心新增任务类型；无既有任务行为变化。
- 边界与异常：复用现有失败/中断/续跑机制。
- 验证方式：单测 + 任务中心页面创建板块采集任务人工确认（T15 回归覆盖）。
- 完成标准：R5 验收通过。
- 实际落地情况：已实施（2026-08-09 T5 执行，后续复核加固）——`backend/services/async_task.py` 注册 `board` 任务类型（TASK_TYPES/WRITE_TASK_TYPES/TASK_CAPABILITIES + `_h_board` handler），checkpoint 已细化为字典类型、成分/指数板块代码、资金流类型+周期；任务结果 `ok=false` 时正确标记 failed 并保留 checkpoint，失败任务可从未成功工作单元续跑；`frontend/src/api/data.ts` 加 `board` 到 TaskType 联合与 TASK_LABEL「板块采集」。

### 6.6 任务 T6：CLI `board` 命令族 + daily 流程集成

- 状态：已完成（2026-08-09 T6 执行）
- 依赖：T4、T5
- 涉及文件/模块：[cli.py](../../backend/cli.py)（`board --backfill` / `board --update` / `daily --skip-board`）、[pipeline.py](../../backend/services/pipeline.py)（`run(..., board: bool = True)` + 步骤 + total_steps + 失败隔离）、`backend/tests/`（参数化测试矩阵）
- 目标：R21 全部语义落地。
- 操作：`DailyPipeline.run()` 新增 `board: bool = True`；板块步骤在「更新数据」之后顺序执行；`skip_update=True` 仍采集板块；`--skip-board` 跳过；`total_steps` 同步计入；板块步骤失败不提前 return、继续质检等后续步骤，但最终 `ok=false`；单板块失败记录清单并继续，步骤/任务最终标 `failed`，续跑仅重试失败项。
- 产出：CLI/管道改动 + 参数化测试矩阵（`board=True` 默认执行、`skip_update=True` 仍执行、`--skip-board` 确实跳过、板块失败后继续质检、最终状态与失败清单正确、`total_steps` 不出现 `3/2`）。
- 影响范围：每日流程、CLI；既有 `daily` 默认行为变化（新增板块步骤，默认开启）。
- 边界与异常：「不阻塞」= 不中断主流程执行，而非任务整体成功。
- 验证方式：参数化矩阵单测 + CLI 冒烟 `python -m backend.cli board --backfill`（4 表有数据）。
- 完成标准：R21 验收通过。
- 实际落地情况：已实施（2026-08-09 T6 执行）——`backend/services/pipeline.py` `DailyPipeline.run` 新增 `board: bool = True`（板块步骤在更新后顺序执行，`total_steps` 同步计入，`skip_update=True` 仍采集板块，板块失败不提前 return 继续质检但最终 `ok=false`）；`backend/cli.py` 新增 `board` 命令族（`--backfill`/`--update`）与 `daily --skip-board`。4 个参数化测试全绿（board 默认执行 / board=False 跳过 / 板块失败继续质检但 ok=false / total_steps 步骤分段正确）。

### 6.7 任务 T7：板块维度质检规则 + 阈值配置化

- 状态：已完成（2026-08-09 T7 执行；只进不出改造后调整为指数缺口扫描）
- 依赖：T4（成分/指数写入链路）
- 涉及文件/模块：[data_report.py](../../backend/services/data_report.py)（板块指数缺口扫描规则）、`backend/tests/`（质检规则测试）
- 目标：R12——板块指数缺口扫描（`board_bar` 最近交易日滞后 `daily_bar` 全局最新交易日 → `board_index_gap`），写 `data_quality_issue`。**🔴 2026-08-09 只进不出修订：成分数波动不再质检**（源端真实重组非错误），`board_member_wave` 扫描与 `member_surge_shrink` 候选恢复整条删除（见 T9/T13 废弃）。
- 操作：
  1. 复用现有质检扫描框架新增板块指数缺口规则。
  2. **issue 判重与收敛策略（明确，承接现有 data_report 收敛模式）**：板块自动扫描类问题沿用现有「扫描前清上轮**未解决**的同类 open 问题 + 已 resolved/ignored 不动」收敛模式，反复跑不堆积。
- 产出：质检规则 + 单测（指数缺口扫描触发/不误报）。
- 影响范围：数据质量页出现板块指数缺口问题。
- 验证方式：单测。
- 完成标准：R12 验收标准中指数缺口扫描部分通过。
- 实际落地情况：已实施（2026-08-09 T7 执行）——`backend/services/data_report.py` 新增 `scan_board_quality()`（成分数波动 `board_member_wave` + 指数缺口 `board_index_gap` 扫描写 issue）；`backend/config/settings.py` 加 `BoardQualityConfig` 子模型（relative_change_ratio=0.5/absolute_change_threshold=20）+ `Settings.board_quality` 字段；`config/settings.yaml` 加阈值基线；`backend/dataquality/checker.py` SCAN_ISSUE_TYPES 加 board_index_gap/board_member_wave（收敛可清）**且不含 member_surge_shrink**（候选关联 open issue 不被误删）。4 个单测全绿（成分数波动触发/指数缺口/配置三环/收敛不误删 member_surge_shrink）。**2026-08-09 修订（用户反馈）：`board_quality` 降级为仅 YAML 基线，从 CONFIG_GROUPS 移除（低频稳定参数不做 Web 在线配置）；同花顺请求参数改走新增 `ths_board` 覆盖层白名单（见版本注记）**。

### 6.8 任务 T8：`/api/sectors*` 只读 API + 查询服务

- 状态：**已完成（2026-08-09 T8 执行）**
- 依赖：T4（数据来源）；**T10a（常量 + 资源 seed 前置部分）须先行或与 T8 同批交付**——T8 的 403/权限验收隐含依赖 `sectors:view` 进 `BUSINESS_RESOURCE_CODES` 与资源 seed，不可晚于 T8 收尾（T10a 依赖仅 T1，无环）
- 涉及文件/模块：`backend/api/sectors.py`（新增路由）、`backend/services/board_query.py`（新增查询服务）、`backend/main.py`（挂路由）、`backend/tests/test_sectors_api*.py`（新增）
- 目标：板块列表/详情/bars/members 四类只读接口及市场指数基准 bars 按需求 §6.2 契约要点实现。
- 操作：参数白名单校验（未知参数 400）；`sort_by` 稳定字段码；统计口径（涨幅收盘价对比、历史不足「—」、涨跌家数口径、最新交易日双口径显式返回）；`trade_date` 截面语义；空值「—」；404/400/403；members 服务端分页（size 默认 20）；板块数 <600 单次全查内存合并（双库边界：只读 DuckDB，成分股现价/涨跌幅/换手取个股行情表同库关联）；涨幅从 `board_bar` 实时计算，不从资金流周期表读；领涨股按行情截面日有效成分股 `pct_chg` 最大者计算，并在同一次聚合中得到涨跌家数；列表只展示 `has_members` 或 `has_bar` 为 true 的板块。
- 产出：接口 + 服务 + 单测/接口测试（口径与 DuckDB 对账）。
- 影响范围：新增只读接口，无既有接口变化。
- 边界与异常：不跨库 JOIN；资金流数据日期与涨幅数据日期分别返回。
- 验证方式：接口测试 + 与 DuckDB 抽验对账（涨幅/净流入/成分数）。
- 完成标准：R7-R10、R13、R14 的数据层验收通过。
- 实际落地情况：`BoardQueryService` 提供列表/详情/bars/members 四查询；涨幅从 `board_bar` 实时计算，净流入取资金流最新即时行，领涨股与涨跌家数在一次成分股行情聚合中按所选交易日计算，避免 N+1；同涨幅按成交额/代码稳定决胜。接口参数白名单、404/400/403 与分页排序均有测试覆盖。

### 6.9 任务 T9：候选成分快照接口（查询/确认应用/丢弃）

- 状态：**废弃（2026-08-09 只进不出改造）**
- 废弃原因：成分模型改为「只进不出」后，候选机制整条删除（`board_member_candidate` 表、`member_surge_shrink`/`board_member_wave` issue 类型、`/api/data/board-candidates` 接口、数据质量页候选确认/丢弃全部移除）。本任务承载的候选查询/应用/丢弃接口不再需要，**不再实施**。
- 替代闭环：成分采集不完整 → `board_member_incomplete` issue → 数据质量页「重采成分」（fix 分派重采该板块，完整快照 `INSERT ON CONFLICT DO NOTHING`）。详见版本注记「成分模型改为只进不出」。

### 6.10 任务 T10a：RBAC 常量 + seed（前置部分）

- 状态：**已完成（2026-08-09 T8 同批交付）**
- 依赖：T1（无其他依赖，供 T8/T10b 先行消费，消除原 T8↔T10 双向依赖环）
- 涉及文件/模块：[constants.py](../../backend/auth/constants.py)（`BUSINESS_RESOURCE_CODES` 加 `sectors:view`）、[pg_ddl.py](../../backend/storage/pg_ddl.py)（`_SEED_MENU_TREE` quotes 下加 `/sectors` 子菜单 visible=login、`_SEED_RESOURCES` 加 `sectors:view` GET `/api/sectors*` 挂 `/sectors`）
- 目标：R22 后端 seed 部分——常量与 seed 幂等落地，使 T8 的 403/权限验收可依赖。
- 操作：`sectors:view` 进 `BUSINESS_RESOURCE_CODES`；`_SEED_MENU_TREE` 在 quotes 下加「板块行情」子菜单；`_SEED_RESOURCES` 加 `sectors:view` 资源行；沿用既有 `ON CONFLICT (id) DO NOTHING` 幂等插入方式。**部署时序约束：菜单 seed 生效不得早于前端路由上线**——`_SEED_MENU_TREE` 加 `/sectors` 后，若前端未同批发布，菜单将指向不存在的路由；前后端必须同批发布（见 §9）。本任务只改代码内 seed，不产生迁移 SQL。
- 产出：常量 + seed 改动（随代码部署生效）。
- 影响范围：新库 PG sys_menu/sys_resource 新增行；`BUSINESS_RESOURCE_CODES` 扩展。**不涉及既有库回填**（既有库授权由 T10b 回填 SQL 处理）。
- 边界与异常：菜单 seed 对既有库仍须手动回填授权后才可见（T10b）。
- 验证方式：seed 幂等重跑 + `BUSINESS_RESOURCE_CODES` 常量测试。
- 完成标准：`sectors:view` 入业务授权集合；seed 幂等可重跑。
- 实际落地情况：已实施（2026-08-09 T8 同批）——`backend/auth/constants.py` `BUSINESS_RESOURCE_CODES` 加 `sectors:view`；`backend/storage/pg_ddl.py` `_SEED_MENU_TREE` quotes 下加 `/sectors` 子菜单（login）+ `_SEED_RESOURCES` 加 `sectors:view`（GET /api/sectors）+ `_BUSINESS_MENU_CODES` 加 `/sectors`。新库随 seed 自动授予 normal/tenant_admin。

### 6.10b 任务 T10b：RBAC 既有库回填 + 权限测试

- 状态：**已完成（2026-08-09 T8 同批交付）**
- 依赖：T10a（常量 + seed 已就位）、T8（接口就位后 403 断言才可测）
- 涉及文件/模块：`agent-works/concept-industry-board/sectors-view-grant.sql`（既有库一次性回填授权 + bump perm_ver，marker 幂等）、`backend/tests/`（路由扫描/权限测试）
- 目标：R22 后端回填与权限测试——既有库回填 `sectors:view` 授予 normal/tenant_admin；回填与 `perm_ver` 自增同一 PG 事务；接口 `require_perm` 守卫；无授权用户菜单不可见 + 路由守卫 fail-closed + 接口 403。
- 操作：沿用 `asset-publish-open` 迁移模式（确定性基线恢复，不依赖 marker 内容，marker 仅作幂等标记；见 pg_ddl.py:934）；路由扫描测试同步新增端点断言；权限测试覆盖有/无 `sectors:view`、有/无 `stocks:view`。
- 产出：回填/回滚 SQL + 权限测试。
- 影响范围：既有库 sys_role_resource/sys_user_role 授权关系 + 受影响用户 `perm_ver`（旧 token 失效重登，预期行为）。**全量用户 token 因 perm_ver 变化失效重登为预期副作用**。
- 边界与异常：回填 SQL 幂等可重复执行；正向执行前把实际新增角色写入 marker 的 `inserted_roles`，回滚只删除这些角色的 `sectors:view` 授权并 bump perm_ver，迁移前已有授权不受影响。旧 marker 缺少该字段时拒绝猜测删除，必须依据迁移前快照人工恢复；新格式空数组表示本次未新增授权，可安全写入回滚 tombstone。受影响用户 token 因 `perm_ver` 变化失效属预期。
- 验证方式：权限测试（有/无 `sectors:view`、有/无 `stocks:view`）+ 回填 SQL 幂等重跑 + 路由扫描测试。
- 完成标准：R22 验收标准中后端部分通过。
- 实际落地情况：已实施（2026-08-09 T8 同批）——`agent-works/concept-industry-board/sectors-view-grant.sql` 落地（既有库回填 `sectors:view` 授予 normal/tenant_admin + bump perm_ver，marker 幂等 + advisory lock + 确定性基线回滚，对齐 asset-publish-open）；`backend/tests/test_rbac_deps.py` 补 `sectors:view` 权限测试（有授权过/无授权 403）。本地库已执行回填（granted=2），normal 用户接口 403→200。

### 6.11 任务 T11：板块行情列表页 `/sectors`

- 状态：已完成（2026-08-11 T11 执行）
- 依赖：T8（接口）、T10a（常量 + seed）；开工前先按 page-template.md §1 把原型/组件选型结论同步用户（本计划 §4 已给推荐与理由）
- 涉及文件/模块：`frontend/src/views/SectorsView.vue`（新增，优先 `npm run scaffold-page -- --pageKey sectors --label 板块行情 --archetype list`）、`frontend/src/router/index.ts`（`/sectors`）、[pageRegistry.ts](../../frontend/src/layout/pageRegistry.ts)（`sectors` pageKey：slots/consumedComponentFields/componentMeta sortFields）、`frontend/src/api/sectors.ts`（新增 API 封装）、[DESIGN.md](../../DESIGN.md)（page-registry 区块登记）
- 目标：R7、R10 + R22/R23 列表页部分，逐项承接 §4.1 功能点表与原型区域。
- 操作：action 区全市场/自选、板块类型、交易日、搜索防抖与查询主命令；排序走列头；筛选态写 URL query；进详情携带来源 query；业务默认项由 `usePageSettings('sectors')` 承载，表格字段由 `componentValueOf('table', ...)` 承载；四态与权限态完整。
- 产出：页面 + 路由 + registry 登记 + API 封装 + Vitest（筛选态还原、偏好优先级 URL>保存>默认、非法值回落）。
- 影响范围：新增页面与菜单可见入口；无既有页面变化。
- 边界与异常：搜索关键字 ≤50 字符；空值列「—」；窄视口主表内滚。
- 验证方式：Vitest + `npm test`（pageRegistry 契约）+ Playwright（T15）。
- 完成标准：R7、R10 验收通过；契约测试绿。
- 实际落地情况：列表与走势同屏；行点击切换当前板块，勾选只管理附加对比板块；走势按区间首日归一为 0%，可选择市场指数并展示超额涨跌，K 线模式复用统一范围。抽屉登记默认类型、默认范围、默认图表模式、默认对比指数、全局 K 线范围及表格组件字段；远端偏好水合完成后再初始化页面默认项。

### 6.12 任务 T12：板块详情页 `/sectors/:code`

- 状态：已完成（2026-08-11 T12 执行）
- 依赖：T8、T10a、T11（列表页来源 query 契约）
- 涉及文件/模块：`frontend/src/views/SectorDetailView.vue`（新增，`--pageKey sectors-detail --label 板块详情 --archetype detail`）、`frontend/src/router/index.ts`（`/sectors/:code`）、[pageRegistry.ts](../../frontend/src/layout/pageRegistry.ts)（`sectors-detail` + `memberTable` 嵌套 slot，parentId=detail）、`frontend/src/api/sectors.ts`、[DESIGN.md](../../DESIGN.md)（page-registry 登记）
- 目标：R8、R9、R11、R13、R14 + R22/R23 详情页部分，逐项承接 §4.2 功能点表与原型区域。
- 操作：摘要卡（含双数据日期标注）；复用 `StockChartWorkspace`、`KlineRangeSelect`、`useKlinePrefs`、`useStockChartPreferences` 展示 K 线与量能，并允许拖拽分隔线调整高度；图表区默认 560px、成分股区最小 420px；成分股表统一分页和服务端排序；进入个股前复用 `stockSet` 建立成分股集合和板块详情返回地址；`stocks:view` 权限感知；显式返回并恢复来源 query；菜单复用工作标签最近子路由恢复；低高度整体滚动兜底。
- 产出：页面 + registry 登记 + Vitest（返回筛选态有/无来源 query、权限行禁用、memberTable 字段消费、偏好回落）。
- 影响范围：新增页面；无既有页面变化。
- 边界与异常：板块不存在 → error 态；历史不足涨幅「—」不缩短周期。
- 验证方式：Vitest + `npm test` 契约 + Playwright（T15）。
- 完成标准：R8、R9、R11、R13、R14 验收通过；契约测试绿。
- 实际落地情况：已实施（2026-08-11）。列表页保留点行切换走势，「查看详情」放在当前观察名称左侧身份区；详情完成摘要、自选、交易日、统一 K 线范围，并复用个股详情行情多图工作区实现 K 线/量能高度拖拽及比例保存；成分股服务端分页排序、权限两态和显式返回齐备。缓存详情 code 固定，避免返回列表时误请求 `/api/sectors/`；对比口径固定为“区间首日=0%”并补清晰说明，移除难理解的中点基准；走势和 K 线 tooltip 以行情红绿突出涨跌。

### 6.13 任务 T13：数据质量页候选操作列（废弃）

- 状态：**废弃（2026-08-09 只进不出改造）**
- 废弃原因：候选机制整条删除（见 T9 废弃说明），数据质量页不再有候选确认/丢弃操作列。本任务不再实施。
- 替代闭环：数据质量页 `board_member_incomplete` 行「重采成分」（fix 分派），覆盖成分采集失败/未采的逐板块恢复。详见版本注记「成分模型改为只进不出」。

### 6.14 任务 T14：RBAC 前端接入与配置闭环端到端核对

- 状态：已完成（2026-08-11 T14 执行）
- 依赖：T10a、T10b、T11、T12
- 涉及文件/模块：`frontend/src/router/index.ts`（守卫 meta 权限）、菜单 seed 消费（侧栏）、两页 `v-permission`（如涉及按钮级权限）、[system-rbac-tenant.md](../architecture/system-rbac-tenant.md) 验收清单
- 目标：R22/R23 端到端核对——菜单可见性与授权一致；无授权用户路由守卫 fail-closed；pageRegistry 两处登记与路由一致；两页配置闭环（保存/读取/消费/非法回退/恢复默认同时重置业务偏好与组件字段）；DESIGN.md page-registry 登记完整。
- 操作：按 system-rbac-tenant.md「新页面接入菜单和权限」清单逐项验收；组件字段契约测试；「恢复默认」同时调 `reset()` 与 `resetLayout`。
- 产出：核对结论 + 缺失修补。
- 影响范围：权限与配置正确性。
- 边界与异常：默认角色授权决策以 T10a seed 为准。
- 验证方式：`npm test`（契约/布局测试）+ 权限场景人工验收（用最小权限调试账号，先读 `agent-works/multi-tenant-rbac/test-users.md`）。
- 完成标准：R22、R23 验收标准中非 E2E 部分通过。
- 实际落地情况：已按新页面接入清单逐项核对路由、菜单、资源、接口守卫、默认角色授权、pageRegistry 和恢复默认。板块自选写入口补 `v-permission="'sector-watchlist:update'"`；新增 `debug_sectors_only` 最小权限角色/账号，仅持板块菜单、查看与自选读写码，不含 `stocks:view`；路由单测覆盖 `/sectors/:code` 前缀归属，设置契约锁定列表/详情同时重置业务偏好与组件配置。后端权限聚焦 48 项、前端权限/布局聚焦 106 项通过；前端全量 84 文件 / 661 项通过并完成正式构建；标准视口真实浏览器验证板块可访问、自选按钮可见、成分股不可跳转且直达个股详情被守卫回板块页。

### 6.15 任务 T15：E2E、构建、视口与回归验收

- 状态：已完成（2026-08-12 复核）
- 依赖：T11、T12、T14
- 涉及文件/模块：`frontend/e2e/`（新增 `sectors-*.spec.ts` 等）、[e2e guide](../e2e-automation/guide.md)、`frontend/dist`
- 目标：R7-R14、R22、R23 的页面级验收与全量回归。
- 操作：**板块 E2E 数据夹具先行**——测试 DuckDB 默认无板块数据，通过 `backend/devtools/e2e_board_data.py`、`frontend/e2e/helpers/sectorData.ts` 与 `scripts/run-sector-e2e.sh` 提供列表/详情/成分/指数的可清理确定性夹具；受 `AI_STOCKS_ENV=dev|test|local` + `AI_STOCKS_E2E_WRITE=1` 双重门控，seed/cleanup 只在后端停服时执行并使用 E2E 专属主键。Playwright 覆盖列表切换/排序/搜索/分页/列显隐；详情摘要/走势图周期/成分股分页与排序；显式返回和浏览器原生后退/前进；R9 权限两态；质检重采；空态/错误重试。构建与三视口回归按 AGENTS.md 门控执行。
- 产出：E2E 用例 + 构建产物 + 视口验收记录 + 回归结果。
- 影响范围：交付质量门禁。
- 边界与异常：E2E 选择器只用稳定契约；回归结束后重启后端移除限流豁免。
- 验证方式：`cd frontend && npm run test:e2e`（含新用例与相关回归）+ `npm run build` + `python -m pytest backend/tests/ -q` 全量（遵守 DuckDB 锁规则）。
- 完成标准：需求文档 §11 验收标准全部通过；`npm run build` 与后端全量测试绿。
- 实际落地情况：`backend/devtools/e2e_board_data.py` + `frontend/e2e/helpers/sectorData.ts` + `scripts/run-sector-e2e.sh` 提供受本地环境与 `AI_STOCKS_E2E_WRITE=1` 门控的确定性 seed/cleanup；只写 E2E 专属主键并在后端停服时写入。三视口共享固定调试账号、自选和页面偏好，脚本固定 `--workers=1` 串行，避免跨 project 状态竞争。`sectors-workbench.spec.ts` 覆盖三视口排行、指数基准、周期缩放、自选、对比、K 线、量能、高度分隔条、10日涨幅列显隐、分析区收起/展开、标题说明、菜单/个股/显式返回、浏览器原生后退/前进、列表空态与错误重试；`pageRegistry.spec.ts` 强制可配置列候选必须由页面真实消费显隐状态；`sector-quality-recovery.spec.ts` 覆盖成分重采收敛。工作台不再依赖本地真实板块数据。

### 6.16 任务 T16：2026-08-14 审查复核整改

- 状态：已完成（验证结果见 §8 与 §11）
- 需求映射：R3、R7-R8、R11、R22-R23、R26，以及发布安全约束。
- 安全：恢复页面 Cookie 注入，数据库只保存带版本前缀的 Fernet 密文；独立主密钥仅从环境/受控文件读取，接口掩码回显、配置元数据驱动审计脱敏；启动时加密迁移历史明文（无密钥则删除）并原位脱敏历史审计。
- 正确性与性能：MACD 标题消费资产数据口径；详情/自选查询把板块范围下推 SQL；列表/详情共享图表适配和数值格式化工具。
- 发布闭环：`StockChartSettingSection` 登记到 DESIGN；恢复默认契约改为断言真实 helper；板块聚焦命令固定覆盖数据管理、质量恢复和工作台三份 spec；权限 SQL marker 记录实际插入角色，旧 marker 缺失快照时回滚 fail-closed。
- 文档：同步 requirement、requirement-closure、plan、DESIGN、架构配置、板块采集和 E2E 指南。

### 6.17 任务 T17：页面 Cookie 加密配置恢复

- 状态：已完成，验证结果见 §11.2。
- 纠偏原因：T16 把“消除明文存储”错误扩大为“移除页面配置”，破坏了管理员在线注入链路；用户确认应恢复功能，只收紧存储安全。
- 实现：恢复系统设置字段与任务调度数据源「授权配置」入口；`AppConfigRepo` 保存前使用独立 Fernet 主密钥加密，读取时校验并在进程内解密，接口只回显掩码与 `unset|usable|unavailable` 状态。系统设置和任务调度入口都提示密文不可解密并允许重新加密覆盖或清除；环境变量/文件优先于页面值。
- 安全闭环：密钥缺失、格式错误、密文篡改均 fail-closed；历史明文有密钥时原位加密、无密钥时删除；迁移工具只迁移加密后的敏感值；审计继续由配置元数据脱敏。
- 发布配置：部署前生成并安全保存 `AI_STOCKS_CONFIG_ENCRYPTION_KEY`，或配置仅后端可读的 `_FILE`；不得复用 JWT 密钥。密钥轮换必须先重加密现有密文，不得直接替换。

## 7. 数据库与 SQL 计划

### 7.1 DuckDB（代码内 DDL，无独立 SQL 文件）

- 路径：[ddl.py](../../backend/storage/ddl.py)（当前 4 表 + `_DIMENSION_SEED` board 行；候选表为已删除的历史设计）。
- 用途：板块 4 表与维度注册。
- 执行时机：后端启动 DDL init 幂等执行（T3 随代码上线）。
- 影响范围：DuckDB schema 新增；无既有表变更、无数据迁移。
- 回滚方式：`DROP TABLE IF EXISTS board_dict, board_member, board_bar, board_fund_flow` + 删除维度 seed 行（新表无外部依赖，可安全回滚）。

### 7.2 PG seed（代码内幂等 seed）

- 路径：[pg_ddl.py](../../backend/storage/pg_ddl.py) `_SEED_MENU_TREE`/`_SEED_RESOURCES`（`/sectors` 菜单 + `sectors:view` 资源）。
- 执行时机：PG DDL init 幂等执行（T10a 随代码上线）；新库自动生效。
- 影响范围：sys_menu/sys_resource 新增行；新角色授权集合。
- 回滚方式：删除 seed 行 + 清理对应资源/菜单（须先执行 7.3 回滚 SQL 还原既有库授权）。

### 7.3 PG 既有库回填 SQL

- SQL 文件路径：`agent-works/concept-industry-board/sectors-view-grant.sql`（回填 + 内嵌回滚段）。
- 用途：既有库为 normal/tenant_admin 角色一次性补授 `sectors:view`，同一 PG 事务 bump `perm_ver`；marker 幂等（沿用 asset-publish-open 模式，确定性基线恢复，不依赖 marker 内容）。
- **产物状态（2026-08-09 T10b 已落地）**：`sectors-view-grant.sql` 已交付（正向授予 + 注释内嵌回滚段，对齐 asset-publish-open 同文件双段结构）；本节描述已固化。
- 执行时机：T10a 代码部署后、T14 权限验收前，一次性执行；重复执行幂等。
- **回填基线（确定性）**：normal/tenant_admin 角色在**无 `sectors:view` 授权**的原始状态上新增该资源授权 + bump perm_ver；仅当确有新增才 bump（沿用 asset-publish-open `_backfill_asset_publish_open_v1` 的「changed 才 bump」模式，pg_ddl.py:1697-1699），避免空跑污染 perm_ver。
- 影响范围：sys_role_resource/sys_user_role 授权关系 + 受影响用户 `perm_ver`（旧 token 失效重登，预期行为）。
- 回滚方式：使用 `sectors-view-grant.sql` 与 `sectors-menu-grant.sql` 各自注释的回滚段，只删除 marker `inserted_roles` 记录的本次新增接口/菜单授权并按实际变化 bump `perm_ver`；旧 marker 无记录时不执行破坏性删除，需从迁移前快照恢复。不回滚已新增的 sys_menu/sys_resource seed 行（无害残留，菜单随代码回退消失）。
- SQL 文件要求：含总体/字段/执行语句注释，说明用途、影响范围、前置条件、回滚方式（协作红线）。

### 7.4 配置项

- 路径：`config/settings.yaml`（板块质检阈值基线）+ **`backend/config/settings.py` `Settings` 模型加子模型字段（Pydantic default_factory，与 YAML 节字段名对齐）** + `get_effective_settings()` 消费（T7）。**2026-08-09 修订：`board_quality` 为低频稳定参数，已从 CONFIG_GROUPS 覆盖层移除，仅 YAML 基线、不做 Web 在线配置**（见版本注记）；同花顺请求参数独立配置段 `ths_board`（min_interval_sec/timeout_sec/max_retries/retry_backoff_sec），入覆盖层白名单、挂「数据治理」tab 可 Web 覆盖。
- 执行时机：T7 随代码上线；默认值 `relative_change_ratio=0.5`、`absolute_change_threshold=20`；`ths_board` 默认 `min_interval_sec=1.0`/`timeout_sec=10`/`max_retries=3`/`retry_backoff_sec=2`。
- **契约要点（T1 核验补充）**：`get_effective_settings()` 先 YAML 再叠加 app_config 覆盖层，覆盖层按白名单 `CONFIG_GROUPS` 字段校验（`app_config.py:22-65`）；阈值在 `Settings` 加子模型字段（`board_quality`）、`settings.yaml` 加对应节，**不入 CONFIG_GROUPS**（消费端回落 YAML 基线）；同花顺请求参数 `ths_board` 在 Settings 模型 / settings.yaml / CONFIG_GROUPS 三处同步（可在线覆盖）。
- 影响范围：质检扫描阈值；不调整时纯 YAML 基线生效。
- 回滚方式：删除 YAML 键与白名单项即回到无板块质检（规则代码同步移除）。

## 8. 测试与验证计划

- 单元测试：
  - 计划：T2 适配器单测；T3 DDL/约束单测；T4 采集逻辑单测（diff/hash/同日冻结/资金流映射/**member_count 刷新时机**/事务原子性/**写锁冲突关键字归类与重试恢复**）；T6 daily 参数化矩阵；T7 质检规则与配置覆盖（含收敛不误删 `member_surge_shrink`、**Settings 模型/YAML/CONFIG_GROUPS 三环覆盖生效**）；T8 统计口径（含领涨股来源）；前端 Vitest（筛选态、偏好优先级、memberTable 字段消费、返回 query 白名单校验）。
  - 具体完成情况：T2 已落地——`test_ths_board_source.py` 20 用例全绿（含登录态 4 例，2026-08-09）；T3 已落地——`test_ddl.py` 17 用例全绿（含板块表/CHECK/表达式唯一索引 7 例，2026-08-09）；T4 已落地——`test_board_ingest.py` 13 用例全绿（diff/hash 幂等/候选/事务原子性/写锁归类/IN 占位符，2026-08-09）；T5 已落地——`test_data_mgmt_b.py` 板块任务 4 用例全绿（注册/执行/互斥/续跑，2026-08-09）；T6 已落地——`test_pipeline.py` 板块集成 4 用例全绿（默认执行/跳过/失败隔离/total_steps，2026-08-09）；T7 已落地——`test_data_mgmt_b.py` 板块质检 4 用例全绿（成分数波动/指数缺口/配置三环/收敛不误删，2026-08-09）
- 接口测试：
  - 计划：T8 四接口口径对账（涨幅/净流入/成分数 vs DuckDB，领涨股按行情截面有效成分股涨幅第一且覆盖稳定决胜）；T10a/T10b 权限（有/无 sectors:view、403）。**跨进程锁冲突集成测试（T4 新增断言）**：独立子进程持写锁 → 被测进程写事务归类返回 `duckdb_write_unavailable`、锁释放后重试恢复。
  - 具体完成情况：T8 已落地——`test_sectors_api.py` 8 用例全绿（列表/详情/bars/members 口径、涨幅不读资金流周期表、涨跌家数、排序分页、404/400）；T10a/T10b 已落地——`test_rbac_deps.py` sectors:view 权限用例（有授权过/无授权 403）+ 回填 SQL 幂等（本地库执行 granted=2）。
- 页面/交互测试：
  - 计划：T15 Playwright（列表筛选/排序/搜索/分页/列显隐、详情走势图周期/成分股统一分页、返回筛选态两路径、R9 权限两态、质检页 `board_member_incomplete` 重采）。
  - 具体完成情况：板块核心工作台三视口已覆盖列表、自选、指数基准、周期缩放、走势/K 线、量能、详情、返回与个股正向跳转；标准视口覆盖搜索、排序、分页、列显隐/恢复默认、无 `stocks:view` 的成分股禁用及直达个股路由 fail-closed；质量页确定性用例覆盖 `board_member_incomplete` 重采与任务完成后收敛。
- 组件资产闭环测试：
  - 计划：`sectors`/`sectors-detail` pageRegistry 契约测试（memberTable 嵌套 slot、consumedComponentFields 指向真实 slot）；两页组件字段保存/读取/非法回退/恢复默认参数化矩阵；DESIGN.md page-registry 登记核对。
  - 具体完成情况：pageRegistry、组件字段、数值范围、详情图表高度及列表/详情双重恢复默认契约已覆盖；2026-08-14 当前 HEAD 的实际结果见本节“回归测试”，历史数量不再作为当前绿色依据。
- 权限与数据范围测试：
  - 计划：T10a/T10b 后端权限测试 + T14 前端菜单/守卫验收（最小权限调试账号，先读 `agent-works/multi-tenant-rbac/test-users.md`）。
  - 具体完成情况：T14 已完成。新增并校准 `debug_sectors_only`，后端权限聚焦 48 项、前端权限/路由/布局聚焦 106 项和标准视口 Playwright 权限链路均通过。
- 回归测试：
  - 计划：`python -m pytest backend/tests/ -q` 全量（先 `./start.sh status`→`./start.sh stop`，结束后按原状态恢复并确认 `/api/health=200`）；`npm test`；相关既有 E2E 回归。
  - 具体完成情况（2026-08-14）：整改开始时前端 Vitest 为 697 passed / 2 failed，不能视为通过；修复后的实际命令、数量和状态在全部验证结束后记录到 §11。本轮未执行的验证必须在 §11 明示原因。
- 异常与边界测试：
  - 计划：只进不出落库幂等（ON CONFLICT）、不完整快照不落库、401 cookie 刷新、单板块失败继续与失败清单、历史不足「—」、空值列「—」、`transaction()` 原子性（中途失败整体回滚）、写锁冲突 `duckdb_write_unavailable`（锁释放后重试可恢复）、**member_count/member_snapshot_at 完整快照路径刷新**、**完整快照后旧 incomplete issue 自动 resolved**。
  - 具体完成情况：后端全量测试覆盖落库幂等、完整性、事务、权限与异常分支；页面 E2E 覆盖空/错误/权限状态、质量恢复成功收敛和无个股权限 fail-closed。DuckDB 写锁按读写回归与公开回测只读回归分离执行，结束后恢复日常后端。
- 图示与原型一致性验证：P1/P2 实现对照 `prototypes/sector-board.html`/`prototypes/sector-detail.html` 的主要区域（action 筛选区/主表/分页/设置抽屉；摘要区/走势图工具条/图表/成分股表/抽屉/tooltip）、操作入口、关键状态（数据/空/错误/加载/无权/个股权限两态）与低高度退化；**P1 的「概念/行业分段」「主排序周期分段」两控件已按 2026-08-11 用户裁定移除，不纳入对照**；P3 无原型，按 QualityView 现状扩展核对。
- 配置闭环验证：`defaultType/defaultScope/defaultChartMode/benchmarkCode`、全局 `kline-prefs` 与 `chart.minHeight`、`pageSize/defaultSort/hiddenColumns` 组件字段可展示、保存、读取、实际生效、恢复默认、非法值回落并兼容旧值。
- 需求映射验证：§5 映射表逐项核对，R1-R14、R21-R23、R26 均有任务与验证方式；R15-R20/R24/R25 均标跳过且有原因；MACD 不再是未解释的超范围开发内容。
- 页面功能点验证：§4.1/§4.2/§4.3 功能点表逐项有技术实现、任务编号、交互状态与异常处理验证。

## 9. 发布与回滚

- 发布前检查：后端全量测试绿（DuckDB 锁规则）；`npm test` + `npm run build` 绿；E2E 通过；回填 SQL 已评审；`.env.local` 环境确认 `AI_STOCKS_ENV`。
- 发布步骤：
  1. 部署后端代码（DDL/seed 幂等自动生效）→ `./start.sh restart` → `./start.sh status` 确认 `/api/health=200`。**注意：菜单 seed 生效不得早于前端路由上线，步骤 1 与步骤 3 必须同批发布**（否则菜单指向不存在的 `/sectors` 路由）。
  2. 执行 `sectors-view-grant.sql`（既有库回填，T10b 产物）。
  3. 部署前端 `frontend/dist`（`npm run build` 产物，与步骤 1 同批）。
  4. 系统管理员触发 `python -m backend.cli board --backfill`（或任务中心创建板块采集），确认 4 表数据与任务进度。
  5. 冒烟：列表页/详情页/数据概览/数据质量页。
- 配置或环境变量：同花顺源为公开 HTTP；可选登录态优先读取 `AI_STOCKS_THS_COOKIE` / `_FILE`，为空时消费页面加密配置。Cookie 不得硬编码、写入 YAML 或审计值；PG 只允许保存 `enc:v1:` 密文，页面能力依赖独立 Fernet 主密钥。请求限速/超时/重试走 `ths_board` YAML + app_config 白名单覆盖。
- 回滚方案：代码回退（前端 dist + 后端）→ 分别启用 `sectors-view-grant.sql`、`sectors-menu-grant.sql` 内的注释回滚段，按 marker 精确撤销本次新增授权并在实际变化时 bump `perm_ver`；旧 marker 缺少 `inserted_roles` 时先恢复迁移前快照，不得直接删除角色现有授权 → DuckDB 4 表可保留（只读接口随代码回退消失，数据无害残留）或按 §7.1 drop；维度 seed 行随代码回退消失。

## 10. 风险、假设与待确认项

### 10.1 风险

- 同花顺反爬升级（v cookie 脚本失效/限流加严）：`ths.js` 依赖 akshare 包内资源，akshare 升级可能破坏；缓解——适配器单测 mock 化 + 401 刷新重试 + 限速 ≥1s；失效时板块采集失败隔离不阻塞主流程（R21）。
- **成分股翻页限制与登录态解除（2026-08-09 T2 实测定稿）**：无登录态时详情页翻页第 6 页起必返回登录墙（HTTP 200 但内容为 `upass...login` 跳转壳，单发第 6 页同样命中，非 IP 频率触发），单板块最多稳定取 5 页（概念 50 只/行业 100 只）；**提供登录 cookie（`login_cookie` 参数 / `AI_STOCKS_THS_COOKIE` 环境变量，浏览器同花顺登录后复制）后登录墙解除**——冷 IP 下实测半导体第 6 页正常返回 20 只、完整取到 120 只，`complete` 判定回归正确（空页=真实尾页）。**代价：同花顺对数据中心 IP 的连续请求有动态风控**——请求量累积后返回空页/401，冷却短暂恢复、持续高频后 IP 被标记稳定 401（cookie 本身 sess_tk 30 天内有效，非凭证过期）。缓解：适配器限速默认 ≥1s/次 + 分批断点 + 登录态失败时 `complete=False` 走 R2 保护；长期大批量采集需评估 IP 轮换或进一步低频。
- **板块指数历史年限（2026-08-09 实测，需求 R3 偏差修正）**：`d.10jqka.com.cn/v4/line` 指数历史**仅保留近 3 年**——实测 2024/2025/2026 返回 200、2021/2022/2023 返回 404。需求 R3 原「回填近 5 年」不成立，已修正为「回填源端可用年限（2024 起）」；**各板块指数最早可用日不同属正常**（按各自最早日回填，页面历史不足显示「—」不缩短周期）。`ingest_board` 指数回填起点已从 2021 改为 2024。
- `py_mini_racer` 当前为传递依赖：T2 显式声明消除升级漂移风险。
- app_code(clid) 需逐板块详情页抓取，采集耗时与失败率高于其他接口：失败不阻塞字典主体，`app_code` 允许为空后续补采。
- 既有库回填执行遗漏会导致老用户菜单不可见：发布步骤强制包含 SQL 执行与权限验收。
- E2E 全量回归的登录限流/DuckDB 读写锁门控配置遗漏：T15 操作步骤显式列出。
- 表达式唯一索引依赖 DuckDB 版本能力：本机 1.5.3 实测创建与强制均生效（2026-08-09 复核）；若部署环境旧版本拒绝，T3 单测在开发期暴露，按 §4 降级方案执行，不会带病上线。
- 写锁冲突识别靠异常消息关键字归类（2026-08-09 实测）：本机 DuckDB 1.5.3 **无锁等待配置**（`SET duckdb_max_lock_wait_time` 抛 CatalogException），跨进程冲突**立即失败**（0.006s 抛 `IOException: Could not set lock`，被 `duckdb_client` 包装进 `StorageError` 且消息含 `lock`，归类可命中）。已移除锁等待超时设计，仅保留关键字归类；若错误消息格式随 DuckDB 升级变化导致关键字漏配，最坏退化为 500 而非半成品状态，且 T4 的跨进程锁冲突集成测试可尽早暴露。**连接恢复无需额外处理**：冲突只发生在 connect 阶段、`_conn` 保持 `None`，锁释放后同一实例重试即自动重建连接（实测确认），不存在需显式释放的残留连接。
- 列表页 `pageSize` 统一使用全局 20/50/100/200；详情成分股使用 10/20/30/50。
- 回填/回滚 SQL 已由 `sectors-view-grant.sql`、`sectors-menu-grant.sql` 固化；发布前须评审目标库 marker 格式并保留迁移前授权快照，生产执行仍需单独变更授权。
- **`board_type` 参数接线（2026-08-09 复核修复）**：`ingest_board(board_type=)` 已向字典、成分、指数、资金流四阶段透传；采集页、调度、CLI/任务参数均可按 `concept|industry` 限定范围，非法值 fail-fast。
- **`--update` 增量语义（2026-08-14 当前事实）**：`ingest_board(mode=)` 区分 `backfill`（指数全量回填 2024 起）与 `update`（指数只补最近 5 天）；两种模式的资金流都刷新即时/3日/5日/10日/20日全周期，因为滚动周期值每日变化，只采即时会造成多周期数据停滞。成分股按周频配置跳过，`backfill`/强制重采绕过。CLI、daily、`_h_board` 均消费同一口径。

### 10.2 假设

- 板块成分股现价/涨跌幅/换手来自 DuckDB 个股行情表（与 `board_bar` 同库关联，不跨库 JOIN）；个股当日无行情时对应列显示「—」且不计入涨跌家数。
- 质检页 `board_member_incomplete` 行触发「重采成分」（fix 分派重采该板块成分），QualityView 复用现有 fix 动作（需求 §7.3 修订）。
- 任务中心「板块采集」前端中文标签改 `data.ts` 一处即可被任务中心各列表消费（与现有任务类型同款）。
- 领涨股按所选行情交易日有效成分股 `pct_chg` 最大者计算；停牌/缺收盘/缺有效前收排除，同涨幅按成交额降序、股票代码升序决胜。资金流源自带领涨字段仅作原始留存。
- 列表/详情只展示 `has_members` 或 `has_bar` 为 true 的板块；仅 `has_fund_flow` 的资金流独有板块入字典但不进页面展示（承接需求 §2.5）。

### 10.3 待确认项

- 无阻塞待确认项。以下非阻塞项在实施中按既定口径执行，如有异议随时回到用户确认：
  - 采集服务落 `board_ingest.py` 新文件还是并入 `ingest.py`（T4 实施时按既有分层就近原则定，偏离时在开发留痕说明）。
  - 列表排行采用当前重构后的精简列与同屏走势；旧原型仅保留信息架构参考。
  - 列表页 `pageSize` 使用全局 20/50/100/200，详情成分股使用 10/20/30/50。
  - **成分快照完整性判定维持当前口径（2026-08-09 已拍板）**：`complete`（空页即尾页 + 登录墙识别标不完整）作为完整性唯一闸门，不完整快照整趟不落库 + 写 `board_member_incomplete` 待重采；**不引入「取到数 vs member_count/资金流公司家数」的完整性对账**（首次初始化无基准、无法识别假完整）。已知盲区（登录墙恰好截到等于基准数的「假完整」）接受为源端限制。
  - 领涨股口径已确认（2026-08-12）：按行情截面日有效成分股涨幅第一计算；不再使用资金流快照日领涨字段。
  - 资金流独有板块「进入 board_dict」（R4 §2.5，**2026-08-10 口径更新**）：实测资金流源板块单元格**带链接含真实路径 code**（如 `/gn/detail/code/308734/`），故 T4 实现为「有链接 code 的独有板块经 `_upsert_fund_only_boards` 补进字典（`has_fund_flow=true`、`has_members/has_bar=false`，不进页面展示）；仍无稳定代码（无链接 code 且名称匹配不到字典）的板块写 `board_fund_unmatched` 质检、不伪造代码」。早期 `_fund_flow_union_supplement` 空实现（假设源无稳定代码）已废弃，由 `_upsert_fund_only_boards` 取代。

## 11. 数据采集闭环复核与修复结论（2026-08-09）

本节是对既有计划的增量实施记录，不替换前述任务拆解与历史决策。

| 复核方向 | 当前结论 | 已补齐事实 |
| --- | --- | --- |
| 现有采集链对齐 | 已闭环 | 板块已进入 CLI、daily、异步任务、采集页、调度页、任务中心、数据源状态、维度目录、数据概览和质量体系；支持 backfill/update、concept/industry、指定板块、阶段选择和限量 |
| 失败与续跑 | 已闭环 | 字典按类型、成分/指数按板块、资金流按类型+周期记录 checkpoint；部分失败使任务/流水线 `ok=false`，保留成功 checkpoint，可只重试未成功工作单元；显式空板块范围不会误扩成全量 |
| 修复流程 | 已闭环 | `board_member_incomplete` 重采完整成分快照，`board_index_gap` 补采指数，`board_fund_unmatched` 刷新字典并重采资金流；仅真实复检通过后 resolved，失败或复检未通过保留 open，失败工作单元不写完成 checkpoint |
| 数据概览 | 已补齐 | 除 `board` 维度行外，概览和闭环图展示 4 表行数、概念/行业数量、成分/指数/资金流覆盖、指数/资金流最新日期、未闭环问题分类和最近采集状态，并提供前往板块采集入口 |
| 当前未完成范围 | 无 | `/sectors` 与 `/sectors/:code` 页面、pageRegistry、页面配置、权限矩阵、质检动作与发布级全量验收均已完成 |

验证基线：历史 2026-08-11 结果仅作留痕，不代表当前 HEAD；当前 HEAD 的单一验证事实与未执行项见下方 §11.2。

### 11.1 历史验证归档（已失效）

2026-08-14 早期整改的 882/889 后端用例数及“敏感配置不进入迁移”的中间态结论已被 T17 加密迁移方案和后续整改取代，不作为当前 HEAD 的验收证据。当前结果只维护在 §11.2，避免多套“最新事实”并存。

### 11.2 2026-08-14 当前 HEAD 单一验证事实

- 后端聚焦：`python -m pytest backend/tests/test_data_mgmt_b.py -k 'ths_login_cookie' -q`，**5 passed**；覆盖未设置、正常加密可用、主密钥缺失、错误密钥、篡改密文和无密钥整批拒绝，接口状态与运行态一致且不返回明文。
- 后端全量：`python -m pytest backend/tests/ -q`，**893 passed**；仅有既有 FastAPI `on_event` 弃用警告。复核报告中的 890 是本轮新增三种故障状态用例前的基线，不再作为当前 HEAD 结果。
- 前端全量：`npm test`，**85 files / 702 tests passed**；`npm run build` 通过并同步 `frontend/dist`，仅有既有第三方 PURE 注释与 chunk size 警告。
- 板块聚焦 Playwright：`AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:sectors`，三份 spec 三视口合计 **12 passed / 6 skipped**（跳过项均为用例声明的视口条件）；任务调度页验证“已存密文无法解密”提示、重新输入入口和原调度保存链路，未向数据库写入 E2E 假 Cookie；确定性夹具已 cleanup。
- 静态与运行检查：本次 Python 变更 Ruff `F` 规则、`git diff --check` 通过；测试前按规则停服，验证后已恢复 dev 后端并确认 `/api/health=200`。
- 命令异常：首次并行启动前端全量测试的子进程未继承 Node 路径，以 `npm: command not found` 在测试启动前退出；随后使用本机 npm 绝对路径完整重跑，以上 85/702 为有效结果。
- 未执行：真实同花顺 Cookie 保存后联网采集及外部数值逐项对账（不使用用户真实凭证）；本机 `.env.local` 尚未配置新主密钥，因此未向本地真实 `app_config` 写入模拟 Cookie，保存/解密由隔离测试库验证；生产密钥管理系统接入与密钥轮换演练、生产 PostgreSQL 权限 SQL 正向/回滚演练（均无生产环境和变更授权）；全量跨模块 Playwright、公开回测只读 Playwright、暗色/reduced-motion 与加载中间帧专项截图。
