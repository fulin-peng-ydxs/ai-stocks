# 个股走势关联板块

## 模块定位

本模块在股票截至目标交易日已经收录的行业、概念候选中，分别选出近期走势最相关的行业冠军和概念冠军。计算通过版本化后台任务完成，股票列表、分组列表、每日榜单和策略筛选直接批量读取对应业务日快照，连板天梯则为整份当日快照读取同日冠军或样本不足时的最近历史冠军；读取发现该日期、该范围从未生成快照时，只幂等创建异步首次计算任务，不在页面请求线程内逐股计算或写正式结果。

> “走势相关”表示在扣除共同市场基准后，股票与板块收益的同步程度；不表示公司主营归属、当前有效成分关系、因果关系或投资建议。

当前端到端运行事实见 [`../stock-board-correlation/stock-board-correlation-closed-loop-flow.md`](../stock-board-correlation/stock-board-correlation-closed-loop-flow.md)，需求与验收边界见 [`../stock-board-correlation/requirement.md`](../stock-board-correlation/requirement.md)，开发和验证证据见 [`../stock-board-correlation/plan.md`](../stock-board-correlation/plan.md) 与 [`../stock-board-correlation/performance-report.md`](../stock-board-correlation/performance-report.md)。

## 页面字段怎么理解

| 字段 | 含义 | 使用方式 |
| --- | --- | --- |
| 综合相关度 | `0.6 × 20日相关度 + 0.4 × 60日相关度`，范围 `[-1, 1]` | 越接近 1 表示同向同步越强；越接近 -1 表示反向同步越强；接近 0 表示线性同步较弱 |
| 20 日相关度 | 最近 20 个收益区间内，股票与板块扣除基准后的缩尾 Pearson 相关系数 | 更敏感地反映近期走势 |
| 60 日相关度 | 最近 60 个收益区间内，同口径的相关系数 | 更偏向中期稳定性 |
| 20 日有效样本 | 20 日窗口内，股票、候选板块和实际基准三方同日均存在可计算收益的日期数 | 最大为 20，少于 15 时该候选无效 |
| 60 日有效样本 | 60 日窗口内，三方共同有效收益日期数 | 最大为 60，少于 40 时该候选无效 |
| 数据截止日 | 本轮计算使用的最后一个开市日 | 页面业务日期与它不一致时不展示冠军 |

有效样本不是“数据库里有多少条收盘价”，也不是自然日数量。一条收益需要相邻两个市场开市日都有合法收盘；随后还要求股票、候选板块和基准指数在同一个区间结束日都能得到收益。任一方缺失，该日期不会进入相关性计算。

例如 20 日窗口显示 `18`，表示最多 20 个收益区间里只有 18 个日期满足三方共同有效。它仍超过 15 的最低门槛，可以计算，但证据完整度低于满样本 `20`。样本数只说明数据支撑强弱，不说明相关方向，也不能单独代替相关系数和可信度。

## 核心技术

| 层次 | 当前实现 | 关键入口 |
| --- | --- | --- |
| 纯算法 | 固定开市日历、收益构造、基准选择、市场中性化、缩尾 Pearson、双窗口加权、可信度和稳定决胜 | `backend/indicators/stock_board_correlation.py` |
| 领域服务 | 股票池与目标日解析、点时兼容候选和行情批量加载、唯一代码收益预计算、完整性校验、按日快照写入和摘要读取 | `backend/services/stock_board_correlation.py` |
| 异步任务 | `stock_board_correlation` 五阶段任务、DuckDB 写互斥、取消检查、结果统计 | `backend/services/async_task.py` |
| 结果维护与调度 | 缺失快照由读取入口创建一次首次计算；已有结果的再次维护支持最新完整日或固定交易日、全市场或指定股票，手动与调度均强制重算，代码不创建默认调度 | `backend/services/stock_board_correlation.py`、`backend/services/result_maintenance.py`、`backend/scheduler/scheduler.py` |
| 数据结构 | 冠军与状态按交易日快照（每日一行），保存各交易日结果，不保存候选明细 | `backend/storage/ddl.py` |
| 后端读取 | 单股累计归属及冠军接口；股票、分组、榜单和筛选结果形成后批量附加摘要；天梯按整份日期快照合并有效冠军，当日样本不足时附带历史来源 | `backend/api/stocks.py`、`backend/groups/stock_group.py`、`backend/api/board.py`、`backend/services/screen_score.py`、`backend/services/limit_ladder_query.py` |
| 前端展示 | 四个表格 slot 复用同一单元格并在后台轮询时只合并走势摘要；表格与天梯复用同一轮询生命周期，分别保留轻量固定间隔和天梯分阶段退避策略 | `frontend/src/components/RelatedBoardCell.vue`、`frontend/src/composables/useAsyncResultPolling.ts`、`frontend/src/composables/useRelatedBoardFirstLoad.ts`、`frontend/src/layout/pageRegistry.ts` |

## 系统架构

```mermaid
flowchart LR
  BM[(board_member / board_dict)] --> SVC[StockBoardCorrelationService]
  CAL[(trade_calendar)] --> SVC
  STOCK[(daily_bar 后复权收盘)] --> SVC
  BOARD[(board_bar 原始收盘)] --> SVC
  INDEX[(index_bar 基准收盘)] --> SVC
  TASK[异步任务 / 动态调度] --> SVC
  SVC --> ALG[v2 纯算法]
  ALG --> CHECK[完整性校验]
  CHECK --> STATE[(stock_board_correlation_state)]
  CHECK --> WINNER[(stock_board_correlation)]
  STATE --> READ[批量摘要读取]
  WINNER --> READ
  READ -->|同日快照缺失| TASK
  READ --> PAGES[股票 / 分组 / 榜单 / 筛选 / 天梯]
```

## 算法口径

### 1. 日期与收益

- 从 `trade_calendar` 取得截至目标日最近 61 个连续开市收盘点，对应最多 60 个收益区间。
- 个股收盘使用 `close × COALESCE(adj_factor_clean, adj_factor)` 后复权口径；板块和指数使用原始连续收盘。
- 收益按相邻开市日计算：`return_t = close_t / close_(t-1) - 1`。任一相邻收盘缺失、非有限或不大于 0，该区间收益缺失；算法不会跨缺口桥接，也不会向窗口外补样本。

### 2. 基准选择与回退

| 股票范围 | 默认基准 |
| --- | --- |
| 沪市主板 | 上证指数 `000001.SH` |
| 深市主板 | 深证成指 `399001.SZ` |
| 创业板 | 创业板指 `399006.SZ` |
| 科创板 | 科创 50 `000688.SH` |
| 无法识别的板块/交易所 | 上证指数并标记回退 |

默认基准必须在目标日存在合法收盘，并同时满足 20/60 日最低 15/40 收益样本。映射基准不足时整只股票统一回退上证指数；上证指数仍不足则整批任务失败，不发布部分结果。

### 3. 共同有效样本与市场中性化

对每个候选板块和每个窗口，仅保留以下三组收益同时存在的日期：

```text
valid_dates = stock_returns ∩ board_returns ∩ benchmark_returns
```

随后分别扣除同日基准收益：

```text
stock_neutral_t = stock_return_t - benchmark_return_t
board_neutral_t = board_return_t - benchmark_return_t
```

因此页面中的 `sample_20/sample_60` 就是两个窗口各自 `valid_dates` 的数量。它回答的是“这次相关性有多少个真正可比较的共同日期支撑”。

### 4. 缩尾、相关度和综合分

- 股票和板块的中性收益序列分别按自身 5%/95% 分位缩尾，降低极端单日波动影响。
- 对缩尾后的两组序列计算 Pearson 相关系数。常数序列、非有限结果或样本不足均使该候选无效。
- 综合相关度固定为：`score = 0.6 × corr_20 + 0.4 × corr_60`。
- 行业和概念分开评选。候选先按综合分降序，再按 60 日相关度、60 日有效样本降序，最后按板块代码升序稳定决胜。

### 5. 可信度

| 等级 | 条件 |
| --- | --- |
| 高 | 60 日有效样本不少于 50、综合相关度不低于 0.70，且 20/60 日相关度同号 |
| 中 | 60 日有效样本不少于 40，且综合相关度不低于 0.50 |
| 低 | 其它仍满足候选最低样本门槛的结果 |

负相关结果是合法结果：它表示扣除市场基准后，股票和该板块更倾向反向变化。如果某类型所有合格候选都为负，最高的负相关候选仍可能成为冠军，但可信度会是低。冠军表示“候选集合里相对最优”，不保证绝对相关性强。

## 计算与发布流程

1. 解析最新共同完整交易日或用户选定的固定交易日，以及全市场/指定股票范围；固定日不能被静默回退到更早日期，并拒绝未知、尚未上市、已退市、北交所或项目范围外的显式代码。
2. 一次批量读取行业/概念候选：`first_seen_date IS NULL` 的历史关系始终参与，明确日期的关系仅在 `first_seen_date <= 目标日` 时参与；按唯一股票、板块和基准加载 61 个收盘点。
3. 按唯一板块和基准预计算收益映射，逐股复用，避免按候选关系重复构造。
4. 分别计算行业、概念冠军，并生成每股状态。没有合格冠军是合法状态，不视为逐股失败。
5. 校验目标覆盖、唯一性、类型、有限值、样本、日期、算法版本、基准和板块字典引用。
6. 仅在全部校验通过后，用一个短 DuckDB 事务替换目标范围的冠军表和状态表；失败或取消保留最后成功结果。

任务中心固定展示读取候选、加载行情、批量计算、结果校验、原子切换五阶段。结果维护入口始终传入 `force=true`，即使已有同版本结果也重算；任务可在切换前协作式取消，不支持从不完整结果续跑。失败不切换当前态，保留最后成功结果。

## 数据模型

### `stock_board_correlation`

每只股票、每种板块类型、每个交易日一行冠军快照，主键为 `(code, board_type, as_of_date)`。核心字段包括：

- `score/corr_20/corr_60`：综合、短窗和长窗相关度，均限制在 `[-1, 1]`。
- `sample_20/sample_60`：共同有效收益样本，数据库约束最低为 15/40。
- `confidence`：`high | medium | low`。
- `benchmark_code/benchmark_fallback`：实际使用的市场基准及是否回退。
- `as_of_date/computed_at/algorithm_version`：数据截止日、计算时间和算法版本。

### `stock_board_correlation_state`

每只成功处理的股票在每个交易日一行，即使行业和概念都没有冠军也会写入。主键为 `(code, as_of_date)`；`has_industry_champion/has_concept_champion` 表示两种冠军是否存在，支撑合法空结果、日期保护和版本重算判断。`industry/concept_empty_reason` 保存 `no_candidates | insufficient_samples | invalid_correlation`，对应的 `*_max_sample_20/60` 保存该类型候选共同有效样本的最高值；有冠军时这些字段为空。

两张表都是可重算派生的每日快照，保存各交易日冠军；状态表同时保存无冠军时的结构化原因和候选最高共同样本数，但不保存全部候选相关性。正向与回滚 SQL 位于：

- `agent-works/stock-board-correlation/create-stock-board-correlation.sql`
- `agent-works/stock-board-correlation/migrate-as-of-snapshot-pk.sql`
- `agent-works/stock-board-correlation/migrate-board-member-first-seen-date.sql`
- `agent-works/stock-board-correlation/add-empty-result-reasons.sql`
- `agent-works/stock-board-correlation/rollback-stock-board-correlation.sql`

应用初始化会检测旧版冠军表和状态表主键，并在一个事务内迁移为按日主键；`board_member.first_seen_date` 通过幂等迁移补列。单独 SQL 保留给受控发布、演练和人工核验。

## 页面、API 与权限

| 能力 | 入口 | 权限与行为 |
| --- | --- | --- |
| 单股累计归属和冠军 | `GET /api/stocks/{code}/related-boards` | 需要 `stocks:view`；可传 `business_date` 启用历史保护 |
| 股票普通表/分组表 | `/stocks` | 沿用股票/分组查看权限；最终页数据形成后批量附加摘要 |
| 每日榜单 | `/board`、`POST /api/board/run` | 沿用 `board:view`；摘要不参与评分或排序 |
| 策略筛选 | `/screen`、`POST /api/screen/run` | 沿用 `screen:run`；摘要不参与命中和评分 |
| 连板天梯 | `/limit-ladder`、`GET /api/limit-ladder/{trade_date}` | 沿用 `limit-ladder:view`；按所选历史日整份天梯快照读取当日冠军或样本不足时的历史回退，不按当前可见卡片分页 |
| 板块详情跳转 | `/sectors/{board_code}` | 只有 `sectors:view` 才生成链接；无权限仍可看板块名称 |
| 任务与调度 | 数据管理任务中心、定时调度 | 使用既有 system-only `data-task:manage`、`data-schedule:manage` |

四个业务表格统一使用“行业走势”“概念走势”列名，冠军通过 `MarketBoardTag` 的 tag 变体同行显示名称与业务日涨跌幅，并复用个股详情的行情方向配色；涨红跌绿、缺行情保持中性浅底与“—”，不显示“走势最相关”角标。悬浮层保留综合相关度、20/60 日相关度、20/60 日有效样本数和数据截止日，相关度最多显示 4 位小数；有效样本的技术定义由本文统一维护，页面不重复展示定义句。消费页向共享单元格传完整摘要及行业/概念类型，由共享组件判断历史与异常展示；板块链接阻止行点击冒泡，避免同时打开股票详情。

按业务日期先匹配该日、当前算法版本状态与冠军；仅该类型当日已计算且原因为 `insufficient_samples` 时，允许读取当前版本、早于业务日的最近有效冠军。旧版本、未来日期、缺档或无候选/相关性无效不得回退。缺少状态快照时，GET 使用算法版本、日期、规范化股票范围和上游数据水位生成触发事件，幂等创建 `stock_board_correlation` 异步首次计算任务；请求线程不计算、不写正式结果，只有任务已经创建且处于 `pending/running` 时页面才显示“计算中”并通过原业务读取接口自动刷新。同一数据水位的失败任务不会被查询反复重建；上游最新日推进或同日补数改变水位后，允许一次新尝试。全局写槽被其他任务占用时，走势任务尚未创建，页面直接降级为空；写槽释放后由再次读取、结果维护或已配置调度决定是否创建。采集任务本身不直接触发失效或重算。

### 样本不足时沿用历史结果

- 行业、概念分别查询最近一条有效冠军；必须早于请求业务日、属于当前算法版本、存在一致状态快照及有效板块字典引用。没有历史结果时仍为空，不在查询中补算过去日期。
- `summary.as_of_date/benchmark` 与空结果原因保留当日事实；沿用的冠军增加 `history: {as_of_date, benchmark}`，相关度、样本数和基准均来自原结果。此回退只作用于读模型，不写回当日快照，不改变 15/40 门槛、评分、筛选表达式或回测决策。
- 正常冠军读取为一次快照 SQL 加一次按唯一板块/业务日批量行情查询；出现样本不足时再增加一次按股票和类型批量历史查询，不逐股访问。无冠军时不查行情。涨跌幅与个股详情共用服务入口，按业务日收盘相对该板块此前最近收盘计算；业务日行情缺失或价格无效返回 null，不借用相邻日期行情。历史冠军仅沿用身份和相关性，涨跌幅仍取页面业务日。
- 表格与天梯卡片共用 `RelatedBoardHistoryHint` 消费 `AppStatusDot` 显示黄色状态点及来源日期说明；表格结构化浮层显示原日期、原基准。当天再次计算有合格冠军后，下次读取自动恢复当日结果。
- 天梯热点与筛选消费同一有效冠军，热点通过 `historical_stock_count` 标出沿用历史的数量；天梯和策略筛选 CSV 都保留来源日期及“历史/当日/无结果”状态。历史日期查询始终只能向前取结果。

## 空结果怎么判断

行业或概念显示“—”不一定是错误，可能包括：

- 股票在该业务日没有该类型候选。
- 股票、候选板块或基准在窗口内缺少相邻收盘，导致共同有效样本低于 15/40。
- 中性收益为常数或相关系数无法得到有限值。
- 页面业务日期没有同日当前版本结果快照，且首次任务未能创建或同数据水位任务已经失败，此时返回 `as_of_mismatch`，页面仍统一显示“—”。
- 已成功创建该业务日首次任务且任务仍为 `pending/running` 时返回 `first_load_pending`，页面显示“计算中”。

每日状态表按行业、概念分别保存 `no_candidates`、`insufficient_samples` 或 `invalid_correlation`，样本不足时同时保存 20/60 日候选最高共同样本数。API 保留当日结构化原因；样本不足且有可用历史时显示历史冠军，否则页面显示“—”，仅在原因真实存在时通过悬浮或键盘聚焦解释。历史未重算行允许原因为空，页面不得根据 `has_*_champion=false` 自行推测。

结构体检按算法的共同有效样本口径判定：个股或冠军板块未覆盖结果目标日时显示 `WARN` 标记，右侧保留未覆盖数量，口径说明通过标记悬浮层展示；该日期差异不据此否定已经满足 15/40 门槛的结果，样本低于门槛仍判失败。基准指数必须有目标日有效收盘，其目标日缺失继续判失败。

## 性能与容量

- 候选、个股行情、板块行情和基准行情均批量读取；板块与基准收益按唯一代码预计算。
- 四个直接表格入口按当前页代码集合固定一次 SQL；连板天梯按整份当日快照代码集合固定一次 SQL，均不随行数逐股查询。
- 固定读取基准中，1/50/200 代码 P95 为 `2.498/3.761/6.293ms`，通过 `10/20/50ms` 门槛。
- 本地真实全市场任务曾处理 5211 只股票、67592 条候选并成功原子切换；该结果不代表生产并发和网络条件下的 SLA。

详细环境、固定随机种子、复现命令和真实任务统计见 [`../stock-board-correlation/performance-report.md`](../stock-board-correlation/performance-report.md)。

## 验证入口

```bash
# 纯算法、累计归属、编排、任务、读取和结构体检聚焦测试
python -m pytest \
  backend/tests/test_stock_board_correlation_algorithm.py \
  backend/tests/test_stock_board_correlation_membership.py \
  backend/tests/test_stock_board_correlation_orchestration.py \
  backend/tests/test_stock_board_correlation_task.py \
  backend/tests/test_stock_board_correlation_read.py \
  backend/tests/test_stock_board_correlation_checkup.py -q

# 共享单元格与生产构建
cd frontend
npm test -- --run src/components/__tests__/RelatedBoardCell.spec.ts
npm run build

# 安全真实后端页面链路；runner 负责服务状态、夹具和清理
AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:stock-board-correlation
```

会访问项目 DuckDB 的测试必须遵守 `AGENTS.md` 的停服、锁和原状态恢复规则。E2E 只允许在 `dev|test|local` 且显式开启写门控时执行。

## 风险事项

| 等级 | 风险点 | 影响 | 当前控制 |
| --- | --- | --- | --- |
| 中 | `board_member` 只有首次观察日，没有移出时间线 | 已退出板块的股票仍可能参与候选比较 | `NULL` 兼容全部历史，明确首次观察日晚于目标日则排除；页面不宣称当前主营或有效归属 |
| 中 | 基准或行情缺口降低共同有效样本 | 候选无冠军或可信度降低 | 相邻日不桥接、15/40 门槛、基准整股回退、上证不足整批失败 |
| 中 | 业务日当前版本无快照 | 首次读取需等待后台任务，失败时该业务日仍无结果 | GET 按数据水位幂等创建指定日期、指定范围的异步首次任务；同水位失败不循环，上游补数后可再尝试，也可由结果维护或用户调度重算 |
| 低 | 历史未重算状态没有空结果原因 | 页面仍显示“—”，但该日期无法悬浮解释 | 保持 NULL 兼容并在需要时按目标日重算，不从布尔状态推测 |
| 中 | 生产并发与硬件不同于本地验证 | 全量任务窗口或读取尾延迟可能变化 | DuckDB 写互斥、内存计算、短事务切换；生产首轮继续观察 |
| 低 | 负相关候选仍可成为相对冠军 | 用户可能误读为强同向关联 | 页面显示带符号相关度并将结果标为低可信；文档明确解释 |
