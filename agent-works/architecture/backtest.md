# 回测

> 用历史数据验证「选股+买卖」策略与「评分」预测力的事件驱动回测引擎：在杜绝未来函数、撮合不失真、复权一致的前提下，产出净值曲线/绩效/逐笔成交，并以「分层命中率减全市场 base rate」量化评分的真实超额能力。

<span style="color:#2563eb">●</span> 输入方案　<span style="color:#7c3aed">●</span> 历史验证　<span style="color:#16a34a">●</span> 结果复盘　<span style="color:#dc2626">●</span> 风险约束

## 核心技术

**事件驱动引擎（逐日先卖后买）**。`backend/backtest/engine.py:223` `BacktestEngine.run` 按交易日逐日循环：执行日 `D` 成交的是信号日 `D-1` 做出的决策——`engine.py:315` `sig = days[i-1]`，`T` 日选股/卖出判定、`T+1` 开盘成交。每日四步：①评估并执行卖出（`engine.py:319`）②选股+买入（`engine.py:377`）③估值（`engine.py:428`）④记账资金曲线。卖出在买入之前，先释放仓位再填新仓。

**撮合 Broker 与成本模型**。`backend/backtest/broker.py` 是防撮合失真的核心：
- 可成交性按板块/ST 涨跌停判定。`limit_prices`（`broker.py:20`）按 `round(pre_close×(1±pct), 2)` 算涨跌停价；`can_buy_at_open`（`broker.py:27`）要求开盘价严格低于涨停价（开盘即封涨停买不到），`can_sell_at_open`（`broker.py:33`）要求开盘价严格高于跌停价（封死跌停卖不出）。`pct` 取板块值（主板 0.10 / 科创创业 0.20），ST 强制 0.05（`engine.py:64-66`）。
- 停牌（执行日无 bar）不可成交，触发卖出但封死/停牌 → 加入 `pending_sells` 顺延到下一可交易日（`engine.py:354-356`）。
- 整手取整：买入按 100 股整手 floor，现金不足时逐步缩减 `lot_size`（`broker.py:99-109`）。
- 方向性滑点：买入价上浮 `×(1+slippage)`、卖出价下浮 `×(1-slippage)`（`broker.py:95`/`broker.py:134`）。
- 费用：佣金双边（费率/最低值取大）+ 印花税（仅卖）+ 过户费（`broker.py:79-88`）。默认参数见 `backend/config/settings.py:106`（佣金率 0.00025/最低 5 元、印花税 0.001、过户费 0.00001、滑点 0.002）。

**复权一致：后复权记账 + 原始价判可成交性**。`engine.py:60-62` 用 `COALESCE(adj_factor_clean, adj_factor)` 算 `open_hfq`/`close_hfq`，成交/估值/净值/收益率统一在后复权（hfq）基准下进行——hfq 单调、无需 rebase；而涨跌停可成交性用**原始** `open`/`pre_close` 判定（`engine.py:354`/`engine.py:415`），因为涨跌停是按原始价 round 到分的市场规则。

**前向收益（hfq、无未来函数）**。`backend/backtest/forward.py` `compute_forward_returns` 回答「信号后 N 日内最高摸到多少涨幅」：入场价取信号日**下一根可得 bar** 的 hfq 开盘价（`forward.py:94` `shift(-1)`，停牌自然顺延到复牌首日，与撮合一致），窗口 `[T+1..T+N]` 内 hfq high 的反向滚动最大（`forward.py:99`）。比值消去公共复权基准故等于真实复权收益；`adj_factor` 是历史已知值，用未来 N 日价格是「评估」而非「信号生成」，无未来函数。右沿数据不足完整 N 日窗口的信号标 `eval_<N>=False`（按市场日历判定，`forward.py:108-113`），默认从命中率中排除以免低估。

**评分验证的分层超额 / base rate**。`backend/backtest/signal.py` `SignalAnalyzer.analyze`：区间逐日全市场打分→分档（主升浪核心/龙头候选/观察），对每个 `(code, 信号日)` 算前向最大涨幅，`base_rate(N,X)` = 同期**全部已评分票**的无条件命中率（`signal.py:104`），各分档命中率减 base rate 即**超额命中率**（`signal.py:124`），并附样本量 `n` 与 `reliable`（`n≥min_samples`，默认 30，`signal.py:126`）。base rate 必算——牛市里随便选都高命中，唯有超额能反映模型真实能力。base rate 口径含退市股（全市场截面派生），防幸存者偏差。

**防未来机制（贯穿）**。① `T` 日决策、`T+1` 成交（`engine.py:315`）；② 卖出旧式信号 `below_ma` 用后向滚动均线（`engine.py:67-71`）；③ 筛选表达式预计算虽用 `≤date_end` 全序列，但每个调仓日只读该日及之前的布尔值（`precompute.py:8`）；④ 前向收益仅用于事后评估，不回流进信号。

**稳健性测试**。`backend/backtest/robustness.py` 复用 `BacktestService.run_strategy(persist=False)` 不污染历史：`param_sweep` 固定其它参数扫单参数多取值看绩效是否平滑（`robustness.py:33`）；`in_out_sample` 区间一分为二做样本内外切分防过拟合（`robustness.py:42`）；同期基准（默认中证 500）即天然对照组，超额即相对全市场的优势。

**性能优化**。① 筛选表达式批量预计算 `HitPrecomputer`（`backend/backtest/precompute.py`）：把 AST 的 expr 叶子在全历史一次性算成 `(code,date)->bool` 查找表（O(股) 次而非 O(股×日) 次），仅对尺度不变的相对条件成立，含绝对价比较的 expr 不适用（`precompute.py:10`）。② 策略回测与分层分析共享同一 `IndicatorEngine` 实例，区间指标快照只算一遍（`engine.py:40`、`backtest_service.py:155`）。

## 业务架构

回测分两条路径（API `kind` 区分，见 `backend/api/backtest.py:33`）：

**① 策略回测（`kind=strategy`）**——`BacktestEngine.run`。输入：筛选方案（候选池）+ 评分方案（排序）+ 买卖方案（买/卖/兜底）+ 本金/TopN/调仓周期/行业上限/基准。流程产出净值曲线、绩效、逐笔成交（含 `exit_reason` 与部分命中时的 `exit_detail` 命中指标标签）。买卖方案给定时用 `sell_tree`/`buy_tree` 条件树判定（`engine.py:332`/`engine.py:391`），未给定走旧式（评分=固定模型、卖出=跌破 MA + 止盈/止损/到期兜底，`engine.py:336`）。同时附带同区间的分层分析（`backtest_service.py:170`）。

**② 评分验证（`kind=score_check`，旧值 `signal` 兼容）**——`SignalAnalyzer.analyze`。输入：评分方案 + 持有期（horizons）+ 涨幅阈值（thresholds）。输出分层命中率与超额命中率，纯向量化、与卖出规则解耦，不涉及撮合/资金。

两条路径都引用三类方案：筛选方案（`screen_profile`）、评分方案（`score_profile`）、买卖方案（`trade_profile`），运行时解析各自 `version` 并参与去重签名（`backtest_service.py:61`）。

**编排服务** `backend/services/backtest_service.py` `BacktestService`：`run_strategy`/`run_signal` 跑回测算绩效+分层并落库；`prepare` 在运行前算签名（全条件指纹：日期+三方案及版本+所有数值参数，`backtest_service.py:57`）并查同条件已完成历史，供前端弹框选择「加载历史/重跑覆盖」；落库采用覆盖语义——同签名旧记录先 purge 保证每个条件组合历史唯一（`backtest_service.py:101`）。

**涉及表**（`backend/storage/ddl.py:344` 起）：
- `backtest_run`（`:344`）：任务，含 kind/三方案 id 及 version/signature/区间/params(JSON)/status。
- `backtest_trade`（`:367`）：逐笔成交，含 entry/exit 价（hfq 含滑点）、`exit_reason`、`exit_detail`、收益率/盈亏/持有日、买入时分档与排名（grade/entry_score/entry_rank/entry_pick_rank/entry_pool）。
- `backtest_equity`（`:392`）：逐日净值（equity/cash/position_value/n_positions/drawdown/benchmark_equity）。
- `backtest_metrics`（`:407`）：一行一 run 的绩效（total/annual return、max_drawdown、sharpe/calmar/sortino、win_rate、profit_factor 等，`backend/backtest/metrics.py`）+ 分层命中率 JSON（`hit_rate_by_grade`）。

**API**（`backend/api/backtest.py`）：`POST /run`（同步执行并落库）、`POST /prepare`（查重）、`POST /robust`（稳健性，不落历史）、`GET /runs`（按 kind 分别列）、`GET /runs/{id}`（详情）、`DELETE /runs/{id}`。前端 `frontend/src/views/BacktestView.vue` 按 kind 分别加载历史、不混展，跑前先 `prepare` 弹框。

## 页面使用说明书

回测页用于把"看起来合理的方案"放回历史交易规则里验证。它分两类：策略回测验证是否能交易赚钱，评分验证验证评分分档是否有预测力。

### 1. 策略回测

| 参数 | 含义 | 影响 |
|------|------|------|
| 回测区间 | 开始/结束日期 | 越长越慢，但样本更稳定 |
| 筛选方案 | 候选池条件 | 决定每天哪些股票有资格进入买入池 |
| 评分方案 | 候选池排序 | 决定 TopN 排名和分档 |
| 买卖方案 | 买入确认、卖出条件、止盈止损、持仓天数 | 决定实际成交与退出 |
| 初始资金 | 回测本金 | 影响仓位金额，不改变收益率口径 |
| TopN | 每次最多持仓/买入数量 | 影响集中度和换手 |
| 调仓周期 | 每隔几天重新选股 | 影响交易频率 |
| 行业上限 | 同行业最多持仓比例 | 降低行业集中风险 |
| 基准 | 超额收益对照 | 用于绩效比较 |

**策略回测输出怎么看**：

| 输出 | 说明 | 判断重点 |
|------|------|----------|
| 净值曲线 | 组合权益随时间变化 | 是否靠少数阶段拉动、是否长期跑赢基准 |
| 绩效指标 | 收益、年化、最大回撤、夏普、胜率等 | 收益与回撤是否匹配 |
| 逐笔成交 | 买入/卖出日期、价格、收益、卖出原因 | 卖出原因是否符合方案预期 |
| 分层分析 | 同区间评分分档命中率 | 策略收益是否有评分预测力支撑 |

```mermaid
flowchart LR
  A["筛选方案\n候选池"] --> D["策略回测"]
  B["评分方案\n排序/分档"] --> D
  C["买卖方案\n进出场"] --> D
  D --> E["净值/绩效"]
  D --> F["逐笔成交"]
  D --> G["卖出原因复盘"]
```

### 2. 评分验证

评分验证不模拟交易，只回答"高分股票在未来 N 日内更容易达到某个涨幅吗"。

| 参数 | 含义 |
|------|------|
| 评分方案 | 要验证的打分模型 |
| 持有期 horizons | 如 5/10/20 日，看未来窗口内最高涨幅 |
| 涨幅阈值 thresholds | 如 5%/10%/20%，定义命中 |
| 样本区间 | 用于逐日全市场打分和统计 |

**重点看超额命中率**：分档命中率必须减去同期全市场 base rate。牛市里所有股票都容易涨，只有超额为正且样本量足够，才说明评分有增量价值。

### 3. 历史结果与重跑

回测运行前会按日期、三类方案及版本、TopN、成本等参数生成签名：

- 签名已存在：前端提示加载历史或覆盖重跑。
- 覆盖重跑：同签名旧结果先清理，再落新结果。
- 修改任一方案内容后版本号变化，历史结果不会被误认为同一次回测。

### 4. 与其它模块的关联关系

| 上游模块 | 回测如何使用 |
|----------|--------------|
| 数据管理 | 提供行情、交易日历、退市股、复权清洗、涨跌停标记 |
| 配置管理 | 提供评分方案、买卖方案、成本参数 |
| 策略筛选 | 提供候选池方案 |
| 每日榜单 | 与回测共享评分口径，可把榜单思路放回历史验证 |
| 个股与分组 | 可用逐笔成交里的股票回详情页复盘 K线和信号 |

### 5. 回测前检查清单

| 检查项 | 为什么 |
|--------|--------|
| 数据最新且无关键缺口 | 避免指标断档和成交日缺失 |
| 退市股已补 | 避免只用幸存股票高估收益 |
| 复权清洗已重建 | 避免收益率和均线异常 |
| 方案版本确认 | 保证历史结果可复现 |
| 成本参数确认 | 佣金、印花税、滑点会显著影响高换手策略 |

## 业务流程

**跑一次策略回测**：
1. 前端组织参数（区间/筛选+评分+买卖方案 id/TopN/本金/调仓周期/止盈止损/行业上限/基准）→ `POST /prepare` 查同条件历史；命中则提示「加载/覆盖」。
2. `POST /run` → `run_strategy`：解析方案版本、算签名、purge 同签名旧记录、写 `running`。
3. `BacktestEngine.run`：预载行情（向前缓冲 ma_period 个交易日算均线，`engine.py:266`）；构建逐日评分榜 + 买/卖树命中（`_decision_data`，`engine.py:176`）；可选筛选方案命中预计算（`HitPrecomputer`）。
4. 逐日循环：信号日 `D-1` 评估卖出（卖树命中/止盈/止损/到期）→ 执行日 `D` 开盘撮合（涨跌停/停牌检查，不可成交则顺延）→ 选股（信号日截面按评分降序，过候选池+买树+行业上限）→ `D` 开盘买入（整手+滑点+费用）→ `D` 收盘估值记净值。
5. 区间末对仍持仓者按最后可得价强平（`exit_reason=区间末强平/停牌·退市强平`，`engine.py:444`），不悬空。
6. `compute_metrics` 算绩效 + 同区间 `SignalAnalyzer` 算分层 → 落 `backtest_equity`/`backtest_trade`/`backtest_metrics`，写 `done`。

**跑一次评分验证**：
1. `POST /run`（kind=score_check）→ `run_signal`。
2. `SignalAnalyzer.analyze`：区间逐日全市场打分（`_score_range`，方案表达式型指标跨区间向量化补列）→ `compute_forward_returns` 算各 horizon 前向最大涨幅 → 按 `(code, signal_date)` inner join。
3. 算 base rate（全部已评分票）→ 各分档命中率减 base rate 得超额 + 样本量 + reliable 标记。
4. 结果 JSON 落 `backtest_metrics.hit_rate_by_grade`，写 `done`；前端渲染分层命中率表（行=各档+base rate，列=N×X）。

## 风险事项

| 等级 | 风险点 | 影响 | 建议 |
|------|--------|------|------|
| <span style="color:#dc2626">●</span> 高 | 回测 API 仍为同步执行（`backend/api/backtest.py:7`） | 长区间/大 universe 下 HTTP 可能超时，并发回测会受 DuckDB 单写锁影响 | 长区间先缩小样本验证；后续应改异步任务 + 进度轮询 |
| <span style="color:#f59e0b">●</span> 中 | 同一指标 key 在评分项+买卖树中只取首次参数（`engine.py:100`） | 多参数同 key 方案可能静默取错参数 | 同一方案内避免同 key 多参数混用，必要时拆自定义指标 |
| <span style="color:#f59e0b">●</span> 中 | `HitPrecomputer` 不适合绝对价比较 expr（`precompute.py:10`） | 如 `C>50` 这类条件可能得到错误命中 | 表达式预计算前增加运行期校验；当前用约定规避 |
| <span style="color:#f59e0b">●</span> 中 | 开盘可成交性只近似涨跌停，不建模盘中流动性 | 大额或冷门股可能高估可成交规模 | 对冷门股策略降低仓位假设，后续加入成交量约束 |
| <span style="color:#f59e0b">●</span> 中 | 信号质量分档固定为三档（`signal.py:28`） | 自定义评分方案的新分档名不会进入分层统计 | 自定义方案沿用既有分档，或扩展分层配置 |
| <span style="color:#16a34a">●</span> 低 | 前向收益使用窗口内最高价 | 命中率代表"最高摸到"，不等于可实现收益 | 只用于评分预测力比较，不作为收益预期 |
| <span style="color:#16a34a">●</span> 低 | 年化按 242 个交易日、无风险利率默认 0（`metrics.py:14`） | 极短区间年化/夏普统计意义有限 | 短区间重点看逐笔、回撤和样本量 |
| <span style="color:#16a34a">●</span> 低 | 止盈/止损/到期按信号日 close 判定，次日开盘成交（`engine.py:329`） | 触发价与成交价存在一日跳空偏差 | 属真实交易约束，复盘时结合逐笔成交看 |
