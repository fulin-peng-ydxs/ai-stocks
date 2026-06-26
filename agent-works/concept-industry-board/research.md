# 概念 / 行业板块数据可行性调研

> 调研时间：2026-06-25　调研性质：只读评估，未改任何代码 / 未建任何表
> 结论一句话：**东财被封的真实性质是「出口 IP 频率限流 / 连接 reset」，不是接口失效——curl 同机同 IP 单发能 200。一旦解除（换出口 / 代理 / 严格限速），东财可一站式提供「概念 + 行业 + 历史指数行情 + 成分股 + 资金流」全套，完全覆盖必要数据。**

---

## 1. 现状（代码事实）

| 维度 | 状态 | 依据 |
|------|------|------|
| `stock_basic.industry` 字段 | ✅ 已定义、已采集 | [ddl.py:34](../../backend/storage/ddl.py:34)；baostock `get_industry()`（证监会行业，[baostock_source.py:142](../../backend/datasource/baostock_source.py:142)）；写入点 [ingest.py:1605](../../backend/services/ingest.py:1605) |
| `stock_basic.concept` 字段 | 🟡 仅占位，始终 NULL | [ddl.py:35](../../backend/storage/ddl.py:35) 定义为「JSON 字符串可多值」，全代码无写入 |
| 板块字典 / 成分股关系 / 板块行情表 | 🔴 不存在 | DDL 无任何板块相关表 |
| 交易所 `board`（主板/创业板/科创板） | ✅ 有但与本议题无关 | [akshare_source.py:106](../../backend/datasource/akshare_source.py:106)，仅用于涨跌停判定 |

---

## 2. 数据源接口实测矩阵（2026-06-25 本机网络）

### 🟡 东财系（`*_em`）—— 被「出口 IP 限流」，非接口失效（已定性，见 §3）

| 接口 | 单发实测 | 备注 |
|------|------|------|
| `stock_board_concept_name_em` / `industry_name_em` | 触发限流时 ConnectionError | curl 单发可 200 |
| `stock_board_concept_cons_em`（成分股） | 同上 | 仅东财有可用成分股接口 |

### ✅ 同花顺系（`*_ths`）—— 稳定可用，但**无成分股接口**

| 接口 | 结果 | 字段 |
|------|------|------|
| `stock_board_concept_name_ths`（概念列表） | OK 373 行 | `name, code` |
| `stock_board_industry_name_ths`（行业列表） | OK 90 行 | `name, code` |
| `stock_board_concept_summary_ths`（概念资金概要） | OK 50 行 | `日期,概念名称,驱动事件,龙头股,成分股数量` |
| `stock_board_concept_index_ths` / `industry_index_ths`（指数历史） | OK | `日期,开/高/低/收,成交量,成交额` |
| 成分股 | ❌ 该版本无 `cons_ths`，cons 仅东财版 | — |

### ✅ 新浪系 —— 可用，含成分股，但板块体系弱（~49）

`stock_sector_spot` + `stock_sector_detail`：唯一在限流下也能拿到「板块→成分股」的备选，但粒度粗、口径与同花顺/东财不一致。

### ✅ baostock 行业 —— 已接入

`get_industry()`：证监会行业单一标签，无成分股反查、无板块行情。

---

## 3. 东财封禁性质诊断（关键结论）

**判定：不是 IP 黑名单、不是接口失效、与 User-Agent 无关，而是「出口 IP 的频率触发型限流 / 连接 reset」。**

证据链：

1. **同机同 IP，curl 最初单发可拿到东财数据 200**：`www.eastmoney.com`、`quote.eastmoney.com`、`push2.eastmoney.com/api/qt/clist/get` 均成功 → 排除 DNS 问题、接口下线、IP 整段黑名单。
2. **UA 无关**：curl 默认 UA、伪装 `python-requests` UA、python 带浏览器 UA，行为一致。
3. **频率触发**：连续打 8 次后 curl + python **全部变 000（Empty reply / RemoteDisconnected）**。本次调研前面跑了十余次探针，正好把该出口 IP 打进限流冷却窗口 → 失败是「累积请求触发限流后服务端/链路 reset」，不是稳定不可达。
4. 失败症状是 `RemoteDisconnected` / `Empty reply`（连上后被掐断），与「IP 被防火墙丢包」的超时/`Connection refused` 不同，进一步指向应用层/链路的主动 reset。

> **推论**：换出口 IP（手机热点 / 另一条宽带 / 代理）+ 严格限速，东财大概率恢复稳定。**待用户换网络打开下方 URL 验证**：
> `https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3&fields=f12,f14,f2,f3`
> 看到 `{"rc":0,...,"diff":[...]}` JSON = 确认 IP 限流，方案 §4 成立。

---

## 4. 假设东财可用：能拿到哪些数据（akshare 1.18.64 离线源码核对）

### ⭐ 必要数据 —— 四件套全覆盖

| 能力 | 接口 | 关键字段 / 说明 |
|------|------|----------------|
| **概念板块字典** | `stock_board_concept_name_em` | 板块代码(BKxxxx)、板块名称、最新价、涨跌幅、总市值、上涨/下跌家数、领涨股 |
| **行业板块字典** | `stock_board_industry_name_em` | 同上结构 |
| **概念成分股** | `stock_board_concept_cons_em(symbol)` | 个股代码、名称、价格、涨跌幅、市值、换手等 → 板块↔个股映射 |
| **行业成分股** | `stock_board_industry_cons_em(symbol)` | 同上 |
| **概念指数历史** | `stock_board_concept_hist_em(symbol, period, start, end, adjust)` | 日/周/月 K，**支持 adjust 复权参数**（与项目「复权一致」契约契合） |
| **行业指数历史** | `stock_board_industry_hist_em(...)` | 同上 |

> 口径说明：东财概念板块代码为 `BKxxxx`，与同花顺 `88xxxx` 体系不同。东财概念同样达 300+、贴近市场题材，且**唯一同时具备「成分股 + 复权历史」**。因此推荐**主用东财**，而非同花顺（同花顺本环境拿不到成分股）。

### ✨ 增量数据 —— 有则更佳（题材轮动 / 资金面研究的核心）

| 能力 | 接口 | 用途 |
|------|------|------|
| **板块资金流排名** | `stock_sector_fund_flow_rank(indicator, sector_type)` | 今日/5日/10日，全板块主力净流入排名 |
| **行业历史资金流** | `stock_sector_fund_flow_hist(symbol)` | 单行业逐日主力净流入序列 |
| **概念历史资金流** | `stock_concept_fund_flow_hist(symbol)` | 单概念逐日主力净流入序列 |
| **板块内个股资金流** | `stock_sector_fund_flow_summary(symbol, indicator)` | 某板块内成分股资金流明细 |
| **板块实时行情** | `stock_board_concept_spot_em` / `industry_spot_em` | 盘中快照（EOD 系统用处有限） |
| **当日板块异动** | `stock_board_change_em` | 盘中异动事件（涨停潮/异动拉升） |
| **北向资金行业排行** | `stock_hsgt_board_rank_em` | 北向资金增持行业排名 |
| **板块分时历史** | `*_hist_min_em` | 分钟级，EOD 系统一般不需要 |

### 「概念资金概要 / 资金流」是什么（你问的那块）

指**每个板块每天的资金进出量化指标**，核心是「主力净流入额」——把当日成分股的成交按单笔规模拆成超大单 / 大单 / 中单 / 小单，**主力 = 超大单 + 大单**的买入额减卖出额，汇总到板块。典型字段：`主力净流入额 / 主力净流入占比 / 超大单净额 / 大单净额 / 净流入排名`。

- 用途：判断一个题材是「资金在抢」（净流入持续为正且排名靠前）还是「在出货」（价涨但资金净流出）。这是题材轮动、龙头甄别的**关键量化面**，比单看涨跌幅信息量大得多。
- 区别于同花顺 `summary_ths` 的「驱动事件 / 龙头股」——那是**定性**题材描述；资金流是**定量**资金面。两者互补。

---

## 5. 方案设计（假设东财可用；遵循现有分层与契约）

### 5.1 表设计（DuckDB，沿用幂等 + PK + 点时风格）

```
board_dict        板块字典
  board_code PK         -- 东财 BKxxxx，跨日稳定，作主键
  name, board_type      -- concept / industry
  source                -- 'em'（预留 ths/sina）
  member_count          -- 最新成分数（冗余，便于核对）
  updated_at

board_member      板块成分股（多对多，点时累积）
  board_code, code, in_date, out_date    -- PK(board_code, code, in_date)
  -- ⚠ 见 5.4「成分股历史不可回溯」

board_bar         板块指数日线
  board_code, trade_date, open/high/low/close, volume, amount  -- PK(board_code, trade_date)
  -- 板块指数本身无除权，存原值，不套个股复权链

board_fund_flow   板块资金流（增量，可选）
  board_code, trade_date, main_net_inflow, main_net_ratio, ...  -- PK(board_code, trade_date)
```

`stock_basic.concept`：**不再硬塞字段**，改由 `board_member` 反向关联查询「某票属于哪些概念/行业」，避免冗余与不一致；如需展示可加视图。

### 5.2 采集分层（复用现有架构，不另起炉灶）

- **datasource/**：东财板块取数收敛到 `akshare_source`（或新建 `eastmoney_board` 适配器），统一走 `rate_limited` + `with_retry` + 空响应快速降级（参考 [akshare_source.py:41](../../backend/datasource/akshare_source.py:41) `_ak_or_empty`），并复用模块级 requests 超时注入。
- **storage/**：`ddl.py` 加 4 表 + `repository.py` 加点时读写。
- **services/**：`ingest.py` 加板块采集编排——板块字典刷新 → 成分股快照 → 板块指数回填/增量 →（可选）资金流。沿用**写库全局互斥**与 `async_task` 进度。
- **cli.py**：新增 `board` 命令族（`board --backfill` 全量回填指数历史 + 首次成分快照；`board --update` 增量）；并入 `daily` 一键流程。

### 5.3 应对 IP 限流（落地前提）

- 数据源配置增加**代理出口**（可选）+ **严格限速**（建议 ≥1.5s/次，低于现有 `rate_limit_per_sec`），加 `Referer: https://quote.eastmoney.com/` 头降低被 reset 概率。
- 板块全量回填（300+ 概念 × 成分股 + 指数历史）是**密集请求**，最易触发限流——必须分批 + 断点续跑（参考现有 `backfill` 断点机制）。

### 5.4 关键约束 / 坑（设计决策点，须先确认）

1. **🔴 成分股历史不可回溯**：东财 `cons_em` 只返回**当前**成分，不给历史进出。因此 `board_member` 的 `in_date/out_date` 只能**从接入日起每日快照 diff 累积**——接入前的历史成分无法补。这与项目「防幸存者偏差」理想有缺口：**早期回测按板块成分选股会带幸存者偏差**，须在回测层显式标注「板块成分仅自 YYYY-MM-DD 起点时可信」。
2. **板块指数复权**：板块指数无除权概念，`board_bar` 直接存原值，**不套用个股 `adj_factor` 复权链**，避免污染既有复权契约。
3. **个股代码对齐**：`cons_em` 返回 6 位代码，入库前需补交易所后缀对齐 `stock_basic.code`（如 `600000.SH`）。
4. **口径单选**：建议**主源东财**统一概念/行业体系，不混用同花顺/新浪口径（混用会导致成分股与板块代码对不上）。

---

## 6. 推荐路径与待确认项

**推荐**：先由用户换网络验证东财（§3 URL）。确认是 IP 限流后——

1. 以**东财为唯一板块数据源**，落地 §5 的 4 张表 + 采集链，必要四件套（概念 / 行业 / 历史指数 / 成分股）一次到位；
2. 资金流作为**增量第二期**（`board_fund_flow` + 资金流接口），支撑题材轮动研究；
3. 限流通过**限速 + 可选代理 + 分批断点**控制。

**开发前须确认（关键决策点）**：
- 成分股历史不可回溯（5.4-1）能否接受？是否需要在回测层加「板块成分起点」护栏？
- 是否要第一期就纳入资金流，还是先只做四件套？
- 是否需要代理出口配置，还是先用「严格限速 + 换宽带出口」？
