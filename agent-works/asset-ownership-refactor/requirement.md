# 需求文档 · 资产归属重构（asset-ownership-refactor）

> 本文档已完成现状调研与范围确认，作为后续开发计划（`auto-plan-dev`）的输入。所有现状判断均给出代码事实源（`file:line`）。

## 1. 背景与目标

当前系统存在一个用户可见的「系统内置」概念：评分 / 筛选 / 买卖方案里有一批「预设方案」，在下拉和列表里带灰色「系统内置」徽标。这批预设本质上是 `is_preset=true` + 归属固定平台槽 `PUBLIC_BOARD_OWNER = ("default","admin")` + `visibility=public` 的组合（`backend/storage/pg_ddl.py:42-56`、`backend/scoring/score_profile.py:288-290`）。

同时，现有资产可见性模型（阶段六）已经把「私有 / 租户公开 / 全体公开」三档、opaque ref 脱敏、复制为我的等能力建好，但存在两处与目标体验不一致：

1. 三类方案的下拉/列表接口一次性返回「自己 + 租户公开 + 全体公开 + 内置」混合集（`list_visible`），用户下拉里混着别人的和内置的资产；
2. 公开资产没有独立的浏览/搜索入口，也没有关键字搜索；发布权限只放给管理员（普通用户不能公开自己的资产）。

**本次目标**：把资产模型统一成「所有资产都归属真实用户 → 用户（含普通用户）可自主公开到租户/全体 → 他人在资产页通过统一「搜索」弹窗浏览公开资产 → 复制保存为自己的私有方案」。对用户彻底取消「系统内置」这一可见概念；后台每日榜单机制保持不变。

## 2. 当前项目现状

### 2.1 「系统内置」的真实构成

- 常量：`DEFAULT_TENANT_ID="default"`、`DEFAULT_OWNER_USER_ID="admin"`、`PUBLIC_BOARD_OWNER=("default","admin")`（`backend/storage/pg_ddl.py:42-50`）。预设方案在数据层面**已经归属 admin 用户**，无独立哨兵 owner，无 `owner_user_id=0` 之类。
- 保存逻辑：仅当 owner 恰为 `PUBLIC_BOARD_OWNER` 且 `is_preset=true` 时，`save` 自动把 `visibility` 置 `public` 并写 `published_at/published_by`（`backend/scoring/score_profile.py:288-290`）。
- 前端徽标：资产类「系统内置」只经 `AssetVisibilityTag.vue:55`（`mode==='source' && source==='preset'`）一处渲染；各资产页以 `:source="p.is_preset ? 'preset' : p.source"` 传入（`frontend/src/components/SystemBuiltinTag.vue`、`AssetVisibilityTag.vue`、`AssetProfileLabel.vue`）。system/layout/menu/tenant/config 页另有一套与资产无关的 `is_builtin` 语义，本次不动。

### 2.2 `is_preset` 与每日榜单的耦合（关键）

`is_preset` 不只是前端标签，后台每日榜单生产/查询链路有多处硬依赖：`get_public_board_profile` 仅返回 `is_preset` 方案（`backend/services/public_board.py:54`）、`list_public_board_profiles` 只列 `is_preset`（`:61`）、榜单最新日/生产筛选按 `p.is_preset=true`（`:89,136,138`）。因此「取消内置」若彻底删列，会牵动榜单机制并放大默认榜单的不可控性。

### 2.3 各类资产的 list / copy / 可见性现状

| 资产 | list 接口 | 现状口径 | copy | 可见性存储 |
|---|---|---|---|---|
| 评分 score-profile | `GET /api/score-profiles`（`backend/api/score_profiles.py:52-55`） | `ScoreProfileRepo.list_visible`（`backend/scoring/score_profile.py:327-343`）：自己+public+同租户tenant+preset 混合 | 有 `/copy`（`score_profiles.py:133-154` → `copy_visible` `score_profile.py:387-396`） | `visibility` 列 + CHECK（`pg_ddl.py:219,224`） |
| 筛选 screen-profile | `GET /api/profiles`（`backend/api/profiles.py:67-70`） | `ProfileRepo.list_visible`（`backend/screening/profile.py:144`）同上 | 有 `/copy`（`profiles.py:154-175` → `profile.py:215`） | 同上（`pg_ddl.py:190,195`） |
| 买卖 trade-profile | `GET /api/trade-profiles`（`backend/api/trade_profiles.py:57-60`） | `TradeProfileRepo.list_visible`（`backend/signals/trade_profile.py:271`）同上 | 有 `/copy`（`trade_profiles.py:139-160` → `trade_profile.py:342`） | 同上（`pg_ddl.py:250,255`） |
| 回测 backtest | `GET /api/backtest/runs`（`backend/api/backtest.py:132-160`） | `list_runs`（`backend/services/backtest_service.py:463-557`）默认可见全部，**已支持 `?source=mine\|tenant\|public` 分段**（`:477-485`） | **无 copy**，仅「复用参数重跑」（`source_run_ref` `backtest.py:55`、`_record_reuse_if_needed` `backtest_service.py:559-566`） | `visibility` 列 |
| 榜单方案下拉 | `GET /api/board/profiles`（`backend/api/board.py:143-149`） | 直接复用 `ScoreProfileRepo().list_visible()` | 复用评分方案 | 复用评分方案 |

- 纯「仅自己」的查询已存在：`ScoreProfileRepo.list()`（`score_profile.py:321-325`，`WHERE tenant_id AND owner_user_id`），筛选/买卖同构。
- 所有 list 接口**均无关键字搜索参数**。
- opaque ref 编解码统一在 `backend/services/asset_visibility.py`：`make_asset_ref`（`:58-70`）、`parse_asset_ref`（`:88-112`）、`resolve_asset_ref_or_legacy_id`（`:115-131`）、行装饰 `decorate_asset_row`（`:164-196`）、脱敏 `owner_label`（`:155-161`，同租户他人→「同租户用户」，跨租户→「其他租户用户」，从不回显真实 user_id）、统一可见性过滤 `visible_sql/visible_params`（`:231-241`）。

### 2.4 发布权限现状（与目标冲突）

同一 visibility 路由用 `require_visibility_perm(view, publish-tenant, publish-public)`（`system-rbac-tenant.md:202`）。当前策略：**租户公开权仅 `tenant_admin/system`，全体公开权仅 `system`**，且 seed 里主动 `DELETE` 撤销普通角色（normal/paid）的租户发布权（`backend/auth/constants.py`、`backend/storage/pg_ddl.py` seed，记忆 `multi-tenant-rbac-pivot`）。发布权限码刻意不进 `BUSINESS_RESOURCE_CODES`。

### 2.5 前端复用面

- 已有：可见性发布三档 + 复制 + 复用组件 `AssetVisibilityActions.vue`（消费点 `ConfigView.vue:1118/1470`、`ScreenView.vue:571`、`BacktestView.vue:979`）、纯展示 `AssetVisibilityTag.vue`、`AssetProfileLabel.vue`。
- 缺口：**无统一「方案选择器」组件**——5 页各写一份 `el-select/<ul> + AssetProfileLabel`（`ScreenView.vue:539-569`、`ConfigView.vue:1093-1109/1450-1462`、`BacktestView.vue:1074-1095/1117-1137/955-978`、`BoardView.vue:228-249`、`StockDetailView.vue:947-960`）；**无收藏任何代码**。
- 可复用抽屉/列表基座：`PageDrawer.vue` + `AppDataTable.vue` / `AppPagination.vue` / `AppFilterSelect.vue` / `AppStateBlock.vue` / `AppRowActions.vue`。
- 回测历史已有 `historySource`（全部/我的/租户公开/全体公开）过滤下拉（`BacktestView.vue:955-978`），是「按来源加载」的唯一先例。

### 2.6 现有下架机制（可复用）

用户被停用/删除、租户被停用/删除时，服务层在同事务把该用户/租户**非 private 的评分、筛选、买卖方案和回测记录下线为 private，回测引用列恢复为裸 id**（`system-rbac-tenant.md` 用户/租户操作闭环表）。放开发布权后可直接复用这套下架能力。

### 2.7 需核实项

评分、买卖预设的 `seed_defaults()`（`score_profile.py:451-455`、`trade_profile.py:414-418`）在生产代码**无调用点**（仅 `test_backtest.py` 命中）；仅筛选 `seed_presets()` 有 CLI 入口 `seed-presets`（`cli.py:221-224,601`）。动手前需核实线上这批评分/买卖预设的真实入库方式。

## 3. 用户角色与使用场景

- **普通用户（normal/paid）**：拥有并维护自己的方案；可把自己的方案公开到本租户或全体；可在资产页「搜索」弹窗浏览他人公开的方案，加载查看、复制为自己的私有方案。**（本次新增：可自主公开）**
- **租户管理员（tenant_admin）**：同普通用户，历史上额外拥有租户发布权。
- **系统管理员（system / admin 账号）**：退化为普通资产 owner；原「系统内置」方案成为 admin 名下的普通公开方案，admin 像普通用户一样维护/公开它们；`is_preset` 标记（后台不可见语义）继续决定默认每日榜单来源。

典型场景：
1. 新用户首次进入评分/筛选/买卖/回测页，下拉为空 → 点「搜索」→ 浏览全体公开方案 → 复制 admin 公开的基础方案为自己的私有方案 → 开始使用。
2. 资深用户把打磨好的方案公开到全体，供他人搜索、复制。

## 4. 功能范围

### 4.1 必须实现

| 需求编号 | 需求项 | 来源/依据 | 验收意图 |
| --- | --- | --- | --- |
| R1 | 前端彻底移除「系统内置」可见概念：资产页不再渲染「系统内置」徽标，该批方案显示为 admin 的公开方案 | 用户诉求①；`AssetVisibilityTag.vue:55`、各页 `:source="p.is_preset?..."` | 全站资产界面无「系统内置」字样；原预设显示为「全体公开」来源 |
| R2 | `is_preset` 列保留为后台「官方每日榜单来源」内部标记（用户不可见），榜单机制零改动 | 方案 A（已确认）；`public_board.py:54,61,89,136,138` | 每日榜单仍按 `is_preset` 生产/展示；前端任何接口不再据此打「系统内置」标签 |
| R3 | 各资产下拉只加载「自己的」资产（评分/筛选/买卖/回测/榜单方案下拉） | 用户诉求②；已有 `list()` `score_profile.py:321-325`、回测 `source=mine` | 各页方案下拉只出现当前用户 owner 的资产，不含他人公开/内置 |
| R4 | 放开普通用户发布权：普通用户可把自己的资产公开到租户或全体 | 用户诉求②（已确认全放开）；`constants.py`、`pg_ddl.py` seed | normal/paid 用户可对自己的方案执行租户公开、全体公开并生效 |
| R5 | 各资产页新增统一「公开资产搜索」弹窗：按来源（租户/全体）+ 关键字浏览公开资产，支持加载展示、复制保存为「我的方案」 | 用户诉求②；`asset_visibility.py` ref/装饰、`PageDrawer`+`AppDataTable` | 每个资产页有「搜索」入口；弹窗可分来源+关键字检索；可加载查看与复制入库 |
| R6 | 回测补「复制/另存为方案」能力（当前仅重跑） | 用户诉求②对齐三类方案；`backtest_service.py:559-566` | 公开回测可复制为当前用户 private 记录（参数与结果承接口径见 §5） |
| R7 | 统一「方案选择器 + 公开资产搜索」为共享前端组件，替换 5 页私有装配 | 复用优先（`frontend-reuse-enforcer`）；`AssetProfileLabel` 已抽 | 评分/筛选/买卖/回测/榜单五处共用同一选择器与搜索弹窗组件 |

### 4.2 建议实现

| 需求编号 | 需求项 | 来源/依据 | 纳入条件 | 处理状态 |
| --- | --- | --- | --- | --- |
| R8 | 放开发布权后，为公开资产增加「举报/下架」或管理员治理入口 | 安全边界扩大后的运营治理 | 公开资产规模变大、出现滥用时 | 后续建议 |
| R9 | 新用户首登时默认复制一份 admin 基础公开方案，缓解「下拉为空」冷启动 | §3 场景1、冷启动体验 | 产品确认要做引导 | 待确认 |
| R10 | 个股详情页（`StockDetailView.vue:947-960`）买卖方案选择同步接入「仅自己+搜索弹窗」 | 与 R3/R5 一致性 | R5 组件就绪后顺带接入 | 本次纳入 |

### 4.3 暂不实现

| 需求编号 | 需求项 | 不做原因 | 后续触发条件 |
| --- | --- | --- | --- |
| R11 | 收藏 / favorite（标记、置顶他人公开资产） | 用户明确本次不做；全仓无任何收藏代码，需全栈从零（建表+接口+前端） | 用户后续提出常用公开资产管理诉求 |
| R12 | 自选分组、盘感训练接入可见性/公开/搜索 | 二者当前无 visibility/copy/ref 模型（纯 per-user 私有），需从零补整套底座 | 用户提出跨用户共享分组/训练配置时另立需求 |
| R13 | 彻底删除 `is_preset` 列、榜单改按 `visibility=public` 圈定来源（方案 B） | 用户已选方案 A；B 会放大默认榜单不可控并波及 DDL/迁移/大量 stage6 测试 | 产品决定重构默认榜单来源机制时 |

## 5. 详细功能需求

### R1 移除「系统内置」可见概念
- **功能描述**：前端资产（评分/筛选/买卖/回测/榜单方案）不再出现「系统内置」徽标；原预设方案在下拉与搜索弹窗中按其真实 `visibility` 显示（admin 公开的显示为「全体公开」+ 脱敏 owner 标签）。
- **操作流程**：调整 `AssetVisibilityTag.vue` 的 `source` 语义，移除 `preset` 分支的「系统内置」渲染；各页传参不再区分 `is_preset`。
- **校验/异常**：需确保后端 list 返回中前端不再依赖 `is_preset` 打标签（后端可继续返回该字段供榜单，但前端展示层忽略）。
- **对现有功能影响**：`AssetVisibilityTag.vue` 的 `preset` 分支、`AssetProfileLabel` 来源展示、相关 Vitest 断言。

### R2 `is_preset` 降级为后台标记
- **功能描述**：`is_preset` 列与榜单链路（`public_board.py`）保持现状，仅剥离其「前端系统内置徽标」用途。语义从「系统内置（用户可见）」改为「官方每日榜单来源（仅后台）」。
- **权限与数据范围**：`is_preset` 的写入仍随预设 seed / admin 归属逻辑；非平台槽 owner 保存不产生 `is_preset`。
- **对现有功能影响**：不改榜单生产/查询 SQL；`save` 自动置 public 逻辑（`score_profile.py:288-290`）保持，确保 admin 预设仍是 public。

### R3 下拉仅加载自己的资产
- **功能描述**：评分/筛选/买卖/回测/榜单方案下拉只返回当前用户 owner 的资产。
- **操作流程（后端）**：为三类方案 list 接口增加 `source=mine`（对齐回测已有口径），或下拉改调纯 `list()`；回测下拉沿用 `source=mine`。
- **输入输出**：入参 `source=mine`；出参不含他人 public/tenant 与 preset。
- **异常/边界**：下拉为空（新用户）属正常态，前端空态引导去「搜索」。
- **对现有功能影响**：各页 `loadProfiles/loadProfileOptions` 调用参数；需保留「已选中的只读公开方案仍能正常回显」的兼容（当前选中项可能来自搜索弹窗加载的公开资产）。

### R4 放开普通用户发布权
- **功能描述**：普通用户可对自己拥有的资产执行「租户公开 / 全体公开 / 收回私有」。
- **操作流程（后端）**：调整发布权限码归类——将 `publish-tenant` / `publish-public`（screen/trade/score/backtest）纳入普通业务授权集合；移除 seed 中撤销普通角色租户发布权的 `DELETE`；补默认授权回填。
- **校验规则**：仍必须 owner-only（非 owner 不能改他人可见性，`require_visibility_perm` owner 校验保留）；公开回测发布前仍校验引用方案不低于目标公开范围（现有逻辑保留）。
- **权限与数据范围**：发布仍按 `tenant_id + owner_user_id` 归属；`perm_ver` 联动按现有事务口径。
- **对现有功能影响**：`constants.py`、`pg_ddl.py` seed、`seed_stage6_asset_visibility`、相关权限/路由扫描测试与 stage6 可见性测试断言。

### R5 统一公开资产搜索弹窗
- **功能描述**：资产页点「搜索」打开抽屉，按来源（租户公开 / 全体公开）+ 关键字浏览对应类型的公开资产，可加载到当前页展示、复制为自己的私有方案。
- **前置条件**：用户已登录；对应资产类型存在公开资产。
- **操作流程**：打开抽屉 → 选来源分段 + 输入关键字 → 列表分页展示（名称、版本、来源徽标、脱敏 owner、更新时间）→ 行操作「加载查看」/「复制为我的」。
- **输入输出（后端 browse 接口）**：入参 `source=tenant|public`、`q`（关键字，匹配名称）、分页；出参复用 `decorate_asset_row`/`summarize_asset_row`（含 opaque `profile_ref`/`run_ref`、`source`、`readonly`、脱敏 `owner_label`），**不回显真实 owner/tenant/user_id**。
- **校验/异常**：仅返回可见（tenant 限同租户、public 全体）；关键字为空返回全部公开；空结果走空态；加载失败走错误态。
- **权限与数据范围**：browse 用 `visible_sql` 的 tenant/public 分支（排除自己，避免与下拉重复）；复制走已有 `/copy`（落当前 owner private）。
- **对现有功能影响**：三类方案新增 browse 接口 + `q`；回测可复用现有 `source` 并补 `q`。

### R6 回测复制/另存为方案
- **功能描述**：公开回测记录可复制为当前用户的 private 记录，便于纳入自己的资产列表。
- **待定实现取向（交开发计划细化）**：
  - 方案 6a：新增回测 `/copy` 接口，克隆参数与结果快照，归属当前 owner、visibility=private；
  - 方案 6b：沿用现有「复用参数重跑」，把「另存为」定义为「以公开参数重跑并保存为自己的私有 run」。
- **校验/异常**：引用方案的可见性承接、`source_run_ref` 审计（`_record_reuse_if_needed`）保留。
- **对现有功能影响**：`backtest_service.py`、`backtest.py`；前端回测历史选择器与搜索弹窗接入。

### R7 统一方案选择器 + 搜索弹窗组件
- **功能描述**：抽取一个共享「资产选择器」组件（下拉/列表 + 来源徽标 + 搜索入口）+ 一个共享「公开资产搜索抽屉」组件，替换 5 页私有实现。
- **对现有功能影响**：`ScreenView`、`ConfigView`（评分+买卖）、`BacktestView`、`BoardView`、`StockDetailView` 的选择器段；需保持各页现有交互（评分/买卖为侧栏 `<ul>` 列表，需评估统一为选择器组件或保留列表形态但共用搜索弹窗）。

## 6. 数据与接口需求

- **数据表**：无新增表（不做收藏、不删 `is_preset`）。沿用 `score_profile`/`screen_profile`/`trade_profile`/`backtest_run` 的 `tenant_id + owner_user_id + visibility + is_preset` 列。
- **权限元数据**：调整 `sys_resource`/角色授权 seed，使 `*:publish-tenant`、`*:publish-public` 进入普通业务授权集合；删除撤销普通角色租户发布权的 seed DELETE；补默认授权。
- **接口新增/调整**：
  - 三类方案 list：新增 `source=mine`（下拉用）与 browse 用 `source=tenant|public` + `q`；或新增独立 `GET .../browse`。命名与形态对齐回测 `source` 口径。
  - 回测：list 已有 `source`，补 `q`；新增 copy 或定义「另存重跑」（R6）。
- **数据一致性**：复制走已有 `copy_visible`（`ON CONFLICT`/归属校验、409 保护、复制审计 `record_asset_copy_audit`）；owner 脱敏统一走 `asset_visibility.py`，前端不接触真实 owner。
- **不变量**：opaque ref 不入库；下拉/browse/复制全部经 `resolve_asset_ref_or_legacy_id` 精确按归属查。

## 7. 页面与交互开发需求

本次涉及页面：以「新增统一搜索抽屉 + 下拉改仅自己 + 发布按钮对普通用户放开」为主，均为对现有资产页的**更新**。仅对**统一搜索抽屉**出 1 份 HTML 原型（跨页复用同一交互，代表所有资产类型）；各资产页为局部更新，不逐页出原型。

### 7.1 页面 P1：公开资产搜索抽屉（统一组件）

- 对应需求编号：R5、R7、R10
- 页面类型：抽屉（跨评分/筛选/买卖/回测/榜单/个股详情复用）
- 页面入口：各资产页选择器区新增「搜索」按钮
- 原型文件：`prototypes/public-asset-search-drawer.html`
- 页面布局：
  - 布局事实源：对齐 `prototypes/public-asset-search-drawer.html`
  - 页头：标题「浏览公开的{资产类型}」+ 关闭
  - 工具栏：来源分段（租户公开 / 全体公开）+ 关键字搜索框
  - 主区：`AppDataTable` 列表（名称、来源徽标、脱敏 owner、版本、更新时间、操作列）
  - 操作列：「加载查看」「复制为我的」
  - 分页：底部 `AppPagination`
  - 关键状态与退化：加载中 / 空态（无公开资产）/ 错误态 / 复制中/成功/失败 / 窄视口抽屉全宽
- 数据来源：browse 接口（`source=tenant|public` + `q`），字段走 `decorate_asset_row`
- 权限与可见性：仅可见公开资产；owner 全程脱敏；复制入库归当前用户 private
- 组件复用与通用能力：
  - 已有通用能力：`PageDrawer`、`AppDataTable`、`AppFilterSelect`、`AppStateBlock`、`AppPagination`、`AssetProfileLabel`、`AssetVisibilityTag`、`/copy` API
  - 可能新增能力：统一「公开资产搜索抽屉」组件 + 统一「资产选择器」组件（R7），供多资产页复用
  - 配置化承载：无

#### 7.1.1 功能点：来源分段 + 关键字检索
- 默认展示：默认「全体公开」，空关键字返回全部公开
- 用户操作：切换来源、输入关键字（防抖）
- 输入与校验：关键字裁剪空白；分页参数合法化
- 状态变化：切换/输入触发重查；加载态覆盖列表
- 空/错误/权限状态：空态提示「暂无公开{类型}」；错误态可重试；未登录不进入（路由已保护）
- 验收标准：来源+关键字能正确过滤，仅出公开且排除自己

#### 7.1.2 功能点：加载查看
- 用户操作：点行「加载查看」→ 关闭抽屉并把该公开资产以只读态载入当前页选择器/预览
- 状态变化：当前页选择器回显该只读公开方案（`readonly=true`）
- 联动：与页面既有「只读方案」展示口径一致（复用 `AssetVisibilityTag` readonly）
- 验收标准：加载后当前页能只读展示该公开方案，不污染「我的」下拉

#### 7.1.3 功能点：复制为我的
- 用户操作：点行「复制为我的」→ 调 `/copy` → 落当前用户 private → 刷新「我的」下拉并选中
- 保存/提交：成功 toast；同名/冲突 409 提示
- 状态变化：我的下拉新增该副本并选中
- 验收标准：复制后出现在「仅自己」下拉，visibility=private，owner=当前用户

### 7.2 更新页面（不单独出原型）

| 页面 | 文件:行 | 变更区域 | 说明 |
|---|---|---|---|
| 筛选方案 | `ScreenView.vue:539-571` | 下拉改仅自己 + 新增「搜索」按钮 + 发布按钮对普通用户可见 | 局部更新，复用 P1 抽屉 |
| 评分方案 | `ConfigView.vue:1093-1118` | 侧栏列表改仅自己 + 「搜索」入口 + 发布放开 | 侧栏 `<ul>` 形态保留，接搜索弹窗 |
| 买卖方案 | `ConfigView.vue:1450-1470` | 同评分 | 同上 |
| 回测 | `BacktestView.vue:955-1137` | 方案下拉仅自己 + 历史/方案搜索弹窗 + 回测另存（R6） | 历史 `source` 先例可平移 |
| 榜单 | `BoardView.vue:228-249` | 方案下拉仅自己 + 「搜索」入口 | 榜单展示机制不变 |
| 个股详情 | `StockDetailView.vue:947-960` | 买卖方案选择仅自己 + 「搜索」入口 | R10 |

## 8. 边界条件与异常场景

- 新用户/无自有资产：下拉为空为正常态，空态引导「搜索」；R9 冷启动引导为可选增强。
- 已加载的只读公开资产：下拉切「仅自己」后，当前选中的公开只读方案要能继续回显，不被过滤逻辑清空。
- 发布权放开后被停用/删除：复用现有「非 private 资产下线为 private、回测引用恢复裸 id」下架机制（§2.6）。
- 关键字/来源组合无结果：空态；租户公开对跨租户用户不可见。
- 复制冲突：`copy_visible` 已有 409 与归属校验，前端给可读提示。
- 回测另存的引用可见性：保持「引用方案不低于目标可见范围」校验。

## 9. 性能、安全与兼容性要求

- **安全（重点）**：R4 是安全边界变更。必须保证：①仍 owner-only 改可见性；②browse/list/copy 全程经 `visible_sql` + 归属键，禁止信任前端传入 owner；③owner 脱敏不回退。新增 browse 端点必须挂后端守卫、登记 `sys_resource`、补路由扫描测试（AGENTS 鉴权边界）。
- **性能**：browse 需分页 + 关键字索引考量；避免全表扫描公开资产。
- **兼容性**：`is_preset` 字段后端保留，老前端/接口不受影响；opaque ref 兼容旧前缀逻辑保留。
- **测试**：波及 `test_stage6_*_visibility`、`test_score_profile*`、路由扫描、资源码/菜单 seed、前端 Vitest 与相关 E2E。

## 10. 业务亮点与优化建议

| 编号 | 优化建议 | 价值 | 处理状态 | 说明 |
| --- | --- | --- | --- | --- |
| R7 | 统一「资产选择器 + 搜索抽屉」组件 | 消除 5 页重复实现，降低后续维护成本 | 本次纳入 | 复用优先原则 |
| R9 | 新用户默认复制基础公开方案 | 缓解下拉为空冷启动 | 待确认 | 需产品确认 |
| R8 | 公开资产治理/下架入口 | 放开发布后的运营兜底 | 后续建议 | 规模变大再做 |

## 11. 验收标准

| 需求编号 | 验收标准 | 验证方式 |
| --- | --- | --- |
| R1 | 全站资产界面无「系统内置」字样；原预设显示为「全体公开」 | 前端各资产页目视 + Vitest（`AssetVisibilityTag`） |
| R2 | 每日榜单仍按 `is_preset` 正常生产/展示，前端不据此打标签 | 后端榜单接口回归 + `public_board` 相关测试 |
| R3 | 各资产下拉仅出现当前用户 owner 资产 | 用不同调试账号（`test-users.md`）验证下拉内容 + 后端 list 测试 |
| R4 | 普通用户可对自己方案租户/全体公开并生效，不能改他人资产 | 普通账号 E2E/接口测试 + 权限守卫测试 |
| R5 | 搜索弹窗可按来源+关键字检索公开资产，可加载查看与复制入库；owner 脱敏 | 弹窗交互 E2E + browse 接口测试（脱敏断言） |
| R6 | 公开回测可复制/另存为当前用户 private 记录 | 回测接口/前端验证 |
| R7 | 五处选择器与搜索弹窗共用同一组件 | 代码审查 + Vitest 复用点 |
| R10 | 个股详情买卖方案接入仅自己+搜索 | 页面验证 |

## 12. 建议开发顺序

- **阶段一（后端资产可见性收口）**：R2、R3、R4。目标：先把「下拉仅自己」「发布权放开」「is_preset 降级为后台标记」在后端与权限层落定并测试通过。前置：这是前端一切改动的契约基础；里程碑：三类方案 list 支持 `source=mine`、普通用户可发布、stage6/权限测试全绿。
- **阶段二（公开资产 browse 接口 + 回测另存）**：R5 后端部分、R6。目标：新增 browse（`source`+`q`）与回测复制/另存。依赖阶段一的可见性口径；里程碑：browse 接口返回脱敏公开资产、回测可复制、接口测试通过。
- **阶段三（前端统一组件与页面接入）**：R1、R5 前端、R7、R10。目标：抽统一「资产选择器 + 搜索抽屉」，各资产页接入并移除「系统内置」徽标。依赖阶段二接口；里程碑：五处页面共用组件、无系统内置字样、E2E/Vitest 通过、`npm run build` 同步 `dist`。
- 说明：本需求跨 RBAC + 后端可见性 + 前端组件，规模中大，建议后续以阶段一/二/三分别细化开发计划；阶段一是安全边界变更，务必先独立验证再动前端。

## 13. 遗留确认项

- **R6 实现取向**：回测「另存为方案」采用新增 `/copy`（6a）还是「公开参数重跑保存」（6b），交开发计划阶段二决策（不阻塞阶段一）。
- **R9 冷启动引导**：是否给新用户默认复制基础公开方案，待产品确认（不阻塞）。
- **§2.7 预设入库核实**：评分/买卖预设线上入库方式需在阶段一动手前核实，避免存量来源与代码不一致。
