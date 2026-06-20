# 开发计划：盘感训练

## 1. 需求来源与目标

- **需求文档**：[requirement.md](agent-works/market-sense-training/requirement.md)
- **功能目标**：新增"盘感训练"模块——盲测、逐日揭示、T+1 真实撮合的手动交易训练；记录思路、产出交易/盈亏/风险统计与评级，并跨局回溯成长。
- **本次不做**：多用户账号体系、分时/Tick 日内训练、做空/T+0、社交排行榜（详见需求 §4.3）。
- **计划输出目录**：`agent-works/market-sense-training/`

## 2. 当前项目依据（已核实）

### 后端
- **入口与路由注册**：[backend/main.py](backend/main.py) —— `from backend.api.xxx import router as xxx_router` + `app.include_router(xxx_router)`（行 21-75）。新模块需在此追加 `training_router`。
- **建表机制**：[backend/storage/ddl.py](backend/storage/ddl.py) —— `init_db(client)` 幂等执行 `CREATE TABLE IF NOT EXISTS`（行 645-658），行 580+ 有"轻量迁移"补列段。新表加入此处即随启动自动建。已有同类表 `backtest_run/backtest_trade`、`*_profile`、`stock_group` 可参考命名风格。
- **行情查询（核心复用）**：[`MarketRepository.get_bars(code, end_date, lookback, adjust="qfq")`](backend/storage/repository.py)（行 108-138），点时安全、前复权基准取截面日 `adj_factor_clean`。
- **随机股票池**：[`MarketRepository.get_universe_asof(asof_date, filters)`](backend/storage/repository.py)（行 182-237），剔除 ST/次新/停牌/一字板/市值区间，支持板块过滤。
- **撮合纯函数（直接复用）**：[backend/backtest/broker.py](backend/backtest/broker.py) —— `limit_prices(pre_close, pct)`（行 20）、`can_buy_at_open(open_px, pre_close, pct)`（行 27）、`can_sell_at_open(...)`（行 33）、`_buy_costs/_sell_costs`（行 79-89，费用口径）。
- **费率配置**：`config.py` 的 `backtest.cost`（佣金 0.03%/最低 5 元、印花税 0.1%、过户费 0.002%、滑点 0.1%）。
- **交易日历**：`trade_calendar(trade_date, is_open)`。
- **统一响应**：[backend/api/response.py](backend/api/response.py)（`{code,msg,data}`）。

### 前端
- **路由**：[frontend/src/router/index.ts](frontend/src/router/index.ts) —— 惰性加载 `component: () => import('@/views/Xxx.vue')` + `meta.title`。
- **导航菜单**：[frontend/src/App.vue](frontend/src/App.vue) 行 47-52 `el-menu-item index="/xxx"`，`activeMenu` 计算属性处理子路由高亮。
- **K 线组件**：[CandleChart.vue](frontend/src/components/CandleChart.vue) —— `props: {bars, markers?, zoomStart?, zoomEnd?}`，`TradeMarker = {date, kind:'buy'|'sell', label}`。
- **资金曲线**：[EquityChart.vue](frontend/src/components/EquityChart.vue)。
- **API 层**：[client.ts](frontend/src/api/client.ts)（axios，拦截器解包 data）。
- **composables**：[useTradeDates.ts](frontend/src/composables/useTradeDates.ts)、[usePageSettings.ts](frontend/src/composables/usePageSettings.ts)、[useTheme.ts](frontend/src/composables/useTheme.ts)。
- **布局规范**：`docs/前端布局自适应规范.md`，`.v-page/.v-grow/.v-scroll`，禁整页滚动。

### 约束
- 后端起停走 `./start.sh`；前端改 `frontend/src` 后必须 `npm run build`；复权一律 qfq 且不写回 `adj_factor`。

## 3. 实施范围

### 3.1 必须实现
训练开局与随机抽样、盲测逐日揭示、资金账户按手 T+1 撮合、思路与复盘记录、一局结算统计与评级、训练历史与成长回溯、训练数据持久化（需求 §4.1）。

### 3.2 可选增强
系统视角对照复盘、暂停/续局、键盘快捷键（需求 §4.2）。这些不阻塞主闭环，作为收尾任务，可裁剪。

### 3.3 暂不实现
见需求 §4.3。

## 4. 技术方案

### 4.1 模块边界
- **后端新增**：`backend/api/training.py`（路由）、`backend/services/training_service.py`（编排与撮合）、`backend/storage/ddl.py` 追加 3 张表。撮合复用 broker 纯函数，**不复用 `Broker` 类**（其 `buy` 以金额为单位、面向多标的策略；训练是单股按手、T+1 揭示驱动，单独实现轻量账户更清晰）。
- **前端新增**：`frontend/src/views/TrainingView.vue`、`frontend/src/api/training.ts`、路由与菜单各一处接入。复用 `CandleChart`/`EquityChart`。

### 4.2 核心数据流（一个回合的生命周期）
1. **开局**：service 在 `[range_start,range_end]` 随机起点 → `get_universe_asof` 抽股 → 校验（≥K 连续交易日、起点前 ≥60 历史、窗口内不退市）→ 落 `training_session` + N×`training_round`（`cursor_date`=起点）。
2. **首屏**：返回起点前 60 + 起点当日的 **qfq K 线**（`get_bars(end_date=cursor_date, lookback=60)`），脱敏（无 code/name/真实日期，横轴用相对日）。
3. **下单**：用户在 `cursor_date`（看到的最后一根）提交 `buy/sell + hands + reason?` → service 仅登记为"待成交意图"（pending），**不立即成交**（T+1）。
4. **揭示下一日**：`reveal` → cursor 前移到下一可交易日 `next_date` → 用 `next_date` 的 qfq `open` 结算上一步 pending 意图：`can_buy_at_open/can_sell_at_open` 判定，封板/停牌则该意图失败或顺延 → 更新账户、落 `training_trade`（含 `decide_date`/`fill_date`/`rel_day`/`price`/`fee`/`pnl`）→ 返回新增 K 线。
5. **回合结束**：cursor 到第 K 个交易日 → 仍有持仓按末日收盘强平（标"到期清算"）→ 计算 `round_return` 与 `benchmark_return`（首日满仓 buy&hold）→ round.status=`done`，推进下一回合。
6. **整局结算**：所有回合 done → 计算综合评分/评级 → session.status=`completed` → 揭晓身份。

### 4.3 点时安全 / 防作弊（硬要求）
- running 态接口**只返回截止 cursor_date 的脱敏 K 线**，绝不下发未来 bar、真实 code/name/日期。
- cursor 推进、成交价、费用、盈亏一律后端计算并落库；前端不参与撮合。
- `reveal` 带乐观校验（请求携带前端已知 cursor，过期则拒绝），防多标签页并发推进。

### 4.4 关键取舍
- T+1 用"意图→次日开盘结算"模型，最贴合需求 §5.3 且天然防未来函数。
- 评分公式权重用需求 §12 默认值，先硬编码于 service，后续可外置配置（不阻塞）。
- multi 模式各回合**独立账户**（需求 §12 默认），整局汇总取各回合合计/平均。

## 5. 任务编排与进度追踪

| 序号 | 状态 | 任务 | 依赖 | 涉及文件/模块 | 产出 | 验证方式 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 已完成 | 需求确认与现状调研 | 无 | requirement.md、本计划 §2 | 需求文档 + 集成点核实 | 4 项核心决策已确认 |
| 2 | 已完成 | 新增 3 张训练表 DDL 与建表接入 | 1 | [ddl.py](backend/storage/ddl.py)、[training_tables.sql](agent-works/market-sense-training/training_tables.sql) | `training_session/round/trade` 表 | 服务重启后 `init_db` 建表成功，API 触发建表生效 |
| 3 | 已完成 | 撮合/费用工具抽取与单股 T+1 结算函数 | 2 | [training_service.py](backend/services/training_service.py)、复用 [broker.py](backend/backtest/broker.py) | `_settle_pending()`/费用/`settle_round` 强平 | API 实测封板/停牌/到期清算正确 |
| 4 | 已完成 | 随机抽样与开局服务 | 2 | training_service.py、repository.py | `create_session()` | 实测样本校验、N 不重复、样本不足报错 |
| 5 | 已完成 | 逐日揭示与脱敏 K 线服务 | 3,4 | training_service.py、`get_bars` | `reveal()`、脱敏序列 | 实测仅截止 cursor、无未来/身份字段 |
| 6 | 已完成 | 下单意图登记服务（T+1 pending） | 3,4 | training_service.py | `place_intent()` | 实测资金/持仓校验、T+1 模型 |
| 7 | 已完成 | 回合结算 + 基准对照 + 整局评分 | 3,5,6 | training_service.py | `settle_round()`/`_settle_session()`/评分 | 实测收益/胜率/回撤/评级/benchmark |
| 8 | 已完成 | 思路与复盘记录服务 | 6,7 | training_service.py | reason 落库、`update_review()` | 每笔理由与整局复盘可存可读 |
| 9 | 已完成 | 训练历史与成长曲线服务 | 7 | training_service.py | `list_sessions()`/`growth()`/`get_detail()`/`delete()` | 服务端分页、级联删除、成长序列 |
| 10 | 已完成 | 训练 API 路由与注册 | 5-9 | [training.py](backend/api/training.py)、[main.py](backend/main.py) | 9 个端点 | 全链路接口实测通过 |
| 11 | 已完成 | 前端 API 封装与类型 | 10 | [training.ts](frontend/src/api/training.ts) | 类型 + 调用函数 | `vue-tsc` 类型检查通过 |
| 12 | 已完成 | 训练页面 TrainingView（开局+训练台+结算） | 11 | [TrainingView.vue](frontend/src/views/TrainingView.vue)、复用 CandleChart/EquityChart | 主页面 | `npm run build` 通过，浏览器实测整页不滚动 |
| 13 | 已完成 | 路由与导航接入 | 12 | [router/index.ts](frontend/src/router/index.ts)、[App.vue](frontend/src/App.vue) | `/training` 路由 + 菜单项 | 浏览器实测菜单进入正常 |
| 14 | 已完成 | 训练历史与成长回溯页/区 | 11,13 | TrainingView.vue、[GrowthChart.vue](frontend/src/components/GrowthChart.vue) | 历史列表 + 成长曲线 + 单局回看 | 浏览器实测列表/回看复现买卖点 |
| 15 | 部分完成 | 可选增强（快捷键已做；系统对照/续局未做） | 12-14 | TrainingView.vue | B/S/→ 快捷键 | 系统评分对照、暂停续局留作后续 |
| 16 | 已完成 | 联调、回归与交付核检 | 2-14 | 全链路 | 验收通过 | 后端 API + 浏览器端到端实测、无 console 报错 |

## 6. 详细实施步骤

### 6.1 任务 2：训练表 DDL
- **目标**：在 `ddl.py` 新增需求 §6.1 的三张表（`training_session`、`training_round`、`training_trade`），随 `init_db` 幂等创建。
- **操作**：参照 `backtest_run/backtest_trade` 段的写法追加 `CREATE TABLE IF NOT EXISTS`；字段、JSON 列、主键按需求 §6.1。`user_id` 留空列备用。SQL 单独落 `agent-works/market-sense-training/training_tables.sql` 备查（见 §7）。
- **影响范围**：仅新增表，不动既有表。
- **边界与异常**：DuckDB JSON/TEXT/DATE 类型与现有表保持一致用法。
- **完成标准**：`./start.sh` 重启后三表存在且可空插入。

### 6.2 任务 3：撮合/费用工具与 T+1 结算
- **目标**：实现单股 T+1 成交结算与费用、强平。
- **操作**：复用 broker 的 `can_buy_at_open/can_sell_at_open/limit_prices`；新增 `resolve_fill(intent, next_bar)`：按 `next_date` qfq `open` 判定能否成交，计算手数→股数、滑点、佣金/印花/过户费、现金变动与（卖出/清算时）pnl 与 return_pct；`force_close(position, last_bar)` 末日收盘强平。费率读 `config.backtest.cost`；零摩擦模式费用置 0。
- **影响范围**：新增 service 内函数，不改 broker。
- **边界与异常**：开盘涨停→买入失败；开盘跌停→卖出失败；停牌（next bar 缺失）→顺延至下一可交易日仍按意图结算；T+1 当日买入不可卖。
- **完成标准**：单元测试覆盖正常/封板/停牌/零摩擦/到期清算。

### 6.3 任务 4：随机抽样与开局
- **目标**：`create_session(params)` 产出 session+rounds。
- **操作**：交易日集合取自 `trade_calendar`；随机起点→`get_universe_asof`→抽股→校验（≥K 连续交易日、起点前 ≥60 历史、窗口内 `delist_date` 不落入）；不满足重抽，设最大重试（如 50 次）超限抛"可用样本不足"；multi 回合间去重。落库 cursor=起点。
- **完成标准**：single 出 1、multi 出 N 不重复；非法参数（K> 可用日、资金过小、N> 池规模）报错。

### 6.4 任务 5：逐日揭示与脱敏
- **目标**：`reveal(session_id, known_cursor)` 与首屏 `get_running_view`。
- **操作**：以 cursor_date 为 end_date 调 `get_bars` 增量返回新 K 线；脱敏（剥离 code/name/真实日期，加 `rel_day`）；推进 cursor 时先结算上一日 pending 意图（调任务 3）。乐观锁校验 `known_cursor`。
- **边界**：到达第 K 个交易日触发回合结算（任务 7）。
- **完成标准**：接口响应中无未来 bar、无身份字段；停牌日正确跳过。

### 6.5 任务 6：下单意图
- **目标**：`place_intent(session_id, side, hands, reason?)`。
- **操作**：校验手数为正整数、买入金额（含预估费用）≤ 可用现金、卖出 ≤ 持仓且非 T+1 锁定；登记 pending（不立即成交）。reason 暂存，成交时写入 trade。
- **完成标准**：各校验失败给明确文案且不改账户。

### 6.6 任务 7：结算与评分
- **目标**：回合与整局结算。
- **操作**：回合末强平→`round_return`、`benchmark_return`（首日满仓 buy&hold）；整局综合评分（需求 §12 默认权重：超额收益 40%+绝对收益 25%+回撤控制 20%+胜率 15%）→评级 S/A/B/C/D；落 `total_return/score/grade`、`completed_at`。资金曲线点供 EquityChart。
- **完成标准**：各指标与评级数值经测试用例核对。

### 6.7 任务 8-9：记录、历史与成长
- reason/review_note 读写；`list_sessions`（服务端分页排序，遵守记忆 `list-interaction-standards`）；`growth` 返回按时间的 score/return/胜率序列；`get_detail`（completed 全量含身份与买卖点）；`delete` 级联三表。

### 6.8 任务 10-14：API 与前端
- **API**：按需求 §6.2 实现 8 端点，统一 `{code,msg,data}`，揭示/下单 30s 超时。`main.py` 注册 `training_router`。
- **前端页面**：`TrainingView.vue` 三态——未开局（参数卡，用 `TradeDatePicker` + `usePageSettings` 记忆）/训练中（CandleChart + 账户面板 + 当前回合成交表，`.v-page/.v-grow` 混合成长区）/结算（统计 + EquityChart + 评级 + 身份揭晓）。空/加载/未成交错误态齐全；主题用 `useTheme`。买卖点经 `markers` 标注（盲测期 label 不含真实日期）。
- **路由/菜单**：`/training` 路由 + `App.vue` 菜单项（如 `🎮 盘感训练`），`activeMenu` 兼容。
- **历史/成长**：列表 + 成长曲线 + 单局回看（回看时身份已揭晓，可跳 StockDetailView）。

## 7. 数据库与 SQL 计划

- **SQL 文件路径**：`agent-works/market-sense-training/training_tables.sql`（与 `ddl.py` 内嵌建表语句保持一致，供审阅/手动执行备用）。
- **用途**：创建 `training_session`、`training_round`、`training_trade` 三张表。
- **执行时机**：实际建表由后端启动时 `init_db()` 幂等执行（`CREATE TABLE IF NOT EXISTS`）；SQL 文件仅作归档与人工核验。
- **影响范围**：仅新增表，不改既有表、不迁移历史数据。
- **回滚方式**：`DROP TABLE IF EXISTS training_trade; training_round; training_session;`（无外部依赖，可安全回滚；训练数据为可重建的用户产出）。

## 8. 测试与验证计划

- **单元测试**（`backend/tests/`）：撮合结算（封板/停牌/零摩擦/T+1 锁定/到期清算）、随机抽样校验、评分与基准计算、脱敏（无未来/身份字段）。
- **接口测试**：开局→reveal→下单→reveal 结算→回合切换→整局结算→历史/成长→删除 全链路；防作弊（running 态构造请求拉未来/身份应被拒）；乐观锁并发推进。
- **页面/交互测试**：用 `preview_*` 起前端，验证 `/training` 整页不滚动、K 线不被压扁、表体内滚；开局→训练→结算三态流转；买卖点标记、账户实时更新、未成交提示、评级与身份揭晓；历史回看复现思路。
- **回归测试**：确认未影响回测/筛选/个股等既有页（共享 `get_bars`、broker 函数未改签名）。
- **异常与边界测试**：样本不足、资金不足、持仓不足、停牌密集、窗口内退市、零摩擦模式。
- **构建验证**：前端 `npm run build` 通过；后端 `./start.sh` 重启后接口可用。

## 9. 发布与回滚

- **发布前检查**：单元/接口/页面测试通过；`npm run build` 成功；`ddl.py` 建表幂等确认。
- **发布步骤**：合并后 `./start.sh` 重启后端（自动建表），前端构建产物随静态资源发布。
- **配置或环境变量**：无新增；复用 `config.backtest.cost` 费率。
- **回滚方案**：前端移除路由/菜单/页面即下线入口；后端移除 `training_router` 注册；训练表可保留（不影响其他模块）或按 §7 DROP。无数据迁移，回滚低风险。

## 10. 风险、假设与待确认项

### 10.1 风险
- **前复权基准滚动一致性**：揭示期以 cursor 为基准、回看期以末日为基准，K 线绝对价位会不同（形态一致）。需在回看时统一以"回合末日"为基准重算，避免与训练时观感矛盾——已在任务 5/14 注意。
- **盲测泄露**：脱敏不彻底（如残留 tooltip 中的真实日期/code）会破坏训练价值。任务 5 接口层与任务 12 前端层双重把关，测试用例专项覆盖。
- **撮合口径偏差**：训练撮合若与回测 broker 出现费率/滑点不一致，会影响"人 vs 系统"对照可信度。统一读 `config.backtest.cost`。

### 10.2 假设
- 系统为单机单用户，训练记录归当前用户，`user_id` 留空（需求 §3）。
- 数据库为 DuckDB，行情数据已具备（依赖数据管理模块产出）。
- multi 模式各回合独立账户（需求 §12 默认）。

### 10.3 待确认项（不阻塞，可在开发中按默认推进）
1. 评分权重与评级阈值——用需求 §12 默认，后续可外置配置。
2. 基准口径（首日满仓 vs 等额定投）——默认首日满仓。
3. 起点前历史窗口根数——默认 60 交易日。
4. 键盘快捷键/续局是否纳入首版——列为可选任务 15。
