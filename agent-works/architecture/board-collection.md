# 板块数据采集闭环

> 同花顺板块数据（概念/行业）的采集、质检、概览、调度、手动采集与修复全链路闭环。数据独立于个股行情源，由专属 `ThsBoardSource` 直连同花顺，经 `board_dict / board_member / board_bar / board_fund_flow` 四表落库，供板块行情页（`/sectors`）、详情页（`/sectors/:code`）与数据管理各页消费。

<span style="color:#2563eb">●</span> 直连采集　<span style="color:#7c3aed">●</span> 只进不出　<span style="color:#16a34a">●</span> 周频控制　<span style="color:#dc2626">●</span> 质检修复闭环

## 数据源与反爬（`backend/datasource/ths_board.py`）

同花顺板块数据是**独立反爬直连源**，不调用 akshare 板块公开函数；仅复用 akshare 打包的 `ths.js`（v cookie 生成脚本，经 `py_mini_racer` 执行）。三域职责：

| 域 | 用途 | 备注 |
|----|------|------|
| `q.10jqka.com.cn` | 板块字典、成分股详情页 AJAX | 翻页是路径参数 `page/N/ajax/1/`，每页行数不固定（概念 10/行业 20） |
| `data.10jqka.com.cn` | 资金流排行 | 周期走 `board/N` 参数；请求带 `hexin-v` 头 |
| `d.10jqka.com.cn` | 板块指数日线 | `v4/line/bk_{clid}/01/{year}.js`，**历史仅近 3 年**（2024 起，2021-2023 返回 404） |

反爬与稳定性关键事实：
- **v cookie**：详情页 AJAX 必须带 `v=...`，否则 401；由 `py_mini_racer` 执行 `ths.js` 动态生成，401 时自动刷新重试一次。
- **登录态**（可选）：解除详情页/字典翻页登录墙（第 6 页起无登录必命中），但 cookie 里的 `v` 会过期，须用新生成的 `v` 覆盖。Cookie 可由页面加密配置或环境/受控文件注入；不进入 YAML，PG 只存密文，审计不存明文。
- **翻页终止**：翻页是路径参数 `page/N/ajax/1/`，每页行数不固定（概念 10/行业 20），用「该页无行」终止翻页并做页码上限护栏。
- **资金流空壳页**：`data.*/funds/*` 分页偶发返回 HTTP 200 但无数据行的空壳页（反爬）。`get_board_fund_flow` 对首页与后续页都空壳重试（`_FUND_FLOW_EMPTY_RETRIES=3`），重试后仍空只**跳过该页、不截断后续页**——修复前 `df.empty→break` 遇中间页空壳会截断后续所有页，造成即时周期覆盖在 350~387 间波动（2026-08-13 实测）。
- **资金流源覆盖边界**：排行榜源（`funds/gnzjl`）覆盖约 350~387 个概念板块；**部分老板块（如 WiFi 6/AI PC/中国AI 50，K 线自 2024 起）排行榜源从不收录**（换排序参数也不出现），gnSection/详情页虽有资金流但为**不同口径**（同刻排行榜「净额」vs 详情页「资金净流入(亿)」系统性不同，diff -5.87~+3.63），不得混入 `board_fund_flow.net_inflow`。
- **排序参数敏感**：部分板块带 `field/199112/order/desc` 才能取全，部分不带反而更多；鲁棒策略是两种请求都试、取代码集合的并集。
- **限流/超时/重试走配置**（见下文「配置」），`rate_limited` 装饰器优先读实例属性 `_min_interval_sec`，前端改配置后新建实例即生效。
- **完整性判定**：单板块分页不完整（登录墙/翻页失败/401）时 `get_board_members` 返回 `complete=False`，采集层据此不落库。

**概念字典数量口径**：无登录态时 `gn/index` 第 6 页起撞登录墙，概念停在约 **375**（深页板块如 CRO概念/NMN/HJT电池 取不到）；配置/注入登录 Cookie 解除登录墙后可翻到深页取全（约 **390**）。375 是登录墙截断值而非全量。

## 登录态 Cookie 管理（同花顺）

登录态 Cookie 用于解除同花顺详情页/字典翻页登录墙（第 6 页起无登录必返回 `upass...login` 跳转壳），是取全深页板块（375→390）与完整成分股（半导体无登录约 100 只，登录后 120~160 只）的前提。**不配置也能采集，只是被登录墙截断**。

### 取数优先级（`ths_board.py:_login_cookie_from_config`）

生效 Cookie 按以下顺序取第一个非空值，前序存在即生效、不继续回落：

1. **环境变量 `AI_STOCKS_THS_COOKIE`**：完整 Cookie 头字符串（运维部署级，最高优先级）。
2. **环境变量 `AI_STOCKS_THS_COOKIE_FILE`**：指向存有 Cookie 的文件路径（读取后 `strip`，仅当 `AI_STOCKS_THS_COOKIE` 为空时读取）。
3. **页面加密配置 `ths_board.login_cookie`**：系统设置或任务调度的数据源「授权配置」入口写入；`AppConfigRepo` 解密后只在进程内消费。

### 安全与运维机制

- **注入**：页面配置保留，适合系统管理员在线更新；部署环境仍可用环境/文件覆盖。页面只回显“已设置”，不返回明文。
- **持久化防线**：`ths_board.login_cookie` 标记为 `password + encrypted`；数据库保存 `enc:v1:` Fernet 密文，主密钥只来自 `AI_STOCKS_CONFIG_ENCRYPTION_KEY` / `_FILE`，审计 before/after 固定脱敏。
- **存量处置**：PG 初始化发现历史明文时，有主密钥则原位加密，无主密钥则删除明文并告警；历史审计 before/after 原位改为“已变更”。已暴露 Cookie 仍须在同花顺侧轮换。

### 生效时机与失效

- 新建 `ThsBoardSource` 实例时读取环境/文件/页面加密配置；运行中变更后由新任务使用新值，常驻实例需重建或重启。
- Cookie 是**会话凭证**：同花顺登录过期/异地登录会失效；`v` 字段由请求侧动态生成并覆盖（`_replace_v`），不依赖复制时的旧 `v`。
- 失效表现：采集日志中 `complete=False` 增多（成分不完整）、概念数回到 375 附近（深页板块缺失）→ 重新获取浏览器 Cookie 并更新页面配置或运行时环境/文件。

### 与 v cookie 的区别

| | v cookie | 登录 Cookie |
|---|---|---|
| 作用 | 反爬校验（详情页 AJAX 必须带） | 登录态（解除翻页登录墙） |
| 生成 | 请求侧动态执行 `ths.js` | 浏览器登录后复制 |
| 过期 | 与 IP/时间动态绑定，401 自动刷新 | 会话级，过期需重新获取 |
| 管理 | 无需人工 | 页面配置 / 环境变量 |

## 四张表（`backend/storage/ddl.py`）

| 表 | 主键 | 核心字段 | 语义 |
|----|------|----------|------|
| `board_dict` | `board_code` | `app_code`(clid) / `board_type` / `has_members` / `has_bar` / `has_fund_flow` / `member_count` / `member_history_start_date` / `member_snapshot_at` / `last_seen_at` | 板块字典 + 能力字段 + 成分快照元信息 |
| `board_member` | `(board_code, code)` | — | 成分股多对多，**只进不出**累积 |
| `board_bar` | `(board_code, trade_date)` | `open/high/low/close/volume/amount` | 板块指数日线，**存原值不套个股复权链** |
| `board_fund_flow` | `(board_code, snapshot_date, period)` | `inflow/outflow/net_inflow/net_ratio` / `leader_stock/leader_pct` | 资金流多周期（即时/3日/5日/10日/20日） |

`board_code` 用同花顺路径 code（概念 `30xxxx` / 行业 `88xxxx`），取数与跳转统一用它；`board_member.code` 补交易所后缀对齐 `stock_basic.code`。

## 采集编排（`backend/services/ingest.py` + `board_ingest.py`）

编排顺序固定：**字典 → 成分快照 → 指数 → 资金流**，单步骤失败记日志不中断，返回失败清单。

### mode 语义

| mode | 字典 | 成分 | 指数 | 资金流 |
|------|------|------|------|--------|
| `update`（每日增量） | 全量 upsert | 周频跳过逻辑 | 截止最近交易日、区间起点往前取 **7 个自然日**缓冲（覆盖跨周末/长假缺口，非"7 个交易日"）；非交易日不探测直接回退，交易日全量先**源端就绪探测**，未就绪回退到上一交易日继续采集 | 全周期（即时/3日/5日/10日/20日）每日刷新 |
| `backfill`（初始化） | 全量 upsert | 强制全量（绕周频） | 源端可用年限（2024 起） | 全周期 |

资金流增量全周期口径：滚动周期（3日/5日/10日/20日）是源端按最近 N 个交易日滚动重算的值，每日变化，只采「即时」会让多周期数据停在 backfill 当天。数据源不返回可靠数据日，update/backfill 主编排统一以本轮目标交易日写入 `snapshot_date`，不使用周末或节假日的实际采集日。数据源不支持按日期回溯补采，故缺失的历史某天无法追回，质检只盯最新快照新鲜度（见下）。

### 指数源端就绪探测与新鲜度透出

板块指数源端（同花顺）**分板块陆续发布当日数据**，傍晚采集时大部分板块可能还没出当天指数；若直接采，会落一批"停在昨天"的数据且任务报成功，只能靠质检缺口事后发现。对齐行情 update 的就绪门（`_UPDATE_READY_*`）：

- **触发条件**：仅「全量（未指定 `board_codes`）且截止日=今天（即今天是交易日）」。指定板块、backfill、缺口窄窗口重采尊重调用方意图不探测；非交易日截止日<今天，历史数据必已发布，也不探测。
- **判定**：均匀抽样 10 个板块请求当日单日指数，已出数占比 < 50% 视为未就绪（`_BAR_READY_SAMPLE`/`_BAR_READY_RATIO`，`board_ingest.py`）。
- **回退语义**：未就绪时不拉当日半成品，将本轮 `end` 收敛为上一交易日并继续整体采集；结果返回 `fallback=True, reason=source_not_ready, requested_end, end`，任务日志 warn 说明原目标和实际截止日。下轮定时仍重新目标当天，7 日缓冲保证之前的漏采可同步补齐。
- **新鲜度透出**：每次指数采集的结果与日志（任务阶段行 + `data_update_log` detail）都带**采集区间 `start ~ end`** 和「已出截止日 K/N」（本轮范围内库内已覆盖到截止日的板块数，含续跑已完成），让「成功但源端滞后」在日志层面直接可见。

`force_members` 解析（`ingest.py:1823`）：未显式传值时，`mode=backfill` **或** 显式指定 `board_codes` → 强制全量；否则默认 update 走周频。**显式传 `False` 会覆盖自动解析**（历史教训：CLI 曾始终传 `args.force_members` 默认 False，导致指定板块重采被周频挡住，已修为仅显式 `--force-members` 才传）。

### 只进不出模型（成分）

- `board_member` 主键 `(board_code, code)`，**每只成分股一行累积，不删除、不做 diff、不记候选**。
- 完整快照（`complete=True`）`INSERT ... ON CONFLICT DO NOTHING`：已在表内的不动、新出现的插入；同步刷新 `board_dict.member_count`（当前成分数）。
- **完整性即闸门**：`complete=False`（登录墙/翻页失败/401）整趟快照不落库，`data_update_log` 记 failed + 写 `board_member_incomplete` issue，已采旧数据原样保留。
- 重采天然安全：完整快照只新增不覆盖，缺某股不影响既有行。

### 周频跳过（成分不随每日增量全量拉）

成分股低频静态，不每天重拉。默认模式只重拉两类板块：
- `member_snapshot_at` 距今 ≥ `member_update_interval_days`（默认 7，`ths_board` 配置可调）；
- `member_snapshot_at IS NULL`（从未完整落库）。

未达间隔的板块记 `skipped` 跳过——**不计失败、不打 failed 日志、不写 `board_member_incomplete` 质检**（跳过 ≠ 失败，周频不产生虚假质量问题）。`force=True`（质量修复重采 / backfill 初始化 / CLI `--force-members` / 前端「强制刷新全部板块成分」）绕过间隔。间隔比较与写入同源（DB `now()` 写 TIMESTAMP 列、DB `now()` 取 cutoff），避免会话时区 8h 偏移。

### checkpoint 续跑

四阶段各自 checkpoint，resume 时与当前范围做交集过滤：
- 字典 `dict_done_types`（按 concept/industry 类型）
- 成分 `member_done_codes`（按板块 code）
- 指数 `bar_done_codes`（按板块 code）
- 资金流 `fund_done_keys`（按 `{scope_tag}:{board_type}:{period}`，`scope_tag` 是 board_codes 子集的 md5 前缀或 `ALL`）

**资金流 checkpoint 带范围签名**：改 board_codes 子集后续跑不会误命中旧范围已完成组。**旧格式兼容**：改动前无前缀的键（如 `concept:即时`）在全量续跑时自动平移为 `ALL:concept:即时`，避免旧任务升级后重拉全部资金流。

### 部分失败语义

板块采集单板块/单步骤失败保留 checkpoint 供重试，任务标 failed 且 message 明示「部分完成，可重试未完成项」。`ok=False` 保留成功工作单元 checkpoint，重试时从剩余单元继续；中断状态的用户操作文案为「继续任务」，避免把失败与中断混为同一状态。

### 终止穿透

编排层 dict/members/bar/fund 四个步骤的 `except Exception` 前都加 `except TaskCancelled: raise`（对齐个股 update/backfill 穿透写法）——用户点「终止」正确中断为可续跑 `interrupted`，而非被当成失败吞掉跑完。

### 资金流独有板块

资金流源含字典没有的板块（概念 375 vs 387）。**当前口径（2026-08-10 修订）**：
- 链接带真实路径 code（如 `/gn/detail/code/308734/`）→ 稳定主键，经 `_upsert_fund_only_boards` 补进字典（`has_fund_flow=true`、`has_members/has_bar=false`，列表页不展示，供资金流数据关联）；
- 仍无稳定代码（无链接 code 且名称匹配不到字典）→ 写 `board_fund_unmatched` 质检、不伪造代码。

## 质检（`backend/services/data_report.py` + `dataquality/checker.py`）

板块专项 issue 独立于个股 L1-L4 打分，归入「板块」层（`ISSUE_LAYER` 映射）：

| issue_type | 产生方 | 含义 | 修复动作 |
|-----------|--------|------|----------|
| `board_index_gap` | `scan_board_quality` 扫描 | 板块指数最新日线滞后全局最新交易日 | 补最后已有日之后到当前全局最新日的末尾连续区间；从未入库时只补当前最新日 |
| `board_index_gap_daily` | `scan_board_quality` 扫描 | 板块指数近 `GAP_WINDOW_DAYS` 个开市日内某具体交易日缺失 | 按缺失日窄窗口重采该板块指数 |
| `board_index_invalid` | `scan_board_quality` 扫描 | 指数 OHLC 缺失/越界、价格非正或成交量额为负 | 按异常日窄窗口重采该板块指数 |
| `board_member_incomplete` | 采集层 + `scan_board_quality` | 成分快照采集不完整/失败，或宣称支持成分但从未形成完整快照 | 重采成分（force 绕周频） |
| `board_fund_unmatched` | 采集层 `_write_unmatched_quality` | 资金流未匹配到字典 | 重采资金流 |
| `board_fund_missing` | `scan_board_quality` 扫描 | 板块某周期无不早于基准日的资金流快照（每板块一条 issue，detail 列缺失周期） | 按缺失周期定向重采资金流 |
| `board_fund_stale` | `scan_board_quality` 扫描 | 源级资金流某周期快照滞后全局最新交易日（源级单条，code=NULL，detail 列滞后周期） | 按滞后周期重采全源资金流 |

关键语义：
- `scan_board_quality` 先完整计算再**事务内收敛**扫描型 open 问题，扫描失败不丢旧台账。所有板块问题都支持用户选择“仅忽略本次”或“整体忽略”；质量页还可按当前类型、严重度或对象筛选，将全部 open 问题一键按“仅忽略本次”标记正常。本次异常消失后规则自动失效，整体规则须人工恢复监控；无代码的源级/名称映射问题使用稳定来源或名称组合标识。收敛时**同键（issue_type+code+trade_date）复用 open id**：仍存在的问题 id 不变、detail 原位刷新；本轮不再出现的问题转为 `resolved`（id 保留），保证 issue id 跨扫描稳定，板块 fix 修完立即重扫不会作废批量任务里后续待修 issue 的 id。`board_member_incomplete` 由采集层即时写、扫描补盲区，并共同消费通用忽略规则。指数完整性与字段合法性分开复检；资金流缺失逐板块检查**每个周期**最新快照是否追平基准日，不使用不会回退的 `has_fund_flow` 做当前质量证据，也不会因单板块当日补采而误报全市场。
- 资金流质检**多周期口径**：update 已每日全周期刷新，任一周期单次失败会留下该周期缺口，`board_fund_missing`（detail.periods 列缺失周期）/ `board_fund_stale`（detail 列滞后周期）可定向重采修复；数据源**不支持按日期回溯补采**，故不检查历史某天缺口，只盯最新快照新鲜度。stale 只把「有快照但滞后」的周期计入，从未有快照的周期由 missing 按板块覆盖。
- `board_index_gap` 与 `board_index_gap_daily` 共存：前者定位「最新交易日没追上」，恢复时从该板块最后已有日的下一开市日补到当前全局最新日；旧 issue 延迟执行也会追到执行时的最新日，已经被其它任务追平则直接复检，不重复请求源端。从未入库时无法判断板块成立日，只尝试当前最新日，避免把成立前历史当缺口。后者定位「历史窗口内具体某天缺失」，使用缺失日作为 `start=end` 窄窗口重采；源端虽按年请求，但返回前按请求区间过滤，只幂等 upsert 对应日期。初始化完整历史仍单独走 `backfill`（源端可用年限为 2024 起）。
- **晚成立板块豁免**：逐日缺口扫描以各板块 `min(board_bar.trade_date)` 为数据起点锚，起点（板块成立日）之前的缺失属源端本无数据、不报；起点之后的缺失照报漏采。新板块（如每季「xx一季报预增」）首次进字典即自动豁免成立前缺口，不靠人工 ignore；若其成立后被漏采（起点之后空洞）仍会报。源端 2024 起才有板块指数，`backfill` 后 `min` 即真实起点；老板块漏采补采后 `min` 回填 2024-01-02，豁免自动失效。
- `board_fund_missing` 与 `board_fund_unmatched` 方向相反：前者是「字典目标板块当前无新鲜快照」，后者是「源有、字典缺」。
- `board_fund_stale` 与 `board_index_gap` 等价：资金流是整体批量采集，停摆时所有板块一起滞后，故记单条源级 issue（code=NULL），修复动作重采全源，不拆逐板块。
- `board_member_incomplete` / `board_fund_unmatched` 由采集事件写入，写入前统一匹配生效中的忽略规则；仅本次规则在完整成分成功或名称恢复匹配后自动失效。
- severity 走 `SEVERITY_BY_TYPE` 统一映射（板块专项均为 `mid`），不硬编码。
- 个股 `scan_quality_issues` 的 DELETE+INSERT 也包事务（对齐板块 scan 失败保留语义）；个股覆盖帧缓存签名排除板块 issue，板块写入不击穿个股 frame 缓存。

结构体检（`data_verify.py` E 组，只读不写台账）与本台账互补：体检查板块四表的结构合法性与字段/标记契约（孤儿板块、指数日历一致、OHLC/量额合法、`board_type`/`period` 枚举、`has_*` 能力标记与实际数据双向一致）；缺口/新鲜度只归上表 issue + 修复闭环，体检不重复检查。

## 修复闭环（`backend/services/async_task.py`）

板块 issue 走统一的 fix 任务机制（与个股同链路）：
1. 创建 fix 任务 → issue 置 `fixing` + 绑定 `fix_task_id`；
2. `_recover_one` 按 issue_type 分派重采（指数末尾缺口补最后已有日之后的连续区间 / 指数逐日缺口与非法值按问题日窄窗口重采 / 成分 `force=True` 绕周频 / 资金流缺失按 detail 周期定向 `board_codes`+`periods`、滞后按 detail 周期全源重采、未匹配全周期重采）；
3. `recheck_clean` 真检查该问题是否消失（如成分查 `member_snapshot_at` 非空且无 active 同类 issue，逐日缺口查该日 `board_bar` 记录是否存在）；
4. 通过 → `resolved`；未通过 → 保持 open；任务失败/中断 → `fixing` 复位 `open`；扫描型板块问题修复后立即重扫，同一底层缺口产生的关联台账同步收敛（重扫同键复用 id，不重排 open issue；批量任务里已被重扫先收敛的兄弟 issue 按 `resolved` 良性跳过，不再报「质检问题不存在」失败）。

## 概览 / 调度 / 手动采集 / 前端接入

- **数据概览**（`/data/overview` → `_board_stage`）：板块规模（字典数/概念/行业）、覆盖进度（成分 ready/target、指数、资金流）、鲜活度（板块指数/资金流快照需同时满足日期不早于最新交易日且覆盖率达到统一成功档；日期追平但覆盖不足显示“未齐”）、质量问题分项、最近采集状态。板块数据 tab 展示 hero 卡 + 两列布局（覆盖进度/鲜活度 + 质量问题/最近采集），低高度由面板承接滚动。
- **任务调度**（`/data/schedules` → `SCHEDULABLE_TASK_TYPES` 含 `board`）：创建/编辑校验 `mode ∈ {update,backfill}`、`board_type ∈ {concept,industry}`、`only ⊆ {dict,members,bar,fund}` 和 `force_members`；触发走同一异步任务互斥闸。
- **手动采集**（`/data/ingest`）：与调度页共用 `BoardTaskScopeFields`，对齐采集模式、板块类型、分阶段 `only`、成分强刷；手动入口额外支持指定板块代码/名称。
- **板块行情页**（`/api/sectors`，权限 `sectors:view`）：列表/详情/bars/members 与市场指数基准 bars 均为只读接口，涨幅从 `board_bar` 实时计算；资金流只读取与行情截面日同日的 `board_fund_flow` 快照，某板块或周期当日无数据时返回空且不回退；领涨股按所选行情交易日的有效成分股 `pct_chg` 最大者计算，停牌/缺有效前收排除，同涨幅按成交额降序、代码升序决胜，资金流源自带领涨字段仅作原始留存。列表采用排行与走势图主从联动，自选与对比队列分离；首屏只选择当前列表第一项，额外对比板块由用户主动勾选。纯板块间对比各序列按自身区间首个有效值起算（通常即区间首日为 0%）；叠加系统配置的中证 500、沪深 300、上证指数、科创 50、深证成指或创业板指虚线时，统一从首个共同有效日期起算并计算板块相对指数的超额涨跌，个别板块上市较晚只缩短基准期、不否决整体。列表与详情的近 60/120/250 日是数据与横向缩放的共同硬边界，板块与指数按同一组末尾交易日对齐截断；只有“全部”加载完整历史。列表 K 线模式与详情复用行情多图工作区呈现 K 线、量能和可选 MACD；三者均基于 `board_bar` 原始连续指数，标题不得显示股票复权语义。详情默认图表区 560px、成分股区最小 420px，支持拖拽分隔线调整和保存多图高度比例。成分股采用服务端分页排序，`stocks:view` 决定是否可跳个股页；进入个股前写入当前成分股集合与板块详情返回路径，避免继承每日榜单等旧集合。缓存详情实例固定自身 code，返回列表不再触发空 code 请求；来源状态通过 query 白名单显式恢复，应用菜单恢复最近停留的板块列表或详情子路由。
- **板块自选**：`board_watchlist` 落 PostgreSQL，以 `tenant_id + owner_user_id + board_code` 隔离；加入时保存名称/类型快照。读取时由服务层分别查询 PG 自选与 DuckDB 板块行情后内存合并，禁止跨库 JOIN；板块字典失效时仍返回快照并标记 `available=false`，用户可主动移出。

## 配置（`backend/config/settings.py` + `storage/app_config.py`）

`ths_board` 配置段（系统设置「同花顺板块」tab 可 Web 覆盖，YAML 基线）：

| 字段 | 默认 | 说明 |
|------|------|------|
| `min_interval_sec` | 1.0 | 相邻请求最小间隔（限流） |
| `timeout_sec` | 10 | 单请求超时 |
| `max_retries` | 3 | 失败重试次数 |
| `retry_backoff_sec` | 2.0 | 重试退避基数 |
| `member_update_interval_days` | 7 | 成分快照更新间隔（周频跳过） |

`get_effective_settings()` 每次调用重新合并 YAML ⊕ app_config 覆盖层（不缓存），Web 改参后新建实例即生效。

## CLI（`backend/cli.py`）

`python -m backend.cli board`：
- `--backfill` / `--update`：全量回填 / 增量（默认）
- `--dict` / `--members` / `--bar` / `--fund`：分表只跑指定步骤
- `--codes` / `--type` / `--limit`：指定板块子集 / 板块类型 / 前 N 个小批量
- `--force-members`：绕过成分周频跳过，强制全量拉成分

`daily` 集成：`DailyPipeline.run(board=True)` 每日跑板块增量（`--skip-board` 跳过），板块步骤失败不阻塞后续质检。

## API / 权限矩阵

板块能力贯穿数据管理域与板块行情域，权限分三类（`backend/api/*.py` + `backend/auth/deps.py`）：

| 接口 | 权限 | 用途 |
|------|------|------|
| `GET /api/data/overview`、`/hub` | `data:overview` | 数据概览含板块规模/覆盖/鲜活/问题分项（`_board_stage`） |
| `GET /api/data/boards` | `data:overview` | 板块搜索（采集页「指定板块」下拉） |
| `GET /api/data/stock-quality` 等 | `data:overview` | 逐股/质量口径（板块 issue 按层归类展示） |
| `GET /api/data/quality` | `data-quality:view` | 质检台账（板块 issue 名称从 board_dict/detail 补全，支持板块代码/名称搜索） |
| `POST /api/data/quality/{id}/fix`、`/fix-batch`、`/recover-batch`、`/{id}/reset`、`/{id}/ignore`、`/{id}/restore-monitoring` | `data-quality:fix` | 板块 issue 的修复/批量恢复/复位/按范围忽略/恢复监控 |
| `POST /api/data/tasks`、`GET /tasks/{id}`、`/resume`、`/cancel` | `data-task:manage` | 板块采集任务创建/进度/续跑/取消（`task_type=board`） |
| `GET/POST /api/data/schedules` 及子端点 | `data-schedule:manage` | 板块定时采集任务 CRUD/启停/立即触发 |
| `GET/POST /api/data/settings` | `data-settings:manage` | `ths_board` 配置段读写（限流/超时/成分更新间隔） |
| `GET/POST /api/data/sources`、`/test` | `data-source:test` | 数据源状态含 `ths_board`（`role='board'`） |
| `GET /api/sectors`、`/{code}`、`/{code}/bars`、`/{code}/members` | `sectors:view`（业务授权码） | 板块行情只读（列表/详情/指数/成分） |
| `GET /api/sectors/benchmarks/{index_code}/bars` | `sectors:view`（业务授权码） | 系统配置白名单内的市场指数基准行情，用于板块相对强弱与超额涨跌 |
| `GET /api/sectors/watchlist`、`/watchlist/markets` | `sector-watchlist:view`（业务授权码） | 查看当前用户板块自选及对应行情 |
| `POST /api/sectors/watchlist`、`DELETE /watchlist/{board_code}` | `sector-watchlist:update`（业务授权码） | 幂等加入或移出当前用户板块自选 |

数据管理 router 整体在 `main.py` 挂 `require_system` 硬守卫（system-only）；`sectors` 用 `require_perm("sectors:view")`（普通用户经业务授权可读）。

## 验证矩阵

板块闭环的关键测试文件与覆盖能力：

| 文件 | 覆盖 |
|------|------|
| `backend/tests/test_ths_board_source.py`（24 用例） | 数据源层（mock HTTP 不触网）：v cookie/401 刷新、字典/成分/指数解析、资金流翻页、**资金流空壳页重试与跳过（不截断后续页）**、登录墙/登录态、限流参数注入 |
| `backend/tests/test_board_ingest.py`（22 用例） | 字典/成分/指数/资金流采集、**全周期默认采集与多周期 upsert/append**、只进不出幂等、不完整快照不落库、周频跳过、**ignored 豁免（fund + member）**、fund checkpoint 范围签名与旧格式迁移、update/backfill 语义、留痕、写锁归类、事务原子性 |
| `backend/tests/test_data_mgmt_b.py` 板块用例 | board 任务注册/互斥/续跑/部分失败、force_members 透传、scan_board_quality 扫描与事务替换、**多周期 fund_missing/stale 检查与按周期定向重采**、recheck_clean 复检、末尾连续缺口/逐日缺口/非法值修复边界、无历史数据与已追平兼容、搜索、概览/hub 板块统计 |
| `backend/tests/test_sectors_api.py`（12 用例） | `/api/sectors*` 只读接口、权限、涨幅口径、成分股排序、**多周期净流入字段与排序** |
| `backend/tests/test_board_watchlist.py` | 板块自选归属隔离、幂等增删、失效快照保留 |
| `backend/tests/test_pipeline.py` | `DailyPipeline.run(board=True)` 集成、`--skip-board` |
| `backend/tests/test_ddl.py` | board 四表 DDL、维度注册 |
| 前端 `frontend/src/layout/__tests__/` 等 | 页面契约（按钮/组件/布局规范不因板块改动回归） |

运行命令：`python -m pytest backend/tests/test_board_ingest.py backend/tests/test_data_mgmt_b.py backend/tests/test_sectors_api.py -q`；前端 `cd frontend && npx vitest run`。
