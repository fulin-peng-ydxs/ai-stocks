# 开发计划

## 1. 需求来源与目标

- 需求文档：[../requirement.md](../requirement.md)。
- 上游实现依据：
  - 阶段四 B 已完成评分方案公开能力：[../stage4-public-profile-visibility/plan.md](../stage4-public-profile-visibility/plan.md)。
  - 阶段五已完成审计、字典和系统设置承载：[../stage5-platform-capabilities/plan.md](../stage5-platform-capabilities/plan.md)。
  - 阶段六前已更新日志审计原型：[../prototypes/audit-log.html](../prototypes/audit-log.html)，详情抽屉新增 R24 字段变更表。
- 功能目标：进入第六阶段，补齐体验增强项，并把原先独立排期的 R28 其他资产公开能力纳入本阶段。
- 当前计划状态：待开发。
- 本阶段纳入：
  - R22：token 静默刷新，避免长操作中 access token 过期直接打断。
  - R23：审计日志保留期自动清理任务，复用 `audit.retention_days`。
  - R24：操作审计字段级 from/to 变更对比。
  - R28：评分方案之外的其他资产公开能力，优先覆盖筛选方案、买卖方案和回测记录。
- 本阶段不做：
  - 不做公开市场、审批流、收藏、搜索广场、运营推荐或计费联动。
  - 不扩展自选股分组、盘感训练记录、布局配置、系统配置、字典或数据任务为公开资产。
  - 不允许非 owner 修改、删除、覆盖或强制刷新他人公开资产。
  - 不改变行情 DuckDB 只读分析和用户资产 PG 读写的双库边界。
  - 不新增独立大页面；优先在现有策略筛选、买卖指标、策略回测和日志审计页面内完成。
- 计划输出目录：`agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/`。

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
- `ConfigView.vue` 评分规则页已实现 `readonly/source/visibility` 展示、发布下拉和“复制为我的方案”。

### 2.2 R22 当前依据

- 后端已有 `/api/auth/refresh`，`AuthService.refresh()` 会校验 refresh token、账号状态、租户状态和 `perm_ver`，并轮换 refresh token。
- 前端已有 `authToken.ts` 作为 localStorage 事实源，`client.ts` 请求拦截从 localStorage 读 access token。
- 当前 `client.ts` 遇到 401 直接清态跳登录，未尝试静默刷新；这会打断长时间停留后的查询、保存、回测和页面设置操作。

### 2.3 R23 当前依据

- 阶段五已新增 `audit.retention_days`，系统设置可配，`AuditService` 已把它用于默认查询窗口和页面提示。
- `audit_log` 已有按 `event_time`、租户、分类、资源码、结果的索引。
- 当前缺口是自动删除超保留期审计记录；阶段五明确未实现 R23。

### 2.4 R24 当前依据

- 当前 `audit_log.context` 只保存脱敏上下文；`AuditService._sanitize_context()` 有白名单与敏感 key 过滤。
- 审计页详情抽屉当前展示执行信息、资源信息、错误摘要和事件上下文。
- 原型已更新为在详情抽屉展示“字段变更”表，列为字段、变更前、变更后。

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

## 3. 实施范围

### 3.1 必须实现

| 需求编号 | 需求内容 | 本阶段开发内容 | 对应任务 | 完成标志 |
| --- | --- | --- | --- | --- |
| R22 | token 静默刷新 | 前端 401 后用 refresh token 单飞刷新、重放原请求、轮换本地 token；刷新失败再跳登录 | T2 | 长时间停留后首次受控请求可自动恢复，不重复弹错 |
| R23 | 审计保留期自动清理 | 新增审计清理服务、CLI/启动调度入口、审计事件记录和测试 | T3 | 超过 `audit.retention_days` 的审计日志可按计划清理 |
| R24 | 字段级变更对比 | `audit_log` 增结构化 `changes`，服务层脱敏、采集关键变更，审计页详情展示 from/to | T4,T10 | 配置、RBAC、字典、公开状态等关键变更可在详情里看到字段差异 |
| R28-8 | 筛选方案公开能力 | `screen_profile` 增 visible 模型，API 支持可见列表/详情/版本/发布/复制，筛选页只读和复制 | T5,T8,T10 | 用户可查看公开筛选方案、复制为自己的 private、非 owner 不可改删 |
| R28-9 | 买卖方案公开能力 | `trade_profile` 增 visible 模型，API 支持可见列表/详情/版本/发布/复制，买卖指标页只读和复制 | T6,T9,T10 | 用户可查看公开买卖方案、复制为自己的 private、非 owner 不可改删 |
| R28-10 | 回测记录公开能力 | `backtest_run` 增 visible 模型，列表/详情支持可见记录，owner 可公开/收回，viewer 可复用参数重跑 | T7,T10 | 同租户/全体公开回测可读，删除和覆盖仍限 owner |
| R20/R21 延续 | 权限和菜单闭环 | 新增资源码、默认角色授权、按钮 `v-permission`、路由/端点扫描测试 | T1,T11 | 无权接口 403，按钮不显示，菜单不 fail-open |

### 3.2 可选增强

- 在可见资产列表展示 owner_label、source、readonly 和发布范围标签。
- 给回测历史列表增加“我的 / 租户公开 / 全体公开”筛选。
- 在审计摘要中增加清理任务最近执行结果。

### 3.3 暂不实现

- 不做批量审批、公开撤回审批、运营推荐和公开资产广场。
- 不做跨租户协作编辑。
- 不把公开回测的大结果表复制给 viewer；viewer 需要重跑时走当前 `backtest:run` 权限生成自己的记录。
- 不改变评分方案阶段四 B 已完成的外部 API 契约，除非为抽取通用 helper 做兼容性内部重构。

## 4. 技术方案

### 4.1 总体实现思路

阶段六按“体验增强 → 审计治理 → 通用资产可见性 → 三类资产接入 → 前端页面闭环 → 测试与文档”推进。

核心原则：

- 复用评分方案的 `private/tenant/public + opaque ref + readonly + copy` 模型。
- 抽出通用 asset ref 和可见性工具，避免 screen/trade/backtest 各自实现不同口径。
- owner 写语义和 visible 读语义分离：保存、删除、发布只查 owner；列表、详情、运行引用可以走 visible。
- 公开资产读侧不得信任前端传入 owner；所有 opaque ref 解析后必须再次校验当前用户可见性。
- 回测结果公开只读，不让 viewer 删除、覆盖或强制刷新 owner 结果。

### 4.2 R22 静默刷新设计

- `client.ts` 响应拦截遇到 401 时：
  - 登录页、`/auth/login`、`/auth/register`、`/auth/refresh` 的 401 不触发静默刷新。
  - 有 refresh token 且原请求未重试过时，调用独立 axios 实例请求 `/api/auth/refresh`，避免递归走业务拦截器。
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
  - 写入一条 `event_category='task'` 或 `event_category='security'` 的审计事件，context 记录 `retention_days/cutoff/affected_count`。
  - 清理失败只记录日志和审计失败事件，不影响主业务启动。
- 触发方式：
  - CLI：`python -m backend.cli audit-cleanup`，用于人工/部署校验。
  - 应用启动后台调度：每天低峰执行一次；PG 写任务不占 DuckDB 写互斥。
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
  - `list_runs_visible(kind)`：自己的 + 同租户公开 + 全体公开。
  - `get_run_visible(run_ref_or_id)`：解析 owner 后读取 run 和从表。
  - `set_run_visibility(run_ref_or_id, visibility)`：owner-only。
  - `delete_run()` 保持 owner-only。
- `/api/backtest/runs`：
  - 列表返回 visible runs，增加 `run_ref/source/readonly/visibility/owner_label`。
  - 详情支持 `run_ref`。
  - 删除 owner-only；非 owner 403。
  - 新增 `/runs/{run_ref}/visibility`。
- `BacktestView.vue`：
  - 历史回测下拉展示来源标签。
  - 公开记录详情只读，删除按钮隐藏或禁用。
  - 提供“复用参数”动作，将 run.params 回填到当前表单，用户点击运行后生成自己的记录。

### 4.9 页面设计闭环

- 不新增页面原型。
- 更新页面：
  - `AuditLogView.vue`：承接已更新的 [../prototypes/audit-log.html](../prototypes/audit-log.html) 详情抽屉字段变更区域。
  - `ScreenView.vue`：在已有策略筛选页增加公开标签、只读提示、复制按钮和发布下拉；不重排页面主结构。
  - `ConfigView.vue` 买卖指标页：按评分规则页现有模式增加公开标签、只读、复制和发布下拉。
  - `BacktestView.vue`：历史回测下拉和详情工具区增加公开标签、发布下拉和复用参数动作。
- 若实现时出现新增主区域、复杂抽屉或跨组件大重排，应先补对应原型再继续开发。

## 5. 需求与开发内容映射和开发状态

| 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R22 | token 静默刷新 | 前端单飞 refresh + 重放原请求 + 失败回登录 | T2 | 待开发 | 一致 | 后端 refresh 已存在，主要补前端 |
| R23 | 审计日志保留期自动清理 | 清理服务、CLI/调度入口、测试和审计事件 | T3 | 待开发 | 一致 | 复用阶段五 `audit.retention_days` |
| R24 | 字段级 from/to | `audit_log.changes`、采集 helper、审计页展示 | T4,T10 | 待开发 | 一致 | 原型已先更新 |
| R28-8 | 筛选方案公开 | `screen_profile` visible + API + ScreenView 接入 | T5,T8,T11 | 待开发 | 一致 | 方案类资产复制为 private |
| R28-9 | 买卖方案公开 | `trade_profile` visible + API + ConfigView trade 接入 | T6,T9,T11 | 待开发 | 一致 | 复用评分方案 UI 口径 |
| R28-10 | 回测记录公开 | `backtest_run` visible + API + BacktestView 接入 | T7,T10,T11 | 待开发 | 一致 | 结果资产只读，可复用参数重跑 |
| R20/R21 延续 | 权限/按钮/接口闭环 | 新资源码、默认授权、扫描和页面权限测试 | T1,T11,T12 | 待开发 | 一致 | 防 fail-open |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：阶段六范围校准与 SQL/资源码规划

- 状态：待开发
- 依赖：无
- 涉及文件/模块：
  - `backend/storage/pg_ddl.py`
  - `backend/auth/constants.py`
  - `agent-works/multi-tenant-rbac/stage6-experience-asset-visibility/*.sql`
  - `agent-works/multi-tenant-rbac/requirement.md`
- 目标：落定阶段六 DDL、资源码、菜单授权和人读 SQL 留痕。
- 操作：
  - 为 `screen_profile/trade_profile/backtest_run/audit_log` 设计增量字段和索引。
  - 新增 publish 权限码：
    - `screen-profile:publish-tenant/public`
    - `trade-profile:publish-tenant/public`
    - `backtest:publish-tenant/public`
  - 默认授权：tenant publish 默认给 tenant_admin/system；public publish 默认 system；normal/paid 需角色显式授权。
  - 写 SQL 留痕，说明执行时机、影响范围和回滚方式。
- 完成标准：DDL/seed 计划和 §5 映射无遗漏。

### 6.2 任务 T2：R22 token 静默刷新

- 状态：待开发
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
- 验证方式：mock 两个并发 401 只触发一次 refresh；refresh 成功重放请求；refresh 失败跳登录。
- 完成标准：不会重复弹“会话失效”，不会 refresh 递归。

### 6.3 任务 T3：R23 审计自动清理

- 状态：待开发
- 依赖：T1
- 涉及文件/模块：
  - `backend/storage/audit_repository.py`
  - `backend/services/audit_service.py`
  - `backend/cli.py`
  - `backend/main.py` 或调度模块
  - `backend/tests/test_stage6_audit_cleanup.py`
- 目标：自动清理超保留期审计日志，避免 `audit_log` 无限增长。
- 操作：
  - 仓库层新增按 cutoff 删除。
  - 服务层读取 `audit.retention_days` 并记录清理审计事件。
  - CLI 提供人工执行入口。
  - 启动后台调度每日低峰执行，失败只告警不阻断主业务。
- 验证方式：插入窗口内/外记录，执行清理后仅窗口外被删；tenant 范围不作为删除条件，保留期是平台全局策略。
- 完成标准：清理任务幂等，重复执行不会误删保留期内记录。

### 6.4 任务 T4：R24 审计字段变更模型

- 状态：待开发
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
- 完成标准：详情接口返回 `changes: [] | [{field,before,after}]`，敏感字段不泄漏明文。

### 6.5 任务 T5：通用资产可见性 helper

- 状态：待开发
- 依赖：T1
- 涉及文件/模块：
  - `backend/services/asset_visibility.py` 或 `backend/storage/visibility.py`
  - `backend/tests/test_stage6_asset_visibility.py`
- 目标：抽出 asset ref、source、readonly 和可见性判断公共逻辑。
- 操作：
  - 实现 ref 编解码和类型校验。
  - 实现 visible where 片段或 helper，供三个仓库复用。
  - 明确旧 id 兼容：只查当前 owner。
- 完成标准：screen/trade/backtest 三类资产不复制三套不一致 ref 逻辑。

### 6.6 任务 T6：筛选方案公开能力

- 状态：待开发
- 依赖：T4,T5
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
- 完成标准：跨租户 tenant 不可见，public 可见，非 owner 保存/删除 403。

### 6.7 任务 T7：买卖方案公开能力

- 状态：待开发
- 依赖：T4,T5
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
- 完成标准：用户可在回测中选择同租户/全体公开买卖方案，结果写当前用户回测记录。

### 6.8 任务 T8：回测记录公开能力

- 状态：待开发
- 依赖：T4,T5,T6,T7
- 涉及文件/模块：
  - `backend/services/backtest_service.py`
  - `backend/api/backtest.py`
  - `frontend/src/api/backtest.ts`
  - `frontend/src/views/BacktestView.vue`
  - `backend/tests/test_stage6_backtest_visibility.py`
- 目标：回测历史支持公开查看和参数复用。
- 操作：
  - `backtest_run` 接入 visible 字段。
  - 列表和详情支持 visible run；从表读取使用 run 的真实 owner。
  - 新增公开/收回接口，owner-only。
  - 删除保持 owner-only。
  - 前端历史回测下拉展示来源；只读公开记录隐藏删除；增加“复用参数”。
- 完成标准：viewer 能查看公开回测详情，但不能删除或覆盖 owner 记录。

### 6.9 任务 T9：前端公开资产 UI 统一

- 状态：待开发
- 依赖：T6,T7,T8
- 涉及文件/模块：
  - `frontend/src/components`（如需抽取 `AssetVisibilityTag`）
  - `frontend/src/views/ScreenView.vue`
  - `frontend/src/views/ConfigView.vue`
  - `frontend/src/views/BacktestView.vue`
- 目标：三个页面公开状态展示一致，按钮不溢出，权限态明确。
- 操作：
  - 统一 source/visibility/readonly tag 文案。
  - 公开下拉和复制按钮都走 `v-permission`。
  - 保持现有页面布局，不新增整页说明文字。
- 完成标准：三档视口无按钮文本溢出，无整页横向滚动。

### 6.10 任务 T10：审计页字段变更展示

- 状态：待开发
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
- 完成标准：详情抽屉信息区顺序与原型一致，长值不撑破抽屉。

### 6.11 任务 T11：测试、构建与页面验证

- 状态：待开发
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
- 完成标准：专项测试通过，build 通过，页面无明显布局溢出。

### 6.12 任务 T12：文档治理和阶段收尾

- 状态：待开发
- 依赖：T11
- 涉及文件/模块：
  - `CLAUDE.md`
  - `README.md`（如公开资产能力需对外说明）
  - [../requirement.md](../requirement.md)
  - 本计划
  - `DESIGN.md`（如新增组件或页面登记需要）
- 目标：阶段六事实源回写，避免后续按旧 R28 待定状态开发。
- 操作：
  - 回写 requirement 阶段六状态、R28 覆盖范围和未覆盖范围。
  - 如抽取公开状态组件，登记维护矩阵。
  - 更新计划实际落地情况和验证结果。
- 完成标准：需求、计划、代码事实和测试基线一致。

## 7. 数据库与 SQL 计划

- 计划 SQL 文件：
  - `stage6-experience-asset-visibility/stage6-experience-asset-visibility.sql`
  - `stage6-experience-asset-visibility/resource-codes.sql`
- DDL 变更：
  - `audit_log`：新增 `changes JSONB NOT NULL DEFAULT '[]'::jsonb`。
  - `screen_profile`：新增 `visibility/published_at/published_by`、合法值约束、可见性索引。
  - `trade_profile`：新增 `visibility/published_at/published_by`、合法值约束、可见性索引。
  - `backtest_run`：新增 `visibility/published_at/published_by`、合法值约束、可见性索引。
- 默认值：
  - 历史 screen/trade/backtest 资产默认 `private`。
  - 内置 screen/trade preset 默认保持 `private`，除非后续明确要平台预设全员共享；本阶段先不扩大。
- 回滚：
  - 新增字段可保留不用。
  - 若需撤回公开状态，可统一 `UPDATE ... SET visibility='private', published_at=NULL, published_by=NULL`。
  - 资源码和授权回滚需同步 bump 受影响用户 `perm_ver`。

## 8. 测试与验证计划

- 单元测试：
  - asset ref 编解码、source/readonly 判断、visibility 合法值校验。
  - AuditService changes 脱敏和清理 cutoff。
- 接口测试：
  - screen/trade/backtest visible list/detail/versions/publish/copy/delete。
  - 跨租户 tenant 不可见，public 可见，private 不可见。
  - 非 owner 保存、删除、发布均 403。
  - refresh 单飞和失败回登录。
- 页面测试：
  - AuditLogView 字段变更。
  - ScreenView 公开筛选方案只读/复制/发布。
  - ConfigView trade 公开买卖方案只读/复制/发布。
  - BacktestView 公开历史只读、删除隐藏、复用参数。
- 权限测试：
  - publish-tenant 默认 tenant_admin/system。
  - publish-public 默认 system。
  - 无角色用户 fail-closed。
- 回归测试：
  - 阶段四评分方案公开能力专项。
  - 阶段五审计/字典/系统设置专项。
  - 全量前端 build。
- 页面验证：
  - 5181 预览端口，视口 `1100x620 / 1366x768 / 1440x900`。
  - 重点检查标签、下拉、抽屉、历史回测区域不溢出。

## 9. 发布与回滚

- 发布前检查：
  - 备份 PG 中 `audit_log`、三类资产表、RBAC 资源/授权表和 `sys_user`。
  - 执行 SQL 或确认 `init_pg_db()` 幂等迁移与 SQL 留痕一致。
  - 跑阶段六专项、阶段四 R28 评分方案专项和前端 build。
- 发布步骤：
  - 停后端释放 DuckDB 锁：`./start.sh stop`。
  - 执行迁移或启动后端触发幂等 DDL。
  - 启动后端并确认 `/api/health=200`。
  - 构建并部署前端。
  - 用 system、tenant_admin、normal 三类账号抽样验证。
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
- 审计清理是不可逆删除，必须明确备份和保留期配置。
- 公开筛选方案运行时不能把结果写入方案 owner 槽，否则 viewer 会污染 owner 资产。

### 10.2 假设

- `private/tenant/public` 三档继续满足阶段六公开需求，不引入更细粒度共享名单。
- 回测记录公开仅对已完成记录有意义；running/failed 记录是否可公开按实现时校验，推荐只允许 `done`。
- 内置筛选/买卖 preset 本阶段不默认 public，避免突然扩大普通用户可见资产。

### 10.3 待确认项

| 项 | 推荐口径 | 影响 |
| --- | --- | --- |
| 内置筛选/买卖 preset 是否默认 public | 暂不默认 public，只保留 owner seed；后续如需全员预设再单独确认 | 避免阶段六扩大业务语义 |
| 回测记录是否允许 failed/running 公开 | 仅允许 `done` 公开 | 避免公开半成品或错误详情 |
| 筛选公开方案运行结果是否落库 | 非 owner 运行结果归 viewer 或不落库，不能写 owner；推荐先不落库或写 viewer 归属 | 避免污染公开方案 owner 资产 |
| R28 是否继续扩展 stock_group/training | 本阶段不做 | 避免无限扩大公开资产范围 |
