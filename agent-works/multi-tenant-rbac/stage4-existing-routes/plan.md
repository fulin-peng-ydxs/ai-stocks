# 开发计划

## 1. 需求来源与目标

- 需求文档：[../requirement.md](../requirement.md)
- 功能目标：进入多租户 RBAC 阶段四，把现有 13 个存量业务 API 路由和对应既有页面纳入阶段三已经落地的权限体系，逐一补齐 `resource code`、后端权限依赖、前端按钮级 `v-permission`、数据隔离回归和全量验证。
- 当前计划状态：待实施稿（非“已完成”）。**C1 已确认（2026-07-04）**：每日榜单采用**平台公共榜单特例**——预设评分方案归 default/admin、`score_result`/`score_snapshot` 按平台公共归属读、全员共享一份；个人自建方案结果仍纯私有、经 `POST /api/board/compute`（`persist=False`）即时查看，不进公共榜单；公共榜单生产者维持现状（调度“评分维护”/CLI 以 default/admin 归属产出预设方案结果）。T3b 已解锁，无剩余阻塞确认项。
- **明确划出阶段四之外（另立独立需求后排）**：通用「资产可见性 / 用户自助公开」模型（方案私有 / 同租户共享 / 全体公开 + 加载 = 自己的 + 公开的）、以及新用户注册时的预设方案分发（当前新用户方案列表为空、且看不到 admin 的），都会改动 R9 隔离读语义、需 publish 权限与 UI、需定公开资产改删边界，不纳入阶段四。决议依据见 [c1-board-ownership-options.md](c1-board-ownership-options.md)。
- 本次不做：
  - 不新增页面，不生成新的 HTML 原型。阶段四只在既有页面做权限接入、按钮显隐/禁用和接口守卫，不涉及新增页面、布局重排或复杂交互重构。
  - 不做阶段五能力：审计页、数据字典页、注册防滥用开关页、配置管理 4 子页面拆分。
  - 不改变阶段三已落地的用户/角色/菜单/功能/租户管理页和原型。
  - 不把 system-only 能力错误开放给租户管理员或普通用户。
- 计划输出目录：`agent-works/multi-tenant-rbac/stage4-existing-routes/`

## 2. 当前项目依据

- 需求阶段已明确阶段四范围：`R21` 为“现有 13 个 API 路由与对应页面全部纳入鉴权与隔离”，阶段四覆盖 `R21` 及 `R20` 全量按钮/路由接入。
- 阶段三权限底座已落地：
  - `backend/auth/deps.py`：`require_perm(code)` 精确码守卫，`require_system()` 系统管理员硬守卫。
  - `backend/auth/context.py`：`AuthContext` 含 `roles/is_system/menus/resources`，`get_current_owner()` 从请求上下文取 `tenant_id + owner_user_id`。
  - `backend/auth/perm_resolver.py`：权限解析以 PG 为权威，system 角色全量菜单/资源，授权变更通过 `perm_ver` 强制重登。
  - `frontend/src/directives/permission.ts`、`frontend/src/utils/permission.ts`、`frontend/src/stores/auth.ts`：前端菜单、路由守卫和按钮权限消费 `/me` 的 `menus/permissions`。
- 当前资源 seed 只覆盖阶段三管理页：
  - `backend/storage/pg_ddl.py` 的 `_SEED_RESOURCES` 已有 `user:*`、`role:*`、`menu:*`、`resource:*`、`tenant:*`。
  - `_seed_role_grants()` 当前只给 normal/paid 默认业务菜单，不给业务功能资源；新增业务功能码后需要处理默认授权和既有库回填。
- 存量 13 路由现状：
  - `backend/api/backtest.py`、`board.py`、`profiles.py`、`score_profiles.py`、`trade_profiles.py`、`stock_groups.py`、`stocks.py`、`training.py`：业务读写接口多数尚未挂精确 `require_perm`。
  - `backend/api/config.py`、`indicators.py`、`layout.py`、`data_admin.py`、`data_tasks.py`：部分系统级接口已有 `require_system`，但缺阶段四精确资源码口径。
  - `backend/main.py`：`data_tasks_router`、`data_admin_router` 整 router 叠加 `require_system`，这是全市场写/数据管理的安全边界。
- 数据隔离现状：
  - `backend/storage/asset_repository.py` 自动写入 `tenant_id/owner_user_id`。
  - `backend/scoring/score_profile.py`、`backend/screening/profile.py`、`backend/services/backtest_service.py`、`backend/services/training_service.py` 等已通过 `get_current_owner()` 和复合主键做个人私有隔离。
  - `backend/api/board.py` 当前仍使用 `DEFAULT_TENANT_ID/DEFAULT_OWNER_USER_ID` 读取榜单结果，需要阶段四校准为当前用户归属或明确作为系统公共结果。
- 前端页面现状：
  - 既有业务页均已在 `frontend/src/router/index.ts` 注册，并已走 `LayoutHost` 或登录全屏壳。
  - `frontend/src/layout/pageRegistry.ts`、`DESIGN.md`、`agent-works/configurable-layout-system/page-template.md` 已形成页面布局治理事实源。
  - 阶段四不改变页面结构，只在既有按钮、菜单入口和接口调用处补权限。
- 测试基线：
  - 后端已有 `backend/tests/test_auth_middleware.py`、`test_rbac_deps.py`、`test_rbac_me.py`、`test_rbac_*`。
  - 前端已有 `frontend/src/directives/__tests__/permission.spec.ts`、`frontend/src/utils/__tests__/permission.spec.ts`、`frontend/src/components/__tests__/SideMenu.spec.ts`、布局契约测试。

## 3. 实施范围

### 3.1 必须实现

- 为 13 个存量 API 路由建立阶段四资源码矩阵，资源码必须稳定、精确、可追踪到菜单和接口。
- 新增或更新 `sys_resource` 初始化数据，并提供既有库的一次性资源码/默认授权回填方案。
- 用户资产类和共享业务类接口逐端点接 `require_perm(code)`。
- system-only 接口继续保留 `require_system` 硬守卫，同时补充精确资源码元数据或组合依赖，避免阶段四把系统能力误授权给非 system。
- 前端既有页面的后端写操作、敏感读操作和任务操作补齐 `v-permission` 或共用 `hasPermission()` 判定。
- 校验所有私有资产接口仍按当前用户归属过滤，跨租户、跨用户不可见。
- 补充后端路由扫描、权限 403、跨账号隔离和前端按钮权限测试。
- 更新阶段四开发留痕和主需求阶段状态。

### 3.2 可选增强

- 增加权限码常量文件，后端与前端分别集中管理阶段四 code，减少字符串漂移。
- 增加路由到资源码的测试报告输出，便于后续阶段五审计直接消费。
- 为高频按钮增加无权限 tooltip，而非仅移除元素。仅在现有组件易接入时做，不扩大页面改造。

### 3.3 暂不实现

- 不生成 `prototypes/*.html`。
- 不拆 `ConfigView.vue` 的 4 个 tab；配置管理父子菜单重构留阶段五 `R19/R16`。
- 不新增审计表、字典表或审计页面；阶段四只让资源码体系为阶段五审计打基础。
- 不做通用「资产可见性 / 用户自助公开」模型（私有 / 同租户 / 全体公开 + 加载 = 自己 + 公开）。C1 已确认仅落**公共榜单特例**（预设方案归 default/admin、公共榜单全员共享一份），不引入通用 `visibility` 列、publish 开关/UI 或公开资产改删边界。个人自建方案仍纯私有。通用共享模型另立独立需求后排。
- 不处理新用户注册的预设方案分发（当前新用户方案列表为空）；该项随通用公开模型一并解决，不在阶段四。
- 不做 token 静默刷新、审计保留期清理、字段级审计对比。

## 4. 技术方案

### 4.1 总体策略

阶段四采用“先建矩阵，再接后端，再接前端，最后做扫描回归”的顺序。

- 后端为准：所有有业务权限含义的 API 必须先由后端守卫拒绝无权请求，前端隐藏只是体验层。
- system-only 不降级：数据管理、任务调度、技术指标写、系统配置、布局平台配置继续由 `require_system` 硬守。资源码只用于登记、页面按钮、测试扫描和后续审计，不作为允许非 system 访问的依据。
- 用户资产类可授权：筛选方案、评分方案、买卖指标方案、自选分组、回测记录、盘感训练、用户级布局配置使用 `require_perm(code)`，normal/paid/tenant_admin 可通过角色授权获得。
- 共享只读类仍要有码：行情列表、个股详情、每日榜单、指标注册表、交易日期、布局生效配置等虽然不加归属过滤，也要通过资源码控制是否可用。
- 全站/研究基础共享读必须独立成登录基线码，不能挂到某个业务页面码或 system-only 码上：布局预设/页面配置/生效配置、交易日历、指标目录这类端点被多个页面或应用启动链路消费，必须对所有登录业务角色恒可用，并在角色页置灰不可反选。
- 数据隔离复核：凡写入或读取用户资产的接口，服务或仓库必须从 `get_current_owner()` 获取归属，不接受前端传入归属覆盖。

### 4.2 后端权限依赖方案

新增或调整 `backend/auth/deps.py`：

- 保留 `require_perm(code)` 语义，并为返回的依赖函数挂可测试元数据，例如 `resource_code = code`。
- 新增组合依赖 `require_system_perm(code)`，内部先执行 `require_system()`，并挂 `resource_code = code`。用于 system-only 端点，保证路由扫描能看到精确码，但运行时仍由 system 硬守卫兜底。
- 新增登录基线码机制 `baseline_locked`：`_SHARED_RESOURCE_CODES` 中的 `layout:view`、`trade-calendar:view`、`indicator:registry` 不再只是默认授权，而是所有已认证业务用户的最小可用资源集。权限解析时把基线码强制注入非 system 用户的 `resources`；system 用户仍走全量资源。
- 角色授权页保留基线码展示，但与 system-only 锁定相反：基线码始终勾选、置灰且不可取消。后端保存授权时必须强制并入基线资源，不能因前端直调或管理员反选导致业务角色丢失这些码。
- 路由扫描测试只允许四类 API：
  - 白名单：`/api/health`、`/api/auth/*`。
  - 已接精确码：依赖中有 `resource_code`。
  - 显式例外：只允许极少数内部无业务权限含义且已说明的非动态 scope 接口；初始计划不设置此类例外。
  - 动态 scope 自守卫端点：仅允许登记在 `DYNAMIC_SCOPE_GUARDED_ROUTES` 的端点，初始只允许 `POST /api/layout/reset`。该类端点必须在函数体内按 payload scope 执行资源码或 system 守卫，并有专门测试覆盖每个 scope。

### 4.3 资源码矩阵初稿

T1 需把下表固化成 `resource-codes.sql` 和 `pg_ddl.py` seed。最终 code 可在不改变业务边界的前提下微调，但必须保持精确、稳定、全局唯一。

| 路由模块/分类 | 资源码 | 端点范围 | 菜单归属 | 权限策略 |
| --- | --- | --- | --- | --- |
| `board.py` | `board:view` | `GET /api/scores/top`、`GET /api/scores` | `/board` | 登录且有每日榜单权限 |
| `board.py` | `board:compute` | `GET /api/board/compute` | `/board` | 登录且有榜单计算权限 |
| `layout.py` | `layout:view` | `GET /api/layout/presets`、`GET /api/layout/pages/{page_key}`、`GET /api/layout/effective/{page_key}` | 全站共享读（FK 锚点 `/board`，login） | `baseline_locked`，所有登录业务角色恒可用，不能 system-only，不能在角色页反选 |
| `stocks.py` | `trade-calendar:view` | `GET /api/data/trade-dates` | 全站共享读（FK 锚点 `/board`，login） | `baseline_locked`，所有登录业务角色恒可用，不能挂 `stocks:view`，不能在角色页反选 |
| `stocks.py` | `stocks:view` | `GET /api/stocks`、`/stocks/{code}/bars`、`/signal`、`/indicators` | `/stocks` | 登录且有个股行情权限 |
| `stocks.py` | `stocks:trade-eval` | `GET /api/stocks/{code}/trade-eval` | `/stocks` | 登录且有买卖评估权限 |
| `profiles.py` | `screen-profile:view` | `GET /api/profiles*` | `/screen` | 用户资产读 |
| `profiles.py` | `screen-profile:save` | `POST /api/profiles` | `/screen` | 用户资产写 |
| `profiles.py` | `screen-profile:delete` | `DELETE /api/profiles/{pid}` | `/screen` | 用户资产删 |
| `profiles.py` | `screen:run` | `POST /api/screen/run` | `/screen` | 策略筛选执行 |
| `score_profiles.py` | `score-profile:view` | `GET /api/score-profiles*` | `/system/config` | 阶段四仍归现配置页；阶段五拆页后迁移菜单 |
| `score_profiles.py` | `score-profile:save` | `POST /api/score-profiles` | `/system/config` | 用户资产写，前端页面暂 system-only |
| `score_profiles.py` | `score-profile:delete` | `DELETE /api/score-profiles/{pid}` | `/system/config` | 用户资产删 |
| `score_profiles.py` | `score:run` | `POST /api/score-profiles/run` | `/board` | 打分执行；C1 若确认公共榜单，需同步明确其写入 `score_snapshot` 的归属和公共结果生产链路 |
| `trade_profiles.py` | `trade-profile:view` | `GET /api/trade-profiles*` | `/system/config` | 用户资产读 |
| `trade_profiles.py` | `trade-profile:save` | `POST /api/trade-profiles` | `/system/config` | 用户资产写 |
| `trade_profiles.py` | `trade-profile:delete` | `DELETE /api/trade-profiles/{pid}` | `/system/config` | 用户资产删 |
| `trade_profiles.py` | `trade-profile:preview` | `POST /api/trade-profiles/preview` | `/system/config` | 买卖条件试算 |
| `stock_groups.py` | `stock-group:view` | `GET /api/stock-groups*` | `/stocks` | 用户资产读 |
| `stock_groups.py` | `stock-group:create` | `POST /api/stock-groups` | `/stocks` | 用户资产写 |
| `stock_groups.py` | `stock-group:update` | `PATCH /api/stock-groups/{gid}` | `/stocks` | 用户资产写 |
| `stock_groups.py` | `stock-group:delete` | `DELETE /api/stock-groups/{gid}` | `/stocks` | 用户资产删 |
| `stock_groups.py` | `stock-group:member-update` | `POST/DELETE/PATCH /api/stock-groups/{gid}/members*` | `/stocks` | 分组成员维护 |
| `backtest.py` | `backtest:view` | `GET /api/backtest/runs*` | `/backtest` | 用户资产读 |
| `backtest.py` | `backtest:run` | `POST /api/backtest/run`、`/prepare` | `/backtest` | 回测执行 |
| `backtest.py` | `backtest:robust` | `POST /api/backtest/robust` | `/backtest` | 稳健性测试 |
| `backtest.py` | `backtest:delete` | `DELETE /api/backtest/runs/{run_id}` | `/backtest` | 回测记录删除 |
| `training.py` | `training:view` | `GET /api/training/sessions*`、`/growth` | `/training` | 用户资产读 |
| `training.py` | `training:start` | `POST /api/training/sessions` | `/training` | 创建训练 |
| `training.py` | `training:trade` | `POST /api/training/sessions/{sid}/reveal|trade|cancel|settle-round` | `/training` | 训练过程操作 |
| `training.py` | `training:review` | `PATCH /api/training/sessions/{sid}/review` | `/training` | 保存复盘 |
| `training.py` | `training:delete` | `DELETE /api/training/sessions/{sid}` | `/training` | 删除训练 |
| `layout.py` | `layout:user-config` | `GET/POST /api/layout/users/{page_key}`、`POST /api/layout/reset` user scope | 业务页 settings drawer | 用户级偏好读写，所有登录业务角色默认可用 |
| `layout.py` | `layout:preset-manage` | `POST/DELETE /api/layout/presets*` | `/system/layout/presets` | `require_system_perm` |
| `layout.py` | `layout:page-manage` | `POST /api/layout/pages/{page_key}`、`POST /api/layout/validate`（仅系统页面布局工作台消费，现无守卫，T5 补）、page scope reset | `/system/layout/pages` | `require_system_perm` |
| `layout.py` | `layout:field-policy` | `GET/POST /api/layout/field-policies` | `/system/layout/components` | `require_system_perm` |
| `indicators.py` | `indicator:registry` | `GET /api/indicators/registry` | 研究基础共享读（FK 锚点 `/screen`，login） | `baseline_locked`，Board/Screen/Config 跨页指标目录读，所有登录研究业务角色恒可用，不能绑定配置页，不能在角色页反选；写仍 system-only |
| `indicators.py` | `indicator:def-manage` | `POST/PATCH/DELETE /api/indicators/def*` | `/system/config` | `require_system_perm` |
| `config.py` | `config:view` | `GET /api/config` | `/system/config` | `require_system_perm` |
| `config.py` | `config:reload` | `POST /api/config/reload` | `/system/config` | `require_system_perm` |
| `data_admin.py` | `data:overview` | `GET /api/data/overview|hub|catalog|dimensions|provenance|stock-quality` | `/data/overview` | `require_system_perm` |
| `data_admin.py` | `data-quality:view` | `GET /api/data/quality` | `/data/quality` | `require_system_perm` |
| `data_admin.py` | `data-quality:fix` | `POST /api/data/quality/*` fix/reset/ignore/recover/mark-delisted | `/data/quality` | `require_system_perm` |
| `data_admin.py` | `data-schedule:manage` | `GET/POST/PUT/DELETE /api/data/schedules*`、run/enabled | `/data/schedule` | `require_system_perm` |
| `data_admin.py` | `data-source:test` | `GET /api/data/sources`、`POST /api/data/sources/test` | `/data/schedule` | `require_system_perm` |
| `data_admin.py` | `data-settings:manage` | `GET/POST /api/data/settings` | `/data/schedule` | `require_system_perm` |
| `data_tasks.py` | `data-task:manage` | `POST/GET /api/data/tasks*`、resume/cancel/logs/list | `/data/ingest` | `require_system_perm` |
| `stocks.py` | `data-status:view` | `GET /api/data/status`、`/data/update-logs` | `/data/overview` | `require_system_perm` |

### 4.4 初始化数据、基线码与默认授权

- `backend/storage/pg_ddl.py`
  - 扩展 `_SEED_RESOURCES`，追加阶段四资源码。
  - 新增 `_SHARED_RESOURCE_CODES`，包含 `layout:view`、`trade-calendar:view`、`indicator:registry` 等所有登录业务角色必须具备且不可移除的 `baseline_locked` 基础读码。
  - 新增 `_BUSINESS_RESOURCE_CODES`，包含 normal/paid/tenant_admin 默认可用的业务资源码。
  - system 角色继续幂等补齐全量菜单和全量资源。
  - 非 system 内置角色不改变既有“管理员手工调整不被启动覆盖”的原则。
- `backend/auth/perm_resolver.py`、`backend/services/auth_service.py`
  - 解析 `/me` 和后端权限上下文时，对非 system 已认证业务用户强制并入 `_SHARED_RESOURCE_CODES`；无角色用户仍 fail-closed。
  - 基线码变化属于有效权限变化，既有库启用或调整基线码后必须对受影响业务用户 bump `perm_ver` 或清 perms 缓存。
- `backend/storage/role_repository.py`、`frontend/src/views/system/RoleManageView.vue`
  - 新增基线资源 ID 查询和 `baseline_locked` 元数据，角色授权读回显时始终包含基线码。
  - 保存授权时后端强制并入基线资源；前端权限树把基线码渲染为勾选置灰，不纳入可取消叶子集合。
- `agent-works/multi-tenant-rbac/stage4-existing-routes/resource-codes.sql`
  - 作为阶段四资源码、基线码与默认授权的一次性执行/审阅脚本。
  - 仅对阶段四新增资源码执行 `INSERT ... ON CONFLICT DO NOTHING`。
  - 对 normal/paid/tenant_admin 的默认业务资源执行一次性 `INSERT ... ON CONFLICT DO NOTHING`，不作为每次启动自动重置。
  - 回填授权或启用基线码时必须同步对受影响用户执行 `perm_ver` 自增；建议通过迁移 CLI 在同一 PG 事务内完成 `sys_role_resource` 写入、基线码启用与 `sys_user.perm_ver` bump，提交后 best-effort 清理 Redis `auth:perms:*` 缓存。若使用纯 SQL，必须在 SQL 中包含 affected users 的 `UPDATE sys_user SET perm_ver = perm_ver + 1 ...`，并在发布步骤中强制相关用户重新登录。
  - system-only 资源挂在 `visible='system'` 菜单下，`RoleRepository.system_only_resource_ids()` 会阻止授予非 system 角色。

### 4.5 页面技术实现

阶段四没有新增页面，也没有复杂更新页面。所有页面均保留现有布局、`LayoutHost`、弹窗、抽屉和滚动策略。原型文件：不生成，依据为需求文档 R21 对“既有页面接入权限”的定义，以及当前 `DESIGN.md` 与 `pageRegistry.ts` 的既有页面登记。

前端页面设计闭环判断：不涉及前端页面设计闭环；不新增页面、不调整布局原型、不新增或变更 `pageRegistry`、不改变设置抽屉结构，不触发组件/布局维护矩阵。阶段四前端改动仅限既有按钮/操作入口的权限显隐、禁用或脚本级防护。T6 必须逐页检查操作区稳定性：如果某工具栏分组或表格操作列在无权限角色下会被全部移除，需要用页面内 computed 控制整组/整列显隐，避免留下空工具栏、空操作列或按钮回流造成布局抖动；保留查询、刷新、页面设置等不敏感基础操作的既有布局。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 每日榜单刷新/计算/导出 | R20/R21 | 有菜单权限才可进入，计算接口有权限才可调用 | 页面结构不变，接口按 `board:view`、`board:compute` 守卫；导出 CSV 为本地操作，不单独加码 | `BoardView.vue` | `board.py` | 401 跳登录，403 提示无权或隐藏触发入口 | T3b,T6 |
| 策略筛选方案维护与运行 | R20/R21 | 查询、编辑条件、保存方案、运行筛选、恢复版本 | 保存/删除/运行按钮加 `v-permission`，后端用 `screen-profile:*`、`screen:run` | `ScreenView.vue` | `profiles.py` | 无权按钮移除；后端 403 兜底 | T3a,T6 |
| 回测运行、稳健性、历史删除 | R20/R21 | 可运行回测、查看历史、删除历史 | 运行/稳健性/删除按钮按 `backtest:*` 控制，历史读按 `backtest:view` | `BacktestView.vue` | `backtest.py` | loading 和现有错误态保留；403 统一提示 | T4,T6 |
| 盘感训练全过程 | R20/R21 | 开始训练、买卖、撤单、结算、复盘、删除 | 过程按钮按 `training:start/trade/review/delete` 控制 | `TrainingView.vue` | `training.py` | 无权时不展示交易动作；直调接口 403 | T4,T6 |
| 个股行情和分组维护 | R20/R21 | 查询个股、详情页、加入/移出分组、新建/编辑/删除分组 | 行情读 `stocks:view`，交易评估 `stocks:trade-eval`，分组按钮按 `stock-group:*` | `StocksView.vue`、`StockDetailView.vue` | `stocks.py`、`stock_groups.py` | 分组越权查无结果或 403；按钮无权移除 | T3a,T6,T8 |
| 配置管理现有单页 | R20/R21 | 当前仍是 system-only 单页，内部含评分/技术/买卖/系统设置 | 阶段四不拆页；系统级按钮保留 `require_system_perm`；用户资产配置 API 先补码，页面开放留阶段五 | `ConfigView.vue` | `config.py`、`indicators.py`、`score_profiles.py`、`trade_profiles.py` | 普通用户目前无菜单入口；直达由路由守卫拦截 | T3a,T5,T6 |
| 数据概览/质量/采集/调度 | R20/R21 | 系统管理员管理全市场数据和任务 | 全部 system-only；按钮按 `data:*`、`data-quality:*`、`data-task:*`、`data-schedule:*` 控制 | `data/*.vue` | `data_admin.py`、`data_tasks.py`、`stocks.py` data endpoints | 非 system 403，不显示菜单和操作按钮 | T5,T6 |
| 布局配置工作台和用户设置抽屉 | R20/R21 | 普通用户可保存自己的页面偏好，system 可管 preset/page/policy | 用户层 `layout:user-config`；平台层 `layout:*manage` 继续 system-only | `PageSettingsDrawer.vue`、`layout/*.vue`、各业务页设置入口 | `layout.py` | 用户层不能伪造 userId；page/preset scope 非 system 403 | T4,T5,T6,T8 |

## 5. 需求与开发内容映射和开发状态

| 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R8 | 接口级 + 按钮级 RBAC 权限校验 | 阶段四补齐存量业务接口 `resource code`、后端 `require_perm/require_system_perm`、前端 `v-permission` | T1,T2,T3a,T3b,T4,T5,T6,T8,T9 | 进行中 | 一致 | T1 资源码矩阵已固化（48 码，见 resource-codes.sql）；C1 已确认（公共榜单特例），`board.py` 权限接入随 T3b 正常推进 |
| R9 | 数据归属与租户隔离 | 复核 profiles/groups/backtest/training/layout 等资产接口均按 `get_current_owner()` 隔离；每日榜单按 C1 定为平台公共只读、有意不带用户归属，个人自建方案结果仍私有 | T3a,T3b,T4,T8 | 待开始 | 一致 | C1 已确认；公共榜单读“有意全局”须显式声明，与私有资产隔离用例分开。通用可见性/公开模型不在阶段四 |
| R20 | 前端登录态与权限渲染 | 既有页面写操作、敏感操作和系统级操作补按钮权限；菜单/路由守卫保持 fail-closed | T6,T9 | 待开始 | 一致 | 不新增页面，不重排布局 |
| R21 | 全部存量功能/接口接入用户体系 | 13 个存量路由逐一补资源码、守卫、基线码、默认授权、测试扫描和全量回归；榜单按 C1 公共特例接入 | T1,T2,T3a,T3b,T4,T5,T6,T7,T8,T9,T10 | 进行中 | 一致 | T1 已核对 91 端点全映射（发现 `layout/validate` 裸露端点，纳入 T5）；C1 已确认，全量接口无阻塞；通用资产共享/公开为阶段四外独立需求 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：固化阶段四资源码矩阵

- 状态：已完成
- 依赖：阶段三 RBAC 机制已稳定
- 涉及文件/模块：
  - `agent-works/multi-tenant-rbac/stage4-existing-routes/plan.md`
  - `agent-works/multi-tenant-rbac/stage4-existing-routes/resource-codes.sql`
  - `backend/api/*.py`
- 目标：形成完整、无遗漏、可回归扫描的 13 路由资源码矩阵。
- 操作：
  - 逐个核对 `backend/api/backtest.py`、`board.py`、`config.py`、`indicators.py`、`layout.py`、`profiles.py`、`score_profiles.py`、`trade_profiles.py`、`stock_groups.py`、`stocks.py`、`data_tasks.py`、`data_admin.py`、`training.py`。
  - 把每个端点归为共享只读、用户资产、system-only 三类。
  - 单独核对全站/研究基础共享读端点：`GET /api/layout/presets`、`GET /api/layout/pages/{page_key}`、`GET /api/layout/effective/{page_key}`、`GET /api/data/trade-dates`、`GET /api/indicators/registry` 必须有登录业务角色恒可用且不可反选的 `baseline_locked` 共享读码。
  - 登记动态 scope 自守卫端点清单，初始仅 `POST /api/layout/reset`；扫描测试必须要求它有 scope 分支测试。
  - 输出 `resource-codes.sql`，记录新增 `sys_resource`、归属菜单、是否 `baseline_locked`、默认授权目标角色和是否 system-only。
- 产出：阶段四资源码矩阵和 SQL 计划文件。
- 影响范围：权限 seed、角色授权页、前端按钮权限、后续审计资源码。
- 边界与异常：如果发现某端点无法稳定归类，必须在本计划 §10.3 追加待确认项后再继续接入该端点。
- 验证方式：人工核对 + 后续 T8 路由扫描测试。
- 完成标准：13 个路由模块的所有非白名单端点均有明确资源码或明确 system-only 码。
- 实际落地情况：已完成（2026-07-04）。
  - 逐一核对 13 模块共 **91 个端点**（`grep '@router.<verb>'`），全部映射到 **48 个资源码 + 1 个动态 scope 自守卫端点**（`POST /api/layout/reset`），无遗漏。产出 [resource-codes.sql](resource-codes.sql)：A 类 baseline 基线共享读 3、B 类可授权业务码 24、C 类 system-only 21。
  - 相对 §4.3 初稿的两处**具体化落定**（不改业务边界）：
    1. **`POST /api/layout/validate` 现无任何守卫**（`layout.py:156`，纯校验、不落库不涉归属），经查仅被系统页面布局工作台 `LayoutPagesView.vue` 消费 → 归 `layout:page-manage`（system-only），T5 补 `require_system_perm`。这是本次核对发现的既有裸露端点。
    2. baseline 三码 + `layout:user-config` 无天然业务菜单，而 `sys_resource.menu_id` 为 `NOT NULL + FK` 且不得挂 `visible='system'` 菜单（否则被 `system_only_resource_ids` 误判、非 system 授不了）。经确认 `menu_id` 只影响角色页分组渲染与 system-only 判定、**不影响 baseline 的运行时强制注入**，故锚定现有 login 叶子（零菜单树改动）：`layout:view`/`trade-calendar:view`/`layout:user-config`→`/board`，`indicator:registry`→`/screen`。
  - **score-profile:\* / trade-profile:\* 归 `/system/config`（visible='system'）**：本阶段配置页仍 system-only，这些码经菜单可见性自动进 `system_only_resource_ids`，非 system 授权被拦截 → 事实上 system-only；阶段五拆页后移菜单即开放，故 T3a 仍以 `require_perm(code)` 接入（保留迁移路径），不用 `require_system_perm`。
  - SQL 含既有库一次性回填：资源落行 + normal/paid/tenant_admin 业务默认授权 + system 全量补齐 + 全部非 system 用户 `perm_ver` bump，整脚本单事务。

### 6.2 任务 T2：补齐资源 seed、基线码、默认授权与权限依赖元数据

- 状态：已完成
- 依赖：T1
- 涉及文件/模块：
  - `backend/storage/pg_ddl.py`
  - `backend/auth/deps.py`
  - `backend/auth/perm_resolver.py`
  - `backend/services/auth_service.py`
  - `backend/storage/role_repository.py`
  - `frontend/src/views/system/RoleManageView.vue`
  - `agent-works/multi-tenant-rbac/stage4-existing-routes/resource-codes.sql`
- 目标：让新装库和既有库都能获得阶段四资源码、基线共享读码和默认业务授权，且 role 授权页与后端守卫口径一致。
- 操作：
  - 扩展 `_SEED_RESOURCES`，追加阶段四资源码。
  - 增加 `_SHARED_RESOURCE_CODES`，用于所有登录业务角色强制持有且不可反选的全站/研究基础共享读码。
  - 增加 `_BUSINESS_RESOURCE_CODES`，用于 normal/paid/tenant_admin 默认业务授权的一次性回填。
  - 权限解析时把 `_SHARED_RESOURCE_CODES` 注入所有非 system 已认证业务用户的 `resources`；无角色用户仍 fail-closed。
  - 角色授权读写时把基线码作为 `baseline_locked` 资源处理：回显勾选、前端置灰、保存时后端强制并入。
  - 确保 system 角色启动幂等补齐全量资源。
  - 新增或调整 `require_system_perm(code)`，system-only 端点保留硬守卫并挂资源码元数据。
  - 给 `require_perm` 返回函数挂 `resource_code`，供 T8 扫描。
- 产出：资源 seed、基线共享读机制、默认授权机制、权限依赖元数据。
- 影响范围：新装数据库、既有数据库升级、角色管理页可勾选资源树、`/me` 权限集合。
- 边界与异常：
  - 不在每次启动时强制恢复 normal/paid 的业务资源授权，避免覆盖管理员后续手工调整。
  - `_SHARED_RESOURCE_CODES` 不属于可被管理员移除的业务授权，不适用“手工调整不覆盖”原则；这是业务用户运行应用的基线能力。
  - system-only 资源必须挂在 `visible='system'` 菜单下，防止非 system 角色被误授。
- 验证方式：
  - `python -m pytest backend/tests/test_rbac_schema.py backend/tests/test_rbac_roles.py -q`
  - 新增 seed/backfill 测试。
- 完成标准：阶段四资源码可在 PG 中幂等存在；system 全量；normal/paid/tenant_admin 有业务默认码；非 system 不能拿 system-only 码。
- 实际落地情况：已完成（2026-07-04）。
  - `backend/auth/constants.py`：新增 `SHARED_RESOURCE_CODES`（3 baseline）+ `BUSINESS_RESOURCE_CODES`（24），零依赖、供 pg_ddl/perm_resolver/repository 共用。
  - `backend/storage/pg_ddl.py`：`_SEED_RESOURCES` 追加 48 阶段四资源码（与 resource-codes.sql 一致）；`_seed_role_grants` 给 normal/paid = `BUSINESS_RESOURCE_CODES`、tenant_admin = 用户管理码 + 业务码；system 全量补齐不变。
  - `backend/auth/deps.py`：`require_perm` 返回依赖挂 `resource_code` 元数据；新增 `require_system_perm(code)`（运行时 = require_system 硬守卫 + 挂 `resource_code`/`require_system_perm=True` 供 T8 扫描）。
  - `backend/auth/perm_resolver.py`：`resolve()` 对**非 system 且有角色**用户强制并入 baseline（运行时权威）；无角色仍 fail-closed。
  - `backend/storage/resource_repository.py`：DTO 增 `baseline_locked`（code ∈ SHARED_RESOURCE_CODES）。
  - `backend/storage/role_repository.py`：新增 `baseline_resource_ids()`（取交集防未 seed）。
  - 前端 `menu.ts`/`PermissionTree.vue`/`RoleManageView.vue`：Resource 增 `baseline_locked`；角色树 baseline 节点恒勾选 + 置灰 + 「基线」标签 + 排除出可勾选/全选/gather 集（`baselineLocked` 与 `sysLocked` 相反语义）。
  - **关键设计决定（相对 §4.4 初稿的收敛）**：baseline **不持久化进 `sys_role_resource` 授权**，改由 `perm_resolver.resolve` 运行时强制注入作为**单一权威**——比"保存时并入持久化"更强（前端漏传/直调都无法绕过），且保持 `set/get_grants` 幂等、不污染 grants 表、不破坏既有 `test_rbac_roles` 授权回显用例；角色页据 `baseline_locked` 标记展示锁定态，不当作可授权项。故未改 `role_admin_service.set_grants` 的持久化逻辑（原“保存时强制并入”降级为注释说明）。
  - 验证：后端 `test_rbac_{me,perm_resolver,roles,resources,menus,deps,schema}` **84 passed**；前端 `npm run build` 通过 + `permission/SideMenu/manage-error-states/layout` **118 passed**。同步更新 `test_rbac_me.py::test_normal_me_business_only` 断言为「baseline 恒注入 + 不含 system-only 码」（持久测试库 normal 为 stage3 存量态，业务码默认授权走新库 seed / 既有库回填 SQL，其授权→/me 链路留 T8 显式授权用例）。

### 6.3 任务 T3a：非榜单业务共享读与用户资产基础接口接入

- 状态：已完成
- 依赖：T2
- 涉及文件/模块：
  - `backend/api/stocks.py`
  - `backend/api/profiles.py`
  - `backend/api/score_profiles.py`
  - `backend/api/trade_profiles.py`
  - `backend/api/stock_groups.py`
  - `backend/api/indicators.py`
- 目标：个股行情、交易日历、指标目录、策略筛选、评分方案、买卖方案、自选分组逐端点接入精确 `require_perm`。
- 操作：
  - 给非榜单共享读接口挂 `stocks:view`、`stocks:trade-eval`、`indicator:registry` 等读码。
  - 给全站基础共享读接口 `GET /api/data/trade-dates` 挂 `trade-calendar:view`，确保不依赖 `/stocks` 菜单授权。
  - 给跨页指标目录 `GET /api/indicators/registry` 挂 `indicator:registry`，确保有筛选/榜单但无配置页的自定义角色仍能加载指标选择器。
  - 给用户资产 CRUD 挂 `screen-profile:*`、`score-profile:*`、`trade-profile:*`、`stock-group:*`。
  - 确认各仓库不接受前端 tenant/owner 覆盖。
- 产出：业务读写接口精确权限码接入。
- 影响范围：`/screen`、`/stocks`、`/system/config` 内评分/买卖相关接口。
- 边界与异常：ConfigView 阶段四仍 system-only，评分/买卖配置 API 先有码，普通用户页面入口留阶段五拆页后开放。
- 验证方式：
  - 新增无权限用户访问样例接口 403。
  - 新增拥有业务码用户访问样例接口 200 或进入业务层错误而非 401/403。
  - 跨用户 profile/group 读写隔离测试。
- 完成标准：上述模块非白名单接口均被 T8 扫描识别为已接资源码。
- 实际落地情况：已完成（2026-07-04）。
  - 逐端点挂 `dependencies=[Depends(require_perm("code"))]`（沿用 users.py 惯例）：
    - `stocks.py`：`/stocks`·`/{code}/bars`·`/signal`·`/indicators` → `stocks:view`；`/{code}/trade-eval` → `stocks:trade-eval`；`/data/trade-dates` → `trade-calendar:view`（baseline）。（`/data/status`·`/data/update-logs` 属 system-only，留 T5）
    - `profiles.py`：GET×3 → `screen-profile:view`；POST → `screen-profile:save`；DELETE → `screen-profile:delete`；`/screen/run` → `screen:run`。
    - `score_profiles.py`：GET×3 → `score-profile:view`；POST → `score-profile:save`；DELETE → `score-profile:delete`；`/run` → `score:run`。
    - `trade_profiles.py`：GET×3 → `trade-profile:view`；POST → `trade-profile:save`；DELETE → `trade-profile:delete`；`/preview` → `trade-profile:preview`。
    - `stock_groups.py`：GET×2 → `stock-group:view`；POST → `create`；PATCH → `update`；DELETE → `delete`；members POST/DELETE/PATCH → `stock-group:member-update`。
    - `indicators.py`：`/indicators/registry` → `indicator:registry`（baseline）；写端点仍 system-only（T5）。
  - 前端归属越权核查：上述端点 body 模型（ProfileIn/ScoreProfileBody/TradeProfileBody/GroupCreate/GroupMeta/MembersBody）均**不含 tenant/owner 字段**，仓库经 `get_current_owner()` 取归属，无前端覆盖路径。
  - 测试基建适配：`test_auth_middleware.py::tadmin` fixture 原为「有 role_code 但无 sys_user_role」的 stage3 捷径（fail-closed），stage4 改为显式挂 `sys_user_role(tenant_admin)` + 幂等补 tenant_admin 业务码授权（对齐 seed/回填意图；非 system by kind 不变，故全部 system-only「forbidden」断言仍成立）。
  - 验证：**全量后端 398 passed**（含 test_auth_middleware/test_api 及各仓库隔离用例）。

### 6.4 任务 T3b：每日榜单接口接入（公共榜单特例，C1 已确认）

- 状态：待开始
- 依赖：T2（C1 已确认=平台公共榜单特例，无阻塞）
- 涉及文件/模块：
  - `backend/api/board.py`
  - `backend/scoring/*`（`ScoreSnapshotRepo` 读侧归属）
  - `backend/storage/pg_ddl.py`（公共归属常量口径）
  - `CLAUDE.md`（补“公共榜单读有意不带归属”铁律）
  - `backend/tests/test_stage4_resource_codes.py`（新增或扩展）
- 目标：把每日榜单接入 `board:view`/`board:compute`，并将 `board.py` 的 `default/admin` 读取**显式定性为平台公共只读**（有意不带用户归属），而非用户私有资产读。
- 操作（C1 = 公共榜单特例，口径已定）：
  - 给 `GET /api/scores/top`、`GET /api/scores` 挂 `board:view`，`GET /api/board/compute` 挂 `board:compute`。
  - `board.py` 读侧**保留平台公共归属**（现 `DEFAULT_TENANT_ID/DEFAULT_OWNER_USER_ID`），但把它从“stage1 未落 auth 的临时默认”改写为**显式的平台公共榜单归属常量**（命名与注释体现“有意全局、非用户私有”），并在 `CLAUDE.md`「资产归属与隔离」补一条：`score_result`/`score_snapshot` 公共榜单读**有意不带归属**（与 `indicator_def`/`mark_stale_*` 同类先例并列），防后续按私有资产铁律误加归属过滤。
  - 生产者维持现状：调度“评分维护”/CLI 以 default/admin（= 平台公共归属）产出预设方案的 `score_result`/`score_snapshot`。本任务不改生产链路，只固化“预设方案归 default/admin”这一约定。
  - `score:run`（`POST /api/score-profiles/run`）仍写**调用者个人归属**（属 T3a 的用户资产写，不在本任务），不进公共榜单；个人打分结果经 `POST /api/board/compute`（`persist=False`）即时查看。
  - **不做**通用可见性/公开列、不做新用户预设分发（阶段四外）。
- 产出：每日榜单接口权限接入 + 公共榜单归属口径显式固化 + CLAUDE.md 铁律。
- 影响范围：`/board` 读侧、公共榜单归属常量、`score_snapshot` 公共读；不改 `score:run` 归属、不改生产调度。
- 边界与异常：公共榜单读与私有资产隔离用例**必须分开**——公共读断言“全员同一份、有意不带 owner 过滤”，不可套用 profiles/groups 的跨账号不可见断言。
- 验证方式：
  - 无 `board:view` 的登录用户访问榜单 403；有 `board:view` 用户看到同一份公共榜单。
  - 两个不同租户/用户读 `GET /api/scores/top` 得到**同一份**平台公共结果（公共读专项，区别于私有资产跨账号隔离用例）。
  - `board:compute` 与 `board:view` 权限分离测试。
- 完成标准：榜单接口有码；`board.py` 公共归属显式命名+注释、CLAUDE.md 铁律落地；公共读测试与私有隔离测试口径不混用。
- 实际落地情况：待实施。

### 6.5 任务 T4：回测、训练和用户级布局配置接入

- 状态：待开始
- 依赖：T2（不依赖 C1；只消费 T2 已固化的共享资源码和权限依赖）
- 涉及文件/模块：
  - `backend/api/backtest.py`
  - `backend/api/training.py`
  - `backend/api/layout.py`
  - `backend/services/backtest_service.py`
  - `backend/services/training_service.py`
  - `backend/storage/layout_config.py`
- 目标：回测、盘感训练和用户设置抽屉既能按权限控制，又不破坏个人私有隔离。
- 操作：
  - 回测接口挂 `backtest:view/run/robust/delete`。
  - 训练接口挂 `training:view/start/trade/review/delete`。
  - 全站布局共享读接口 `GET /api/layout/presets`、`GET /api/layout/pages/{page_key}`、`GET /api/layout/effective/{page_key}` 挂 `layout:view`，确保不依赖 `/system/layout` 或 system-only 菜单授权。
  - 用户级 layout 配置接口挂 `layout:user-config`。
  - 保留 `layout.py` 已有 userId 忽略前端传值的隔离逻辑。
  - 复核 `reset_layout_config`：`scope=page/preset` 仍 system-only，`scope=user` 可走当前用户资源码。
- 产出：回测、训练、用户偏好接口权限接入。
- 影响范围：`/backtest`、`/training`、所有页面设置抽屉。
- 边界与异常：用户设置抽屉是跨页面基础能力，normal/paid/tenant_admin 默认应具备 `layout:user-config`。
- 验证方式：
  - 跨用户无法读取/删除别人的回测、训练。
  - 非 system 不能重置 page scope 布局。
  - 有 `layout:user-config` 的普通用户可保存自己的页面偏好。
- 完成标准：回测、训练、用户设置抽屉不出现权限遗漏或越权。
- 实际落地情况：待实施。

### 6.6 任务 T5：system-only 路由叠加精确码并保持硬守卫

- 状态：待开始
- 依赖：T2
- 涉及文件/模块：
  - `backend/api/config.py`
  - `backend/api/indicators.py`
  - `backend/api/layout.py`
  - `backend/api/data_admin.py`
  - `backend/api/data_tasks.py`
  - `backend/api/stocks.py`
  - `backend/main.py`
- 目标：数据管理、任务调度、技术指标写、系统配置、布局平台配置全部具备精确资源码，同时继续阻止非 system。
- 操作：
  - 将已有 `Depends(require_system)` 的端点改为 `Depends(require_system_perm("..."))` 或叠加等价组合依赖。
  - 如果某 router 在 `main.py` 整体挂 `require_system`，端点仍补 resource code 依赖，保证扫描可见。
  - `data_admin.py`、`data_tasks.py` 按数据概览、质量修复、采集任务、调度管理、数据源测试、设置保存拆分精确码。
  - `indicators.py` 写操作按 `indicator:def-manage` 接入，读注册表按业务读码处理。
- 产出：system-only 端点精确码接入。
- 影响范围：系统管理员后台能力。
- 边界与异常：绝不把 system-only 菜单改成 `visible='login'`，绝不允许 tenant_admin 通过角色授权获得数据管理能力。
- 验证方式：
  - 复用并扩展 `test_system_route_forbidden_for_tenant_admin`。
  - 对每类 system-only 端点抽样断言 tenant_admin 403、system 非 401/403。
- 完成标准：system-only 端点既有精确码，又不放宽角色边界。
- 实际落地情况：待实施。

### 6.7 任务 T6：前端按钮级权限接入

- 状态：待开始
- 依赖：T2,T3a,T4,T5；BoardView 榜单按钮权限接入依赖 T3b/C1
- 涉及文件/模块：
  - `frontend/src/views/BoardView.vue`
  - `frontend/src/views/ScreenView.vue`
  - `frontend/src/views/BacktestView.vue`
  - `frontend/src/views/TrainingView.vue`
  - `frontend/src/views/StocksView.vue`
  - `frontend/src/views/StockDetailView.vue`
  - `frontend/src/views/ConfigView.vue`
  - `frontend/src/views/data/*.vue`
  - `frontend/src/views/layout/*.vue`
  - `frontend/src/constants/permissions.ts`（如新增）
- 目标：所有触发后端写、任务、敏感操作的按钮与脚本逻辑按阶段四资源码显隐或禁用。
- 操作：
  - 优先使用 `v-permission="'code'"` 控制模板按钮。
  - 脚本逻辑、组合禁用条件和批量操作使用 `hasPermission(auth.role, auth.permissions, code)`。
  - 页面本地导出、纯前端清空条件、导航跳转不单独挂权限，依赖页面可见性。
  - 数据页和布局管理页的 system-only 操作全部加对应码。
  - 对每个页面 action 区、表格操作列和弹窗 footer 做无权限态检查：权限按钮全移除时，整组/整列应按 computed 隐藏或保留稳定的非敏感基础操作，不能留下空白操作列或空工具栏。
  - 保留现有 loading、empty、error、no-perm 行为，不做布局变更。
- 产出：既有页面按钮级权限接入。
- 影响范围：全部存量业务页和系统页操作按钮。
- 边界与异常：如果按钮触发多个 API，使用最严格的写操作码；不能只隐藏按钮而漏掉脚本直接调用路径。
- 验证方式：
  - `cd frontend && npm run build`
  - `cd frontend && npm test -- permission SideMenu` 或项目实际 vitest 命令。
  - 新增关键页面按钮权限单测或轻量组件测试。
- 完成标准：无权用户不可见或不可用对应按钮；直调接口仍由后端 403。
- 实际落地情况：待实施。

### 6.8 任务 T7：菜单、路由守卫和默认落点回归

- 状态：待开始
- 依赖：T2,T6
- 涉及文件/模块：
  - `backend/services/auth_service.py`
  - `frontend/src/router/index.ts`
  - `frontend/src/components/SideMenu.vue`
  - `frontend/src/utils/permission.ts`
  - `backend/storage/pg_ddl.py`
- 目标：资源码变多后，菜单、路由、首个可导航落点仍 fail-closed 且用户体验稳定。
- 操作：
  - 复核 `/me` 返回的 menus/resources 与角色授权一致。
  - normal/paid 默认菜单和资源能进入 `/board`、`/stocks`、`/screen`、`/backtest`、`/training`。
  - 所有登录业务角色强制具备 `layout:view`、`trade-calendar:view`、`indicator:registry`，自定义角色即使未显式授权或在角色页尝试反选，也能加载全站布局、交易日历和指标目录。
  - 角色权限树中 `baseline_locked` 资源始终勾选且不可取消；保存授权后再次读取仍包含基线码。
  - tenant_admin 默认能进入业务页和用户管理页，不可见 system-only 菜单。
  - system 可见全量菜单和全量资源。
- 产出：菜单与路由守卫回归。
- 影响范围：登录后导航、刷新、直达 URL。
- 边界与异常：`/me` 失败时继续 fail-closed，不回退静态全量菜单。
- 验证方式：扩展 `test_rbac_me.py`、`SideMenu.spec.ts`、`utils/permission.spec.ts`、`RoleManageView` 相关权限树测试。
- 完成标准：不同角色菜单和首个落点符合预期；无权直达被导向安全落点。
- 实际落地情况：待实施。

### 6.9 任务 T8：后端权限与隔离测试

- 状态：待开始
- 依赖：T3a,T4,T5,T7；榜单权限和归属样例依赖 T3b/C1
- 涉及文件/模块：
  - `backend/tests/test_stage4_resource_codes.py`（新增）
  - `backend/tests/test_auth_middleware.py`
  - `backend/tests/test_asset_repository.py`
  - `backend/tests/test_backtest.py`
  - `backend/tests/test_training_service.py`
  - `backend/tests/test_stock_group.py`
  - `backend/tests/test_screen_profile_repo.py`
- 目标：用自动化测试证明阶段四“无漏接、无越权、无误伤”。
- 操作：
  - 新增路由扫描：13 个存量模块所有非白名单 API 必须有资源码依赖、`require_system_perm` 或登记过的动态 scope 自守卫端点。
  - 动态 scope 自守卫端点专项测试：`POST /api/layout/reset` 的 user scope 有 `layout:user-config` 可用，page scope 非 system 403、system 通过。
  - 新增权限样例：无权限用户访问业务写接口返回 403；有资源码用户可进入业务层。
  - 新增基线共享读样例：自定义角色未授 `stocks:view` 仍可访问 `GET /api/data/trade-dates`；未授配置页仍可访问 `GET /api/indicators/registry`；未授布局管理仍可访问 `GET /api/layout/presets`、`GET /api/layout/pages/{page_key}`、`GET /api/layout/effective/{page_key}`。
  - 新增基线不可反选样例：角色授权保存时遗漏或移除 `_SHARED_RESOURCE_CODES`，后端仍强制并入，`/me.permissions` 仍包含这些码。
  - 新增 system-only 样例：tenant_admin 访问数据管理、指标写、布局平台配置仍 403。
  - 新增跨账号样例：profile/group/backtest/training/layout user config 不能互读互删。
  - 保留已有默认 deny、Redis fail-closed、安全头和限流测试。
- 产出：阶段四后端回归测试。
- 影响范围：后端全部业务路由和资产隔离。
- 边界与异常：业务层依赖行情数据时，测试可以只断言权限阶段结果，避免要求完整业务数据。
- 验证方式：
  - `./start.sh stop`
  - `python -m pytest backend/tests/test_stage4_resource_codes.py -q`
  - `python -m pytest backend/tests/test_auth_middleware.py backend/tests/test_rbac_deps.py -q`
  - `python -m pytest backend/tests/ -q`
- 完成标准：新增测试和全量后端测试通过。
- 实际落地情况：待实施。

### 6.10 任务 T9：前端权限测试与构建验证

- 状态：待开始
- 依赖：T6,T7
- 涉及文件/模块：
  - `frontend/src/directives/__tests__/permission.spec.ts`
  - `frontend/src/utils/__tests__/permission.spec.ts`
  - `frontend/src/components/__tests__/SideMenu.spec.ts`
  - `frontend/src/views/system/__tests__/*.spec.ts`
  - 可新增 `frontend/src/views/__tests__/stage4-permissions.spec.ts`
- 目标：验证按钮权限、菜单权限和构建产物。
- 操作：
  - 扩展权限工具测试，覆盖新增权限码多码判断和 system 恒过。
  - 扩展角色管理页测试，覆盖 `baseline_locked` 资源勾选置灰、不可反选和保存后仍回显。
  - 对关键页面操作按钮做轻量 mount 测试，至少覆盖数据页、业务页、布局页各一个样板。
  - 确认无权限时按钮被移除或禁用，有权限时渲染。
  - 构建生产产物，满足项目要求。
- 产出：前端权限测试和构建结果。
- 影响范围：前端所有业务页。
- 边界与异常：不做视觉截图验收，因为无布局变化；仅保留现有 layout-contract 回归。
- 验证方式：
  - `cd frontend && npm run build`
  - `cd frontend && npm test`
- 完成标准：前端构建和 Vitest 通过。
- 实际落地情况：待实施。

### 6.11 任务 T10：文档治理和阶段状态回写

- 状态：待开始
- 依赖：T8,T9
- 涉及文件/模块：
  - `agent-works/multi-tenant-rbac/requirement.md`
  - `agent-works/multi-tenant-rbac/stage4-existing-routes/plan.md`
  - `CLAUDE.md`
  - `README.md`
  - `DESIGN.md`（如页面登记无变化则不改）
- 目标：把阶段四实际落地结果、测试结果和后续边界回写到事实源。
- 操作：
  - 更新本计划中任务状态和实际落地情况。
  - 在总需求 §12 标注阶段四完成情况和测试基线。
  - 在 `CLAUDE.md`/`README.md` 补充“存量业务路由已接精确权限码”的稳定规则。
  - 如果没有页面结构变化，明确 `DESIGN.md` 无需新增页面登记。
- 产出：文档治理闭环。
- 影响范围：后续 AI 和开发者对阶段四状态的判断。
- 边界与异常：只沉淀稳定事实，不写临时调试过程。
- 验证方式：文档链接和路径可达；计划映射表状态与任务状态一致。
- 完成标准：阶段四状态、测试基线、剩余范围清晰可追踪。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划

- SQL 文件路径：`agent-works/multi-tenant-rbac/stage4-existing-routes/resource-codes.sql`
- 用途：
  - 人读留痕阶段四新增 `sys_resource` 清单。
  - 既有数据库一次性回填阶段四资源码、基线码和内置角色默认业务授权。
  - 回填默认授权或启用基线码后，同事务 bump 受影响用户 `perm_ver`，让旧 token 失效，避免 Redis perms 缓存继续按旧权限集服务。
  - 与 `backend/storage/pg_ddl.py` seed 互为校验依据。
- 执行时机：
  - 开发期：T2 完成后在测试 PG 上执行或由新增迁移/CLI 包装执行。
  - 上线期：代码部署并完成 PG 备份后执行一次，再启动应用。
- 影响范围：
  - `sys_resource`
  - `sys_role_resource`
  - 权限解析中的 `_SHARED_RESOURCE_CODES` 基线注入
  - 不改资产表结构，不改行情 DuckDB 表。
- 回滚方式或不可回滚原因：
  - 资源码回滚需同步回滚代码中对应 `require_perm`，否则接口会因资源码缺失导致非 system 用户无法授权。
  - SQL 层可删除阶段四资源码，`sys_role_resource` 会随 FK 或显式删除清理，但这属于权限能力回退，不建议单独回滚数据库而不回滚代码。
  - 如执行过 `perm_ver` bump，回滚后用户需重新登录一次以恢复与回滚后权限表一致的 token。
  - 不涉及不可逆数据迁移。

## 8. 测试与验证计划

- 单元测试：
  - 计划：补 `require_perm` 元数据、`require_system_perm`、权限工具函数、资源 seed、`baseline_locked` 和默认授权测试。
  - 具体完成情况：待验证。
- 接口测试：
  - 计划：新增阶段四路由扫描测试；对每类业务接口抽样验证 401/403/允许访问。
  - 具体完成情况：待验证。
- 页面/交互测试：
  - 计划：关键页面按钮权限 mount 测试，覆盖业务页、数据页、布局页；无布局变化，不做新原型截图。
  - 具体完成情况：待验证。
- 权限与数据范围测试：
  - 计划：跨用户/跨租户验证 profiles、stock groups、backtest、training、layout user config 不互通；system-only 端点对 tenant_admin 仍 403。
  - 具体完成情况：待验证。
- 回归测试：
  - 计划：后端 `python -m pytest backend/tests/ -q`；前端 `cd frontend && npm run build && npm test`。
  - 具体完成情况：待验证。
- 异常与边界测试：
  - 计划：无 token 401、无资源码 403、Redis 故障 fail-closed、`/me` 菜单失败 fail-closed、普通用户直达 system-only URL 被守卫拦截。
  - 具体完成情况：待验证。
- 图示与原型一致性验证：本阶段不涉及新增页面或复杂页面改造，不生成原型。验证重点是既有页面布局不变、按钮权限接入后不破坏现有空/加载/错误状态。
- 配置闭环验证：本阶段仅涉及用户级布局偏好已有闭环，验证展示、保存、读取、实际生效、重置和非法 scope 拒绝。注册防滥用开关留阶段五。
- 需求映射验证：以 §5 表为准，确保 R8/R9/R20/R21 均有任务、测试和状态。
- 页面功能点验证：以 §4.5 表为准，确保每个既有页面操作点有资源码、技术实现、任务编号和异常处理。

## 9. 发布与回滚

- 发布前检查：
  - `AI_STOCKS_JWT_SECRET`、PG、Redis 均可用。
  - 先备份 PG 中 `sys_resource`、`sys_role_resource`、`sys_role_menu`、`sys_user_role`。
  - 执行后端和前端全量测试。
  - 确认 `resource-codes.sql` 与 `pg_ddl.py` seed 一致。
- 发布步骤：
  - 停服务：`./start.sh stop`。
  - 应用数据库资源码回填脚本或对应 CLI。该步骤必须在同一 PG 事务内写入默认授权、启用基线码并 bump 受影响用户 `perm_ver`，提交后 best-effort 清 Redis perms 缓存；若无法清缓存，也必须通过 PG `perm_ver` 让旧 token 401 并要求相关用户重新登录。
  - 部署代码。
  - 启动服务：`./start.sh` 或生产脚本。
  - 用 system、tenant_admin、normal 三类账号抽样验证菜单、按钮和接口。
- 配置或环境变量：
  - 沿用阶段二/三已有 `AI_STOCKS_JWT_SECRET`、PG、Redis 配置。
  - 本阶段不新增环境变量。
- 回滚方案：
  - 代码回滚到阶段三版本。
  - 如需数据库回滚，恢复发布前 PG 权限表备份，或删除阶段四新增资源码和授权关系。
  - 若只回滚前端不回滚后端，用户可能能访问页面但接口 403；若只回滚后端不回滚前端，按钮可能隐藏但旧接口缺码。建议代码和权限数据一起回滚。

## 10. 风险、假设与待确认项

### 10.1 风险

- 资源码粒度过细会增加角色授权复杂度，过粗会削弱按钮级控制。T1 必须把同一业务动作归并清楚。
- system-only 端点如果只改成 `require_perm`，会把数据管理/调度/系统配置误授权给非 system。必须使用 `require_system_perm` 或等价硬守卫组合。
- 既有数据库的 non-system 内置角色不会被 `_seed_role_grants()` 自动覆盖。必须用一次性 SQL 或迁移命令补默认业务资源，否则普通用户会有菜单但无按钮/接口权限。
- `_SHARED_RESOURCE_CODES` 如果只做默认授权而不做 `baseline_locked`，自定义角色反选后仍会造成全站布局、交易日历或指标目录 403。必须由后端权限解析和角色授权保存共同保证不可移除。
- `board.py` 仍有默认归属读取，可能导致多用户看到 admin 榜单结果。C1 必须先确认公共/私有口径，随后 T3b 才能修正实现并落测试。
- `score:run` 当前通过 `ScoreSnapshotRepo` 写入调用者归属下的 `score_snapshot/score_snapshot_meta`。如果 C1 确认为平台公共榜单，必须同步确定公共结果生产者和写入归属，避免只改读侧后公共榜单没有生产来源。
- 前端按钮多、页面多，容易漏掉脚本调用路径。T6 后必须靠 T8/T9 扫描和测试兜底。

### 10.2 假设

- 阶段三 RBAC、瘦令牌、`perm_ver` 强制重登、菜单 fail-closed 均保持现状。
- 阶段四默认给 normal/paid/tenant_admin 授予研究业务功能码；system 继续全量。
- 租户管理员默认可用研究业务功能和用户管理，但不可用数据管理、任务调度、系统配置、布局平台配置、菜单/角色/租户/资源管理。
- 当前配置管理单页保持 system-only，普通用户评分规则/买卖指标独立入口留阶段五拆页后开放。
- 行情/参考数据仍为全局共享只读，不做 tenant/owner 过滤。

### 10.3 阻塞确认项（已清零）

| 编号 | 确认项 | 结论（2026-07-04 用户拍板） | 落地方式 |
| --- | --- | --- | --- |
| C1 | 每日榜单结果归属：平台公共榜单，还是每个用户/租户私有榜单；公共则由谁生产 | **✅ 已确认：平台公共榜单特例。** 预设评分方案归 default/admin；`score_result`/`score_snapshot` 按平台公共归属读、全员共享一份；生产者维持调度“评分维护”/CLI 以 default/admin 产出。个人自建方案结果仍纯私有、经 `POST /api/board/compute` 即时看，不进公共榜单。**通用「资产可见性/自助公开」模型（私有/同租户/全体 + 加载=自己+公开）与新用户预设分发不在阶段四，另立独立需求后排。** | 见 T3b（§6.4）：`board.py` 公共归属显式定性 + CLAUDE.md「有意不带归属」铁律 + 公共读专项测试。决议依据 [c1-board-ownership-options.md](c1-board-ownership-options.md) |

> C1 已确认，阶段四无剩余编码前阻塞项，可全量进入 T1–T10。

### 10.4 非阻塞待确认项

| 项 | 默认处理 | 影响 | 确认时机 |
| --- | --- | --- | --- |
| 资源码最终命名 | 以 §4.3 初稿为准，T1 可在不改变边界下微调 | 影响 seed、前端常量和测试 | T1 |
| 前端无权按钮是移除还是禁用 | 沿用 `v-permission` 移除；复杂组合按钮可禁用 | 影响页面交互细节，不影响安全 | T6 |
| 既有库默认授权执行方式 | 优先一份 SQL 留痕 + CLI/手动执行一次 | 影响升级步骤 | T2/发布前 |
