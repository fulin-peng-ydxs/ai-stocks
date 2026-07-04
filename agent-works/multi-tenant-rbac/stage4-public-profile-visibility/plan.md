# 开发计划

## 1. 需求来源与目标

- 需求文档：
  - [../requirement.md](../requirement.md) 中 `R28 资产可见性与自助公开`。
  - [../stage4-existing-routes/c1-board-ownership-options.md](../stage4-existing-routes/c1-board-ownership-options.md) 中 C1 决议：阶段四只做“公共榜单特例”，通用公开方案另立需求。
  - 当前会话确认的偏差修正目标：内置公开方案、他人公开方案、自己的方案都应可获取；使用方案查询指定日期结果时按 `方案 + 日期 + 版本` 查 fresh 快照，缺失或 stale 时按逻辑重新计算。
- 功能目标：在阶段四复审修复基线上，补齐评分方案的通用可见性与自助公开能力，并让每日榜单按统一“可见方案 + 日期 + 版本 + 快照读穿透”语义工作。
- 当前计划状态：**已完成（2026-07-04）**，实现提交 `d8bf27a Agent 更新(阶段四): 公开评分方案与配置拆页`。
- 本次不做：
  - 不把筛选方案、买卖方案、回测记录一并公开化；本分支只覆盖评分方案与每日榜单真实消费链路。
  - 不做公开审批流、运营审核台、付费配额或审计查询页。
  - 不重做阶段四 `PUBLIC_BOARD_OWNER` 公共榜单生产修复；只做兼容迁移和语义统一。
  - 不新增独立评分菜单或全新页面；配置管理四子页已前移落地，并复用现有 ConfigView 单 tab 模式。
- 计划输出目录：`agent-works/multi-tenant-rbac/stage4-public-profile-visibility/`

## 2. 当前项目依据

- 需求依据：
  - `R28` 明确资产可见性为 `private / tenant / public`，读侧从“仅本人”放宽为“本人 ∪ 公开 [∪ 同租户]”，并要求明确 publish 权限、只读引用、公开方案快照归属和新用户默认可见预设。
  - 阶段四 C1 已将每日榜单收敛为 `PUBLIC_BOARD_OWNER` 平台公共只读特例，当前分支要把它纳入通用可见方案模型，而不是继续扩大特例。
- 后端数据结构：
  - [backend/storage/pg_ddl.py](../../../backend/storage/pg_ddl.py) 中 `score_profile` 已补 `visibility/published_at/published_by`，用于表达 `private/tenant/public` 可见性。
  - `score_snapshot` 与 `score_snapshot_meta` 主键已包含 `tenant_id + owner_user_id + trade_date + profile_id + profile_version`，具备按方案 owner 共享快照的结构基础。
  - `PUBLIC_BOARD_OWNER` 当前作为平台公共预设和公共快照 owner，写在 [backend/storage/pg_ddl.py](../../../backend/storage/pg_ddl.py) 与 [CLAUDE.md](../../../CLAUDE.md)。
- 后端业务逻辑：
  - [backend/scoring/score_profile.py](../../../backend/scoring/score_profile.py) 已区分 owner 写语义和 visible 读语义；读侧可见自己的、租户公开、全体公开和平台内置预设。
  - [backend/api/score_profiles.py](../../../backend/api/score_profiles.py) 的 `/score-profiles*` 列表/详情走 visible 语义，保存/删除保持 owner-only；`/score-profiles/run` 对可见已保存方案按真实 owner 槽读写快照。
  - [backend/scoring/snapshot.py](../../../backend/scoring/snapshot.py) 同时存在 `get_board()` 读穿透物化和 `get_board_cached()` 只读 fresh 快照两种语义。
  - [backend/api/board.py](../../../backend/api/board.py) 的 `/board/profiles` 只列 `PUBLIC_BOARD_OWNER` 下 `is_preset=true`，`/board/run` 只读平台公共 fresh 快照，不触发物化。
  - [backend/services/public_board.py](../../../backend/services/public_board.py) 只生产 `PUBLIC_BOARD_OWNER` 公共预设快照。
- 权限与菜单：
  - [backend/auth/constants.py](../../../backend/auth/constants.py) 中 `BUSINESS_RESOURCE_CODES` 默认给业务角色 `board:view/board:compute/score:run/score-profile:*/trade-profile:*` 等业务授权码。
  - [backend/storage/pg_ddl.py](../../../backend/storage/pg_ddl.py) 已前移阶段五配置管理拆页：`/system/config` 为 login 可见父菜单，`/system/config/score` 评分规则和 `/system/config/trade` 买卖指标为业务可授权子页，`/system/config/tech` 技术指标和 `/system/config/system` 系统设置仍 system-only。
  - 前端路由由后端菜单授权 fail-closed 控制，[frontend/src/router/index.ts](../../../frontend/src/router/index.ts) 不能靠静态菜单兜底暴露新入口。
- 前端页面与 API：
  - [frontend/src/api/scoreProfile.ts](../../../frontend/src/api/scoreProfile.ts) 与 [frontend/src/api/board.ts](../../../frontend/src/api/board.ts) 已使用 opaque `profile_ref` 和 `visibility/source/readonly` 字段定位跨 owner 可见方案。
  - [frontend/src/views/BoardView.vue](../../../frontend/src/views/BoardView.vue) 的方案下拉消费可见方案，文案改为公共/可见方案口径。
  - [frontend/src/views/ConfigView.vue](../../../frontend/src/views/ConfigView.vue) 复用原配置页能力，以 `/system/config/score|trade|tech|system` 单 tab 路由承载拆页。
- 页面设计依据：
  - [DESIGN.md](../../../DESIGN.md) 要求业务页面走 `LayoutHost`、页面声明来自 `pageRegistry`，表格体内滚，说明性文字收进 `HelpTip/HelpHint`，按钮文字不得溢出。
  - 本需求没有 HTML 原型引用；新增评分方案入口若需要页面，必须复用现有 `ConfigView` 评分 tab 布局，不另行发散新视觉。
- 当前验证基线：
  - Stage4 修复提交 `cc9862a` 前已跑后端专项 27 passed、前端 build 通过、前端权限相关测试 86 passed；该基线作为本分支回归入口。

## 3. 实施范围

### 3.1 必须实现

- 给评分方案建立 `visibility` 模型，并兼容历史数据和平台预设。
- 提供可见方案读取能力：自己的方案、同租户公开方案、全体公开方案、平台内置预设。
- 公开方案只读引用：非 owner 不可编辑、删除或覆盖他人方案。
- 提供评分方案发布/取消发布能力，按资源码控制公开范围。
- 为可见方案定义稳定 `profile_ref`，解决跨 owner 同名 `profile_id` 歧义。
- 每日榜单改为消费可见方案列表，`/board/run` 按 `profile_ref + run_date + version` 查询或受控读穿透物化。
- 缺失或 stale 快照时，按用户确认的原始逻辑重新计算；计算写入方案 owner 的快照槽，并限制为“可见方案当前版本 + 指定日期”的幂等缓存物化。
- 保留 `PUBLIC_BOARD_OWNER` 平台公共预设兼容，不破坏 `debug_board_only` 只授 `/board + board:view` 的可用性。
- 补后端、前端、权限、数据范围和回归测试。

### 3.2 可选增强

- 给榜单页展示“已缓存 / 已重新计算 / 生产中”轻量状态。
- CLI 支持按 `profile_ref` 或 `visibility` 批量生产公开方案快照。
- 在数据总览中增加公开方案覆盖统计，而不仅展示平台公共预设最新日。

### 3.3 暂不实现

- 不扩展筛选方案、买卖方案和回测记录的公开能力。
- 不做公开审批流、公开市场、搜索广场、收藏、评分或运营推荐。
- 不引入新的外部依赖或独立队列系统；读穿透计算先复用现有同步评分与 PG 锁/事务能力。
- 不改变行情、指标定义、数据管理等 system-only 平台边界。

## 4. 技术方案

### 4.1 总体实现思路

本分支把“平台公共榜单特例”收敛到“可见评分方案”模型内：

- 方案目录层：`ScoreProfileRepo` 新增 visible 查询，返回 owner、自身/公开来源、只读状态和稳定 `profile_ref`。
- 方案管理层：owner-only 保存/删除保持不变，publish/unpublish 单独走权限码；非 owner 公开方案只能复制为自己的方案。
- 榜单读取层：`/board/profiles` 返回可用于榜单的可见方案摘要；`/board/run` 用 `profile_ref` 定位真实 owner，读取或受控物化该 owner 槽下的 `score_snapshot`。
- 快照归属：公开方案的快照写方案 owner 槽。这样同一公开方案、同一日期、同一版本只有一份结果，所有可见用户共享。
- 读穿透计算：`board:view` 允许对“自己可见的方案当前版本”触发缺失/stale 快照的幂等物化；`board:compute` 保留为强制刷新、回测查看和批量生产入口。该行为是缓存物化，不允许修改方案内容或写调用者个人资产。
- 并发控制：物化时以 `tenant_id/owner_user_id/profile_id/version/trade_date` 建 PG advisory lock 或等价锁，避免多用户同时打开同一公开方案导致重复删除重写。

### 4.2 数据结构与兼容策略

- `score_profile` 增加：
  - `visibility TEXT NOT NULL DEFAULT 'private'`，合法值 `private | tenant | public`。
  - `published_at TIMESTAMP NULL`。
  - `published_by TEXT NULL`。
- 历史数据兼容：
  - `is_preset=true` 且 owner 为 `PUBLIC_BOARD_OWNER` 的方案初始化为 `visibility='public'`。
  - 其他历史方案初始化为 `visibility='private'`。
- `score_profile_version` 暂不增加 visibility 字段，版本历史记录方案内容；当前可见性以 `score_profile` 当前行控制。
- 索引建议：
  - `(visibility, tenant_id, owner_user_id)` 用于 visible list。
  - `(tenant_id, owner_user_id, id, version)` 已由主键覆盖方案定位。

### 4.3 方案引用契约

为避免前端只传 `profile_id` 导致跨 owner 同名冲突，所有可见方案列表返回 `profile_ref`：

- `profile_ref` 是后端生成的 URL-safe opaque token，内容包含 `tenant_id/owner_user_id/profile_id`，前端只透传不解析。
- 后端解析后必须再次校验当前用户是否可见该方案，不能信任前端传来的 owner 信息。
- `profile_id` 继续保留给展示和旧接口兼容；新增接口优先使用 `profile_ref`。

### 4.4 权限策略

新增或调整资源码：

- `score-profile:view`：查看自己的方案和可见公开方案。需从 `/system/config` system-only 锚迁出，变为可授权业务码。
- `score-profile:save`：保存自己的方案。
- `score-profile:delete`：删除自己的方案。
- `score-profile:publish-tenant`：把自己的方案公开到本租户，默认给 `tenant_admin` 和 `system`，普通用户可由角色授权。
- `score-profile:publish-public`：把自己的方案公开到全体，默认只给 `system`。
- `board:view`：查看榜单并允许对可见方案执行缺失/stale 的受控缓存物化。
- `board:compute`：强制刷新、批量生产或未来异步生产入口。

非 owner 限制：

- 非 owner 对公开方案详情可读，保存/删除/publish 返回 403。
- 非 owner 可以“复制为我的方案”，写入自己的 owner 槽，version 从 1 开始。

### 4.5 API 契约

- `GET /api/score-profiles`
  - 返回可见方案列表。
  - 每项含 `profile_ref/id/name/version/is_preset/visibility/source/readonly/owner_label`。
- `GET /api/score-profiles/{profile_ref}`
  - 支持新 `profile_ref`；兼容旧 `id` 时仅查当前 owner。
  - 非 owner 公开方案可读，返回 `readonly=true`。
- `POST /api/score-profiles`
  - 只保存当前用户自己的方案；不能覆盖他人公开方案。
- `DELETE /api/score-profiles/{profile_ref}`
  - 仅 owner 可删。
- `POST /api/score-profiles/{profile_ref}/visibility`
  - body: `{ visibility: "private" | "tenant" | "public" }`。
  - `tenant/public` 分别校验 publish 资源码；`private` 仅 owner 可执行。
- `POST /api/score-profiles/{profile_ref}/copy`
  - 把可见方案复制成当前用户私有方案。
- `GET /api/board/profiles`
  - 返回可用于榜单的可见方案摘要，复用 `profile_ref`。
- `POST /api/board/run`
  - body: `{ profile_ref, run_date?, top?, force? }`。
  - `run_date` 缺省时取行情最新交易日；如果该日期快照缺失或 stale，按读穿透规则物化。
  - `force=true` 必须有 `board:compute`，否则只能在缺失/stale 时物化。

### 4.6 页面 P1 技术实现：每日榜单

- 原型文件：需求未提供新原型。本次是更新既有 [frontend/src/views/BoardView.vue](../../../frontend/src/views/BoardView.vue)，保留 `LayoutHost` list 页面结构，替代布局依据为 `DESIGN.md §5/§9` 与现有 BoardView。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 可见方案下拉 | R28-1/R28-2 | 展示内置公开、他人公开、自己的方案 | `listBoardProfiles()` 返回 `profile_ref/source/readonly`，下拉用 tag 标识“我的/租户/公开/内置” | `BoardView.vue`、`frontend/src/api/board.ts` | `GET /api/board/profiles` | 无方案显示空态；无权限 403 走现有错误态 | T5,T8 |
| 按方案日期查询榜单 | R28-5 | 按方案、日期、版本查结果 | `runBoardProfile()` 改传 `profile_ref`，返回 `run_date/version/cache_status` | `BoardView.vue`、`SubScoreBars` | `POST /api/board/run` | 缺行情或计算失败给明确错误；loading 不阻塞导出状态 | T5,T8 |
| 缺失/stale 自动重算 | R28-5/R28-6 | 没有 fresh 快照时重新计算 | 后端读穿透物化，前端展示“正在计算/已更新”短状态 | `BoardView.vue` | `POST /api/board/run` | 并发锁等待或重复请求需幂等；超时提示重试 | T5,T8,T11 |
| 平台预设兼容 | R28-7 | 原公共榜单角色继续可用 | `PUBLIC_BOARD_OWNER` 预设作为 `source=preset` 的 public 方案 | `BoardView.vue`、`public_board.py` | `GET /api/board/profiles` | `debug_board_only` 仍不需要 `score-profile:*` | T5,T11 |

### 4.7 页面 P2 技术实现：评分方案管理

- 原型文件：需求未提供新原型。本次不设计全新复杂页面，抽取并复用 [frontend/src/views/ConfigView.vue](../../../frontend/src/views/ConfigView.vue) 的评分规则 tab 作为评分方案管理区；如开发发现必须重排大布局，应先补充需求或原型后再继续。

| 页面功能点 | 对应需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 可见方案列表 | R28-1/R28-2 | 自己和公开方案都可见 | 抽 `ScoreProfilePanel`，列表显示 `source/visibility/readonly` | `ConfigView.vue`、新增/抽取 `ScoreProfilePanel.vue` | `GET /api/score-profiles` | 无方案时提示可新建；公开只读方案不可编辑保存 | T4,T7,T9 |
| 公开/取消公开 | R28-3/R28-4 | owner 可按权限公开到租户/全体或收回私有 | 按 `score-profile:publish-*` 显示操作；保存后刷新列表和权限状态 | `ScoreProfilePanel.vue`、`v-permission` | `POST /api/score-profiles/{ref}/visibility` | 无权限按钮不显示；直调 403；公开失败保留原状态 | T2,T4,T9 |
| 复制为我的方案 | R28-4 | 他人公开方案只读但可复制 | 新增“复制为我的方案”按钮，写当前 owner 私有方案 | `ScoreProfilePanel.vue` | `POST /api/score-profiles/{ref}/copy` | 同名冲突提示改名；成功后切到我的副本 | T4,T7,T9 |
| 非 owner 只读 | R28-4 | 公开资产不能被他人改删 | 编辑区禁用保存/删除；可查看规则和历史当前版本 | `ScoreProfilePanel.vue` | `GET /api/score-profiles/{ref}` | 只读态用 tag/HelpTip 说明，不遮挡主要操作 | T4,T9 |
| 业务入口 | R28-3 | 普通授权用户能维护自己的评分方案 | 前移阶段五配置管理拆页：系统管理 → 配置管理 → 评分规则 | `pg_ddl.py` menu seed、`router/index.ts` | `/system/config/score` | 未授权不出菜单，直达由路由守卫拦截 | T2,T9 |

## 5. 需求与开发内容映射和开发状态

> R28 子项由本计划按 `requirement.md` 中 R28 文义拆分，用于开发追踪，不改变总需求编号含义。

| 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| R28-1 | 用户资产增加可见性维度 `private / tenant / public` | `score_profile` 增字段、迁移、校验、seed 兼容 | T1,T2 | 已完成 | 一致 | 本分支先做评分方案 |
| R28-2 | 读侧从“仅本人”放宽为“本人 ∪ 公开 [∪ 同租户]” | `ScoreProfileRepo.list_visible/get_visible`、visible API、Board profiles | T3,T4,T5 | 已完成 | 一致 | 后端二次校验可见性 |
| R28-3 | 用户可自助公开自己的方案，公开范围受权限控制 | publish/unpublish API、资源码、前端按钮 | T2,T4,T9 | 已完成 | 一致 | 全体公开默认 system，租户公开按角色授权 |
| R28-4 | 公开资产默认只读引用，不能被他人改删 | readonly 字段、保存/删除 owner 校验、复制为我的方案 | T3,T4,T9,T11 | 已完成 | 一致 | 非 owner 只读，允许复制 |
| R28-5 | 公开方案快照归属明确 | 快照写方案 owner 槽，`profile_ref` 定位 owner | T3,T5,T6 | 已完成 | 一致 | 避免按 viewer 重复计算 |
| R28-6 | 查询方案日期结果时 fresh 返回，缺失/stale 重算 | `/board/run` 读穿透物化、并发锁、cache 状态 | T5,T6,T11 | 已完成 | 基本一致 | 已实现读穿透与 cache 状态；PG advisory lock 未单独落地 |
| R28-7 | 新用户默认可见公开预设 | 平台预设作为 `visibility=public/source=preset` 纳入 visible list | T1,T3,T5,T11 | 已完成 | 一致 | 不做复制分发，只做可见引用 |
| R20/R21 延续 | 前端权限渲染和存量榜单页权限闭环不退化 | 菜单 seed、路由、v-permission、阶段四测试回归 | T2,T7,T8,T11 | 已完成 | 一致 | 保持 Stage4 `debug_board_only` 可用 |

## 6. 详细实施步骤与进度追踪

### 6.1 任务 T1：需求与现状校准

- 状态：已完成
- 依赖：无
- 涉及文件/模块：
  - `agent-works/multi-tenant-rbac/requirement.md`
  - `agent-works/multi-tenant-rbac/stage4-existing-routes/plan.md`
  - `backend/api/board.py`
  - `backend/api/score_profiles.py`
  - `backend/scoring/score_profile.py`
  - `frontend/src/views/BoardView.vue`
  - `frontend/src/views/ConfigView.vue`
- 目标：确认本分支是在 Stage4 修复基线之上补 R28 评分方案可见性，不继续扩大公共榜单特例。
- 操作：
  - 读取 R28、C1 决议、当前 Stage4 计划和关键代码。
  - 识别当前偏差：`score_profile` owner-only、`/board` 只读平台预设、`profile_id` 跨 owner 歧义、普通用户无评分方案管理入口。
- 产出：本计划的当前项目依据与需求映射。
- 影响范围：仅文档计划。
- 边界与异常：未连接数据库实查现有数据；以 DDL、代码和测试为事实源。
- 验证方式：计划中 §2、§5 能回溯到需求和代码路径。
- 完成标准：不存在未映射的本次必须需求项。
- 实际落地情况：已完成；已按 `$auto-plan-dev` 重新生成计划结构。

### 6.2 任务 T2：数据库结构、SQL 与资源码规划

- 状态：已完成
- 依赖：T1
- 涉及文件/模块：
  - `backend/storage/pg_ddl.py`
  - `backend/auth/constants.py`
  - `agent-works/multi-tenant-rbac/stage4-public-profile-visibility/score-profile-visibility.sql`
  - `agent-works/multi-tenant-rbac/stage4-public-profile-visibility/resource-codes.sql`
- 目标：让新装库和既有库都具备评分方案可见性字段、权限码和菜单入口。
- 操作：
  - 在 DDL 中给 `score_profile` 增加 `visibility/published_at/published_by`。
  - 在 `init_pg_db()` 中用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 兼容既有库。
  - 追加合法值约束或在仓库层做强校验。
  - 添加索引 SQL。
  - 新增 `score-profile:publish-tenant`、`score-profile:publish-public`，并将 `score-profile:view/save/delete` 从 system-only 锚迁为可授权业务码或新增业务锚。
  - 给业务用户新增评分方案管理菜单入口，保持 system 仍全量。
  - 写人读 SQL 留痕，说明执行时机和回滚。
- 产出：DDL 改动、SQL 留痕、资源码/菜单 seed 计划落地。
- 影响范围：PG `score_profile`、`sys_resource`、`sys_menu`、`sys_role_resource`、`perm_ver`。
- 边界与异常：既有 `is_preset=true` 平台方案必须初始化为 `public`，其他历史方案必须为 `private`。
- 验证方式：
  - 新增/更新 PG DDL 测试。
  - 查询 `information_schema.columns` 确认字段存在。
  - 资源码扫描测试确认新增端点有码。
- 完成标准：新装和既有库启动后字段、资源码、菜单入口一致。
- 实际落地情况：已完成；`score_profile` 增加 `visibility/published_at/published_by`，`init_pg_db()` 幂等补列和回填平台预设 public，配置管理拆为 `/system/config/score|trade|tech|system`，publish 资源码和 SQL 留痕已同步。

### 6.3 任务 T3：方案引用与可见性仓库能力

- 状态：已完成
- 依赖：T2
- 涉及文件/模块：
  - `backend/scoring/score_profile.py`
  - `backend/auth/context.py`
  - `backend/tests/test_score_profile_visibility.py`（新增）
- 目标：在仓库层建立 owner-only 与 visible 两套清晰语义。
- 操作：
  - 新增 `ProfileRef` 编解码 helper，生成 opaque `profile_ref`。
  - 新增 `list_visible()`：返回 own、tenant public、global public、platform preset。
  - 新增 `get_visible(profile_ref)`：解析后校验可见性并返回 profile + owner 信息 + readonly/source。
  - 保留 `list/get/save/delete` owner-only 语义，供编辑写操作使用。
  - 新增 `set_visibility()`，校验 owner、visibility 合法值和权限调用方传入。
  - 新增 `copy_visible_to_owner()`。
- 产出：评分方案可见性核心仓库能力。
- 影响范围：评分方案列表、详情、保存、删除、发布、复制。
- 边界与异常：
  - 非 owner 不得通过 visible profile 执行 save/delete。
  - `profile_ref` 无效、跨租户 tenant-only、不可见 private 均返回 404 或 403，口径需在 API 层统一。
- 验证方式：
  - owner 可见自己的 private。
  - 同租户可见 tenant，不同租户不可见。
  - 所有人可见 public。
  - 平台预设可见且 source 为 preset。
  - 非 owner 保存/删除被拒。
- 完成标准：仓库测试覆盖所有可见性组合和 owner 写边界。
- 实际落地情况：已完成；`ScoreProfileRepo` 保留 owner-only 方法，新增 `profile_ref` 编解码、`list_visible/get_visible/set_visibility/copy_visible/versions_visible`。

### 6.4 任务 T4：评分方案 API 与权限接入

- 状态：已完成
- 依赖：T2,T3
- 涉及文件/模块：
  - `backend/api/score_profiles.py`
  - `backend/auth/deps.py`
  - `backend/tests/test_score_profiles_api_visibility.py`（新增或扩展）
- 目标：让前端和第三方 API 能安全获取、发布、复制可见评分方案。
- 操作：
  - 调整 `GET /score-profiles` 为 visible list。
  - 调整详情/版本接口支持 `profile_ref`，旧 `id` 仅兼容当前 owner。
  - 保存/删除强制 owner-only。
  - 新增 `POST /score-profiles/{profile_ref}/visibility`。
  - 新增 `POST /score-profiles/{profile_ref}/copy`。
  - API 返回 `readonly/source/visibility/owner_label/profile_ref`。
  - 参数错误返回 400，不可见返回 404，无权限返回 403。
- 产出：评分方案通用公开 API。
- 影响范围：配置页、未来评分方案管理页、榜单方案目录。
- 边界与异常：公开到全体必须具备 `score-profile:publish-public`；公开到租户必须具备 `score-profile:publish-tenant`。
- 验证方式：
  - 多用户多租户 API 测试。
  - 无 publish 权限直调返回 403。
  - 非 owner 删除公开方案返回 403。
- 完成标准：API 权限与仓库可见性一致。
- 实际落地情况：已完成；`/score-profiles` 列表/详情/版本走 visible 语义，保存/删除保持 owner-only，新增 visibility 和 copy 接口。

### 6.5 任务 T5：榜单可见方案目录

- 状态：已完成
- 依赖：T3,T4
- 涉及文件/模块：
  - `backend/api/board.py`
  - `backend/services/public_board.py`
  - `frontend/src/api/board.ts`
  - `backend/tests/test_stage4_board.py`
- 目标：让榜单页方案目录从平台预设特例升级为通用可见方案。
- 操作：
  - `/board/profiles` 改用 `ScoreProfileRepo.list_visible()`，但只返回榜单需要的摘要字段。
  - 平台 `PUBLIC_BOARD_OWNER` 预设返回 `source=preset/visibility=public/readonly=true`。
  - 保留旧 `profile_id` 字段展示，新增必传 `profile_ref`。
  - 更新 `list_public_board_profiles()` 命名或保留兼容 wrapper，避免服务语义漂移。
- 产出：榜单页可见方案目录 API。
- 影响范围：每日榜单加载、普通用户首页、公共预设兼容。
- 边界与异常：如果用户没有任何可见方案，返回空列表，不 403。
- 验证方式：普通用户、租户管理员、system、多租户用户分别拉取目录。
- 完成标准：内置预设、自己的 private、同租户公开、全体公开按预期出现或隐藏。
- 实际落地情况：已完成；`/board/profiles` 返回可见评分方案摘要，平台预设作为 `source=preset/visibility=public` 兼容。

### 6.6 任务 T6：榜单读穿透物化与快照归属

- 状态：已完成
- 依赖：T3,T5
- 涉及文件/模块：
  - `backend/api/board.py`
  - `backend/scoring/snapshot.py`
  - `backend/services/public_board.py`
  - `backend/tests/test_stage4_board.py`
  - `backend/tests/test_score_profile_visibility.py`
- 目标：实现用户确认的“fresh 返回，缺失/stale 重算”语义，同时保证公开方案快照写入方案 owner 槽。
- 操作：
  - `/board/run` 改收 `profile_ref`，定位方案 owner。
  - 默认日期取行情最新交易日；显式 `run_date` 按指定日期。
  - fresh 时读取 owner 槽快照。
  - 缺失/stale 时获取 PG 锁后调用 `ScoreSnapshotRepo(...owner...).get_board()` 物化。
  - 返回 `cache_status`：`fresh | materialized | refreshed | empty`。
  - `force=true` 要求 `board:compute`，否则 fresh 不重算。
  - 保留旧 `{profile_id}` 请求的兼容逻辑：仅匹配 `PUBLIC_BOARD_OWNER` 预设或当前 owner，后续前端统一迁移到 `profile_ref`。
- 产出：统一榜单运行链路。
- 影响范围：`score_snapshot/score_snapshot_meta` 写入归属、榜单性能、并发写。
- 边界与异常：
  - 只允许对当前用户可见方案物化，private 他人方案不可借由 `profile_ref` 计算。
  - 物化失败不能删除已有 fresh 结果；先算后替换或保证事务顺序。
  - 大盘无行情数据返回空态，不写脏 meta。
- 验证方式：
  - fresh 命中不重算。
  - stale 后 `board:view` 触发物化并返回新结果。
  - 两个用户读同一 public 方案得到同一 owner 槽结果。
  - 非可见方案 404/403。
  - `force=true` 无 `board:compute` 返回 403。
- 完成标准：榜单页不再因为最新行情日未预生产而空榜，且不写调用者个人槽污染公开方案。
- 实际落地情况：已完成；`/board/run` 支持 `profile_ref`，默认日期取行情最新日，fresh 直接返回，缺失/stale 物化到方案 owner 槽，`force=true` 要求 `board:compute`。未单独实现 PG advisory lock。

### 6.7 任务 T7：生产任务与 CLI 语义统一

- 状态：后续增强
- 依赖：T3,T6
- 涉及文件/模块：
  - `backend/services/public_board.py`
  - `backend/services/async_task.py`
  - `backend/cli.py`
  - `backend/api/data_admin.py`
  - `backend/tests/test_data_mgmt_c.py`
- 目标：把公共预设生产任务升级为可见公开方案生产任务，同时保留数据总览清晰口径。
- 操作：
  - 将 `produce_public_board_snapshots()` 扩展为支持 `visibility=public` 或指定 `profile_ref`。
  - `public-board` CLI 支持 `--profile-ref`、`--visibility public|preset`。
  - 评分维护任务默认至少生产平台预设；是否生产全部 public 方案通过参数控制，避免公开方案过多拖慢维护任务。
  - 数据总览继续展示平台预设最新日；可选增加 public 方案覆盖摘要。
- 产出：生产任务与读穿透链路一致。
- 影响范围：任务中心、CLI、数据总览文案。
- 边界与异常：生产任务必须跳过不可见/已删除/非当前版本方案。
- 验证方式：CLI help、任务 handler 单测、stale 后生产恢复测试。
- 完成标准：手动任务和榜单读穿透写入同一 owner 槽，结果一致。
- 实际落地情况：未扩展；本轮保留既有 `public-board` 平台预设生产链路，公开方案依赖 `/board/run` 读穿透恢复 fresh 快照。

### 6.8 任务 T8：前端 API 类型与榜单页接入

- 状态：已完成
- 依赖：T4,T5,T6
- 涉及文件/模块：
  - `frontend/src/api/scoreProfile.ts`
  - `frontend/src/api/board.ts`
  - `frontend/src/views/BoardView.vue`
  - `frontend/src/views/__tests__/stage4-permissions.spec.ts`
- 目标：让榜单页消费可见方案和读穿透结果。
- 操作：
  - 扩展 `ScoreProfileSummary/Profile` 类型。
  - `runBoardProfile()` 改传 `profile_ref`。
  - 下拉展示 `source/visibility` tag。
  - HelpTip 文案从“平台公共预设”改为“可见评分方案：我的/租户/公开/内置”。
  - 展示 `cache_status` 的轻量状态，不新增大面积说明文字。
  - 保持表格列、导出、TopN、日期选择器行为不变。
- 产出：可见方案榜单页。
- 影响范围：`/board` 首页。
- 边界与异常：旧 localStorage 若只存 `profile_id`，加载时应回退到列表第一项，不直传旧 id 导致 404。
- 验证方式：Vitest mount/harness 覆盖有方案、无方案、materialized 状态、403 错误态。
- 完成标准：普通用户、仅榜单角色、system 均可按权限看到正确方案列表。
- 实际落地情况：已完成；前端 API 类型支持 `profile_ref/visibility/source/readonly/cache_status`，BoardView 改用可见方案下拉和读穿透状态。

### 6.9 任务 T9：评分方案管理入口与发布 UI

- 状态：已完成
- 依赖：T2,T4
- 涉及文件/模块：
  - `frontend/src/views/ConfigView.vue`
  - `frontend/src/views/ScoreProfilesView.vue`（可新增，复用抽取组件）
  - `frontend/src/router/index.ts`
  - `frontend/src/layout/pageRegistry.ts`
  - `backend/storage/pg_ddl.py`
  - `frontend/src/views/__tests__/score-profile-visibility.spec.ts`（新增）
- 目标：让被授权用户能维护自己的评分方案并发布/取消发布。
- 操作：
  - 从 `ConfigView.vue` 评分 tab 抽出 `ScoreProfilePanel`，避免两套评分规则编辑逻辑。
  - 前移阶段五配置管理拆页，新增 `/system/config/score` 评分规则子页。
  - 页面继续走 `LayoutHost`，采用现有评分 tab 的 workbench 布局。
  - 列表增加 `visibility/source/readonly` 展示。
  - owner 方案显示发布/取消发布；非 owner 公开方案禁用保存/删除，显示复制按钮。
  - `v-permission` 控制保存、删除、发布到租户、发布到全体。
- 产出：评分方案自助公开 UI。
- 影响范围：配置管理评分 tab、菜单授权、路由守卫。
- 边界与异常：
  - 不开放技术指标、系统设置、买卖方案给普通用户。
  - 新页面如果复用评分 tab 后仍出现复杂布局歧义，应暂停并补原型。
- 验证方式：
  - 无权限用户不见菜单，直达被守卫重定向。
  - 有 `score-profile:view` 可进页面。
  - 无 publish 权限不可选择对应公开范围。
  - 非 owner 公开方案只读，复制后成为自己的 private。
- 完成标准：R28 自助公开链路有可操作 UI，不依赖 system-only ConfigView。
- 实际落地情况：已完成；新增 `系统管理 → 配置管理 → 评分规则` 子页，复用 ConfigView 的单 tab 模式，公开方案只读，支持复制；公开范围通过当前状态标签下拉设置（私有/租户公开/全体公开），不再平铺两个公开按钮；买卖指标同步拆到 `/system/config/trade`。

### 6.10 任务 T10：资源码、菜单与文档事实源同步

- 状态：已完成
- 依赖：T2,T4,T9
- 涉及文件/模块：
  - `CLAUDE.md`
  - `agent-works/multi-tenant-rbac/requirement.md`
  - `agent-works/multi-tenant-rbac/stage4-existing-routes/resource-codes.sql`
  - `agent-works/multi-tenant-rbac/stage4-public-profile-visibility/plan.md`
  - `DESIGN.md`（如新增页面登记需要）
- 目标：防止后续 AI 继续按“榜单只读平台预设特例”或“score-profile 仍 system-only”旧事实开发。
- 操作：
  - 更新 CLAUDE.md 的资产可见性和榜单语义。
  - 在总需求 R28 或阶段状态处登记本分支落地范围。
  - 更新资源码 SQL 留痕。
  - 如新增评分方案页面，同步 DESIGN §9 页面登记和 pageRegistry 测试契约。
- 产出：AI 约束和计划文档同步。
- 影响范围：后续开发者与 AI 事实源。
- 边界与异常：只写稳定规则，不写临时调试过程。
- 验证方式：`rg` 检查旧“只读平台预设/score-profile system-only”表述是否仍误导。
- 完成标准：文档与代码语义一致。
- 实际落地情况：已完成；`CLAUDE.md` 增加 R28 当前事实覆盖，SQL 留痕与 seed 同步到配置管理拆页。

### 6.11 任务 T11：测试、构建与浏览器验证

- 状态：已完成（浏览器抽样未执行）
- 依赖：T3,T4,T5,T6,T7,T8,T9,T10
- 涉及文件/模块：
  - `backend/tests/`
  - `frontend/src/**/__tests__/`
  - `frontend/dist`
- 目标：证明公开方案能力不破坏 Stage4 权限基线。
- 操作：
  - 后端新增评分方案可见性、API 权限、榜单物化、生产任务测试。
  - 前端新增榜单页与评分方案页权限/只读态测试。
  - 跑 Stage4 专项回归。
  - 修改 `frontend/src` 后执行 `npm run build`。
  - 用 `debug_board_only`、普通用户、租户管理员、system 做浏览器抽样验证。
- 产出：可复现验证结果。
- 影响范围：后端、前端、权限、菜单、构建产物。
- 边界与异常：浏览器验证使用 5181 专用端口，不抢 5173。
- 验证方式：
  - `python -m pytest backend/tests/test_score_profile_visibility.py backend/tests/test_score_profiles_api_visibility.py backend/tests/test_stage4_board.py -q`
  - `python -m pytest backend/tests/test_stage4_resource_codes.py backend/tests/test_stage4_menu_guard.py -q`
  - `cd frontend && npm run build`
  - `cd frontend && npm test -- src/views/__tests__/score-profile-visibility.spec.ts src/views/__tests__/stage4-permissions.spec.ts src/directives/__tests__/stage4-button-permission.spec.ts src/utils/__tests__/permission.spec.ts`
- 完成标准：测试通过，浏览器无 403/控制台错误，公开方案读写和榜单物化符合验收。
- 实际落地情况：已完成后端专项、前端构建和前端权限/布局测试；本轮未启动 5181 做浏览器抽样。

## 7. 数据库与 SQL 计划

- SQL 文件路径：
  - `agent-works/multi-tenant-rbac/stage4-public-profile-visibility/score-profile-visibility.sql`
  - `agent-works/multi-tenant-rbac/stage4-public-profile-visibility/resource-codes.sql`
- 用途：
  - `score-profile-visibility.sql`：既有库增加 `score_profile.visibility/published_at/published_by`、索引、历史数据初始化。
  - `resource-codes.sql`：新增 publish 权限码、评分方案业务菜单/资源默认授权、必要的 `perm_ver` bump。
- 执行时机：
  - 开发期由 DDL 幂等逻辑自动建字段，SQL 作为人读留痕和既有库校验脚本。
  - 上线时先备份 PG 权限表和 `score_profile`，再执行 SQL 或等价迁移 CLI。
- 影响范围：
  - `score_profile`
  - `sys_menu`
  - `sys_resource`
  - `sys_role_resource`
  - `sys_user.perm_ver`
- 回滚方式或不可回滚原因：
  - 字段新增可保留不使用；回滚代码后旧逻辑会忽略新增字段。
  - 资源码和菜单可删除或恢复备份，但需同步回滚前端 route 和后端 API 权限。
  - 已公开的方案如果回滚为私有语义，需要执行 SQL 将 `visibility` 置回 `private`，否则后续再启用功能会继续公开。

## 8. 测试与验证计划

- 单元测试：
  - 计划：覆盖 `ProfileRef` 编解码、visible 查询、visibility 校验、readonly 判断、snapshot owner 选择。
  - 具体完成情况：`backend/tests/test_score_profile.py` 覆盖 visible 查询、平台预设、只读与复制。
- 接口测试：
  - 计划：覆盖 `/score-profiles` visible list/detail/save/delete/publish/copy，`/board/profiles`，`/board/run` fresh/stale/materialized。
  - 具体完成情况：`backend/tests/test_score_profile_visibility_api.py` 与 `backend/tests/test_stage4_board.py` 覆盖。
- 页面/交互测试：
  - 计划：覆盖 BoardView 可见方案下拉、cache 状态、无方案空态；评分方案管理页只读、发布、复制按钮显隐。
  - 具体完成情况：已通过 `npm run build` 类型检查；未新增 mount 测试。
- 权限与数据范围测试：
  - 计划：多租户用户 A/B 验证 private 不可见、tenant 同租户可见、public 全体可见、非 owner 不可改删、无 publish 权限 403。
  - 具体完成情况：后端 API/仓储测试已覆盖；RBAC 菜单与路由扫描专项通过。
- 回归测试：
  - 计划：复跑 Stage4 路由扫描、menu guard、board、权限指令、前端 build。
  - 具体完成情况：后端公开方案/榜单/RBAC 相关专项 73 passed；配置拆页后 RBAC seed 专项 42 passed；前端 build 通过；前端权限/布局 Vitest 96 passed。
- 异常与边界测试：
  - 计划：无效 `profile_ref`、跨租户 tenant-only、公开方案被 owner 删除、版本更新后旧快照、并发双请求物化、`force=true` 无权限。
  - 具体完成情况：覆盖跨租户 tenant-only 与无 publish 权限；无效 ref、并发双请求、公开方案删除后的前端恢复未单独覆盖。
- 图示与原型一致性验证：本需求无原型文件；BoardView 保持现有 list 布局，评分方案管理复用 ConfigView 评分 tab 布局。若新增独立评分方案页，必须同步 `pageRegistry` 和 `DESIGN.md §9`，并检查 1440x900、700、560 三档视口不溢出。
- 配置闭环验证：`visibility` 展示、保存、读取、消费、取消公开、非法值拒绝、历史数据默认值和平台预设兼容均需覆盖。
- 需求映射验证：以 §5 表为准，所有 R28 子项必须有任务、测试和状态。
- 页面功能点验证：以 §4.6、§4.7 表为准，所有页面功能点都有技术实现、任务编号和异常处理验证。

## 9. 发布与回滚

- 发布前检查：
  - PG 备份 `score_profile/sys_menu/sys_resource/sys_role_resource/sys_user`。
  - 确认 Stage4 修复基线提交已部署或合并。
  - 执行后端专项、前端 build、前端权限测试。
  - 确认 `score-profile-visibility.sql` 与 `pg_ddl.py` DDL/seed 一致。
- 发布步骤：
  - `./start.sh stop`。
  - 执行数据库迁移 SQL 或等价 CLI。
  - 部署后端和前端代码。
  - `./start.sh`。
  - 用 system、tenant_admin、normal、debug_board_only 抽样登录验证。
- 配置或环境变量：
  - 不新增环境变量。
  - 沿用现有 PG/Redis/JWT 配置。
- 回滚方案：
  - 回滚代码到 `cc9862a` Stage4 修复提交。
  - 恢复发布前权限表备份，或删除新增菜单/资源码授权。
  - 保留 `score_profile` 新增字段无害；如需彻底回滚公开状态，执行 SQL 将非 preset 方案 `visibility='private'`。
  - 回滚后 bump 受影响用户 `perm_ver`，要求重新登录。

## 10. 风险、假设与待确认项

### 10.1 风险

- `board:view` 读穿透物化会把纯读入口变成受控缓存写入口；必须限制为可见方案、当前版本、指定日期，并保证幂等锁。
- 公开方案数量增长后，打开榜单可能触发较重计算；需通过缓存、锁和可选批量生产任务兜底。
- `score-profile:*` 从 system-only 迁出后，权限 seed、菜单、角色页和路由守卫必须同步，否则普通用户有 API 无页面或有页面无接口。
- `profile_ref` 兼容不当会造成旧前端只传 `profile_id` 误命中平台预设或当前用户方案。
- 抽取 `ConfigView` 评分 tab 可能影响系统管理员现有配置页，需要前端回归覆盖。

### 10.2 假设

- “缺失/stale 应重新计算”按用户原始理解执行；本计划把它定义为 `board:view` 的受控读穿透缓存物化，而不是任意写权限。
- 公开方案快照写方案 owner 槽，公开方案结果全员共享一份。
- 公开到全体默认只给 system；公开到租户默认给 tenant_admin 和 system，普通用户可由角色授权获得。
- 新用户默认可见平台内置公开预设和全体公开方案，不做复制分发。
- 本分支只覆盖评分方案；其他资产类型后续按同一模型再独立迁移。

### 10.3 待确认项

| 项 | 默认处理 | 影响 | 确认时机 |
| --- | --- | --- | --- |
| 评分方案管理新入口路径 | 已按用户意见改为 `系统管理 → 配置管理 → 评分规则`，不再新增顶层评分菜单 | 影响菜单 seed、路由、权限测试 | 已调整 |
| `board:view` 读穿透是否需要异步化 | 默认同步受控物化；公开方案过多时再引入任务化 | 影响用户等待时间和后端并发 | T6 性能测试后 |
| 全体公开是否允许普通用户角色获得 | 默认不授普通用户，只能 system 或显式授权 | 影响运营治理 | T2 资源码默认授权时 |
