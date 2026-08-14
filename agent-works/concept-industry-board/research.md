# 概念 / 行业板块数据可行性调研

> 调研时间：2026-06-25　复核时间：2026-08-08（换网段后复测）
> 调研性质：只读评估，未改任何代码 / 未建任何表
> **结论一句话（2026-08-08 更新）：东财列表/成分股接口在本机网络下持续受限（冷却 3/6 分钟不恢复）；同花顺可独立闭环「板块字典 + 成分股 + 板块指数历史」全套，成为事实主源。** 推荐主源同花顺，东财仅保留可用域（push2his 指数历史）作冗余，新浪降为兜底。

---

## 1. 现状（代码事实）

| 维度 | 状态 | 依据 |
|------|------|------|
| `stock_basic.industry` 字段 | ✅ 已定义、已采集 | [ddl.py:34](../../backend/storage/ddl.py:34)；baostock `get_industry()`（证监会行业，[baostock_source.py:142](../../backend/datasource/baostock_source.py:142)）；写入点 [ingest.py:1605](../../backend/services/ingest.py:1605) |
| `stock_basic.concept` 字段 | 🟡 仅占位，始终 NULL | [ddl.py:35](../../backend/storage/ddl.py:35) 定义为「JSON 字符串可多值」，全代码无写入 |
| 板块字典 / 成分股关系 / 板块行情表 | 🔴 不存在 | DDL 无任何板块相关表 |
| 交易所 `board`（主板/创业板/科创板） | ✅ 有但与本议题无关 | [akshare_source.py:106](../../backend/datasource/akshare_source.py:106)，仅用于涨跌停判定 |

---

## 2. 数据源接口实测矩阵（2026-08-08 复测，换网段后）

### 🔴 东财系（`*_em`）—— push2 数字子域持续受限，不可作主源

| 接口 | 复测结果 | 备注 |
|------|------|------|
| `stock_board_concept_name_em` / `industry_name_em`（列表） | 🔴 首发偶发 200（504 条），连发即 reset，冷却 3/6 分钟均不恢复 | 走 `79/17.push2.eastmoney.com` 数字子域 |
| `stock_board_concept_cons_em` / `industry_cons_em`（成分股） | 🔴 持续 000 | 走 `29.push2.eastmoney.com` |
| `stock_board_concept_hist_em`（概念指数历史） | ✅ 200，数据完整 | 走 `91.push2his.eastmoney.com` |
| `stock_board_industry_hist_em`（行业指数历史） | 🔴 000 | 走 `7.push2his.eastmoney.com` |
| `stock_value_em`（市值，现有链路） | ✅ 200 稳定 | 走 `datacenter-web.eastmoney.com` |

**限流定性（比 6-25 更明确）**：东财的封禁是**出口 IP 级 + 频率触发 + 全 push2 域名生效**，非接口失效、非子域问题。换网段后同一现象复现；批量扫 16 个数字子域全 000；冷却 6 分钟不恢复。akshare 东财列表接口硬编码数字子域且分页仅 0.5~1.5s 随机延迟，现网下无法支撑板块采集。**结论：东财主源方案不可行。**

### ✅ 同花顺系（`*_ths`）—— 可独立闭环全套（2026-08-08 新证实）

**此前结论「同花顺无成分股接口」已被推翻。** akshare 公开层无 `cons_ths`，但同花顺板块详情页内嵌完整成分股表格，AJAX 翻页可取全：

```
http://q.10jqka.com.cn/gn/detail/code/{概念代码}/page/{页码}/ajax/1/      # 概念板块
http://q.10jqka.com.cn/thshy/detail/code/{行业代码}/page/{页码}/ajax/1/  # 行业板块
```

**取数要点（实测踩坑）**：
- **生产实现口径**：板块采集全部走自封装的 `ThsBoardSource`（直连同花顺 `q.10jqka.com.cn` / `data.10jqka.com.cn`），**不调用 akshare 公开函数**。下表「接口名」为调研阶段验证用的 akshare 函数，仅用于确认数据可用性与字段；生产实现需在 `ThsBoardSource` 内按相同 URL/参数自行请求解析。
- 请求必须带 `v` cookie（用 akshare **打包的同花顺 `ths.js`** 经 `py_mini_racer` 执行生成——这只是复用其内置的 JS 反爬校验脚本，并非调用 akshare 板块接口），否则 401。
- 翻页是路径参数 `page/N/ajax/1/`，不是 URL query。
- **排序参数敏感**：部分板块带 `field/199112/order/desc` 才能取全，部分不带反而更多（实测华为汽车带排序 50 只/不带 20 只，创新药相反）。鲁棒策略：两种都试、取多者。
- 每页条数不固定（概念 10 条/页、行业 20 条/页），用「该页行数 < 满页」判断尾页不可靠，须按序号去重续取或探测空页终止。
- **🔑 双代码体系（2026-08-08 用户手机核实）**：同花顺概念板块有两套代码——**路径 code（30xxxx，如 AI PC=309121）**与 **App clid（88xxxx，如 AI PC=886071）**。实测：
  - Web/资金流/分类页所有跳转链接统一用**路径 code**；取数（成分股、指数、分类）也必须用路径 code，clid 作路径取数返回 0 行。
  - **clid 只出现在详情页隐藏字段 `id="clid"`**，是手机 App 内部代码；概念板块 clid 全部 88 开头且唯一，行业板块 clid=路径 code（如半导体 881121=881121）。
  - 概念资金流接口**只返回名称、无代码**，映射须按名称匹配。
  - **采集方案**：主键用路径 code（取数稳定）；`app_code` 存 clid（逐板块详情页抓取，375 概念需额外 1 请求/板块），供用户与手机 App 核对。

| 接口（akshare 函数，调研验证用） | 复测结果 | 备注 |
|------|------|------|
| `stock_board_concept_name_ths`（概念列表） | ✅ 375 行 | `name, code`（6 位路径 code，如 `309121`） |
| `stock_board_industry_name_ths`（行业列表） | ✅ 90 行 | `name, code`（如半导体 `881121`） |
| 概念成分股（详情页 AJAX） | ✅ 可分页取全 | 实测 AI PC 50 只、创新药 50 只、华为汽车 50 只、人工智能 50 只 |
| 行业成分股（详情页 AJAX） | ✅ 可分页取全 | 实测半导体约 190 只（10 页×20 只） |
| `stock_board_concept_index_ths` / `industry_index_ths`（指数历史） | ✅ | `日期,开/高/低/收,成交量,成交额` |

> **生产实现**：以上接口仅调研验证。`ThsBoardSource` 需在内部按相同 URL/参数自行请求解析（见「取数要点」），不依赖 akshare 函数名或返回值结构。

### 🟡 新浪系 —— 备选，粒度粗

`stock_sector_spot` + `stock_sector_detail`：可用（含成分股），但概念仅 175 个、行业仅 49 个，粒度粗、口径与同花顺不一致，无板块指数历史。降为兜底。

### ✅ baostock 行业 —— 已接入

`get_industry()`：证监会行业单一标签，无成分股反查、无板块行情。

---

## 3. 数据源能力矩阵（2026-08-08 定稿）

| 能力 | 东财 | 同花顺 | 新浪 | baostock |
|------|------|--------|------|----------|
| 概念板块字典 | ❌ 被封 | ✅ 375 | ✅ 175 | ❌ |
| 行业板块字典 | ❌ 被封 | ✅ 90 | ✅ 49 | ✅ 证监会单标签 |
| 板块→成分股 | ❌ 被封 | ✅ 详情页 AJAX | ✅ detail | ❌ |
| 板块指数历史 | ✅ 仅 push2his | ✅ 概念+行业 | ❌ | ❌ |
| 数据闭环 | ✗ 缺列表/成分 | ✅ **完整** | ✗ 无指数 | ✗ 无板块 |

**主源选型结论：同花顺。** 唯一可独立闭环「板块字典 + 成分股 + 板块指数历史」全套、且当前网络下稳定的源；无需跨源对齐。东财 push2his 概念指数历史可作冗余/交叉验证；新浪为兜底。

---

## 4. 成分股内容抽查（2026-08-08 实测，验证可用性）

| 板块 | 代码 | 成分数 | 代表性成分股 |
|------|------|--------|--------------|
| AI PC | 309121 | 50 | 胜宏科技、博敏电子、奥士康、景旺电子、中京电子、鹏鼎控股 |
| 创新药 | 308014 | 50 | 博腾股份、百普赛斯、泓博医药、药石科技、康龙化成 |
| 华为汽车 | 308507 | 50 | 中富电路、通宇通讯、京泉华、万通智控、强瑞技术 |
| 人工智能 | 302035 | 50 | 志特新材、一博科技、国科微、芯朋微、翱捷科技 |

> ⚠️ **数据质量注意**：「人工智能」板块成分股混入大量医药股（义翘神州、诺唯赞、药石科技、康龙化成、美迪西、成都先导等），疑似同花顺对该概念的定义偏宽（含 AI 制药/AI 医疗）或板块代码与命名漂移。接入时对「概念命名与内容」需做质检验证，勿想当然按名称解释成分股。

---

## 5. 调研阶段方案设计（2026-08-08，已由 §7 的现行实现校准）

> 本节保留需求形成时的区间 diff/候选方案研究过程，不再代表当前表结构和采集规则；当前有效事实见 §7、`requirement.md` §14 与 `plan.md` §11。

### 5.1 表设计（DuckDB，沿用幂等 + PK + 点时风格）

```
board_dict        板块字典（概念+行业并集）
  board_code PK         -- 同花顺路径 code（概念 30xxxx / 行业 88xxxx），跨日稳定，作主键；所有取数接口/跳转链接统一用它
  app_code              -- 同花顺 App 内部代码（概念 clid 88xxxx，如 AI PC=886071；行业 clid=路径 code）。用户手机 App 显示此码，供核对
  name, board_type      -- concept / industry
  source                -- 'ths'（来源系统；非数据能力标记）
  has_members           -- 是否有成分股数据
  has_bar               -- 是否有板块指数
  has_fund_flow         -- 是否有资金流
  member_count          -- 调研阶段定义；现行口径为最近一次完整快照返回数
  member_history_start_date -- 成分快照首次完整采集日（板块级）
  last_seen_at          -- 最近一次在任意源出现
  updated_at

board_member      板块成分股（多对多，快照 diff 累积）
  board_code, code, in_date, out_date    -- PK(board_code, code, in_date)
  -- 区间语义 [in_date, out_date)：in_date=首次完整快照观察到，out_date=首次确认缺席
  -- ⚠ 见 5.4「成分股历史不可回溯」；不完整快照禁止执行退出 diff

board_bar         板块指数日线
  board_code, trade_date, open/high/low/close, volume, amount  -- PK(board_code, trade_date)
  -- 板块指数本身无除权，存原值，不套个股复权链

board_fund_flow   板块资金流
  board_code, snapshot_date, period, inflow, outflow, net_inflow,
  net_ratio, leader_stock, leader_pct  -- PK(board_code, snapshot_date, period)
  -- period ∈ {即时, 3日, 5日, 10日, 20日}（全部采集，页面本期只展示即时）

board_member_candidate  成分快照候选（异常快照暂存与人工确认）
  candidate_id PK, issue_id, board_code, snapshot_date, codes_json,
  payload_hash, diff_summary, status, applied_at
  -- 唯一约束 (board_code, snapshot_date, payload_hash)；status ∈ {pending, applied, discarded}
  -- 候选与 data_quality_issue 同在 DuckDB，经 issue_id 关联
  -- 每板块每日最多一个 applied；同日替换本期不实现
```

`stock_basic.concept`：**不再硬塞字段**，改由 `board_member` 反向关联查询「某票属于哪些概念/行业」，避免冗余与不一致；如需展示可加视图。

### 5.2 采集分层（复用现有架构，不另起炉灶）

- **datasource/**：新增 `ths_board.py` 自封装同花顺板块适配器 `ThsBoardSource`（**不走 akshare 公开函数**），统一走 `rate_limited` + `with_retry`（参考 [base.py:40](../../backend/datasource/base.py:40)），内部构造 `v` cookie 与 AJAX 翻页请求。
- **storage/**：`ddl.py` 加 5 表（`board_dict`、`board_member`、`board_bar`、`board_fund_flow`、`board_member_candidate`）+ `repository.py` 加点时读写与候选恢复读写。
- **services/**：`ingest.py` 加板块采集编排——板块字典刷新 → 成分股快照 → 板块指数回填/增量 → 资金流（本期纳入）。沿用**写库全局互斥**与 `async_task` 进度。
- **cli.py**：新增 `board` 命令族（`board --backfill` 全量回填指数历史 + 首次成分快照；`board --update` 增量）；并入 `daily` 一键流程。

### 5.3 应对频率限制（同花顺同样存在频率限流）

- 严格限速（同花顺详情页连续翻页会触发频率限制，建议 ≥1s/次，低于现有 `rate_limit_per_sec`）。
- 板块全量回填（375 概念 × 分页 + 指数历史）是密集请求——必须分批 + 断点续跑（参考现有 `backfill` 断点机制）。

### 5.4 关键约束 / 坑（已确认）

1. **🔴 成分股历史不可回溯**：同花顺详情页只返回**当前**成分，不给历史进出。因此 `board_member` 的 `in_date/out_date` 只能**从接入日起每日快照 diff 累积**——接入前的历史成分无法补。`member_history_start_date` 按**板块级**保存（首次完整采集日），不同板块首次完整采集可能不同，因此按板块保存比全局日期更准确。**本期不改回测层**；后续真正接入筛选/回测时，再对早于该日期的查询拒绝执行或显示明确警告。
2. **🔴 快照区间语义**：`snapshot_date` = Asia/Shanghai 时区实际成功采集日期；`in_date`=首次在完整快照中观察到该股票，`out_date`=首次确认缺席；有效区间 `[in_date, out_date)`，查询 `in_date <= D AND (out_date IS NULL OR out_date > D)`。**单板块分页不完整、请求失败或成分数异常时，不执行退出 diff**，防止误把全部股票标记退出。**合法异常恢复（全同步 + payload_hash 幂等）**：被拦截板块候选快照写入 `board_member_candidate`（含 `candidate_id`/`issue_id`/`payload_hash`，与 `data_quality_issue` 同在 DuckDB 经 `issue_id` 关联）；**创建（issue+candidate）、应用（member+candidate+issue）、丢弃（candidate+issue）均为同一 DuckDB 事务**，不绑 `fix_task_id`、不起异步任务；`payload_hash = SHA-256(ISO日期 + "\n" + sorted(set(归一化代码)).join("\n"))`（不用 Python hash()；输入 UTF-8、输出小写 hex 64 字符、字段声明为 VARCHAR(64)，由服务层校验 + `CHECK (regexp_full_match(payload_hash, '[0-9a-f]{64}'))` 保证格式），同 hash+pending 返回已有、同 hash+applied/discarded 幂等跳过；**每板块每日最多一个 applied（DB 层用 `(board_code, snapshot_date, CASE WHEN status='applied' THEN 1 ELSE NULL END)` 表达式唯一索引兜底；DuckDB 不支持 `WHERE status='applied'` 部分索引），同日不同 hash 走异常处理不允许普通 apply**；PG 审计为 **best-effort**（对齐 audit_repository 现状，失败返回 None 不回滚 DuckDB），不引入 outbox（项目无此设施，可靠性提升列后续需求）。
3. **板块指数复权**：板块指数无除权概念，`board_bar` 直接存原值，**不套用个股 `adj_factor` 复权链**，避免污染既有复权契约。
4. **个股代码对齐**：详情页返回 6 位代码，入库前需补交易所后缀对齐 `stock_basic.code`（如 `600000.SH`）。
5. **口径单选**：建议**主源同花顺**统一概念/行业体系，不混用新浪/东财口径（混用会导致成分股与板块代码对不上）。
6. **🟡 排序参数敏感性**：同花顺详情页 AJAX 对排序参数敏感（见 §2），适配器须两种请求方式都试、取多者，避免板块成分取不全。
7. **🟡 概念内容漂移**：「人工智能」等板块成分股存在命名与内容不符（混入医药股），接入质检需抽样核对（见 §4）。
8. **🟡 字典与资金流集合差异**：概念字典 375 vs 概念资金流 387，采用**并集字典**。资金流接口若无可稳定映射的板块代码、只能名称匹配时，未匹配项写质检问题，**不生成伪造代码**。`source` 表示来源系统（`ths`），能力差异用 `has_members/has_bar/has_fund_flow` 字段区分。

---

## 6. 推荐路径与已确认结论

**推荐（2026-08-08 修订；🔴 候选/diff 部分已由 2026-08-09 只进不出改造取代，见 §7 现行事实）**：

1. 以**同花顺为唯一板块数据源**，落地 §5 的 4 张表 + 采集链（板块字典、成分关系只进不出累积、历史指数、资金流一次到位；候选恢复机制已废弃，不落候选表）；
2. 资金流**第一期纳入**（`board_fund_flow`，即时/3日/5日/10日/20日全周期采集，页面本期只展示即时），支撑资金面验证；
3. 限流通过**限速 + 分批断点**控制；
4. 东财 push2his 概念指数历史可作为同花顺指数的交叉验证（可选，暂不实现）。

**已确认决策**：
- 成分股历史不可回溯（5.4-1）能否接受？**已确认：本期只保存板块级 `member_history_start_date`，不改回测层；回测联动后续单独实施。**
- 是否要第一期就纳入资金流？**已确认：纳入。**
- 同花顺适配器是单独封装 `ths_board.py` 数据源，还是挂在既有 `AKShareSource` 上？**已确认：单独封装 `ThsBoardSource`。**

---

## 7. 现行实现事实复核（2026-08-09）

- **数据模型**：当前为 `board_dict`、`board_member`、`board_bar`、`board_fund_flow` 4 表；`board_member_candidate` 已删除。`board_member` 主键为 `(board_code, code)`，只进不出，不维护 `in_date/out_date`，不做快照 diff。
- **完整性闸门**：只有非空且 `complete=True` 的成分快照才落库；成功时在同一事务中新增关系、刷新 `member_count/member_snapshot_at/member_history_start_date` 并收敛活跃 `board_member_incomplete`。不完整或异常时旧数据不动、更新日志记失败、问题保留待重采。
- **数据源适配**：`ThsBoardSource` 已独立落地，字典、clid、成分、指数、资金流均由同一适配器提供；clid 按实例缓存。指数分年请求会通过 DataFrame `failed_years` 标记部分失败，失败年份不写完成 checkpoint。
- **采集范围与增量**：支持 `backfill|update`、`concept|industry`、指定板块、阶段范围和限量。update 只补近期指数并采即时资金流；backfill 回填源端可用指数历史并采全部资金流周期。显式空代码范围是 no-op，不会退化为全量。
- **断点与失败**：字典按类型、成分/指数按板块、资金流按类型+周期记录 checkpoint；部分失败任务最终为 failed，但保留已成功 checkpoint 供定向续跑。
- **质量修复**：现行问题类型为 `board_index_gap`、`board_member_incomplete`、`board_fund_unmatched`。修复复用同一采集服务，只有真实复检通过才 resolved；失败或复检未通过回到 open。
- **数据概览**：除维度注册外，现已聚合 4 表行数、概念/行业数量、成分/指数/资金流覆盖、最新日期、活跃问题分类和最近采集状态。
- **范围边界**：数据采集与数据管理闭环已完成；板块业务查询后端 `/api/sectors*` 已完成，但 `/sectors` 与 `/sectors/:code` 前端业务页仍未落地。

---

## 附：同花顺板块适配器封装决策（2026-08-08）

**是否单独封装一个同花顺数据源？——建议：单独封装 `ThsBoardSource`，不并入 `AKShareSource`，也不并入 `DataSource` 基类主流程。**

理由：

1. **技术栈不同**：同花顺板块取数不走 akshare 公开函数，而是直连 `q.10jqka.com.cn` 详情页 + AJAX 翻页 + `v` cookie 校验。这比 akshare 封装层更深，且依赖 `py_mini_racer` 执行 ths.js。若并入 `AKShareSource`（走 akshare 函数），会把「直连 + JS 校验」这套独立机制硬塞进一个「以 akshare 函数为主」的类里，职责混杂。
2. **数据形态不同**：现有 `DataSource` 统一 schema 全是**时间序列**（daily_bar/index_bar/calendar/valuation…），而板块数据是**关系型**（板块字典 + 成分股多对多 + 板块指数）。把「板块字典/成分股」硬塞进 `DataSource` 抽象（`get_daily_bar` 这类接口）会破坏抽象一致性——`DataSource` 应保持「个股时间序列」职责，板块关系数据另立适配器。
3. **能力选源不适用**：`IngestionService._source_for(capability)` 是按 `capabilities` 声明在主源/补源间选源。板块采集是**独立编排流程**（字典→成分→指数→资金流），不是某个 capability 的兜底，不需要进 `_source_for` 的选源链。
4. **限流独立性**：同花顺板块接口的限流策略（≥1s/次、v cookie 刷新）与现有 akshare 限流（`rate_limit_per_sec`）不同，单独封装便于独立控制。

**建议结构**：

```
backend/datasource/ths_board.py      # ThsBoardSource：板块字典/成分股/指数历史/资金流
  class ThsBoardSource:
      get_board_dict(board_type)      # concept / industry → name, code
      get_board_members(code)         # 分页取成分股，两种排序策略取多者
      get_board_bar(code, start, end) # 板块指数历史
      get_board_fund_flow(board_type, period) # 资金流（本期纳入；按类型与周期抓取）
  # 内部：_v_cookie()（py_mini_racer + ths.js）、_ajax_page()（带 cookie 翻页）
  # 复用 base.rate_limited / with_retry 装饰器，独立限流间隔
```

- `IngestionService` 新增板块编排方法（`ingest_board`），直接持有 `ThsBoardSource` 实例，不进 `_source_for` 选源链。
- `cli.py` 新增 `board` 命令族调 `ingest_board`。
- 不修改 `DataSource` 抽象与既有 `AKShareSource`/`BaostockSource`。

**备选（不推荐）**：并入 `AKShareSource` 加 `get_board_dict/get_board_members` 方法。缺点：引入 `py_mini_racer` 依赖到主采集源、`DataSource` 抽象被关系型数据污染、限流混用。除非坚持「所有取数都走 akshare 一层」，否则不建议。
