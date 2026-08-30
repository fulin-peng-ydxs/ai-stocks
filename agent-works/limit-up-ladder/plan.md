# 连板天梯开发计划

> 计划状态：实施中（T1～T7 已完成，下一阶段为 T8）
> 需求基线：`requirement.md`（R1～R31）
> 页面原型：`prototypes/limit-up-ladder.html`

## 1. 需求来源与目标

- 需求文档：`agent-works/limit-up-ladder/requirement.md`。
- 功能目标：新增 `/limit-ladder` 盘后连板天梯，按交易日物化完整涨停快照，按连续板高度呈现金字塔，支持固定窗口统计、行业/概念聚合、个股行情分析、CSV、个人默认偏好及 system-only 单日重算。
- 已确认本期范围：R1～R19；其中 R15～R19 为已纳入建议项。
- 本次不做：R20～R31 中需求文档标记为本期不纳入或后续建议的能力。
- 计划输出目录：`agent-works/limit-up-ladder/`。
- 阻塞项：无。R9、R18～R23 及“保留 DuckDB 任务中心”均已由当前连续会话确认。

## 2. 当前项目依据

| 范围 | 现状依据 | 本计划处理 |
| --- | --- | --- |
| 涨跌停规则 | `backend/market_rules.py` 已有 `price_limit_pct_for`，主板 ST 以 2026-07-06 为 5%/10% 分界，科创/创业 ST 保持 20% | 扩展共享规则以覆盖收盘封板、无涨跌幅限制日及点时 ST；天梯不另建平行口径 |
| 行情事实 | DuckDB 已有 `stock_basic`、`daily_bar`、`trade_calendar`、`board_dict`、`board_member`、`stock_board_correlation(_state)`；`daily_bar` 有 `is_st`、`is_one_word` | 新增点时 ST 与天梯版本化快照表；市场、板块和相关概念仍从既有事实读取 |
| 完整性 | `backend/services/trade_calendar_readiness.py` 已有交易日历就绪检查；采集服务能返回实际受影响日期 | 增加“选中日点时股票池 + 有效行情/停牌”门禁，不把不完整数据发布为空快照 |
| 快照模式 | `backend/scoring/snapshot.py` 已有失效、按日期标记及持久化模式 | 复用失效思想，采用“状态指针 + 不可变成功版本”保证失败时保留旧结果 |
| 长任务 | `backend/services/async_task.py` 已有任务类型、单 DuckDB 写者、同类任务冲突、进度和日志；前端 `data.ts` 有封闭 `TaskType`/`TASK_LABEL` | 新增 `limit_ladder_recompute` 写任务和同日幂等键；同步任务中心前端类型、筛选、名称、摘要和测试 |
| 可靠审计 | 现有 `AuditRepository` 与异步任务审计是 best-effort，异常会降级忽略 | PG 新增统一日期任务协调账本；自动与管理员入口创建 DuckDB 任务前先落账本，使用唯一键、身份快照、重试和 DuckDB→PG 对账补齐终态及 `audit_log` |
| 用户偏好 | PG `user_preference`、`backend/api/user_preferences.py`、`usePageSettings` 已具备 tenant/owner 隔离、保存、读取和重置 | 复用 `scope=page,pageKey=limit-ladder,prefKey=settings`，不新增偏好表 |
| 权限 | `require_perm`、`require_system_perm`、`sys_menu/sys_resource`、动态菜单路由守卫和 `v-permission` 已形成闭环 | 新增 `limit-ladder:view` 和 system-only `limit-ladder:recompute`；板块、个股详情继续消费既有权限 |
| 页面布局 | `LayoutHost` + `pageRegistry` 显式登记；`board` 已使用 `master-detail` | 新增 `pageKey=limit-ladder` 的 `master-detail` 登记，不新增布局体系或系统组件种类 |
| 页面复用 | 已有 `TradeDatePicker`、`AppControlRow`、`PageSegmented`、`AppStateBlock`、`MarketMasterDetailWorkspace`、`StockAnalysisPanel`、`PageDrawer`、`PageSettingsDrawer` | 复用以上组件；只新增天梯领域卡片/分层组件，响应式分析继续走现有抽屉能力 |
| 详情上下文 | `useStockSet` 支持有序集合、`returnPath` 和本地持久化；个股 bars 支持 `end` | 写入当前筛选后的天梯集合并携带完整 URL；分析截止日固定为所选交易日 |
| 板块跳转 | `/sectors/:code`、`sectors:view` 和 `stock_board_correlation` 已提供稳定 `board_code` 与 `as_of_date` | 卡片最新相关概念直接跳板块行情；顶部热点只负责天梯筛选，两者不复用同一点击语义 |
| 设计与测试 | `DESIGN.md`、页面模板、E2E 指南要求三种基线视口、稳定 test id、构建及 5181 Playwright | 页面按原型和设计 Token 落地，并额外增加 768×1024 窄屏 E2E |

### 2.1 已确认的数据域例外

用户已确认保留现有 DuckDB `async_task/task_log` 任务中心，不在本需求中迁移全平台任务元数据。需求文档已同步调整：DuckDB 继续作为任务 ID、进度、日志、互斥和恢复的运行时事实源；PG 保存天梯统一日期任务协调账本和最终审计。二者通过不可变 `command_id`、DuckDB `task_id` 和审计 `source_event_key` 关联，并由对账任务处理跨库非原子窗口。

## 3. 实施范围

### 3.1 必须实现

- R1～R14：页面入口、交易日门禁、统一涨停规则、ST 治理、快照、重算、天梯、卡片、窗口、热点、相关概念跳转、行情分析、权限及完整页面状态。
- 所有任务初始状态均为 `待开始`；详细映射见第 5 节。

### 3.2 本次纳入的建议项

| 需求编号 | 内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 验证方式 |
| --- | --- | --- | --- | --- | --- |
| R15 | 一字板标记及筛选 | 本次纳入 | 进行中（T3 完成） | T3、T8、T12 | 规则单测、组件及 E2E |
| R16 | 板块、ST、关键词组合筛选 | 本次纳入 | 进行中（T6 完成） | T6、T8、T12 | 接口契约、组合筛选 E2E |
| R17 | 涨停总数、最高板、首板数 | 本次纳入 | 进行中（T3、T6 完成） | T3、T6、T8、T12 | 聚合单测、页面状态断言 |
| R18 | 当前筛选结果 CSV | 本次纳入 | 进行中（T6 完成） | T6、T8、T12 | 下载测试及 CSV 字段断言 |
| R19 | 个人默认偏好 | 本次纳入 | 待开始 | T9、T12 | 偏好 API、非法值、重置及 E2E |

### 3.3 暂不实现

| 需求编号 | 内容 | 开发状态 | 原因 |
| --- | --- | --- | --- |
| R20 | 晋级数量与晋级率 | 跳过 | 用户已确认本期不纳入，需另定跨日基数 |
| R21 | 炸板数量与炸板率 | 跳过 | 用户已确认本期不纳入，EOD 日线不足以形成可靠盘中触板口径 |
| R22 | 1～120 日自定义窗口 | 跳过 | 用户已确认仅做 10/20/31/60 |
| R23 | 用户切换同层排序 | 跳过 | 用户已确认本期固定排序 |
| R24 | 昨日晋级、断板和梯队迁移 | 跳过 | 后续建议，先积累稳定快照 |
| R25 | 多日行业/概念热度趋势 | 跳过 | 后续建议，需另定跨日归属口径 |
| R26 | 历史天梯并排对比 | 跳过 | 后续建议，不属于本期单页结构 |
| R27 | 管理员区间批量重算 | 跳过 | 后续建议，先验证单日资源上限 |
| R28 | 首次封板时间、开板次数、封单金额 | 跳过 | 当前 EOD 数据源不可可靠支持 |
| R29 | 北交所 | 跳过 | 超出当前股票池边界 |
| R30 | 盘中实时天梯 | 跳过 | 超出 EOD 产品定位 |
| R31 | 历史日期的走势相关概念快照 | 跳过 | 已确认历史榜读取当前最新相关概念 |

## 4. 技术方案

### 4.1 数据模型与发布状态

在 DuckDB 新增以下七张领域表，均在 `backend/storage/ddl.py` 登记并由 `init_db` 幂等建表；PG 新增统一日期任务协调账本和审计 outbox，并为共享审计表增加可空唯一事件键：

| 表 | 关键字段与约束 | 用途 |
| --- | --- | --- |
| `stock_st_status_daily` | `(code,trade_date)` 主键；`is_st,source,source_ref,quality,captured_at,updated_at` | 点时 ST 当前事实；`quality=accurate|approximate`，近似不得伪装准确 |
| `stock_st_status_history` | `version_id` 主键；`code,trade_date,old_is_st,new_is_st,old/new_source,old/new_quality,change_reason,changed_at,task_id` | 不可变变更追溯；同值同来源幂等重跑不追加，值/来源/质量变化才追加 |
| `limit_ladder_snapshot_state` | `trade_date` 主键；`status,current_snapshot_id,last_success_at,task_id,rule_version,upstream_fingerprint,failure_summary,invalid_reason,updated_at` | 日期级状态指针；状态仅允许 `calculating|valid|invalid|recalculating|failed` |
| `limit_ladder_snapshot` | `snapshot_id` 主键；`trade_date,rule_version,computed_at,stock_count,has_approx_st,coverage_json,source_version` | 不可变成功版本元数据；合法空快照也保留版本 |
| `limit_ladder_snapshot_stock` | `(snapshot_id,code)` 主键；名称、板块、涨停比例、ST/质量、一字板、连续板、成交额、行业及来源版本 | 卡片与分层的固化事实 |
| `limit_ladder_snapshot_concept` | `(snapshot_id,code,board_code)` 主键；`board_name,source_version` | R10 多概念固化集合，与 R11 当前相关概念严格分离 |
| `limit_ladder_snapshot_aggregate` | `(snapshot_id,group_type,group_key)` 主键；`group_name,stock_count` | 全量行业/概念聚合校验结果；筛选后的聚合由服务层基于快照股票受控重算 |
| PG `limit_ladder_task_ledger` | `command_id` 不可变 UUID 主键；`task_id,trade_date,source,actor_kind,tenant_id,actor_user_id,actor_account,trigger_tenant_id,trigger_user_id,trigger_account,request_ip,request_method,request_path,request_id,status,rule_version,result_summary,retry_count,last_error,created/updated_at`；`source IN (auto_first_load,auto_invalid_refresh,admin_recompute)`；`status IN (requested,running,succeeded,failed,interrupted)`；对 `trade_date WHERE status IN ('requested','running')` 建部分唯一索引 | 三种入口共享同日活动命令；终态释放日期占位。管理员主体从鉴权上下文和 PG 用户事实固化；自动任务使用独立 `system:limit-ladder` 主体并保留触发请求身份，不信任前端身份字段 |
| PG `limit_ladder_audit_outbox` | `(command_id,event_type)` 唯一；`source_event_key=command_id:event_type`、完整主体/请求快照 `payload`、`status,retry_count,next_retry_at,last_error,created/delivered_at` | requested/running/succeeded/failed/interrupted 可靠投递；终态可由 DuckDB 任务对账补建，审计投递不得重新推断操作者 |
| PG `audit_log.source_event_key` | 可空字段 + 非空唯一索引 | outbox 投递使用 `ON CONFLICT DO NOTHING`，避免投递成功后进程中断造成重复审计 |

发布采用“临时计算结果校验 → 同一 DuckDB 事务写不可变版本及子表 → 更新 `current_snapshot_id/status=valid`”的原子切换。重算失败只更新状态和失败摘要，不删除 `current_snapshot_id`。规则版本或上游受影响日期只把状态置为 `invalid`；旧成功版本仍可读并明确标为过期。

### 4.2 计算与查询数据流

1. 交易日服务确定最新完整交易日或校验用户指定日期；非交易日直接返回可选择的最近交易日。
2. 完整性门禁以 `list_date<=T AND (delist_date IS NULL OR delist_date>=T)` 且板块为主/科/创形成点时股票池。池内每股必须存在 T 日有效日线，或存在 `stock_suspension` 的 T 日确认停牌；两者均无、OHLC/前收盘非法或涨跌幅规则不可判定时拒绝发布。采集日志仅按第 4.2 节定义的结构化 T 日终态摘要判定，不扫描任意历史 failed 行。
3. 滚动“X 天 N 板”最多批量读取 60 个交易日。连续板高度不受 60 日窗口限制：先定位选中日涨停候选，再以候选代码集合按批次继续向前读取交易日和行情，直到每只候选遇到未涨停、停牌、缺行情或上市边界；每批对剩余候选一次性查询，禁止逐股 N+1，也禁止用 60 日截断高度。
4. 逐日涨停事实统一调用 `market_rules`；无涨跌幅限制且不可可靠判定时拒绝发布受影响结果。选中日涨停股票才进入快照。
5. 行业单归属只使用快照生成时的权威 `stock_basic.industry`；概念使用 `board_member + board_dict` 多归属。行业名称仅在唯一精确匹配行业字典时附稳定 `board_code`，否则保留统计/筛选但不提供详情跳转；缺失归“未分类”。
6. 10/20/31/60 日次数是查询读模型：对快照候选股票批量计算，返回 `window_start_date` 和 `actual_trade_days`；切换窗口不新建快照；同层固定按“窗口次数降序、当日成交额降序、代码升序”。
7. R11 从 `stock_board_correlation` 当前成功态读取概念冠军、`board_code` 和 `as_of_date`，在服务层合并到返回 DTO；不写入历史快照、不传历史 `business_date` 限制。
8. 展示筛选在已发布快照集合上取交集；摘要、层内数量、热点和 CSV 使用同一筛选函数，防止四套口径漂移。

完整性结果 `coverage` 使用固定结构：`pool_count`、`valid_bar_count`、`confirmed_suspension_count`、`missing_count`、`invalid_bar_count`、`unsupported_rule_count`、`ingest_terminal_status=success|partial|failed|unknown`、`ingest_run_id`、`reason_codes[]`、`sample_codes[]`（每类最多 20 个）、`checked_at`。日行情顶层编排结束时向 `data_update_log` 写结构化终态摘要：`table_name=daily_bar`、`source=pipeline`、`date_start=date_end=T`、JSON `detail.kind=market_day_terminal`，detail 同时含 `run_id/expected/successful/failed/status`。门禁只解析此类摘要，无法解析或缺 kind 的旧 detail 忽略；同日按 `updated_at DESC,id DESC` 取一条，后续 success 覆盖早期失败，历史无摘要为 unknown 并依赖事实闭合。原因码至少包括 `NOT_TRADING_DAY`、`INGEST_PARTIAL`、`MISSING_BAR_OR_SUSPENSION`、`INVALID_DAILY_BAR`、`UNSUPPORTED_LIMIT_RULE`。只有所有计数闭合、差异数为 0，且终态为 success 或 unknown 时，股票数为 0 才能认定为合法无涨停。

### 4.3 API 契约

新增 `backend/api/limit_ladder.py`，统一前缀 `/api/limit-ladder`：

| 方法与路径 | 权限 | 能力与关键返回 |
| --- | --- | --- |
| `GET /trade-dates` | `limit-ladder:view` | 可用交易日、最新完整日及日期就绪原因；底层复用交易日能力 |
| `GET /{trade_date}` | `limit-ladder:view` | `window=10|20|31|60`、板块/ST/一字板/关键词/热点筛选；顶层返回状态、coverage、层级、摘要、热点及 `requested_window_start_date/requested_window_trade_days`；每个股票 DTO 独立返回 `window_start_date/actual_trade_days` 和相关概念截止日 |
| `GET /{trade_date}/status` | `limit-ladder:view` | 无快照/计算中/有效/失效/失败及任务进度，供首算与重算轮询 |
| `GET /{trade_date}/export` | `limit-ladder:view` | 与查询接口共用参数规范化和筛选函数，输出 UTF-8 BOM CSV |
| `POST /{trade_date}/recompute` | `limit-ladder:recompute` + system 硬守卫 | 以 `admin_recompute` 调用统一 `ensure_date_task`；同日任意来源 requested/running 返回活动命令/任务，succeeded/failed/interrupted 后允许新建 |

错误契约：非法窗口/板块/日期返回 400；无权限 403；非交易日和未就绪使用稳定业务码与结构化原因；合法空结果为 200 且 `snapshot.stock_count=0`。动态窗口或相关概念局部失败不能覆盖成功快照主体。

### 4.4 权限、菜单与审计

- 在 `_SEED_MENU_TREE` 的“最新行情”下新增 `/limit-ladder` 叶子，只补缺失行。
- 在 `_SEED_RESOURCES` 新增 `limit-ladder:view`（挂 `/limit-ladder` 业务菜单）和 `limit-ladder:recompute`（挂既有 `visible=system` 的 `/data/ingest` 系统菜单作为权限锚点）。后者仍由天梯页面按钮消费，但借助现有 `system_only_resource_ids()` 同时阻止非 system 角色获得该资源码。
- `/limit-ladder` 加入业务菜单集合；新库 normal/tenant_admin 对齐每日榜单默认范围。存量库通过一次性 marker SQL 原子补默认授权并自增受影响用户 `perm_ver`，后续管理员撤销不被启动 seed 补回。
- 重算后端必须使用 `require_system_perm("limit-ladder:recompute")`；按钮使用 `v-permission`，不能只按账号名判断。
- 板块跳转只在有 `sectors:view` 时可操作；个股详情继续要求 `stocks:view`。
- 新增唯一编排入口 `ensure_date_task(trade_date, source, actor_context)`；无快照 GET、失效日期 GET 和管理员 POST 分别传 `auto_first_load`、`auto_invalid_refresh`、`admin_recompute`。入口为每次尝试生成候选 command_id，并在一个 PG 事务中插入 requested 账本与 outbox；以同日活动态部分唯一索引作为最终并发裁决，唯一冲突时丢弃候选并查询返回现有 command/task。若冲突命令恰在查询前进入终态，则在有限次数内重新竞争，不依赖“先查后写”。只有事务成功取得活动槽位者才创建 DuckDB 任务；`trigger_event_id` 只传其 command_id，绝不传 trade_date，因此不会复用历史终态。
- PG 事务插入 requested 账本/outbox 时同步固化审计主体和请求来源。管理员主体的 `tenant_id/actor_user_id` 取鉴权上下文，`actor_account` 通过既有 `UserRepository.get_by_id()` 从 PG `sys_user` 权威事实解析，并校验返回用户的 tenant 与上下文一致；自动任务使用 `actor_kind=system,tenant_id=NULL,actor_user_id=system:limit-ladder,actor_account=system:limit-ladder`，触发用户另存于 trigger 字段并同样解析 `trigger_account`。IP 复用项目可信代理解析口径，method/path 取服务端 Request，request_id 由服务端生成；任何前端同名参数或未经信任的身份头均忽略。outbox payload 复制该不可变快照，后续 running/终态审计沿用，不重新查询可能已变更的账号。
- 创建 DuckDB 任务后回填 task_id；执行器写 running 及 succeeded/failed/interrupted 终态，终态自动释放日期活动占位。启动时先运行 DuckDB `reconcile()` 将残留任务置 interrupted，再在 PG advisory lock 下执行天梯账本对账，最后投递 outbox；定时对账复用同一锁和幂等 upsert。interrupted 是独立不可续跑终态，允许同日新命令。投递器用 `audit_log.source_event_key` 唯一索引幂等写审计后标记 delivered。

### 4.5 页面 P1 技术实现

- 页面路由：`/limit-ladder`；页面文件 `frontend/src/views/LimitLadderView.vue`。
- 原型文件：`agent-works/limit-up-ladder/prototypes/limit-up-ladder.html`，承接页头状态、筛选行、三项摘要、行业/概念热点、左侧天梯、右侧分析、设置抽屉和重算确认框。
- 页面结构：`LayoutHost` 的 action 槽承载页头和筛选；main 槽使用 `MarketMasterDetailWorkspace`，左侧天梯为主要纵向增长区并独立滚动，右侧 `StockAnalysisPanel`；overlays 放 `PageSettingsDrawer`、全屏 `PageDrawer` 和确认弹窗。
- 响应式：桌面保留主从结构；窄屏不强制物理三角形，仍按最高板至首板排序，分析改全屏抽屉；低高度时筛选可换行、天梯主体保持可滚动。
- 设计：使用系统 Token、涨红语义、等宽数字和明确文字/图标，不用颜色单独表达 ST、一字板、选中或过期。

| 页面功能点 | 对应需求 | 交互与状态 | 技术实现/复用 | 数据/API | 异常与权限 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 页头、交易日、状态 | R2、R5、R6、R13、R14 | 默认最新完整交易日；切日取消旧请求写回；展示有效/计算/失效/失败和最后成功时间 | `TradeDatePicker`、`AppStateBlock`、请求序号/Abort 控制 | trade-dates、status、ladder query | 非交易日引导最近日；403 统一页态 | T6、T7、T10、T11 |
| 管理员单日重算 | R6、R13、R14 | 明示目标日期，确认/取消，防重复提交，完成后刷新 | `v-permission`、确认弹窗、任务轮询 | recompute、status | 非 system 不渲染且接口 403；失败保留旧结果 | T5、T7、T10、T12 |
| 固定窗口 | R9 | 10/20/31/60，默认 31；只改次数与同层排序；短上市历史显示实际起始日 | `PageSegmented`，卡片辅助文案消费 `window_start_date/actual_trade_days` | ladder query `window` | 非法值回退 31；局部失败保留旧视图 | T6、T8、T9、T12 |
| 板块/ST/一字板/关键词 | R15、R16 | 条件取交集，交易日变化清热点与选股，不触发重算 | `AppControlRow`、多选、checkbox、搜索输入 | 共用查询/导出参数 | 筛选空与当日无涨停分开 | T6、T8、T12 |
| 三项摘要 | R17 | 当前筛选集合的总数、最高板、首板数 | 领域摘要组件，消费统一筛选结果 | ladder query | 无结果最高板“—” | T6、T8 |
| 行业/概念热点 | R10 | 分栏计数；点击只聚焦天梯，再点取消；按当前可见集合重聚合 | 新增页面域 `LadderHotspots`；可选板块详情入口独立处理 | ladder query 聚合 | 无 `sectors:view` 仍可筛选但不可跳详情 | T3、T6、T8、T12 |
| 连板天梯 | R3、R4、R7、R8、R9、R15、R16 | 最高板至首板、层数量、卡片键盘选择和明确标签 | 新增页面域 `LimitLadder`/`LimitLadderCard`，不登记为系统组件种类 | ladder query | 近似 ST 提示；筛选空、过期结果明确 | T3、T8、T11、T12 |
| 卡片最新相关概念 | R11 | 点击直接进入 `/sectors/:boardCode`，不改变天梯热点筛选 | 复用 `RelatedBoardCell` 的权限/展示语义或抽取最小通用链接适配 | 当前 correlation 字段 | 无结果“—”；无 `sectors:view` 只读 | T6、T8、T12 |
| 股票行情分析 | R12、R14 | 卡片选择驱动分析，高亮当前项；截止选中日 | `MarketMasterDetailWorkspace`、`StockAnalysisPanel`、分析 session composable | 既有 stock bars/indicators | 局部失败局部重试，不清天梯 | T10、T11、T12 |
| 查看个股详情/返回 | R12、R13 | 写当前筛选有序集合、完整返回 URL、选中项和滚动锚点 | `useStockSet` + URL query/session scroll key | 既有 `/stocks/:code` | 无 `stocks:view` 不显示入口 | T10、T12 |
| CSV 导出 | R18 | 文件名含日期和窗口，数据严格等于当前筛选集合 | 复用下载工具；服务端生成字段与转义 | export | 快照概念集合、最新概念、截止日三列独立；失败不影响页面 | T6、T8、T12 |
| 页面设置 | R19 | 保存默认、取消不保存、重置系统默认；URL 显式值优先 | `PageSettingsDrawer`、`usePageSettings`、分析默认字段 | user-preferences | 读取失败非阻断；非法旧值回退 | T9、T12 |
| 响应式与可访问性 | R14 | 桌面三视口 + 768px 窄屏、键盘焦点、非颜色提示、低高度可滚动 | `PageDrawer`、语义 aria、稳定 test id | 不新增 API | 768×1024 必须进入全屏分析；1100×620 不遮挡主要操作 | T10、T12 |

### 4.6 前端组件与配置接入闭环

| 页面/区域 | 复用或新增 | 现有机制 | 配置/登记 | 资产维护 | 实际消费与验证 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 页面布局 | 复用 | `LayoutHost` + `pageRegistry` | 显式新增 `pageKey=limit-ladder`、`master-detail`、`mixed-panel` | 同步 `DESIGN.md` 页面登记 marker | 页面真实调用 `getPageLayout` 和远端布局；registry 单测 | T7、T10、T13 |
| 行情主从区 | 复用并补窄屏承载 | `MarketMasterDetailWorkspace`、`StockAnalysisPanel`、`PageDrawer` | 不新增系统组件 kind | 若抽取通用全屏分析承载，同步组件清单/设计说明 | 桌面与窄屏真实消费；组件/E2E | T10、T12、T13 |
| 天梯分层/卡片 | 新增页面域组件 | Vue 页面组件 | 不进入系统组件配置；需求明确暂无第二消费方 | 无需新增系统资产清单，保留页面域说明 | `LimitLadderView` 唯一消费；组件测试 | T8、T12 |
| 页面偏好 | 复用 | `usePageSettings` + PG `user_preference` | `pageKey=limit-ladder`，schema v1 | 不新增配置平台 | 保存、读取、消费、重置、非法回退全链路测试 | T9、T12 |
| CSV | 复用 | `downloadCsv`/下载响应 | 不涉及页面登记 | 否 | 导出端点和页面按钮真实消费 | T6、T8、T12 |

## 5. 需求与开发内容映射和开发状态

| 范围 | 需求 | 计划开发内容 | 任务 | 状态 | 偏差 | 验证 |
| --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R1 | 先建可编译页面壳，再接路由、菜单、pageRegistry，且不改每日榜单 | T7、T10 | 进行中（T7 完成） | 一致 | 页面文件存在后路由才登记；T10 解除 staged 后菜单可进且 `/board` 回归不变 |
| 必须实现 | R2 | 固定 coverage 契约区分非交易日、未就绪与合法空 | T2、T4、T6、T11 | 进行中（T2、T4、T6 完成） | 一致 | 每个原因码可复现；仅覆盖闭合时允许空快照 |
| 必须实现 | R3 | 共享收盘涨停规则及特殊日保护 | T1、T3 | 已完成 | 一致 | 分界日和特殊日单测 |
| 必须实现 | R4 | 每日 ST 当前事实、不可变变更历史、近似质量、回填失效及默认隐藏 | T1、T2、T3、T4、T8、T11 | 进行中（T1～T4 完成） | 一致 | 幂等采集不增历史；来源变化可追溯且仅失效受影响日 |
| 必须实现 | R5 | 首读通过统一日期任务入口物化、成功版本持久化、重复读取 | T2、T4、T5、T6 | 已完成 | 一致 | 首读并发只创建一个活动任务；有效快照不重复物化 |
| 必须实现 | R6 | 三种来源共享日期任务协调、活动态同日幂等、含 interrupted 的状态、原子发布和可靠 PG 账本 | T4、T5、T6、T11 | 进行中（T4～T6 完成） | 一致 | auto→auto、admin→admin、auto→admin、admin→auto 均复用同日活动命令；任一终态后可重算；重启对账补齐中断审计 |
| 必须实现 | R7 | 不受 60 日窗口截断的连续板算法和最高至首板分层 | T3、T8 | 进行中（T3 完成） | 一致 | 75 连板夹具返回 75；停牌/缺失/未涨停/上市边界中断 |
| 必须实现 | R8 | 卡片完整字段及标签 | T3、T6、T8 | 进行中（T3、T6 完成） | 一致 | DTO/组件/视觉验收 |
| 必须实现 | R9 | 10/20/31/60 动态次数、固定排序及股票级短上市实际起始日 | T3、T6、T8、T9、T12 | 进行中（T3、T6 完成） | 一致 | 每个股票 DTO/卡片显示自身 `window_start_date/actual_trade_days`，顶层字段不混用 |
| 必须实现 | R10 | `stock_basic.industry` 单行业、多概念、未分类和当前筛选聚合 | T3、T4、T6、T8 | 进行中（T3、T4、T6 完成） | 一致 | 行业不按代码猜测；多概念计数与筛选集合一致 |
| 必须实现 | R11 | 当前最新概念、截止日、直接板块跳转 | T6、T8、T12 | 进行中（T6 完成） | 一致 | 接口字段/权限/路由 E2E |
| 必须实现 | R12 | 复用行情分析、详情集合和返回恢复 | T10、T12 | 待开始 | 一致 | Playwright 完整往返 |
| 必须实现 | R13 | 查看/重算/关联权限、seed、结构化主体账本和审计对账 | T2、T5、T7、T11 | 进行中（T2、T5、T7 完成） | 一致 | 非 system 不可获重算码；自动/管理员身份及请求来源完整且不可由前端伪造；任务终态审计唯一 |
| 必须实现 | R14 | 加载、空、未就绪、过期失败、403、响应式和无障碍 | T10、T11、T12 | 待开始 | 一致 | 每种状态及 768px 全屏抽屉均有 E2E |
| 本次纳入 | R15 | 一字板标记、筛选及联动 | T3、T8、T12 | 进行中（T3 完成） | 一致 | 规则/组件/E2E |
| 本次纳入 | R16 | 板块、ST、关键词组合筛选 | T6、T8、T12 | 进行中（T6 完成） | 一致 | 组合筛选测试 |
| 本次纳入 | R17 | 当前视图三项摘要 | T3、T6、T8 | 进行中（T3、T6 完成） | 一致 | 聚合/页面测试 |
| 本次纳入 | R18 | 当前视图 CSV，三类概念字段分离 | T6、T8、T12 | 进行中（T6 完成） | 一致 | CSV 内容/文件名测试 |
| 本次纳入 | R19 | 默认偏好保存、读取、消费、重置 | T9、T12 | 待开始 | 一致 | 偏好 API/组件/E2E |
| 本期不纳入 | R20 | 晋级数量与晋级率 | - | 跳过 | 未覆盖 | 用户确认本期不做 |
| 本期不纳入 | R21 | 炸板数量与炸板率 | - | 跳过 | 未覆盖 | 用户确认本期不做 |
| 本期不纳入 | R22 | 自定义窗口 | - | 跳过 | 未覆盖 | 用户确认本期不做 |
| 本期不纳入 | R23 | 排序切换 | - | 跳过 | 未覆盖 | 用户确认固定排序 |
| 后续建议 | R24 | 晋级/断板/梯队迁移 | - | 跳过 | 未覆盖 | 稳定跨日快照后另立需求 |
| 后续建议 | R25 | 热点趋势 | - | 跳过 | 未覆盖 | 跨日口径另立需求 |
| 后续建议 | R26 | 并排历史回放 | - | 跳过 | 未覆盖 | 不属于本期页面 |
| 后续建议 | R27 | 区间批量重算 | - | 跳过 | 未覆盖 | 先验单日资源边界 |
| 暂不实现 | R28 | 盘中封板字段 | - | 跳过 | 未覆盖 | 数据源不支持 |
| 暂不实现 | R29 | 北交所 | - | 跳过 | 未覆盖 | 股票池不包含 |
| 暂不实现 | R30 | 盘中实时天梯 | - | 跳过 | 未覆盖 | EOD 定位 |
| 暂不实现 | R31 | 历史相关概念快照 | - | 跳过 | 未覆盖 | 当前最新概念已确认 |

## 6. 详细实施步骤与进度追踪

### T1：统一涨停规则与点时 ST 解析契约

- 状态：已完成。
- 依赖：无。
- 输入：`daily_bar`、`stock_basic`、交易日和既有 `market_rules`。
- 目标：形成不依赖新增表的唯一涨停判断与点时 ST 解析值对象契约。
- 涉及文件/模块：`backend/market_rules.py`、新增纯规则模块及规则测试。
- 操作：补板块识别、收盘封板和特殊无限制日结果类型；定义准确事实优先、名称近似兜底的 `is_st/source/source_ref/quality` 输出；本任务不写表。
- 产出：统一涨停规则 API、ST 解析结果类型和纯函数测试。
- 影响范围：回测/质检共享规则及后续天梯计算；不得改变既有普通场景结果。
- 边界与异常：主板 ST 分界日前后、科创/创业 20%、停牌、前收盘缺失、无限制日和价格取整。
- 验证方式：不初始化新增表即可运行参数化单测，证明 5%/10%/20% 与特殊日边界。
- 完成标准：R3 及 R4 的解析口径可独立交付，未提前依赖 T2 表结构。
- 实际落地情况：已在 `backend/market_rules.py` 增加受支持上市板块解析、板块比例、收盘封板结果和值对象；特殊日显式区分适用、不适用和未知，未知规则/缺失比例/非法价格均阻止正式发布。新增 `backend/limit_ladder/rules.py`，准确点时事实优先，名称兜底始终标记 `approximate`。`backend/tests/test_limit_ladder_rules.py` 覆盖主板 ST 分界日前后、科创/创业 20%、停牌、价格取整、特殊日、未知板块和 ST 来源质量；与既有 `test_quality.py` 共同回归通过。

### T2：DuckDB 领域表与 PG 日期任务账本迁移

- 状态：已完成。
- 依赖：无；可与 T1 并行，但 T3 必须等待 T1、T2 均完成。
- 输入：第 4.1 节表契约、现有 DuckDB/PG DDL 和迁移规范。
- 目标：为 ST 历史、版本快照和可靠管理员审计建立可幂等存储。
- 涉及文件/模块：`backend/storage/ddl.py`、`backend/storage/pg_ddl.py`、`limit-ladder-schema.sql`、`limit-ladder-audit-ledger.sql`、存储测试。
- 操作：新增七张 DuckDB 表、PG 账本和审计 outbox；为 ledger 添加同日 requested/running 部分唯一索引；为 `audit_log` 增加可空 `source_event_key` 与非空唯一索引；添加状态约束并编写前向/验证/回滚 SQL。
- 产出：新库初始化 DDL、存量升级 SQL、PG 账本/outbox 仓库接口和幂等审计键。
- 影响范围：新增领域表及 `audit_log` 可空字段/索引；不修改既有行情表、`async_task/task_log` 或既有审计记录含义。
- 边界与异常：重复执行、约束冲突、合法空版本、旧成功指针、账本事件幂等、事务回滚；部分唯一约束只覆盖 requested/running，所有终态不得继续占用同日活动槽位。
- 验证方式：临时 DuckDB/PG 重复初始化；非法状态被拒绝；失败事务零半成品；同 command/event 只存在一行；同日 requested/running 冲突而 succeeded/failed/interrupted 后可插入新 command；旧审计写入不传事件键仍兼容。
- 完成标准：新库和存量库可安全升级，且 T3 开始前 ST 当前/历史表真实存在。
- 实际落地情况：`backend/storage/ddl.py` 已登记七张 DuckDB 表及索引；`backend/storage/pg_ddl.py` 已登记日期任务账本、审计 outbox、活动日期/任务/投递索引和 `audit_log.source_event_key` 兼容迁移；`backend/storage/limit_ladder_task_repository.py` 提供 requested 原子落账、状态转换、活动命令查询和 outbox 投递状态接口。两份前向 SQL 已归档并写明前置条件、影响、验证和回滚顺序。内存 DuckDB 重复初始化、非法约束、合法空快照、真实临时 PG 重复初始化、三种终态释放日期槽、活动态冲突、旧审计兼容和事件键唯一性测试均通过。

### T3：点时 ST 采集追溯与天梯领域计算器

- 状态：已完成。
- 依赖：T1、T2。
- 输入：T1 规则、T2 ST 表、日行情采集上下文、最大 60 日滚动数据，以及可继续向前分页的历史行情。
- 目标：先落地 ST 当前/历史写入闭环，再产出不被 60 日截断的连板结果。
- 涉及文件/模块：`backend/services/ingest.py`、新增 `backend/services/stock_st_status.py`、`backend/services/limit_ladder_calculator.py` 及单测。
- 操作：每日采集幂等写 ST 当前事实，值/来源/质量变化时追加历史并返回受影响日；滚动次数最多读取 60 日；连续板对选中日涨停候选按批次继续向前读取，直到每股中断或上市边界；返回股票级 `window_start_date/actual_trade_days`；行业只固化 `stock_basic.industry`，概念固化多归属。
- 产出：ST 写入/追溯仓库、每日采集挂点、天梯领域 DTO、coverage 逐股明细和聚合结果。
- 影响范围：日行情采集、天梯快照与查询；不改变个股行情、板块行情或每日榜单。
- 边界与异常：同值重跑、来源升级、近似转准确、缺行情/停牌中断、连续板超过 60 日、短上市、合法空、未分类和行业字典非唯一。
- 验证方式：重跑不增 ST 历史，来源变化只增一版；构造连续 75 板后第 76 日中断夹具，结果必须为 75 而非 60；每批对剩余候选一次查询；卡片起始日准确。
- 完成标准：R4 的采集追溯闭环及 R3/R7～R10/R15/R17 领域结果均可观察。
- 实际落地情况：新增 `StockSTStatusService`，以单批事务幂等维护点时 ST 当前事实，只有值、来源、来源引用或质量真实变化时才追加不可变历史，并把受影响交易日返回给采集顶层；日线采集已写入带 `stock_name/approximate` 来源的每日事实，同时保留未来准确来源的显式注入入口。`LimitLadderCalculator` 已实现 10/20/31/60 日窗口、股票级短历史字段、选中日候选批量筛选和每 60 日一批的向前连板追溯，缺行情、确认停牌、非涨停和上市边界都会中断，未按股票逐只查询。行业取 `stock_basic.industry` 单归属，概念取字典/成员多归属并支持“未分类”；首次上市无涨跌幅限制日按交易所制度排除，旧制度无法可靠重建的首日返回规则未知。ST 幂等/来源与值变化、采集挂点、75 连板、停牌/缺失/未涨停中断、短上市窗口、多概念和聚合测试均已通过。

### T4：完整性门禁、快照发布、每日失效与回退

- 状态：已完成。
- 依赖：T2、T3。
- 输入：点时股票池、有效日线、确认停牌、结构化日行情终态摘要、计算结果和规则版本。
- 目标：严格区分非交易日、未就绪、合法空和有效快照，并原子发布版本。
- 涉及文件/模块：新增 `backend/services/limit_ladder_snapshot.py`；采集、修复、板块归属和 ST 回填失效挂点。
- 操作：日行情顶层编排结束时写 `table_name=daily_bar,source=pipeline,detail.kind=market_day_terminal` 的 T 日终态摘要；门禁只按 T 日和该结构化摘要过滤，并按 `updated_at DESC,id DESC` 取最新一条；无法解析的旧 detail 忽略，无摘要记 unknown 并使用事实闭合；实现 coverage、状态机、原子版本切换和精确失效。
- 产出：门禁结果、快照仓库、状态转换 API、失效矩阵。
- 影响范围：天梯日期状态和上游任务完成钩子；不删除旧成功版本。
- 边界与异常：点时池闭合、停牌证明、早期失败后成功补采、同日多来源日志、历史无结构化摘要、非法 OHLC、特殊规则未知、合法空和发布故障。
- 验证方式：后写 success 覆盖早期 partial/failed；非结构化旧日志不作硬否决；历史无摘要但事实闭合可发布；最新终态 partial/failed 必须拒绝；故障后仍指向旧成功。
- 完成标准：R2/R4～R6/R10 的门禁、状态和一致性验收可复现。
- 实际落地情况：新增 `LimitLadderSnapshotService`，按点时股票池批量核对有效 OHLC/前收盘、确认停牌、缺行情、规则未知和最新结构化采集终态，输出固定 coverage、原因码、样本代码及上游指纹；指纹覆盖一字板标记、点时 ST、概念归属和行业字典映射，事务内可识别所有会改变已发布股票字段的上游漂移。非结构化旧日志被忽略，无终态日志按 `unknown + 事实闭合` 处理，后写 partial/failed 会阻断发布。发布采用不可变版本，单个 DuckDB 事务写元数据、股票、概念、聚合并切换状态指针；合法无涨停仍发布零股票版本，发布失败或上游漂移保留旧成功指针并记录 failed。点时 ST 真实变化与同日快照失效在同一事务提交，指定日期行情及日常增量行情按实际返回日期失效，全量行情/基础信息及板块字典/成分变化使用有边界扩大范围且不删除旧版本。增量行情全市场编排新增 `market_day_terminal` 结构化终态摘要。非交易日、事实闭合、旧日志忽略、后写终态覆盖、合法空、重复不可变版本、事务故障回滚、旧指针回退、发布字段指纹和精确日期失效测试均已通过。

### T5：DuckDB 任务执行、可靠 PG 审计与任务中心前端

- 状态：已完成。
- 依赖：T2、T4。
- 输入：自动首算、失效自动重算或管理员重算请求，服务端鉴权/Request 上下文、DuckDB 任务框架和 PG 日期任务账本。
- 目标：在保留现有任务中心的前提下，让三种触发路径共享同日活动任务，并形成不会静默丢失、不会错认操作者的可靠审计。
- 涉及文件/模块：`backend/services/async_task.py`、`backend/storage/audit_repository.py`、新增 `backend/services/limit_ladder_task_coordinator.py` 及账本/outbox/对账服务、既有 `backend/storage/user_repository.py`、可信代理 IP 公共解析能力、`frontend/src/api/data.ts`、`frontend/src/views/data/IngestView.vue` 及相关测试；`ScheduleView.vue` 不开放该单日强制重算类型。
- 操作：实现 `ensure_date_task`，用同日活动态部分唯一索引协调三种 source；每次生成候选 command_id 后原子插入 requested/outbox，取得活动槽位者才创建 DuckDB 任务，唯一冲突者丢弃候选并返回已有活动命令，冲突命令已终态时有限重试。创建时从鉴权上下文、PG 用户事实和服务端 Request 固化主体/触发身份/请求来源；自动任务使用明确 system 主体。Duck `trigger_event_id=command_id`，不得使用 trade_date；执行器写 running/succeeded/failed/interrupted 及 outbox。启动顺序固定为 Duck reconcile → PG advisory-lock 对账 → outbox 投递；定时对账使用同一锁。interrupted 不可续跑，终态释放同日占位并允许新命令。
- 产出：统一日期任务协调器、新任务类型、活动态幂等约束、结构化身份快照、含 interrupted 的账本/outbox 状态机、重试/对账入口和任务中心前端承接。
- 影响范围：现有任务列表增加一种类型；不迁移或改写其他任务记录。
- 边界与异常：PG 初始写失败不创建任务；管理员主体或自动触发用户的权威账号解析失败则拒绝创建命令，不使用前端账号兜底；活动命令在唯一冲突后立即终态时有限重试，超过上限返回可重试错误；Duck 创建失败写 failed；回填失败按 command_id 对账；启动对账把启动时间前仍无 Duck 任务的 requested 命令标 failed，定时对账把超过 5 分钟仍无任务的 requested 命令标 failed；重启残留任务映射 interrupted；所有终态均可再次重算同日。
- 验证方式：auto→auto、admin→admin、auto→admin、admin→auto 四类同日并发各只产生一个活动命令和一个 DuckDB 任务；伪造 actor/IP/path 参数不影响账本，管理员和 system 主体可完整还原 audit_log；成功/失败/中断后均能创建新 command_id；构造服务重启后 PG running 被对账为 interrupted 且审计唯一；重复启动/定时对账不重复事件；任务中心显示中断状态和摘要。
- 实际落地情况：新增 `LimitLadderTaskCoordinator`，由 PG 活动态部分唯一索引统一协调自动首算、失效刷新和管理员重算；创建前按服务端鉴权上下文、PG 用户事实和可信代理边界固化主体及 Request 快照，自动来源使用隔离 system 主体。取得日期槽位者以 `command_id` 作为 DuckDB `trigger_event_id` 创建不可续跑的 `limit_ladder_recompute` 单写任务，执行器物化 T4 不可变快照并回写 running/succeeded/failed；Duck 创建失败和 coverage 未通过均进入 failed 并释放日期。已发布快照不因 PG 终态镜像临时失败而回滚，处理器保留 Duck 成功事实并由启动/周期对账补齐；对账同时读取任务结果，`valid` 才映射 succeeded，未发布结果映射 failed，避免 coverage 失败被误判成功。启动期按 Duck interrupted 后 PG 对账的顺序执行，30 秒周期对账复用 PG advisory lock，requested 孤儿和重启残留可收敛，outbox 通过 `source_event_key` 幂等投递 `audit_log`。任务中心复用既有类型、筛选、来源、状态、日志抽屉和摘要布局，补充系统来源、日期标签、coverage 摘要及中断/早期失败兜底；调度页面不开放该内部任务类型。四种来源顺序并发、权威身份/请求快照、Duck 创建失败释放、重启 interrupted 对账、处理器原子物化和任务能力测试通过；`limit-ladder-task-center.spec.ts` 已在 5181 的 1100×620、1366×768、1440×900 三视口完成真实登录、类型/状态筛选、日志抽屉、coverage 摘要和截图验证。

### T6：查询、状态、短历史字段与 CSV API

- 状态：已完成。
- 依赖：T4、T5。
- 输入：当前成功快照、窗口参数、展示筛选、当前相关概念和任务状态。
- 目标：提供前端无需推断的稳定查询、状态和导出契约。
- 涉及文件/模块：新增 `backend/api/limit_ladder.py`、`backend/services/limit_ladder_query.py`、`backend/main.py`、API 测试。
- 操作：实现第 4.3 节端点；GET 遇到无快照或失效时分别以 `auto_first_load/auto_invalid_refresh` 调用 T5 `ensure_date_task`，管理员 POST 以 `admin_recompute` 调用同一入口；统一参数/筛选函数；顶层返回 coverage、快照状态及 `requested_window_start_date/requested_window_trade_days`，每个股票 DTO 返回自己的 `window_start_date/actual_trade_days`；R10 快照概念与 R11 当前概念分字段；CSV 复用同一集合。
- 产出：查询/状态/导出/重算 API 和类型化响应模型。
- 影响范围：新增 API 前缀，不改变既有接口。
- 边界与异常：无快照/失效只通过统一入口创建或复用任务；筛选空与合法空分码；相关概念失败降级；非法窗口/板块/日期 400。
- 验证方式：逐状态响应断言；短上市股票的 `window_start_date/actual_trade_days` 只出现在对应股票 DTO，顶层仅使用 `requested_window_start_date/requested_window_trade_days`；CSV 行集合等于查询集合且三个概念字段独立；并发返回同一活动任务。
- 完成标准：R2/R5/R6/R8～R11/R16～R18 的前端所需字段齐全且可验证。
- 实际落地情况：新增 `LimitLadderQueryService`，以不可变成功快照为主体，提供交易日、逐状态、统一筛选、分层、摘要、当前可见热点和 CSV 读模型；无快照与失效快照只经 T5 统一入口分别触发首算与刷新，并立即返回可轮询的计算状态。10/20/31/60 日字段仅对快照股票批量读取最多 60 个交易日，不重跑完整连续板长历史；顶层与股票级短历史字段严格分离。快照多概念与当前走势相关概念、截止日分别返回，动态窗口或当前概念局部失败不遮蔽旧成功快照；动态窗口主计算和降级元数据同时失败时仍返回快照主体。新增四个查询/导出端点和 system-only 重算端点，板块别名、ST、一字板、关键词和热点使用同一交集函数，CSV 输出 UTF-8 BOM、复用同一可见集合并防止外部名称触发电子表格公式，非交易日最近交易日保持日期格式。逐状态、非法参数、权限元数据、短上市、筛选聚合、概念分离、双重降级、CSV 安全与集合契约测试通过；本阶段未改页面，因此页面自动化归入 T5 任务中心承接和后续页面阶段。

### T1～T7 当前自审结论

- 阶段边界：提交 `48685f8`～`8ee9f0f` 只落地 T1～T6 与其自审修复；本轮只新增 T7 页面/路由/布局登记与 RBAC 接入，没有提前实现 T8 的筛选、摘要、热点、卡片或导出，也未进入 T9/T10。
- 文档与配套：需求基线未发生变化；本计划、`DESIGN.md`、页面 registry marker、菜单/resource seed、staged 菜单集合和 `limit-ladder-rbac.sql` 已同步 T7 最新事实。当前无新增环境变量或部署参数；存量库迁移使用独立 marker、事务级 advisory lock、插入账本和 `perm_ver` 失效，重算资源锚定 `/data/ingest` system 菜单。
- 验证事实：T1～T6 既有验证事实保持不变；T7 新增后端契约 4 项与 RBAC 通用回归 6 项通过，pageRegistry/响应式/组件配置 55 项通过，生产构建通过。专项 SQL 在本地 PG 实际执行并复跑幂等，授权结果为 normal/tenant_admin 仅 view、system 为 view+recompute；浏览器以 `debug_system` 真实登录，在 1366×768 和 768×1024 验证页面壳，完成分析区收起/展开、设置抽屉、staged 菜单隐藏、直接路由和零控制台告警检查，并生成三张本地截图。完整业务页长期 Playwright 回归仍属于 T12，代表性全市场规模链路仍属于 T11，不在 T7 提前宣告完成。

### T7：可编译页面壳、pageRegistry、静态路由与权限接入

- 状态：已完成。
- 依赖：T6。
- 输入：API 类型、原型、DESIGN 页面模板和 RBAC 接入规范。
- 目标：先建立可编译页面文件和布局登记，再接静态路由、菜单和权限，消除依赖倒置。
- 涉及文件/模块：新增 `LimitLadderView.vue`、`frontend/src/layout/pageRegistry.ts`、`frontend/src/router/index.ts`、`backend/storage/pg_ddl.py`、权限常量/扫描测试、`limit-ladder-rbac.sql`。
- 操作：第一步创建含 `LayoutHost`/状态占位的页面壳并登记 `master-detail`；第二步添加静态路由；第三步 seed 菜单/两资源码和默认 view 授权；前端未完整时使用 staged menu，T10 完成后解除。
- 产出：可编译页面壳、registry 记录、路由、菜单、资源和升级授权 SQL。
- 影响范围：最新行情菜单和默认业务角色；不覆盖管理员运行时配置。
- 边界与异常：seed 只补缺失；recompute 锚定 system 菜单；无角色 fail-closed；页面文件必须先于路由提交。
- 验证方式：每一步均可构建；路由解析、菜单 seed 幂等、默认角色、system-only 防误授和保留管理员配置测试通过。
- 完成标准：R1/R13 的页面入口和权限骨架可独立落地且无编译中间态。
- 实际落地情况：新增 `LimitLadderView.vue` 可编译页面壳，真实消费 `LayoutHost`、`getPageLayout('limit-ladder')`、`MarketMasterDetailWorkspace`、`AppStateBlock` 与 `PageSettingsDrawer`；页面只展示阶段接入状态和主从区收展，不包含 T8 业务控件。`pageRegistry` 以 `master-detail` 登记 action/head、workspace、ladder、analysis 和 settings，静态路由在页面文件存在后接入，`DESIGN.md` marker 同步。PG seed 在“最新行情”下只补 `/limit-ladder`，新增默认业务码 `limit-ladder:view`，将 `limit-ladder:recompute` 锚定 `/data/ingest` system 菜单且不并入业务默认资源；`/limit-ladder` 在 T10 前加入 staged 集合，system 也不收到未完成菜单。专项 SQL 可处理 seed 已先行的存量库，使用 marker/锁/插入账本只补 normal、tenant_admin、system 所需授权并同步 `perm_ver`，重复执行 no-op，不覆盖菜单或资源运行时配置。
- 验证情况：后端 T7 契约 4 项及菜单父链、seed 幂等、菜单/资源配置保留、全量行保留、资源唯一性共 6 项回归通过；前端 registry、responsive、component-config 共 55 项通过，`npm run build` 通过。专项 SQL 已在本地开发 PG 连续执行两次并核对 marker=1、normal/tenant_admin 仅有 view、system 独占 recompute；另在事务内注入冲突 marker，已确认 fail-closed 且回滚后合法 marker 保持不变；后端重启后 `/api/health=200`。交互式浏览器自动化在真实 `debug_system` 登录态完成 1366×768、768×1024 页面截图、分析区收展、设置抽屉、staged 菜单隐藏及直接路由验证，控制台 error/warning 均为空；截图位于本地忽略目录 `agent-works/limit-up-ladder/screenshots/`。

### T8：筛选、摘要、热点、天梯卡片与导出前端

- 状态：待开始。
- 依赖：T6、T7。
- 输入：查询 DTO、原型左侧区域和权限状态。
- 目标：实现天梯主要研究视图及所有展示筛选联动。
- 涉及文件/模块：新增 `frontend/src/api/limitLadder.ts`、`LimitLadder.vue`、`LimitLadderCard.vue`、`LadderHotspots.vue` 及 Vitest。
- 操作：实现窗口、板块、ST、一字板、关键词、热点和 URL 状态；渲染层级/卡片/摘要；短上市股展示实际起始日；CSV 传当前规范化参数；卡片概念只跳板块。
- 产出：页面域组件、前端 DTO、筛选状态模型和导出入口。
- 影响范围：仅连板天梯页面；卡片暂不注册系统组件 kind。
- 边界与异常：未分类、多概念、近似 ST、筛选空、无 sectors 权限、短历史和导出失败。
- 验证方式：组件测试逐项证明卡片字段、起始日、热点取交集、摘要同步、概念点击不改筛选及 CSV 参数一致。
- 完成标准：R7～R11/R15～R18 的主视图结果可观察且无口径分叉。
- 实际落地情况：待实施。

### T9：个人偏好配置闭环

- 状态：待开始。
- 依赖：T7。
- 输入：已存在的 `LimitLadderView.vue` 页面壳、偏好默认值和既有 `usePageSettings`。
- 目标：实现默认值的存储、读取、消费、重置和兼容闭环。
- 涉及文件/模块：`LimitLadderView.vue`、`PageSettingsDrawer` 接入、偏好单测。
- 操作：定义 schema v1；保存窗口、忽略 ST、三板块和分析偏好；实现 URL > 个人默认 > 系统默认；取消不保存、重置后持久化、非法旧值回退。
- 产出：设置抽屉业务区、偏好规范化器和水合流程。
- 影响范围：当前用户 `page/limit-ladder/settings` 一行偏好，不新增表。
- 边界与异常：远端读取失败、未知板块、非法窗口、旧 schema、保存失败。
- 验证方式：重进页面恢复；URL 覆盖个人值；非法值回到 31/忽略ST/全板块；取消不写、重置写入并生效。
- 完成标准：R19 每条验收均有组件或 E2E 断言。
- 实际落地情况：待实施。

### T10：完整页面装配、行情分析、详情返回与窄屏承载

- 状态：待开始。
- 依赖：T7、T8、T9。
- 输入：页面壳、天梯组件、偏好、行情分析组件和 `stockSet`。
- 目标：完成原型所有区域和桌面/窄屏业务闭环。
- 涉及文件/模块：`LimitLadderView.vue`、通用分析抽屉适配、`DESIGN.md` 页面登记。
- 操作：装配 action/main/overlays；行情 `end-date=tradeDate`；768px 窄屏使用全屏 `PageDrawer`；写筛选后有序 stockSet、完整返回 URL、选中项和滚动锚点；完成所有状态块。
- 产出：可发布页面、详情往返上下文和响应式分析承载。
- 影响范围：新增页面及个股详情既有返回机制消费，不改详情布局。
- 边界与异常：日期切换取消旧写回、K线局部失败、无详情权限、筛选后当前股消失、低高度滚动。
- 验证方式：组件与浏览器证明桌面主从、768×1024 全屏抽屉、1100×620 可操作、详情返回恢复全部上下文。
- 完成标准：R12/R14 及原型四个页面功能区全部可操作。
- 实际落地情况：待实施。

### T11：后端综合测试与代表性规模验证

- 状态：待开始。
- 依赖：T1～T7。
- 输入：规则、表、计算、快照、任务、API、RBAC 和确定性夹具。
- 目标：为 R1～R19 后端验收提供可重复证据。
- 涉及文件/模块：`backend/tests/test_limit_ladder_*.py`、确定性夹具及必要 `start.sh` 子命令。
- 操作：覆盖规则、ST 历史、结构化采集终态、coverage、无限连续板回溯、原子发布、失效、三来源活动态幂等、结构化审计主体、interrupted 对账、CSV、权限和规模；构造四类来源顺序并发、前端身份伪造、分界日、20% 板块、75 连板、停牌/缺失、早败后成功日志、历史无日志、合法空、多概念、短上市和 PG 故障。
- 产出：聚焦测试集、规模报告和夹具生命周期脚本。
- 影响范围：测试环境；夹具必须前缀隔离和精确清理。
- 边界与异常：按项目 DuckDB 锁规则停服/恢复；PG 指纹和本地环境门控；失败也清理。
- 验证方式：执行聚焦 pytest；真实入口或等价全市场规模完成加载、门禁、计算、落表和读取，不以 Mock 代替。
- 完成标准：映射表中每个后端验收结果均能指向具体测试。
- 实际落地情况：待实施。

### T12：前端测试、任务中心回归、Playwright 与视觉验收

- 状态：待开始。
- 依赖：T5、T8～T11。
- 输入：完整页面、任务中心前端、确定性 E2E 夹具和原型。
- 目标：证明 R1～R19 的真实点击链路、状态、权限和响应式结果。
- 涉及文件/模块：Vitest、`frontend/e2e/limit-ladder.spec.ts`、任务中心测试、npm scripts/helper。
- 操作：覆盖首次计算、合法空、每类未就绪原因、过期失败、403、窗口/筛选/热点、股票级短历史起始日/实际天数、CSV、偏好、任务中心类型/中断状态/摘要、活动态重算权限、概念直跳、K线、详情返回和滚动恢复。
- 产出：组件测试、Playwright spec、视觉截图和构建结果。
- 影响范围：前端测试与 `dist`；E2E 使用 5181。
- 边界与异常：视口至少 768×1024、1100×620、1366×768、1440×900；稳定 test id；不使用脆弱中文正文或坐标。
- 验证方式：`npm test`、聚焦 Playwright、`npm run build`；断言 768px 全屏 PageDrawer 而非桌面分栏。
- 完成标准：页面、任务中心、原型和四视口均有可重复通过证据。
- 实际落地情况：待实施。

### T13：文档、升级演练、需求映射与最终自审

- 状态：待开始。
- 依赖：T11、T12。
- 输入：真实代码 diff、SQL、测试结果、需求 R1～R31 和设计/RBAC 规范。
- 目标：校准计划状态、完成发布回滚演练并从第三方视角修复遗漏。
- 涉及文件/模块：本计划、`development-trace.md`、架构事实文档、SQL 执行记录、`DESIGN.md`。
- 操作：代码/业务/UI/RBAC/数据一致性自审；执行 SQL 前向/回滚演练；记录实际文件、接口、表、状态和测试；同步任务中心 DuckDB + PG 审计账本的数据边界文档。
- 产出：最终留痕、测试证据、SQL 演练记录和更新后的计划状态。
- 影响范围：文档与发布流程，不引入新业务范围。
- 边界与异常：任何降级、未执行测试或范围偏差必须显式记录，不能批量标完成。
- 验证方式：R1～R31 映射扫描、SQL 静态扫描、`git diff --check`、构建产物同步和事实文档链接检查。
- 完成标准：无 `待确认/阻塞/部分覆盖` 遗留，无未解释超范围，计划与实现一致。
- 实际落地情况：待实施。

## 7. 数据库、SQL、seed 与配置计划

| 路径 | 数据库/用途 | 执行时机 | 影响范围 | 回滚 |
| --- | --- | --- | --- | --- |
| `agent-works/limit-up-ladder/limit-ladder-schema.sql` | DuckDB 新增第 4.1 节七张表、约束和索引 | 部署后端代码前或首次启动前；代码 `init_db` 同样幂等补建 | 新增天梯/ST 当前及历史表，不改现有行情和任务中心 | 无业务数据时可按依赖顺序 drop；已有快照/ST 历史时先备份，代码回滚默认保留表 |
| `agent-works/limit-up-ladder/limit-ladder-audit-ledger.sql` | PG 新增含三种 source、结构化主体/触发身份/请求来源、interrupted 终态的日期任务账本，requested/running 同日活动态部分唯一索引、五类事件审计 outbox，并给 `audit_log` 增加可空 `source_event_key` 与非空唯一索引 | 后端启用任何自动首算或管理员重算入口前 | 平台任务协调/审计辅助表及共享审计表兼容字段；终态释放同日活动槽位；不改 DuckDB 任务表 | 先完成/导出未投递 outbox，再删部分唯一索引、审计唯一索引/字段及辅助表；旧审计记录不受影响 |
| `agent-works/limit-up-ladder/limit-ladder-rbac.sql` | PG 新增菜单、两资源码、normal/tenant_admin 初始 view 授权、marker 和 `perm_ver` 失效 | 前后端同批发布；事务 + advisory lock 执行一次 | 全局菜单/RBAC；受影响用户需重新登录 | 依据 marker/账本只删迁移插入且仍存在的授权与节点；发现账本外自定义角色引用则拒绝级联 |
| `agent-works/limit-up-ladder/rollback-limit-ladder.sql` | PG RBAC/审计辅助结构确定性回滚和 DuckDB 保留/删除说明 | 仅发布回退且人工确认后 | 菜单、权限、审计辅助结构和领域表 | 必须显式确认 marker；先处理未投递 outbox；默认保留 DuckDB 快照/ST 历史，可恢复代码后继续使用 |
| `backend/storage/ddl.py` | 新库及本地启动的 DuckDB 幂等 seed | 应用初始化 | 新领域表 | 代码回滚不主动删表 |
| `backend/storage/pg_ddl.py` | 新库菜单/资源默认值和业务角色集合 | PG 初始化/启动 seed | 新库默认权限；存量只补缺失身份，不覆盖运行时配置 | 移除代码默认不会删除存量行，真正回滚使用专项 SQL |

- 个人偏好复用既有 `user_preference`，不新增偏好表；PG 新增重算账本/outbox，并给共享审计表增加兼容的幂等事件键。
- 本期不新增环境变量；规则版本以代码稳定常量写入快照和审计。
- SQL 文件实施时必须含前置条件、事务边界、字段说明、影响、验证查询和回滚说明，并通过菜单覆盖静态扫描。

## 8. 测试与验证计划

- 单元测试：市场规则、ST 质量、连续板、窗口次数、固定排序、行业/概念聚合、参数规范化；完成情况：T1/T3 已验证市场规则、ST 质量、75 日连续板、固定窗口/短上市、排序与行业/概念聚合，T6 已验证窗口/板块/ST/一字板/关键词/热点参数规范化和交集筛选。
- 存储/集成：DDL 幂等、ST 当前/历史追溯、coverage 每个原因码、合法空、版本原子切换、失败保留、日期失效、四类来源顺序并发任务复用、结构化主体不可伪造、PG 账本对账、规模落表；完成情况：T2 已验证 DDL/账本约束，T3 已验证 ST 追溯，T4 已验证 coverage、结构化采集终态、合法空、不可变版本、事务回滚、失败保留和日期失效，T5 已验证四种来源顺序共享活动命令、权威主体/请求快照、终态释放、重启 interrupted 对账和审计唯一；规模落表随 T11 实施。
- 接口：全部端点的 200/400/403/业务状态码、相关概念独立字段、CSV；完成情况：T6 已验证新增端点的 200/400、查看 403 守卫、重算 system-only 元数据、逐状态业务码、相关概念独立字段和 CSV；菜单资源实际授权随 T7 验证。
- 权限：菜单树、路由守卫、`limit-ladder:view` 默认角色、`limit-ladder:recompute` system-only、关联权限、seed 保留管理员配置；完成情况：T7 已验证菜单/路由骨架、view 默认角色、recompute system-only、seed 幂等和运行时配置保留，关联板块/个股权限随 T10/T12 验证。
- 页面：原型各区域、全部状态、短上市起始日、筛选联动、偏好闭环、分析局部失败、板块直跳、详情返回；完成情况：待验证。
- 组件/配置：pageRegistry 被真实消费且无重复登记；页面域卡片不误注册系统 kind；偏好和布局配置实际生效；完成情况：待验证。
- 响应式/无障碍：768×1024、1100×620、1366×768、1440×900 四视口，键盘聚焦、aria、非颜色提示、低高度滚动；完成情况：待验证。
- 回归：每日榜单、个股详情、板块详情、用户偏好、任务中心 `TaskType/TASK_LABEL/筛选/摘要` 和权限扫描；完成情况：T5 已验证任务中心类型标签、筛选、系统来源、终态摘要和调度页不暴露内部任务，其余随对应阶段验证。
- 构建：改动 `frontend/src` 后必须执行 `cd frontend && npm run build && cd ..`；完成情况：T5 构建已通过，后续前端阶段仍须重复执行。
- 原型一致性：实现对照 `prototypes/limit-up-ladder.html`，黄色原型批注不进入正式页面；卡片概念点击只跳板块行情；完成情况：待验证。
- 需求映射：自动检查 R1～R31 均在第 5 节且状态合法；完成情况：T1～T7 关联 R1～R13/R15～R18 状态已同步，其中跨阶段需求保持“进行中”，其余待后续阶段。

## 9. 发布与回滚

### 9.1 发布前检查

1. 数据库备份并验证 PG 指纹、DuckDB 独占写条件。
2. 执行/验证三份前向 SQL，确认领域表、审计账本和菜单/资源码无身份冲突。
3. 后端规则、快照、权限测试通过；前端 Vitest、聚焦 E2E、构建通过。
4. system、normal、tenant_admin 和无角色用户分别验收最小权限状态。
5. 确认前端路由、pageRegistry、DESIGN marker 同批完成后再解除 staged menu 门控。

### 9.2 发布顺序

1. 停止后端以释放 DuckDB 写锁并备份数据。
2. 依次执行 DuckDB schema SQL、PG audit-ledger SQL、PG RBAC SQL，并运行各自验证查询。
3. 发布后端并健康检查；确认任务类型和接口路由已装配。
4. 发布前端源码与 `dist`；重新登录刷新 `perm_ver` 权限。
5. 以 system 首算一个已完整交易日，再以普通角色完成只读页面验收。

### 9.3 回滚

- 前端/后端代码回退后，默认保留新增 DuckDB 表，不影响旧模块。
- 执行专项 RBAC 回滚前先检查自定义角色引用；有账本外引用时停止并由管理员处理。
- 已生成快照不自动删除；如确认永久撤销且已备份，才按 SQL 注释的逆依赖顺序删表。
- 回滚后验证 `/board`、`/stocks`、`/sectors`、任务中心和权限解析未受影响。

## 10. 风险、假设与待确认项

### 10.1 风险

- 历史 ST 仅能近似时会影响旧日期涨停判断；通过质量标识、页面提示和后续精确回填失效收口。
- 行业统计使用 `stock_basic.industry`，与同花顺行业板块并非同一语义；只有名称唯一精确匹配时才提供详情跳转，避免为追求跳转而错误归属。
- 首次访问可能触发全市场计算；需要批量读取、同日任务幂等和代表性规模验证，避免阻塞请求线程。
- 快照失效挂点分散在采集、修复、规则和归属治理链路；遗漏会导致旧结果静默有效，T4/T11 必须做失效矩阵测试。
- 任务中心进度表仍在 DuckDB；它是现有平台事实，若未来迁移 PG 需独立项目，不能在本功能中半迁移。

### 10.2 假设

- 上市板块仍只支持主板、创业板、科创板，不含北交所。
- 当前 `stock_board_correlation` 的概念冠军是 R11 唯一最新走势相关概念来源。
- 概念跳转以 `board_dict.board_code` 为稳定引用；行业仅在 `stock_basic.industry` 名称唯一精确匹配行业字典时获得跳转引用；“未分类”和非唯一行业不跳转。
- 页面查询结果规模是单日涨停股票集合，可在服务层合并 DuckDB 快照与当前相关概念，不构成跨库大结果集风险。

### 10.3 待确认项

无阻塞或非阻塞确认项。实现阶段如发现数据源无法区分特殊无涨跌幅日，应按 R3 拒绝发布并回到需求确认，不得自行降级为普通涨停比例。
