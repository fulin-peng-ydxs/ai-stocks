# 需求文档：盘感训练

> 系统：复盘啦了（ai-stocks）
> 模块定位：在策略回测、个股筛选之外，新增一个**面向人的手动交易训练**模块——以游戏化、盲测、逐日揭示的方式，让用户对随机个股/随机交易日做买卖决策，回溯思路正确性与成长轨迹。
> 文档状态：核心决策已确认（见 §4、§5），可据此进入开发计划阶段。文末 §12 为不阻塞开发的遗留确认项。

---

## 1. 背景与目标

### 1.1 要解决的问题
现有系统的回测（[backtest_service.py](backend/services/backtest_service.py)）是**机器按规则自动交易**，验证的是"策略"的有效性；它无法回答另一类问题：

- **人**面对真实历史行情、在看不到未来的前提下，买卖时机的判断对不对？
- 同一套盘感，重复训练后是否在**进步**（胜率、收益、回撤控制）？

"盘感训练"补上这块：把回测引擎的"未来函数防护"从一种工程约束，变成一种**刻意的体验设计**——用户只能看到截止"当下"的 K 线，逐日揭示，自己下买卖单，事后用真实结果对照思路。

### 1.2 目标
1. **判断思路正确性**：每笔买卖可记录理由，结束后用真实盈亏对照，定位"想对了/想错了"。
2. **结果可量化**：一局训练产出完整的交易记录、资金曲线、盈亏与风险统计、综合评价。
3. **成长可回溯**：跨多局沉淀训练历史，展示胜率/收益/评分的成长曲线。
4. **体验像游戏**：盲测、逐日揭示、键盘操作、即时反馈、结束评级，降低枯燥感。

### 1.3 非目标（本模块不做的事）
- 不做实盘/模拟盘对接，不接入实时行情，纯历史数据回放。
- 不替代回测：本模块训练的是"人"，不是"策略"。
- 不做多人对战/排行榜社交（系统当前为单机单用户，见 §3）。

---

## 2. 当前项目现状（开发依据）

以下为可直接复用的现有基础设施，均经代码调研确认。

### 2.1 行情与基础数据（DuckDB）
- 数据库：DuckDB 单文件 `/data/ai_stocks.duckdb`，连接类 [duckdb_client.py](backend/storage/duckdb_client.py)（线程安全、串行化 SQL）。
- 日线表 `daily_bar`（[ddl.py](backend/storage/ddl.py)）：主键 `(code, trade_date)`，字段含 `open/high/low/close`（不复权原始价）、`pre_close`、`volume`、`amount`、`adj_factor`、`adj_factor_clean`（去抖后分段恒定，前复权实际用列）、`turnover_rate`、`is_st`、`limit_status`（0/1/-1）、`is_one_word`。
- 市值表 `daily_metrics`：`(code, trade_date)` → `float_mv`、`total_mv`。
- 基础信息表 `stock_basic`：`code`、`name`、`exchange`、`board`、`list_date`、`delist_date`（NULL=在市）、`industry`、`price_limit_pct`（0.10/0.20/0.05）。
- 交易日历表 `trade_calendar`：`trade_date`、`is_open`。

### 2.2 关键查询能力（直接复用）
- **单股前复权 K 线（点时安全）**：[`MarketRepository.get_bars(code, end_date, lookback, adjust="qfq")`](backend/storage/repository.py)。仅返回 `trade_date <= end_date` 的数据，前复权基准取**截面日（end_date）**的 `adj_factor_clean`。这是盘感训练"逐日揭示且不泄露未来"的核心：每揭示一天，以当天为 `end_date` 取 qfq 序列即可天然防未来函数。
- **点时股票池**：[`MarketRepository.get_universe_asof(asof_date, filters)`](backend/storage/repository.py)，按截面剔除 ST / 次新 / 停牌 / 一字板 / 流通市值区间，支持板块过滤、防幸存者偏差——用于"随机抽合格个股"。
- **成交约束（防作弊/真实化）**：回测引擎 [engine.py](backend/backtest/engine.py) 已实现 `can_buy_at_open`（开盘涨停买不到）、`can_sell_at_open`（开盘跌停卖不出）、停牌顺延。
- **费用与撮合**：[broker.py](backend/backtest/broker.py) 已有佣金（0.03%，最低 5 元）、印花税（0.1%，仅卖出）、过户费（0.002%）、滑点（0.1%）的整手撮合与成本/盈亏记账，可抽取复用。

### 2.3 前端可复用资产
- 技术栈：Vue 3.4 + TypeScript + Vite 5 + Element Plus 2.7 + ECharts 5.5 + Vue Router 4 + Pinia + Axios。
- **K 线组件 [CandleChart.vue](frontend/src/components/CandleChart.vue)**：蜡烛图 + MA + 成交量 + `markers`（▲买/▼卖标记）+ dataZoom + 主题响应。盘感训练核心图表直接复用。
- 资金曲线组件 [EquityChart.vue](frontend/src/components/EquityChart.vue)：净值 + 回撤双轴。
- 交易日选择器 [TradeDatePicker.vue](frontend/src/components/TradeDatePicker.vue) + composable [useTradeDates.ts](frontend/src/composables/useTradeDates.ts)。
- 页面设置持久化 [usePageSettings.ts](frontend/src/composables/usePageSettings.ts)、主题 [useTheme.ts](frontend/src/composables/useTheme.ts)。
- API 模式：[client.ts](frontend/src/api/client.ts) axios 封装，拦截器解包 `{code,msg,data}`。
- 布局规范：必须遵守 `docs/前端布局自适应规范.md` 的 `.v-page` / `.v-grow` / `.v-scroll` 三层契约，禁止整页滚动（项目硬性规范，见记忆 `layout-no-page-scroll`）。

### 2.4 约束与惯例
- 后端起停一律走 `./start.sh`（记忆 `start-service-via-startsh`）。
- 前端改 `frontend/src` 后必须 `npm run build`（记忆 `feedback_build_after_change`）。
- 能点现有元素触发的操作不单独加按钮（记忆 `feedback-no-redundant-buttons`）。
- 复权一律 qfq，且写回口径遵守 `adj-factor-preclose-separation` / `qfq-factor-rootfix`（清洗因子用 `adj_factor_clean`，不可写回 `adj_factor`）。

---

## 3. 用户角色与使用场景

- **唯一角色：训练者（系统使用者本人）**。系统当前为单机单用户、无登录鉴权（无 user 表）。本模块**不引入用户体系**，所有训练记录归属当前本机用户；表结构预留可空 `user_id` 字段以便未来扩展，但本期不实现多用户隔离。
- **典型场景**：
  1. 想练短线手感 → 选"单股连续 K 日"模式，盲测一只随机股，逐日决策。
  2. 想批量练盘感 → 选"多股各一回合"模式，连练 N 只随机股。
  3. 复盘成长 → 进训练历史，看历次评分/收益曲线，回看某局逐笔决策与思路。

---

## 4. 功能范围

### 4.1 必须实现
1. **训练配置与开局**：选模式（单股/多股）、历史交易日范围、回合数 N、每回合连续交易日窗口 K、随机范围过滤、初始资金。
2. **盲测逐日揭示训练**：盲测（隐藏股名/代码/真实日期）、给足历史窗口、逐日"下一日"揭示、K 线实时刷新。
3. **手动买卖（资金账户 + 按手分批 + T+1 开盘成交 + 真实约束）**：见 §5.3。
4. **思路记录**：每笔交易理由（选填）+ 整局复盘笔记。
5. **一局结果统计与评价**：交易明细、资金/回撤曲线、盈亏与风险指标、对照基准、综合评分/评级、身份揭晓。
6. **训练历史与成长回溯**：历史训练列表、跨局成长曲线、单局详情回看（含逐笔决策与思路）。
7. **训练数据持久化**：新增训练相关表，落库 DuckDB。

### 4.2 建议实现（不改变核心闭环的增强项）
- **系统视角对照复盘**：一局结束后，对照展示系统对该股该时段的评分/买卖信号（复用 `score_profile` / `trade_profile` 试算），帮助用户判断"系统会怎么做"。标注为增强，不阻塞主流程。
- **暂停/续局**：进行中的训练可中断并稍后继续（依赖训练状态落库，天然可做）。
- **键盘快捷键**：B 买 / S 卖 / → 下一日 / Esc 结束。

### 4.3 暂不实现
- **多用户与账号体系**：当前系统单机单用户，本期不做登录与数据隔离；待系统整体引入用户体系后再扩展（表已预留 `user_id`）。
- **盘中分时/Tick 级行情**：现有数据仅日线，本期成交价以日线 OHLC 为准；待有分时数据后再考虑日内训练。
- **做空/融资融券/T+0**：A 股训练遵循 T+1、禁止做空，本期不做衍生玩法。
- **社交排行榜/对战**：无多用户基础，本期不做。

---

## 5. 详细功能需求

### 5.1 训练开局（配置）
- **功能描述**：用户配置一局训练参数并开局。
- **配置项**：
  - 模式：`single`（单只随机个股，N=1）/ `multi`（多只随机个股，每回合一只）。统一为"一局 = N 回合，每回合 = 一只股 + 随机起点 + 连续 K 个交易日窗口"。
  - 历史交易日范围 `[range_start, range_end]`：随机起点只在此范围内抽取。默认 = 数据最早可用日 ~ 最新交易日；用 `TradeDatePicker` 限定交易日。
  - 回合数 N（multi 模式）：默认 5，范围 1~20。
  - 每回合连续交易日窗口 K：默认 20，范围 5~60。
  - 随机范围过滤：默认排除 ST / 次新（上市 < ~250 交易日）/ 停牌密集 / 一字板，沿用 `get_universe_asof` 过滤；可选板块（主板/创业板/科创板）。
  - 初始资金：默认 100,000 元，范围 10,000~10,000,000。
  - 费用开关：默认按回测费率计入佣金/印花税/过户费/滑点；可关闭为"零摩擦"练纯时机。
- **前置条件**：行情库非空，且所选范围内存在满足过滤条件、且自起点起有 ≥K 个连续可交易日、且起点前有足够历史窗口（建议 ≥60 交易日）的个股。
- **随机抽取算法**：
  1. 在 `trade_calendar` 中取 `[range_start, range_end]` 的交易日集合。
  2. 随机抽起点 `start_date`，对其调用 `get_universe_asof(start_date, filters)` 得候选池，随机抽一只 `code`。
  3. 校验该股自 `start_date` 起有 ≥K 个连续交易日数据、起点前有 ≥60 交易日历史、窗口内不退市。不满足则重抽（设最大重试次数，超限报"可用样本不足"）。
  4. multi 模式重复 N 次，回合间股票不重复。
- **输出**：创建 `training_session`（status=`running`）及 N 条 `training_round`（每条记 `code`、`start_date`、`window_days`、状态 `pending`），返回首个回合的初始视图（不含未来数据）。
- **校验规则**：K ≤ 范围内可用交易日数；初始资金 > 单手最低买入额；N ≤ 候选池规模。
- **异常**：样本不足 → 明确提示放宽范围/过滤；行情库为空 → 引导先去数据管理补数。

### 5.2 盲测逐日揭示
- **功能描述**：回合内以"当下"为界揭示 K 线，用户看不到未来。
- **盲测口径**（已确认）：训练进行中**隐藏股票名称、代码、真实交易日期**；K 线横轴只显示"相对第 t 天 / 共 K 天"；回合结束后才揭晓真实身份与日期。
- **初始视图**：回合开始时，展示**起点前约 60 个交易日历史 + 起点当日**，给用户判断趋势的上下文；其后每次"下一日"揭示一根新 K 线。
- **点时安全实现**：每揭示到第 t 天（真实日 `cur_date`），后端以 `get_bars(code, end_date=cur_date, lookback=60+t, adjust="qfq")` 取序列；前复权基准随 `cur_date` 滚动，天然不泄露未来除权/价格。
- **揭示交互**：`下一日` 按钮 / `→` 键推进；推进到窗口末日（第 K 天）后回合自动结算。
- **停牌处理**：窗口内遇停牌日（`daily_bar` 无该日行）跳过并提示"停牌"，不占揭示节奏。
- **K 线展示**：复用 `CandleChart`，叠加 MA、成交量；已成交的买卖点用 `markers`（▲/▼）标注在对应相对日。

### 5.3 手动买卖（资金账户 + 按手分批 + T+1 开盘成交）
- **资金模型**（已确认）：每局一个资金账户，初始资金 = 配置值；可在回合内**按手（100 股/手）分批买入/卖出**，支持加仓、减仓、清仓。单回合聚焦一只股，持仓结构简单。
- **下单流程**：
  1. 用户在看到第 t 天（`cur_date`）行情后下买/卖单，指定手数（买入受可用现金约束，卖出受持仓约束）。
  2. **成交价规则**（已确认）：T+1 开盘价成交——即在下一个揭示日 `next_date` 的 `open`（前复权）成交。
  3. **真实约束**：套用 `can_buy_at_open`（`next_date` 开盘涨停 → 买入失败，提示"开盘涨停未成交"）、`can_sell_at_open`（开盘跌停 → 卖出失败）、停牌顺延至下一可交易日。
  4. **费用**：默认计入佣金/印花税/过户费/滑点（沿用回测费率与 `broker` 逻辑）；可被开局"零摩擦"开关关闭。
  5. **T+1 限制**：当日买入的持仓，当日（同一揭示日）不可卖出。
- **每笔交易理由**（已确认）：下单时可填一句操作理由（选填），随成交记录落库。
- **账户面板**：实时显示可用现金、持仓手数/成本/浮盈亏、总资产、当前相对日。
- **输入输出**：输入 = {round_id, side, hands, reason?}；输出 = 更新后的账户状态 + 待成交/已成交提示。
- **校验**：手数为正整数；买入金额（含费用）≤ 可用现金；卖出手数 ≤ 持仓手数。
- **异常**：资金不足、持仓不足、涨跌停未成交、停牌顺延，均给明确文案并不改账户状态（未成交不扣钱）。
- **回合结束清算**：窗口末日仍有持仓 → 默认按末日收盘价（前复权）强制平仓计入盈亏，并标注"到期清算"。

### 5.4 思路与复盘记录
- 每笔交易理由：见 §5.3，落 `training_trade.reason`。
- **整局复盘笔记**（已确认）：一局结束后提供复盘文本框，落 `training_session.review_note`；历史回看时可编辑。

### 5.5 一局结果统计与评价
- **结算触发**：所有回合窗口走完，session.status=`completed`。
- **统计输出**（每回合 + 整局汇总）：
  - 交易明细：逐笔 买/卖、相对日、成交价、手数、费用、单笔盈亏与收益率、持有交易日数、理由。
  - 资金曲线 + 最大回撤（复用 `EquityChart`）。
  - 指标：总收益率、胜率、盈亏比、最大回撤、平均持有天数、交易次数。
  - **基准对照**：与"该回合首日满仓买入持有到末日"（buy & hold）收益对比，判断择时是否加分。
  - **综合评分/评级**：基于收益、是否跑赢基准、回撤控制、胜率的加权评分 → 评级（如 S/A/B/C/D），用于游戏化与成长曲线。具体权重见 §12 遗留项（可先用默认权重）。
- **身份揭晓**：结算后揭示每回合真实股票名称、代码、真实日期区间，并提供跳转个股详情（[StockDetailView.vue](frontend/src/views/StockDetailView.vue)）回看。
- **建议增强**：对照系统评分/买卖信号（§4.2）。

### 5.6 训练历史与成长回溯
- **历史列表**：分页展示历次 session（时间、模式、回合数、总收益、评级），服务端分页排序（遵守记忆 `list-interaction-standards`）。
- **成长曲线**：按时间展示历次评分 / 总收益 / 胜率的趋势，回应"成长的回溯"目标。
- **单局回看**：打开任一历史 session，复现逐回合 K 线 + 买卖点 + 每笔理由 + 复盘笔记 + 统计（身份此时为已揭晓）。
- **删除**：可删除历史 session（级联删回合与交易）。

---

## 6. 数据与接口需求

### 6.1 新增数据表（DuckDB，DDL 加入 [ddl.py](backend/storage/ddl.py)）
```
training_session
  id              VARCHAR PRIMARY KEY      -- 如 train_YYYYMMDDHHMMSS
  user_id         VARCHAR        NULL      -- 预留多用户，本期空
  mode            VARCHAR                  -- single | multi
  range_start     DATE                     -- 随机起点范围
  range_end       DATE
  n_rounds        INTEGER                  -- 回合数
  window_days     INTEGER                  -- 每回合连续交易日 K
  initial_capital DOUBLE
  filters         JSON                     -- 板块/排除条件快照
  fee_enabled     BOOLEAN
  status          VARCHAR                  -- running | completed | aborted
  total_return    DOUBLE         NULL      -- 结算后汇总
  score           DOUBLE         NULL      -- 综合评分
  grade           VARCHAR        NULL      -- 评级
  review_note     TEXT           NULL      -- 整局复盘
  created_at      TIMESTAMP
  completed_at    TIMESTAMP      NULL

training_round
  session_id      VARCHAR
  seq             INTEGER                  -- 回合序号
  code            VARCHAR                  -- 真实个股（结算前前端不返回明文，见 §9）
  start_date      DATE                     -- 真实起点
  window_days     INTEGER
  cursor_date     DATE           NULL      -- 当前揭示到的真实交易日
  status          VARCHAR                  -- pending | running | done
  round_return    DOUBLE         NULL
  benchmark_return DOUBLE        NULL      -- buy&hold 对照
  PRIMARY KEY (session_id, seq)

training_trade
  session_id      VARCHAR
  round_seq       INTEGER
  seq             INTEGER                  -- 笔序
  side            VARCHAR                  -- buy | sell
  decide_date     DATE                     -- 决策日（看到的最后一根 K）
  fill_date       DATE                     -- T+1 成交日
  rel_day         INTEGER                  -- 相对第几天（盲测展示用）
  price           DOUBLE                   -- 前复权成交价
  hands           INTEGER                  -- 手数
  shares          BIGINT
  fee             DOUBLE                   -- 费用合计
  pnl             DOUBLE         NULL      -- 卖出/清算时结算
  return_pct      DOUBLE         NULL
  reason          TEXT           NULL      -- 每笔理由
  PRIMARY KEY (session_id, round_seq, seq)
```
- 命名、JSON 字段、版本/快照风格沿用现有 `backtest_*` / `*_profile` 表惯例。

### 6.2 新增后端 API（FastAPI，新增 `backend/api/training.py` + `backend/services/training_service.py`）
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/training/sessions` | POST | 开局：建 session + 抽样回合，返回首回合初始视图（不含未来/身份） |
| `/api/training/sessions` | GET | 历史列表（分页/排序，服务端） |
| `/api/training/sessions/{id}` | GET | 单局详情（running 时屏蔽未揭示数据与身份；completed 全量） |
| `/api/training/sessions/{id}` | DELETE | 删除（级联） |
| `/api/training/sessions/{id}/reveal` | POST | 揭示下一交易日，返回新增 K 线 + 待成交结果 |
| `/api/training/sessions/{id}/trade` | POST | 下单（buy/sell + hands + reason），返回更新后账户状态 |
| `/api/training/sessions/{id}/review` | PATCH | 保存整局复盘笔记 |
| `/api/training/sessions/{id}/growth` | GET（或并入列表） | 成长曲线数据 |
- 服务层复用：`MarketRepository.get_bars`、`get_universe_asof`、`broker` 撮合与费用、`engine` 的涨跌停/停牌判定函数（建议抽公共工具，避免与回测耦合）。

### 6.3 数据一致性
- 揭示与成交严格按交易日先后；`cursor_date` 落库，防止前端伪造推进。
- 前复权基准随 `cursor_date` 滚动，保证回看与训练时所见一致（点时安全）。
- 成交价、费用、盈亏一律后端计算并落库，前端不参与撮合。

---

## 7. 交互体验要求
- **布局**：`/training` 路由，新增 `TrainingView.vue`，遵守 `.v-page`/`.v-grow` 契约，整页不滚动。
  - 顶部：开局参数卡（未开局时）/ 回合进度条 + 账户面板（训练中）。
  - 主体混合成长区：上块 K 线（固定高度如 480px，复用 `CandleChart`）；中块买卖操作面板（固定）；下主表 当前回合成交明细（`min-height` + 表体内滚）。
- **游戏化反馈**：买卖即时在 K 线打标记、账户数字动效、揭示下一日有节奏感；回合/整局结束有评级弹层与身份揭晓。
- **键盘操作**：B 买、S 卖、→ 下一日（建议实现）。
- **空状态**：无历史训练时引导"开始第一局"；样本不足时给放宽建议。
- **加载/错误**：揭示与下单走 30s 标准超时；未成交（涨跌停/停牌）给非阻断提示，不改账户。
- **持久化**：开局参数用 `usePageSettings` 记忆；主题用 `useTheme`。
- **不加冗余按钮**：身份揭晓、回看入口尽量挂在现有元素（如点回合卡/股名）上。

---

## 8. 边界条件与异常场景
- 起点附近停牌密集、上市不足、窗口内退市 → 抽样阶段校验并重抽。
- 窗口内连续停牌导致可揭示日不足 K → 以实际可交易日结算并提示。
- 资金不足/持仓不足/涨跌停/一字板 → 未成交，账户不变，明确文案。
- 回合到期仍持仓 → 末日收盘强制平仓，标注"到期清算"。
- 零摩擦模式 → 费用为 0，但仍受涨跌停/停牌约束。
- 历史回看不得再泄露"训练时本不该看到"的内容之外信息错乱（completed 后全量是允许的）。
- 并发：单用户单机，但需防同一 session 被多标签页同时推进——以 `cursor_date` 乐观校验，过期推进请求拒绝。

## 9. 性能、安全与兼容性
- **防作弊（关键）**：running 状态下，后端**绝不返回未揭示的未来 K 线，也不返回真实 `code`/`name`/真实日期**；前端拿到的是脱敏序列 + 相对日。身份仅在 completed 后下发。
- **性能**：单股 60+K 根 K 线，`get_bars` 单股查询轻量；揭示为增量返回（只回新增的一根），避免整段重传。历史列表服务端分页。
- **数据量**：训练表随使用增长，量级远小于行情表，无特别压力。
- **兼容性**：复用现有 DuckDB / FastAPI / Vue3+EChart 栈，无新依赖；遵守 qfq 复权与 `adj_factor_clean` 口径。

## 10. 业务亮点与优化建议（可选增强，不扩大必做范围）
- **系统视角对照**：结算后对照 `score_profile` 评分与 `trade_profile` 买卖信号，量化"人 vs 系统"差距。
- **成长画像**：成长曲线之外，按"择时得分/止损纪律/追高频率"等维度给训练者打标签，引导改进。
- **题库化**：把出现过的"经典走势"（如放量突破后回踩）沉淀为可重练样本（依赖后续设计，标注为后续建议）。

## 11. 验收标准（可观察、可测试）
1. 开局：按配置成功抽样，single 出 1 回合、multi 出 N 个不重复回合，每回合满足窗口与历史窗口校验；样本不足时给明确提示。
2. 盲测：训练中接口与页面均不含真实股名/代码/真实日期与未来 K 线；结算后正确揭晓。
3. 揭示：逐日推进，前复权 K 线与 `get_bars(end_date=cursor_date)` 一致，停牌日正确跳过。
4. 成交：买卖按 T+1 开盘价成交；开盘涨停买不到、跌停卖不出、停牌顺延均按预期；T+1 当日买不可卖；费用与回测口径一致；零摩擦模式费用为 0。
5. 资金账户：按手分批买卖，可用现金/持仓/浮盈亏实时正确；到期强制平仓正确入账。
6. 记录：每笔理由与整局复盘均落库且可回看编辑。
7. 统计：交易明细、资金/回撤曲线、收益/胜率/盈亏比/回撤/平均持有天数、基准对照、综合评分/评级均正确产出。
8. 历史与成长：历史列表服务端分页排序；成长曲线随局数更新；单局可完整回看（含逐笔理由与复盘）；删除级联生效。
9. 布局：`/training` 整页不滚动，K 线不被压扁，表体内滚、表头吸顶（符合布局规范）。
10. 防作弊：构造请求尝试在 running 态拉取未来数据/身份，后端拒绝或脱敏。
11. 前端改动后 `npm run build` 通过；后端经 `./start.sh` 起停验证接口可用。

## 12. 遗留确认项（不阻塞开发，建议后续敲定）
1. **综合评分/评级公式权重**：收益、跑赢基准、回撤、胜率各占多少、评级阈值如何分档。影响：仅影响评价数值与游戏化体感，不影响数据结构与流程。先用默认权重（建议：相对基准超额收益 40% + 绝对收益 25% + 回撤控制 20% + 胜率 15%，S≥90/A≥80/B≥70/C≥60/D<60）实现，后续可在配置页调。
2. **基准口径**：buy & hold 用"首日满仓"还是"等额定投"。先用首日满仓。影响：仅对照数值。
3. **multi 模式回合间是否共享同一资金账户还是各回合独立账户**：默认**各回合独立账户**（聚焦单股盘感，互不影响），整局汇总取各回合平均/合计。若希望练"资金在多标的间调度"，需改为共享账户。影响：结算汇总口径，不影响单回合逻辑。
4. **历史窗口默认根数（起点前展示多少历史）**：暂定 60 交易日，后续可按体验微调。
5. **键盘快捷键与暂停续局**：列为建议实现，是否纳入首版可后定。
