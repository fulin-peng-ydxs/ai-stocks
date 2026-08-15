# 盘感训练

> 面向人的手动交易训练模块：盲测随机个股、逐日揭示 K 线、真实撮合买卖（买 T+0 收盘价 / 卖 T+1 开盘价），事后以历史结果对照思路，并跨局沉淀评分 / 收益 / 胜率成长曲线。它训练的是"人"而非"策略"——验证盘感正确性、回溯决策思路、量化成长轨迹。

<span style="color:#2563eb">●</span> 盲测防作弊　<span style="color:#7c3aed">●</span> 买 T+0 / 卖 T+1 撮合　<span style="color:#16a34a">●</span> 评分与成长　<span style="color:#dc2626">●</span> 点时安全

---

## 核心技术

**回合固定复权基准（关键设计）**。训练撮合与回测不同：回测用 hfq（后复权单调无需 rebase），训练需要在进行中实时展示价格且 K 线不能跳变。解决方案：每回合在开局时取 `start_date` 当日 `adj_factor_clean` 固定为 `base_factor`（`training_service.py`），回合内所有 OHLC 均按 `raw_price × (factor / base_factor)` 缩放——即以 start_date 为基准的前复权。好处：① 价格绝对值在回合内稳定，无跳变；② 用原始价判涨跌停，不受复权干扰；③ 回合结束后回看与训练时所见价位一致。

**买 T+0 / 卖 T+1 撮合模型（贴近真实 + 防未来）**。区分买卖时点，匹配 A 股交易制度（当日可买、当日买入次日才可卖）：

- **买入 T+0（`_execute_buy_now`）**：用户在 cursor 日（含当日收盘）尾盘决策买入，**当日即按收盘价即时成交**。用**原始收盘价**调 `broker.can_buy_at_open` 判收盘是否封涨停（封板买不到），通过后按前复权展示价计费、更新 cash/pos，插 `training_trade`（决策日=成交日=cursor_date）。成交价是已发生的当日收盘价，非未来函数。
- **卖出 T+1（`place_intent` → `_settle_pending`）**：当日提交卖出意图（手数+理由），序列化为 JSON 存入 `training_round.pending`，**不立即成交**。揭示下一日（`reveal`）时调 `_settle_pending`：取 next_date 原始行情，用**原始价**调 `broker.can_sell_at_open` 判可成交（开盘跌停卖不出 / 停牌顺延），通过后按前复权展示价计费、插 `training_trade`。成交价取"揭示那一刻"才知道的次日开盘价，无法预知；当日买入的仓位最早次日开盘卖出，天然满足 T+1。

`_settle_pending` 仍保留 buy 分支，仅兼容历史遗留的 buy pending（按次日开盘价结算），新会话买入不再走此路径（`training_service.py`）。

**盲测脱敏（双层保护）**。① 服务层：`_bars_for_view(reveal_dates=False)`（`training_service.py:118`）将 `date` 字段替换为相对日标签 `D±N`，response 中不含 `code`/`name`/真实日期；`get_view`（running 态）固定走脱敏路径，仅 `get_detail`（completed 态）才展示真实身份。② API 层：`reveal` 接受 `cursor_idx` 乐观校验——前端已知的游标与服务端不符则拒绝，防多标签页并发推进导致状态错乱（`training_service.py:400`）。盲测阶段仍返回回合所属**板块（主板/创业板/科创板）**：其为宽泛分类且与选股过滤同口径，不指向具体个股，供训练台标注用。

**点时安全 K 线**。`_bars_for_view` 查询条件严格为 `trade_date <= cursor_date`（`training_service.py:128`），从不返回 cursor 之后的 bar；`adj_factor_clean` 用 `COALESCE(adj_factor_clean, adj_factor)` 兜底，与全系统口径一致（`qfq-factor-rootfix` 规范）。

**训练 MACD 脱敏附带**。`_bars_for_view` 末尾对返回 bars 的脱敏前复权 close 直接计算 `compute_macd`（12/26/9，严格后向），每根 bar 附 `macd_diff/macd_dea/macd_hist`（保留 3 位小数，暖机不足为 null）与 `macd_golden_cross/macd_dead_cross`（金叉/死叉信号，个股详情 MACD 面板同款）。不在前端走 `/api/stocks/{code}/indicators`（会按真实 code 查询，泄盲测身份）；数值与真实 qfq 有基准差异但方向/形态一致，训练中与结算回看共用。

**综合评分公式**（`_settle_session`，`training_service.py:610`）：
```
score = 超额收益得分×0.40 + 绝对收益得分×0.25 + 回撤控制得分×0.20 + 胜率得分×0.15
```
各维度线性映射到 0~100：超额 = `clamp01((ret - bench + 0.10) / 0.20)`，绝对 = `clamp01((ret + 0.20) / 0.40)`，回撤 = `clamp01((mdd + 0.25) / 0.25)`，胜率 = `win_rate`。评级阈值 S≥90 / A≥80 / B≥70 / C≥60 / D<60。multi 模式各回合独立账户，整局收益取各回合平均。

**资金曲线回放**（`_round_equity_curve`，`training_service.py:556`）：按成交记录逐日模拟 cash 与 pos 变化，用前复权收盘价估值；最大回撤 `_max_drawdown`（`training_service.py:581`）按峰值跌幅算，供结算统计与评分使用。

**随机抽样校验**（`create_session`）：最大重试 80 次（`MAX_PICK_RETRY`），每次随机起点 → `MarketRepository.get_universe_asof` 取当日候选池 → 校验：起点前 ≥60 历史交易日（`MIN_HISTORY`）、起点后有 ≥window_days 连续交易日数据、窗口内不退市；multi 模式用 `used_codes` 集合去重。

训练默认硬性股票池来自 `get_effective_settings().universe`，前端只显式暴露“排除 ST”和“板块”两个筛选项：

| 规则 | 默认值 / 口径 |
|------|---------------|
| 板块 | 主板、创业板、科创板；不含北交所 |
| ST | 默认排除 ST；前端可关闭 |
| 上市天数 | 默认至少 60 个交易日 |
| 当日可用行情 | 起点日必须有 `daily_bar`，停牌或无行情不会入池 |
| 一字涨停 | 默认排除开盘一字涨停股（`is_one_word=true` 且 `limit_status=1`） |
| 流通市值 | 默认 `5e9 <= float_mv <= 4e10` |
| 数据窗口 | 起点前历史 ≥60 日，起点后可揭示窗口 ≥配置的 `window_days` |

---

## 业务架构

一局训练的生命周期由三张表和四个关键服务方法驱动：

```
create_session()
  → training_session (running, cur_round=0)
  → N × training_round (first: running, rest: pending)
  → get_view()  ← 返回首回合盲测视图

──── 回合内循环 ────
place_intent(buy)                       place_intent(sell)
  → _execute_buy_now()                    → training_round.pending = {sell, hands, reason}
    ← 当日收盘价即时成交（T+0）            → 校验持仓
    → training_trade (INSERT)
    → training_round (UPDATE cash/pos)

reveal()
  → _settle_pending()  ← next_date 开盘价结算 pending 卖出（T+1）/失败
    → training_trade (INSERT)
    → training_round (UPDATE cash/pos)
  → cursor_date 前移, cursor_idx+1
  → 返回新 K 线 + fill_msg

settle_round()  ← 到达末日后触发
  → 强制平仓 (auto_close=True)
  → 计算 round_return + benchmark_return
  → 推进 cur_round 或触发 _settle_session()
──────────────────

_settle_session()
  → 汇总各回合 → 评分/评级 → completed
  → get_detail()  ← 揭晓真实身份，返回完整详情
```

**训练阶段与 API 对应**：

| 阶段 | 前端操作 | 调用端点 |
|------|----------|----------|
| 开局 | 填配置、点「开始训练」 | `POST /sessions` |
| 盲测中 | 看 K 线决策后点「买」/「卖」 | `POST /sessions/{id}/trade` |
| — | 撤单 | `POST /sessions/{id}/cancel` |
| — | 点「下一日」 | `POST /sessions/{id}/reveal` |
| — | 到末日点「结算回合」 | `POST /sessions/{id}/settle-round` |
| 结算后 | 填复盘笔记 | `PATCH /sessions/{id}/review` |
| 历史 | 翻看历史列表 | `GET /sessions` |
| — | 看成长曲线 | `GET /growth` |
| — | 打开某局详情 | `GET /sessions/{id}` |
| — | 删除某局 | `DELETE /sessions/{id}` |

**涉及表**（`backend/storage/ddl.py`）：
- `training_session`：一局训练，含配置快照（mode/n_rounds/window_days/initial_capital/filters/fee_enabled）、运行状态（status/cur_round）、汇总指标（total_return/score/grade/win_rate/max_drawdown/n_trades）、复盘笔记（review_note）。
- `training_round`：一个回合，含真实股票信息（code/start_date/end_date，running 态对前端不可见）、`base_factor`（复权基准）、`price_limit_pct`（涨跌停板块倍率）、实时账户状态（cash/pos_shares/pos_cost/pos_avg_price/realized_pnl）、pending JSON（T+1 意图）、游标（cursor_date/cursor_idx）。
- `training_trade`：逐笔成交，含 decide_date（决策日）/ fill_date（成交日）/ rel_day（相对日，盲测展示用）/ 前复权展示价 / 手数 / 费用 / pnl / return_pct / reason / auto_close。

**前端视图类型**（`frontend/src/api/training.ts`）：
- `RunningView`：running 态视图，`round` 字段中含脱敏 bars（相对日标签）+ markers + 账户状态 + 板块（宽泛分类），无 code/name/真实日期。
- `DetailView`：completed 态视图，`rounds` 数组含真实身份 + 真实日期 + equity_curve，交易记录含 decide_date/fill_date。

---

## 页面使用说明书

### 开局配置

填写训练参数后点「开始训练」。常用配置（模式/窗口/资金/板块/日期范围）在主配置卡；低频配置（排除 ST / 计入交易成本）在右上角设置抽屉。参数通过 `usePageSettings` 持久化，下次打开自动还原。

### 训练台操作

开局后进入盲测训练台：

- **K 线区**：个股详情同款多图联动工作区（`StockChartWorkspace.vue`）——K 线 + 均线 + 可配置的量能/MACD 辅助图，横轴为相对日（D±N），买卖点以 ▲/▼ 标注（买=蓝▲在最低价下方、卖=橙▼在最高价上方）。图表类型、显隐与高度占比在设置抽屉配置，K 线范围用顶部范围选择器。**MACD 由后端在训练 bars 内附带**（复用 `compute_macd` 12/26/9，由脱敏前复权 close 计算，不引用真实代码，防作弊契约不变；训练中与结算回看共用），金叉/死叉以 MACD 面板标签标注。DataZoom 可拖动查看历史上下文。**图表区域高度**与个股详情一致，在设置抽屉「组件设置」调节。
- **账户面板**：实时显示可用现金、持仓手数 / 成本 / 浮盈亏、总资产、当前进度（第 X 日 / 共 Y 日）。
- **下单**：选手数（或按金额自动换算）→ 点「买」或「卖」；支持快捷手数/金额预设（在设置抽屉配置）。**买入当日按收盘价即时成交（T+0）**，立即反映到账户与成交明细；**卖出登记为 pending（T+1）**，次日开盘成交，点「撤单」可撤回尚未成交的卖出意图。
- **推进**：点「下一日」（或按 `→`）揭示次日 K 线并结算 pending 卖出；成交失败（开盘跌停/停牌）会弹提示，账户不变。键盘快捷键：`B` = 买、`S` = 卖、`→` = 下一日。
- **结算**：到达窗口末日后点「结算回合」，强制清算持仓；multi 模式自动切入下一回合。

### 结算详情

所有回合结束后：
- 揭晓每回合真实股票名称、代码、**所属板块（主板/创业板/科创板，与选股过滤同口径）**、日期区间，可点股票名跳转个股详情页。
- 查看逐回合 K 线（含 MACD 与完整买卖点）、成交明细（含每笔理由与 decide/fill 日期）、资金曲线与回撤。回合卡在整页流内完整展开（不被视口压缩），逐回合成交明细表超出 240px 上限后表内滚动，避免撑爆整页。
- 整局复盘与训练台/训练首页一样由页面 main 区整区滚动承接（`body` 槽 `scroll: 'region'`）：长内容自然撑高、内容不被压缩到窄滚动条，小视口下也可完整滚动浏览。
- 整局评分（0~100）、评级（S~D）、总收益、胜率、最大回撤、交易次数。
- **评分规则说明卡**：综合评分 = 超额收益×40% + 绝对收益×25% + 回撤控制×20% + 胜率×15%，四维度口径与评级阈值（S≥90/A≥80/B≥70/C≥60/D<60）逐字对齐后端公式。
- 复盘笔记输入框，内容落库后历史回看时可继续编辑。

### 训练历史

配置卡下方展示历次训练记录（服务端分页，默认按时间倒序），点击任意行进入历史回看（此时身份已揭晓，页面同结算详情）。删除按钮级联清除该局所有回合与成交记录。分页走全站 AppPagination 规范（默认 20 条/页，可选 20/50/100/200，与所有列表页一致），每页条数可在设置抽屉「组件设置」调节（`history.pageSize`，与列头排序同源）。config 阶段历史表吃满剩余高度、表内滚动；小视口内容超限时整区滚动兜底。

成长曲线区（有历史数据后展示）：折线图跨局展示评分 / 总收益 / 胜率趋势，横轴按完成时间排列。

---

## 与其他模块的关系

| 依赖项 | 用途 | 是否修改 |
|--------|------|----------|
| `MarketRepository.get_universe_asof` | 随机抽样候选池（防幸存者偏差） | 未修改 |
| `broker.can_buy_at_open` / `can_sell_at_open` | 涨跌停可成交性判定（买入复用判收盘封涨停，卖出判次日开盘跌停） | 未修改 |
| `config.backtest.cost` | 佣金/印花/过户费/滑点费率 | 未修改 |
| `StockChartWorkspace.vue` | 训练 K 线工作区（多图联动，新增可选 `markers` 买卖点标注） | 新增 markers 支持 |
| `EquityChart.vue` | 资金曲线（结算详情） | 未修改 |
| `daily_bar` / `trade_calendar` / `stock_basic` | 行情/日历/股票基础信息 | 未修改（只读） |

训练模块**不修改**回测相关表与服务，与筛选 / 榜单 / 配置管理完全解耦，可独立上下线。
