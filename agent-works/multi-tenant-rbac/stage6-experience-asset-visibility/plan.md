# 开发计划

## 1. 需求来源与目标

- 需求文档：[../requirement.md](../requirement.md)。
- 上游实现依据：
  - 阶段四 B 已完成评分方案公开能力：[../stage4-public-profile-visibility/plan.md](../stage4-public-profile-visibility/plan.md)。
  - 阶段五已完成审计、字典和系统设置承载：[../stage5-platform-capabilities/plan.md](../stage5-platform-capabilities/plan.md)。
  - 阶段六前已更新日志审计原型：[../prototypes/audit-log.html](../prototypes/audit-log.html)，详情抽屉新增 R24 字段变更表。
  - 页面设计闭环依据：[../../configurable-layout-system/page-template.md](../../configurable-layout-system/page-template.md) 与 [../../../DESIGN.md](../../../DESIGN.md)。
- 功能目标：进入第六阶段，补齐体验增强项，并把原先独立排期的 R28 其他资产公开能力纳入本阶段。
- 当前计划状态：进行中（T1、T2 已完成，T3-T12 未开始）。
- 计划输出目录：`agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/`。
- 本阶段纳入：
  - R22：token 静默刷新，避免长操作中 access token 过期直接打断。
  - R23：审计日志保留期自动清理任务，复用 `audit.retention_days`。
  - R24：操作审计字段级 from/to 变更对比。
  - R28：评分方案之外的其他资产公开能力，覆盖筛选方案、买卖方案和回测记录。
- R28 验收口径：需求文档第 11 章原先止于 R24，本次同步补充 R28 验收行；计划中的 R28 验收来自 requirement.md 的 R28 资产公开说明、阶段四 B 的评分方案 `visibility/profile_ref/readonly/copy` 模型，以及阶段六 §3.1 的三类资产范围。
- 本次不做：
  - 不做公开市场、审批流、收藏、搜索广场、运营推荐或计费联动。
  - 不扩展自选股分组、盘感训练记录、布局配置、系统配置、字典或数据任务为公开资产。
  - 不允许非 owner 修改、删除、覆盖或强制刷新他人公开资产。
  - 不改变行情 DuckDB 只读分析和用户资产 PG 读写的双库边界。
  - 不新增独立大页面；优先在现有策略筛选、买卖指标、策略回测和日志审计页面内完成。

### 1.1 本次口径修订

- `R28 其他资产公开能力` 从“独立需求（排期待定）”调整为阶段六范围。评分方案当前事实保持不变，本阶段以其 `visibility/profile_ref/readonly/copy` 模型为基线扩展。
- 资产公开范围统一为 `private | tenant | public`：
  - `private`：仅 owner 可见。
  - `tenant`：owner + 同租户用户可见。
  - `public`：全体登录用户可见。
- 公开资产默认只读引用；方案类资产可复制为当前用户 private 副本；回测记录可查看详情并复用参数重跑，不直接复制大结果表。
- 回测记录属于结果资产，不是策略方案。公开的是一次已完成运行结果和参数快照；查看他人公开回测不写 viewer 资产，重跑才生成 viewer 自己的记录。

## 2. 当前项目依据

### 2.1 已完成的评分方案公开模型

- `score_profile` 已有 `visibility/published_at/published_by`，并有合法值约束和可见性索引。
- `ScoreProfileRepo` 已实现：
  - opaque `profile_ref` 编解码。
  - `list_visible/get_visible/set_visibility/copy_visible/versions_visible`。
  - owner-only 保存/删除与 visible 读取语义分离。
- `/api/score-profiles` 列表、详情、版本、复制和公开接口已支持 visible 语义。
- `/api/board`、回测服务和回测引擎已经能消费可见评分方案 `profile_ref`。
- `ConfigView.vue` 评分规则页已实现 `readonly/source/visibility` 展示、发布下拉和“复制为我的方案”，但可见性标签目前是页面内联实现，阶段六需抽出资产可见性组件避免三页复制。

### 2.2 R22 当前依据

- 后端已有 `/api/auth/refresh`，`AuthService.refresh()` 会校验 refresh token、账号状态、租户状态和 `perm_ver`，并轮换 refresh token。
- 前端 `frontend/src/api/auth.ts` 已有 `refresh()` API 封装；`authToken.ts` 是 localStorage token 事实源，`client.ts` 请求拦截从 localStorage 读 access token。
- 当前 `client.ts` 遇到 401 直接清态跳登录，未尝试静默刷新；这会打断长时间停留后的查询、保存、回测和页面设置操作。
- `client.ts` 实现静默刷新时不能直接依赖 store；应复用 refresh 契约或低层独立 axios 实例，避免业务拦截器递归。

### 2.3 R23 当前依据

- 阶段五已新增 `audit.retention_days`，系统设置可配，`AuditService` 已把它用于默认查询窗口和页面提示。
- `audit_log` 已有按 `event_time`、租户、分类、资源码、结果的索引。
- 项目已有 `backend/scheduler/scheduler.py`，使用 APScheduler 单例，并由 `backend/main.py` startup/shutdown 启停；阶段六必须复用该调度器注册每日审计清理 job，不新建并行定时器。
- 当前缺口是自动删除超保留期审计记录；阶段五明确未实现 R23。

### 2.4 R24 当前依据

- 当前 `audit_log.context` 只保存脱敏上下文；`AuditService._sanitize_context()` 有白名单与敏感 key 过滤。
- 审计页详情抽屉当前展示执行信息、资源信息、错误摘要和事件上下文。
- 原型已更新为在详情抽屉展示“字段变更”表，列为字段、变更前、变更后；无字段级变更时显示“无字段级变更”。

### 2.5 R28 其他资产当前依据

- `screen_profile` / `screen_profile_version`：
  - 表结构目前没有 `visibility/published_at/published_by`。
  - `backend/screening/profile.py` 只有 owner-only 的 `list/get/save/delete/versions`。
  - `/api/profiles` 和 `ScreenView.vue` 都按 owner-only 方案工作。
- `trade_profile` / `trade_profile_version`：
  - 表结构目前没有 `visibility/published_at/published_by`。
  - `backend/signals/trade_profile.py` 只有 owner-only 的 `list/get/save/delete/versions`。
  - `/api/trade-profiles` 与 `ConfigView.vue` 买卖指标页没有只读、复制和发布状态。
- `backtest_run` 及从表：
  - `backtest_run` 目前没有 `visibility/published_at/published_by`。
  - `BacktestService.list_runs/get_run/delete_run` 只读当前 owner。
  - 回测服务已能解析可见评分方案，但筛选方案、买卖方案仍按当前 owner id 解析。
  - `BacktestView.vue` 的评分方案下拉已支持可见评分方案；选股方案、买卖方案和历史回测仍只列当前用户资产。
- 权限资源已有 `screen-profile:view/save/delete`、`trade-profile:view/save/delete/preview`、`backtest:view/run/delete`；阶段六新增 publish 权限码时需同步 `BUSINESS_RESOURCE_CODES`、`_SEED_RESOURCES`、默认授权、路由扫描测试和 `perm_ver` 规则。

### 2.6 前端设计与组件依据

- 本阶段不新增路由，不新增可导航页面；改造既有 `ScreenView.vue`、`ConfigView.vue`、`BacktestView.vue`、`AuditLogView.vue`。
- `SourceTag.vue` 是配置来源标签，不是资产可见性标签；不能直接复用为 `visibility/source/readonly` 资产标签。
- 评分规则页已有公开能力样板，但可见性 tag 与发布入口仍在页面内；阶段六新增 `AssetVisibilityTag` 和 `AssetVisibilityActions` 作为普通真实复用组件，不进入布局配置组件种类。
- 本阶段不新增系统布局组件种类，不新增 `COMPONENT_CATALOG` 或 `COMPONENT_FIELD_DEFS` 字段；若实现中发现需要配置化组件字段，必须先回到计划更新维护矩阵。

## 3. 实施范围

### 3.1 必须实现

| 需求编号 | 需求内容 | 本阶段开发内容 | 对应任务 | 完成标志 |
| --- | --- | --- | --- | --- |
| R22 | token 静默刷新 | 前端 401 后用 refresh token 单飞刷新、重放原请求、轮换本地 token；刷新失败再跳登录 | T2 | 长时间停留后首次受控请求可自动恢复，不重复弹错 |
| R23 | 审计保留期自动清理 | 新增审计清理服务、CLI 入口、复用 APScheduler 每日 job、审计事件记录和测试 | T3 | 超过 `audit.retention_days` 的审计日志可按计划清理 |
| R24 | 字段级变更对比 | `audit_log` 增结构化 `changes`，服务层脱敏、采集关键变更，审计页详情展示 from/to | T4,T10 | 配置、RBAC、字典、公开状态等关键变更可在详情里看到字段差异 |
| R28-8 | 筛选方案公开能力 | `screen_profile` 增 visible 模型，API 支持可见列表/详情/版本/发布/复制，筛选页只读和复制 | T5,T6,T9,T11 | 用户可查看公开筛选方案、复制为自己的 private、非 owner 不可改删 |
| R28-9 | 买卖方案公开能力 | `trade_profile` 增 visible 模型，API 支持可见列表/详情/版本/发布/复制，买卖指标页只读和复制 | T5,T7,T9,T11 | 用户可查看公开买卖方案、复制为自己的 private、非 owner 不可改删 |
| R28-10 | 回测记录公开能力 | `backtest_run` 增 visible 模型，列表/详情支持可见记录，owner 可公开/收回，viewer 可复用参数重跑 | T5,T8,T9,T11 | 同租户/全体公开回测可读，删除和覆盖仍限 owner |
| R20/R21 延续 | 权限和菜单闭环 | 新增资源码、默认角色授权、按钮 `v-permission`、路由/端点扫描测试 | T1,T11,T12 | 无权接口 403，按钮不显示，菜单不 fail-open |

### 3.2 可选增强

| 需求编号/增强编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| E1 | 统一展示 `owner_label/source/readonly/visibility` 标签 | 原计划可选增强，整改后纳入必做 UI 交付 | 待开始 | T9,T11 | 三类 R28 资产与评分页统一使用 `AssetVisibilityTag`，避免页面内复制标签逻辑 |
| E2 | 回测历史增加“我的 / 租户公开 / 全体公开”筛选 | 原计划可选增强，纳入本阶段 | 待开始 | T8,T9,T11 | API 返回 `source` 后前端提供轻量筛选；不新增独立公开广场 |
| E3 | 审计摘要中展示清理任务最近执行结果 | 后续建议 | 跳过 | - | R23 本阶段通过审计事件和 CLI/调度日志验证；摘要卡片会改变审计页信息架构，后续如需要再补原型和任务 |

### 3.3 暂不实现

- 不做批量审批、公开撤回审批、运营推荐和公开资产广场。
- 不做跨租户协作编辑。
- 不把公开回测的大结果表复制给 viewer；viewer 需要重跑时走当前 `backtest:run` 权限生成自己的记录。
- 不改变评分方案阶段四 B 已完成的外部 API 契约，除非为抽取通用 helper 做兼容性内部重构。
- 不把 `stock_group`、盘感训练记录或系统配置纳入 R28 阶段六资产公开范围。

## 4. 技术方案

### 4.1 总体实现思路

阶段六按“权限与 DDL 规划 -> 体验增强 -> 审计治理 -> 通用资产可见性 -> 三类资产接入 -> 前端页面闭环 -> 测试与文档”推进。

核心原则：

- 复用评分方案的 `private/tenant/public + opaque ref + readonly + copy` 模型。
- 抽出通用 asset ref 和可见性工具，避免 screen/trade/backtest 各自实现不同口径。
- owner 写语义和 visible 读语义分离：保存、删除、发布只查 owner；列表、详情、运行引用可以走 visible。
- 公开资产读侧不得信任前端传入 owner；所有 opaque ref 解析后必须再次校验当前用户可见性。
- 回测结果公开只读，不让 viewer 删除、覆盖或强制刷新 owner 结果。
- 审计字段采集不作为 R28 公开能力的硬前置；T6/T7/T8 依赖 T1/T5，R28 公开状态变更采集在 T4 完成后接入。

### 4.2 R22 静默刷新设计

- `client.ts` 响应拦截遇到 401 时：
  - 登录页、`/auth/login`、`/auth/register`、`/auth/refresh` 的 401 不触发静默刷新。
  - 有 refresh token 且原请求未重试过时，调用 refresh 契约刷新 token；实现上可使用独立 axios 实例或拆出低层 refresh 方法，不能让 refresh 请求再次进入业务响应拦截器。
  - 使用模块级 `refreshPromise` 实现单飞；并发多个 401 只发一次 refresh。
  - 刷新成功后更新 localStorage 中 access/refresh token，并重放原请求。
  - 刷新失败或 `perm_ver` 变更时清态跳登录。
- `authToken.ts` 增加 `getRefreshToken()`、`updateTokens()`，保持 client 与 store 不循环依赖。
- `auth store` 保持现有 `_applyLogin/fetchMe`；静默刷新只更新 token，不强制重拉 `/me`，因为角色和菜单没变；若刷新失败则清态。

### 4.3 R23 审计清理设计

- `AuditRepository.delete_before(cutoff)`：按 `event_time < cutoff` 删除，返回影响行数。
- `AuditService.cleanup_expired()`：
  - 读取 `get_effective_settings().audit.retention_days`。
  - 计算 cutoff 并调用仓库删除。
  - 写入一条 `event_category='task'` 的审计事件，context 记录 `retention_days/cutoff/affected_count`。
  - 清理失败只记录日志和审计失败事件，不影响主业务启动。
- 触发方式：
  - CLI：`python -m backend.cli audit-cleanup`，用于人工/部署校验。
  - 应用启动后台调度：在 `backend/scheduler/scheduler.py` 的现有 APScheduler 单例中注册平台级每日审计清理 job，由 `backend/main.py` 既有 startup/shutdown 管理；不另起线程池或新调度器。
  - 默认低峰执行时间可先固定在 `03:30`；如果后续要可配置执行时间，需另补配置闭环。
- 保留期配置继续以系统设置的 `audit.retention_days` 为唯一来源。

### 4.4 R24 字段级变更对比设计

- `audit_log` 新增 `changes JSONB NOT NULL DEFAULT '[]'::jsonb`。
- `AuditService.record_*` 系列方法新增 `changes` 参数，统一经过脱敏和白名单过滤。
- 变更结构：

```json
[
  {"field": "status", "before": "active", "after": "disabled"},
  {"field": "visibility", "before": "private", "after": "tenant"}
]
```

- 采集优先级：
  - 系统设置变更：记录配置 key 的 before/after，敏感配置只记录“已变更”。
  - 用户/租户状态变更、角色分配、菜单/资源授权变更。
  - 数据字典类型/字典项启停、标签、排序变更。
  - R28 资产公开状态变更。
- 前端 `AuditLogView.vue`：
  - 按原型在详情抽屉“错误摘要”前新增“字段变更” section。
  - 无 changes 时显示“无字段级变更”。
  - 宽值用 `overflow-wrap:anywhere`，抽屉内滚，不扩大页面主体布局。

### 4.5 通用资产可见性设计

- 新增内部工具建议：`backend/services/asset_visibility.py` 或 `backend/storage/visibility.py`。
- 通用能力：
  - `make_ref(asset_type, tenant_id, owner_user_id, asset_id)`。
  - `parse_ref(ref, expected_type)`。
  - `visibility_source(row, viewer_tenant, viewer_user)` 返回 `mine | tenant | public`。
  - `readonly(row, viewer_user)`。
- 各资产仓库保留领域命名：
  - 筛选方案返回 `profile_ref`，ref 内部 asset_type=`screen_profile`。
  - 买卖方案返回 `profile_ref`，ref 内部 asset_type=`trade_profile`。
  - 回测记录返回 `run_ref`，ref 内部 asset_type=`backtest_run`。
- 旧 id 兼容：
  - 未带 ref 前缀的旧 id 仅按当前 owner 查询。
  - 新前端列表和运行参数优先传 opaque ref。

### 4.6 筛选方案公开设计

- DDL：`screen_profile` 增加 `visibility/published_at/published_by`、合法值约束和 `(visibility, tenant_id, owner_user_id)` 索引。
- `ProfileRepo` 增加：
  - `list_visible()`、`get_visible(ref_or_id)`、`versions_visible(ref_or_id)`。
  - `set_visibility(ref_or_id, visibility, published_by)`。
  - `copy_visible(ref_or_id, new_id, new_name)`。
- `/api/profiles`：
  - 列表改为 visible list，返回 `profile_ref/source/readonly/visibility/owner_label`。
  - 详情和版本支持 ref。
  - 保存/删除保持 owner-only。
  - 新增 `/profiles/{ref}/visibility` 和 `/profiles/{ref}/copy`。
- `/api/screen/run`：
  - `profile_id` 可接收当前 owner id 或 `profile_ref`。
  - 非 owner 公开方案运行时读取公开 AST；运行结果归执行者，不写 owner 资产。

### 4.7 买卖方案公开设计

- DDL：`trade_profile` 增加 `visibility/published_at/published_by`、合法值约束和索引。
- `TradeProfileRepo` 增加与筛选方案一致的 visible 方法。
- `/api/trade-profiles`：
  - 列表、详情、版本支持 visible。
  - 保存/删除 owner-only。
  - 新增 `/trade-profiles/{ref}/visibility` 和 `/trade-profiles/{ref}/copy`。
- 回测服务和回测引擎：
  - `trade_profile_id` 可接收当前 owner id 或 `trade_profile` ref。
  - 解析后读取方案真实 owner 的买卖树。
  - 回测记录仍写执行者 owner 槽。

### 4.8 回测记录公开设计

- DDL：`backtest_run` 增加 `visibility/published_at/published_by`、合法值约束和索引。
- 子表 `backtest_equity/backtest_trade/backtest_metrics` 不加 visibility；它们随 run owner 被可见读取。
- `BacktestService` 增加：
  - `list_runs_visible(kind, source=None)`：自己的 + 同租户公开 + 全体公开；`source` 支持前端“我的/租户公开/全体公开”筛选。
  - `get_run_visible(run_ref_or_id)`：解析 owner 后读取 run 和从表。
  - `set_run_visibility(run_ref_or_id, visibility)`：owner-only，且默认只允许 `done` 记录公开。
  - `delete_run()` 保持 owner-only。
- `/api/backtest/runs`：
  - 列表返回 visible runs，增加 `run_ref/source/readonly/visibility/owner_label`。
  - 详情支持 `run_ref`。
  - 删除 owner-only；非 owner 403。
  - 新增 `/runs/{run_ref}/visibility`。
- `BacktestView.vue`：
  - 历史回测下拉展示来源标签，并提供“我的 / 租户公开 / 全体公开”筛选。
  - 公开记录详情只读，删除按钮隐藏或禁用。
  - 提供“复用参数”动作，将 run.params 回填到当前表单，用户点击运行后生成自己的记录。

### 4.9 权限与审计闭环

- 新增资源码：
  - `screen-profile:publish-tenant`、`screen-profile:publish-public`。
  - `trade-profile:publish-tenant`、`trade-profile:publish-public`。
  - `backtest:publish-tenant`、`backtest:publish-public`。
- 默认授权：
  - `*-publish-tenant` 默认给 `tenant_admin` 和 `system`。
  - `*-publish-public` 默认仅给 `system`。
  - `normal/paid` 可由角色显式授权，授权变更与 `perm_ver` bump 同事务提交。
- 复制权限：
  - 筛选方案复制使用 `screen-profile:save`。
  - 买卖方案复制使用 `trade-profile:save`。
  - 回测记录不复制结果，复用参数重跑使用 `backtest:run`。
- 审计事件：
  - 发布、收回、复制、公开回测复用参数重跑均记录审计。
  - 公开状态变化写入 R24 `changes`，字段名统一为 `visibility`。

### 4.10 页面功能点表

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| access token 过期后静默续期 | R22 | 用户长时间停留后继续操作，不被第一次 401 直接踢回登录 | `client.ts` 响应拦截单飞 refresh，成功后重放原请求 | `client.ts`、`authToken.ts`、`auth.ts` | `/api/auth/refresh` | refresh 加载不做整页遮罩；失败沿用登录态失效处理 | T2 |
| 审计详情字段变更表 | R24 | 抽屉顺序为执行/资源信息 -> 字段变更 -> 错误摘要 -> 事件上下文 | `AuditLogView.vue` 详情抽屉新增字段变更 section | `AuditLogView.vue` | `GET /api/audit/logs/{id}` 返回 `changes` | loading 沿用详情加载；空态“无字段级变更”；长值换行 | T10 |
| 筛选方案公开状态展示 | R28-8 | 方案下拉/编辑区显示来源、公开范围、只读 | 列表返回 visible profiles，页面使用资产标签组件展示 | `ScreenView.vue`、`AssetVisibilityTag` | `GET /api/profiles` | 列表加载失败保留错误提示；无公开资产时仅显示我的方案或空态 | T6,T9 |
| 筛选方案发布/收回 | R28-8 | owner 可设置私有/租户公开/全体公开 | 发布下拉走权限码，接口 owner-only | `ScreenView.vue`、`AssetVisibilityActions` | `POST /api/profiles/{ref}/visibility` | 无 publish 权限不渲染对应命令；保存中禁用重复点击 | T6,T9 |
| 筛选公开方案只读与复制 | R28-8 | 非 owner 只读，可复制为我的 private | readonly 禁编辑，复制按钮使用 `screen-profile:save` | `ScreenView.vue` | `POST /api/profiles/{ref}/copy` | 复制失败展示接口错误；复制成功选中新副本 | T6,T9 |
| 买卖方案公开状态展示 | R28-9 | 买卖指标页与评分页保持同口径公开标签 | 买卖 tab 接入 visible list/detail/version | `ConfigView.vue`、`AssetVisibilityTag` | `GET /api/trade-profiles` | 加载/错误沿用配置页模式；无公开资产时显示当前空态 | T7,T9 |
| 买卖方案发布/复制/只读 | R28-9 | owner 发布，viewer 复制后编辑 | 发布下拉、readonly 禁编辑、复制按钮权限为 `trade-profile:save` | `ConfigView.vue`、`AssetVisibilityActions` | visibility/copy 接口 | 无权限隐藏；非 owner 保存/删除后端仍 403 | T7,T9 |
| 回测历史公开记录展示 | R28-10 | 历史回测可看到我的、租户公开、全体公开 | run 列表返回 `run_ref/source/readonly/visibility/owner_label` | `BacktestView.vue`、`AssetVisibilityTag` | `GET /api/backtest/runs` | loading/error 沿用历史列表；无公开记录显示“暂无公开回测记录” | T8,T9 |
| 回测历史来源筛选 | E2 | 用户可在我的/租户公开/全体公开之间筛选 | 列表筛选控件传 `source` 或前端按返回 source 过滤 | `BacktestView.vue` | `GET /api/backtest/runs?source=` | 筛选后为空显示对应空态，不影响运行表单 | T8,T9 |
| 回测记录发布/收回 | R28-10 | owner 可公开已完成记录，非 owner 只读 | 详情/历史工具区接入发布下拉 | `BacktestView.vue`、`AssetVisibilityActions` | `POST /api/backtest/runs/{run_ref}/visibility` | running/failed 禁止公开并提示；无权限隐藏 | T8,T9 |
| 公开回测复用参数重跑 | R28-10 | viewer 不复制结果，只把参数回填到表单再运行 | “复用参数”从 run params 回填，运行仍走当前用户 | `BacktestView.vue` | `GET /api/backtest/runs/{run_ref}`、`POST /api/backtest/run` | 回填失败提示；运行权限缺失时按钮隐藏或禁用 | T8,T9 |

### 4.11 组件资产闭环表

| 页面/区域 | 运行时复用组件 | 布局或配置组件种类 | 组件配置字段/页面注册 | 设计规范或组件清单更新 | 真实消费与验证 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 评分/筛选/买卖/回测公开状态标签 | 新增普通真实组件 `AssetVisibilityTag.vue` | 不涉及系统组件种类 | 不新增配置字段；不改 pageRegistry | 需要补 `DESIGN.md` 真实复用组件清单 | `ConfigView.vue` 评分页回迁、`ScreenView.vue`、`ConfigView.vue` 买卖 tab、`BacktestView.vue` 消费；前端测试和 build 验证 | T9,T11,T12 |
| 方案/回测发布与复制动作 | 新增普通真实组件 `AssetVisibilityActions.vue`，通过 props 控制权限、readonly、loading 和可用命令 | 不涉及系统组件种类 | 不新增配置字段；不改 pageRegistry | 需要补 `DESIGN.md` 真实复用组件清单 | 三类 R28 资产接入；评分页可在不改变契约前提下回迁；用权限态测试验证 | T9,T11,T12 |
| 审计详情字段变更 | 复用 Element Plus 表格/描述组件，不新增真实复用组件 | 不涉及 | 不新增配置字段；不改 pageRegistry | 不需要新增组件清单 | `AuditLogView.vue` 详情抽屉真实消费；长值与空态验证 | T10,T11 |
| 页面布局 | 复用既有页面布局和 `LayoutHost` 接入状态 | 不新增布局原型 | 不新增页面注册；既有页面继续使用原 pageKey | 不更新 page-registry，除非实现中实际新增页面或布局旋钮 | 三档视口验证无溢出；不新增 `vh` 硬编码 | T9,T10,T11 |

### 4.12 前端页面设计闭环

#### 页面定位

- 页面类型：既有高密度业务工作台/列表/系统日志页的局部增强。
- 用户主流程：选择资产 -> 查看来源和公开范围 -> owner 发布/收回，viewer 只读查看或复制/复用参数 -> 后端按权限和归属校验。
- 是否新页面：否。
- 是否改造已有页面：是，涉及 `ScreenView.vue`、`ConfigView.vue`、`BacktestView.vue`、`AuditLogView.vue`。

#### 布局选型

- 选用原型：沿用既有页面原型；`ScreenView`/`ConfigView`/`BacktestView` 属于 workbench，`AuditLogView` 属于 list + drawer。
- 选择理由：本阶段是现有资产操作点增强，不改变主流程和主区信息架构；新增整页原型会扩大范围。
- 是否需要新增布局原型：否。

#### Slot 与组件设计

| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| action | profile-toolbar/history-toolbar | toolbar/actions | 否 | 页面既有 action 区 | 否 | 增加发布、复制、来源筛选，不改变主按钮层级 |
| main | profile-editor/result-detail/history-list | form/table/detail | 维持既有设置 | 既有主区内部滚动 | 否 | readonly 禁编辑，公开标签不撑开主区 |
| overlay | audit-detail-drawer | drawer/detail-table | 否 | 抽屉内部滚动 | 否 | 字段变更表放在错误摘要前 |

#### 空状态设计

- 表格空态：继续使用全局 `el-table` 空态；不叠加额外 `el-empty`。
- 方案列表空态：无我的方案且无公开方案时显示现有页面空态；筛选到公开来源为空时显示“暂无公开筛选方案/买卖方案”。
- 回测历史空态：筛选为租户公开或全体公开且无记录时显示“暂无公开回测记录”。
- 审计字段变更空态：按原型显示“无字段级变更”。

#### 配置设计

| 类型 | 字段 | 层级 | 落点 | 说明 |
| --- | --- | --- | --- | --- |
| 布局旋钮 | 无新增 | - | - | 本阶段不新增布局设置 |
| 组件设置 | 无新增 | - | - | `AssetVisibilityTag/Actions` 是普通真实组件，不进入配置组件目录 |
| 页面记忆 | 回测历史来源筛选 | 页面业务态 | `BacktestView.vue` 当前会话或既有 page settings 能力 | 不新增后端配置字段；实现时若要持久化必须更新计划 |

#### 复用与新增判断

- 复用已有布局：复用四个既有页面布局和 Element Plus 组件。
- 复用已有组件：可复用按钮、下拉、标签和抽屉基础组件；不复用 `SourceTag.vue` 作为资产标签。
- 新增真实组件：新增 `AssetVisibilityTag.vue` 与 `AssetVisibilityActions.vue`。
- 真实组件是否进入 `DESIGN.md` 清单：是。
- 是否关联系统组件种类：否。
- 是否新增组件种类：否。
- 是否新增组件配置字段：否。
- 是否新增页面专属业务态：仅回测历史来源筛选；不引入持久化配置闭环。

#### 维护清单

- pageRegistry：不新增页面，不改 pageRegistry；若实现中新增页面或配置消费，必须补登记。
- COMPONENT_CATALOG：不涉及。
- COMPONENT_FIELD_DEFS：不涉及。
- componentSchemas：不涉及。
- 后端 layout_config 字段规则：不涉及。
- componentPreview：不涉及。
- DESIGN.md 真实复用组件清单：新增资产可见性标签和动作组件。
- DESIGN.md `page-registry` 区块：不更新，除非实际新增页面。
- RBAC 菜单/功能点：同步 `_SEED_RESOURCES`、`BUSINESS_RESOURCE_CODES`、默认授权、接口守卫、`v-permission` 和权限扫描测试。
- 测试：组件消费页测试、权限态测试、`npm run build`、三档视口验证。

#### 验收

- `cd frontend && npm test`：覆盖组件、页面和布局契约相关测试。
- `cd frontend && npm run build`：改动 `frontend/src` 后必须执行。
- 视口验证：`1100x620 / 1366x768 / 1440x900`。
- 检查公开标签、发布下拉、复制/复用按钮、审计抽屉字段变更表无文本溢出、无整页横向滚动、无新增视口高度硬编码。

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R22 | token 静默刷新 | 前端单飞 refresh + 重放原请求 + 失败回登录 | T2 | 已完成 | 一致 | 已补前端 client 静默刷新和专项测试 |
| 必须实现 | R23 | 审计日志保留期自动清理 | 清理服务、CLI、复用 APScheduler 调度、测试和审计事件 | T3 | 待开始 | 一致 | 复用阶段五 `audit.retention_days` 与现有 scheduler |
| 必须实现 | R24 | 字段级 from/to | `audit_log.changes`、采集 helper、审计页展示 | T4,T10 | 待开始 | 一致 | 原型已先更新 |
| 必须实现 | R28-8 | 筛选方案公开 | `screen_profile` visible + API + ScreenView 接入 | T5,T6,T9,T11 | 待开始 | 一致 | 方案类资产复制为 private |
| 必须实现 | R28-9 | 买卖方案公开 | `trade_profile` visible + API + ConfigView trade 接入 | T5,T7,T9,T11 | 待开始 | 一致 | 回测引用公开买卖方案时结果归 viewer |
| 必须实现 | R28-10 | 回测记录公开 | `backtest_run` visible + API + BacktestView 接入 | T5,T8,T9,T11 | 待开始 | 一致 | 结果资产只读，可复用参数重跑 |
| 必须实现 | R20/R21 延续 | 权限/按钮/接口闭环 | 新资源码、默认授权、扫描和页面权限测试 | T1,T11,T12 | 进行中 | 一致 | T1 已完成 DDL/资源码/默认授权规划与测试，T11/T12 待后续阶段收口 |
| 可选增强 | E1 | 公开资产来源/只读/范围标签统一 | 新增 `AssetVisibilityTag` 并接入三类 R28 资产和评分页回迁 | T9,T11,T12 | 待开始 | 一致 | 由原计划可选提升为必做 UI 资产闭环 |
| 可选增强 | E2 | 回测历史来源筛选 | 回测历史增加“我的 / 租户公开 / 全体公开”筛选 | T8,T9,T11 | 待开始 | 一致 | 不新增公开广场，仅在历史区域内筛选 |
| 可选增强 | E3 | 审计摘要展示清理任务最近执行结果 | 暂不纳入本次 | - | 跳过 | 未覆盖 | 会改变审计页摘要信息架构，后续如需要先补原型 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：阶段六范围校准与 SQL/资源码规划

- 状态：已完成
- 依赖：无
- 涉及文件/模块：
  - `backend/storage/pg_ddl.py`
  - `backend/auth/constants.py`
  - `agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/stage6-experience-asset-visibility.sql`
  - `agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/resource-codes.sql`
  - [../requirement.md](../requirement.md)
- 目标：落定阶段六 DDL、资源码、菜单授权和人读 SQL 留痕。
- 操作：
  - 为 `screen_profile/trade_profile/backtest_run/audit_log` 设计增量字段、约束和索引。
  - 新增 publish 权限码：`screen-profile:publish-tenant/public`、`trade-profile:publish-tenant/public`、`backtest:publish-tenant/public`。
  - 默认授权：tenant publish 默认给 tenant_admin/system；public publish 默认 system；normal/paid 需角色显式授权。
  - 写 SQL 留痕，说明执行时机、影响范围和回滚方式。
- 产出：DDL/seed 修改方案、SQL 留痕文件、需求验收 R28 行和权限码清单。
- 影响范围：PG 表结构、资源 seed、角色默认授权、权限缓存版本。
- 边界与异常：新增字段必须默认 `private` 兼容历史数据；资源码回滚必须同步 bump 受影响用户 `perm_ver`。
- 验证方式：资源码扫描测试覆盖新增接口；SQL diff 与 `pg_ddl.py` 保持一致；历史数据默认私有。
- 完成标准：DDL/seed 计划和 §5 映射无遗漏，新增资源码不 fail-open。
- 实际落地情况：已完成；`backend/storage/pg_ddl.py` 已补 `audit_log.changes`、`screen_profile/trade_profile/backtest_run.visibility/published_at/published_by`、合法值约束和可见性索引，并新增既有库幂等升级函数 `_upgrade_stage6_asset_visibility()`；`backend/auth/constants.py` 已新增阶段六 tenant/public publish 权限常量且未放入默认业务授权集合；`_SEED_RESOURCES` 已新增 6 个 publish 资源码，`seed_stage6_asset_visibility()` 用 `migration.stage6_asset_visibility_v1` 标记一次性回填 tenant_admin 的租户公开权限并清理 normal/paid 与 tenant_admin 的 public publish 误授权；已生成 SQL 留痕 `stage6-experience-asset-visibility.sql` 和 `resource-codes.sql`；`backend/tests/test_rbac_schema.py` 已补 T1 专项断言。验证：`python -m py_compile backend/auth/constants.py backend/storage/pg_ddl.py backend/tests/test_rbac_schema.py` 通过；`git diff --check` 通过；T1 相关 pytest `test_stage6_asset_visibility_schema_and_resources`、`test_stage6_asset_publish_grants_backfilled_for_tenant_admin`、`test_tenant_admin_has_tenant_publish_by_default`、`test_normal_role_business_only` 共 4 项通过。完整 `backend/tests/test_rbac_schema.py -q` 当前 12 passed、2 failed，失败点为本地既有库旧菜单 `menu_strategy_analysis` parent 残留与 system 旧菜单授权缺口，不属于本次 T1 新增 DDL/资源码断言。

### 6.2 任务 T2：R22 token 静默刷新

- 状态：已完成
- 依赖：T1
- 涉及文件/模块：
  - `frontend/src/api/client.ts`
  - `frontend/src/api/authToken.ts`
  - `frontend/src/api/auth.ts`
  - `frontend/src/stores/auth.ts`
  - 前端 auth/client 测试
- 目标：access token 过期时自动 refresh 并重放原请求。
- 操作：
  - `authToken.ts` 增加 refresh token 读取和 token 更新方法。
  - `client.ts` 增加 401 refresh 单飞队列和 `_retry` 标记。
  - 排除登录、注册、refresh、登录页自身 401。
  - refresh 成功后重放原请求；失败后按现有逻辑清态跳登录。
- 产出：静默刷新拦截器、token 更新工具、并发 401 前端测试。
- 影响范围：所有通过 `client.ts` 发出的受控 API 请求。
- 边界与异常：refresh 请求不能递归进入自身；写请求只重放一次；refresh token 失效、账号禁用、租户禁用或 `perm_ver` 失配都必须清态。
- 验证方式：mock 两个并发 401 只触发一次 refresh；refresh 成功重放请求；refresh 失败跳登录。
- 完成标准：不会重复弹“会话失效”，不会 refresh 递归。
- 实际落地情况：已完成；`frontend/src/api/authToken.ts` 已新增 `getRefreshToken()` 和 `updateTokens()`；`frontend/src/api/client.ts` 已实现 401 静默 refresh 单飞、`_retry` 重放保护、登录/注册/refresh 排除、低层 `fetch('/api/auth/refresh')` 避免 axios 拦截器递归、刷新失败清态跳登录；新增 `frontend/src/api/__tests__/client-refresh.spec.ts` 覆盖并发两个 401 只触发一次 refresh、刷新成功后用新 access token 重放原请求、刷新失败清理本地 auth。验证：`cd frontend && npm run test -- src/api/__tests__/client-refresh.spec.ts` 通过（2 tests）；`cd frontend && npm run build` 通过；`git diff --check` 通过。

### 6.3 任务 T3：R23 审计自动清理

- 状态：待开始
- 依赖：T1
- 涉及文件/模块：
  - `backend/storage/audit_repository.py`
  - `backend/services/audit_service.py`
  - `backend/cli.py`
  - `backend/scheduler/scheduler.py`
  - `backend/main.py`
  - `backend/tests/test_stage6_audit_cleanup.py`
- 目标：自动清理超保留期审计日志，避免 `audit_log` 无限增长。
- 操作：
  - 仓库层新增按 cutoff 删除。
  - 服务层读取 `audit.retention_days` 并记录清理审计事件。
  - CLI 提供人工执行入口。
  - 在现有 APScheduler 单例注册每日低峰平台级清理 job，失败只告警不阻断主业务。
- 产出：清理服务、CLI 命令、scheduler 注册逻辑、后端测试。
- 影响范围：`audit_log` 历史数据、调度启动流程、审计事件。
- 边界与异常：删除不可逆；保留期小于等于 0 或配置异常时必须 fail-safe 不清理；调度失败不影响应用启动。
- 验证方式：插入窗口内/外记录，执行清理后仅窗口外被删；重复执行幂等；scheduler 注册不创建第二个 APScheduler。
- 完成标准：清理任务幂等，重复执行不会误删保留期内记录。
- 实际落地情况：待实施。

### 6.4 任务 T4：R24 审计字段变更模型

- 状态：待开始
- 依赖：T1
- 涉及文件/模块：
  - `backend/storage/pg_ddl.py`
  - `backend/storage/audit_repository.py`
  - `backend/services/audit_service.py`
  - `backend/tests/test_stage6_audit_changes.py`
- 目标：审计详情具备结构化字段变更数据。
- 操作：
  - `audit_log` 增 `changes JSONB`。
  - `AuditRepository.insert/list/detail` 支持 changes。
  - `AuditService` 增 diff 构造和脱敏方法。
  - 先接入系统设置、字典、RBAC 和 R28 公开状态变更。
- 产出：`changes` 字段、审计 diff helper、字段脱敏规则、后端测试。
- 影响范围：审计写入、查询返回结构、R24 前端详情展示。
- 边界与异常：敏感字段不泄漏明文；无 changes 时返回空数组；旧记录兼容默认 `[]`。
- 验证方式：系统设置/RBAC/公开状态变更写入 before/after；敏感 key 只显示“已变更”；旧记录详情返回空数组。
- 完成标准：详情接口返回 `changes: [] | [{field,before,after}]`，敏感字段不泄漏明文。
- 实际落地情况：待实施。

### 6.5 任务 T5：通用资产可见性 helper

- 状态：待开始
- 依赖：T1
- 涉及文件/模块：
  - `backend/services/asset_visibility.py` 或 `backend/storage/visibility.py`
  - `backend/tests/test_stage6_asset_visibility.py`
- 目标：抽出 asset ref、source、readonly 和可见性判断公共逻辑。
- 操作：
  - 实现 ref 编解码和类型校验。
  - 实现 visible 判断 helper，供三个仓库复用。
  - 明确旧 id 兼容：只查当前 owner。
- 产出：通用 helper、三类资产共享的 ref/source/readonly 规则、单元测试。
- 影响范围：筛选方案、买卖方案、回测记录的 visible 读模型。
- 边界与异常：asset_type 不匹配必须拒绝；ref 解析后必须二次可见性校验；旧 id 不跨 owner 查找。
- 验证方式：ref 类型错配、跨租户 tenant 不可见、public 可见、owner readonly=false、非 owner readonly=true。
- 完成标准：screen/trade/backtest 三类资产不复制三套不一致 ref 逻辑。
- 实际落地情况：待实施。

### 6.6 任务 T6：筛选方案公开能力

- 状态：待开始
- 依赖：T1,T5
- 涉及文件/模块：
  - `backend/screening/profile.py`
  - `backend/api/profiles.py`
  - `backend/services/screen_score.py`
  - `frontend/src/api/screening.ts`
  - `frontend/src/views/ScreenView.vue`
  - `backend/tests/test_stage6_screen_profile_visibility.py`
- 目标：筛选方案支持公开、只读和复制。
- 操作：
  - DDL/仓库/API 接入 visible 方法。
  - `screen/run` 支持可见 ref，非 owner 公开方案运行不写 owner 资产。
  - 筛选页方案下拉显示来源标签；公开方案只读，提供复制为我的方案。
  - owner 可设置私有/租户公开/全体公开。
- 产出：筛选方案 visible API、publish/copy 接口、运行时 ref 解析、页面接入点。
- 影响范围：策略筛选页、`/api/profiles`、`/api/screen/run`、筛选方案表。
- 边界与异常：非 owner 保存/删除/发布 403；复制用 `screen-profile:save`；公开方案运行结果不得污染 owner。
- 验证方式：跨租户 tenant 不可见，public 可见，非 owner 保存/删除 403；复制后新方案为 private 且 owner 为 viewer。
- 完成标准：用户可查看公开筛选方案、复制为自己的 private、非 owner 不可改删。
- 实际落地情况：待实施。

### 6.7 任务 T7：买卖方案公开能力

- 状态：待开始
- 依赖：T1,T5
- 涉及文件/模块：
  - `backend/signals/trade_profile.py`
  - `backend/api/trade_profiles.py`
  - `backend/backtest/engine.py`
  - `backend/services/backtest_service.py`
  - `frontend/src/api/tradeProfile.ts`
  - `frontend/src/views/ConfigView.vue`
  - `backend/tests/test_stage6_trade_profile_visibility.py`
- 目标：买卖方案支持公开、只读、复制，并可被回测引用。
- 操作：
  - DDL/仓库/API 接入 visible 方法。
  - `BacktestEngine` 和 `BacktestService` 解析可见 `trade_profile_id`。
  - 买卖指标页按评分页模式补 visibility tag、发布下拉、只读禁编辑和复制。
- 产出：买卖方案 visible API、publish/copy 接口、回测引用解析、页面接入点。
- 影响范围：买卖指标配置页、回测运行、`/api/trade-profiles`、买卖方案表。
- 边界与异常：非 owner 保存/删除/发布 403；复制用 `trade-profile:save`；回测结果写当前用户。
- 验证方式：用户可在回测中选择同租户/全体公开买卖方案；跨租户 tenant 不可见；复制后可编辑副本。
- 完成标准：用户可查看公开买卖方案、复制为自己的 private、非 owner 不可改删。
- 实际落地情况：待实施。

### 6.8 任务 T8：回测记录公开能力

- 状态：待开始
- 依赖：T1,T5,T6,T7
- 涉及文件/模块：
  - `backend/services/backtest_service.py`
  - `backend/api/backtest.py`
  - `frontend/src/api/backtest.ts`
  - `frontend/src/views/BacktestView.vue`
  - `backend/tests/test_stage6_backtest_visibility.py`
- 目标：回测历史支持公开查看、来源筛选和参数复用。
- 操作：
  - `backtest_run` 接入 visible 字段。
  - 列表和详情支持 visible run；从表读取使用 run 的真实 owner。
  - 新增公开/收回接口，owner-only。
  - 删除保持 owner-only。
  - 前端历史回测下拉展示来源；只读公开记录隐藏删除；增加来源筛选和“复用参数”。
- 产出：回测记录 visible API、publish 接口、run_ref、来源筛选、复用参数前端动作。
- 影响范围：回测历史列表、回测详情、回测从表读取、回测权限。
- 边界与异常：默认仅允许 `done` 记录公开；viewer 不能删除或覆盖 owner 记录；从表查询必须带 run 真实归属。
- 验证方式：viewer 能查看公开回测详情但不能删除；source 筛选空态正确；复用参数后运行生成 viewer 自己的记录。
- 完成标准：同租户/全体公开回测可读，删除和覆盖仍限 owner。
- 实际落地情况：待实施。

### 6.9 任务 T9：前端公开资产 UI 统一

- 状态：待开始
- 依赖：T6,T7,T8
- 涉及文件/模块：
  - `frontend/src/components/AssetVisibilityTag.vue`
  - `frontend/src/components/AssetVisibilityActions.vue`
  - `frontend/src/views/ScreenView.vue`
  - `frontend/src/views/ConfigView.vue`
  - `frontend/src/views/BacktestView.vue`
  - `frontend/src/api/*`
- 目标：三个页面公开状态展示一致，按钮不溢出，权限态明确。
- 操作：
  - 新增 `AssetVisibilityTag` 展示 source/visibility/owner_label/readonly。
  - 新增 `AssetVisibilityActions` 统一发布、收回、复制/复用入口的权限态和 loading 态。
  - 将评分页内联 visibility tag 回迁到组件，作为真实样板回归。
  - 公开下拉和复制按钮都走 `v-permission`；筛选复制为 `screen-profile:save`，买卖复制为 `trade-profile:save`，回测复用为 `backtest:run`。
  - 保持现有页面布局，不新增整页说明文字。
- 产出：两个前端真实复用组件、四个页面消费点、权限态和空态实现。
- 影响范围：评分规则、筛选方案、买卖指标、策略回测页面。
- 边界与异常：组件不进入系统组件种类；无公开资产空态不能叠加表格空态；长 owner_label 不撑破按钮或列表。
- 验证方式：组件测试或页面测试覆盖 mine/tenant/public/readonly；三档视口无按钮文本溢出，无整页横向滚动。
- 完成标准：三类 R28 资产和评分页公开 UI 口径一致。
- 实际落地情况：待实施。

### 6.10 任务 T10：审计页字段变更展示

- 状态：待开始
- 依赖：T4
- 涉及文件/模块：
  - `frontend/src/api/audit.ts`
  - `frontend/src/views/system/AuditLogView.vue`
  - `frontend/src/views/system/__tests__/AuditLogView.spec.ts`
- 目标：正式页面承接已更新原型的字段变更表。
- 操作：
  - API 类型增加 `changes`。
  - 详情抽屉新增字段变更 section。
  - 无 changes 显示“无字段级变更”。
- 产出：审计详情 changes 类型、抽屉字段变更区域、前端测试。
- 影响范围：系统日志审计页详情抽屉。
- 边界与异常：字段值长文本必须换行；空数组显示空态；不改变列表筛选和主表布局。
- 验证方式：有 changes/无 changes 两类详情渲染；长值不撑破抽屉；顺序匹配原型。
- 完成标准：详情抽屉信息区顺序与原型一致，长值不撑破抽屉。
- 实际落地情况：待实施。

### 6.11 任务 T11：测试、构建与页面验证

- 状态：待开始
- 依赖：T2-T10
- 涉及文件/模块：
  - `backend/tests/`
  - `frontend/src/**/__tests__/`
  - `frontend/dist`
- 目标：证明阶段六能力不破坏已有权限、隔离和公开评分方案链路。
- 操作：
  - 后端覆盖静默刷新相关接口、审计清理、审计 changes、三类资产 visible API、回测可见详情。
  - 前端覆盖 client refresh、AuditLogView changes、ScreenView/ConfigView/BacktestView 公开态。
  - 修改 `frontend/src` 后运行 `npm run build`。
  - 使用 5181 专用端口做三档视口抽样，重点看公开标签、下拉、详情抽屉和回测历史区域。
- 产出：后端/前端专项测试、build 结果、页面视口验证记录。
- 影响范围：阶段六全量改动和阶段四/五回归链路。
- 边界与异常：涉及 DuckDB 的后端测试前按 AGENTS 要求检查并停止后端服务，测试后按原状态恢复；未执行的验证必须在计划中写原因。
- 验证方式：专项 pytest、Vitest、`npm run build`、5181 三档视口验证。
- 完成标准：专项测试通过，build 通过，页面无明显布局溢出。
- 实际落地情况：待实施。

### 6.12 任务 T12：文档治理和阶段收尾

- 状态：待开始
- 依赖：T11
- 涉及文件/模块：
  - `CLAUDE.md`
  - `README.md`（如公开资产能力需对外说明）
  - [../requirement.md](../requirement.md)
  - 本计划
  - [../../../DESIGN.md](../../../DESIGN.md)
- 目标：阶段六事实源回写，避免后续按旧 R28 待定状态开发。
- 操作：
  - 回写 requirement 阶段六状态、R28 覆盖范围和未覆盖范围。
  - 登记 `AssetVisibilityTag/Actions` 到 DESIGN 真实复用组件清单。
  - 更新计划实际落地情况和验证结果。
- 产出：需求状态回写、设计组件清单更新、计划进度和验证结果更新。
- 影响范围：AI 协作事实源、设计规范、阶段六交付记录。
- 边界与异常：只沉淀真实落地事实，不提前把未实现项写成已完成；如未更新 README 需说明原因。
- 验证方式：`rg` 检查 R28 待定旧口径是否残留；DESIGN 组件清单存在真实消费页面；计划 §5/§6 状态一致。
- 完成标准：需求、计划、代码事实和测试基线一致。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划

- SQL 文件路径：
  - `agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/stage6-experience-asset-visibility.sql`
  - `agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/resource-codes.sql`
- 用途：
  - `stage6-experience-asset-visibility.sql`：记录 `audit_log`、`screen_profile`、`trade_profile`、`backtest_run` 的字段、约束、索引和历史数据默认值。
  - `resource-codes.sql`：记录新增 publish 权限码、默认授权、`perm_ver` bump 和回滚语句。
- 执行时机：
  - 开发库由 `init_pg_db()` 幂等迁移或手动执行 SQL 留痕校验。
  - 发布前备份相关表，再执行迁移或启动后端触发幂等 DDL。
- 影响范围：
  - `audit_log`：新增 `changes JSONB NOT NULL DEFAULT '[]'::jsonb`。
  - `screen_profile`：新增 `visibility/published_at/published_by`、合法值约束、可见性索引。
  - `trade_profile`：新增 `visibility/published_at/published_by`、合法值约束、可见性索引。
  - `backtest_run`：新增 `visibility/published_at/published_by`、合法值约束、可见性索引。
- 历史数据默认值：
  - 历史 screen/trade/backtest 资产默认 `private`。
  - 内置 screen/trade preset 默认保持 `private`，除非后续明确要平台预设全员共享；本阶段先不扩大。
- 回滚方式或不可回滚原因：
  - 新增字段可保留不用。
  - 若需撤回公开状态，可统一 `UPDATE ... SET visibility='private', published_at=NULL, published_by=NULL`。
  - 资源码和授权回滚需同步 bump 受影响用户 `perm_ver`。
  - 审计清理删除的数据不可由代码回滚恢复，发布前必须备份 `audit_log`。

## 8. 测试与验证计划

- 单元测试：
  - 计划：asset ref 编解码、source/readonly 判断、visibility 合法值校验；AuditService changes 脱敏和清理 cutoff。
  - 具体完成情况：待验证。
- 接口测试：
  - 计划：screen/trade/backtest visible list/detail/versions/publish/copy/delete；refresh 单飞和失败回登录。
  - 具体完成情况：R22 前端请求层已验证 refresh 单飞、成功重放和失败清态：`cd frontend && npm run test -- src/api/__tests__/client-refresh.spec.ts` 通过（2 tests）。screen/trade/backtest visible 接口待 T6/T7/T8/T11 实现后验证。
- 页面/交互测试：
  - 计划：AuditLogView 字段变更；ScreenView 公开筛选方案只读/复制/发布；ConfigView trade 公开买卖方案只读/复制/发布；BacktestView 公开历史只读、来源筛选、删除隐藏、复用参数。
  - 具体完成情况：待验证。
- 组件资产闭环测试：
  - 计划：验证 `AssetVisibilityTag/Actions` 真实消费、新增组件清单维护、评分页回迁、三类 R28 页面接入；本阶段不新增配置组件种类或字段。
  - 具体完成情况：待验证。
- 权限与数据范围测试：
  - 计划：publish-tenant 默认 tenant_admin/system；publish-public 默认 system；无角色用户 fail-closed；跨租户 tenant 不可见，public 可见，private 不可见；非 owner 保存、删除、发布均 403。
  - 具体完成情况：T1 已验证资源码和默认授权规划：`python -m pytest backend/tests/test_rbac_schema.py::test_stage6_asset_visibility_schema_and_resources backend/tests/test_rbac_schema.py::test_stage6_asset_publish_grants_backfilled_for_tenant_admin backend/tests/test_rbac_schema.py::test_tenant_admin_has_tenant_publish_by_default backend/tests/test_rbac_schema.py::test_normal_role_business_only -q` 通过（4 passed）。接口级 owner/非 owner 保存、删除、发布 403 待 T6/T7/T8/T11 实现后验证。
- 回归测试：
  - 计划：阶段四评分方案公开能力专项；阶段五审计/字典/系统设置专项；全量前端 build。
  - 具体完成情况：待验证。
- 异常与边界测试：
  - 计划：refresh 递归保护、重复写请求只重放一次、审计保留期非法值 fail-safe、running/failed 回测禁止公开、回测从表按 run 真实 owner 读取。
  - 具体完成情况：R22 已覆盖 refresh 请求不走 `http` 拦截器、401 原请求只设置一次 `_retry`、并发 refresh 单飞；其余审计/回测边界待 T3/T8/T11 验证。
- 图示与原型一致性验证：
  - 计划：`AuditLogView` 实现必须匹配 `prototypes/audit-log.html` 的详情抽屉顺序、字段变更空态、列头和长值换行；其他页面为既有页面局部增强，不新增原型。
  - 具体完成情况：待验证。
- 配置闭环验证：
  - 计划：本阶段不新增系统配置；R23 只消费既有 `audit.retention_days`；若新增配置项必须补“谁定义、谁渲染、谁保存、谁读取、谁消费、谁校验、如何回退”。
  - 具体完成情况：待验证。
- 需求映射验证：
  - 计划：检查 §3.1、§3.2、§5、§6 任务编号一致，状态值仅使用 `待开始/进行中/已完成/阻塞/跳过`。
  - 具体完成情况：T1/T2 已回写 §5 和 §6：R22 行标为已完成，R20/R21 延续行标为进行中，T1/T2 标为已完成；T3-T12 仍保持待开始，未连续开发后续任务。
- 页面功能点验证：
  - 计划：验证 §4.10 每个页面功能点都有技术实现、任务编号、交互状态和异常处理验证。
  - 具体完成情况：待验证。
- 页面视口验证：
  - 计划：5181 预览端口，视口 `1100x620 / 1366x768 / 1440x900`，检查标签、下拉、抽屉、历史回测区域不溢出。
  - 具体完成情况：待验证。

## 9. 发布与回滚

- 发布前检查：
  - 备份 PG 中 `audit_log`、三类资产表、RBAC 资源/授权表和 `sys_user`。
  - 执行 SQL 或确认 `init_pg_db()` 幂等迁移与 SQL 留痕一致。
  - 跑阶段六专项、阶段四 R28 评分方案专项、阶段五审计专项和前端 build。
  - 确认 `backend/scheduler/scheduler.py` 只使用现有 APScheduler 单例，未新增并行调度器。
- 发布步骤：
  - 停后端释放 DuckDB 锁：`./start.sh stop`。
  - 执行迁移或启动后端触发幂等 DDL。
  - 启动后端并确认 `/api/health=200`。
  - 构建并部署前端。
  - 用 system、tenant_admin、normal 三类账号抽样验证。
- 配置或环境变量：
  - 不新增环境变量。
  - R23 继续消费系统设置 `audit.retention_days`；每日执行时间先固定在代码中的低峰时间。
- 回滚方案：
  - 回滚代码。
  - 新增字段保留无害；如需强制私有化，批量把新增 `visibility` 字段置回 `private`。
  - 删除或恢复新增资源码授权后 bump 相关用户 `perm_ver`。
  - 审计清理不可恢复已删除历史，发布前必须备份 `audit_log`。

## 10. 风险、假设与待确认项

### 10.1 风险

- 公开方案 ref 解析若缺少二次可见性校验，会造成跨租户越权。
- 回测公开结果读取需按 run 真实 owner 读从表，JOIN 条件遗漏会串数据。
- 前端静默刷新如果队列处理不当，可能形成 refresh 递归或重复重放写请求。
- 审计清理是不可逆删除，必须明确备份和保留期配置；非法保留期必须 fail-safe。
- 公开筛选方案运行时不能把结果写入方案 owner 槽，否则 viewer 会污染 owner 资产。
- 前端公开资产 UI 若不抽组件，三页标签、发布下拉、readonly 文案会快速漂移；因此 T9 将组件化列为必做。
- R28 原需求验收表此前无单独行，已在本次计划整改中补齐；后续开发若扩大到 `stock_group/training` 将超出阶段六范围。

### 10.2 假设

- `private/tenant/public` 三档继续满足阶段六公开需求，不引入更细粒度共享名单。
- 回测记录公开仅对已完成记录有意义；本阶段只允许 `done` 记录公开。
- 内置筛选/买卖 preset 本阶段不默认 public，避免突然扩大普通用户可见资产。
- R23 调度执行时间固定低峰即可满足阶段六；不新增可配置执行时间。
- 公开资产标签和动作组件是普通真实组件，不需要进入布局配置系统。

### 10.3 待确认项

| 项 | 推荐口径 | 影响 |
| --- | --- | --- |
| 内置筛选/买卖 preset 是否默认 public | 暂不默认 public，只保留 owner seed；后续如需全员预设再单独确认 | 避免阶段六扩大业务语义 |
| 回测记录是否允许 failed/running 公开 | 仅允许 `done` 公开 | 避免公开半成品或错误详情 |
| 筛选公开方案运行结果是否落库 | 非 owner 运行结果归 viewer 或不落库，不能写 owner；推荐先不落库或写 viewer 归属 | 避免污染公开方案 owner 资产 |
| R28 是否继续扩展 stock_group/training | 本阶段不做 | 避免无限扩大公开资产范围 |
