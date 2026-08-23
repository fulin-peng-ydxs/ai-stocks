# 开发计划：交易纪律记录与履约打卡

## 1. 需求来源与目标

- 需求文档：[requirement.md](./requirement.md)，状态为“业务闭环及审查阻塞项已确认，可作为开发计划输入”。
- 页面原型：[prototypes/trading-discipline-workbench.html](./prototypes/trading-discipline-workbench.html)，已完整读取并作为 P1 工作台与 P2 用户中心快捷卡片的布局、状态和交互依据。
- 功能目标：建设私人交易规则的草稿/正式版本/未来交易日生效闭环，完成按“规则 + 交易日”的履约打卡、操作记录、未履约原因、历史修订和全局快捷无操作履约。
- 本次不做：R18-R25 所述打卡服务端草稿、账户快照/资金流水、AI 或规则引擎结果、自动裁决、图表、券商同步、公开分享。
- 计划输出目录：`agent-works/trading-discipline-checkin/`。
- 准入结论：无剩余阻塞项；需求和原型已明确流程、数据、权限、接口验收与上线边界。
- 当前开发阶段：T1-T11 已完成并分别提交，下一开发任务为 T12；T5-T9 阶段验收尚未完成，须待 T12-T13 的确定性夹具、真实 PG 业务闭环及发布回归完成后才能判定通过。本轮只完成 T11，未连续开发 T12。

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
| `WorkspaceTabs.vue`、`useWorkspaceTabs.ts`、`WorkspaceRouteView.vue` | 当前关闭标签会先删 tab/KeepAlive 缓存再导航，页面守卫无法挽回现场；达到 12 个标签时还会同步淘汰最旧缓存 | 新增应用壳层未保存协议，任何显式关闭、容量淘汰、路由离开或注销都必须先决策，获准后才能删 tab/cache |
| `frontend/src/layout/pageRegistry.ts`、`LayoutHost.vue` | 非公开 View 必须登记并真实消费布局 | 登记 `trade-discipline` workbench，使用 `LayoutHost` 和 overlay 设置抽屉 |
| `PageSettingsDrawer`、`useRemoteLayoutConfig`、`usePageSettings` | 已有 page/user 配置保存、读取、重置链路 | 密度走布局配置；历史 `pageSize` 走现有组件字段，不新增尺寸偏好 |
| `AppDataTable`、`AppTableColumn`、`AppPagination`、`AppStateBlock`、`PageDrawer` | 已有表格、分页、四态和页面内抽屉 | 历史列表、修订详情、四态直接复用，不手写平行实现 |
| `frontend/src/App.vue` | 已有 440px 视口级用户中心抽屉 | 仅增加快捷卡片、头像状态点和确认动作，不创建第二个全局抽屉 |
| `DESIGN.md`、`page-template.md` | 页头 `flex-start`、查询自动触发、页面登记和三视口为硬约束 | 页面实现与 E2E 逐项验证；同步 DESIGN page-registry marker |
| `agent-works/architecture/system-rbac-tenant.md` | 新页面需静态路由、菜单/资源 seed、默认角色回填、按钮守卫和 `perm_ver` 原子失效 | T1 使用独立 marker 状态机接入，冲突/非法状态 fail-closed |
| `agent-works/e2e-automation/guide.md`、`test-users.md` | E2E 固定 5181；物理写需环境门控和 PG 指纹；长期用例复用 helper；固定调试账号是页面权限事实源 | T12 建独立、可清理、串行的交易纪律夹具与聚焦运行入口，失败由 trap 精确清理并恢复后端 |
| 测试体系 | pytest、Vitest、Playwright；前端源码改动后必须 build | 分层补仓库/服务/API/组件/E2E，并遵守 DuckDB 锁、PG 指纹、5181 端口和三视口规则 |

当前无法直接证明生产 PG 中是否已有自定义角色或人工授权，故存量授权迁移必须记录“实际插入行”，回滚不得猜测删除既有合法授权。

## 3. 实施范围

### 3.1 必须实现

> 本章“已完成”只表示对应代码或分层实现已落地，不等于阶段验收通过；阶段验收状态与未执行项以第 6、8 章为准。

| 需求编号 | 实施内容 | 对应任务 | 状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| R1 | 私人规则生命周期、名称唯一、明细启用/顺序/换行 | T1、T2、T6、T10-T13 | T1-T2 后端及 T6 页面管理已完成 | DDL/服务单测 + 页面 E2E |
| R2 | 本金与启用选股规则资金上限校验 | T2、T6、T10-T11 | T2 后端校验及 T6 页面汇总/预校验已完成 | 金额边界参数化测试 |
| R3 | 正式版本连续生成且历史不可变 | T1、T2、T6、T10 | T1-T2 后端基础及 T6 发布交互已完成 | 发布事务与历史快照测试 |
| R4 | 规则 + 交易日唯一打卡 | T1、T3、T7、T10 | T1/T3 后端及 T7 首次/修正表单已完成 | 唯一性/幂等测试 |
| R5 | 四种履约/操作组合 | T3、T7、T10-T13 | T3 服务及 T7 四组合表单已完成 | 服务组合测试 + E2E |
| R6 | 多笔同股操作与股票关联 | T3、T4、T7、T10-T13 | T3-T4 后端及 T7 多操作编辑已完成 | 页面操作行测试 + E2E |
| R7 | 每笔分别关联具体选股与方向匹配买卖规则 | T3、T7、T10-T13 | T3 服务及 T7 候选/方向联动已完成 | 候选 0/1/多条测试 |
| R8 | 可选成交事实与完整度 | T1、T3、T7、T10-T11 | T1/T3 后端及 T7 可选事实字段已完成 | 字段边界与展示测试 |
| R9 | 历史筛选、详情、不可变修订 | T1、T3、T8、T10-T13 | T1/T3 后端及 T8 页面已完成 | 分页/修订/API/E2E |
| R10 | 真实交易日选择与校验 | T3、T4、T5、T7、T10-T13 | T3-T4 服务/API 及 T7 统一交易日控件已完成 | 页面日期状态 + E2E |
| R11 | 私人归属和跨用户隔离 | T1-T4、T8、T10、T12-T13 | T1-T4 后端归属隔离与 404 防泄露已完成 | 页面权限 + E2E |
| R12 | 用户中心摘要、状态点与跳转 | T4、T9、T11-T13 | T4 摘要 API 及 T9 全局卡片/跳转已完成 | App 组件测试 + 三视口 E2E |
| R13 | 快捷无操作已履约 | T3、T4、T9、T10-T13 | T3-T4 幂等服务/API 及 T9 快捷交互已完成 | 用户中心交互 + E2E |
| R14 | 原始事实稳定、派生能力不反写 | T1-T3、T10 | T1-T3 核心事实层已完成 | 外键/不可变仓库测试与数据契约审查 |
| R15 | 三页签、主从布局和响应式闭环 | T5-T8、T11、T13 | T5 工作台壳、T6 规则主从区及 T7 打卡主从区已完成 | 布局契约 + 三视口 Playwright |
| R26 | 单选可输入原因、自动新增、行内删除 | T1、T3、T7、T10-T13 | T1/T3 后端及 T7 原因组合框已完成 | 原因事务/交互 E2E |
| R27 | 未履约详细说明必填并保留换行 | T1、T3、T7-T8、T10-T13 | T1/T3 后端及 T7 表单必填已完成 | API/页面/历史展示测试 |
| R28 | 路由、菜单、四功能码、默认角色授权 | T1、T4-T9、T10-T13 | T1/T4 RBAC、T5 页面权限及 T9 快捷入口权限已完成 | 前端路由/按钮权限测试 |
| R29 | pageRegistry、LayoutHost、维护矩阵 | T5、T11、T13 | T5 页面登记、LayoutHost 与 DESIGN marker 已完成 | pageRegistry/layout contract |
| R30 | 补录按履约日有效版本解析 | T1-T4、T7、T10、T12-T13 | T1-T4 后端绑定/current API 及 T7 历史交易日入口已完成 | 页面补录 + E2E |
| R31 | 专用轻量股票搜索 | T4、T7-T8、T10-T13 | T4 受限搜索 API 及 T7 防抖/中止选择器已完成 | 前端防抖、迟到请求 + E2E |
| R32 | 页面设置保存、读取、消费、恢复默认 | T5、T8、T11、T13 | T5 密度、历史 pageSize/border 与恢复默认接入已完成 | 偏好/组件/E2E |
| R33 | 通用表格、分页、状态、抽屉复用 | T5、T8、T11、T13 | T5 页面壳复用闭环已完成，T8 继续补历史筛选与详情 | 组件依赖与布局契约审查 |
| R34 | 加载、空、错误、无权限四态 | T5-T9、T11、T13 | T5 页面及 T9 快捷卡状态边界已完成 | 独立状态组件测试 + E2E |
| R35 | 每主体至多一个规则草稿、乐观锁、放弃/发布 | T1、T2、T6、T10-T13 | T1-T2 后端生命周期及 T6 草稿交互已完成 | 并发 409/事务/恢复 E2E |
| R36 | 激活时间、下一真实交易日、双状态展示 | T1-T4、T6-T7、T10-T13 | T1-T4 事件/API、T6 管理双状态及 T7 履约版本轨道已完成 | 页面双状态 + E2E |

### 3.2 可选增强

| 需求编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R16 | 复制规则 | 本次纳入 | T2 后端及 T6 页面来源选择已完成 | T2、T6、T10-T13 | 副本为无版本号的新主体草稿，可选复制正式版或草稿内容 |
| R17 | 页面离开前未保存提醒 | 本次纳入 | T5 应用协议、T6 规则三选及 T7 打卡二选已完成 | T5-T8、T11、T13 | 应用壳先决策再改变标签/缓存；T8 继续复用打卡二选，浏览器刷新使用原生提示 |
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
- 新增应用级 `useUnsavedChangesGuard.ts`：以现有 workspace tab key 为索引暴露 `registerUnsavedHandler(tabKey, { isDirty, requestLeave })`（返回注销函数）、`confirmLeave(tabKey, reason)`、`confirmAll(reason)`；`reason` 区分 route/tab-close/tab-evict/logout/context-change。router、`WorkspaceTabs`、标签容量淘汰和注销共享同一 async preflight，显式关闭通过一次性 permit 避免随后的 router guard 重复询问。preflight 返回允许后，才调用 `removeWorkspaceTab`/释放 KeepAlive；非当前缓存页也能被询问。打卡决策为“放弃修改/继续编辑”，规则编辑为“保存草稿/放弃修改/继续编辑”，保存失败保持当前标签和现场。`beforeunload` 受浏览器限制只使用原生确认，不能伪造三按钮；用户留下后再在页内保存草稿。

### 4.2 数据模型

| 表/约束 | 关键设计 |
| --- | --- |
| `trade_discipline_rule` | 主体状态、最新正式版本指针、`next_activation_seq`、时间、软删除；复合主键含归属；生命周期写入在主体行锁内原子递增序号 |
| `trade_discipline_rule_name_claim` | 以 `(tenant_id, owner_user_id, normalized_name)` 唯一占用正式名/草稿拟用名；解决跨 `rule`/`draft` 表并发重名，发布时原子换名，归档仍占名 |
| `trade_discipline_rule_draft` + 两类 draft 明细 | 每主体唯一草稿、修订号、来源版本；保存启用态、顺序与原始换行 |
| `trade_discipline_rule_version` + 两类正式明细 | `(归属, rule_id, version_no)` 唯一；正式行不可更新；启用明细顺序唯一且类型受 CHECK 约束 |
| `trade_discipline_rule_activation` | `publish/archive/restore` 不可变事件，保留稳定事件 ID、每主体单调 `event_seq`、`occurred_at`、`activated_at`、`effective_from_trade_date` 与版本引用；`(归属, rule_id, event_seq)` 唯一 |
| `trade_discipline_checkin` | `(归属, rule_id, trade_date)` 唯一，保存当前修订指针 |
| `trade_discipline_checkin_revision` | 规则版本、自评、无操作、详细说明、复盘说明、首次/修正时间；不可变 |
| `trade_discipline_reason`、`trade_discipline_violation` | 个人原因软删除；修订保存原因码/引用和名称快照，每个 breached 修订恰好一条 |
| `trade_discipline_operation` | 每修订多条、稳定顺序、股票名快照、方向、两个具体规则引用及可空财务字段；复合外键锁定同一规则版本 |

金额使用 `NUMERIC` 定点数；交易日用 `DATE`；服务端事件时间用 `TIMESTAMPTZ`。生命周期事务先以 `(tenant_id, owner_user_id, rule_id) FOR UPDATE` 锁主体，再通过 `next_activation_seq + 1` 分配序号，并用锁后 `clock_timestamp()` 生成事件时间；主体计数器与事件同事务提交，回滚不得留下事件或提前推进已提交序号。有效状态只按 `(effective_from_trade_date, event_seq)` 全序解析，时间戳不参与胜负，因此等时间戳、长事务或并发提交仍有唯一结果。索引覆盖该全序、归属下规则列表、历史日期倒序、股票/原因筛选和修订详情。正文只按普通文本序列化，不渲染 HTML。

### 4.3 接口与权限契约

四项固定功能码为 `trade-discipline:view`、`trade-discipline:rule-manage`、`trade-discipline:checkin-view`、`trade-discipline:checkin-submit`；下表为节省篇幅使用末段简称。system 恒过，normal/tenant_admin 新库默认全授，既有库由 T1 的显式迁移补齐；自定义角色不自动扩权。

| 接口组 | 主要端点 | 权限 | 事务/异常 |
| --- | --- | --- | --- |
| 摘要 | `GET /api/trade-discipline/summary` | `view` + `checkin-view` | 日历为空返回可区分错误，不泄露正文 |
| 规则读写 | `GET/POST /rules`、`GET /rules/{ref}`、`PUT/DELETE /rules/{ref}/draft` | 读用 `view`，维护用 `rule-manage` | 名称/草稿冲突 409；输入保留 |
| 生命周期 | `POST /rules/{ref}/publish\|archive\|restore\|copy`、`DELETE /rules/{ref}` | `rule-manage` | 发布/事件/指针/草稿删除同事务；日历缺失不提交 |
| 打卡 | `GET /checkins/current`、`POST /checkins`、`POST /checkins/{ref}/amendments` | 读 `checkin-view`，写 `checkin-submit` | 修订及明细同事务；版本/修订冲突 409 |
| 历史 | `GET /checkins`、`GET /checkins/{ref}/revisions/{no}` | `checkin-view` | 服务端筛选、排序、分页；归属不匹配不泄露存在性 |
| 原因 | `GET /reasons`、`DELETE /reasons/{ref}` | 读 `checkin-view`，删 `checkin-submit` | 自定义原因随打卡事务新增；删除为软删除 |
| 快捷动作 | `POST /checkins/quick-no-operation` | `checkin-submit` | 服务端固定已履约+无操作，重复请求幂等，冲突返回现有引用 |
| 股票选择 | `GET /stock-options?q=&limit=` | `checkin-submit` | 空查询拒绝；`limit<=20`；仅代码/名称/板块/行业 |

API 不接收 `tenant_id`、`owner_user_id`、`activated_at` 或生效日。日志只记动作、对象引用、状态和错误码，不记录完整规则正文、操作清单或详细说明。

### 4.4 页面 P1：交易纪律工作台

- 原型文件：`prototypes/trading-discipline-workbench.html`。
- 页面结构：`workbench` 外层三页签；pageRegistry 登记 `workspaceTabs`（`tabs`）为唯一 `growMain`，下挂 `checkinPanel`、`rulesPanel`、`historyPanel` 三个互斥业务面板；今日打卡与规则管理共用 feature-scoped 左侧规则轨道 + 右侧工作区；页头动作区与标题顶部对齐。
- 页签配置：`workspaceTabs` 只表达结构，不登记 `componentMeta.tabs`、不消费 `defaultActive`、不写 page/user 配置；页面会话默认 `checkin`，URL `tab` 只恢复当前访问。三个面板是真实消费者，切换前先执行 R17 preflight。
- 滚动：`workspaceTabs` 承担主成长和面板切换；当前面板内部承接滚动。主从区在 1100px 提前变为上下结构；表单不横向滚动，只有历史表格内部横向滚动；详情抽屉正文内滚。

| 页面功能点/原型区域 | 对应需求 | 技术实现 | 组件/模块 | 数据、状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- |
| 页头、最新交易日、三页签、页面设置 | R15、R17、R29、R32、R34 | registry slots：`toolbar` + `workspaceTabs(tabs,growMain)` + 三个嵌套 panel + `historyDetail/settings` overlays；tab 为会话态 | `LayoutHost`、`PageSettingsTrigger/Drawer` | 初载四态互斥；切 tab 先走未保存协议；设置失败保留当前内容 | T5 |
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
| 响应式与低高度 | R15、R34 | 1100×620 上下主从；1366/1440 双栏；无固定视口高度 | 页面样式/token | 无整页横向溢出、动作始终可达 | T5-T8、T13 |

逐区域数据/API 与事件流：

| 原型/页面区域 | 调用契约（关键输入 → 输出） | 刷新与联动 |
| --- | --- | --- |
| 页头/日期 | `GET /api/data/trade-dates` → `min/max/dates`；`GET /api/layout/effective/trade-discipline` → effective layout | 首次进入并行加载；日历失败只接管日期相关区域并禁止提交 |
| 今日规则轨道 | `GET /api/trade-discipline/summary?trade_date=` → 目标日规则、有效 vN、管理待生效动作、打卡状态/计数 | 日期变化、提交/修正、规则生命周期成功后刷新；同步全局摘要缓存 |
| 打卡表单读取 | `GET /api/trade-discipline/checkins/current?rule_ref=&trade_date=` → 绑定版本、启用选股/买卖明细、当前修订和表单事实 | 规则/日期切换前 R17 preflight；无记录返回可补录模型，无有效版本返回阻断原因 |
| 原因下拉 | `GET /api/trade-discipline/reasons` → 内置+本人个人原因；`DELETE /reasons/{ref}` | 删除成功移除候选；当前选中项被删则清空；提交自定义文本由打卡响应返回新 reason_ref 并并入候选 |
| 操作股票搜索 | `GET /api/trade-discipline/stock-options?q=&limit=20` → code/name/board/industry | 300ms 防抖、取消迟到请求；只更新当前操作行候选，不清其他输入 |
| 打卡提交/修正 | `POST /checkins` 或 `POST /checkins/{ref}/amendments`，输入 expected revision、用户自评、原因文本/引用、说明和操作 → 新 revision | 成功清脏并刷新 current、summary、history 和全局卡；409 保留表单并提示读取最新修订 |
| 规则列表/详情 | `GET /rules?status=&q=` → 主体/双状态/草稿提示；`GET /rules/{ref}` → 正式版本、工作草稿、明细和 draft_revision | 切规则前 R17 preflight；列表失败不清右侧；生命周期成功刷新列表、详情、summary |
| 规则草稿 | `POST /rules` 创建主体+草稿；`PUT /rules/{ref}/draft` 输入 expected draft_revision；`DELETE /rules/{ref}/draft` | 保存成功更新基线并清未保存态；放弃草稿恢复正式版；409 保留前端输入 |
| 规则生命周期 | `POST /rules/{ref}/publish\|archive\|restore\|copy`、`DELETE /rules/{ref}` → 主体状态、当前有效状态、待生效日、版本/草稿信息 | 成功刷新规则列表/详情/今日轨道/全局摘要；失败不提前改本地状态 |
| 历史筛选/分页 | `GET /checkins?date_from=&date_to=&rule_ref=&result=&has_operation=&stock_q=&reason_q=&amended=&page=&size=` → total/list | 任一筛选改动重置 page=1；分页只换页；修正成功保留条件重查当前页 |
| 修订详情 | `GET /checkins/{ref}/revisions/{no}` → 规则版本快照、原因/说明、操作及两个规则关联 | 切 revision 只刷新抽屉正文；发起修正关闭抽屉并以 ref/revision 加载打卡面板 |

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

P2 数据/API 与事件流：打开用户抽屉时调用 `GET /api/trade-discipline/summary`，输入默认最新数据交易日，输出完成/待办计数与规则行；“去打卡/管理规则”只生成 `/trade-discipline?tab=&rule_ref=&trade_date=` 会话 URL；快捷确认调用 `POST /api/trade-discipline/checkins/quick-no-operation`，只传 `rule_ref + trade_date`，成功后刷新共享 summary 并通知已打开工作台刷新 current/history，409/已有记录则保留抽屉并跳正式表单。

### 4.6 组件资产与配置闭环

| 页面/区域 | 运行时组件 | 布局/配置种类 | 注册与字段 | 规范更新 | 真实消费与验证 | 任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 工作台壳 | 复用 `LayoutHost`、`AppStateBlock` | 复用 workbench/toolbar/tabs/section/settings-drawer | 新增 pageRegistry 页面；`workspaceTabs` 是唯一 `growMain`；复用 `density`，明确不消费 tabs.defaultActive | 同步 DESIGN marker | 页面真实渲染三页签/三 panel，页签只存会话态 | T5、T11 |
| 历史列表 | 复用表格、列、分页、搜索 | 复用 data-table | `history` 消费 `pageSize`、`border` | 不新增字段定义 | 保存、重载、分页真实应用，非法值回退 20 | T5、T8、T11 |
| 修订详情 | 复用 `PageDrawer` | overlay detail | registry overlay，不新增 kind | 否，已有清单 | 页面边界、正文内滚、关闭与修正跳转 | T8、T11 |
| 规则轨道/操作编辑/原因下拉 | 新增 feature-scoped 组件并在两个页签消除重复 | 不登记系统组件种类 | 不新增通用组件配置字段 | 不进入全局组件清单；仅本业务内部复用 | View/组件测试覆盖事件与状态契约 | T6-T8、T11 |
| 用户快捷卡 | 新增业务组件，由现有 `App.vue` 全局抽屉消费 | 不涉及页面布局种类 | 不写页面偏好 | 不改变全局抽屉组件边界 | App 组件测试与任意页面 E2E | T9、T11、T13 |

本期不新增布局原型、系统组件 kind、`COMPONENT_FIELD_DEFS` 字段或后端布局字段规则；`tabs` 是现有种类，仅登记结构而不开放长期默认页签设置；规则编辑宽度/高度绝不进入配置或 `user_preference`。

### 4.7 RBAC 正向迁移与确定性回滚契约

- 稳定常量：marker key 为 `migration.trade_discipline_default_grants_v1`，事务 advisory lock 为 `8410010005`；Python 和 SQL 留痕必须引用同一常量，不另写近似版本。
- 稳定 seed 身份：菜单 `id=code=route_path='/trade-discipline'`、`title='交易纪律'`、`type='leaf'`、`visible='login'`；四个资源均 `id=code` 且 `menu_id='/trade-discipline'`，代表 method/path 固定为 `trade-discipline:view → GET /api/trade-discipline/summary`、`trade-discipline:rule-manage → POST /api/trade-discipline/rules`、`trade-discipline:checkin-view → GET /api/trade-discipline/checkins`、`trade-discipline:checkin-submit → POST /api/trade-discipline/checkins`。同一功能码可守卫该接口组其他端点，路由扫描以每个实际端点的守卫为准。
- seed 顺序：`seed_rbac()` 先确保内置角色存在，再调用专用 `_seed_trade_discipline_rbac()`；通用 `_SEED_MENU_TREE/_SEED_RESOURCES` 循环对 `/trade-discipline` 和四个资源码跳过，由专用状态机唯一写入，避免 tombstone 后被通用 seed 复活。
- marker 状态：缺失才允许正向；合法 applied 重启 no-op 并核验目标行仍与契约一致；合法 rolled_back/tombstone 永久 no-op；JSON 损坏、版本未知或 applied/rolled_back 冲突均为 invalid 并抛错，禁止补菜单、资源或授权。
- 默认授权可维护性：applied 只持续校验 marker 固定账本结构以及菜单/资源不可变身份，不要求 normal/tenant_admin 的初始授权行永久存在；管理员后续撤销默认菜单或功能授权时，重启不得补回或失败。回滚允许账本内默认授权已缺失，只删除当前仍存在的同键行；发现账本外自定义角色授权仍拒绝级联回滚。
- 正向冲突：marker 缺失但 `sys_menu.id`、`code` 或 `route_path` 任一命中 `/trade-discipline`，或 `sys_resource.id/code` 任一命中上述四个固定功能码时，均视为身份占用并使整事务 fail-closed；不因字段恰好相同就收编旧行，不覆盖、不改名、不授予角色权限，由运维先判定冲突来源。
- applied JSON 固定为 `{"version":1,"applied":true,"rolled_back":false,"inserted_menu_ids":[...],"inserted_resource_ids":[...],"inserted_role_menus":[[role_id,menu_id],...],"inserted_role_resources":[[role_id,resource_id],...]}`；数组只记录本事务 `RETURNING` 的实际新增行。
- 正向事务：取得 lock，校验状态/冲突，插入一级 leaf 菜单和四资源，给 normal/tenant_admin 插入菜单与四资源授权，写 applied marker，并对这两个角色成员及全部 system 用户同事务 `perm_ver + 1`；提交后 best-effort 清权限缓存。
- 回滚事务：`_rollback_trade_discipline_rbac()` 与 SQL 回滚段取得同一 lock，只接受合法 applied；按 marker 账本删除本次角色资源/菜单授权，再删本次资源和菜单，bump 同一受影响用户，最后把 marker 改为保留原账本的 `{"version":1,"applied":false,"rolled_back":true,...}` tombstone。marker 缺失/invalid 拒绝破坏性回滚，tombstone 重复回滚 no-op。
- 上线回滚顺序：先回滚前端 `dist`（移除静态路由，避免 system 直达失效页），在本版本后端代码和 SQL 工件仍可用时执行 `python -m backend.cli trade-discipline-rbac rollback --confirm-marker migration.trade_discipline_default_grants_v1` 完成 RBAC 回滚并核验 tombstone，最后才回滚后端 API；CLI 非零退出、tombstone 不正确或目标菜单/资源仍存在时必须停止，禁止继续切换后端版本。不得只“隐藏菜单”或只撤角色授权；后端回滚并重启后必须断言菜单、资源和授权均未复活。
- 显式重新启用：只能由运维确认后删除 tombstone，再重新执行正向迁移；普通应用重启不得自动重新启用。
- 跨阶段菜单门控：T5 已同批落地静态路由、pageRegistry、DESIGN marker、正式页面及对应测试，并移除 `/trade-discipline` 门控；`/me` 现按既有角色授权下发该菜单。资源授权和后端 API 契约保持不变。

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R1 | 规则主体、明细、生命周期与页面管理 | T1、T2、T6、T10-T13 | T1-T2 后端基础已完成 | 一致 | 含名称唯一、启用态、顺序、换行 |
| 必须实现 | R2 | 前后端定点资金校验 | T2、T6、T10-T11 | T2 后端校验已完成 | 一致 | 仅启用选股项参与 |
| 必须实现 | R3 | 不可变正式版本与连续版本号 | T1、T2、T6、T10 | T1-T2 后端基础已完成 | 一致 | 无实质变化不发新版 |
| 必须实现 | R4 | 规则日唯一打卡身份 | T1、T3、T7、T10 | T1/T3 后端已完成 | 一致 | 修正不新增平行记录 |
| 必须实现 | R5 | 四种组合 | T3、T7、T10、T12-T13 | T3 服务已完成 | 一致 | 全部正式提交 |
| 必须实现 | R6 | 多操作与股票关联 | T3、T4、T7、T10-T13 | T3-T4 后端服务/API 已完成 | 一致 | 同股不去重 |
| 必须实现 | R7 | 两个具体规则单选关联 | T3、T7、T10-T13 | T3 服务校验已完成 | 一致 | 0/1/多候选闭环 |
| 必须实现 | R8 | 可选成交字段和完整度 | T1、T3、T7、T10-T11 | T1/T3 后端已完成 | 一致 | 不伪造收益精度 |
| 必须实现 | R9 | 历史、详情、修正 | T1、T3、T8、T10-T13 | T1/T3 后端与 T8 前端已完成 | 一致 | 旧修订不可变 |
| 必须实现 | R10 | 真实交易日 | T3-T5、T7、T10-T13 | T3 服务校验已完成 | 一致 | 日历失败时禁止打卡 |
| 必须实现 | R11 | 私人归属 | T1-T4、T8、T10、T12-T13 | T1-T4 后端隔离已完成 | 一致 | 管理员也不扩大范围 |
| 必须实现 | R12 | 全局摘要与跳转 | T4、T9、T11、T13 | T4 API 与 T9 全局卡片/会话跳转已完成 | 一致 | 复用现有抽屉 |
| 必须实现 | R13 | 快捷无操作履约 | T3、T4、T9、T10-T13 | T3-T4 服务/API 与 T9 快捷交互已完成 | 一致 | 服务端固定语义 |
| 必须实现 | R14 | 原始事实/派生边界 | T1-T3、T10 | T1-T3 核心事实层已完成 | 一致 | 不创建 AI 调用链 |
| 必须实现 | R15 | 工作台主从与三页签 | T5-T8、T11、T13 | T5-T8 三页签业务区已完成 | 一致 | 规则编辑不用抽屉 |
| 可选增强 | R16 | 复制正式版或草稿为新未发布主体 | T2、T6、T10-T13 | T2 后端已完成 | 一致 | 本次纳入 |
| 可选增强 | R17 | 应用级未保存协议覆盖路由、工作标签、浏览器和业务上下文 | T5-T8、T11、T13 | T5 壳层协议已完成 | 一致 | 先决策后删除标签/缓存；打卡二选、规则三选 |
| 可选增强 | R18 | 暂不纳入 | - | 跳过 | 未覆盖 | D9 明确无服务端打卡草稿 |
| 可选增强 | R19 | 暂不纳入 | - | 跳过 | 未覆盖 | 收益域另立需求 |
| 可选增强 | R20 | 暂不纳入 | - | 跳过 | 未覆盖 | AI/规则引擎另立需求 |
| 暂不实现 | R21 | 不开发自动履约裁决 | - | 跳过 | 未覆盖 | 本期人工自评 |
| 暂不实现 | R22 | 不开发 AI 分析 | - | 跳过 | 未覆盖 | 模型边界未立项 |
| 暂不实现 | R23 | 不开发图表 | - | 跳过 | 未覆盖 | 数据成熟后另做 |
| 暂不实现 | R24 | 不接券商 | - | 跳过 | 未覆盖 | 外部授权未确认 |
| 暂不实现 | R25 | 不公开/分享/监督 | - | 跳过 | 未覆盖 | 私人资产范围 |
| 必须实现 | R26 | 单选可输入原因与行内删除 | T1、T3、T7、T10-T13 | T1/T3 后端已完成 | 一致 | 新原因随打卡事务新增 |
| 必须实现 | R27 | 独立详细说明 | T1、T3、T7-T8、T10-T13 | T1/T3 后端已完成 | 一致 | 必填且保留换行 |
| 必须实现 | R28 | 路由/RBAC/默认角色闭环 | T1、T4-T9、T10-T13 | T1/T4 后端 RBAC 闭环已完成 | 一致 | 存量授权可回滚 |
| 必须实现 | R29 | 页面登记与 LayoutHost | T5、T11、T13 | T5 已完成 | 一致 | 同步维护矩阵 |
| 必须实现 | R30 | 历史日有效版本解析 | T1-T4、T7、T10、T12-T13 | T1-T4 后端绑定/API 已完成 | 一致 | 草稿/未生效/归档不可绑定 |
| 必须实现 | R31 | 轻量股票端点 | T4、T7-T8、T10-T13 | T4 后端 API 与 T7-T8 前端消费已完成 | 一致 | 不扩大 stocks:view |
| 必须实现 | R32 | 设置闭环 | T5、T8、T11、T13 | T5-T8 历史分页设置消费已完成 | 一致 | 密度 + 历史分页真实消费 |
| 必须实现 | R33 | 通用组件复用 | T5、T8、T11、T13 | T5-T8 表格、筛选、行操作与页面抽屉复用已完成 | 一致 | 无页面私有表格/抽屉体系 |
| 必须实现 | R34 | 四态 | T5-T9、T11、T13 | T5 页面壳已完成 | 一致 | permission 为 error 变体 |
| 必须实现 | R35 | 工作草稿生命周期 | T1、T2、T6、T10-T13 | T1-T2 后端生命周期已完成 | 一致 | 正式版继续履约 |
| 必须实现 | R36 | 下一交易日生效与双状态 | T1-T4、T6-T7、T10-T13 | T1-T4 后端事件/解析/API 已完成 | 一致 | 发布/归档/恢复均覆盖 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：PG 模型、索引、SQL 与 RBAC 迁移

- 状态：已完成（2026-08-22）
- 依赖：无。
- 涉及文件：`backend/storage/pg_ddl.py`、`backend/auth/constants.py`、`backend/cli.py`、`backend/tests/conftest.py`、`backend/tests/test_trade_discipline_t1.py`、`agent-works/trading-discipline-checkin/trading-discipline-schema.sql`。
- 目标：落地第 4.2 节实体、复合外键/CHECK/唯一索引，并完成菜单、四资源码、新库默认授权和存量 normal/tenant_admin 回填。
- 操作：新增 DDL/ASSET_PK/索引；生命周期表加入 `event_seq` 且主体加入 `next_activation_seq`；seed 一级菜单 `/trade-discipline`；实现 `_seed_trade_discipline_rbac` 与 `_rollback_trade_discipline_rbac` 的 marker 状态机，记录实际插入行并同事务 bump `perm_ver`；新增受控 CLI `python -m backend.cli trade-discipline-rbac rollback --confirm-marker migration.trade_discipline_default_grants_v1`，确认值不完全匹配即拒绝，成功时输出 marker/删除计数供发布流程核验。
- 产出：可重复启动的 schema/seed 与等价人工复核 SQL（含确定性回滚）。
- 影响范围：PG public schema、RBAC 默认角色；不改 DuckDB 数据。
- 边界与异常：表间 FK 全带归属；不覆盖自定义角色；marker 非法、编码/路由冲突或未知状态全部 fail-closed；tombstone 下任何启动 seed 均不得复活菜单/资源/授权；禁止浮点金额。
- 验证方式：DDL/CHECK/FK/索引测试、seed 幂等、冲突原子回滚、marker 四态、正向/回滚后重启测试。
- 完成标准：新库和既有库均得到正确表/菜单/资源；无角色仍 fail-closed。
- 实际落地情况：已新增 14 张带复合归属主键/外键的交易纪律业务表、两项后置指针外键、6 项查询索引、`NUMERIC` 金额约束及打卡来源 `submission_source=workbench|quick_no_operation`；历史存量默认回填为 `workbench`。四个功能码使用独立常量，不并入会绕过 tombstone 的通用业务授权集合。菜单、资源及 system/normal/tenant_admin 初始授权由 marker `migration.trade_discipline_default_grants_v1` 和 advisory lock `8410010005` 原子维护；applied 只核验固定 marker 与菜单/资源结构，允许管理员后续撤销默认授权且重启不补回、不失败。回滚允许账本内授权已缺失，但拒绝账本外自定义角色授权并保留 tombstone。Python 与人工 SQL 已同步固定 marker、资源字段、可撤销默认授权和回滚策略；T5 页面就绪前 `/me` 对所有角色隐藏阶段菜单。

### 6.2 任务 T2：规则仓库与生命周期服务

- 状态：已完成（2026-08-22）
- 依赖：T1。
- 涉及文件：新增 `backend/storage/trade_discipline_repository.py`、`backend/services/trade_discipline_service.py`、`backend/tests/test_trade_discipline_t2.py`；修改 `backend/common/exceptions.py`、`backend/storage/pg_client.py`、`backend/storage/pg_ddl.py`、`backend/tests/test_trade_discipline_t1.py`、`agent-works/trading-discipline-checkin/trading-discipline-schema.sql`。
- 目标：实现 R1-R3、R11、R14、R16、R35、R36 的名称占用、草稿、发布、归档、恢复、复制和有效版本解析。
- 操作：事务锁主体；规范化名称；保存草稿覆盖并递增修订；发布比对实质变化；查询 DuckDB 下一开市日；锁内递增 `next_activation_seq` 并用 `clock_timestamp()` 写不可变事件；严格按 `(effective_from_trade_date, event_seq)` 解析；复制不带历史。
- 产出：可被 API 调用的规则领域方法和稳定 DTO。
- 影响范围：规则相关 PG 表与只读交易日历。
- 边界与异常：日历缺失、已归档、重名、草稿修订冲突、无实质变化、同日多动作均有确定结果。
- 验证方式：仓库/服务参数化单测与事务失败注入；增加完全相同 `occurred_at`、长事务、并发发布/归档/恢复，以及序号分配事务回滚后无幽灵事件/无计数器误推进测试。
- 完成标准：草稿与正式版本职责不混淆，任何生命周期动作均不倒灌。
- 实际落地情况：已实现全归属过滤的规则仓库和服务 DTO，覆盖 NFKC/trim/casefold 名称占用、未发布/启用/归档与工作草稿正交状态、草稿修订乐观锁、无实质变化去草稿、连续正式版本、复制正式版或草稿、受限物理删除，以及严格按 `(effective_from_trade_date,event_seq)` 的历史有效版本解析。生命周期动作均先锁主体，在同一 PG 事务内以 `clock_timestamp()` 分配事件时间和单调序号，再只读 DuckDB 求上海自然日后的首个开市日；日历缺失会回滚版本、事件、计数器与主体状态。规则列表使用单次 PG 批量查询同时返回最新管理事件（类型、序号、时间、生效日）、目标交易日有效状态和有效版本概要；详情返回完整有效版本，不再按规则产生 N+1。需求事实源已同步明确 `event_seq` 是唯一裁决顺序，时间戳只作审计和生效日计算。

### 6.3 任务 T3：打卡、原因、操作与历史服务

- 状态：已完成（2026-08-22）
- 依赖：T1、T2。
- 涉及文件：`backend/services/trade_discipline_service.py`、`backend/storage/trade_discipline_repository.py`、`backend/tests/conftest.py`，新增 `backend/tests/test_trade_discipline_t3.py`。
- 目标：实现四种组合、具体规则关联、原因事务、修订、历史和快捷幂等动作。
- 操作：校验数据交易日和有效版本；首次/修正创建不可变修订；原因文本归一化复用/新增；验证操作方向、两个明细引用、非负数和时间日期；分页筛选。
- 产出：打卡写服务、摘要、历史查询和修订详情。
- 影响范围：打卡/修订/原因/操作表。
- 边界与异常：未履约原因+详细说明必填；无操作与操作行互斥；已有打卡固定原版本；财务不完整允许但返回完整度。
- 验证方式：组合、幂等、并发、归属、原因删除和规则关联单测。
- 完成标准：一次提交的所有事实原子成功或全部回滚。
- 实际落地情况：已实现首次提交、乐观锁修正、快捷无操作幂等提交、按规则/日期读取、摘要、服务端分页筛选、任意修订详情和原因候选/软删除。首次提交在规则主体锁内按履约日解析有效事件并绑定正式版本；修正始终复用原修订版本，不受后续发布或归档影响。快捷端点只对仍为首次修订且来源/内容均为快捷无操作的既有记录幂等；工作台提交、未履约、有操作或已修正记录统一返回带既有打卡引用的 409。操作保存前以一次 DuckDB 查询批量验证全部股票代码存在，允许已退市代码承接历史场景，名称继续作为提交时快照。四种组合、具体规则引用、方向、交易日内时间、财务字段和完整度继续由服务端校验；规则金额与操作财务字段在服务层分别按 `NUMERIC(20,2)`、`NUMERIC(20,4)` 同等级检查小数位和整数位，绕过 API 也会在写库前返回业务校验错误，写入仍保持全事务原子。

### 6.4 任务 T4：API、专用股票搜索与权限守卫

- 状态：已完成（2026-08-22，本地验证通过并独立提交）
- 依赖：T2、T3。
- 涉及文件：新增 `backend/api/trade_discipline.py`，修改 `backend/main.py`。
- 目标：按第 4.3 节开放接口，统一响应/错误码并挂精确权限。
- 操作：定义 Pydantic 请求/响应；注册 router；实现 stock-options 受限查询；摘要双权限；写端点审计只记引用摘要。
- 产出：OpenAPI 可见、无裸露路由的完整 API。
- 影响范围：`/api/trade-discipline/*`；现有 `/api/stocks` 不变。
- 边界与异常：空 q、limit 超限、401/403/404、409、422、日历缺失均可区分。
- 验证方式：API 权限矩阵、路由扫描、契约与响应测试。
- 完成标准：无 `stocks:view` 的 submit 用户能搜索，不能访问完整 stocks API。
- 实际落地情况：已新增 `backend/api/trade_discipline.py` 并在 `backend/main.py` 注册 21 个 OpenAPI 端点；规则、生命周期、打卡、历史、原因、摘要和快捷动作均使用统一响应，API 边界将归属隐藏映射为真实 404、业务输入映射为 422，并保留携带安全对象引用的 409。规则本金、资金上限、成交金额和费用复用 `max_digits=20, decimal_places=2` 的受约束 Decimal，成交价和数量复用 `max_digits=20, decimal_places=4`，整数位或小数位越界在进入服务与 PG 前统一返回 422；提交与修正共享同一操作请求模型。规则列表/详情刷新后可直接消费管理状态、最新管理事件、待生效标记、目标交易日有效状态及版本。摘要同时要求 `view + checkin-view`，其余 20 个端点均以 `(method,path) → 精确功能码集合` 完整矩阵校验；无角色 fail-closed。专用 `stock-options` 仍只返回四个轻量字段且不扩大 `/api/stocks` 权限。写动作审计不记录正文、操作清单或详细说明。未进入 T5 前端开发。

### 6.5 任务 T5：前端路由、工作台壳与配置闭环

- 开发状态：已完成（2026-08-23，已独立提交）
- 阶段验收状态：未完成；当前自动化和页面壳验证已完成，最终准入待 T10-T13 整体回归。
- 依赖：T4。
- 涉及文件：新增 `frontend/src/views/TradeDisciplineView.vue`、`frontend/src/api/tradeDiscipline.ts`、`frontend/src/composables/useUnsavedChangesGuard.ts`；修改 router、`WorkspaceTabs.vue`、`useWorkspaceTabs.ts`、`WorkspaceRouteView.vue`、`App.vue`、pageRegistry、DESIGN marker；按需扩展 `useTradeDates` 的非破坏性状态暴露。
- 目标：搭建三页签、LayoutHost slots、四态、权限只读态、设置抽屉和应用壳层未保存协议。
- 操作：登记 `workspaceTabs` 现有 `tabs` kind 为唯一 `growMain`，三个业务 panel 为子 slot，明确不消费 `defaultActive`；密度/历史 pageSize 配置闭环；query 参数仅恢复会话；页头 `flex-start`。实现按 tab key 注册/注销处理器、单标签/全局 preflight 和一次性导航 permit；把 `addWorkspaceTab` 的容量淘汰与 `removeWorkspaceTab` 的显式关闭改成先 await 决策、后改变 tab/KeepAlive，路由切换和注销复用同一协议；全 dirty 无安全淘汰目标时阻止新导航。注册 `beforeunload` 原生保护。
- 发布门控：只有静态路由、pageRegistry、DESIGN marker、正式 View 和路由解析测试全部同批完成后，才从 `STAGED_FRONTEND_MENU_CODES` 移除 `/trade-discipline`；禁止先解除门控再补页面。
- 产出：可联调的页面骨架与 API 类型。
- 影响范围：新增一级业务页和 DESIGN 页面索引；不新增配置字段。
- 边界与异常：无权不伪装空态；交易日加载错误可观察且本页 fail-closed；保存草稿失败/用户继续编辑时标签、缓存和路由均不变；干净页面保持既有关闭行为。
- 验证方式：router/pageRegistry/layout/config 单测；WorkspaceTabs 当前/非当前关闭、容量淘汰、注销和 beforeunload 协议测试。
- 完成标准：页面通过布局机器契约且设置没有假消费。
- 实际落地情况：已新增 `/trade-discipline` 静态路由、正式 View、API 类型封装和 pageRegistry/`LayoutHost` workbench 登记，`workspaceTabs` 为唯一 `growMain`，三个业务面板按会话 query 切换；历史表真实消费 `pageSize/border`，页面密度与恢复默认沿用既有设置链路，未新增配置字段。交易日共享能力新增可观察 `idle/loading/ready/error` 状态，本页在日历失败时 fail-closed；基础 `trade-discipline:view` 缺失时优先显示整页权限态且不请求业务数据，页签内权限继续按精确功能码分流。应用级未保存协议已覆盖路由、当前/非当前标签关闭、容量淘汰、注销、业务上下文和 `beforeunload`，均先确认再改变标签/KeepAlive/路由，一次性 permit 避免重复确认；具体打卡二选和规则三选由 T6-T8 页面编辑器注册。静态路由、页面登记、DESIGN marker、页面测试同批完成后已解除 `/trade-discipline` 菜单门控，system/tenant_admin/normal 的 `/me` 菜单回归通过。T5 只提供规则/打卡/历史可联调壳与只读摘要，不实现 T6-T8 的编辑、提交、筛选和修订业务。

### 6.6 任务 T6：规则管理页面

- 开发状态：已完成（2026-08-23，已独立提交）
- 阶段验收状态：未完成；组件与页面实测已覆盖，规则发布/归档/恢复的可清理真实 E2E 待 T12-T13。
- 依赖：T5、T2、T4。
- 涉及文件：`TradeDisciplineView.vue`、新增 `views/trade-discipline/components/RuleMasterList.vue`、`TradeRuleEditor.vue`、`FixedDecimalInput.vue` 等 feature 组件，以及 `frontend/src/utils/fixedDecimal.ts`。
- 目标：完整承接原型规则管理主从区和 R1-R3、R16-R17、R35-R36。
- 操作：规则筛选/切换；明细增删启停排序；多行自动换行；资金实时汇总；草稿/发布/放弃/复制/归档/恢复/删除；双状态展示；向应用协议注册规则三选项处理器，只有保存成功或明确放弃才允许离开。
- 产出：不使用编辑抽屉的规则管理闭环。
- 影响范围：工作台规则页签与共享规则轨道。
- 边界与异常：停用项不帮助发布；草稿冲突保留输入；待生效动作不提前替换今日版本。
- 验证方式：组件测试 + 规则生命周期 E2E。
- 完成标准：保存后启用态、顺序、换行原样恢复，vN/草稿/待生效可观察。
- 实际落地情况：新增共享 `RuleMasterList` 与就地编辑 `TradeRuleEditor`，规则管理和今日打卡复用同一规则轨道；接入规则搜索/键盘选择、新建、草稿打开与保存、放弃草稿、发布、正式版/草稿来源复制、归档、恢复和未发布删除。选股及买卖明细支持增删、启停、上下排序、方向/类型联动与多行内容，资金汇总仅计算启用选股项；总本金与资金上限从 API 类型、表单模型、受控输入、定点比较到提交 payload 全程保持十进制字符串，复用 feature 级 `FixedDecimalInput` 限制 `NUMERIC(20,2)` 的 18 位整数与 2 位小数，并以 `bigint` 最小单位求和，未经过 JS `number`。正式版、归档版及无维护权限态不渲染明细结构命令且启停控件禁用。规则列表刷新失败只接管左侧轨道，保留右侧详情与未保存输入；仅首次没有可用规则快照时由整页错误态接管。页面同时展示当前有效、管理动作和编辑现场，不用抽屉覆盖上下文。规则编辑器已注册应用级未保存处理器，页签、规则和路由切换明确提供“继续编辑 / 放弃修改 / 保存草稿”三个动作，保存失败不放行；复制前的未保存输入也复用同一决策。1100px 主从区修正为上下结构，1366/1440 保持双栏，未新增配置字段、权限、菜单或 SQL。

### 6.7 任务 T7：今日打卡页面

- 开发状态：已完成（2026-08-23，已独立提交）
- 阶段验收状态：未完成；组件自动化已覆盖四组合，真实 PG 四组合、补录和修正待 T12-T13。
- 依赖：T5、T3、T4、T6 的规则轨道。
- 涉及文件：新增 `TradeCheckinForm.vue`、`TradeOperationEditor.vue`、`ViolationReasonCombobox.vue`、`StockOptionSelect.vue`。
- 目标：承接原型打卡区、四种组合、原因、操作、补录和修正入口。
- 操作：上下文选择、候选 0/1/多处理、方向联动、远程搜索取消迟到请求、原因行内删除、提交刷新联动；向应用协议注册打卡二选项处理器，并复用于页签/规则/日期切换。
- 产出：完整今日/历史补录表单。
- 影响范围：今日打卡页签与共享摘要。
- 边界与异常：局部加载失败保留已填内容；无有效版本阻止；409 不清表单。
- 验证方式：表单/组件测试 + 四组合与补录 E2E。
- 完成标准：需求 7.1.1 的字段、状态、权限和错误均有可观察行为。
- 实际落地情况：新增 `TradeCheckinForm`、`TradeOperationEditor`、`ViolationReasonCombobox`、`StockOptionSelect`，并把 T5 占位区替换为真实打卡主从工作区。页面按目标交易日并行读取有效规则与轻量摘要，默认优先待打卡规则，展示规则总数/已完成/待打卡和每条规则的履约版本、结果及修订号；摘要失败由打卡区局部接管并 fail-closed，规则、摘要和表单请求均防止迟到响应覆盖。表单覆盖已履约/未履约 × 有操作/无操作四种组合，历史交易日补录、已有记录只读及显式修正；无操作切换会确认后清空操作，未履约原因保持单选可输入、自定义项行内删除且停用历史快照仍可读，详细说明独立必填。多操作使用稳定前端 key，股票搜索 250ms 防抖并主动中止旧请求；当前搜索失败会清除非选中旧结果、保留已选快照，并在选择器下方独立渲染可访问的 `role="alert"` 重试提示，不依赖下拉空列表文案。方向变化保留股票/选股规则并重算买卖规则，候选唯一自动选中、多条留空、零条明确阻止。财务字段均可空且非负，价量金额不一致只警告确认，不覆盖用户金额，操作时间不预填虚构事实且必须属于履约日。首次提交与 `expected_revision` 修正分端点，修正操作只上送请求白名单并由服务端生成新操作 ID，避免复用旧修订主键；成功后刷新表单、规则轨道和页面摘要，409/请求失败保留输入。打卡编辑器已接入应用级二选未保存协议，页签、规则、交易日和路由切换只有“继续编辑/放弃修改”，不新增服务端草稿。T7 当时未虚构尚不存在的全局刷新目标，现已由 T9 的共享变更通知接通用户中心摘要；T12-T13 的可清理真实数据及长期 Playwright 仍按原计划后续完成。

### 6.8 任务 T8：历史列表、修订详情与修正

- 开发状态：已完成（2026-08-23，已独立提交）
- 阶段验收状态：未完成；拦截式三视口 E2E 已覆盖前端交互，真实 PG 修订链路待 T12-T13。
- 依赖：T5、T3、T4、T7。
- 涉及文件：新增 `TradeDisciplineHistory.vue`、`TradeCheckinRevisionDrawer.vue`。
- 目标：完成自动筛选、分页、详情修订切换和发起修正。
- 操作：复用通用表格/列/分页/搜索/抽屉；服务端筛选；保留筛选刷新；详情完整展示规则和操作快照。
- 产出：历史页签与页面内详情抽屉。
- 影响范围：工作台历史区域。
- 边界与异常：筛选失败由表格区接管；无维护权限只读；旧修订不可编辑。
- 验证方式：视图测试 + 筛选分页/抽屉/修正 E2E。
- 完成标准：任意修订均可追溯，修正后列表保留条件并显示新修订号。
- 实际落地情况：新增 `TradeDisciplineHistory` 和 `TradeCheckinRevisionDrawer`，历史页按交易日起止、规则、自评结果、有无操作、修正状态、股票及违规原因自动发起服务端筛选，筛选变化重置第 1 页，分页仅查询目标页；交易日复用真实交易日选择器，股票复用 R31 远程搜索，查询失败由表格区域接管并清除旧结果。主表复用 `AppDataTable`、`AppTableColumn`、`AppRowActions` 和既有 `pageSize/border` 设置，展示规则版本、操作数、违规摘要、修订状态与最后更新时间。详情复用页面边界 `PageDrawer`，抽屉状态与实例由 `TradeDisciplineView #overlays` 持有，pageRegistry 登记 `historyDetail` overlay，并按 DESIGN 使用 `xl` 复杂详情档位；可切换并读取任一不可变修订，完整展示履约结论、原因/说明、规则资金、启停状态与换行正文、操作规则关联、成交事实和财务完整度。当前修订的“发起修正”复用 T7 表单，不复制第二套编辑器；载入完成后自动进入修正态，规则/日期切换会退出历史返回语义，提交成功自动回到历史页并保留筛选和当前页、刷新出新修订号。历史筛选状态提升到工作台会话层，页签卸载重建不丢条件。真实页面复审另发现筛选控件在工作区宽度下被内层行容器收缩，已统一为四列响应式网格并让控件体占满单元格，复核无页面横向溢出。

### 6.9 任务 T9：用户中心快捷卡片与全局联动

- 开发状态：已完成（2026-08-23，已独立提交）
- 阶段验收状态：未完成；拦截式三视口 E2E 已覆盖快捷交互，真实 PG 快捷提交一致性待 T12-T13。
- 依赖：T4、T5、T7。
- 涉及文件：修改 `frontend/src/App.vue`；新增 `frontend/src/components/trade-discipline/TradeDisciplineQuickCard.vue`、`frontend/src/composables/useTradeDisciplineSummary.ts`。
- 目标：在现有抽屉内加入摘要、状态点、跳转和快捷无操作履约。
- 操作：打开时按需加载；权限条件渲染；确认对话框；成功刷新全局与页面；冲突跳正式页。
- 产出：P2 快捷闭环。
- 影响范围：应用顶栏/用户抽屉；不重排身份卡与退出按钮。
- 边界与异常：无权限/失败不显示红点，不轮询，不在抽屉承载长表单。
- 验证方式：App/快捷卡组件测试 + 任意授权业务页 E2E。
- 完成标准：抽屉提交和正式工作台状态一致。
- 实际落地情况：在既有 440px 用户中心抽屉的身份卡下新增 feature-scoped `TradeDisciplineQuickCard`，退出登录仍固定在底部；卡片覆盖加载、失败、无生效规则、全部完成和待打卡状态，展示最新交易日、完成/总数、每条规则版本及履约状态；有规则时同时提供“去打卡”和低层级“管理规则”入口。应用壳只在同时具备页面查看和打卡查看权限时渲染卡片，快捷按钮另受提交权限和 `v-permission` 双重约束；启动取得最新交易日后加载一次摘要以支持头像待办点，打开抽屉及打卡变更时刷新，不轮询，失败/无权/无规则均不显示误导状态点。新增模块级摘要与变更通知 composable：快捷提交固定调用专用端点且只传规则和交易日，二次确认成功后刷新卡片并通知已挂载工作台；409 不覆盖既有记录而直接带 `tab/rule_ref/trade_date` 进入正式表单，网络失败保留原规则行动作。工作台补齐该会话 URL 的日期/规则恢复，并在快捷变更后刷新当前摘要、规则、表单或历史；正式表单提交也反向通知全局摘要。真实页面视觉复核发现空态说明被按钮挤出孤行，已改为说明在上、操作靠右在下；未新增全局组件类型、页面配置、权限、菜单、SQL 或依赖。

### 6.10 任务 T10：后端自动化测试

- 状态：已完成（2026-08-23，已独立提交）
- 依赖：T1-T4。
- 涉及文件：新增 `backend/tests/test_trade_discipline_*.py`，修改 RBAC schema/资源扫描相关测试。
- 目标：覆盖 DDL、归属、事务、版本、事件、日期、原因、操作、权限和 API。
- 操作：使用临时用户/租户和清理夹具；参数化盘中/周末/节假日及同生效日事件；注入事务失败；验证 SQL marker 回滚。
- 产出：可复现 pytest 回归集。
- 影响范围：测试库；不依赖固定调试账号。
- 边界与异常：运行前按 DuckDB 锁规则停服，结束后恢复原状态。
- 验证方式：聚焦 pytest，再运行 `python -m pytest backend/tests/ -q`。
- 完成标准：本期后端验收项均有自动化断言。
- 实际落地情况：新增 `backend/tests/test_trade_discipline_t10.py` 作为跨 T1-T4 的后端验收集。R36 参数化覆盖交易日盘中、收盘后、周末和节假日动作，统一断言按上海自然日之后首个 `trade_calendar.is_open=true` 日期生效；生命周期故障注入覆盖发布、归档、恢复在已经分配 `event_seq`、写入激活事件后发生最终更新失败，分别断言版本、事件、主体状态、草稿和 `next_activation_seq` 原子回滚；长事务探针进一步断言事件时间来自 `clock_timestamp()` 动作时钟而不是事务开始时钟。新增人工 SQL 工件契约测试，将 marker、advisory lock、四资源码、fail-closed 条件、删除顺序、`perm_ver` bump 与 tombstone 写入锁定到运行时常量。既有 T1-T4 已覆盖 14 表 DDL/复合归属、marker 状态机和真实回滚、名称与版本、同生效日 `event_seq`、并发生命周期、四组合打卡、原因/修订事务、操作校验、跨归属、21 个 API 及精确权限矩阵，复核后无需重复修改 RBAC schema/资源扫描测试。专项 58/58、后端全量 979/979、目标文件 Ruff、`py_compile` 和 `git diff --check` 均通过；全量仅有既有 FastAPI `on_event` 弃用警告。测试前后按规则停止并恢复 dev 后端，最终 PID 以提交前健康检查为准，`/api/health=200`。本轮未运行前端 Vitest/build/Playwright、页面验证或真实 PG 页面业务写入：T10 未修改前端，且确定性真实业务夹具仍归 T12-T13。

### 6.11 任务 T11：前端单元与组件契约测试

- 状态：已完成（2026-08-23，已独立提交）
- 依赖：T5-T9。
- 涉及文件：新增页面/feature 组件测试，更新 router/pageRegistry/App 相关测试。
- 目标：覆盖配置消费、权限、四态、应用级脏保护、原因单选、规则候选、双状态和摘要联动。
- 操作：使用真实通用组件浅/实挂载组合；断言不直接使用 `el-table/el-drawer`；验证设置重载和恢复默认；模拟当前/非当前标签、路由、注销和容量淘汰，分别断言打卡二选与规则三选以及保存失败不丢缓存。
- 产出：Vitest 与布局契约回归。
- 影响范围：前端测试。
- 边界与异常：不以临时中文正文或脆弱 CSS 层级作为长期选择器。
- 验证方式：`cd frontend && npm test`。
- 完成标准：组件、路由、布局和 DESIGN 契约均通过。
- 实际落地情况：在现有真实挂载测试上补齐 6 项 T11 契约：交易纪律历史 `pageSize` 默认变化会归页并重载，恢复默认同时调用页面偏好与布局配置重置；快捷提交广播会刷新当前工作台摘要、规则和选中打卡表单；规则三选中的保存失败保持决策框、脏状态和输入，用户明确继续编辑后才返回不放行；非当前脏标签关闭被拒绝时标签和 KeepAlive 身份均不先删除；pageRegistry 锁定 `workspaceTabs` 为唯一 `growMain`、三个业务子面板、历史/设置受控字段及不消费 `defaultActive`，并断言历史表和修订抽屉复用 `AppDataTable`/`PageDrawer` 而不直写 `el-table/el-drawer`；router/App 源码契约锁定路由、注销与快捷卡共同消费应用级权限和未保存协议。复用判断：新增同文件 `ruleState` 与 `leaveDecisionButtons` helper 收敛重复夹具和三选定位；页面、编辑器、工作标签挂载器生命周期不同，抽成跨文件万能 helper 会增加配置和分层耦合，因此保持各自既有 helper；未新增组件、composable、util、配置字段或依赖，无需更新 DESIGN 组件清单。专项 5 个文件 68/68、前端全量 116 个文件 879/879、`npm run build`（含 `vue-tsc`）和 `git diff --check` 均通过；构建仅有既有第三方 PURE 注释和大 chunk 警告。未执行后端 pytest、Playwright、真实页面或真实 PG 写入：本轮仅修改前端测试，T12 夹具与 T13 浏览器/发布验收尚未开始。

### 6.12 任务 T12：交易纪律确定性 E2E 夹具与运行入口

- 状态：待开始
- 依赖：T1-T4、T10。
- 涉及文件：新增 `backend/devtools/e2e_trade_discipline.py`、`frontend/e2e/helpers/tradeDiscipline.ts`、`scripts/run-trade-discipline-e2e.sh`；修改 `start.sh`、`frontend/package.json`、`backend/devtools/rbac_test_users.py`、`agent-works/multi-tenant-rbac/test-users.md`、`agent-works/e2e-automation/guide.md`。
- 目标：提供不依赖开发者真实数据、可重复 seed/cleanup、失败必清理的 PG + DuckDB 夹具，并固化权限账号和执行命令。
- 操作：
  - `./start.sh e2e-trade-discipline seed --expected-pg-fingerprint <64位十六进制>` 与 `./start.sh e2e-trade-discipline cleanup --expected-pg-fingerprint <64位十六进制>` 调用 Python 夹具，`--expected-pg-fingerprint` 对两个动作均为必填；缺失、格式非法或与夹具进程直连 PG 计算值不一致时，必须在任何 PG/DuckDB 写入前 fail-closed。`npm run test:e2e:trade-discipline` 调用聚焦脚本并自动管理该参数。
  - 所有夹具物理写同时要求 `AI_STOCKS_ENV=dev|test|local`、`AI_STOCKS_E2E_WRITE=1` 和停服前从 `/api/health/e2e` 取得的 PG 指纹一致，任一不满足即 fail-closed；保存的指纹只存在聚焦脚本进程变量中，不写仓库或长期临时文件。
  - 固定账号：`debug_normal` 验证默认全功能；新增 `debug_trade_discipline_view`（菜单 + view/checkin-view）验证只读；新增 `debug_trade_discipline_submit`（菜单 + view/checkin-view/checkin-submit、无 rule-manage、无 stocks:view）验证 R31；`debug_board_only` 验证无权；`debug_tenant_admin/debug_system` 验证默认角色。账号均由 `dev-users` 幂等校准，不写密码。
  - PG 夹具归属固定 `debug_tenant + 对应 debug_* owner`，所有业务 ID 使用 `e2e_td_` 前缀，规则名使用 `E2E纪律-` 前缀；seed v1-v3、待生效 v4、发布/归档/恢复事件（含等时间戳不同 event_seq）、四种打卡、历史修订、自定义原因和多笔操作。
  - DuckDB 只写 `9988*.SZ` 股票及一段专属固定交易日/行情；seed/cleanup 前停止后端以独占写锁，测试后端以正常读写模式启动。cleanup 只按专属代码、日期和 PG 归属+前缀逆 FK 顺序删除，不碰真实数据。
  - 聚焦脚本先记录测试前后端状态，再取得指纹：若当前 `/api/health/e2e` 已返回合法值则直接保存；若后端未运行或未以 E2E 写模式启动，则受控停止现有后端（如有），以 `AI_STOCKS_ENV` + `AI_STOCKS_E2E_WRITE=1` 临时启动后端，等待健康后读取并校验 64 位指纹。只有成功保存指纹后才停止后端，并把同一值显式传给 cleanup、seed 和退出清理。
  - 完整顺序固定为“记录原状态 → 确保 E2E 后端可用并获取指纹 → stop → cleanup/seed（均传 expected fingerprint）→ 以 `AI_STOCKS_E2E_LOGIN_BYPASS=1` 启动被测后端 → 再读 `/api/health/e2e` 并断言指纹未变化 → 三视口 `--workers=1` 运行”。EXIT trap 无论通过、失败或中断均先 stop，再以已保存指纹精确 cleanup，最后恢复原后端运行/停止状态；若尚未取得指纹则禁止尝试物理清理，不遗留写开关或登录豁免。
  - 人工直接执行 seed/cleanup 时不自动猜测 PG：调用者必须先以相同本地配置和 E2E 写门控启动后端，从 `/api/health/e2e` 取得指纹，停止后端，再通过必填参数执行；夹具进程随后以 `pg_fingerprint(pg)` 常量时间比对。需要自动流程时只使用聚焦脚本，不复制一套隐式取值逻辑。
- 产出：确定性数据构造器、TS fail-fast helper、固定测试账号、`start.sh`/npm 命令和同步后的 E2E 事实文档。
- 影响范围：仅本地 dev/test/local PG 与 DuckDB 专属前缀数据；生产/共享环境拒绝运行。
- 边界与异常：重复 seed 先用同一已验证指纹精确 cleanup；部分 seed 失败由事务回滚；cleanup 可幂等重复；取得指纹后若 `.env.local`/PG 目标发生变化，后续直连比对或重启后的健康复核必须拒绝写入/测试；PG/DuckDB 任一清理失败使脚本非零退出并明确列出残留，不静默恢复成功状态。
- 验证方式：夹具单测、seed→查询计数→cleanup→零残留、重复 seed/cleanup、缺少/非法/错误/停服前后变化的 PG 指纹、后端原本运行/未运行、后端持锁拒绝和 trap 状态恢复测试。
- 完成标准：T13 不再依赖临时手工造数，固定命令可独立复现版本、生效、权限和历史修订场景。
- 实际落地情况：待实施。

### 6.13 任务 T13：Playwright、构建与发布验收

- 状态：待开始
- 依赖：T10-T12。
- 涉及文件：新增 `frontend/e2e/trade-discipline.spec.ts`，更新 WorkspaceTabs/路由/页面设置相关长期用例；同步相关事实文档入口（仅真实变化）。
- 目标：以真实点击链路验收全部纳入需求和原型一致性。
- 操作：使用 T12 专用命令覆盖首次建规则、草稿/发布/待生效、等时间戳事件全序、四类打卡、原因新增删除、历史修正、快捷入口、权限和三视口；覆盖路由离开、当前/非当前工作标签关闭、容量淘汰、注销和浏览器刷新保护，分别验证打卡二选项、规则三选项及保存失败不丢现场；运行 build 和回归。
- 产出：E2E、构建产物和上线核对结果。
- 影响范围：本地测试 PG/DuckDB、`frontend/dist`。
- 边界与异常：固定 5181、`--workers=1`；普通全量 E2E 明确排除需专属夹具的 spec，随后必须单独运行 `npm run test:e2e:trade-discipline`；不得污染真实用户数据。
- 验证方式：`cd frontend && npm test`、`npm run build`、`AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:trade-discipline`、其余全量 E2E、`git diff --check`。
- 完成标准：R1-R17、R26-R36 验收可观察且无未解释偏差。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划

| 路径/类别 | 用途 | 执行时机 | 影响范围 | 回滚方式 |
| --- | --- | --- | --- | --- |
| `backend/storage/pg_ddl.py` + `backend/cli.py` | 业务表、索引、打卡来源升级，以及专用 `_seed/_rollback_trade_discipline_rbac` 状态机和 `trade-discipline-rbac rollback` CLI；使用 marker `migration.trade_discipline_default_grants_v1` 和 advisory lock `8410010005` | 新库首次启动及既有环境受控重启时由 `init_pg_db()` 幂等执行；既有打卡来源默认回填 `workbench`；后端版本切换前由受控发布回滚显式调用 CLI | PG schema、`sys_menu/sys_resource/sys_role_*`、`app_config` marker、受影响用户 `perm_ver` | 有业务事实时保留业务表；RBAC 删除当前仍存在的账本内行并写 tombstone，已被管理员撤销的默认授权允许缺失，账本外授权拒绝级联；marker 缺失/损坏/冲突时 fail-closed |
| `backend/auth/constants.py` | 新库 normal/tenant_admin 默认业务功能码 | 与 seed 同时 | 默认角色新装授权 | 代码回滚；既有授权由 marker 账本处理 |
| `agent-works/trading-discipline-checkin/trading-discipline-schema.sql` | 与运行时代码等价的 DDL、冲突核验、正向迁移和回滚 SQL；marker JSON 固定记录 inserted menu/resource/role grants | 开发/评审时生成；生产默认不与启动迁移重复执行，仅用于人工复核或应急回滚 | 同上 | 取得同一 advisory lock，按账本删授权→资源→菜单，同事务 bump `perm_ver` 并把原账本改为 rolled_back tombstone |
| `backend/services/trade_discipline_service.py` 内置原因常量 | 返回八个只读内置原因；不写 `sys_dict`，个人原因才进入业务表 | 后端部署即生效 | 所有授权用户的原因候选，不修改历史快照 | 随代码回滚；已由用户创建的个人原因和历史违规事实保留 |
| `frontend/src/layout/pageRegistry.ts` + 既有 layout/user preference 表 | 页面密度、历史 pageSize 元数据与个人值 | 前端发布后，用户首次保存设置时写既有 PG 链路 | 当前用户当前 pageKey | 恢复默认删除/重置用户覆盖；不新增 SQL 列或 app_config |
| `backend/devtools/e2e_trade_discipline.py` + `start.sh e2e-trade-discipline` | T12 确定性 PG/DuckDB seed/cleanup；两个动作均要求 `--expected-pg-fingerprint`；PG 使用 `e2e_td_`/`E2E纪律-` 与固定 owner，DuckDB 仅用 `9988*.SZ` 和专属日期 | 仅在聚焦 E2E 前后执行；要求 `AI_STOCKS_ENV=dev\|test\|local`、`AI_STOCKS_E2E_WRITE=1`、停服前健康端点指纹与进程直连 PG 指纹一致，且 seed/cleanup 时后端已停 | 本地/测试 PG 的固定调试账号私有数据与 DuckDB 专属代码/日期；不触碰生产和开发者真实数据 | EXIT trap 使用停服前保存的同一指纹，按 FK 逆序和专属归属/前缀精确删除，恢复测试前后端状态；无指纹不清理，任一残留使命令失败并报告 |
| `frontend/e2e/helpers/tradeDiscipline.ts` + `scripts/run-trade-discipline-e2e.sh` + `frontend/package.json` | 调用 seed/cleanup、校验夹具引用并以 5181/单 worker 执行三视口 spec | T13 聚焦验收时；普通全量 E2E 排除此专属 spec | 测试进程、临时登录豁免和 `frontend/dist`（构建时） | trap 清理、移除运行时环境变量并恢复原后端；脚本失败保持非零退出 |

生产步骤先备份 PG 并核验未来 `trade_calendar` 可用，再在低流量窗口部署/重启。若应用代码回滚，保留新增业务表避免丢失已提交事实；必须先回滚前端 `dist`，再趁本版本 CLI/SQL 尚未随代码切换移除时执行专用 RBAC 回滚，核验 tombstone、删除计数和 `perm_ver`，最后回滚后端 API。后端回滚并重启后验证 seed 不会复活任何目标行；不得以“隐藏菜单”代替完整回滚。待数据保留期和导出策略另行确认前，不提供生产删表回滚。

## 8. 测试与验证计划

- 单元测试：规则名称归一化、金额定点、版本实质变化、原因匹配、操作规则候选与完整度；生命周期覆盖相同 `occurred_at`、长事务、并发发布/归档/恢复和事务回滚，断言无幽灵事件或计数器误推进，并严格按 `(effective_from_trade_date,event_seq)` 得到唯一结果。具体完成情况：T2 已覆盖规则生命周期及列表单查询双状态；T3 已覆盖四种打卡组合、金额/时间/规则关联、批量股票代码校验、原因归一化复用与删除快照、故障回滚、旧版本固定、快捷来源/冲突/并发幂等、历史筛选分页和跨 owner 隔离。T10 新增盘中/收盘后/周末/节假日参数化、长事务动作时钟及发布/归档/恢复在激活事件写入后的事务失败回滚，专项回归 58 个 pytest、后端全量 979 个 pytest 通过。
- 接口测试：所有端点成功/422/403/404/409、分页筛选、快捷幂等、R31 限流边界。具体完成情况：T4 已覆盖全部 21 个端点的统一成功响应契约、OpenAPI 可见性、权限矩阵、401/403/404/409/422、非法日期范围、专用股票搜索空值/上限/独立权限、跨 owner 隐藏和审计脱敏；分页筛选与快捷并发幂等已有 T3 服务测试，T10 完成后后端接口验收自动化已闭环，T12-T13 继续覆盖真实 PG 页面端到端链路。
- 页面/交互测试：三页签、主从区、全部命令、四种打卡、修订抽屉、全局快捷卡；未保存保护逐项覆盖路由、当前/非当前工作标签关闭、容量淘汰、注销、浏览器刷新以及页签/规则/日期切换，分别断言打卡二选、规则三选、保存失败不放行且标签/KeepAlive/输入均未先删除。具体完成情况：T5 已用视图测试覆盖三页签、交易日 fail-closed、规则加载和无权限态；协议单测覆盖单标签/全局确认、当前/非当前关闭、容量淘汰拒绝、一次性路由 permit、注销聚合决策和 `beforeunload`。T6 新增规则轨道和编辑器 8 项组件测试，覆盖搜索/键盘选择、双状态、启停/顺序/换行保存、明确三选、保存后发布修订号、放弃草稿后重载状态、复制来源及详情请求竞态。T7 新增打卡、操作、股票和原因组件回归，覆盖四组合、首次提交/修正、修订号、请求字段白名单与操作新 ID、二选未保存保护、候选唯一/多条、方向联动、防抖/旧请求中止、自定义原因删除、摘要局部错误和无权限分支。T8 新增历史与修订详情 6 项组件测试并扩充 T7 历史入口测试，覆盖完整列、服务端查询参数、分页重置、错误接管、快照展示、修订切换、旧修订/无维护权限只读及异步上下文完成后自动进入修正；新增三视口 Playwright 覆盖筛选、抽屉、修订切换、修正提交、返回历史保留筛选和新修订号。T9 新增快捷卡组件测试，覆盖权限分支、二次确认、专用入参、成功刷新/广播和 409 正式页引导；三视口 Playwright 从普通业务页覆盖头像待办点、抽屉摘要、快捷提交、全局刷新及会话 URL 对规则/日期的真实恢复。T13 使用可清理真实夹具补全正式数据链路。
- 组件资产闭环测试：验证通用组件真实导入/渲染、feature 组件事件契约、pageRegistry、密度/pageSize 保存读取消费与重置；断言 `workspaceTabs` 使用真实 `tabs` kind 且唯一 `growMain`，三个业务 panel 是实际消费者，`defaultActive` 未进入长期偏好，滚动由活动 panel 承接；确认没有新增未消费字段。具体完成情况：T5 已通过 pageRegistry、layout、component-config、table/button system 与页面实挂载测试；T8 将历史表格迁入 feature 组件后，页面组件树仍真实消费 `pageSize/border`、`AppDataTable` 和 `PageDrawer`，并更新机器契约递归核验实际组件树。T11 已补齐交易纪律专属 registry/通用组件静态契约、历史分页默认变化后的真实重载及恢复默认双重重置，未新增配置字段。
- T11 阶段验证记录：交易纪律页面、规则编辑器、工作标签、pageRegistry 和 router/App 契约专项 5 个文件、68 项通过；前端全量 Vitest 116 个文件、879 项全部通过，`npm run build`（含 `vue-tsc`）和 `git diff --check` 通过。首轮专项 66/68，通过复核发现两项测试假设偏差：标准 registry 会自动补齐历史 `border` 与设置抽屉字段，保存失败的三选 Promise 会保持待决供原框重试；按真实契约修正后全部通过。第三方复审另将新增三选用例从 `.el-dialog__footer` 层级选择器改为稳定 `ElDialog` 组件 helper，最终未发现生产代码、权限、配置或 DESIGN 漂移。后端 pytest、Playwright、真实页面及真实 PG 写入未执行：本轮只修改前端测试，相关验收仍归 T12-T13。
- 权限与数据范围测试：system/normal/tenant_admin/自定义最小权限/无角色；跨 owner/tenant；有 submit 无 stocks:view；按钮和接口一致。具体完成情况：T1 已验证默认授权、管理员撤销后重启不补回/不失败、seed 幂等、冲突原子回滚、marker 严格结构、tombstone 不复活及账本外授权拒绝回滚；T4 已验证全部 21 端点精确权限矩阵、自定义最小权限、未认证、无角色 fail-closed、摘要双权限、跨 owner 404 和 submit/stocks:view 独立边界；T5 已验证 system/tenant_admin/normal 的菜单门控解除、页面只读/无权限分支和按钮系统契约，T6-T7 已让规则命令与打卡新增/删除/提交/修正按钮消费各自精确权限，并验证无查看权限接管、无提交权限只读；T8 验证历史查看权限接管、无提交权限不渲染修正命令、旧修订不可编辑，股票筛选继续复用独立于 `stocks:view` 的 R31 端点；T9 在应用壳同时校验 view + checkin-view 才展示卡片，并让快捷命令独立消费 checkin-submit，无权/失败均不产生头像状态点。
- 确定性夹具测试：覆盖必填指纹缺失/格式非法/不匹配、后端原本运行和未运行两种取值路径、停服前后 PG 目标变化及后端持锁拒绝；再执行两轮 `获取指纹→stop→seed→计数与引用核验→cleanup→零残留`，模拟取值前、取值后、seed 后和测试中断验证 trap 只在已有可信指纹时清理并恢复原服务状态。具体完成情况：待验证。
- 回归测试：按锁规则运行后端聚焦及全量 pytest；运行前端 Vitest、build、普通全量 Playwright（排除专属 spec），再执行 `AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:e2e:trade-discipline`；测试前后核验服务状态。具体完成情况：2026-08-23 的 T1-T4 复审已完成后端全量 967/967 等验证，详见前次提交记录。T5 前端全量 Vitest 105 个文件、824 项通过，`npm run build` 通过，并完成登录/权限/设置验收。T6 前端全量 Vitest 107 个文件、832 项全部通过，`npm run build` 通过；构建仅有既有 PURE 注释与大 chunk 警告。使用固定本地账号 `debug_normal` 完成登录态真实页面验收：创建未发布规则，填写两条选股和两条买卖明细，验证停用项不计资金、上下排序、买卖方向联动、换行内容经保存和整页刷新原样恢复；明确三选中“继续编辑”不离开，“保存草稿”成功后才切换页签；最后通过页面删除未发布规则，确认列表回到 0 条，退出账号并复原视口。1440×900、1366×768、1100×620 的 document/main/panel 均无横向溢出，1100×620 主从区为上下结构且动作可达。后端未改动，未重复运行 pytest/Ruff；运行中的 dev 后端保持 PID 80325，`/api/health=200`。真实发布、归档、恢复会留下不可删除的正式业务数据，本轮未在固定调试账号下执行，前端命令通过组件 mock、既有 T2/T4 后端测试和接口契约复核验证；普通全量 Playwright、交易纪律专属 Playwright及 T12 可清理夹具仍按计划归 T12-T13，本轮未执行。
- T7 阶段验证记录：交易纪律组件/视图专项 7 个文件、23 项通过，覆盖四组合、首次提交/修正、旧修订操作 ID 不复用、装饰字段不外泄、二选未保存保护、无提交权限只读、候选唯一/多条、方向联动、股票搜索防抖及旧请求中止、自定义原因行内删除和摘要局部错误；前端全量 Vitest 111 个文件、845 项全部通过，`npm run build` 和 `git diff --check` 通过，构建仅有既有 PURE 注释与大 chunk 警告。使用固定本地账号 `debug_normal` 在专用 5181 端口完成真实登录，未登录直达正确回跳登录页，登录后今日打卡/规则管理/历史记录三页签及各自空态加载正常，控制台无错误；1440×900、1366×768、1100×620 的 document/main/panel 均无横向溢出，紧凑视口信息层级和操作入口可达。该账号当前没有生效规则；为避免在 T12 可清理夹具尚未实现时留下不可删除的正式规则和打卡事实，本阶段没有在浏览器执行真实表单提交、修正、原因新增删除或股票选择，相关行为由本次组件测试和既有 T3-T4 后端测试覆盖，明确标记为未做登录态真实数据验证。普通全量 Playwright、交易纪律专属 Playwright仍按计划归 T12-T13，本轮未执行；后端代码未改动，未重复运行 pytest/Ruff，运行中的 dev 后端保持 PID 80325，`/api/health=200`。
- T8 阶段验证记录：历史/修订/T7 复用表单与工作台专项 4 个文件、18 项通过；前端全量 Vitest 113 个文件、852 项全部通过，`npm run build`、`vue-tsc` 和 `git diff --check` 通过，构建仅有既有 PURE 注释与大 chunk 警告。新增长期 Playwright 使用真实 `debug_normal` 登录、页面级确定性只读/拦截夹具且不写 PG，在 1100×620、1366×768、1440×900 三视口 3/3 通过，完整覆盖服务端筛选参数、修订详情、旧修订只读、发起修正、提交后返回历史、筛选保留和新修订号。另用固定账号在专用 5181 端口读取真实后端空历史数据，验证筛选/重置、四列响应式布局、空态和控制台；实测 1280×720 的 document/history workspace 均无横向溢出且控制台无 warning/error。真实账号当前无打卡数据，且 T12 可清理业务夹具尚未实现，因此本阶段未对真实 PG 执行打卡修正，也未独立复核带真实数据的详情快照；相关前端点击链路由页面级确定性 Playwright 覆盖，后端修订行为由 T3-T4 测试事实支撑。普通全量 Playwright、T12 专用夹具、后端 pytest/Ruff 本阶段未执行：前两项仍归 T12-T13，后两项因本阶段未改后端。后端保持 PID 80325，`/api/health=200`。
- T9 阶段验证记录：快捷卡、工作台参数恢复与设计契约专项 4 个文件、24 项通过；前端全量 Vitest 114 个文件、856 项全部通过，`npm run build`、`vue-tsc`、`git diff --check` 通过，构建仅有既有 PURE 注释与大 chunk 警告。首轮全量曾真实发现并整改新卡片的原生命令按钮、游离 gap 和宽泛微字号选择器三项设计契约违规；第三方复审又补充去除快捷成功的重复摘要请求，并为“同页查询参数切换被未保存保护拒绝”增加 URL 回滚和回归测试，整改后专项及全量复跑通过。新增长期 Playwright 使用真实 `debug_normal` 登录、页面级确定性拦截夹具且不写 PG，在 1100×620、1366×768、1440×900 三视口 3/3 通过，覆盖任意业务页头像待办点、用户抽屉、二次确认、快捷专用入参、摘要刷新、正式页 URL 及规则/日期恢复。另用该固定账号在专用 5181 端口读取真实后端：普通业务页可打开用户中心，真实最新日为 2026-08-21，账号当前无生效规则，卡片正确显示创建引导、身份卡与退出按钮顺序不变；可视复核修正空态孤行后无横向挤压，控制台无 warning/error。因 T12 可清理业务夹具尚未实现，未在真实 PG 创建正式规则或执行快捷打卡，避免留下不可删除事实；带待办规则的完整点击由真实账号登录 + 页面级确定性 Playwright 覆盖，后端快捷幂等/冲突仍由 T3-T4 测试事实支撑。普通全量 Playwright、T12 专用夹具、后端 pytest/Ruff 本阶段未执行：前两项归 T12-T13，后两项因本阶段未改后端。后端保持 PID 80325，`/api/health=200`。
- T5-T9 复审整改验证记录（2026-08-23）：首轮曾声明“8 项复审问题代码与文档整改通过”，后续复审证明该结论过早：规则金额虽已用 `bigint` 比较，但 API 字符串先经 `Number()` 和 `el-input-number` 进入浮点模型；股票搜索失败也只写入有选项时不可见的 `no-data-text`。现已补齐 API→表单→受控输入→定点比较→提交 payload 的全字符串金额链路，并以 18 位整数、2 位小数约束匹配 `NUMERIC(20,2)`；覆盖 `9007199254740992.01`、最大值 `999999999999999999.99`、相邻分位及越界输入。举一反三复核同时发现 T7 成交价、数量、金额、费用及历史快照存在同源浮点路径，已复用受控输入并按 `NUMERIC(20,4)/(20,2)` 收紧类型，价量乘积使用 `bigint` half-up 归整，历史金额分组展示不再经过 `Number()`。后端统一响应的 `Decimal` 字符串序列化以 `ApiResponse(...).model_dump_json()` 本地探针确认；未修改后端。股票搜索错误改为独立可见 `role="alert"`，测试断言真实 DOM 可见文本。聚焦回归 7 个文件、35 项通过；前端全量 Vitest 116 个文件、873 项全部通过；`npm run build`、`vue-tsc`、`git diff --check` 通过，构建仅有既有 PURE 注释与大 chunk 警告。T8/T9 两条长期 Playwright 首轮 4/6，通过整体复审发现快捷卡用例的非精确“用户中心”定位会同时命中“关闭用户中心”；限定顶栏容器并精确匹配后，全部源码整改完成后的三个目标视口最终 6/6 通过。原 8 项现已完成代码与文档整改，但仍不等于 T5-T9 阶段验收通过。真实 PG 发布、归档、恢复、四组合打卡、补录、修正、快捷提交仍未执行，原因是 T12 可清理夹具尚未完成；后端 pytest/Ruff 未执行，原因是本轮未修改后端。后端保持 PID 80325，`/api/health=200`。
- 后端 `NUMERIC` 值域复审整改记录（2026-08-23）：确认前端字符串定点链路不能替代 API/服务端防御，补充两位/四位小数受约束 Decimal 请求类型及服务层同等级整数位校验。API 覆盖精确最大值、最大值加最小单位、额外整数位和额外小数位，规则创建、普通打卡和修正越界均在 PG 前返回统一 `HTTP 422 + code=4000`；服务单测覆盖绕过请求模型时的相同边界。按 DuckDB 锁规则记录运行状态、正常停服后，T2-T4 聚焦 41/41、后端全量 970/970、目标文件 Ruff、`py_compile` 和 `git diff --check` 均通过；补充统一错误码断言后单测 1/1 复跑通过，全量仅有既有 FastAPI `on_event` 弃用警告。测试后已恢复 dev 后端，PID 36187，`/api/health=200`。未执行前端 Vitest/build/Playwright 和真实 PG 业务写入：本轮未修改前端，且真实写链路仍等待 T12 可清理夹具。该后端值域阻塞项已关闭，但 T5-T9 正式阶段验收仍待 T10-T13 其余准入项完成。
- 异常与边界测试：日历空/滞后、周末发布、同日等时间戳多事件、并发生命周期、草稿与修订并发、规则被归档、网络失败、原因删除、规则候选为零、财务字段不完整。具体完成情况：T2-T4/T10 已覆盖日历空、盘中/收盘后/周末/节假日、同生效日等时间戳多事件、并发发布/归档/恢复、事件分配后事务回滚、草稿乐观锁、修订乐观锁、归档态拒绝编辑、原因删除快照、规则候选非法和财务字段不完整；前端网络失败可观察性已有 T5-T9 组件测试，真实网络/PG 页面链路仍待 T12-T13。
- 原型一致性：逐区对照 HTML 的页头、三页签、两套主从区、操作/原因/双状态、历史抽屉、设置抽屉、用户快捷卡和 1100×620/1366×768/1440×900 退化；原型批注和演示数据不得进入线上文案。具体完成情况：T5-T9 已核对页面框架、规则/打卡主从区、就地编辑、规则与履约状态、操作事实、原因输入、历史筛选表格、页面边界修订抽屉、修订切换、用户中心身份卡下快捷摘要及响应式样式契约；带真实 PG 正式规则的数据验收待 T12-T13 确定性夹具完成。
- 需求映射验证：用脚本核对 requirement 的 R1-R36 范围编号均在第 5 章出现，纳入项均有任务/状态/验证，跳过项均有原因。具体完成情况：2026-08-23 T10 复核脚本确认 28 个纳入项（R1-R17、R26-R36）在需求第 5 章和计划中均有映射，R18-R25 均有跳过/后续原因，缺失项为 0。

## 9. 发布与回滚

- 发布前检查：确认 PG 备份、迁移 marker 未冲突、DuckDB 未来开市日存在、默认角色/自定义角色授权方案、无明文或本地数据进入 Git；按测试前状态停服/恢复。
- 发布步骤：先部署幂等 DDL/专用 RBAC seed 与后端 API并验证健康、marker 和权限，再发布前端源码及同步后的 `dist`，最后以 normal、tenant_admin、仅查看、仅提交、无权限账号跑冒烟；存量自定义角色由管理员按需授权，不自动扩大。
- 配置或环境变量：生产无新增环境变量和业务 `app_config`；RBAC 仅新增稳定 migration marker。T12 只复用既有 `AI_STOCKS_ENV`、`AI_STOCKS_E2E_WRITE`、`AI_STOCKS_E2E_LOGIN_BYPASS` 测试门控，不能进入生产启动配置；页面设置复用现有 layout/user preference 链路。
- 回滚方案：先回滚前端 `dist` 以移除静态路由；随后在当前后端版本和 SQL 工件仍存在时执行 `python -m backend.cli trade-discipline-rbac rollback --confirm-marker migration.trade_discipline_default_grants_v1`，在同一 advisory lock 下按 marker 账本撤销本次 role grants、资源和菜单，bump `perm_ver`、写 rolled_back tombstone 并核验输出；只有 CLI 成功且 tombstone/目标行核验通过，才回滚后端 API 并重启验证不会重新 seed，否则停止回滚流程并保留当前后端工件供修复。保留业务表与用户事实，仅确认从未写入生产事实时才允许逆序删表。

## 10. 风险、假设与待确认项

### 10.1 风险

- 生命周期动作依赖 DuckDB 已同步未来交易日；缺失时按需求 fail-closed，可能暂时阻止发布/归档/恢复，页面必须给出同步指引。
- 新功能表和事件较多，事务与复合外键实现复杂；以 T1-T3 的仓库测试先锁定不变量，再开放 API。
- 应用级未保存协议会经过全局工作标签与注销链路；仅注册脏页面参与拦截，干净页面保持原行为，并用现有页面回归防止壳层改动误伤其他模块。
- 用户中心摘要会增加一次轻量请求；登录后取得最新交易日时加载一次以支持头像待办点，打开抽屉和履约变更时按需刷新，不轮询，避免全局性能回退。
- 历史股票/原因模糊筛选可能增长；首期通过归属前缀索引、分页和受控查询观察，实际数据量不足以支持更重的全文索引决策。

### 10.2 假设

- 使用现有 PostgreSQL、DuckDB、Element Plus 和布局系统，不引入新依赖。
- 业务 ID 沿用项目 opaque `TEXT` 引用风格；API 不暴露归属复合键。
- 系统内置未履约原因由后端常量返回，个人原因才入表；历史始终保存名称快照。
- 本期新增的 feature-scoped 组件只服务交易纪律模块，不登记为可配置系统组件；若未来第二个业务模块消费，再升级为全局真实复用组件并同步 DESIGN 清单。

### 10.3 待确认项

- 无阻塞待确认项。开发中若发现生产数据库存在与计划 marker、菜单 ID/code/route 或资源 ID/code 冲突的外部数据，专用迁移必须原子失败并停止发布，由运维先确认来源；不得在执行时临时改 marker、锁键或覆盖既有行。
