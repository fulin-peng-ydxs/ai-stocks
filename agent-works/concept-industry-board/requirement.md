# 需求文档:板块概念数据采集与展示

> 需求文档版本：2026-08-14（同步页面、MACD、凭证安全与发布验收事实）
> 上游闭环分析：[requirement-closure.md](requirement-closure.md)（已确认）
> 数据源调研：[research.md](research.md)（同花顺主源）
> 评审修订说明：本次修订吸收评审意见——编号冲突重排、上游结论对齐（TopN+展开、返回保留筛选态、统计卡字段）、权限基线修正（`sectors:view` 非登录基线，进业务授权集合 + 既有库回填）、数据口径闭环（6 位板块代码、375/387 并集、涨幅计算口径）、原型合规、验收可执行、配置化闭环、开发顺序补中间里程碑。

---

## 1. 背景与目标

「复盘啦」是 EOD A 股趋势龙头研究系统。以下是**需求提出时的历史基线**：系统已覆盖个股行情、每日榜单、策略筛选、回测、盘感训练等能力，但缺少板块维度数据，`stock_basic.concept` 字段始终 NULL，DDL 无任何板块相关表（见 [research.md](research.md) §1）。截至 2026-08-14，板块采集、查询、列表/详情页面、权限接入与发布验收均已完成；历史基线不代表当前实现状态。

本需求把「同花顺板块概念数据」完整接入系统，实现两个目标：

1. **数据采集**：新增板块字典、板块成分股、板块指数、板块资金流四块数据采集，纳入现有数据采集闭环，接入后与无此数据时**操作无感**——自动随每日流程采集、数据概览自动可见、任务中心可追踪、数据质量可监控。
2. **页面展示**：在「最新行情」菜单下新增子菜单「板块行情」，让投资者直接看板块强弱，支撑「题材 → 板块 → 成分股 → 龙头」的研究链路。

## 2. 当前项目现状

### 2.1 板块数据现状（需求基线与当前校准）

| 维度 | 现状 | 依据 |
|---|---|---|
| `stock_basic.industry` | ✅ 已采集（baostock 证监会行业） | [ddl.py:34](../../backend/storage/ddl.py:34) |
| `stock_basic.concept` | 🟡 保持占位 NULL | 板块关系以 `board_member` 为事实源，不回写冗余字符串 |
| 板块字典/成分股/指数/资金流 | ✅ 已落地 | `board_dict` / `board_member` / `board_bar` / `board_fund_flow` 4 表 |

### 2.2 数据采集闭环（复用基座）

- **异步任务**：[async_task.py](../../backend/services/async_task.py) 已注册 `board` 任务类型并纳入写任务互斥、取消/续跑能力；checkpoint 覆盖字典类型、成分/指数板块代码和资金流类型+周期。
- **采集编排**：[IngestionService](../../backend/services/ingest.py) 已实现板块四阶段编排，[DailyPipeline](../../backend/services/pipeline.py) 已把板块作为默认步骤接入每日流程，并保持失败后继续质检、最终 `ok=false` 的真实状态。
- **数据概览**：[ddl.py](../../backend/storage/ddl.py) 已注册 `board` 维度；[data_admin.py](../../backend/api/data_admin.py) 除维度行外还返回板块 4 表行数、类型数、三类覆盖、最新日期、活跃问题分类和最近更新状态。
- **配置覆盖层**：[environment-configuration.md](../architecture/environment-configuration.md) YAML 基线 ⊕ `app_config` PG 覆盖，消费端用 `get_effective_settings()`。
- **数据源抽象**：[base.py](../../backend/datasource/base.py) `DataSource` + `rate_limited`/`with_retry` 装饰器。板块数据是关系型（非个股时间序列），已按 research.md 附录**单独封装 `ThsBoardSource`**，不进 `_source_for` 选源链。

### 2.3 页面与权限基座

- **菜单与页面**：[pg_ddl.py](../../backend/storage/pg_ddl.py) 已在 `quotes`（最新行情）下 seed `/sectors` 菜单和资源；`/sectors`、`/sectors/:code` 路由及列表、详情、工作台页面均已落地，并通过标准板块 Playwright 入口验证。
- **权限模型**：`sectors:view` 已加入 `BUSINESS_RESOURCE_CODES`，完成既有库一次性回填 + bump `perm_ver`；后端 `/api/sectors*` fail-closed，前端路由守卫、菜单消费和页面按钮权限态均已落地。`sys_menu.visible` 仅 `login|system` 两值。
- **设计规范**：[DESIGN.md](../../DESIGN.md) §5 可配置布局系统，所有 registry 页面走 `<LayoutHost>`；§7.3 组件字段治理；page-registry marker 机器契约。新页面执行流程见 [page-template.md](../configurable-layout-system/page-template.md)。
- **页面登记与实现**：板块列表/详情已登记 pageRegistry 并消费 `<LayoutHost>`；图表主题统一经 `components/chartTheme.ts::useEChartsTheme()` 消费，格式化逻辑复用共享工具。

### 2.4 数据源可用性（已实测，见 [research.md](research.md)）

| 能力 | 同花顺 | 说明 |
|---|---|---|
| 概念板块字典 | ✅ 375（无登录态） | `stock_board_concept_name_ths`，代码 **6 位**（如 309121）；**375 = 无登录态登录墙截断值，配登录 Cookie 后约 390 全量** |
| 行业板块字典 | ✅ 90 | `stock_board_industry_name_ths`，代码 6 位（如 881121） |
| 概念成分股 | ✅ 详情页 AJAX | `q.10jqka.com.cn/gn/detail/code/{code}/page/{n}/ajax/1/` |
| 行业成分股 | ✅ 详情页 AJAX | `q.10jqka.com.cn/thshy/detail/code/{code}/page/{n}/ajax/1/` |
| 板块指数历史 | ✅ 原始连续指数 | `stock_board_concept_index_ths` / `industry_index_ths`，天然无除权跳变 |
| 概念资金流 | ✅ 387 | `stock_fund_flow_concept`（即时/3日/5日/10日/20日） |
| 行业资金流 | ✅ 90 | `stock_fund_flow_industry` |

**关键取数约束**（research.md §2 实测踩坑）：
- **板块采集全部走自封装 `ThsBoardSource`（直连同花顺 `q.10jqka.com.cn` / `data.10jqka.com.cn`），不调用 akshare 公开函数**；akshare 仅调研验证时用于探测数据可用性，生产实现按相同 URL/参数自行请求解析。
- 同花顺详情页必须带 `v` cookie（复用 akshare 打包的同花顺 `ths.js` 反爬校验脚本，经 `py_mini_racer` 执行生成，非调用 akshare 板块接口），否则 401。
- **登录态 Cookie（2026-08-14 安全收口）**：详情页/字典翻页第 6 页起会命中登录墙，提供登录 Cookie 可解除登录墙取全深页板块与完整成分股。系统管理员可从页面配置，`app_config` 只保存带版本前缀的加密密文，接口仅回显掩码及 `未设置 / 可用 / 无法解密` 状态，审计 before/after 固定脱敏；密钥缺失、错误或密文损坏时运行态跳过 Cookie，管理页面必须明确提示不可用并允许重新加密覆盖或清除。环境变量/受控文件可优先覆盖，YAML 禁止配置。历史明文有主密钥时原位加密、无主密钥时删除；疑似暴露过的 Cookie 必须在同花顺侧轮换。
- 翻页是路径参数 `page/N/ajax/1/`，不是 URL query。
- 排序参数敏感：部分板块带 `field/199112/order/desc` 才能取全，部分不带反而更多。鲁棒策略：两种都试、取多者。
- 板块指数原始连续、无除权概念，直接展示原值；页面周期切换只改变查看区间，不代表复权处理，也不存复权字段。

**双代码体系（2026-08-08 用户手机核实）**：同花顺概念板块有**路径 code（30xxxx，如 AI PC=309121）**与 **App clid（88xxxx，如 AI PC=886071）**两套代码。Web/资金流/分类页跳转与取数统一用路径 code；clid 是手机 App 内部代码（概念板块详情页隐藏字段，88 开头唯一；行业板块 clid=路径 code）。主键用路径 code，`app_code` 存 clid 供用户与手机 App 核对。概念资金流接口只返回名称无代码，映射按名称匹配。

### 2.5 板块字典与资金流集合差异（评审新增）

实测概念字典 375 个（**无登录态登录墙截断值，配登录 Cookie 后约 390**）、概念资金流 387 个——**资金流源含字典没有的板块**（无成分股/无指数，仅资金流）。**当前口径（2026-08-10 修订）**：资金流源板块单元格带链接含真实路径 code（如 `/gn/detail/code/308734/`）即稳定主键，此类独有板块**可补进 `board_dict`**（`has_fund_flow=true`、`has_members/has_bar=false`，列表页不展示，供资金流数据关联）；仍无稳定代码的未匹配项写 `board_fund_unmatched` 质检（见 R1/R4）。

## 3. 用户角色与使用场景

| 角色 | 板块数据权限 | 板块数据场景 |
|---|---|---|
| 普通用户 | 已登录且被授予 `sectors:view`（业务授权集合） | 看板块涨幅榜/资金流、进详情看成分股与指数走势、跳个股行情 |
| 租户管理员 | 同普通用户（**无数据管理权限**） | 同上；不可见采集/任务/概览（数据管理 `visible=system`） |
| 系统管理员 | 全部 + 数据管理 | 在数据采集页触发板块采集/回填、任务中心看进度、数据概览看板块维度、质检处置 |

**典型场景**：
- 场景 A（题材轮动）：用户进「板块行情」→ 切「概念板块」→ 按 5 日涨幅排序 → 发现「AI PC」连续走强 → 点进详情 → 看指数走势确认趋势 → 看成分股选出龙头 → 跳个股行情。
- 场景 B（资金面验证）：用户进板块列表 → 看「即时净流入」列 → 找到「价涨 + 资金净流入」的板块 → 进详情验证。
- 场景 C（系统运维）：系统管理员在数据采集页跑「板块回填」→ 任务中心看进度 → 数据概览看板块维度已 collected。

## 4. 功能范围

### 4.1 必须实现

| 需求编号 | 需求项 | 来源/依据 | 验收意图 |
| --- | --- | --- | --- |
| R1 | 板块字典采集（概念+行业并集）落 `board_dict` | 闭环 A1 | 字典完整、能力字段正确、幂等 |
| R2 | 板块成分股快照采集落 `board_member`（只进不出：`(board_code, code)` 单行累积） | 闭环 A2 | 成分关系可查询、完整性即闸门、可重采 |
| R3 | 板块指数采集落 `board_bar`（同花顺原始连续指数） | 闭环 A3 | 指数日线完整、原值存储 |
| R4 | 板块资金流采集落 `board_fund_flow`（概念+行业，多周期） | 闭环 A4 | 资金流数据可展示、并集映射无伪造代码 |
| R5 | 板块采集异步任务（`board` 类型进任务中心） | 闭环 A5 | 可创建/看进度/取消/续跑 |
| R6 | 板块维度注册 + 数据概览可见 | 闭环 A6 | 数据概览出现「板块数据」维度 |
| R7 | 板块行情列表页 `/sectors` | 闭环 B1 | 板块类型筛选、排序、资金流列、分页 |
| R8 | 板块详情页 `/sectors/:code` | 闭环 B3 | 指数走势图、统计卡、成分股表（统一分页） |
| R9 | 成分股跳转个股详情（权限感知） | 闭环 B4 | 有权限可跳、无权限禁用链接 |
| R10 | 板块搜索 | 闭环 B2（本次纳入） | 名称搜索过滤 |
| R21 | 采集流程集成（daily 自动采集、回填/增量分流、失败不阻塞、断点续跑、部分失败降级） | 评审新增（承接四条笼统 R1-R10） | 板块采集无感融入每日流程 |
| R22 | 页面/RBAC 接入（菜单/资源 seed、`sectors:view` 授权回填 + bump `perm_ver`、路由守卫、pageRegistry 登记） | 评审新增（承接权限/页面闭环；返回筛选态归 R8） | 板块页面可访问、权限正确 |
| R23 | 页面配置闭环（偏好 key/PG 保存/读取/消费/回退、组件字段契约、视口验收、构建） | 评审新增（承接配置化/验收） | 页面设置可持久、回退正常 |
| R26 | 板块原始连续指数 MACD 副图 | 2026-08-14 页面能力扩展 | 列表 K 线模式与详情可选 MACD；标题明确“原始连续指数”，指标与统一 MACD 定义同口径 |

### 4.2 建议实现

| 需求编号 | 需求项 | 来源/依据 | 纳入条件 | 处理状态 |
| --- | --- | --- | --- | --- |
| R11 | 板块指数统一 K 线范围（近 60/120/250 日/全部）与图表高度拖拽 | 对齐个股详情的行情阅读体验 | 全局范围选择 + 复用行情多图工作区 | 本次纳入 |
| R12 | 板块维度数据质量校验（指数缺口；成分波动已移除） | 闭环 A7 | 复用 `data_quality_issue` | 本次纳入（2026-08-09 修订） |
| R13 | 详情页成分股统一分页（无 TopN 展开，`AppPagination` 默认 20） | 用户要求改项目统一分页 | 本次纳入 |
| R14 | 板块资金流统计卡（净流入额） | 闭环 B3 详情页 | 展示层数字 | 本次纳入 |

### 4.3 暂不实现

| 需求编号 | 需求项 | 不做原因 | 后续触发条件 |
| --- | --- | --- | --- |
| R15 | 地域/风格板块 | 用户确认第一期只做概念+行业 | 用户需要地域/风格维度时 |
| R16 | 板块资金流历史趋势图（多日净流入） | 第一期只做统计卡数字 | 需要资金面趋势分析时 |
| R17 | 题材联动图谱 / 板块重叠分析 | 复杂跨板块分析 | 需要板块间联动研究时 |
| R18 | 东财板块指数交叉验证 | 东财 push2 源不稳 | 东财恢复稳定时 |
| R19 | 板块成分作为筛选/回测条件 | 需筛选引擎扩展 + 回测层标注 | 板块接入回测联动时 |
| R20 | 板块强弱热力图 | 需图表组件扩展 | 需要全市场板块一屏总览时 |
| R24 | 审计可靠性提升（持久化 outbox/重试/对账） | 项目现无 outbox 设施，本期审计 best-effort | 需要审计不丢失时 |

## 5. 详细功能需求

### R1 板块字典采集

- **功能描述**：采集同花顺概念 + 行业板块字典并集，落 `board_dict`。
- **前置条件**：`ThsBoardSource` 可用；DuckDB 写锁可用。
- **操作流程**（两阶段，避免采集顺序循环）：
  1. **阶段一 · 字典 seed**：`ThsBoardSource.get_board_dict('concept')` + `get_board_dict('industry')` → 幂等 upsert 概念/行业字典（此时能力字段仅 `has_members/has_bar` 按各自接口判定，`has_fund_flow` 暂置 false）。
  2. **阶段二 · 资金流补充并集**：资金流采集（R4）后，按名称匹配已有字典板块并更新 `has_fund_flow` 能力字段。**资金流独有板块的字典策略（当前口径，2026-08-10 修订）**：资金流源板块单元格带链接含真实路径 code（如 `/gn/detail/code/308734/`），此类独有板块**有稳定主键可补进 `board_dict`**（`has_fund_flow=true`、`has_members/has_bar=false`，列表页不展示）；仍无稳定代码（无链接 code 且名称匹配不到字典）的板块写 `board_fund_unmatched` 质检、不伪造代码（见 R4）。
  3. **能力字段收口**：全部源采集完成后，按实际各接口返回刷新 `has_members/has_bar/has_fund_flow` 与 `last_seen_at`；最近一次完整成分快照成功应用后同步刷新 `member_count` 与 `member_snapshot_at`。板块列表/详情的当前成分数取该完整快照口径；成分明细接口的 `total` 为只进不出累计关系数，两者不得混用。
- **输入输出**：输入板块类型枚举 `concept|industry`；输出写入行数。
- **校验规则**：
  - `board_code` 唯一，同花顺**路径 code**（概念 30xxxx / 行业 88xxxx），所有取数接口/跳转统一用它。
  - `app_code` 存同花顺 **App clid**（概念 88xxxx，如 AI PC=886071；行业 clid=路径 code），逐板块详情页抓取，供用户与手机 App 核对。
  - `board_type ∈ {concept, industry}`；名称非空。
  - `source` 恒为 `ths`（来源系统，非数据能力标记）。
  - 能力字段：`has_members` / `has_bar` / `has_fund_flow`（各接口是否返回该板块）；`member_history_start_date`（成分快照首次完整采集日）；`last_seen_at`。
- **异常情况**：单源失败记日志，不中断整体采集。
- **权限与数据范围**：system-only。
- **对现有功能影响**：无；新增表与采集步骤。

### R2 板块成分股快照采集

- **功能描述**：逐板块分页取同花顺成分股（AJAX 翻页 + v cookie），落 `board_member`。**只进不出**：每只成分股一行，`(board_code, code)` 主键，只插入不删除、不做 diff、不记候选。
- **前置条件**：`board_dict` 已采集；`ThsBoardSource` 可用。
- **操作流程**：对每个板块 → `get_board_members(code)`（两种排序策略取多者）→ **完整快照**（`complete=True`）时对快照内每个 code 执行 `INSERT ... ON CONFLICT (board_code, code) DO NOTHING`——已在表内的不动、新出现的插入；同步刷新 `board_dict.member_count`（当前成分数）。
- **只进不出语义**：表 = 该板块**所有曾经进入过的成分股**累积。退出的股票**永远保留在表内**（不标记退出、不删除），不做逐次快照 diff。重采天然安全——完整快照只新增不覆盖，缺了某股也不影响既有行。
- **🔴 完整性即闸门（成功/失败判定）**：单板块分页不完整（登录墙/翻页失败/401）或请求异常时，`get_board_members` 返回 `complete=False` → **整趟快照不落库**，`data_update_log` 记 failed 待重采；已采集的旧数据原样保留，不受失败影响。**不做 diff 比对、不做波动阈值判断**——成分波动是源端真实重组，不是数据错误。
- **🔴 更新间隔（周频，2026-08-10 新增）**：成分股不随每日增量更新，按 `member_update_interval_days`（默认 7 天，系统设置「同花顺板块·成分快照更新间隔」可配）跳过未到期板块。默认模式只重拉「**上次完整快照距今 ≥ 间隔**」或「**从未完整落库**（`member_snapshot_at IS NULL`）」的板块；未达间隔的板块记 `skipped` 跳过——不计失败、不打 `data_update_log` failed、不写 `board_member_incomplete` 质检。**跳过 ≠ 失败**，周频不会产生虚假质量问题。`force=True`（质量修复重采、`backfill` 初始化、CLI `--force-members`）绕过间隔直接全量拉。
- **可重采性**：数据质量页「重采」= 重新拉该板块完整快照（`force=True` 绕过周频），`complete=True` 则 `ON CONFLICT DO NOTHING` 合并新增；不完整则不落库。既有数据永不因重采而丢失。
- **输入输出**：输入板块代码；输出本次快照新增成分股数（成功）或失败原因。
- **校验规则**：成分股 6 位代码补交易所后缀对齐 `stock_basic.code`；PK `(board_code, code)`。
- **异常情况**：单板块失败跳过记日志（`data_update_log` failed + 失败清单），不中断整体采集。
- **权限与数据范围**：system-only。
- **对现有功能影响**：无。

### R3 板块指数采集

- **功能描述**：采集同花顺板块指数日线（原始连续指数），落 `board_bar`。首次全量回填源端可用年限（2026-08-09 实测 `d.10jqka.com.cn/v4/line` 指数历史**仅保留近 3 年**，2024 起、2021-2023 返回 404；各板块起始日不同属正常，按各自最早可用日回填），每日增量。
- **前置条件**：`board_dict` 已采集。
- **操作流程**：`get_board_bar(code, start, end)` → 幂等 upsert `board_bar`。
- **校验规则**：PK `(board_code, trade_date)`；**存原值，不套个股复权链**（板块指数无除权）。
- **异常情况**：单板块失败跳过。
- **权限与数据范围**：system-only。
- **对现有功能影响**：无。

### R4 板块资金流采集

- **功能描述**：采集同花顺概念 + 行业资金流排行，落 `board_fund_flow`。采集「即时/3日/5日/10日/20日」全部周期；列表默认展示即时净流入，其余周期通过列显隐按需展示。
- **前置条件**：`board_dict` 已采集。
- **操作流程**：`get_board_fund_flow(board_type, period)` → 与字典按**同花顺稳定板块代码**关联 → 幂等 upsert。
- **🔴 并集映射规则**：
  - 资金流源含字典没有的板块（375 vs 387）：先按名称匹配已有字典板块关联；链接带真实路径 code 的独有板块补进字典（见 §2.5）；
  - 仍无稳定代码（无链接 code 且名称匹配不到字典）的板块，写 `board_fund_unmatched` 质检问题，**不生成伪造代码、不新增字典行**。
- **输入输出**：字段含流入/流出/净额/领涨股等。
- **校验规则**：PK `(board_code, snapshot_date, period)`；净额 = 流入 - 流出 校验。
- **异常情况**：失败记日志。
- **权限与数据范围**：system-only。
- **对现有功能影响**：无。

### R5 板块采集异步任务

- **功能描述**：新增 `board` 任务类型进任务中心，支持创建/进度/取消/续跑。
- **前置条件**：`async_task` 基座。
- **操作流程**：`async_task.py` 注册 `board` → `TASK_TYPES` + `WRITE_TASK_TYPES` + `TASK_CAPABILITIES`（可取消/可续跑，checkpoint 按字典类型、成分/指数板块代码、资金流类型+周期）→ handler `_h_board` → `IngestionService.ingest_board(ctx)`；部分失败保留成功 checkpoint，任务标 failed 后仍可续跑未成功工作单元。
- **异常情况**：复用现有任务失败/中断/续跑机制。
- **权限与数据范围**：system-only。
- **对现有功能影响**：任务中心自动出现「板块采集」任务类型。

### R6 板块维度注册 + 数据概览

- **功能描述**：`data_dimension_registry` 加 `board` 维度（status=collected，tables=board_dict/board_member/board_bar/board_fund_flow），数据概览出现「板块数据」维度，并在概览/闭环图展示板块规模、覆盖、鲜活度、未闭环问题和最近采集状态。
- **操作流程**：`ddl.py` `_DIMENSION_SEED` 加行 + seed 幂等；数据管理概览聚合 4 表行数、概念/行业数量、成分/指数/资金流覆盖、指数/资金流最新日期、`board_index_gap`/`board_member_incomplete`/`board_fund_unmatched` 活跃问题与最近更新记录，并提供前往板块采集入口。
- **对现有功能影响**：数据概览「数据资产表」多一行，并新增板块数据统计卡/闭环环节，不改变既有维度口径。

### R7 板块行情列表页 `/sectors`

见 §7.1 页面 P1。

### R8 板块详情页 `/sectors/:code`

见 §7.2 页面 P2。

**返回列表保留筛选态**：
- **保存状态**：板块范围（全市场/自选）、板块类型（全部/concept/industry）、交易日期、排序字段与方向、搜索关键词、页码。
- **承载方式**：列表页筛选态写入 **URL query**（`?scope=&type=&date=&sort=&order=&keyword=&page=`，默认值省略）；**进入详情时把当前列表 query 一并带入详情 URL**，刷新详情后返回仍可还原。不依赖内存态。
- **行为规则（两类分别处理、分别验收）**：
  1. **面包屑 / 页面返回按钮**：**始终显式跳转** `router.replace({ path: '/sectors', query: validatedSourceQuery })`——`validatedSourceQuery` 是详情 URL query 中经白名单校验通过的筛选参数（`scope/type/date/sort/order/keyword/page`）；**无来源 query 或非法 query 时 query 为空对象**，落到默认列表（全市场 + 全部板块 + 最新交易日 + 今日涨幅降序）。**不使用 `router.back()`**。
  2. **浏览器原生后退/前进**：遵循浏览器 history 栈——详情 URL 携带来源 query，原生返回按 history 还原，不做额外拦截。
- **承载表**：列表页在 URL 变更时同步更新 query；详情页仅透传来源 query、不持有独立筛选态。
- **纳入 R8 验收**：面包屑/返回按钮在有/无来源 query 下均显式跳列表并正确还原或落默认；浏览器原生后退按 history 还原；均纳入 Playwright 用例。

### R9 成分股跳转个股详情（权限感知）

- **功能描述**：板块详情页成分股行点击跳 `/stocks/:code`。**权限感知**：用户有 `stocks:view` 时行可点击跳转；无 `stocks:view` 时成分股数据仍可见，但名称/代码渲染为**不可点击文本 + hover 提示「无个股行情查看权限」**，不执行路由跳转。
- **直接访问保护**：用户直接输入 `/stocks/:code` 时，路由守卫和接口守卫保持 fail-closed（现有机制，不新增）。
- **操作流程**：前端 `hasPermission(auth, 'stocks:view')` 判定行可点性。
- **异常情况**：跳转后目标页面按现有个股页四态处理。
- **权限与数据范围**：列表可见需 `sectors:view`；跳转需 `stocks:view`。

### R10 板块搜索

- **功能描述**：列表页按板块名称搜索过滤。
- **操作流程**：**自由文本搜索框（`el-input` + 防抖，非 `AppFilterSelect`）**输入名称 → 服务端查询带 `keyword` 参数。
- **异常情况**：无结果空态。

### R11 板块指数统一范围与高度调整

- **功能描述**：详情页复用个股行情统一的 K 线范围（近 60/120/250 日/全部），展示原始连续指数；K 线与量能之间可拖拽分隔线调整高度。
- **实现**：列表与详情统一将 `KlineRangeSelect` 作为数据和横向缩放的硬边界；近 60/120/250 日精确保留末尾对应交易点，缩放条只能在该周期内查看，只有“全部”加载完整历史。多板块走势与所选市场指数按同一组交易日对齐截断。**走势对比改为多口径对比（2026-08-13 修订）**：头部指标槽即切换器，趋势类指标（累计涨跌/单日涨跌/5日/10日/20日涨幅）以折线叠加，可切中证 500/沪深 300/不对比指数并悬浮展示相对指数超额；截面类指标（即时净流入/涨跌家数）只有最新快照、无法回溯，以柱状对比且不叠加指数；累计涨跌支持「区间首日」与「近一年」两种基期，近一年基期锁死横向范围为 250 交易日。展示哪些槽与默认指标在页面设置抽屉配置。详情复用 `StockChartWorkspace` 呈现 K 线与量能，通过中间分隔线调整并保存高度比例。

### R12 板块维度数据质量校验

- **功能描述**：板块指数缺口扫描，写 `data_quality_issue`。
- **🔴 成分数波动不再质检（2026-08-09 修订）**：改为「只进不出」成分模型后，成分数变化是源端真实重组、非数据错误，**删除 `board_member_wave` 波动扫描与 `member_surge_shrink` 候选恢复机制**（见 R2 修订）；成分采集的完整性由采集层「完整快照才落库」保证（见 R2 完整性即闸门）。
- **指数缺口**：`board_bar` 最近交易日滞后于 `daily_bar` 全局最新交易日 → 写 `board_index_gap`，阈值配置化。
- **状态流转**：复用 `data_quality_issue` 真实枚举 `open → fixing → resolved`，另有 `ignored`。
- **实现**：复用 `data_report.py` 质检扫描，保留板块指数缺口规则。

### R13 详情页成分股统一分页

- **功能描述**：详情页成分股表**直接统一分页**（`AppPagination`，默认每页 20，抽屉可配），**无 TopN 展开/收起**——与项目其它列表分页模式一致。
- **实现**：`GET /api/sectors/{code}/members?page=&size=`（`size` 默认 20，抽屉 `pageSize` 可配 10/20/30/50）。

### R14 板块资金流统计卡

- **功能描述**：详情页摘要卡展示净流入额（最新交易日即时净流入）。
- **实现**：`board_fund_flow` 最新 snapshot_date 的 period='即时' 查询。

### R21 采集流程集成（daily / 回填 / 断点）

- **功能描述**：板块采集作为独立步骤纳入每日流程与 CLI/任务中心，与既有采集无感协同。
- **前置条件**：阶段二适配器与 DDL 就绪。
- **操作流程**：
  - **`DailyPipeline.run()` 新增 `board: bool = True` 参数**（默认采集板块，对齐现有 `quality: bool = True` 模式）。`run(skip_update, board=True, ...)`：**`skip_update=True` 时仍采集板块**（板块独立于行情更新，互不影响）；板块步骤在「更新数据」之后顺序执行（pipeline.py 现有 `step()` 顺序模型）。
  - **CLI `daily` 新增 `--skip-board`**：跳过板块步骤（对齐 `--skip-update` 语义）；`total_steps` 同步计入板块步骤（`(1 if not skip_update else 0) + (1 if board else 0) + ...`），避免进度异常。
  - **失败隔离语义（明确）**：板块步骤失败 → **不提前 return**（继续执行后续质检等步骤），但 `DailyPipeline` 最终 `ok=false`（pipeline.py:102 `ok = all(...)`）。「不阻塞」指**不阻断行情更新主流程执行**（板块是增强数据，其失败不污染已完成的更新步骤），而非任务整体成功。CLI/任务中心的「板块采集」失败会标 failed，可续跑。
  - CLI 新增 `board` 命令族：`board --backfill`（全量回填指数历史 + 首次成分快照 + 资金流全周期）、`board --update`（增量）。
  - 异步任务 `board` 类型：可取消/续跑；字典按 `board_type`、成分/指数按 `board_code`、资金流按 `board_type + period` 记录 checkpoint，断点续跑跳过已成功工作单元。
  - 单板块失败时记录失败板块并继续处理剩余板块；完成遍历后该采集步骤和对应异步任务最终标 `failed`，DailyPipeline 最终 `ok=false`，同时返回失败板块清单与断点，续跑仅重试失败项。
- **输入输出**：输入可选 board_type/board_code；输出各步骤写入行数。
- **异常情况**：整体失败直接标 `failed`；部分板块失败不提前中断，但步骤/任务最终仍标 `failed` 并保留失败清单，可针对失败项续跑。
- **权限与数据范围**：system-only。
- **对现有功能影响**：`async_task.TASK_TYPES`/`TASK_CAPABILITIES` 加 `board`；`pipeline.py` 加步骤；`cli.py` 加命令；`data.ts` 加任务中文标签。

### R22 页面/RBAC 接入

- **功能描述**：`/sectors` 与 `/sectors/:code` 页面、菜单、资源、权限守卫与 pageRegistry 登记，含 `sectors:view` 业务授权回填。
- **前置条件**：阶段四接口就绪。
- **操作流程**：
  - 菜单 seed：`_SEED_MENU_TREE` 在 `quotes` 下加「板块行情」子菜单（`/sectors`，`visible=login`）。
  - 资源 seed：`_SEED_RESOURCES` 加 `sectors:view`（GET `/api/sectors*`），挂 `/sectors` 菜单。
  - 业务授权：`sectors:view` 加入 `auth/constants.py::BUSINESS_RESOURCE_CODES`，新库随 seed 授予 normal/tenant_admin；**既有库一次性回填授权 + 同事务 bump `perm_ver`**（沿用 asset-publish-open 迁移模式，marker 幂等）。
  - 路由：`router/index.ts` 加 `/sectors`、`/sectors/:code`。
  - pageRegistry：`sectors`/`sectors-detail` 登记（见 §7）。
  - 返回筛选态：R8 的「来源 query 带入详情 URL」由列表/详情页路由实现。
- **异常情况**：无授权用户 → 菜单不可见 + 路由守卫 fail-closed + 接口 403。
- **权限与数据范围**：`sectors:view` 登录后可授；采集侧仍 system-only。
- **对现有功能影响**：菜单树、资源表、业务授权集合扩展；既有库需回填。

### R23 页面配置闭环

- **功能描述**：列表/详情页业务偏好（`usePageSettings`）与组件字段（`layout_user_config`）的保存/读取/消费/回退闭环，及构建/布局/视口验收。
- **前置条件**：阶段五页面实现。
- **操作流程**：
  - 列表页 `usePageSettings('sectors', {defaultType, defaultScope, defaultChartMode, benchmarkCode})` + `consumedComponentFields`（pageSize/defaultSort/hiddenColumns）。
  - 详情页范围直接复用全局 `useKlinePrefs`，不再维护页面私有周期偏好；成分表设置走 `memberTable` 组件字段。
  - 设置抽屉「恢复默认」：同时重置业务偏好（`reset()`）与组件字段（`resetLayout`）。
  - 非法偏好值回落默认并提示；URL query > 已保存偏好 > 默认值优先级。
- **异常情况**：偏好读取失败回落默认；恢复默认覆盖全部。
- **权限与数据范围**：登录用户本人偏好；组件字段走 `layout_user_config`（user 层）。
- **对现有功能影响**：新增两个 pageKey 的布局配置与偏好持久化。

### R26 板块原始连续指数 MACD 副图

- **功能描述**：板块列表 K 线模式和板块详情复用 `StockChartWorkspace` 的可选 MACD 副图，参数固定为统一指标定义的 12/26/9。
- **数据口径**：直接消费 `board_bar` 原始连续指数收盘序列，不做股票复权；K 线与 MACD 标题均显示“原始连续指数”，不得显示“前复权”。
- **交互与异常**：图表二/图表三通过共享 `StockChartSettingSection` 配置；MACD 局部加载失败或预热不足不阻断 K 线与量能。
- **验证**：指标数值与 `compute_macd` 对齐；Vitest 与板块聚焦 Playwright 同时断言标题、可见性和设置切换。

## 6. 数据与接口需求

### 6.1 表设计（DuckDB）

```
board_dict        板块字典（概念+行业并集）
  board_code PK         -- 同花顺路径 code（概念 30xxxx / 行业 88xxxx），作主键；所有取数/跳转统一用它
  app_code              -- 同花顺 App 内部代码（概念 clid 88xxxx，如 AI PC=886071；行业 clid=路径 code），供用户与手机 App 核对
  name, board_type      -- concept / industry
  source                -- 'ths'（来源系统）
  has_members           -- 是否有成分股数据
  has_bar               -- 是否有板块指数
  has_fund_flow         -- 是否有资金流
  member_count         -- 最近一次完整快照的当前成分数，供板块列表/详情展示
  member_snapshot_at   -- 最近一次完整成分快照成功应用时间；不完整采集不得刷新
  member_history_start_date -- 成分快照首次完整采集日（板块级，见 R2/R19）
  last_seen_at          -- 最近一次在任意源出现
  updated_at

board_member      板块成分股（多对多，只进不出）
  board_code, code    -- PK(board_code, code)，每行一只成分股，累积不删除
  -- 完整快照 INSERT ON CONFLICT DO NOTHING（在表不动、新增插入）
  -- 不完整快照整趟不落库（见 R2 完整性即闸门）

board_bar         板块指数日线（原始连续指数）
  board_code, trade_date, open/high/low/close, volume, amount  -- PK(board_code, trade_date)

board_fund_flow   板块资金流
  board_code, snapshot_date, period, inflow, outflow, net_inflow,
  net_ratio, leader_stock, leader_pct  -- PK(board_code, snapshot_date, period)
  -- period ∈ {即时, 3日, 5日, 10日, 20日}（全部采集，页面默认即时、其余周期按列配置展示）
```

`stock_basic.concept` 不硬塞字段，由 `board_member` 反向关联查询。

### 6.2 后端接口

| 接口 | 方法 | 权限 | 说明 |
|---|---|---|---|
| `/api/sectors` | GET | `sectors:view` | 板块列表（日期/类型/排序/分页/搜索） |
| `/api/sectors/{code}` | GET | `sectors:view` | 板块详情（摘要+能力字段，含指定交易日） |
| `/api/sectors/{code}/bars` | GET | `sectors:view` | 板块指数区间序列（周期参数） |
| `/api/sectors/{code}/members` | GET | `sectors:view` | 成分股统一分页（`page`/`size`，size 默认 20） |
| `/data/tasks` (board) | POST | `data-task:manage` | 板块采集任务（复用现有） |

**接口契约要点**（评审新增）：
- **参数白名单**：`/api/sectors` 允许 `trade_date`（可选，指定交易日；缺省=最新交易日）、`board_type(concept|industry)`、`sort_by`（**稳定字段码**：`pct_today|pct_5d|pct_10d|pct_20d|net_inflow|up_count`，中文标签仅 UI 层映射）、`order(asc|desc)`、`keyword`、`page`、`size`；未知参数拒绝。
- **响应字段**：板块名、**路径 code + App code(clid)**、类型、成分数、今日/5日/10日/20日涨幅、即时净流入及数据日期、领涨股、能力字段、`trade_date`（本次查询实际生效交易日）。
- **日期口径**：`trade_date` 指定时，涨幅/成分数/净流入均按该交易日截面计算（`board_bar`/`board_member`/`board_fund_flow` 按 `trade_date <= D` 最近有效值）；缺省=最新交易日。
- **用户可见统计口径**：今日涨幅按板块最近交易日收盘价相对上一交易日收盘价计算；5/10/20 日涨幅分别按最近交易日收盘价相对 5/10/20 个交易日前收盘价计算，历史不足时显示「—」，不得缩窗代算。上涨/下跌家数按该交易日有效成分股的个股 `close` 与 `pre_close` 比较；平盘、停牌或缺少有效行情不计入上涨/下跌。领涨股取同一行情交易日有效成分股中 `pct_chg` 最大者，停牌、缺收盘或缺有效前收者排除；同涨幅按成交额降序、股票代码升序稳定决胜。成分股总数仍按最近完整源快照统计。
- **最新交易日口径**：涨幅、上涨/下跌家数和领涨股基于用户所选或 `board_bar` 最近交易日；资金流基于 `board_fund_flow` 最近 snapshot_date；两处日期在响应中显式返回。资金流源自带 `leader_stock/leader_pct` 仅保留原始数据，不作为页面领涨股。
- **空值处理**：无 `board_bar` 的板块涨幅列为空；无资金流则净流入列为空；页面按空值显示「—」。
- **错误码**：404 板块不存在；400 非法参数；403 无权限。
- **排序字段契约**：`sortFields` 登记 `pct_today/pct_5d/pct_10d/pct_20d/net_inflow/up_count` 等字段码并接入 `defaultSort`；接口 `sort_by` 与 `sortFields` 字段码一致（中文仅 UI 展示）。

### 6.3 数据一致性

- 每日流程 `ingest_board` 在「更新数据」之后**顺序执行**，板块步骤失败隔离（不阻塞行情更新主流程）。
- 板块采集写 DuckDB 自动纳入 `WRITE_TASK_TYPES` 互斥。
- 成分股完整快照落库在单次任务内原子完成（`INSERT ON CONFLICT DO NOTHING`），避免并发写。
- 不完整快照整趟不落库（R2 完整性即闸门）。

## 7. 页面与交互开发需求

### 7.1 页面 P1：板块行情列表页

- **对应需求编号**：R7、R10
- **页面类型**：新增页面
- **页面入口**：「最新行情」→「板块行情」`/sectors`
- **原型文件**：`prototypes/sector-board.html`
- **页面布局**：
  - 布局事实源：对齐 `prototypes/sector-board.html`
  - 页面区域：
    - action 区：页面标题、设置入口、全市场/自选分段、板块类型、交易日期和名称搜索。
  - main 区：左侧板块排行宽表，右侧当前板块走势/K 线分析；列表与图表同屏联动。用户通过排行标题右上角的固定切换按钮收起右侧分析区，进入全宽“仅看排行”状态；展开按钮仍保持在原位置，避免操作入口跳动。
  - 主次关系：板块排行负责选择观察对象，图表负责走势分析；收起分析区时排行独占主区，重新展开保留观察对象、对比队列和图表模式。
  - 核心模块与数据区：默认排行表列 = 板块（名称下方合并类型/成分数）| 今日涨幅 | 5日涨幅 | 10日涨幅 | 即时净流入（标准同行表头标数据日）；20日涨幅与3/5/10/20日净流入可在页面设置中启用。所有列宽由全局 `AppTableColumn` 综合语义、表头长度、排序/筛选控件、可选 `header-meta` 和主内容前置控件推导，标准表头保持单行并与主内容对齐，页面不声明私有宽度。当前观察摘要展示今日/5/10/20日涨幅、即时净流入和涨跌家数。
  - **排序口径（2026-08-12 修订）**：排序走通用**列头排序** + `defaultSort` 配置（对齐 StocksView，sortable 列 = 各涨跌幅/各周期净流入/上涨家数，默认今日涨幅降序）。**不单设「主排序周期」控件**——周期属列自身口径、与列头排序重复；详情页范围统一走 `KlineRangeSelect`。涨幅和净流入使用完整列名区分，资金列标注独立快照日期。
  - **行交互口径**：点击行或名称切换当前观察板块，勾选框只管理附加对比；「查看详情」按钮进入当前板块详情。
  - 弹窗/抽屉/设置入口：标题旁 `HelpTip` 承载涨幅/资金口径和操作指引；`PageSettingsDrawer` 承载布局、组件设置和业务选项。
  - 关键状态与退化：empty→引导去采集页；error→`AppStateBlock` 重试；loading→`v-loading`；无权限→permission 无权态；列总宽超过排行区域时由 `wide-table` 提供横向滚动。
- **数据来源**：`/api/sectors`（join board_dict + board_bar 涨幅 + board_fund_flow 即时净流入 + board_member 成分计数）。
- **权限与可见性**：`sectors:view`（业务授权集合，非登录基线）。
- **组件复用与通用能力**：
  - 已有通用能力：`AppDataTable`/`AppTableColumn`/`AppPagination`/`AppStateBlock`/`AppRowActions`/`PageSegmented`/`PageSettingsDrawer`、`usePageSettings`/`useRemoteLayoutConfig`/`getPageLayout`、`pageRegistry`、组件配置字段。
  - 新增通用能力：无；复用并正式纳管既有 `chart.minHeight` 能力，数值字段由 `ComponentAutoSettings` 统一渲染。
  - 配置化承载：`sectors` pageKey 进 `pageRegistry`；组件字段走 `COMPONENT_FIELD_DEFS`；默认类型、范围、图表模式、对比指数和分析区展开状态作为页面业务偏好走 `usePageSettings`。

**配置项定义（列表页，谁保存/谁读取/谁消费/如何回退）**：

| 配置项 | 保存位置 | 读取点 | 消费点 | 默认值 | 合法值 | 非法值处理 | 回退 |
|---|---|---|---|---|---|---|---|
| 业务偏好对象 `{ defaultType, defaultScope, defaultChartMode, benchmarkCode, showAnalysisPanel }` | PG `user_preference`（`usePageSettings('sectors', defaults)` → `scope='page' + page_key='sectors' + pref_key='settings'` 一个对象） | 页面加载 `usePageSettings` 的 `settings` | 列表页默认类型、默认范围、默认图表模式、默认对比指数和分析区展开状态 | 全部板块 / 全市场 / 走势对比 / 中证 500 / 展开 | 已登记枚举与布尔值；自选默认受权限约束 | 非法值回落默认；无自选权限强制全市场 | 设置抽屉「恢复默认」调 `reset()` 置回默认对象 |
| 每页条数 `pageSize` | PG `layout_user_config`（sectors 页 wide-table slot） | `componentValueOf('table','pageSize')` | `AppPagination` | 20 | 20/50/100/200（全局 `PAGE_SIZE_OPTIONS`，2026-08-11 与通用组件一致） | 回落 20 | 设置抽屉恢复默认 |
| 默认排序 `defaultSort` | PG `layout_user_config`（同上） | `componentValueOf('table','defaultSort')` | 主表列头排序 | `pct_today:desc` | sortFields 字段码 + asc/desc | 回落 `pct_today:desc` | 设置抽屉恢复默认 |
| 列显隐 `hiddenColumns` | PG `layout_user_config`（同上） | `componentValueOf('table','hiddenColumns')` | 主表列渲染 | 隐藏20日涨幅与3/5/10/20日净流入；展示板块、今日/5/10日涨幅和即时净流入 | 合法列 key 子集 | 忽略未知列 key | 设置抽屉恢复默认 |

**偏好优先级**：**URL query > 已保存偏好 > 默认值**。URL 带筛选参数（含来自详情的来源 query）优先；无 URL query 时用 `usePageSettings` 已保存偏好；均无则默认值。

**pageRegistry/组件契约（列表页，正文登记）**：
- `sectors` pageKey：`getPageLayout('sectors')`，原型 `master-detail`，`responsiveProfile: 'mixed-panel'`，slot `action(filter-bar) + main(workspace) + workspace/table + workspace/chart`，`supportsPageSettings !== false` → **`overlay:settings-drawer` 自动补登**。
- `componentMeta['table'].columns`：`name/pct_today/pct_5d/pct_10d/pct_20d/net_inflow/net_inflow_3d/net_inflow_5d/net_inflow_10d/net_inflow_20d`；各候选必须进入页面真实显隐判断，`pageRegistry.spec.ts` 拦截候选与渲染漂移。`sortFields` 同步覆盖各涨幅、各周期净流入和上涨家数。
- `consumedComponentFields`：`sectors` 消费 `wide-table` 的 `pageSize/defaultSort/hiddenColumns`（`border` 自动补登）。
- `minWidth=0` 基础断点；主表横向滚动兜底。

#### 7.1.1 页面功能点：板块列表筛选

- 对应需求编号：R7
- 默认展示：全部板块，今日涨幅降序。
- 用户操作：切板块类型（全部/概念/行业）、点列头选排序字段、搜索名称、查询。
- 输入与校验：搜索关键字 ≤ 50 字符。
- 状态变化：筛选条件变化触发服务端查询。
- 保存/提交/取消：无持久提交；类型偏好走页面设置。
- 加载状态：`v-loading` 覆盖主表。
- 空状态：`AppDataTable` 空态「暂无板块数据，请先在数据采集页运行板块采集」。
- 错误状态：`AppStateBlock` error 带重试。
- 权限不足状态：`AppStateBlock` permission 无权态。
- 数据刷新：筛选/排序/翻页变化自动查询。
- 与其他功能点联动：点行切换观察对象；「查看详情」进入当前板块详情。
- 验收标准：R7、R10

#### 7.1.2 页面功能点：板块列表主表

- 对应需求编号：R7
- 默认展示：列 = 板块（类型/成分数合并展示）/今日涨幅/5日涨幅/10日涨幅/即时净流入；20日涨幅和多周期净流入默认隐藏但可配置。当前观察摘要展示今日/5/10/20日涨幅、即时净流入和涨跌家数。
- 用户操作：各涨幅/净流入列头排序、翻页、点行切换观察对象、勾选附加对比、收起/展开走势分析、通过当前观察区「查看详情」进入详情、列显隐（设置抽屉）。
- 状态变化：排序/分页触发查询。
- 验收标准：R7（主表排序/分页/列显隐；不含详情成分股分页 R13，R13 归详情页）

### 7.2 页面 P2：板块详情页

- **对应需求编号**：R8、R9、R11、R14
- **页面类型**：新增页面
- **页面入口**：板块列表保持“点行切换观察对象”；当前观察区「查看详情」进 `/sectors/:code`，避免与列表/图表联动手势冲突。
- **原型文件**：`prototypes/sector-detail.html`
- **页面布局**：
  - 布局事实源：对齐 `prototypes/sector-detail.html`；指数区复用个股详情的 `StockChartWorkspace`，以 K 线 + 量能双面板呈现，支持拖拽分隔线调整并保存高度比例。
  - 页面区域：
    - 摘要区：板块名称、类型标签、成分股数、今日涨跌幅、**上涨/下跌家数**、即时净流入额（含数据日期）、**领涨股及涨幅**（**不含来源/代码副标题**）
    - 主区 detail：板块指数走势图（ECharts，周期切换 + 日期控件）+ 成分股表（embedded，**统一分页**）
  - 主次关系：摘要在上、图表与成分股表并列/上下；图表为主视觉，成分股表支撑选股。
  - 核心模块与数据区：统一 K 线范围（近 60/120/250 日/全部）+ K 线/量能高度分隔拖拽 + **日期控件（`TradeDatePicker`）**；成分股表列 = 代码 | 名称 | 现价 | 涨跌幅 | 换手，统一分页，无 TopN 展开/收起。
  - 弹窗/抽屉/设置入口：`PageSettingsDrawer`；K 线范围消费全局偏好，拖拽高度自动保存；成分股排序/分页/列显隐归组件设置。
  - 关键状态与退化：图表无数据→空态；成分股表空→空态；error→重试；常见桌面视口下摘要和图表保持稳定，成分股表占据剩余空间并由表体内部滚动；只有低高度空间不足时才允许主内容区整体滚动兜底。
- **数据来源**：`/api/sectors/{code}`（摘要+能力字段）、`/api/sectors/{code}/bars`（指数）、`/api/sectors/{code}/members`（成分股）。
- **权限与可见性**：`sectors:view` 查看；`stocks:view` 决定成分股跳转可点性（R9）。
- **组件复用与通用能力**：
  - 已有通用能力：`AppDataTable`/`AppTableColumn`/`AppPagination`/`AppStateBlock`、`useEChartsTheme`、`LayoutHost`/`getPageLayout`。
  - 新增通用能力：无；板块指数复用 `StockChartWorkspace` 的 K 线/量能双面板与高度分隔线。
  - 配置化承载：`sectors-detail` pageKey 进 `pageRegistry`；图表区域高度走 `chart.minHeight` 组件字段，内部高度比例走 `usePageSettings`；**成分股表排序/分页/列显隐走 `memberTable` 组件字段（`layout_user_config`）**。

**配置项定义（详情页，谁保存/谁读取/谁消费/如何回退）**：

| 配置项 | 保存位置 | 读取点 | 消费点 | 默认值 | 合法值 | 非法值处理 | 回退 |
|---|---|---|---|---|---|---|---|
| 图表高度比例 `charts.heightRatios` | PG `user_preference`（`usePageSettings('sectors-detail')`） | `useStockChartPreferences` | K线/量能分隔线 | `kline|volume = 0.75/0.25` | 正数数组且总和为 1 | 归一化或回落默认比例 | 设置抽屉恢复默认 |
| 图表区域高度 `minHeight` | PG `layout_user_config`（sectors-detail 页 chart slot） | `componentValueOf('chart','minHeight')` | 板块指数完整区域与内部工作区安全高度 | 560px | 480–900px 整数 | 前后端拒绝越界；页面兜底 560px | 设置抽屉恢复默认 |
| 每页条数 `pageSize` | PG `layout_user_config`（sectors-detail 页 data-table slot） | `componentValueOf('memberTable','pageSize')` | 成分股统一分页 | 20 | 10/20/30/50 | 回落 20 | 设置抽屉恢复默认 |
| 默认排序 `defaultSort` | PG `layout_user_config`（同上） | `componentValueOf('memberTable','defaultSort')` | 成分股表列头排序 | `pct:desc` | `pct`/`code` + asc/desc | 回落 `pct:desc` | 设置抽屉恢复默认 |
| 列显隐 `hiddenColumns` | PG `layout_user_config`（同上） | `componentValueOf('memberTable','hiddenColumns')` | 成分股列渲染 | 全部显示 | 合法列 key 子集 | 忽略未知列 key | 设置抽屉恢复默认 |

> **单一事实源**：K 线范围来自全局 `useKlinePrefs`；高度比例由板块详情页面偏好承载；成分股默认排序由组件字段 `defaultSort` 承载，不建立第二套周期/排序偏好。

**pageRegistry/组件契约（详情页，正文登记）**：
- `sectors-detail` pageKey：`getPageLayout('sectors-detail')`，原型 `detail`，`responsiveProfile: 'single-column'`，slot `action(toolbar) + main(detail)`，`supportsPageSettings !== false` → **`overlay:settings-drawer` 自动补登**。
- **成分股表登记真实嵌套 slot**（对齐 pageRegistry 现有 `groupTable`/`history`/`trades` 模式）：
  ```ts
  { id: 'memberTable', component: 'data-table', region: 'main', parentId: 'detail', label: '成分股', order: 2, config: { defaultSort: 'pct:desc' } }
  ```
  消费契约经 `componentMeta['memberTable']`、`consumedComponentFields['memberTable']`、`componentValueOf('memberTable', ...)` 统一承载，**不落到 `main`/`detail` slot 上**（否则 pageRegistry.spec.ts 契约测试失败：消费字段必须指向真实 slot）。
- `componentMeta['memberTable'].sortFields`：`pct/code`（成分股排序字段码）。
- `consumedComponentFields['chart']`：`minHeight`；`memberTable`：`pageSize/defaultSort/hiddenColumns`（统一分页模式）。
- 图表保持紧凑稳定，外层默认高度约 560px；内部 K 线与量能双面板完整可见，紧凑工作区最小高度 480px，不得通过裁切量能压缩高度。成分股表作为主成长区，最小高度约 420px，并由表体内部滚动；低高度不足以容纳有效最小高度时，才由主内容区整体滚动兜底。

#### 7.2.1 页面功能点：板块摘要卡

- 对应需求编号：R8、R14
- 默认展示：名称/类型/成分数/今日涨幅/涨跌家数/即时净流入（含数据日期）/领涨股及涨幅。
- 状态变化：随路由 code 变化刷新。
- 空状态：板块不存在→error 态「板块不存在或数据未采集」。
- 验收标准：R8、R14

#### 7.2.2 页面功能点：板块指数走势图

- 对应需求编号：R8、R11
- 默认展示：全局默认近 120 日，原始连续指数 K 线。
- 用户操作：选择近 60/120/250 日/全部；拖拽 K 线与量能之间的分隔线调整高度，也可用方向键精细调整。
- 状态变化：交易日期或范围变化时重新请求 `/bars`；快捷范围先按自然日预取，再精确截断末尾交易点，数据与横向缩放边界保持一致；高度调整即时重绘，结束后保存比例。
- 加载/空/错误：图表 loading/空态/error 复用图表组件四态。
- 验收标准：R8、R11

#### 7.2.3 页面功能点：成分股表（统一分页）

- 对应需求编号：R8、R9、R13
- 默认展示：统一分页（默认每页 20，按涨跌幅降序）代码/名称/现价/涨跌幅/换手；**无 TopN 展开/收起**。
- 用户操作：列头排序、翻页（`AppPagination`）、抽屉配置每页条数（10/20/30/50）；有 `stocks:view` 时点行跳 `/stocks/:code`，无权限时行禁用 + hover 提示。
- 状态变化：排序/分页/每页条数变化触发查询。
- 验收标准：R8、R9、R13

### 7.3 页面 P3：数据质量页（更新页面，R2 恢复闭环）

- **对应需求编号**：R2、R12
- **页面类型**：更新页面（复用现有 [QualityView](../../frontend/src/views/data/QualityView.vue)）
- **页面入口**：「数据管理」→「数据质量」
- **原型文件**：不生成原型（复用现有质检页结构）
- **🔴 候选机制删除（2026-08-09 修订）**：改为「只进不出」成分模型后，**取消候选确认/丢弃功能**（R2 候选机制、`member_surge_shrink` 问题类型、`/api/data/board-candidates` 接口整条移除）。数据质量页不再有候选操作列。
- **成分采集失败恢复**：成分采集不完整（`complete=False`）时不落库、记 `data_update_log failed`，可在采集页/任务中心对指定板块发起**重采**（`ingest_board --members --codes {code}` 或任务中心板块采集指定板块）；重采完整快照即 `ON CONFLICT DO NOTHING` 合并，既有数据不受影响。

## 8. 边界条件与异常场景

| 场景 | 处理 |
|---|---|
| 板块数据未采集 | 列表页 empty 引导去采集页 |
| 双代码体系（路径 code vs App clid） | 主键用路径 code（取数稳定）；`app_code` 存 clid 供用户与手机 App 核对（见 R1） |
| 概念资金流仅名称无代码 | 按名称匹配路径 code；未匹配写质检，不伪造代码（R4） |
| 单板块成分股取数失败/分页不完整 | 完整快照才落库（R2 完整性即闸门）；不完整记 `data_update_log failed` 待重采，不中断整体（R2） |
| 成分数变化（源端重组） | 只进不出模型下视为真实重组，不做波动质检、不写候选（R2/R12 修订） |
| 成分股历史不可回溯 | `board_dict.member_history_start_date` 记录可信起点；本期不改回测（R19 后续） |
| 排序参数敏感取不全 | `ThsBoardSource` 两种排序策略都试取多者 |
| 375 vs 387 集合差异 | 链接带真实路径 code 的独有板块**补进字典**（`has_fund_flow=true`）；无稳定代码的写 `board_fund_unmatched` 质检，不伪造代码（R1/R4 修订 + 2026-08-10 口径更新） |
| 大板块（半导体 190 只） | 成分股统一分页（`AppPagination` 默认每页 20，抽屉可配）（R13） |
| 板块代码失效/改名 | 采集时校验，字典 upsert 保留历史 |
| 401（v cookie 失效） | 刷新 `v` cookie 后重试 |
| 无 `stocks:view` 用户点成分股 | 链接禁用 + hover 提示，不跳转；直接访问路由仍 fail-closed（R9） |
| 板块指数空值 | 列表/详情涨幅列显示「—」 |

## 9. 性能、安全与兼容性要求

- **数据量**：概念 375（无登录态；配 Cookie 约 390）+ 行业 90 ≈ 465~480 板块（并集后约 470+）；成分股最多 190 只/板块；指数近 3 年约 700 日/板块（2024 起）。`board_member` 约 465×50≈2.3 万行。查询均为 PK 索引，规模小。
- **查询性能**：列表页 join 需控制结果集规模（板块数 <600，可单次全查内存合并，遵循双库边界）。
- **采集限流**：同花顺详情页连续翻页会触发频率限制，须 ≥1s/次限速 + 分批断点（research.md §5.3）。
- **权限控制**：`sectors:view` 进业务授权集合（非登录基线），后端 `require_perm` 守卫；`stocks:view` 控制成分股跳转。
- **安全**：`ThsBoardSource` 直连同花顺详情页，无用户输入注入面；请求超时注入。
- **兼容性**：`board_bar` 存原值不套复权链，避免污染既有复权契约；`stock_basic.concept` 不硬塞字段。

## 10. 业务亮点与优化建议

| 编号 | 优化建议 | 价值 | 处理状态 | 说明 |
| --- | --- | --- | --- | --- |
| R16 | 板块资金流历史趋势图（多日净流入） | 资金面趋势分析 | 后续建议 | 需 `board_fund_flow` 多日累积后做 |
| R19 | 板块成分作为筛选/回测条件 | 板块作为选股条件 | 后续建议 | 需筛选引擎扩展 + 回测层起点护栏 |
| R17 | 板块间成分重叠分析 | 题材联动研究 | 后续建议 | 跨板块计算，后续独立需求 |
| R20 | 板块强弱热力图 | 一屏看全市场板块 | 后续建议 | 需图表组件扩展 |
| R24 | 审计可靠性提升（持久化 outbox/重试/对账） | 审计不丢失 | 后续建议 | 项目现无 outbox 设施，本期审计 best-effort；可靠性提升另立需求 |

## 11. 验收标准

| 需求编号 | 验收标准 | 验证方式 |
| --- | --- | --- |
| R1 | 运行板块采集后，`board_dict` 包含本次源响应中的概念+行业并集板块，能力字段 `has_members/has_bar/has_fund_flow` 正确；`app_code`(clid) 与路径 code 映射正确（如 AI PC 309121↔886071）；幂等重跑不重复 | 查询 DuckDB + 与同次源响应对账 + 抽验 AI PC 等板块 app_code |
| R2 | `board_member` 为**只进不出**累积：`(board_code, code)` 主键每行一只成分股，完整快照 `INSERT ON CONFLICT DO NOTHING`（已有不动、新增插入），不删除、不做 diff、不写候选；完整快照落库后 `board_dict.member_count` = 当前成分数；**不完整快照（`complete=False`）整趟不落库**、`data_update_log` 记 failed 待重采，已采数据原样保留；重采完整后合并新增、既有行不丢 | 查询 + DDL/服务单测（构造缺页/失败/完整性闸门/重采合并场景） |
| R3 | `board_bar` 指数日线完整，存原值无复权列 | 查询 + 单测 |
| R4 | `board_fund_flow` 各周期可查询，净额=流入-流出；并集映射无伪造代码，未匹配项进质检 | 查询 + 单测 + 质检核对 |
| R5 | 任务中心出现「板块采集」任务，可创建/看进度/取消/续跑；部分失败任务标 failed 且保留 checkpoint，按字典类型/板块代码/资金流周期只续跑未成功工作单元 | 页面验收 + 单测 |
| R6 | 数据概览出现「板块数据」维度行和统计卡，能看到 4 表行数、概念/行业数、三类覆盖、最新日期、活跃问题分类、最近更新，并可跳转板块采集 | 页面验收 + 单测 |
| R7 | `/sectors` 列表页板块类型筛选（全部/概念/行业）、各涨幅与资金列列头排序、资金流列含数据日期、分页、列显隐正常；10日涨幅可真实显示；列总宽超出排行区域时常显横向滚动条且可真实滚动；右侧分析区可通过排行标题右上角的固定按钮收起为全宽排行并在原位恢复；标题说明可通过鼠标和键盘访问 | Playwright + 页面 + pageRegistry 契约测试 |
| R8 | `/sectors/:code` 详情页摘要（含涨跌家数/领涨股/净流入）/走势图/成分股表正常；返回列表保留筛选态（面包屑/浏览器返回/刷新还原） | 页面验收 + Playwright |
| R9 | 有 `stocks:view` 成分股可跳；无权限行禁用 + hover 提示，直接访问路由 fail-closed | Playwright + 权限测试 |
| R10 | 名称搜索过滤正常，无结果空态 | 页面验收 |
| R11 | 统一 K 线范围正常；快捷周期的数据与横向缩放边界对齐，只有“全部”可查看完整历史；走势对比支持多口径切换（累计/单日/5日/10日/20日涨幅折线，即时净流入/涨跌家数柱状），趋势指标可切中证 500/沪深 300/不对比指数并悬浮展示相对指数超额，累计涨跌支持区间首日/近一年双基期；头部槽可点击切换、抽屉可配置显隐与默认；K线/量能高度分隔线可拖拽、键盘调整并保存 | 页面验收 + Playwright |
| R12 | 板块指数缺口质检可扫描并写 `data_quality_issue`（`board_index_gap`）；成分数波动不再质检（只进不出模型，见 R2 修订）；PG 可用时审计可查询、PG 失败时业务成功且记录 warning | 页面验收 + 配置测试 + 集成测试 |
| R13 | 详情页成分股统一分页（无 TopN 展开）：默认每页 20、抽屉 pageSize 可配 10/20/30/50、分页/排序/权限态正确 | 页面验收 + Playwright |
| R14 | 详情页摘要卡即时净流入数字正确（含数据日期） | 页面验收 |
| R21 | 每日流程 `daily` 自动采集板块，失败不阻塞行情更新；`board` 任务支持回填/增量分流、断点续跑；单板块失败时继续剩余板块，最终步骤/任务 `failed`、DailyPipeline `ok=false`，返回失败板块清单并可仅续跑失败项；**参数化测试矩阵**：`board=True` 默认执行、`skip_update=True` 仍执行板块、`--skip-board` 确实跳过、板块失败后继续质检、最终状态和失败清单正确、`total_steps` 正确（不出现 `3/2`） | CLI + 集成测试 + 参数化矩阵 |
| R22 | 菜单/资源 seed 幂等；`sectors:view` 加入业务授权集合并授予 normal/tenant_admin；既有库一次性回填 + bump `perm_ver`；路由守卫与 pageRegistry 登记一致 | 权限测试 + Playwright |
| R23 | 页面设置偏好可保存/读取/回退（默认类型/范围/图表模式/指数、分析区展开状态、全局 K 线范围、图表高度比例）；`chart.minHeight` 与两页表格字段保存、读取、非法回退、恢复默认闭环；`npm run build` 通过；关键视口 1100×620 / 1366×768 / 1440×900 无文本溢出且详情表体可读 | 前端测试 + 构建 + E2E + 参数化矩阵 |
| R26 | 列表 K 线模式与详情页可选择 MACD；标题为 `MACD（12,26,9·原始连续指数）`；指标按 `board_bar` 原始连续序列计算，局部失败不阻断 K 线/量能 | 后端指标单测 + Vitest + Playwright |

## 12. 建议开发顺序

**建议按「契约 → 数据源与 DDL → 采集与质检 → API 与权限 → 页面」五阶段推进**（评审修订，每阶段独立对账）。

### 阶段一：数据/权限契约确认
- **目标**：冻结 DDL、字段语义、接口契约、权限 seed、配置项。
- **覆盖需求**：R1-R6 的契约部分 + R12 配置项 + 权限设计（`sectors:view` 进 `BUSINESS_RESOURCE_CODES`、既有库回填、perm_ver）。
- **里程碑**：契约文档（DDL + 接口 + 权限）评审通过。

### 阶段二：数据源适配器与 DDL
- **目标**：`ThsBoardSource` 封装 + **4 表 DDL**（board_dict/board_member/board_bar/board_fund_flow）+ 维度注册（候选表已删除）。
- **覆盖需求**：R1-R4 数据源层、R6、R2 只进不出表结构。
- **依赖前置**：阶段一契约。
- **里程碑**：`ThsBoardSource` 单测通过（v cookie、AJAX 翻页、两种排序策略取多者、不完整快照保护）。

### 阶段三：采集/CLI/异步/daily/质检
- **目标**：板块采集进 CLI、异步任务、每日流程、质检。
- **覆盖需求**：R1-R5、R6、R12、**R21**。
- **依赖前置**：阶段二。
- **里程碑**：`python -m backend.cli board --backfill` 后 4 表有数据；任务中心可跑板块采集；质检可扫出指数缺口；daily 自动采集失败不阻塞。

### 阶段四：只读 API 与权限测试
- **目标**：`/api/sectors*` + 权限守卫 + 资源 seed + 回填。
- **覆盖需求**：R7-R10 的数据层，以及 R22 的资源 seed、授权回填、`perm_ver` 和后端权限守卫；本阶段不提前登记尚未落地的页面与路由。
- **依赖前置**：阶段三（数据来源）。
- **里程碑**：接口可独立对账（涨幅/净流入/成分数与 DuckDB 一致）；权限测试通过（有/无 `sectors:view`、有/无 `stocks:view`）。

### 阶段五：页面展示与验收
- **目标**：列表页 + 详情页 + E2E + 构建验收。
- **覆盖需求**：R7-R11、R13、R14、R26、**R22**（页面、路由、菜单、前端守卫与 pageRegistry 同阶段落地）、**R23**（配置闭环 + 构建/布局/视口）。
- **依赖前置**：阶段四。
- **里程碑**：普通用户完成「板块 → 成分股 → 个股」链路；关键视口验收通过；`npm run build` 通过。

## 13. 确认状态

- **阻塞确认项**：无。关键业务、数据、权限和状态决策均已确认。
- **非阻塞未决确认项**：无。建议实现项 R11-R14 已决定本次纳入。
- **后续范围**：R15-R20、R24、R25 均已确认暂不实现；原因和触发条件以 §4.3 为唯一事实源。

## 14. 当前实施事实校准（2026-08-14）

- **采集与数据管理闭环已实现**：R1-R6、R12、R21 的采集、调度、任务、失败续跑、质量扫描、问题修复和概览承接均已落地；采集支持 `backfill|update`、`concept|industry`、指定板块、阶段范围与限量。
- **修复状态以复检为准**：`board_member_incomplete`、`board_index_gap`、`board_fund_unmatched` 均通过异步 fix 复用同一板块采集服务；采集失败或复检仍不通过时不得 resolved，也不得把失败工作单元写入完成 checkpoint。
- **接口与权限已实现**：`/api/sectors*` 查询服务、`sectors:view` 后端守卫、资源/menu seed 与既有库授权回填已落地。
- **页面与权限闭环已实现**：`/sectors`、`/sectors/:code`、前端路由、菜单/资源、pageRegistry、页面设置和业务页 E2E 均已落地；R7-R11、R13-R14、R22-R23 已进入回归维护状态。
- **MACD 扩展已映射**：R26 对应列表 K 线模式、详情页、`StockChartWorkspace`、板块指标接口与标题语义测试；数据口径固定为原始连续指数。
- **凭证安全已收口**：同花顺登录 Cookie 保留页面配置能力，平台只持久化可校验密文；环境/文件可优先覆盖，页面掩码与可用性三态、审计脱敏、历史明文迁移和独立密钥配置属于发布必做项。
- **最新验证状态**：以同目录 `plan.md` §8/§11 的 2026-08-14 实际命令结果为准；历史绿色数量不再代表当前 HEAD。
