# 开发计划：交易纪律记录与履约打卡

## 1. 需求来源与目标

- 需求文档：[requirement.md](./requirement.md)，状态为“业务闭环及审查阻塞项已确认，可作为开发计划输入”。
- 页面原型：[prototypes/trading-discipline-workbench.html](./prototypes/trading-discipline-workbench.html)，已完整读取并作为 P1 工作台与 P2 用户中心快捷卡片的布局、状态和交互依据。
- 功能目标：建设私人交易规则的草稿/正式版本/未来交易日生效闭环，完成按“规则 + 交易日”的履约打卡、操作记录、未履约原因、历史修订和全局快捷无操作履约。
- 本次不做：R18-R25 所述打卡服务端草稿、账户快照/资金流水、AI 或规则引擎结果、自动裁决、图表、券商同步、公开分享。
- 计划输出目录：`agent-works/trading-discipline-checkin/`。
- 准入结论：无剩余阻塞项；需求和原型已明确流程、数据、权限、接口验收与上线边界。

## 2. 当前项目依据

| 依据 | 当前事实 | 计划承接 |
| --- | --- | --- |
| `backend/main.py` | FastAPI 路由集中导入并 `include_router`；应用启动调用 `init_pg_db()` | 新增 `backend/api/trade_discipline.py` 并显式注册；DDL/seed 进入既有启动链路 |
| `backend/storage/pg_ddl.py` | PG 表、索引、菜单、资源和存量授权回填均幂等维护 | 新表进入 `_ASSET_TABLES`/`ASSET_PK`；菜单、资源、授权 marker 与 `perm_ver` 同事务 |
| `backend/auth/constants.py` | `BUSINESS_RESOURCE_CODES` 决定普通业务默认资源集合 | 加入四个已确认交易纪律功能码，不改登录基线码 |
| `backend/auth/context.py`、`backend/storage/asset_repository.py` | 归属来自请求上下文，PG 私人资产按 `tenant_id + owner_user_id` 隔离 | 新仓库所有查询、锁、冲突、更新和删除均显式带归属 |
| `backend/api/stocks.py`、DuckDB `stock_basic` | `/api/stocks` 含行情能力且受 `stocks:view` 保护 | 新建 R31 轻量端点，只复用 `stock_basic` 查询，不复用原权限或完整响应 |
| DuckDB `daily_bar`、`trade_calendar` | 已有行情日期与未来开市日是两套口径 | 打卡日期继续读 `/api/data/trade-dates`；生命周期生效日只读未来 `trade_calendar` |
| `frontend/src/router/index.ts`、`SideMenu.vue` | 静态路由 + 后端授权菜单双重接入 | 新增 `/trade-discipline` 路由；菜单继续由 `/me` 下发 |
| `frontend/src/layout/pageRegistry.ts`、`LayoutHost.vue` | 非公开 View 必须登记并真实消费布局 | 登记 `trade-discipline` workbench，使用 `LayoutHost` 和 overlay 设置抽屉 |
| `PageSettingsDrawer`、`useRemoteLayoutConfig`、`usePageSettings` | 已有 page/user 配置保存、读取、重置链路 | 密度走布局配置；历史 `pageSize` 走现有组件字段，不新增尺寸偏好 |
| `AppDataTable`、`AppTableColumn`、`AppPagination`、`AppStateBlock`、`PageDrawer` | 已有表格、分页、四态和页面内抽屉 | 历史列表、修订详情、四态直接复用，不手写平行实现 |
| `frontend/src/App.vue` | 已有 440px 视口级用户中心抽屉 | 仅增加快捷卡片、头像状态点和确认动作，不创建第二个全局抽屉 |
| `DESIGN.md`、`page-template.md` | 页头 `flex-start`、查询自动触发、页面登记和三视口为硬约束 | 页面实现与 E2E 逐项验证；同步 DESIGN page-registry marker |
| 测试体系 | pytest、Vitest、Playwright；前端源码改动后必须 build | 分层补仓库/服务/API/组件/E2E，并遵守 DuckDB 锁和 5181 端口规则 |

当前无法直接证明生产 PG 中是否已有自定义角色或人工授权，故存量授权迁移必须记录“实际插入行”，回滚不得猜测删除既有合法授权。

## 3. 实施范围

### 3.1 必须实现

| 需求编号 | 实施内容 | 对应任务 | 状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| R1 | 私人规则生命周期、名称唯一、明细启用/顺序/换行 | T1、T2、T6、T10-T12 | 待开始 | DDL/服务单测 + 页面 E2E |
| R2 | 本金与启用选股规则资金上限校验 | T2、T6、T10-T11 | 待开始 | 金额边界参数化测试 |
| R3 | 正式版本连续生成且历史不可变 | T1、T2、T6、T10 | 待开始 | 发布事务与历史快照测试 |
| R4 | 规则 + 交易日唯一打卡 | T1、T3、T7、T10 | 待开始 | 唯一性/幂等测试 |
| R5 | 四种履约/操作组合 | T3、T7、T10-T12 | 待开始 | 服务组合测试 + E2E |
| R6 | 多笔同股操作与股票关联 | T3、T4、T7、T10-T12 | 待开始 | API/页面操作行测试 |
| R7 | 每笔分别关联具体选股与方向匹配买卖规则 | T3、T7、T10-T12 | 待开始 | 候选 0/1/多条测试 |
| R8 | 可选成交事实与完整度 | T1、T3、T7、T10-T11 | 待开始 | 字段边界与展示测试 |
| R9 | 历史筛选、详情、不可变修订 | T1、T3、T8、T10-T12 | 待开始 | 分页/修订/API/E2E |
| R10 | 真实交易日选择与校验 | T3、T4、T5、T7、T10-T12 | 待开始 | 空日历/非交易日/未来日测试 |
| R11 | 私人归属和跨用户隔离 | T1-T4、T8、T10、T12 | 待开始 | 跨用户/跨租户 403/404 测试 |
| R12 | 用户中心摘要、状态点与跳转 | T4、T9、T11-T12 | 待开始 | App 组件测试 + 三视口 E2E |
| R13 | 快捷无操作已履约 | T3、T4、T9、T10-T12 | 待开始 | 幂等/冲突/API/E2E |
| R14 | 原始事实稳定、派生能力不反写 | T1-T3、T10 | 待开始 | 外键/不可变仓库测试与数据契约审查 |
| R15 | 三页签、主从布局和响应式闭环 | T5-T8、T11-T12 | 待开始 | 布局契约 + 三视口 Playwright |
| R26 | 单选可输入原因、自动新增、行内删除 | T1、T3、T7、T10-T12 | 待开始 | 原因事务/交互 E2E |
| R27 | 未履约详细说明必填并保留换行 | T1、T3、T7-T8、T10-T12 | 待开始 | API/页面/历史展示测试 |
| R28 | 路由、菜单、四功能码、默认角色授权 | T1、T4-T9、T10-T12 | 待开始 | seed/扫描/守卫/按钮权限测试 |
| R29 | pageRegistry、LayoutHost、维护矩阵 | T5、T11-T12 | 待开始 | pageRegistry/layout contract |
| R30 | 补录按履约日有效版本解析 | T1-T4、T7、T10、T12 | 待开始 | 激活事件边界测试 + E2E |
| R31 | 专用轻量股票搜索 | T4、T7-T8、T10-T12 | 待开始 | 权限、上限、防抖、迟到请求测试 |
| R32 | 页面设置保存、读取、消费、恢复默认 | T5、T8、T11-T12 | 待开始 | 偏好/组件/E2E |
| R33 | 通用表格、分页、状态、抽屉复用 | T5、T8、T11-T12 | 待开始 | 组件依赖与布局契约审查 |
| R34 | 加载、空、错误、无权限四态 | T5-T9、T11-T12 | 待开始 | 独立状态组件测试 + E2E |
| R35 | 每主体至多一个规则草稿、乐观锁、放弃/发布 | T1、T2、T6、T10-T12 | 待开始 | 并发 409/事务/恢复 E2E |
| R36 | 激活时间、下一真实交易日、双状态展示 | T1-T4、T6-T7、T10-T12 | 待开始 | 时间参数化 + 双状态 E2E |

### 3.2 可选增强

| 需求编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R16 | 复制规则 | 本次纳入 | 待开始 | T2、T6、T10-T12 | 副本为无版本号的新主体草稿，可选复制正式版或草稿内容 |
| R17 | 页面离开前未保存提醒 | 本次纳入 | 待开始 | T5-T8、T11-T12 | 打卡无服务端草稿；规则可保存工作草稿 |
| R18 | 打卡服务端自动保存草稿 | 后续建议 | 跳过 | - | 创建、过期、冲突与清理策略未进入本期，且 D9 明确本期不建 |
| R19 | 账户每日快照与入金/出金流水 | 后续建议 | 跳过 | - | 待收益曲线需求启动后独立设计，避免误称本期数据足以算完整收益 |
| R20 | AI/规则引擎评估实体与生成链路 | 后续建议 | 跳过 | - | 本期仅提供稳定关联键和不可变事实，不接模型或判断器 |

### 3.3 暂不实现

| 需求编号 | 状态 | 原因 |
| --- | --- | --- |
| R21 | 跳过 | 自由文本规则尚无自动裁决口径 |
| R22 | 跳过 | 模型、输入范围、成本与隐私策略未立项 |
| R23 | 跳过 | 图表依赖后续数据完整度与账户快照 |
| R24 | 跳过 | 外部券商授权、对账和安全边界未确认 |
| R25 | 跳过 | 本期资产明确为私人，不提供公开、分享或监督 |

## 4. 技术方案

### 4.1 模块与数据流

- 后端新增 `trade_discipline_repository.py` 负责 PG 归属过滤、锁和事务写入；`trade_discipline_service.py` 负责规则/草稿/版本/激活事件/打卡修订编排；API 层只做模型解析、权限和错误映射。
- 规则正文、用户自评、操作与每次修订作为原始事实；正式版本、历史修订和激活事件只增不改。未来 AI/规则引擎只能通过 `rule_id + version_no`、`checkin_id + revision_no` 关联。
- DuckDB 只读两类参考事实：`stock_basic` 用于 R31，`trade_calendar` 用于下一真实交易日；PG 与 DuckDB 分开查询后在服务层组合，禁止跨库 JOIN。
- 页面通过 `frontend/src/api/tradeDiscipline.ts` 访问统一契约；`useTradeDisciplineSummary.ts` 提供页面与 `App.vue` 共享的按需摘要刷新/失效，不做轮询。
- 同一规则草稿按 `draft_revision` 乐观锁；打卡修正按当前 `revision_no` 乐观锁；冲突统一返回 HTTP 409 和机器可识别错误码，前端保留输入。

### 4.2 数据模型

| 表/约束 | 关键设计 |
| --- | --- |
| `trade_discipline_rule` | 主体状态、最新正式版本指针、时间、软删除；复合主键含归属 |
| `trade_discipline_rule_name_claim` | 以 `(tenant_id, owner_user_id, normalized_name)` 唯一占用正式名/草稿拟用名；解决跨 `rule`/`draft` 表并发重名，发布时原子换名，归档仍占名 |
| `trade_discipline_rule_draft` + 两类 draft 明细 | 每主体唯一草稿、修订号、来源版本；保存启用态、顺序与原始换行 |
| `trade_discipline_rule_version` + 两类正式明细 | `(归属, rule_id, version_no)` 唯一；正式行不可更新；启用明细顺序唯一且类型受 CHECK 约束 |
| `trade_discipline_rule_activation` | `publish/archive/restore` 不可变事件，保留 `occurred_at`、`activated_at`、`effective_from_trade_date` 与版本引用 |
| `trade_discipline_checkin` | `(归属, rule_id, trade_date)` 唯一，保存当前修订指针 |
| `trade_discipline_checkin_revision` | 规则版本、自评、无操作、详细说明、复盘说明、首次/修正时间；不可变 |
| `trade_discipline_reason`、`trade_discipline_violation` | 个人原因软删除；修订保存原因码/引用和名称快照，每个 breached 修订恰好一条 |
| `trade_discipline_operation` | 每修订多条、稳定顺序、股票名快照、方向、两个具体规则引用及可空财务字段；复合外键锁定同一规则版本 |

金额使用 `NUMERIC` 定点数；交易日用 `DATE`；服务端事件时间用 `TIMESTAMPTZ`。索引覆盖归属下规则列表、激活事件解析、历史日期倒序、股票/原因筛选和修订详情。正文只按普通文本序列化，不渲染 HTML。

### 4.3 接口与权限契约

四项固定功能码为 `trade-discipline:view`、`trade-discipline:rule-manage`、`trade-discipline:checkin-view`、`trade-discipline:checkin-submit`；下表为节省篇幅使用末段简称。system 恒过，normal/tenant_admin 新库默认全授，既有库由 T1 的显式迁移补齐；自定义角色不自动扩权。

| 接口组 | 主要端点 | 权限 | 事务/异常 |
| --- | --- | --- | --- |
| 摘要 | `GET /api/trade-discipline/summary` | `view` + `checkin-view` | 日历为空返回可区分错误，不泄露正文 |
| 规则读写 | `GET/POST /rules`、`GET /rules/{ref}`、`PUT/DELETE /rules/{ref}/draft` | 读用 `view`，维护用 `rule-manage` | 名称/草稿冲突 409；输入保留 |
| 生命周期 | `POST /rules/{ref}/publish|archive|restore|copy`、`DELETE /rules/{ref}` | `rule-manage` | 发布/事件/指针/草稿删除同事务；日历缺失不提交 |
| 打卡 | `GET /checkins/current`、`POST /checkins`、`POST /checkins/{ref}/amendments` | 读 `checkin-view`，写 `checkin-submit` | 修订及明细同事务；版本/修订冲突 409 |
| 历史 | `GET /checkins`、`GET /checkins/{ref}/revisions/{no}` | `checkin-view` | 服务端筛选、排序、分页；归属不匹配不泄露存在性 |
| 原因 | `GET /reasons`、`DELETE /reasons/{ref}` | 读 `checkin-view`，删 `checkin-submit` | 自定义原因随打卡事务新增；删除为软删除 |
| 快捷动作 | `POST /checkins/quick-no-operation` | `checkin-submit` | 服务端固定已履约+无操作，重复请求幂等，冲突返回现有引用 |
| 股票选择 | `GET /stock-options?q=&limit=` | `checkin-submit` | 空查询拒绝；`limit<=20`；仅代码/名称/板块/行业 |

API 不接收 `tenant_id`、`owner_user_id`、`activated_at` 或生效日。日志只记动作、对象引用、状态和错误码，不记录完整规则正文、操作清单或详细说明。

### 4.4 页面 P1：交易纪律工作台

- 原型文件：`prototypes/trading-discipline-workbench.html`。
- 页面结构：`workbench` 外层三页签；今日打卡与规则管理共用 feature-scoped 左侧规则轨道 + 右侧工作区；历史为列表；页头动作区与标题顶部对齐。
- 滚动：`LayoutHost` 管页面主区；主从区在 1100px 提前变为上下结构；表单不横向滚动，只有历史表格内部横向滚动；详情抽屉正文内滚。

| 页面功能点/原型区域 | 对应需求 | 技术实现 | 组件/模块 | 数据、状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- |
| 页头、最新交易日、三页签、页面设置 | R15、R29、R32、R34 | registry slots：`toolbar/body/history/settings`；tab 为会话态 | `LayoutHost`、`PageSettingsTrigger/Drawer` | 初载四态互斥；设置失败保留当前内容 | T5 |
| 今日规则状态轨道 | R4、R15、R30、R36 | 按目标交易日解析有效版本和待打卡状态，不按管理状态猜测 | `RuleMasterList`（feature 共享） | 摘要局部加载/错误/重试；无规则引导新建 | T5、T7 |
| 履约日期与自评/无操作 | R4、R5、R10、R17 | 复用交易日能力并扩展可观察加载错误；上下文切换走脏确认 | `TradeDatePicker`、`PageSegmented` | 无日历/无有效版本阻止提交；切无操作二次确认清行 | T7 |
| 未履约原因与详细说明 | R26、R27 | `el-select` filterable/allow-create 单选；个人行带删除；独立 textarea | `ViolationReasonCombobox` | 内置不可删；当前项删除后清空；失败保留输入 | T7 |
| 多条操作记录 | R6-R8、R31 | 稳定 operation key；方向联动；财务字段可空、非负 | `TradeOperationEditor`、`StockOptionSelect` | 股票搜索防抖/取消迟到请求；候选 0/1/多分支 | T7 |
| 提交/修正 | R4-R9、R30 | 首次与修正分端点；提交后刷新表单、轨道和全局摘要 | 表单命令区 | loading 防重复；409 保留输入并提示刷新 | T7 |
| 规则管理左侧列表 | R1、R15、R35、R36 | 与今日打卡复用轨道结构，显示当前有效与管理动作双状态 | `RuleMasterList` | 列表失败不销毁右侧编辑；空态创建首套规则 | T6 |
| 规则编辑工作区 | R1-R3、R17、R35 | 右侧直接编辑；多行内容自动换行/可当次纵向调整；不使用抽屉 | `TradeRuleEditor` | 保存草稿、取消未保存、放弃草稿、发布；409 保留表单 | T6 |
| 明细资金/类型/顺序 | R1、R2、R3 | 启用项实时汇总；买卖一级/二级受控；排序持久化 | 规则明细子组件 | 停用项不参与发布条件；后端再次校验 | T6 |
| 复制、归档、恢复、删除 | R1、R16、R35、R36 | 命令按钮权限化；复制草稿/正式版先选择；待生效双状态 | 规则命令区、`ElMessageBox` | 归档前处理草稿；日历缺失/冲突不改变原状态 | T6 |
| 历史筛选和表格 | R9-R11、R31-R34 | 输入/改选自动查询并重置第 1 页；仅保留重置 | `AppSearchInput`、`AppDataTable`、`AppPagination` | 保留筛选；局部 loading/empty/error/permission | T8 |
| 修订详情与发起修正 | R9、R17、R27、R33 | 页面内 `PageDrawer` 展示任意修订并跳转打卡页加载修正 | `PageDrawer` | 原始换行和两个规则快照完整展示；加载失败可重试 | T8 |
| 响应式与低高度 | R15、R34 | 1100×620 上下主从；1366/1440 双栏；无固定视口高度 | 页面样式/token | 无整页横向溢出、动作始终可达 | T5-T8、T12 |

逐项权限与验证补充：

| 原型/页面区域 | 权限承接 | 可观察验证 |
| --- | --- | --- |
| 页头、页签、设置入口 | 页面进入需 `trade-discipline:view`；设置保存沿用登录基线 `layout:user-config` | 路由守卫、设置保存/重载/恢复默认和四态组件测试 |
| 今日规则轨道 | 摘要同时要求 `view + checkin-view` | 待打卡计数、历史日期有效版本、局部错误重试 E2E |
| 日期、自评、无操作 | 读取 `checkin-view`；可编辑/提交需 `checkin-submit` | 未来/非交易日/空日历、四组合和脏切换 E2E |
| 原因、详细说明 | 候选读 `checkin-view`；删除/随提交新增需 `checkin-submit` | 单选、allow-create、行内删除、换行和事务回滚测试 |
| 操作记录与股票搜索 | 查看既有操作需 `checkin-view`；编辑、R31 搜索和提交需 `checkin-submit` | 同股多笔、0/1/多候选、方向切换、防抖/迟到请求测试 |
| 打卡提交/修正 | `checkin-submit` | loading 防重、409 保留输入、提交后三处摘要联动 E2E |
| 规则列表/双状态 | 页面可见需 `view`；进入维护态需 `rule-manage` | 正式 vN、草稿、待生效动作同时展示测试 |
| 规则编辑、明细和资金 | `rule-manage`；无该码不渲染写命令 | 启用态/顺序/换行回显、金额边界、二级类型测试 |
| 复制/发布/归档/恢复/删除 | `rule-manage` 且按钮挂 `v-permission` | 各动作 loading、防重复、日历缺失和冲突 E2E |
| 历史筛选/表格 | `checkin-view` | 全筛选项自动查询、分页不重置、错误/空/无权状态测试 |
| 修订详情/发起修正 | 详情 `checkin-view`；发起和提交修正需 `checkin-submit` | 任意修订快照、抽屉内滚、只读态和修订递增 E2E |
| 响应式整体 | 沿用页面及区域功能码，不因视口降级放宽权限 | 1100×620、1366×768、1440×900 截图/溢出/可操作性断言 |

### 4.5 页面 P2：用户中心全局抽屉增强

需求明确不单独生成原型；替代依据是 P1 原型中的 `userMask/quick` 区域和现有 `App.vue` 440px 抽屉。

| 页面功能点 | 对应需求 | 技术实现 | 状态/权限/异常 | 任务 |
| --- | --- | --- | --- | --- |
| 头像待打卡状态点 | R12、R28 | `App.vue` 消费共享摘要；仅成功且待打卡时显示 | 无权、失败、无启用规则均不显示误导红点 | T9 |
| 身份卡下今日纪律卡 | R12、R34 | `TradeDisciplineQuickCard` 展示日期、完成/待办和规则行 | 打开抽屉按需加载；加载/空/完成/待办/错误/无权分支 | T9 |
| 去打卡/管理规则 | R12、R28 | 关闭抽屉并带 `tab/rule_ref/trade_date` 会话查询参数跳转 | 路由参数不写偏好；无页面权限不展示 | T9 |
| 无操作履约确认 | R13、R28 | 对话框只确认规则和日期，调用专用幂等端点 | 需 submit 权限；冲突转正式页；失败保留现场重试 | T9 |
| 摘要联动 | R12、R13 | 快捷成功或页面提交后 invalidate + refresh | 不做后台轮询 | T9 |

逐项验证：头像点和卡片展示要求 `view + checkin-view`，快捷按钮再要求 `checkin-submit`；分别使用全权限、仅查看、缺少 checkin-view、缺少 submit 和无角色账号验证。Playwright 逐项断言抽屉加载/空/完成/待办/错误/无权状态、查询参数跳转、确认内容、重复提交幂等、冲突转正式页以及失败后可重试。

### 4.6 组件资产与配置闭环

| 页面/区域 | 运行时组件 | 布局/配置种类 | 注册与字段 | 规范更新 | 真实消费与验证 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 工作台壳 | 复用 `LayoutHost`、`AppStateBlock` | 复用 workbench/toolbar/section/settings-drawer | 新增 pageRegistry 页面；复用 `density` | 同步 DESIGN marker | 页面读取 effective layout 并渲染设置入口 | T5、T11 |
| 历史列表 | 复用表格、列、分页、搜索 | 复用 data-table | `history` 消费 `pageSize`、`border` | 不新增字段定义 | 保存、重载、分页真实应用，非法值回退 20 | T5、T8、T11 |
| 修订详情 | 复用 `PageDrawer` | overlay detail | registry overlay，不新增 kind | 否，已有清单 | 页面边界、正文内滚、关闭与修正跳转 | T8、T11 |
| 规则轨道/操作编辑/原因下拉 | 新增 feature-scoped 组件并在两个页签消除重复 | 不登记系统组件种类 | 不新增通用组件配置字段 | 不进入全局组件清单；仅本业务内部复用 | View/组件测试覆盖事件与状态契约 | T6-T8、T11 |
| 用户快捷卡 | 新增业务组件，由现有 `App.vue` 全局抽屉消费 | 不涉及页面布局种类 | 不写页面偏好 | 不改变全局抽屉组件边界 | App 组件测试与任意页面 E2E | T9、T11-T12 |

本期不新增布局原型、系统组件 kind、`COMPONENT_FIELD_DEFS` 字段或后端布局字段规则；规则编辑宽度/高度绝不进入配置或 `user_preference`。

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R1 | 规则主体、明细、生命周期与页面管理 | T1、T2、T6、T10-T12 | 待开始 | 一致 | 含名称唯一、启用态、顺序、换行 |
| 必须实现 | R2 | 前后端定点资金校验 | T2、T6、T10-T11 | 待开始 | 一致 | 仅启用选股项参与 |
| 必须实现 | R3 | 不可变正式版本与连续版本号 | T1、T2、T10 | 待开始 | 一致 | 无实质变化不发新版 |
| 必须实现 | R4 | 规则日唯一打卡身份 | T1、T3、T7、T10 | 待开始 | 一致 | 修正不新增平行记录 |
| 必须实现 | R5 | 四种组合 | T3、T7、T10、T12 | 待开始 | 一致 | 全部正式提交 |
| 必须实现 | R6 | 多操作与股票关联 | T3、T4、T7 | 待开始 | 一致 | 同股不去重 |
| 必须实现 | R7 | 两个具体规则单选关联 | T3、T7、T10-T12 | 待开始 | 一致 | 0/1/多候选闭环 |
| 必须实现 | R8 | 可选成交字段和完整度 | T1、T3、T7 | 待开始 | 一致 | 不伪造收益精度 |
| 必须实现 | R9 | 历史、详情、修正 | T1、T3、T8、T10-T12 | 待开始 | 一致 | 旧修订不可变 |
| 必须实现 | R10 | 真实交易日 | T3-T5、T7、T10-T12 | 待开始 | 一致 | 日历失败时禁止打卡 |
| 必须实现 | R11 | 私人归属 | T1-T4、T10 | 待开始 | 一致 | 管理员也不扩大范围 |
| 必须实现 | R12 | 全局摘要与跳转 | T4、T9、T11-T12 | 待开始 | 一致 | 复用现有抽屉 |
| 必须实现 | R13 | 快捷无操作履约 | T3、T4、T9、T10-T12 | 待开始 | 一致 | 服务端固定语义 |
| 必须实现 | R14 | 原始事实/派生边界 | T1-T3、T10 | 待开始 | 一致 | 不创建 AI 调用链 |
| 必须实现 | R15 | 工作台主从与三页签 | T5-T8、T12 | 待开始 | 一致 | 规则编辑不用抽屉 |
| 可选增强 | R16 | 复制正式版或草稿为新未发布主体 | T2、T6、T10-T12 | 待开始 | 一致 | 本次纳入 |
| 可选增强 | R17 | 打卡/规则未保存保护 | T5-T8、T11-T12 | 待开始 | 一致 | 本次纳入 |
| 可选增强 | R18 | 暂不纳入 | - | 跳过 | 未覆盖 | D9 明确无服务端打卡草稿 |
| 可选增强 | R19 | 暂不纳入 | - | 跳过 | 未覆盖 | 收益域另立需求 |
| 可选增强 | R20 | 暂不纳入 | - | 跳过 | 未覆盖 | AI/规则引擎另立需求 |
| 暂不实现 | R21 | 不开发自动履约裁决 | - | 跳过 | 未覆盖 | 本期人工自评 |
| 暂不实现 | R22 | 不开发 AI 分析 | - | 跳过 | 未覆盖 | 模型边界未立项 |
| 暂不实现 | R23 | 不开发图表 | - | 跳过 | 未覆盖 | 数据成熟后另做 |
| 暂不实现 | R24 | 不接券商 | - | 跳过 | 未覆盖 | 外部授权未确认 |
| 暂不实现 | R25 | 不公开/分享/监督 | - | 跳过 | 未覆盖 | 私人资产范围 |
| 必须实现 | R26 | 单选可输入原因与行内删除 | T1、T3、T7、T10-T12 | 待开始 | 一致 | 新原因随打卡事务新增 |
| 必须实现 | R27 | 独立详细说明 | T1、T3、T7-T8 | 待开始 | 一致 | 必填且保留换行 |
| 必须实现 | R28 | 路由/RBAC/默认角色闭环 | T1、T4-T9、T10-T12 | 待开始 | 一致 | 存量授权可回滚 |
| 必须实现 | R29 | 页面登记与 LayoutHost | T5、T11-T12 | 待开始 | 一致 | 同步维护矩阵 |
| 必须实现 | R30 | 历史日有效版本解析 | T1-T4、T7、T10-T12 | 待开始 | 一致 | 草稿/未生效/归档不可绑定 |
| 必须实现 | R31 | 轻量股票端点 | T4、T7-T8、T10-T12 | 待开始 | 一致 | 不扩大 stocks:view |
| 必须实现 | R32 | 设置闭环 | T5、T8、T11-T12 | 待开始 | 一致 | 密度 + 历史分页真实消费 |
| 必须实现 | R33 | 通用组件复用 | T5、T8、T11-T12 | 待开始 | 一致 | 无页面私有表格/抽屉体系 |
| 必须实现 | R34 | 四态 | T5-T9、T11-T12 | 待开始 | 一致 | permission 为 error 变体 |
| 必须实现 | R35 | 工作草稿生命周期 | T1、T2、T6、T10-T12 | 待开始 | 一致 | 正式版继续履约 |
| 必须实现 | R36 | 下一交易日生效与双状态 | T1-T4、T6-T7、T10-T12 | 待开始 | 一致 | 发布/归档/恢复均覆盖 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：PG 模型、索引、SQL 与 RBAC 迁移

- 状态：待开始
- 依赖：无。
- 涉及文件：`backend/storage/pg_ddl.py`、`backend/auth/constants.py`、`agent-works/trading-discipline-checkin/trading-discipline-schema.sql`。
- 目标：落地第 4.2 节实体、复合外键/CHECK/唯一索引，并完成菜单、四资源码、新库默认授权和存量 normal/tenant_admin 回填。
- 操作：新增 DDL/ASSET_PK/索引；seed 一级菜单 `/trade-discipline`；新增 marker 化授权迁移，记录实际插入的菜单和资源授权并同事务 bump `perm_ver`。
- 产出：可重复启动的 schema/seed 与等价人工复核 SQL（含确定性回滚）。
- 影响范围：PG public schema、RBAC 默认角色；不改 DuckDB 数据。
- 边界与异常：表间 FK 全带归属；不覆盖自定义角色；已存在 marker 整体 no-op；禁止浮点金额。
- 验证方式：DDL/CHECK/FK/索引测试、seed 幂等、存量授权与回滚测试。
- 完成标准：新库和既有库均得到正确表/菜单/资源；无角色仍 fail-closed。
- 实际落地情况：待实施。

### 6.2 任务 T2：规则仓库与生命周期服务

- 状态：待开始
- 依赖：T1。
- 涉及文件：新增 `backend/storage/trade_discipline_repository.py`、`backend/services/trade_discipline_service.py`。
- 目标：实现 R1-R3、R11、R14、R16、R35、R36 的名称占用、草稿、发布、归档、恢复、复制和有效版本解析。
- 操作：事务锁主体；规范化名称；保存草稿覆盖并递增修订；发布比对实质变化；查询 DuckDB 下一开市日；写不可变事件；同生效日取最晚事件；复制不带历史。
- 产出：可被 API 调用的规则领域方法和稳定 DTO。
- 影响范围：规则相关 PG 表与只读交易日历。
- 边界与异常：日历缺失、已归档、重名、草稿修订冲突、无实质变化、同日多动作均有确定结果。
- 验证方式：仓库/服务参数化单测与事务失败注入。
- 完成标准：草稿与正式版本职责不混淆，任何生命周期动作均不倒灌。
- 实际落地情况：待实施。

### 6.3 任务 T3：打卡、原因、操作与历史服务

- 状态：待开始
- 依赖：T1、T2。
- 涉及文件：`backend/services/trade_discipline_service.py`、`backend/storage/trade_discipline_repository.py`。
- 目标：实现四种组合、具体规则关联、原因事务、修订、历史和快捷幂等动作。
- 操作：校验数据交易日和有效版本；首次/修正创建不可变修订；原因文本归一化复用/新增；验证操作方向、两个明细引用、非负数和时间日期；分页筛选。
- 产出：打卡写服务、摘要、历史查询和修订详情。
- 影响范围：打卡/修订/原因/操作表。
- 边界与异常：未履约原因+详细说明必填；无操作与操作行互斥；已有打卡固定原版本；财务不完整允许但返回完整度。
- 验证方式：组合、幂等、并发、归属、原因删除和规则关联单测。
- 完成标准：一次提交的所有事实原子成功或全部回滚。
- 实际落地情况：待实施。

### 6.4 任务 T4：API、专用股票搜索与权限守卫

- 状态：待开始
- 依赖：T2、T3。
- 涉及文件：新增 `backend/api/trade_discipline.py`，修改 `backend/main.py`。
- 目标：按第 4.3 节开放接口，统一响应/错误码并挂精确权限。
- 操作：定义 Pydantic 请求/响应；注册 router；实现 stock-options 受限查询；摘要双权限；写端点审计只记引用摘要。
- 产出：OpenAPI 可见、无裸露路由的完整 API。
- 影响范围：`/api/trade-discipline/*`；现有 `/api/stocks` 不变。
- 边界与异常：空 q、limit 超限、401/403/404、409、422、日历缺失均可区分。
- 验证方式：API 权限矩阵、路由扫描、契约与响应测试。
- 完成标准：无 `stocks:view` 的 submit 用户能搜索，不能访问完整 stocks API。
- 实际落地情况：待实施。

### 6.5 任务 T5：前端路由、工作台壳与配置闭环

- 状态：待开始
- 依赖：T4。
- 涉及文件：新增 `frontend/src/views/TradeDisciplineView.vue`、`frontend/src/api/tradeDiscipline.ts`；修改 router、pageRegistry、DESIGN marker；按需扩展 `useTradeDates` 的非破坏性状态暴露。
- 目标：搭建三页签、LayoutHost slots、四态、权限只读态、设置抽屉和脏状态导航框架。
- 操作：登记 `trade-discipline`；密度/历史 pageSize 配置默认、保存、读取、消费、重置与非法回退；query 参数仅恢复会话；页头 `flex-start`。
- 产出：可联调的页面骨架与 API 类型。
- 影响范围：新增一级业务页和 DESIGN 页面索引；不新增配置字段。
- 边界与异常：无权不伪装空态；交易日加载错误可观察且本页 fail-closed；旧页面行为不变。
- 验证方式：router/pageRegistry/layout/config 单测。
- 完成标准：页面通过布局机器契约且设置没有假消费。
- 实际落地情况：待实施。

### 6.6 任务 T6：规则管理页面

- 状态：待开始
- 依赖：T5、T2、T4。
- 涉及文件：`TradeDisciplineView.vue`、新增 `views/trade-discipline/components/RuleMasterList.vue`、`TradeRuleEditor.vue` 等 feature 组件。
- 目标：完整承接原型规则管理主从区和 R1-R3、R16-R17、R35-R36。
- 操作：规则筛选/切换；明细增删启停排序；多行自动换行；资金实时汇总；草稿/发布/放弃/复制/归档/恢复/删除；双状态展示。
- 产出：不使用编辑抽屉的规则管理闭环。
- 影响范围：工作台规则页签与共享规则轨道。
- 边界与异常：停用项不帮助发布；草稿冲突保留输入；待生效动作不提前替换今日版本。
- 验证方式：组件测试 + 规则生命周期 E2E。
- 完成标准：保存后启用态、顺序、换行原样恢复，vN/草稿/待生效可观察。
- 实际落地情况：待实施。

### 6.7 任务 T7：今日打卡页面

- 状态：待开始
- 依赖：T5、T3、T4、T6 的规则轨道。
- 涉及文件：新增 `TradeCheckinForm.vue`、`TradeOperationEditor.vue`、`ViolationReasonCombobox.vue`、`StockOptionSelect.vue`。
- 目标：承接原型打卡区、四种组合、原因、操作、补录和修正入口。
- 操作：上下文选择、候选 0/1/多处理、方向联动、远程搜索取消迟到请求、原因行内删除、脏确认、提交刷新联动。
- 产出：完整今日/历史补录表单。
- 影响范围：今日打卡页签与共享摘要。
- 边界与异常：局部加载失败保留已填内容；无有效版本阻止；409 不清表单。
- 验证方式：表单/组件测试 + 四组合与补录 E2E。
- 完成标准：需求 7.1.1 的字段、状态、权限和错误均有可观察行为。
- 实际落地情况：待实施。

### 6.8 任务 T8：历史列表、修订详情与修正

- 状态：待开始
- 依赖：T5、T3、T4、T7。
- 涉及文件：新增 `TradeDisciplineHistory.vue`、`TradeCheckinRevisionDrawer.vue`。
- 目标：完成自动筛选、分页、详情修订切换和发起修正。
- 操作：复用通用表格/列/分页/搜索/抽屉；服务端筛选；保留筛选刷新；详情完整展示规则和操作快照。
- 产出：历史页签与页面内详情抽屉。
- 影响范围：工作台历史区域。
- 边界与异常：筛选失败由表格区接管；无维护权限只读；旧修订不可编辑。
- 验证方式：视图测试 + 筛选分页/抽屉/修正 E2E。
- 完成标准：任意修订均可追溯，修正后列表保留条件并显示新修订号。
- 实际落地情况：待实施。

### 6.9 任务 T9：用户中心快捷卡片与全局联动

- 状态：待开始
- 依赖：T4、T5、T7。
- 涉及文件：修改 `frontend/src/App.vue`；新增 `frontend/src/components/trade-discipline/TradeDisciplineQuickCard.vue`、`frontend/src/composables/useTradeDisciplineSummary.ts`。
- 目标：在现有抽屉内加入摘要、状态点、跳转和快捷无操作履约。
- 操作：打开时按需加载；权限条件渲染；确认对话框；成功刷新全局与页面；冲突跳正式页。
- 产出：P2 快捷闭环。
- 影响范围：应用顶栏/用户抽屉；不重排身份卡与退出按钮。
- 边界与异常：无权限/失败不显示红点，不轮询，不在抽屉承载长表单。
- 验证方式：App/快捷卡组件测试 + 任意授权业务页 E2E。
- 完成标准：抽屉提交和正式工作台状态一致。
- 实际落地情况：待实施。

### 6.10 任务 T10：后端自动化测试

- 状态：待开始
- 依赖：T1-T4。
- 涉及文件：新增 `backend/tests/test_trade_discipline_*.py`，修改 RBAC schema/资源扫描相关测试。
- 目标：覆盖 DDL、归属、事务、版本、事件、日期、原因、操作、权限和 API。
- 操作：使用临时用户/租户和清理夹具；参数化盘中/周末/节假日及同生效日事件；注入事务失败；验证 SQL marker 回滚。
- 产出：可复现 pytest 回归集。
- 影响范围：测试库；不依赖固定调试账号。
- 边界与异常：运行前按 DuckDB 锁规则停服，结束后恢复原状态。
- 验证方式：聚焦 pytest，再运行 `python -m pytest backend/tests/ -q`。
- 完成标准：本期后端验收项均有自动化断言。
- 实际落地情况：待实施。

### 6.11 任务 T11：前端单元与组件契约测试

- 状态：待开始
- 依赖：T5-T9。
- 涉及文件：新增页面/feature 组件测试，更新 router/pageRegistry/App 相关测试。
- 目标：覆盖配置消费、权限、四态、脏保护、原因单选、规则候选、双状态和摘要联动。
- 操作：使用真实通用组件浅/实挂载组合；断言不直接使用 `el-table/el-drawer`；验证设置重载和恢复默认。
- 产出：Vitest 与布局契约回归。
- 影响范围：前端测试。
- 边界与异常：不以临时中文正文或脆弱 CSS 层级作为长期选择器。
- 验证方式：`cd frontend && npm test`。
- 完成标准：组件、路由、布局和 DESIGN 契约均通过。
- 实际落地情况：待实施。

### 6.12 任务 T12：Playwright、构建与发布验收

- 状态：待开始
- 依赖：T10、T11。
- 涉及文件：新增 `frontend/e2e/trade-discipline.spec.ts` 及必要的本地可清理夹具/helper；同步相关事实文档入口（仅真实变化）。
- 目标：以真实点击链路验收全部纳入需求和原型一致性。
- 操作：覆盖首次建规则、草稿/发布/待生效、四类打卡、原因新增删除、历史修正、快捷入口、权限和三视口；运行 build 和回归。
- 产出：E2E、构建产物和上线核对结果。
- 影响范围：本地测试 PG/DuckDB、`frontend/dist`。
- 边界与异常：固定 5181；夹具受 dev/test/local 与写入门控并可精确清理；不得污染真实用户数据。
- 验证方式：`npm run build`、聚焦 E2E、必要时全量 E2E、`git diff --check`。
- 完成标准：R1-R17、R26-R36 验收可观察且无未解释偏差。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划

| 路径/类别 | 用途 | 执行时机 | 影响范围 | 回滚方式 |
| --- | --- | --- | --- | --- |
| `backend/storage/pg_ddl.py` | 业务表、索引、菜单/资源 seed、存量默认授权迁移 | 新库首次启动及既有环境受控重启时由 `init_pg_db()` 幂等执行 | PG schema、`sys_menu/sys_resource/sys_role_*`、`perm_ver` | 无业务数据时按 FK 逆序删表；已有数据时只回滚代码和授权，保留事实表，禁止破坏性删数 |
| `backend/auth/constants.py` | 新库 normal/tenant_admin 默认业务功能码 | 与 seed 同时 | 默认角色新装授权 | 代码回滚；既有授权由 marker 账本处理 |
| `agent-works/trading-discipline-checkin/trading-discipline-schema.sql` | 与运行时代码等价的 DDL、RBAC 回填、核验查询和确定性回滚留痕 | 开发/评审时生成；生产默认不与启动迁移重复执行，仅用于人工复核或应急 | 同上 | marker 保存本迁移实际插入的 role-menu/resource；回滚只删这些行、同事务 bump `perm_ver` 并写 tombstone |
| `backend/services/trade_discipline_service.py` 内置原因常量 | 返回八个只读内置原因；不写 `sys_dict`，个人原因才进入业务表 | 后端部署即生效 | 所有授权用户的原因候选，不修改历史快照 | 随代码回滚；已由用户创建的个人原因和历史违规事实保留 |
| `frontend/src/layout/pageRegistry.ts` + 既有 layout/user preference 表 | 页面密度、历史 pageSize 元数据与个人值 | 前端发布后，用户首次保存设置时写既有 PG 链路 | 当前用户当前 pageKey | 恢复默认删除/重置用户覆盖；不新增 SQL 列或 app_config |

生产步骤先备份 PG 并核验未来 `trade_calendar` 可用，再在低流量窗口部署/重启。若应用代码回滚，保留新增业务表避免丢失已提交事实；隐藏菜单并按 marker 撤销本迁移新增的默认授权。待数据保留期和导出策略另行确认前，不提供生产删表回滚。

## 8. 测试与验证计划

- 单元测试：规则名称归一化、金额定点、版本实质变化、激活事件解析、原因匹配、操作规则候选与完整度。具体完成情况：待验证。
- 接口测试：所有端点成功/422/403/404/409、分页筛选、快捷幂等、R31 限流边界。具体完成情况：待验证。
- 页面/交互测试：三页签、主从区、全部命令、脏保护、四种打卡、修订抽屉、全局快捷卡。具体完成情况：待验证。
- 组件资产闭环测试：验证通用组件真实导入/渲染、feature 组件事件契约、pageRegistry、密度/pageSize 保存读取消费与重置；确认没有新增未消费字段。具体完成情况：待验证。
- 权限与数据范围测试：system/normal/tenant_admin/自定义最小权限/无角色；跨 owner/tenant；有 submit 无 stocks:view；按钮和接口一致。具体完成情况：待验证。
- 回归测试：后端全量 pytest、前端 Vitest、build、相关 Playwright；测试前后恢复服务状态。具体完成情况：待验证。
- 异常与边界测试：日历空/滞后、周末发布、同日多事件、草稿与修订并发、规则被归档、网络失败、原因删除、规则候选为零、财务字段不完整。具体完成情况：待验证。
- 原型一致性：逐区对照 HTML 的页头、三页签、两套主从区、操作/原因/双状态、历史抽屉、设置抽屉、用户快捷卡和 1100×620/1366×768/1440×900 退化；原型批注和演示数据不得进入线上文案。具体完成情况：待验证。
- 需求映射验证：用脚本核对 requirement 的 R1-R36 范围编号均在第 5 章出现，纳入项均有任务/状态/验证，跳过项均有原因。具体完成情况：待验证。

## 9. 发布与回滚

- 发布前检查：确认 PG 备份、迁移 marker 未冲突、DuckDB 未来开市日存在、默认角色/自定义角色授权方案、无明文或本地数据进入 Git；按测试前状态停服/恢复。
- 发布步骤：先部署幂等 DDL/seed 与后端 API并验证健康/权限，再发布前端和 `dist`，最后以 normal、tenant_admin、最小权限账号跑冒烟；存量自定义角色由管理员按需授权，不自动扩大。
- 配置或环境变量：无新增环境变量和 `app_config` 业务配置；页面设置复用现有 layout/user preference 链路。
- 回滚方案：应用回滚到前版本；按 SQL marker 精确撤销本次默认菜单/资源授权并 bump `perm_ver`；保留业务表与用户事实。仅确认从未写入生产事实时才允许逆序删表。

## 10. 风险、假设与待确认项

### 10.1 风险

- 生命周期动作依赖 DuckDB 已同步未来交易日；缺失时按需求 fail-closed，可能暂时阻止发布/归档/恢复，页面必须给出同步指引。
- 新功能表和事件较多，事务与复合外键实现复杂；以 T1-T3 的仓库测试先锁定不变量，再开放 API。
- 用户中心摘要会增加一次按需请求；仅打开抽屉时加载并共享缓存失效，不轮询，避免全局性能回退。
- 历史股票/原因模糊筛选可能增长；首期通过归属前缀索引、分页和受控查询观察，实际数据量不足以支持更重的全文索引决策。

### 10.2 假设

- 使用现有 PostgreSQL、DuckDB、Element Plus 和布局系统，不引入新依赖。
- 业务 ID 沿用项目 opaque `TEXT` 引用风格；API 不暴露归属复合键。
- 系统内置未履约原因由后端常量返回，个人原因才入表；历史始终保存名称快照。
- 本期新增的 feature-scoped 组件只服务交易纪律模块，不登记为可配置系统组件；若未来第二个业务模块消费，再升级为全局真实复用组件并同步 DESIGN 清单。

### 10.3 待确认项

- 无阻塞待确认项。开发中若发现生产数据库存在与计划 marker 同名的外部迁移，必须停止迁移并更换稳定 marker/锁键；该问题不影响当前计划启动。
