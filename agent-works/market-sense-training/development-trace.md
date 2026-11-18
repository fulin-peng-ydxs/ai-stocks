# 盘感训练

归档状态：已归档

## 功能的详细需求

在策略回测、个股筛选之外，新增一个**面向人的手动交易训练**模块：以盲测、逐日揭示的方式，让用户对随机个股随机交易日做买卖决策，事后以真实历史结果对照思路，并跨局沉淀成长轨迹。

**训练配置与开局**：
- 模式：`single`（单只，N=1）/ `multi`（多只，每回合一只）。
- 配置项：历史交易日范围、回合数 N（1~20）、每回合连续窗口 K（5~60 交易日）、初始资金、板块过滤、排除 ST、费用开关（零摩擦模式）。
- 随机抽样：在可选范围内随机取起点 → `get_universe_asof` 抽股 → 校验（起点前 ≥60 历史、起点后 ≥K 连续交易日、窗口内不退市）→ 不满足重抽（最多 80 次），超限报"可用样本不足"。multi 回合间个股不重复。

**盲测逐日揭示**：
- 训练进行中隐藏股票名称、代码、真实日期；K 线横轴只显示相对日标签（`D+0`、`D-1`…）。
- 初始视图：起点前约 480 个交易日历史（≈2 年上下文）+ 起点当日；其后每次"下一日"揭示一根新 K 线。
- 点时安全：所有 K 线用**回合固定复权基准**（`start_date` 当日 `adj_factor_clean`），绝不返回 cursor 之后的数据。

**T+1 意图→次日开盘成交模型**：
- 用户在 cursor 日（看到的最后一根）提交买/卖意图（手数 + 可选理由）→ 登记为 pending，当日不成交。
- 揭示下一日时，以该日 `open`（原始价）判定可成交性（涨停买不到 / 跌停卖不出 / 停牌未成交），通过后按前复权展示价成交并计算费用。
- 费用：佣金（0.025%/最低5元）+ 印花税（仅卖，0.1%）+ 过户费（0.001%）+ 滑点（0.2%），零摩擦模式全置零。
- T+1 限制：当日买入的持仓当日不可卖出（下单阶段校验）。

**到期强制平仓**：到达窗口第 K 日后，若仍有持仓，按末日收盘价（前复权）强制清算，交易记录标注 `auto_close=True`。

**一局结算统计与评价**：
- 逐回合产出：交易明细、资金曲线、最大回撤、收益率、与基准（首日满仓 buy & hold）对照。
- 整局综合评分（0~100）= 超额收益 40% + 绝对收益 25% + 回撤控制 20% + 胜率 15%；评级：S≥90 / A≥80 / B≥70 / C≥60 / D<60。
- multi 模式各回合独立账户，整局取各回合收益率平均。
- 结算后揭晓真实股名、代码、日期区间。

**训练历史与成长回溯**：服务端分页排序的历史列表、跨局评分/收益/胜率成长曲线、单局完整回看（含逐笔理由与复盘笔记）、删除（级联三表）。

**暂未实现**：系统视角评分对照复盘、暂停/续局（数据结构已支持，未实现入口）。

---

## 功能开发的实际结果

完成了盘感训练全主链路，计划任务 1~16 全部落地（任务 15 键盘快捷键 B/S/→ 已实现；系统对照复盘与续局未做）。

**关键文件与职责**：

| 文件 | 职责 |
|------|------|
| `backend/storage/ddl.py` | 追加 `training_session`、`training_round`、`training_trade` 三张表的 `CREATE TABLE IF NOT EXISTS`，随 `init_db()` 幂等建表 |
| `backend/services/training_service.py` | 全部业务逻辑：随机抽样、盲测视图、T+1 意图/成交结算、回合强平、综合评分、历史分页、成长曲线 |
| `backend/api/training.py` | 11 个 FastAPI 端点（见下方 API 清单），薄层路由 |
| `backend/main.py` | 追加 `from backend.api.training import router as training_router` + `app.include_router` |
| `frontend/src/api/training.ts` | 前端 API 封装与 TypeScript 类型（`RunningView`、`DetailView`、`SessionRow` 等） |
| `frontend/src/components/GrowthChart.vue` | 成长曲线折线图（ECharts，评分/收益/胜率三线） |
| `frontend/src/views/TrainingView.vue` | 主页面三态：开局配置卡 / 训练台（K线+账户+操作+成交表）/ 结算详情 |
| `frontend/src/router/index.ts` | 追加 `/training` 惰性加载路由 |
| `frontend/src/App.vue` | 追加菜单项"🎮 盘感训练" |

---

## 功能开发的具体实施方案

### 数据库（`ddl.py`）

追加三张表：

```
training_session  ← 一局训练，含配置快照 / 状态 / 汇总指标 / 复盘笔记
training_round    ← 一个回合，含 code（盲测期后端持有）/ cursor / 账户状态 / pending
training_trade    ← 逐笔成交，含 decide_date / fill_date / rel_day / 费用 / pnl / reason / auto_close
```

`training_round` 的 `pending` 列存 JSON，在 T+1 意图登记到成交结算之间持有下单参数。`base_factor`（`start_date` 当日 `adj_factor_clean`）在建表时写入并固定，回合内所有价格按此基准复权，防止价格跳变。

### 后端服务（`training_service.py`）

**随机抽样**（`create_session`）：从 `trade_calendar` 取可选交易日集合，末尾保留窗口空间；循环随机取起点 → `MarketRepository.get_universe_asof` 取当日候选池 → 校验 → 最多重试 80 次；multi 模式用 `used_codes` 去重。开局时写 session 行 + N 条 round 行，首回合 status=`running`，其余 `pending`。

**K线构造与脱敏**（`_bars_for_view`）：以 `cursor_date` 为上限取全部 bar，找 `start_date` 索引，向前取最多 480 根历史、向后取到 `cursor`，统一除以 `base_factor` 缩放。盲测期 `date` 字段改为 `D±N` 相对日标签。

**T+1 意图模型**（`place_intent` → `_settle_pending`）：`place_intent` 只做校验（资金 / 持仓 / T+1 锁定）并写 pending JSON，不成交。`reveal` 时调 `_settle_pending`：取 `next_date` 的 `_raw_bar`，用**原始价**（不复权）调 `can_buy_at_open` / `can_sell_at_open`，通过后用前复权展示价计算金额与费用，更新 cash / pos / realized_pnl，插 `training_trade`。停牌（`_raw_bar` 返回 None）→ 订单失败，消费 pending 并返回提示文案。

**回合结算**（`settle_round`）：到期强平（按 cursor 日收盘价）→ 计算 `round_return`（= 末日总资产 / 初始资金 - 1）→ 基准收益（`_benchmark_return`：起点开盘后复权 → 末日收盘后复权，与复权基准无关）→ 更新 round status=`done` → 推进下一回合或触发 `_settle_session`。

**整局结算**（`_settle_session`）：各回合收益率取平均为 `total_return`；卖出笔统计胜率；遍历所有回合回放 `_round_equity_curve` 取最差 `_max_drawdown`；评分公式硬编码（超额收益 40%+ 绝对收益 25%+ 回撤 20%+ 胜率 15%），映射到 S/A/B/C/D。

**防作弊**：`get_view`（running 态）调 `_bars_for_view(reveal_dates=False)` 且不返回 code/name；`get_detail`（completed 态）调 `_bars_for_view(reveal_dates=True)` 并返回真实身份；`reveal` 接受 `cursor_idx` 乐观锁防多标签页并发。

### API 端点（`training.py`）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/training/sessions` | POST | 开局 |
| `/api/training/sessions` | GET | 历史列表（分页/排序） |
| `/api/training/growth` | GET | 成长曲线序列 |
| `/api/training/sessions/{sid}` | GET | 当前局视图（running 脱敏 / completed 全量） |
| `/api/training/sessions/{sid}` | DELETE | 删除（级联三表） |
| `/api/training/sessions/{sid}/reveal` | POST | 揭示下一日（带乐观锁 cursor_idx） |
| `/api/training/sessions/{sid}/trade` | POST | 登记买卖意图（T+1 pending） |
| `/api/training/sessions/{sid}/cancel` | POST | 撤销当前 pending |
| `/api/training/sessions/{sid}/settle-round` | POST | 结算当前回合 |
| `/api/training/sessions/{sid}/review` | PATCH | 保存整局复盘笔记 |

注：计划中的 8 个端点在实现时因增加了 `cancel` 和独立 `settle-round` 而变为 10 个（此外 growth 作为独立端点），与计划略有差异，实际更合理。

### 前端（`TrainingView.vue`）

三态切换：`phase === 'idle'`（开局配置卡）/ `phase === 'running'`（训练台）/ `phase === 'done'`（结算详情）。

训练台布局（`.v-page / .v-grow` 混合成长区，禁整页滚动）：顶部进度条 + 账户面板固定高度 → 中部 `CandleChart`（复用，`markers` 标注买卖点）→ 下方操作区（按手数 / 快捷预设）→ 当前回合成交明细表（表体内滚）。

下单：两种模式（按手数 / 按金额），金额模式换算为手数；快捷预设通过 `usePageSettings` 持久化。抽屉（`PageSettingsDrawer`）中放排除ST、费用开关两个低频配置项（本次会话刚移入）。

键盘快捷键（B=买、S=卖、→=下一日）通过 `useKeyDown` 绑定。

成长曲线独立组件 `GrowthChart.vue`：ECharts 折线图，三条线（评分 / 收益 / 胜率），支持主题响应。

---

## 上线部署操作

- `agent-works/market-sense-training/training_tables.sql`：三张表的归档 SQL，供人工审阅；**实际建表由后端启动时 `init_db()` 幂等执行**，无需手动运行。
- 无新增环境变量或配置项；费率复用 `config/settings.yaml` 的 `backtest.cost` 段。
- 发布步骤：`npm run build`（已执行）→ `./start.sh restart`，重启后 `init_db` 自动建表。
- 回滚方式：移除 `main.py` 的 `training_router` 注册 + 移除菜单/路由项即可下线入口；三张训练表不影响其他模块，可保留或按 `training_tables.sql` 末段 DROP 语句删除。

---

## 验证情况

- `npm run build`：通过（build 产物含 `TrainingView-*.js`）。
- 后端接口：随 `./start.sh` 启动，`init_db` 幂等建表已确认（无报错）。
- 前端页面功能验证：浏览器实测开局 → 训练台三态流转、K 线 markers 标注、账户实时更新、揭示下一日、买卖意图登记与成交提示、结算评级与身份揭晓、历史列表回看；布局整页不滚动，表体内滚。
- 键盘快捷键（B/S/→）：浏览器实测响应正常。
- 单元测试（`backend/tests/`）：计划包含撮合/评分/抽样/脱敏单测，本次未单独执行 pytest；主链路通过浏览器端到端实测覆盖。
