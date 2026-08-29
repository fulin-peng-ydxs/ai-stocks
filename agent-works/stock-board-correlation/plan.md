# 个股走势关联板块开发计划

> 计划版本：2026-08-30
> 当前状态：已完成（T1-T11 全部完成；2026-08-30 完成复审修复、完整门禁与真实全市场任务复验）
> 需求状态：业务闭环与正式需求已确认，无阻塞项
> 本文按阶段拆解实施任务，并在每阶段完成后同步记录实际落地与验证结果。

## 1. 需求来源与目标

- 需求文档：[requirement.md](requirement.md)。
- 上游闭环：[requirement-closure.md](requirement-closure.md)。
- 关联能力：`agent-works/concept-industry-board/requirement.md`。
- 功能目标：基于股票累计行业、概念归属，按上市板对应指数做市场中性化，预计算并原子保存每只股票的行业走势冠军和概念走势冠军，供个股查询、每日榜单、策略筛选毫秒级批量读取。
- 本次不做：R11-R20；尤其不保存每日快照、全部候选明细，不接入个股详情，不做盘中计算、全市场非归属板块比较或人工改冠军。
- 页面原型：需求明确不生成 HTML 原型。本次仅扩展既有表格列、共享单元格和调度表单，不新增页面、不重排主区域；以 `DESIGN.md`、`pageRegistry.ts`、`page-template.md` 和现有页面实现作为布局依据。
- 计划输出目录：`agent-works/stock-board-correlation/`。

## 2. 当前项目依据

### 2.1 数据与存储

- `backend/storage/ddl.py` 已定义 `stock_basic`、`daily_bar`、`index_bar`、`board_dict`、`board_member`、`board_bar`；旧库通过 `CREATE TABLE IF NOT EXISTS` 与轻量迁移幂等补结构。
- `board_member` 主键为 `(board_code, code)`，业务含义为累计关系；`board_dict.board_type` 已区分 `industry | concept`，`member_snapshot_at` 可提供成分最近完整采集时间。
- `daily_bar` 后复权口径必须使用 `close * COALESCE(adj_factor_clean, adj_factor)`；`board_bar` 为原始连续板块指数；`index_bar` 承载四类市场基准。
- `trade_calendar` 是统一市场开市日事实源；20/60 个收益区间必须按 21/61 个连续开市收盘点计算，不能按各序列“相邻有效记录”跨停牌或数据缺口桥接。
- `backend/storage/catalog.py` 是数据资产目录和新鲜度说明事实源，新增当前结果关系后需登记。
- DuckDB 当前由 `DuckDBClient` 串行化访问；写任务通过异步任务层互斥。分组资产位于 PostgreSQL，行情和相关性结果位于 DuckDB，必须在服务层内存合并，禁止跨库 JOIN。

### 2.2 任务与调度

- `backend/services/async_task.py` 的 `TASK_TYPES`、`WRITE_TASK_TYPES`、`TASK_CAPABILITIES`、`_HANDLERS` 是任务执行事实源；创建写任务时即检查互斥。
- `backend/scheduler/scheduler.py` 的 `SCHEDULABLE_TASK_TYPES`、`ScheduledJobService._validate` 支持 daily/weekly/monthly/cron、交易日限制、依赖、延迟和失败重试。
- `scheduled_job`、`scheduled_trigger_event`、`async_task` 和任务日志实际均在 DuckDB；`scheduled_job` 已保存通用 `task_type + params`，本次无需新增 PostgreSQL 字段，只扩展 DuckDB 允许值和参数校验，不 seed 默认调度，避免覆盖管理员配置。
- 前端任务类型、中文标签和筛选事实源位于 `frontend/src/api/data.ts`、`IngestView.vue`、`ScheduleView.vue`。
- `frontend/src/components/data/StockIngestScopeFields.vue` 已实现远程股票多选，`frontend/src/views/data/OverviewView.vue` 另有同类搜索/粘贴逻辑；新增相关性范围选择前必须抽取最低层级的通用股票代码多选组件并迁移现有消费点，禁止在 `ScheduleView.vue` 出现第三套远程搜索和代码归一化。
- `backend/services/stock_ingest.py` 已有六位 A 股代码格式化、去重校验；本次把稳定的代码集合规范化抽为通用 helper，由采集与相关性任务共同消费，未知股票存在性校验仍留在各自业务服务。

### 2.3 接口、服务与页面

- `backend/api/stocks.py::list_stocks` 返回分页股票和统一 `trade_date`；`backend/groups/stock_group.py::StockGroupRepo.get` 先读 PG 成员，再读 DuckDB 行情并在内存合并，每行已有 `last_date`。
- `backend/api/board.py::board_run` 返回可指定 `run_date` 的榜单；`board_compute` 是历史/回测链路，必须保持不注入最新相关性。
- `backend/api/profiles.py::run_screen` 与 `backend/services/screen_score.py::screen_scored` 返回可指定历史日期的筛选结果。
- `frontend/src/views/StocksView.vue`、`BoardView.vue`、`ScreenView.vue` 已统一使用 `AppDataTable + AppTableColumn`；`frontend/src/views/data/ScheduleView.vue` 已有任务编辑对话框；本次不新增页面级布局。
- `frontend/src/layout/pageRegistry.ts` 显式登记 `stocks.table`、`stocks.groupTable`、`board.table`、`screen.result`、`data-schedule`；新增业务列必须登记后由页面真实消费。
- `DESIGN.md` 与 `agent-works/configurable-layout-system/page-template.md` 要求表格长文本单行退化、结构化说明使用受控 popover、ready/loading/empty/error 互斥、权限态不可伪装为空态；真实复用组件出现于两个以上页面时需进入组件清单并有真实页面消费与测试。该模板要求的页面定位、slot、四态、维护矩阵和三视口验收见本计划 4.11。

### 2.4 权限与兼容

- 读取沿用 `stocks:view`、`board:view`、`screen:run`；跳转只由前端根据 `sectors:view` 决定是否可点击，板块详情后端权限不变。
- 任务创建和运行沿用 `data-task:manage`，调度沿用 `data-schedule:manage`，均为 system-only。
- `backend/storage/pg_ddl.py` 已 seed 上述资源码和菜单。本次不新增菜单、资源码、角色授权或租户资产表；新增股票归属读取路由复用 `stocks:view`，需加入路由扫描测试但不创建重复资源 seed。
- 现有响应只新增可选 `related_boards`，不得改变分页、排序、评分、筛选表达式和历史决策口径。

### 2.5 调研限制

- 本计划依据仓库 DDL、服务和测试事实生成，未直接修改或抽样本地 DuckDB/PG 运行数据；实施时 T1、T10 必须通过隔离测试库/固定夹具验证真实 DDL 与规模，不以本地生产式数据文件作为测试写目标。

## 3. 实施范围

### 3.1 必须实现

R1-R10 全部纳入本次开发，按 T1-T11 依赖顺序实施。任何一个必须项未达到对应验证标准，功能不得进入发布步骤。

### 3.2 可选增强

| 需求编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R11 | 当前有效成分及移出时间线 | 后续建议 | 跳过 | - | 数据源尚不能稳定表达移出语义；本次明确使用累计关系并标记 `cumulative`。 |
| R12 | 每日冠军历史、切换轨迹与提醒 | 后续建议 | 跳过 | - | 与本次“成功覆盖当前结果、不保存快照”冲突，需另立存储和提醒需求。 |
| R13 | 个股详情展示全部归属和更多解释 | 后续建议 | 跳过 | - | 用户明确本次不接入；仅保留后端通用读取契约。 |
| R14 | 个股与板块领先/滞后分析 | 后续建议 | 跳过 | - | 需要独立算法、参数和验收口径，不能混入同步相关性版本。 |

### 3.3 暂不实现

| 需求编号 | 内容 | 开发状态 | 跳过原因 | 后续验证边界 |
| --- | --- | --- | --- | --- |
| R15 | 每日相关性快照 | 跳过 | 用户确认无必要，当前表只保存最新状态。 | 验证连续多日任务后结果行数不随日期累积。 |
| R16 | 全部候选相关性明细 | 跳过 | 约五万条每日明细无展示价值。 | 验证正式表只含冠军，不含候选排名。 |
| R17 | 个股详情页展示 | 跳过 | 用户明确暂不展示。 | 回归 `/stocks/:code` 无新区域、请求和 pageRegistry 变化。 |
| R18 | 分钟级盘中计算 | 跳过 | 系统和数据源均为 EOD。 | 验证任务与结果只使用交易日 DATE。 |
| R19 | 与未归属全市场板块比较 | 跳过 | 超出“所属板块”边界且易产生伪关联。 | 候选查询必须从 `board_member` 起始。 |
| R20 | 人工修改冠军 | 跳过 | 破坏统一算法和可审计性。 | 不新增人工编辑 API、表单或覆盖字段。 |

## 4. 技术方案

### 4.1 总体数据流与模块边界

```text
board_member + board_dict ─┐
daily_bar + board_bar ─────┼─> StockBoardCorrelationCalculator
index_bar + stock_basic ───┘       │ 版本化相关性算法（当前 v2）
                                    v
                         候选内存结果 + 每股计算状态
                                    │ 完整性校验
                                    v
                         DuckDB 单事务原子替换
                                    │
                  ┌─────────────────┼──────────────────┐
                  v                 v                  v
              /api/stocks      /api/board/run     /api/screen/run
                  │                 │                  │
                  └──── RelatedBoardCell 共享展示 ─────┘
```

- 新增 `backend/services/stock_board_correlation.py`：累计归属读取、输入批量加载、算法编排、完整性校验、原子替换、单股/批量摘要查询均集中于领域服务；可复用的纯算法放 `backend/indicators/stock_board_correlation.py`，API 和异步任务只做参数、权限和编排。
- 计算不得逐股票—板块对发 SQL。一次加载目标股票、累计候选、统一 `trade_calendar` 的 61 个收盘日、对应个股/板块行情和四个指数，按代码建立受限生命周期索引，再在内存按候选对计算；不得加载五年全量行情，任务结束即释放 DataFrame、临时视图和索引。
- 一期不引入 Redis 或进程内缓存，直接以 DuckDB 当前表为事实源，避免切换失效复杂度；达到性能目标后再决定是否需要缓存。

### 4.2 数据模型与原子切换

新增两个不按日期累积的 DuckDB 关系：

1. `stock_board_correlation`：只保存行业/概念冠军，主键 `(code, board_type)`；字段为 `code`、`board_type`、`board_code`、`score`、`corr_20`、`corr_60`、`sample_20`、`sample_60`、`confidence`、`benchmark_code`、`benchmark_fallback`、`as_of_date`、`computed_at`、`algorithm_version`。
2. `stock_board_correlation_state`：每个已处理股票一行，主键 `code`；保存 `as_of_date`、`computed_at`、`algorithm_version`、`benchmark_code`、`benchmark_fallback`、行业/概念是否有冠军。该状态表用于“两类都合法为空”时仍能表达本轮已成功处理、真实日期和实际基准，不是快照或候选明细，规模稳定约 5000 行。

约束与替换：

- `board_type` 仅 `industry | concept`，`confidence` 仅 `high | medium | low`；样本数、有限分数、日期和字典可解释性在切换前做服务级完整性校验，结构体检再做持续校验。
- 计算结果先落在任务内 DataFrame/临时视图，不创建永久候选表。
- 全量成功：同一事务删除两张正式表并插入新冠军和每股状态。
- 指定代码成功：同一事务只删除指定代码的冠军与状态，再插入该范围新结果；范围内合法空冠军会被清除，其他股票不变。
- 任一未知代码、算法异常、上证兜底样本不足、结果校验失败或事务失败均回滚；允许无候选/个股或候选样本不足形成合法空结果。

### 4.3 R1 累计归属与读取接口

- 服务支持单股和批量代码，`board_member INNER JOIN board_dict`，只保留合法类型，元素明确返回 `board_code`、`name`、`board_type`，按类型、名称、代码稳定排序并去重；空代码集合直接返回空映射且不访问数据库。
- `membership_updated_at` 取本次归属涉及板块的 `member_snapshot_at` 最大值；无关系时可为 `null`。
- 新增 `GET /api/stocks/{code}/related-boards`，返回 `membership_scope=cumulative`、`membership_updated_at`、`industries`、`concepts` 及当前摘要；不存在股票或无关系返回空数组，不用 `stock_basic.industry` 兜底。
- 路由复用 `stocks:view`，不新增资源码；同步后端路由权限扫描测试和前端 API 类型。三个列表页面不调用该单股路由，而由原接口内部批量服务合并。

### 4.4 R2 版本化相关性算法

- 当前版本常量为 `stock-board-correlation-v2`；v2 修正基准目标日有效性并使既有 v1 状态自动触发重算。窗口、权重、样本、缩尾、基准映射仍全部写在同一领域模块中，不进入调度参数。
- `as_of_date` 为不晚于 `trade_calendar` 开市日和 `daily_bar`、`board_bar`、`index_bar` 三类数据族最新日期的共同任务级目标日；所有 SQL 显式 `<= as_of_date`，单个陈旧候选不能反向改写任务日期。
- 从 `trade_calendar` 取得截至目标日的 61 个连续开市收盘日，形成 60 个固定收益区间；短窗取其末 20 个区间。个股使用后复权收盘，板块和指数使用原始连续收盘；只有相邻两个开市日都存在有效收盘才计算该区间收益，停牌、上市前或数据缺口记为缺失，不跨日桥接，也不向窗口外补样本。
- 基准按股票映射：沪市主板 `000001.SH`、深市主板 `399001.SZ`、创业板 `399006.SZ`、科创板 `000688.SH`、未知上市板/交易所回退 `000001.SH`。
- 先检查映射指数在目标日存在有效收盘，且自身在 20/60 目标窗口内分别达到 15/40 个有效收益；任一条件不满足时整只股票的两种类型和两个窗口统一回退上证指数。个股或候选自身不足只淘汰对应股票/候选，不触发回退；上证指数仍不满足目标日或样本条件则整个任务失败且不切换。
- 单次批量任务按唯一板块代码和唯一基准代码预计算收益映射；逐股只构造该股收益并复用候选板块/基准收益，禁止按约五万条候选关系重复构造相同板块收益。
- 每个候选在固定 20/60 区间内按股票、板块、最终基准三方同日有效样本对齐，股票和板块分别减同日基准收益；各自按 5%/95% 分位缩尾后计算 Pearson。非有限系数无效。
- 两窗均达标后 `score = 0.6*corr_20 + 0.4*corr_60`；按 score、corr60、sample60 降序和 board_code 升序稳定决胜，行业/概念隔离。
- 高可信：`sample_60>=50 && score>=0.70 && corr_20/corr_60同号`；中可信：`sample_60>=40 && score>=0.50`；其余合格结果为低。负相关最高者仍可成为低可信冠军。

### 4.5 R4 任务、日志与动态配置

- `stock_board_correlation` 加入后端任务白名单、DuckDB 写互斥集合、处理器和可调度白名单；不创建默认调度记录。
- 在 `TASK_CAPABILITIES` 明确登记 `can_cancel=true`、`can_resume=false`、阶段检查点取消；进入原子切换事务后不响应取消。失败、服务重启中断和人工重试均重新计算完整目标范围，前端只展示真实能力，不出现不可用的“续跑”。
- 参数规范化集中在领域服务并被手动任务与调度保存共同复用：`codes` 接受数组或逗号文本，去空去重、统一大写；保存调度时校验 `stock_basic` 存在且属于项目支持板块，任务执行时再按真实目标日校验上市/退市状态，任一失效代码在写前使整批失败并给出原因。空 `codes` 按目标日构造主板、创业板、科创板在市 A 股全量池，不含北交所。`force` 必须为布尔值，缺省 `false`。
- `force=false` 仅当目标范围内每只股票的状态都与目标日、当前算法版本一致时返回成功跳过统计；任一缺状态、日期落后或版本变化都执行计算。全量任务一旦需要计算就全量覆盖，不能只更新落后子集后冒充全量成功；`force=true` 允许同日全量或指定范围重算。
- 任务阶段日志固定包含：读取候选、加载行情、批量计算、结果校验、原子切换。切换前支持取消，进入短事务后不响应中断；不做不完整 checkpoint 续跑，失败重试重新完整计算目标范围。
- 结果统计包含需求列出的全部计数、各基准使用数、回退数、计算/写入耗时和切换标记；可预期的完整性失败返回 `ok=false`、`switched=false` 和已收集统计，使任务标记失败但结果可诊断，未预期异常至少保留阶段日志和错误摘要；任务中心中文名为“个股走势关联板块”，阶段标签和结果在现有日志/详情入口可见。

### 4.6 R5 批量摘要与日期保护

- `get_related_boards(codes, business_dates)` 通过固定次数批量查询状态、冠军和 `board_dict`，并复用 `backend/services/market_benchmark.py` 的指数名称事实源补充 benchmark name，返回 `code -> related_boards`；`business_dates` 支持统一日期或逐代码日期，禁止在新模块复制第五份指数名称映射。
- 只有业务日期等于状态 `as_of_date` 才返回冠军；不一致时保留真实 `as_of_date` 和基准信息，但 `industry/concept=null`、`unavailable_reason=as_of_mismatch`。
- 未处理或缺失状态时返回 `related_boards=null`；结果表孤儿字典不伪造名称，相应冠军为空并由结构体检报告。
- 股票分页用响应 `trade_date`；分组按每行 `last_date`；榜单与筛选用 `run_date`。每个调用方仅在形成最终代码集合后调用一次，不改变原排序、分页或评分。

### 4.7 页面 P1：个股查询 `/stocks`

- 原型文件：不生成；只扩展 `stocks.table` 和 `stocks.groupTable`，现有筛选、普通/分组列表、右侧走势分析和底部选择条保持不变。

| 页面功能点 | 需求 | 技术实现 | 组件/模块 | 数据/API | 状态、权限与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 普通表行业走势/概念走势 | R5、R6、R7 | `list_stocks` 对当前页一次批量合并；两列默认可见且不参与服务端排序 | `RelatedBoardCell`、`StocksView`、`stocks.table` | `GET /api/stocks` 行内可选 `related_boards` | 随主表 loading；无结果“—”；摘要缺失不阻断主表；`stocks:view` | T6、T7、T8 |
| 分组表行业走势/概念走势 | R5、R6、R7 | `StockGroupRepo.get` 在 PG/行情合并完成后，按当前页代码和逐行 `last_date` 一次批量附加 | 同一共享单元格、`stocks.groupTable` | `GET /api/stock-groups/{gid}` | 严禁跨库 JOIN；日期不匹配显示“—”及历史说明；原分组错误态不变 | T6、T7、T8 |
| 悬浮解释 | R6 | 可聚焦 popover 展示 score、20/60 相关度、样本、截止日；低可信显示“相关性较弱” | `RelatedBoardCell` | 行内摘要 | 长名称单行退化；字段缺失安全显示“—” | T7 |
| 权限感知跳转 | R6 | 有 `sectors:view` 才渲染可点击入口并导航 `/sectors/:code` | `RelatedBoardCell`、权限工具 | 无额外请求 | 无权限为普通文本，不触发 403；详情后端仍 fail-closed | T7 |
| 列显隐 | R6、R7 | 在两个 slot 的 `componentMeta.columns` 登记并消费 `hiddenColumns` | `pageRegistry.ts`、现有设置抽屉 | 现有布局/用户偏好接口 | 保存、读取、重置和旧配置缺字段回退沿用现有机制 | T7、T8 |
| 原字段兼容 | R7 | 保留“行业”=`stock_basic.industry`、“板块”=`stock_basic.board` | `StocksView` | 原字段不变 | 回归排序、分页和普通/分组切换 | T8、T10 |

### 4.8 页面 P2：每日榜单 `/board`

- 原型文件：不生成；榜单 master-detail 工作台、评分方案和分析区保持不变，只扩展 `board.table`。

| 页面功能点 | 需求 | 技术实现 | 组件/模块 | 数据/API | 状态、权限与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 榜单行业走势/概念走势 | R5、R6、R8 | `board_run` 得到 Top N 后按代码和 `run_date` 批量合并；登记两列并真实消费 | `RelatedBoardCell`、`BoardView`、`board.table` | `POST /api/board/run` | 最新日期展示；历史不即时回算，显示“—”；摘要空不影响榜单 | T6、T7、T8 |
| 历史链路隔离 | R8 | `board_compute`、回测买入日榜单及评分快照不调用摘要服务 | 后端回归测试 | `GET /api/board/compute` | 防未来数据；原排名、评分档、分项分不变 | T6、T10 |
| 点击、悬浮、列显隐 | R6、R8 | 完全复用共享单元格和现有列偏好 | `RelatedBoardCell`、设置抽屉 | 行内摘要 | `board:view` 查看；`sectors:view` 决定点击；主表四态不变 | T7、T8 |

### 4.9 页面 P3：策略筛选 `/screen`

- 原型文件：不生成；筛选构建区、运行区、结果区和历史版本弹窗保持不变，只扩展 `screen.result` 和导出字段。

| 页面功能点 | 需求 | 技术实现 | 组件/模块 | 数据/API | 状态、权限与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 筛选行业走势/概念走势 | R5、R6、R9 | `screen_scored` 形成最终命中并排序后，按代码和 `run_date` 批量附加 | `RelatedBoardCell`、`ScreenView`、`screen.result` | `POST /api/screen/run` | 最新显示；历史为空；摘要不参与筛选表达式、评分或排序 | T6、T7、T8 |
| CSV 导出 | R9 | 根据当前列可见性追加“行业走势”“概念走势”名称，空值输出空字符串 | `ScreenView.exportCsv`、现有 `downloadCsv` | 当前页面结果 | 不导出代码、分数、样本、算法字段；原列顺序和内容不变 | T8 |
| 点击、悬浮、列显隐 | R6、R9 | 复用共享单元格，登记并消费两列 | `RelatedBoardCell`、设置抽屉 | 行内摘要 | `screen:run` 查看；`sectors:view` 决定点击；重跑时随结果整体替换 | T7、T8 |

### 4.10 页面 P4：任务调度 `/data/schedule` 与任务中心

- 原型文件：不生成；任务表、数据源健康区、触发记录抽屉和编辑对话框保持不变。

| 页面功能点 | 需求 | 技术实现 | 组件/模块 | 数据/API | 状态、权限与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 任务类型选择 | R4 | 下拉加入“个股走势关联板块”，过滤和展示同步 `TaskType/TASK_LABEL` | `data.ts`、`ScheduleView`、`IngestView` | 现有 schedules/tasks API | system-only；旧任务类型兼容 | T5、T9 |
| 股票范围 | R4 | 仅该类型显示可选代码文本/列表，去空去重；空表示全市场 | `ScheduleView` 编辑对话框 | `params.codes` | 客户端先校验格式，服务端校验存在性；错误不关闭对话框 | T5、T9 |
| 强制重算 | R4 | 仅该类型显示 `force` 开关，默认关闭 | `ScheduleView` | `params.force` | 关闭时无新共同日成功跳过；失败不删调度和旧结果 | T5、T9 |
| 时间/依赖/重试/启停/立即执行 | R4 | 原通用闭环原样消费新类型，不新增算法参数 | 现有通用表单与调度器 | `/api/data/schedules*`、`/api/data/tasks*` | 自依赖、循环、非法频率按现有服务端校验；权限沿用 | T5、T9 |
| 日志与统计 | R4、R10 | 中文任务名可筛选；阶段、参数、重试来源和统计在任务详情可见 | `IngestView`、任务日志抽屉 | task result/log API | 失败明确原因；旧冠军继续可读 | T5、T9、T10 |

### 4.11 前端组件与配置接入闭环

复用判断：

- 已查找：`StockIngestScopeFields.vue`、`stockIngest.ts`、`OverviewView.vue` 的股票选择；`AppDataTable`、`AppTableColumn`、`MarketMasterDetailWorkspace`、`HelpTip/HelpHint`、`utils/permission.ts` 与现有板块详情导航。
- 直接复用：四个既有页面布局与表格、列显隐、权限函数、路由、调度 dialog、CSV helper、四态组件和远程股票候选 API。
- 必须抽取：远程股票多选已出现于采集范围和数据概览，本次会成为第三处，抽 `StockCodeMultiSelect` 并迁移现有消费点；后端股票代码格式化/去重同理抽通用 helper。
- 必须新增：现有组件清单没有同时承载冠军名称、结构化相关性解释、历史不匹配和 `sectors:view` 降级的单元格，新增业务域 `RelatedBoardCell`，由三个页面共同消费。
- 不合并：`RelatedBoardCell` 不并入 `StockAnalysisNameCell`，前者是板块相关性解释与板块导航，后者是股票走势对比队列入口，领域对象、事件和变化原因不同；只共享基础权限/router 能力。

| 页面/区域 | 运行时组件 | 现有机制 | 配置/登记 | 规范维护 | 实际消费与验证 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 三业务表格单元格 | 新增业务域共享 `RelatedBoardCell.vue` | 复用 Element Plus popover、router、权限工具 | 不新增系统组件 kind 或字段；该组件不需要独立布局调参 | 将组件、业务边界和三个消费页加入 `DESIGN.md` 真实复用组件清单 | 组件 Vitest + 三页面真实渲染 + build/E2E | T7、T8、T10 |
| `stocks.table/groupTable` | 复用现有 `wide-table` | 显式 pageRegistry slot | `componentMeta.columns` 各加两个 key，页面消费 `hiddenColumns` | 无新布局原型/字段/schema | pageRegistry 双向契约、显隐保存/回退 | T7、T10 |
| `board.table` | 复用现有 `wide-table` | 同上 | 登记两列 | 同上 | 同上 | T7、T10 |
| `screen.result` | 复用现有 `data-table` | 同上 | 登记两列 | 同上 | 显隐还影响 CSV 输出 | T7、T8、T10 |
| `data-schedule` | 复用现有 detail 页面和编辑 dialog | 通用任务表单 | 不新增 layout 字段；任务参数属于业务表单状态并保存进 `scheduled_job.params` | 不改页面登记结构 | 新建、编辑、回显、取消、启停、立即执行 E2E | T9、T10 |
| 股票范围选择 | 抽取通用 `StockCodeMultiSelect.vue`，由既有 `StockIngestScopeFields`、数据概览和新相关性表单共同消费 | 复用 `getStockQuality` 远程候选、Element Plus 多选、统一粘贴去重 | 纯业务表单组件，不新增系统 kind/配置字段 | 加入 `DESIGN.md` 真实复用组件清单并写清消费边界 | 组件测试 + 三消费点回归 + build/E2E | T9、T10 |

页面定位、原型与 slot 决策：

| 页面 | 页面类型/用户主流程 | 既有原型 | 保留区域与变更区域 | slot、成长与滚动 | 窄宽/低高度退化 |
| --- | --- | --- | --- | --- | --- |
| `/stocks` | 更新 `master-detail`；查询股票并辅助判断走势板块 | `stocks` | 保留筛选、工作台、分析区、选择条；只改 `table/groupTable` 列 | `workspace` 主成长区；`table/groupTable` 互斥且沿用 `wide-table` 内滚 | 1100px 下保持单列响应与表体横滚，不压缩成多列重排；低高度由 LayoutHost 主区兜底 |
| `/board` | 更新 `master-detail`；查看榜单并辅助判断题材 | `board` | 保留页头、榜单工作台和分析区；只改 `table` 列 | `workspace` 主成长区，`table` 沿用 `wide-table` 内滚 | 同上，排名与关键字段仍稳定可见 |
| `/screen` | 更新 `list`；运行筛选、查看并导出命中 | `screen` | 保留构建区、结果区和历史版本浮层；只改 `result` 列及 CSV | `result` 是唯一 `growMain`，沿用 `data-table` 内滚 | 结果表横滚，构建区不新增常驻说明或第二滚动层 |
| `/data/schedule` | 更新 `detail`；管理员维护任务定义并查看触发结果 | `data-schedule` | 保留任务表、健康区、触发抽屉、编辑 dialog；只增加类型专属字段 | 保持 `body` 下 `jobTable/sourceTable` 和 `triggerEvents` overlay 结构；参数仍在现有 `#overlays` dialog | 低高度由既有 detail 布局、表体和浮层正文内滚；字段说明不靠加宽 dialog 解决 |

- 本次不新增布局原型、页面路由、slot、系统组件 kind、组件配置字段、主题 token 或页面专属布局 CSS；`RelatedBoardCell` 是 `AppTableColumn` 内部的业务域复用组件，不登记假 slot。
- `RelatedBoardCell` 的多指标解释属于结构化业务数据，使用可键盘聚焦的受控 popover，并以板块名称为触发内容；不手写问号入口、随机 tooltip 样式、宽度或颜色。无 `sectors:view` 时名称仍可聚焦查看解释，但不是链接。
- 股票代码范围使用现有表单组件和辅助说明位置；占位文案不超过 DESIGN 的容量限制，完整格式/空值语义进入字段辅助说明，不新增页面常驻长文。

四态与权限态闭环：

| 页面/区域 | ready | loading | empty | error | permission |
| --- | --- | --- | --- | --- | --- |
| 三个业务主表 | 原表 + 两个可配置列；摘要空仅显示单元格“—” | 首次/刷新继续由 `AppDataTable` 分流，不新增逐行 loading | 主表继续使用唯一全局表格空态；无冠军不是整表空态 | 主请求错误接管原区域并保留重试；摘要查询异常按原接口整体错误策略处理，不吞成伪空 | 原页面 403 走既有无权态；`sectors:view` 缺失只让名称不可点击 |
| 历史日期单元格 | 名称不展示，显示“—”并提供“未保留该历史日期”解释 | 不单独加载 | 属于合法局部空值，不触发主表 empty | 不把日期不匹配当错误 | 仍按原页面查看权限；不尝试跳转 |
| 调度表/编辑 dialog | 类型、范围、force 正常回显并可保存 | 类型列表/保存/立即执行展示现有 loading | 无任务继续使用现有任务表空态 | 参数 400 保留 dialog 和输入；列表/执行失败留可见错误及重试/纠正入口 | `data-schedule:manage` / `data-task:manage` 按 system-only 守卫，前端动作与后端 403 双重验证 |

维护矩阵与 DESIGN 合规结论：

| 维护项 | 结论 | 实施/验证 |
| --- | --- | --- |
| `pageRegistry.ts` | 四个业务表 slot 各登记两个列 key 并由页面 `colVisible/groupColVisible` 真实消费；`data-schedule` 不新增列或 slot | T7、T8；`pageRegistry.spec.ts` 双向契约 |
| `COMPONENT_CATALOG` / `COMPONENT_FIELD_DEFS` / schema / preview / 后端 layout 规则 | 不涉及；共享单元格不需要布局编辑或系统组件页调参 | T7 自审确保无机械登记、无假配置 |
| `DESIGN.md` 真实复用组件清单 | 新增 `RelatedBoardCell` 与 `StockCodeMultiSelect`，分别写清三个表格消费页，以及采集/概览/相关性表单消费边界 | T7、T9、T11；组件与消费页测试 |
| `DESIGN.md` page-registry marker / router / RBAC 菜单 | 既有页面、pageKey、路由和菜单均不变，不重复登记 | T10 契约和路由回归 |
| 按钮、字体、间距、颜色 | 不新增按钮体系、字号、间距或颜色；复用现有 token/Element Plus 语义 | build、设计契约测试和三视口目视/截图检查 |
| 浮层 | 只在现有调度 dialog 增字段；共享单元格为受控 popover，不新增抽屉 | 键盘、Esc/失焦、溢出边界和低高度验证 |

前端设计验收必须覆盖 `1100×620`、`1366×768`、`1440×900`，验证无整页滚动、无 `vh/calc(vh)` 新硬编码、无双重空态、无表头/主操作重叠；执行 `cd frontend && npm test`、`npm run build`，并在安全 E2E 环境运行 `AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design`。若既有页面当前存在与本次无关的 DESIGN 偏差，记录基线并确认本次不扩大偏差；本次触达区域的硬规则违规必须在交付前修复。

## 5. 需求与开发内容映射和开发状态

| 范围 | 需求 | 计划开发内容 | 任务 | 状态 | 偏差 | 对应验收标准/验证方式/跳过证明 |
| --- | --- | --- | --- | --- | --- | --- |
| 必须 | R1 | 累计归属服务、单股路由、批量内部接口、累计口径和更新时间 | T2 | 已完成 | 一致 | 服务/接口测试已覆盖合法类型、稳定排序去重、孤儿、空结果、格式校验和 401/403；1024 股票规模回归验证单次批量查询及服务层最大快照聚合 |
| 必须 | R2 | 固定算法契约、四类基准、整股回退、中性化、缩尾、双窗口、决胜和可信度 | T3 | 已完成 | 一致 | 已独立覆盖映射基准目标日缺失时整股回退、上证目标日缺失时失败，以及中间缺口但样本达标时不回退；修订版本为 `stock-board-correlation-v2`，既有 v1 状态会自动重算 |
| 必须 | R3 | 当前冠军表、每股状态表、全量/范围原子替换、合法空清旧、失败回滚 | T1、T4 | 已完成 | 一致 | DDL、完整性校验、全量/范围替换、合法空和事务故障测试均已通过 |
| 必须 | R4 | 新任务类型、参数、写互斥、动态调度、阶段日志和结果统计 | T4、T5、T9 | 已完成 | 一致 | 后端计算、任务互斥、调度、日志和统计闭环已完成；真实全市场任务处理 5211 只股票、67592 条候选并原子切换成功；T9 已补中文标签、范围/force 表单、编辑回显、五阶段展示和结果摘要 |
| 必须 | R5 | 单股/批量摘要、日期保护、三类业务批量合并、P95与无 N+1 | T2、T6、T10 | 已完成 | 一致 | 单股/批量摘要固定一条 SQL；1/50/200 代码读取 P95 为 `2.498/3.761/6.293ms`，通过 `10/20/50ms` 门槛；日期保护和四个后端消费点回归通过 |
| 必须 | R6 | 共享单元格、统一标题/空态/悬浮/低可信提示/权限跳转、列配置 | T7、T8、T10 | 已完成 | 一致 | 共享组件、四个 slot、三个页面、权限降级和列显隐均完成；关联板块三视口真实夹具 E2E `5 passed / 4 skipped` |
| 必须 | R7 | 股票普通表和分组表接入，保留旧行业/板块语义和排序口径 | T6、T8 | 已完成 | 一致 | 已完成普通列表统一日期、分组逐行 `last_date` 的后端批量合并及普通/分组两表真实列消费；旧行业/板块字段、排序和详情入口未改 |
| 必须 | R8 | 仅 `/board/run` 接入，历史日期退化，`board/compute` 保持隔离 | T6、T8 | 已完成 | 一致 | 已验证 `/board/run` 当前/历史日期保护、榜单真实列消费及 `/board/compute` 无摘要字段，摘要不参与排名 |
| 必须 | R9 | 筛选命中批量接入、结果列和按可见列导出名称 | T6、T8 | 已完成 | 一致 | 已完成最终排序后批量合并、筛选结果真实列消费，以及 CSV 按当前列可见性仅导出冠军名称；评分、排序和内部算法字段不变 |
| 必须 | R10 | 任务可观测、结构体检、算法/API/前端/性能测试和事实文档 | T1、T5、T9、T10、T11 | 已完成 | 一致 | T10 已完成 13 项结构体检、读取性能、真实接口页面链路、完整设计门禁和真实全市场任务；T11 已完成第三方复审、确定性问题修复、业务核查与开发留痕 |
| 建议 | R11 | 暂不纳入 | - | 跳过 | 未覆盖 | 候选接口返回 `membership_scope=cumulative`，不声称当前有效 |
| 建议 | R12 | 暂不纳入 | - | 跳过 | 未覆盖 | DDL 无日期历史主键，连续任务不增长 |
| 建议 | R13 | 暂不纳入 | - | 跳过 | 未覆盖 | `/stocks/:code` 代码、请求、pageRegistry 回归无变化 |
| 建议 | R14 | 暂不纳入 | - | 跳过 | 未覆盖 | 算法仅同日收益相关，不含 shift/lead-lag 参数 |
| 暂不实现 | R15 | 不保存每日快照 | - | 跳过 | 未覆盖 | 当前表主键不含日期，成功覆盖 |
| 暂不实现 | R16 | 不保存候选明细 | - | 跳过 | 未覆盖 | 正式库仅冠军与每股状态，无候选排名表 |
| 暂不实现 | R17 | 个股详情不接入 | - | 跳过 | 未覆盖 | 详情页回归无变化 |
| 暂不实现 | R18 | 不做盘中计算 | - | 跳过 | 未覆盖 | 数据与任务参数均为日频 |
| 暂不实现 | R19 | 不比较未归属板块 | - | 跳过 | 未覆盖 | 候选只能来自 `board_member` |
| 暂不实现 | R20 | 不提供人工改冠军 | - | 跳过 | 未覆盖 | 无写 API/表单/人工字段 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：新增当前结果数据结构、升级 SQL 与数据目录

- 状态：已完成
- 依赖：无
- 需求：R3、R10
- 涉及：`backend/storage/ddl.py`、`backend/storage/catalog.py`、`agent-works/stock-board-correlation/create-stock-board-correlation.sql`、`agent-works/stock-board-correlation/rollback-stock-board-correlation.sql`、存储测试。
- 操作：定义冠军表和每股状态表、主键及必要约束；纳入 `init_db` 幂等初始化；登记数据目录、用途、关系和新鲜度；编写带前置、影响和回滚注释的 SQL。
- 产出：两张 DuckDB 当前态关系、幂等 DDL、正向/回滚 SQL、数据目录登记和存储测试。
- 影响：旧库启动只补缺失表，不改现有业务数据；无初始化冠军数据。
- 边界：只读连接跳过 DDL；迁移不得 seed 调度、菜单或权限；表为空时页面正常退化。
- 验证：隔离 DuckDB 执行两次初始化均成功；`PRAGMA table_info`/约束与计划一致；目录可见；回滚脚本只删除两个派生表。
- 完成标准：新旧库均可获得结构，重复执行幂等，SQL 注释和回滚完整。
- 实际落地情况：已在 `backend/storage/ddl.py` 新增 `stock_board_correlation` 与 `stock_board_correlation_state`，纳入 `init_db` 和数据目录；冠军表按 `(code, board_type)` 唯一，约束合法类型、有限相关值、15/40 最低样本和可信度，状态表可表达行业/概念均无冠军的合法空结果。已提供幂等正向 SQL、仅删除两张派生表的回滚 SQL及专用存储测试；未创建调度、菜单、权限或初始化数据，也未进入 T2。

### 6.2 任务 T2：实现累计行业/概念归属服务与单股契约

- 状态：已完成
- 依赖：T1
- 需求：R1、R5
- 涉及：`backend/services/stock_board_correlation.py`、`backend/services/stock_codes.py`、`backend/services/stock_ingest.py`、`backend/api/stocks.py`、相关 API 类型和测试。
- 操作：抽取采集与相关性任务共用的股票代码格式化/去重 helper 并保持采集行为不变；实现单股/批量归属查询、合法类型过滤、稳定排序去重、累计口径与最近成分快照时间；新增受 `stocks:view` 保护的单股组合路由。
- 产出：通用股票代码 helper、累计归属服务、`GET /api/stocks/{code}/related-boards`、响应类型和权限/接口测试。
- 影响：新增只读路由；现有 `/api/stocks` 暂不改变行为直到 T6。
- 边界：空集合零 SQL；股票不存在/无关系均空数组；不使用 `stock_basic.industry` 兜底；孤儿关系过滤。
- 验证：服务单测、API 200/401/403、路由扫描；查询计数断言批量一次完成；使用 1024 股票规模覆盖大批量参数与快照时间聚合。
- 完成标准：R1 输出字段、权限与异常全部可观察，现有资源 seed 无重复项。
- 实际落地情况：已新增 `backend/services/stock_codes.py`，由既有个股采集参数和相关性领域服务共用沪深代码规范化与稳定去重；新增 `StockBoardCorrelationService.get_membership/get_memberships`，通过一次 `board_member INNER JOIN stock_basic INNER JOIN board_dict` 查询过滤未知股票、板块字典孤儿和非法类型，按名称/代码稳定排序。查询返回原始 `member_snapshot_at`，服务层逐股取有效关系的最大时间，避免 DuckDB 在大批量参数与窗口聚合组合下触发内部类型断言，同时保持一次 SQL 和累计口径不变。已新增受 `stocks:view` 保护的 `GET /api/stocks/{code}/related-boards` 和前端 API 类型/调用封装；本阶段未读取冠军表、未接入列表或页面，冠军摘要与日期保护仍归 T6。

### 6.3 任务 T3：实现版本化相关性算法

- 状态：已完成
- 依赖：T2
- 需求：R2
- 涉及：`backend/services/stock_board_correlation.py` 或拆出的 `backend/indicators/stock_board_correlation.py`、领域单测。
- 操作：从 `trade_calendar` 固定取得 61 个连续开市收盘日，批量加载对应输入；实现 hfq/原始收益、禁止跨缺口桥接、固定 20/60 窗口内三方共同日期对齐、四类基准映射、整股上证回退、5/95 缩尾、Pearson、综合分、稳定决胜和可信度。
- 产出：版本化纯算法模块、批量输入装配和覆盖 R2 全部边界的领域单测。
- 影响：纯计算，不直接写正式表。
- 边界：所有输入 `<=as_of_date`；基准自身不足与个股/候选不足严格分流；上证兜底不足抛完整性错误；NaN/Inf 候选无效；负相关可胜出。
- 验证：固定小样本手算、四上市板、未知板、回退/不回退、21/61 收盘点、停牌/缺口不桥接、窗口外不补样本、常数序列、同分决胜、行业概念隔离测试。
- 完成标准：R2 每条算法契约均有独立断言，算法版本唯一。
- 实际落地情况：已新增 `backend/indicators/stock_board_correlation.py` 纯算法模块，当前修订版本为 `stock-board-correlation-v2`，固定 61 个开市收盘点、20/60 窗口、15/40 样本、四类基准、整股上证回退、市场中性化、5%/95% 缩尾、Pearson、0.6/0.4 综合分、可信度和四级稳定决胜；基准可用性同时要求目标日有效收盘与双窗口样本达标，映射基准失败时整股回退，上证失败时阻止切换，中间缺口仍按样本门槛判定。相邻开市日任一价格缺失即丢弃该区间，不跨缺口或向窗口外补样本。`StockBoardCorrelationService.load_correlation_inputs` 以固定批量查询加载后复权个股价、原始板块/指数价及累计候选，严格限制到实际目标日；计算编排按唯一板块和基准预计算收益，逐股复用而不按候选关系重复构造。版本变化会使 v1 状态在 `force=false` 下自动重算，不遗留错误旧结果。本阶段只返回内存输入与纯计算结果，不写 T1 正式表、不进入 T4。

### 6.4 任务 T4：实现计算编排、完整性校验与原子替换

- 状态：已完成
- 依赖：T1、T3
- 需求：R3、R4
- 涉及：领域服务、DuckDB 事务封装、集成测试。
- 操作：按 `list_date/delist_date/board` 点时构造全量股票池或严格校验显式范围并检查目标状态；只有目标范围日期和算法版本全部最新且 `force=false` 才跳过，否则计算每股状态与冠军，检查目标覆盖、唯一性、合法类型、有限值、样本、日期、字典引用和算法版本；用唯一临时视图在单事务全量或范围替换两张表。
- 产出：全量/范围计算编排、完整性校验、原子切换实现和事务故障注入测试。
- 影响：首次成功任务产生当前结果；后续成功覆盖，失败无变化。
- 边界：未知、未上市、已退市、北交所或其他项目外代码在写前拒绝；合法空必须有状态且清旧冠军；任一非预期逐股失败使整批失败；同日强制重算幂等。
- 验证：全量/范围、部分状态落后、算法版本变化、合法空清理、插入前异常、删除后插入异常、提交失败、重复运行、其他股票不变测试；最终由 T10 真实全市场任务复验完整输入加载、计算、校验和原子替换链路。
- 完成标准：失败前后正式表逐行一致，成功后每股每类型最多一条且状态范围完整。
- 实际落地情况：已在 `StockBoardCorrelationService` 新增共同目标日解析、点时全量股票池、显式范围整体校验、状态日期/算法版本跳过判断、批量逐股计算、状态与冠军行构造、结果覆盖/唯一性/类型/有限值/分数/样本/可信度/日期/算法版本/基准/板块字典完整性校验，以及唯一临时视图配合单 DuckDB 短事务的全量或指定范围替换。全量跳过额外检查正式状态规模和范围外冠军，避免退市或退出项目范围的旧股票残留；合法空仍写状态并删除旧冠军。新增 T4 集成测试覆盖全量、范围、部分状态落后、版本变化、强制幂等、合法空、未知/未上市/已退市/北交所代码、日期/版本/字典/类型污染、删除/插入阶段故障和提交前故障；本阶段未注册异步任务、写互斥、调度或页面能力，仍严格留给 T5 以后。

### 6.5 任务 T5：接入异步任务、写互斥、调度和可观测结果

- 状态：已完成
- 依赖：T4
- 需求：R4、R10
- 涉及：`backend/services/async_task.py`、`backend/scheduler/scheduler.py`、`backend/api/data_admin.py`、任务/调度测试。
- 操作：注册类型、处理器、`can_cancel=true/can_resume=false` 能力、写互斥和调度白名单；复用参数规范化；在各阶段调用取消检查且原子事务内不取消；输出固定阶段日志和完整统计；支持安全跳过、force、范围、调度重试来源。
- 产出：任务/调度注册、能力元数据、参数校验、阶段日志、结果统计和任务/调度集成测试。
- 影响：手动任务与管理员调度均可创建该类型；不自动创建默认 job。
- 边界：普通用户仍无任务权限；长计算阶段每次 SQL 只短暂持有 DuckDB 客户端锁，读请求可继续读取旧正式表，原子切换短事务期间读请求允许短暂等待；取消仅在切换前生效；失败/重启不提供续跑；调度并发按现有写槽位跳过/等待事件规则处理。
- 验证：创建、非法参数、互斥、取消、失败、调度 CRUD、依赖触发、失败重试、立即运行测试。
- 完成标准：后端任务闭环完整，统计能说明最近成功日期、覆盖、基准和空结果；代表性规模任务能通过真实任务入口完成五阶段并切换正式结果。
- 实际落地情况：已将 `stock_board_correlation` 注册到任务类型、DuckDB 写任务单槽位、处理器和可调度白名单，能力固定为 `can_cancel=true/can_resume=false`；手动任务与调度保存共用领域参数规范化，支持数组/逗号文本代码、去空去重和严格布尔 `force`，保存时校验股票存在且属于主板/创业板/科创板，执行时仍按真实目标日复核上市/退市状态。处理器输出读取候选、加载行情、批量计算、结果校验、原子切换五阶段日志，在阶段间和每 100 只股票检查取消，切换事务内不中断；成功、跳过和可预期完整性失败均返回固定统计，跳过时从正式表读取真实候选、冠军、空结果、基准和回退数量。调度沿用现有时间/依赖/重试/启停/立即执行与触发来源，不 seed 默认 job；写槽位与既有任务互斥。同步修正取消和服务重启文案，使不可续跑任务不再误报“可续跑”。最终真实任务返回目标日、5211 只目标股票、67592 条候选、行业/概念冠军 5187/5184、空结果 24、失败 0、回退 0 和成功切换统计。本阶段未增加前端任务标签或表单，留给 T9。

### 6.6 任务 T6：实现批量摘要并接入三类后端响应

- 状态：已完成
- 依赖：T4
- 需求：R5、R7、R8、R9
- 涉及：领域读取服务、`backend/api/stocks.py`、`backend/groups/stock_group.py`、`backend/api/board.py`、`backend/services/screen_score.py`/`backend/api/profiles.py`、接口测试。
- 操作：实现固定次数批量查询的摘要映射和日期保护，复用 `market_benchmark.py` 名称事实源；分别在股票当前页、分组当前页、榜单 Top N、筛选命中结果形成后批量合并。
- 产出：单股/批量摘要服务、四个后端消费点的可选响应字段及日期保护/查询计数测试。
- 影响：现有响应行新增可选 `related_boards`；原字段和排序不变。
- 边界：空集合不查询；分组保持 PG/DuckDB 分读；`board_compute` 和历史回测链路不接入；摘要异常不得被吞成伪空，主查询的整体错误策略按现有接口执行。
- 验证：最新/历史日期、逐行日期、空状态、孤儿、无 N+1、响应兼容、`board_compute` 隔离测试。
- 完成标准：四个后端消费点都只增加固定次数查询，历史数据不出现最新冠军。
- 实际落地情况：已新增 `StockBoardCorrelationService.get_related_boards/attach_related_boards`，用一条 `state LEFT JOIN champion LEFT JOIN board_dict` 查询返回去重代码映射，复用 `MarketBenchmarkService.name` 补指数名称；无状态返回 `null`，字典孤儿冠军不伪造名称，空集合零查询。统一业务日期和逐代码日期都执行 fail-closed 保护，日期不一致时保留真实截止日与基准，但行业/概念为空并返回 `as_of_mismatch`；逐代码日期映射缺项同样不泄露最新冠军。股票分页按响应 `trade_date`、分组当前页按每行 `last_date`、`/board/run` 按 `run_date`、筛选最终排序结果按 `run_date` 各批量附加一次，原字段、分页、排序与评分不变；分组继续 PG/DuckDB 分读，摘要错误沿原主请求错误策略上抛。`/board/compute` 与回测链路未接入。聚焦回归 `177 passed in 33.89s`，覆盖当前/历史 `/board/run`、筛选当前/历史、普通/分组列表、空状态、字典孤儿和旧式非标准代码兼容；50/200 行均固定一次摘要 SQL，P95 留待 T10。

### 6.7 任务 T7：新增共享展示组件并登记页面列

- 状态：已完成
- 依赖：T6
- 需求：R6
- 涉及：`frontend/src/components/RelatedBoardCell.vue`、组件测试、`frontend/src/layout/pageRegistry.ts`、`DESIGN.md`、pageRegistry 测试。
- 操作：实现名称、可聚焦结构化 popover、低可信提示、空态、历史不匹配说明和权限感知导航；为四个业务表 slot 登记两列；组件进入 DESIGN 真实复用组件清单。
- 产出：`RelatedBoardCell.vue`、四个 slot 列登记、DESIGN 组件登记、组件与 pageRegistry 契约测试。
- 影响：新增业务域复用组件，不新增系统组件 kind、配置字段、主题 token 或布局 schema。
- 边界：无 `sectors:view` 不渲染链接；空/历史不匹配均显示“—”但提示不同；最多展示四位小数；不在页面复制 popover。
- 验证：组件 Vitest 覆盖 high/medium/low/null/mismatch/有无权限、键盘聚焦和无链接跳转；pageRegistry 候选与真实消费双向测试。
- 完成标准：三个页面能消费同一组件契约，列配置可保存/读取/回退。
- 实际落地情况：已新增共享 `RelatedBoardCell` 与跨 API 复用的 `relatedBoards` 类型契约，统一呈现冠军名称、综合/20日/60日相关度、20/60日有效样本和截止日，数值最多四位小数；冠军名称使用小号朴素标签，页面不额外展示有效样本定义提示。低可信固定提示“相关性较弱”，无冠军与历史不匹配都显示“—”，但只有历史不匹配提供“未保留该历史日期的相关性结果”可聚焦提示。有 `sectors:view` 或 system 身份才生成经编码的 `/sectors/:code` 链接，无权限保持可聚焦纯文本且不触发权限错误。`board.table`、`screen.result`、`stocks.table`、`stocks.groupTable` 已各登记“行业走势/概念走势”两列，继续继承既有 `hiddenColumns` 保存、读取、重置和旧配置回退机制。T7 曾以精确 8 项过渡集合锁定待消费列；T8 已删除该集合并恢复零例外双向门禁。组件、pageRegistry 与页面状态聚焦回归 `76 passed`，生产构建通过；专项真实后端三视口 E2E `5 passed / 4 skipped`，验证列名、键盘聚焦说明、列显隐和三业务页真实数据链路。未新增系统组件 kind、配置字段、主题 token、布局 schema、路由、菜单或权限 seed。

### 6.8 任务 T8：接入个股、榜单、筛选页面与 CSV

- 状态：已完成
- 依赖：T7
- 需求：R6、R7、R8、R9
- 涉及：`frontend/src/views/StocksView.vue`、`frontend/src/views/BoardView.vue`、`frontend/src/views/ScreenView.vue`、对应 `frontend/src/api/*.ts` 类型和页面测试。
- 操作：普通/分组、榜单、筛选结果分别增加两列；筛选 CSV 按列可见性导出名称；保留主表 loading/empty/error 和布局。
- 产出：三个页面真实列消费、API 类型、可见列 CSV 输出及页面回归测试。
- 影响：默认多两列，窄视口沿用表体横向滚动；不新增排序字段。
- 边界：个股旧行业/板块语义不变；历史榜单/筛选退化；摘要空不影响评分或筛选；个股详情不改。
- 验证：三页面 Vitest、CSV 内容与隐藏列断言、普通/分组切换、日期切换、权限跳转和详情无变化回归。
- 完成标准：P1-P3 页面矩阵每个功能点均通过可观察验证。
- 实际落地情况：已在 `StockBasic`、`GroupMember`、`ScoreRunRow`、`ScreenHit` 响应类型中统一声明可选 `related_boards`，并由 `StocksView` 普通表/分组表、`BoardView` 榜单和 `ScreenView` 筛选结果共同消费 `RelatedBoardCell`；四个 slot 均通过既有 `colVisible/groupColVisible` 控制“行业走势/概念走势”两列显隐，未增加排序字段、私有 popover、页面专属宽度或第二层滚动。共享组件改为接收完整摘要与板块类型，集中执行历史不匹配和后端不可用原因的 fail-closed 展示；板块链接阻止冒泡，避免点击时同时触发股票行详情。筛选 CSV 按当前可见列动态追加“行业走势/概念走势”，仅输出冠军名称，空冠军输出空串，不泄露代码、得分、相关度、样本或算法版本。聚焦 Vitest 覆盖组件、四个 slot 双向消费、页面四态和 CSV 隐藏列，结果 `76 passed`；全量前端 `122` 个测试文件、`961` 项测试通过，生产构建通过。本阶段未完成三业务页真实关联数据的三视口 E2E；该缺口不是测试账号或登录能力限制，项目已有 `debug_system + loginAsDebugUser` 安全登录入口，而是仍缺 T10 的确定性关联数据 seed/cleanup 夹具。本阶段未改个股详情、原行业/板块语义、榜单/筛选评分排序、路由、菜单、权限 seed 或后端接口，也未进入 T9。

### 6.9 任务 T9：接入调度表单和任务中心前端

- 状态：已完成
- 依赖：T5
- 需求：R4、R10
- 涉及：`frontend/src/api/data.ts`、`frontend/src/components/data/StockCodeMultiSelect.vue`、`frontend/src/components/data/StockIngestScopeFields.vue`、`frontend/src/views/data/OverviewView.vue`、`frontend/src/views/data/ScheduleView.vue`、`frontend/src/views/data/IngestView.vue`、相关 Vitest/E2E。
- 操作：先从既有采集范围与数据概览抽取统一远程搜索、粘贴、去重和错误反馈的 `StockCodeMultiSelect`，迁移两个既有消费点并锁定原行为；再扩展 TaskType、中文标签、筛选、阶段标签，调度表单以 `PageSegmented + StockCodeMultiSelect` 增加该类型的全市场/指定股票范围和 force，完成新建、编辑回显、保存、取消、启停、立即执行和结果查看。
- 产出：通用股票代码多选组件、采集/概览迁移、相关性调度表单、任务标签/阶段展示和前端测试。
- 影响：复用现有 dialog 和任务日志抽屉；不改 pageRegistry 结构或新增配置存储。
- 边界：算法窗口/权重/基准不出现在表单；非法代码保留对话框和输入；停用/删除 job 不删当前冠军。
- 验证：通用股票选择组件及采集/概览回归、类型标签单测、相关性表单 Vitest、管理员/普通用户权限、聚焦 Playwright。
- 完成标准：P4 矩阵完整，任务结果可作为 R10 新鲜度可见入口。
- 实际落地情况：已新增真实复用 `StockCodeMultiSelect`，统一远程搜索、已选项保留、逗号/空格/换行批量粘贴、大小写规范化、稳定去重、错误反馈和请求竞态保护，并迁移 `StockIngestScopeFields` 与 `OverviewView`，相关性调度作为第三个消费者；搜索失败不清空已选值，手工非法代码保留在输入中并由后端保存校验返回明确错误。`TaskType`、中文标签和任务筛选已加入 `stock_board_correlation`，任务名称按全市场/指定数量/force 细化；任务中心补齐读取候选、加载行情、批量计算、结果校验、原子切换五阶段中文展示，并在终态日志抽屉展示目标日期、股票/候选/冠军/空结果/回退/跳过/失败/基准分布/耗时/切换统计。调度表单复用 `PageSegmented + StockCodeMultiSelect`，只开放全市场/指定股票和同日强制重算，纯函数统一承接新建参数、非空校验与编辑回显；既有频率、依赖、重试、启停、立即执行和保存失败不关闭对话框行为不变。同步修正不可续跑任务终止文案，不再误称已完成部分会保留。聚焦 Vitest `38 passed`，全量前端 `124` 个测试文件、`968` 项测试通过，生产构建通过。补正后新增 `stock-board-correlation-t9.spec.ts`：复用 `debug_system/debug_normal + loginAsDebugUser` 真实登录和真实菜单守卫，业务接口仅在页面层拦截，未写真实调度；三个固定视口 `9 passed`，覆盖存量编辑回显与取消、新建指定股票、粘贴规范化去重、空范围校验、force、保存失败保留、提交参数与中文标签、任务阶段与终态统计，以及普通用户无法进入调度和任务中心。T10 仅保留需要确定性行情数据或真实任务执行的端到端夹具验证。本阶段未新增算法参数、路由、菜单、权限、配置存储、调度 seed、数据库或后端接口，也未进入 T10。

### 6.10 任务 T10：结构体检、性能、全链路测试和构建

- 状态：已完成
- 依赖：T5-T9
- 需求：R1-R10
- 涉及：结构体检服务/测试、后端 API/集成测试、前端 Vitest、Playwright、性能脚本与报告。
- 操作：增加结果表体检；建立 1/50/200 只预热读取基准和 SQL 计数；新增安全确定性 E2E 夹具，覆盖 PG 评分/筛选资产、DuckDB 专属行情和 runner 生命周期；运行聚焦后端、完整前端测试/构建/设计门禁、pageRegistry、组件和四页面关键交互；最后通过真实任务入口执行一次代表性全市场计算，覆盖批量输入、算法、校验、落表与业务读取。
- 产出：结构体检、性能基准与 `performance-report.md`、安全 E2E 夹具/脚本、聚焦 E2E 用例和可追溯测试结果。
- 影响：测试夹具只使用隔离数据库或现有安全 E2E 机制，不写共享开发数据。
- 边界：执行会访问项目 DuckDB 的后端测试前按 `./start.sh status/stop` 处理锁，结束后恢复原服务状态；夹具 seed/cleanup 必须在后端停服、本地/测试环境和 `AI_STOCKS_E2E_WRITE=1` 下运行，只按精确前缀/日期清理并验证零残留；前端 E2E 使用 5181，固定调试账号先按 `agent-works/multi-tenant-rbac/test-users.md` 校准，不猜账号权限。
- 验证：见第 8 章命令和验收矩阵。
- 完成标准：单股 P95≤10ms、50只≤20ms、200只≤50ms；无 N+1；`npm test`、`npm run build`、`npm run test:design` 与聚焦后端/E2E 全部通过，夹具清理后无前缀残留；真实或等价全市场任务完成五阶段并成功切换，不能用纯算法基准或 Mock 页面响应替代。
- 实际落地情况：
  - 结构与读取：13 项结果体检已接入 `DataVerifier.run/run_structured`；固定 5000 状态/10000 冠军的读取基准每轮一条 SQL，1/50/200 代码 P95 为 `2.498/3.761/6.293ms`，通过 `10/20/50ms` 门槛。
  - runner 生命周期：运行态先检查空闲、快照并受控停服；停止态直接启动测试后端；退出恢复原状态。shell 回归覆盖初始运行、初始停止、守卫失败、测试失败、信号、清理和恢复失败。
  - 真实页面链路：PG + DuckDB 夹具受环境、写开关和 PG 指纹门控；股票、榜单和筛选页面真实调用后端接口，退出后六张 PG 表及 DuckDB 专属数据零残留。
  - 完整门禁：从后端停止态执行 `npm run test:design`，Vitest `969 passed`、生产构建通过、普通 E2E `102 passed / 24 skipped`、板块 `15 passed / 12 skipped`、关联板块 `5 passed / 4 skipped`、交易纪律 `6 passed / 6 skipped`、公开回测 `3 passed`，并恢复停止态。
  - 真实规模：1024 股票回归覆盖大批量归属查询；真实全市场任务按 `2026-08-28` 处理 5211 只股票和 67592 条候选，失败 0，正式结果原子切换成功。详细数据见 `performance-report.md`。

### 6.11 任务 T11：第三方视角业务/代码自审、事实文档与留痕

- 状态：已完成
- 依赖：T10
- 需求：R10、项目协作规则
- 涉及：本目录 `development-trace.md`、`business-audit.md`，以及实际受影响的 `agent-works/architecture/*`、数据字典/数据管理说明、`DESIGN.md`。
- 操作：从第三方视角复查防未来函数、基准回退、累计成员措辞、原子切换、双库边界、权限、页面复用、N+1、历史隔离、回滚与文档事实；发现确定性问题立即修复并重跑对应测试。
- 产出：更新后的计划实际落地记录、`development-trace.md`、`business-audit.md` 及确有事实变化的架构/DESIGN 文档。
- 影响：只同步最终真实实现，不写开发流水账或未落地设想。
- 边界：只修改本功能直接受影响的事实源；无代码事实变化的架构文档不为凑留痕而改，用户已有无关工作区改动不纳入格式化或修复。
- 验证：逐项回查 R1-R20 映射、Git diff、测试结果、SQL 注释、文档链接和未提交数据文件。
- 完成标准：无未解释偏差、无未修复确定性问题，事实文档与代码一致。
- 实际落地情况：
  - 契约复核：逐项核对 R1-R20、算法目标日与基准回退、防未来函数、累计成员措辞、原子切换、失败保旧、双库边界、任务互斥、权限、历史日期隔离、页面复用、四态、DESIGN、SQL、发布和回滚。
  - 已修问题：基准目标日契约、重复收益计算、旧版本标识、股票多选占位、runner 停止态、榜单/筛选真实链路、验收状态失真、任务偏好迟到回填加载态，以及公开回测超时边界。
  - 规模缺陷：真实全市场执行暴露大批量 `IN` 参数与窗口时间聚合组合的 DuckDB 内部断言；改为单次读取原始快照时间并在服务层逐股取最大值，新增 1024 股票规模回归。
  - 最终验证：真实任务处理 5211 只股票、67592 条候选，行业/概念冠军 5187/5184、空结果 24、失败 0并原子切换成功；股票列表接口抽查 20 行均返回关联摘要。后端聚焦、Ruff、前端 Vitest、生产构建和完整设计门禁均通过。
  - 文档结论：需求业务口径、R1-R20 与验收标准未变化；`requirement.md` 仅回写阶段完成状态和证据。已新增 `agent-works/architecture/stock-board-correlation.md` 作为模块技术事实源，并同步 README、数据管理架构、DESIGN、开发留痕、业务核查、性能记录和通用规模测试约束。T11 完成，未进入后续功能阶段。

## 7. 数据库、SQL、seed 与配置计划

| 类别 | 路径/事实源 | 用途 | 执行时机 | 影响范围 | 回滚方式 |
| --- | --- | --- | --- | --- | --- |
| DuckDB DDL | `backend/storage/ddl.py` | 幂等创建冠军表和每股状态表 | 应用启动 `init_db`；部署后、任务启用前 | 只新增派生关系，旧数据不迁移 | 回滚代码并执行回滚 SQL；页面字段无数据时退化 |
| 正向 SQL | `agent-works/stock-board-correlation/create-stock-board-correlation.sql` | 运维审阅/手工升级备用，内容与 DDL 一致 | 自动初始化不可用时，停写任务后执行一次 | 同上 | 使用配套回滚 SQL |
| 回滚 SQL | `agent-works/stock-board-correlation/rollback-stock-board-correlation.sql` | 删除两张派生表 | 停用相关调度、确认无需保留当前结果后 | 仅丢失可重算冠军和状态 | 重新执行正向 SQL 并全量重算；不承诺恢复旧冠军 |
| DuckDB 调度表 | 现有 `scheduled_job.params` | 保存 `codes`、`force` 和通用频率/依赖/重试 | 管理员创建/编辑时 | 不改表结构；不 seed 默认任务；与任务状态/行情共享 DuckDB 串行访问 | 停用或删除对应 job；当前冠军保留 |
| 菜单/资源 seed | `backend/storage/pg_ddl.py` | 复用现有 `stocks:view`、`board:view`、`screen:run`、`sectors:view`、`data-task:manage`、`data-schedule:manage` | 无新增 seed 执行 | 不改变角色、菜单或租户权限 | 不适用；通过路由扫描确认复用正确 |
| 页面列配置 | `frontend/src/layout/pageRegistry.ts` | 登记四个业务表的两列候选 | 前端发布即生效 | 旧用户配置缺新 key 时按现有默认回退为可见 | 回滚前端登记和列消费；旧配置中的未知 key 由现有兼容机制忽略 |
| 算法配置 | 领域模块版本常量 | 固定 R2 映射、窗口、阈值、权重和缩尾 | 编译/部署时 | 所有任务同一口径 | 回滚版本并执行全量重算；禁止混用结果 |
| E2E 夹具 | `backend/devtools/e2e_stock_board_correlation.py`、`./start.sh e2e-stock-board-correlation` | 为三页面、权限和调度交互提供真实后端确定性数据 | 仅聚焦 E2E 前 seed，结束后无论成功失败均 cleanup；runner 负责停服和恢复 | PG 只写 `default/debug_system` 下固定 `e2e_sbc_*` 评分/筛选资产，DuckDB 只写 `9977*.SZ`、`E2ECORR_*`、`E2E相关-`、`e2e_sbc_*` 与 2097 年日期；受本地环境、写开关和 PG 指纹门控 | cleanup 按精确归属/主键/代码/前缀/日期删除，并断言六张 PG 表及 DuckDB 专属数据零残留 |

SQL 文件实施要求：必须包含总体用途、字段注释、前置条件、执行语句、影响范围、验证 SQL 和回滚说明；不得包含本地数据库路径、密钥或调度 seed。

当前实施状态：两张 DuckDB 当前态表、正向/回滚 SQL、数据目录、固定算法、任务调度、页面列、独立结构体检、读取性能门槛、安全 E2E 夹具、分组设计门禁、第三方业务核查和开发留痕均已落地；T1-T11 全部完成。

## 8. 测试与验证计划

### 8.1 后端单元与集成

- 算法：后复权、四基准映射、未知板回退、指数样本不足整股回退、上证不足全任务失败、个股/候选不足不回退、中性化、日期对齐、缩尾、双窗口、决胜、负相关和类型隔离。
- 存储：DDL 幂等、主键、全量/范围切换、合法空清旧、事务回滚、算法版本、状态与冠军一致。
- 接口：R1 单股归属、摘要结构、空集合、日期不匹配、股票/分组/榜单/筛选批量合并、`board_compute` 隔离、401/403 和路由资源扫描。
- 查询计数：50/200 行调用前后固定次数，不允许逐行读取相关性。
- 计划命令：先判断服务锁状态，再运行新增测试文件及受影响既有测试，例如 `python -m pytest backend/tests/test_stock_board_correlation.py backend/tests/test_api.py backend/tests/test_stock_group.py backend/tests/test_stage4_board.py backend/tests/test_stage5_resource_codes.py -q`。
- 具体完成情况：T1 存储、DDL、目录聚焦测试为 `35 passed`；T2 累计归属、采集兼容和接口聚焦测试为 `44 passed`。T3 执行算法、归属和存储聚焦回归为 `31 passed`。T4 聚焦回归为 `47 passed`。T5 及 R2 修订聚焦回归为 `153 passed`。T6 执行摘要、股票/分组、榜单、筛选、算法、任务、调度及既有数据管理链路聚焦回归，结果 `177 passed in 33.89s`；覆盖单股/批量摘要、统一/逐行日期保护、当前/历史消费、50/200 行固定一次摘要 SQL、`board_compute` 隔离和 T1-T5 兼容。前端任务表单、页面列、最终 P95 和全链路验证仍待 T7-T10。

### 8.2 性能基准

- 固定夹具：至少 5000 股票、约 50000 累计候选、约 10000 冠军上限；读取夹具分别准备 1、50、200 代码。
- 条件：本地预热 DuckDB、不含公网、同一硬件连续多轮，报告样本数、P50/P95、SQL 次数和数据规模。
- 门槛：单股 P95≤10ms、50只≤20ms、200只≤50ms；数据库请求次数不随行数线性增长。
- 报告路径：`agent-works/stock-board-correlation/performance-report.md`。
- 具体完成情况：仓库内纯算法入口已按固定种子 `20260829`、5000 股票、50000 候选执行，结果见 `performance-report.md`；纯计算单轮为 `61.646693s`、`811.074 candidate/s`、计算阶段 Python 分配峰值 `2.66 MiB`。T10 读取入口固定 5000 状态/10000 冠军，预热 5 轮并正式执行 50 轮；1/50/200 代码 P50 为 `1.944/3.182/5.574ms`，P95 为 `2.498/3.761/6.293ms`，每轮均为一条 SQL，`--enforce` 全部通过。

### 8.3 前端组件、页面与配置

- `RelatedBoardCell`：名称、四位精度、悬浮信息、低可信、空值、日期不匹配、有/无 `sectors:view`。
- 页面：Stocks 普通/分组、Board 最新/历史、Screen 最新/历史/CSV、Schedule 新建/编辑/非法输入/执行结果。
- pageRegistry：四个 slot 的候选 key 与页面 `colVisible` 消费双向一致；不新增重复 kind/schema/字段。
- 四态：主请求 loading/empty/error 沿用；相关摘要合法空只影响单元格，不制造逐行 loading/error。
- 测试与构建：必须执行 `cd frontend && npm test` 和 `npm run build` 同步 `dist`，不得只跑聚焦 Vitest 代替完整前端契约门禁。
- 设计门禁：使用校准后的本地 E2E 环境执行 `AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design`，覆盖 1100×620、1366×768、1440×900 以及 ready/loading/empty/error/permission；若实际安全环境为 `test|local`，仅替换环境枚举，不放宽写门控。
- E2E：通过 T10 的 seed/cleanup 入口准备确定性数据，使用 5181 验证列显隐、结构化说明、权限跳转、历史退化、调度配置/回显/取消/立即执行；需要新增/更新稳定 `data-testid` 或可访问名称，不使用坐标、CSS 层级或临时中文正文匹配。
- 具体完成情况：T2 新增 `StockBoardMembership` 前端 API 类型与请求封装，聚焦 API 测试 4 项通过，`npm run build` 成功并同步本地 `frontend/dist`。完整 `npm test` 为 950/951 项通过，唯一失败来自本次未触达且 `HEAD` 已存在的 `QualityView.vue` 两处 DESIGN 基线违规（`gap: 4px`、`line-height: 1.5`）；为遵守单阶段边界未在 T2 混入该页面修复。T2 未新增或修改页面、组件、布局配置和样式，页面四态及 DESIGN 验收仍待 T7-T10。
- T7/T8 具体完成情况：共享单元格、四个表格 slot 列登记与真实消费、权限降级、历史 fail-closed、行点击隔离及筛选 CSV 可见列契约均已落地；T8 聚焦回归 `76 passed`，完整 `npm test` 为 `122 passed / 961 passed`，`npm run build` 通过。三业务页的真实关联数据及三视口 E2E 继续由 T10 的确定性 seed/cleanup 夹具验证；未在 T8 执行的原因是数据夹具尚未建立，不是测试账号或登录入口缺失。

### 8.4 结构体检与异常

- 检查主键重复、非法板块类型/可信度、非有限分数、样本低于 15/40、冠军字典孤儿、状态/冠军日期或版本不一致、结果日期晚于 `daily_bar/board_bar/index_bar` 可用日。
- 模拟无候选、仅一种类型、停牌错日、无板块指数、上证兜底不足、任务异常、事务失败、同日重复、两个写任务竞争、字典后续消失。
- 模拟部分股票状态已最新、部分缺状态/落后及算法版本升级，证明 `force=false` 不会错误整批跳过。
- 具体完成情况：T3 已覆盖无候选、个股与候选短窗样本不足、映射基准不可用、上证兜底不足、常数中性序列、负相关和日历/价格缺口；T4 已覆盖目标覆盖、唯一类型、有限值/样本/分数/可信度、日期与算法版本、基准映射及回退标记、板块字典引用和事务异常。T10 已把 13 项独立结构体检接入文本与结构化报告，并用专用测试覆盖合法结果、状态/冠军污染、孤儿、版本和未来日期。

### 8.5 需求与范围回归

- 逐项核对 R1-R10 均有代码、任务状态和可观察验证；R11-R20 均保持跳过证明。
- 回归 `/stocks/:code`、`/api/board/compute`、评分/筛选排序与原有“行业/板块”语义未变化。
- 检查正式库不存在每日快照、候选明细、人工冠军字段或盘中参数。
- 具体完成情况：T11 已逐项回查 R1-R20、功能提交范围、正式关系、接口和页面入口。R1-R10 均有代码、任务状态、验收证据和事实文档；R11-R20 均保持跳过，未出现当前成员时间线、历史快照、候选明细、个股详情、盘中计算、全市场未归属比较或人工冠军入口。`/api/board/compute`、原行业/板块语义、评分/筛选排序和详情页面边界未变化。

## 9. 发布与回滚

### 9.1 发布前检查

- T1-T11 完成且计划状态、实际落地、测试结果同步更新。
- 确认后端服务状态并按锁规则完成测试；前端 build、聚焦 E2E 和性能门槛通过。
- SQL 与代码 DDL 一致；无 `data/`、`logs/`、环境文件或密钥进入改动。
- 管理员尚未创建相关调度，或发布窗口内先保持停用。

### 9.2 发布顺序

1. 发布后端 DDL、领域服务、任务、读取接口和权限扫描测试。
2. 启动应用执行幂等 DDL，验证两张表与任务类型可见。
3. 先手工执行一次全量任务，检查 `as_of_date`、覆盖数、基准分布、回退数、空结果和结构体检。
4. 发布前端共享组件、三页面列和调度表单。
5. 管理员按实际上游任务创建依赖调度；不由代码强制 seed。
6. 观察首轮自动任务和列表接口 P95，再确认发布完成。

### 9.3 回滚

- 前端异常：先回滚前端，后端新增可选字段对旧前端兼容。
- 读取接口异常：回滚后端业务接入，保留派生表和任务可停用状态。
- 计算异常：立即停用相关调度，保留最后成功正式结果；修复后 `force=true` 全量重算。
- 结构需彻底撤回：停用调度、回滚代码、执行 `rollback-stock-board-correlation.sql`。两表均为可重算派生数据，可删除，但删除后无法恢复此前冠军；重新上线需全量重算。
- 不修改现有菜单、角色或用户资产，因此无需权限/资产数据回滚。

## 10. 风险、假设与待确认项

### 10.1 风险

- 累计 `board_member` 会让已退出概念继续参与，可能选出业务上已过时板块；接口和页面必须坚持“走势相关”措辞，不宣称当前有效归属。
- 约 5 万候选对虽然不落库，若按对逐 SQL 或保留无界缓存仍会拖慢任务；必须批量加载并在任务后释放。
- 调度定义、任务日志和正式结果都在 DuckDB；长时间持有 `DuckDBClient` 事务锁会阻塞任务中心和业务查询。计算阶段只能短 SQL + 内存计算，正式表切换压缩为短事务，并用并发读取测试量化等待时间。
- 指定代码任务可能让不同股票保留不同 `as_of_date`；读取必须逐股票使用状态表日期，不能假设全表只有一个日期。
- 四基准行情质量直接影响全市场切换；上证兜底不足必须 fail-closed，不能部分发布。
- 合法空结果只记录行业/概念冠军是否存在，不持久化逐股空结果原因；当前页面按需求显示“—”。若要区分新股样本不足、短期行情缺口或无候选，需要新增需求和数据契约，不能从当前布尔状态反推。
- 新增两列会增加宽表横向滚动，必须依靠列显隐和结构化 popover，不压缩成不可读列宽。

### 10.2 假设

- `stock_basic.board` 继续使用“主板/创业板/科创板”，交易所由代码后缀识别；异常值按上证回退并计数。
- 四个指数代码继续由 `index_bar` 提供；本算法不读取 `backtest.benchmark_main`。
- `stock_board_correlation_state` 是支撑合法空结果和逐股日期保护的当前状态，不属于用户拒绝的历史快照/候选明细。
- 首期不缓存即可达到读取门槛；若实测不达标，先优化单次 SQL/序列化，再另行评估带完整失效契约的缓存，不在本计划预埋。

### 10.3 待确认项

无阻塞待确认项。实施中的命名微调、测试文件拆分和 SQL 细节可在不改变 R1-R20、接口响应、权限和验收口径的前提下按项目现有模式确定；若发现必须改变流程、数据结构、权限、接口或验收标准，应暂停对应任务并回到需求确认。

### 10.4 阶段合理性与范围审计

- R1-R3 是不可跳过的算法/当前态基础；先落 T1-T4 再接任务和读取，避免前端依赖未稳定口径，阶段合理。
- T5（任务调度）与 T6（批量读取）均依赖 T4，但彼此无实现依赖，可在 T4 后并行；T9 仅依赖 T5，T7-T8 依赖 T6，两个前端分支可并行，最终由 T10 汇合。计划编号表达推荐阅读顺序，不强制造成无意义串行。
- T7 在 T6 响应契约稳定后接入，T8 在共享单元格和列登记后接三页；T10 后置全链路与性能，T11 最后做第三方复审和事实同步，未发现倒置测试或前端先于接口契约的问题。
- 抽取 `StockCodeMultiSelect`、通用股票代码 helper、增加当前状态表和安全 E2E 夹具均可回溯到 R3/R4/R5/R10 及项目复用/验证红线，是完成本次闭环的必要技术依赖，不新增用户业务能力。
- R11-R20 均保持跳过，未引入当前成员时间线、历史快照、候选排名、个股详情、盘中计算、全市场风格识别或人工冠军入口；若实现 diff 出现对应表、路由、字段或 UI，按超范围缺陷处理。
