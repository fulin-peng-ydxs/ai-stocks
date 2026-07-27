# 开发计划 · 资产归属重构（asset-ownership-refactor）

## 1. 需求来源与目标

- 需求文档：[requirement.md](./requirement.md)（R1–R13）
- 原型文件：[prototypes/public-asset-search-drawer.html](./prototypes/public-asset-search-drawer.html)
- 功能目标：对用户彻底取消「系统内置」可见概念；各资产下拉只加载自己的资产；放开普通用户自主公开；各资产页新增统一「公开资产搜索」弹窗（浏览租户/全体公开 + 关键字 + 加载查看 + 复制为我的）；回测补「复制/另存为方案」。
- 本次不做：收藏（R11）、自选分组/盘感训练接入可见性（R12）、彻底删除 `is_preset` 列（R13，采用方案 A 保留列作后台榜单来源标记）。
- 计划输出目录：`./agent-works/asset-ownership-refactor/`

## 2. 当前项目依据

### 后端 · 资产可见性与列表
- 统一可见性工具：`backend/services/asset_visibility.py` —— `make_asset_ref:58`、`parse_asset_ref:88`、`resolve_asset_ref_or_legacy_id:115`、`decorate_asset_row:164`、`summarize_asset_row:199`、`owner_label:155`、`visible_sql/visible_params:231-241`、`VISIBILITIES:16-19`。
- 三类方案 list_visible（混合口径）：`backend/scoring/score_profile.py:327-343`、`backend/screening/profile.py:144`、`backend/signals/trade_profile.py:271`。纯自己查询：`score_profile.py:321-325`（`list()`）。
- API 列表入口：`backend/api/score_profiles.py:52-55`、`backend/api/profiles.py:67-70`、`backend/api/trade_profiles.py:57-60`、`backend/api/board.py:143-149`（复用 `ScoreProfileRepo().list_visible()`）。
- copy 接口：`score_profiles.py:133-154`→`copy_visible score_profile.py:387-396`；`profiles.py:154-175`→`profile.py:215`；`trade_profiles.py:139-160`→`trade_profile.py:342`（均含 409 与归属校验、复制审计 `backend/services/asset_audit.py record_asset_copy_audit`）。
- 回测：`backend/api/backtest.py:132-160`（list，已支持 `?source=mine|tenant|public`）、`backend/services/backtest_service.py:463-557`（`list_runs`，source 分支 `477-485`）；无 copy，仅重跑 `source_run_ref`（`backtest.py:55`、`_record_reuse_if_needed backtest_service.py:559-566`）。

### 后端 · is_preset 与榜单（方案 A 保留）
- 榜单对 `is_preset` 硬依赖：`backend/services/public_board.py:54,61,89,136,138`。本次不改这些。
- 平台槽常量：`backend/storage/pg_ddl.py:42-50`（`PUBLIC_BOARD_OWNER`）；预设 save 自动置 public：`backend/scoring/score_profile.py:288-290`。本次保留。

### 后端 · 发布权限（R4 核心改点）
- 发布码分类：`backend/auth/constants.py:38`（`BUSINESS_RESOURCE_CODES`，**未含发布码**）、`:52-63`（`ASSET_TENANT_PUBLISH_RESOURCE_CODES` / `ASSET_PUBLIC_PUBLISH_RESOURCE_CODES`，注释明确「不放入 BUSINESS 避免 normal 获得发布能力」）。
- 撤销普通角色发布权的两处 DELETE：`pg_ddl.py:1403-1408`（stage4 backfill 撤 `score-profile:publish-tenant`）、`pg_ddl.py:1543-1548`（stage6 撤 normal 全部 tenant+public 发布）。
- stage6 授权迁移：`pg_ddl.py:1523-1568`（`seed_stage6_asset_visibility`，用 `_STAGE6_ASSET_VISIBILITY_MARKER` 提前返回；**存量库已跑过，必须新增带新 marker 的回填才能对存量库生效**）。
- 守卫：`backend/auth/deps.py:59 require_visibility_perm`（owner-only + publish 权限校验，运行时按规范化 visibility 写 resource_code）。

### 前端
- 发布权限位：各页 `hasPermission(auth.role, auth.permissions, 'xxx:publish-tenant/public')` 计算 `canPublishTenant/canPublishPublic`（`ScreenView.vue:261-264`、`ConfigView.vue:408-412/739-742`、`BacktestView.vue:278-282`），透传给 `AssetVisibilityActions.vue`（props `canPublishTenant/canPublishPublic:11-12`）。**放开发布权后端生效后，前端权限位自动放开，无需改前端权限判断逻辑。**
- 「系统内置」徽标：`frontend/src/components/SystemBuiltinTag.vue`、`AssetVisibilityTag.vue:55`（`source==='preset'`）；各页 `:source="p.is_preset ? 'preset' : ..."`。
- 选择器（5 处私有）：`ScreenView.vue:539-571`、`ConfigView.vue:1093-1118/1450-1474`、`BacktestView.vue:955-978/1074-1137`、`BoardView.vue:228-249`、`StockDetailView.vue:947-960`。
- 复制/发布组件：`AssetVisibilityActions.vue`（发布三档 + copy + reuse）。
- 复用基座：`PageDrawer.vue`、`AppDataTable.vue`、`AppPagination.vue`、`AppFilterSelect.vue`、`AppStateBlock.vue`、`AppRowActions.vue`、`AssetProfileLabel.vue`。
- 前端 API 封装：`frontend/src/api/{screening,scoreProfile,tradeProfile,board,backtest}.ts`。

### 设计规范
- `DESIGN.md`（视觉 token、页面设计闭环、组件/布局维护矩阵）、`agent-works/configurable-layout-system/page-template.md`（页面模板与登记）。抽屉与列表须复用现有基座与 token，触发组件维护矩阵登记。

### 待核实（阶段一动手前）
- 评分/买卖预设 `seed_defaults()`（`score_profile.py:451-455`、`trade_profile.py:414-418`）生产无调用点，仅 `test_backtest.py` 命中；筛选 `seed_presets()` 有 CLI `seed-presets`（`cli.py:221-224,601`）。需核实线上评分/买卖预设真实入库方式。

## 3. 实施范围

### 3.1 必须实现
- R1 前端移除「系统内置」徽标语义（T10）。
- R2 `is_preset` 降级为后台榜单来源标记，前端不再据此打标签（T1 核实 + T10 前端解耦）。
- R3 各资产下拉只加载自己的资产（T2 后端 + T10 前端接入）。
- R4 放开普通用户发布权（T3）。
- R5 统一公开资产搜索弹窗（T5 后端 browse + T8 前端抽屉）。
- R6 回测复制/另存为方案（T6）。
- R7 统一「选择器 + 搜索弹窗」共享组件（T8/T9）。

### 3.2 可选增强

| 需求编号 | 增强内容 | 需求阶段处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R10 | 个股详情买卖方案接入仅自己+搜索 | 本次纳入 | 待开始 | T11 | 与 R3/R5 一致性 |
| R9 | 新用户默认复制 admin 基础方案 | 待确认 | 跳过 | - | 需产品确认；不阻塞 |
| R8 | 公开资产治理/下架入口 | 后续建议 | 跳过 | - | 放开发布后规模变大再做；现有停用降级机制先兜底 |

### 3.3 暂不实现
- R11 收藏、R12 分组/训练接入、R13 删 is_preset 列。理由见需求文档 §4.3。

## 4. 技术方案

### 4.1 后端可见性收口（R2/R3/R4）

**R3 下拉仅自己**：给三类方案 list API 增加可选 `source` 查询参数，对齐回测已有口径：
- `source=mine`（下拉默认）→ 走纯自己查询（复用/包装 `list()` 的 `WHERE tenant_id AND owner_user_id`，但需补 `decorate_asset_row` 使返回结构与现有一致，含 `profile_ref/source/readonly/owner_label`）。
- 不传 `source` → 维持现状 `list_visible`（向后兼容，避免破坏未改造的调用方）。
- `source=tenant|public` → 见 R5 browse。
统一在 repo 层新增 `list_scoped(source, q, page)` 或在 API 层按 source 分派到 `list()` / `list_visible()` / browse 查询，避免每处复制 SQL。

**R4 放开发布权**（安全边界变更，最谨慎）：
1. `constants.py`：把 `ASSET_TENANT_PUBLISH_RESOURCE_CODES` 与 `ASSET_PUBLIC_PUBLISH_RESOURCE_CODES` 纳入普通业务授权（追加进 `BUSINESS_RESOURCE_CODES` 或在 seed 授权集合里显式并入 normal），并更新其上注释。
2. 撤销两处撤权 DELETE：`pg_ddl.py:1403-1408`、`1543-1548`（保留 tenant_admin 不含 public 的历史约束是否延续需在任务中明确——按需求「全放开」，normal 与 tenant_admin 均获 tenant+public）。
3. **新增回填迁移**（新 marker，如 `migration.asset_publish_open_v1`）：对存量库给 `ROLE_NORMAL`（及 `ROLE_TENANT_ADMIN` 的 public）授 8 个发布码，`ON CONFLICT DO NOTHING`，并 bump 受影响用户 `perm_ver`（同事务）。因 `_STAGE6_ASSET_VISIBILITY_MARKER` 已存在会 early-return，不能复用旧迁移。
4. 守卫 `require_visibility_perm` 的 owner-only 与「引用方案不低于目标公开范围」校验保持不变。
5. `sys_resource` seed 中发布码菜单归属（`pg_ddl.py:858-893`）保持；仅改授权关系。

**R2 is_preset 保留**：后端 list 可继续返回 `is_preset` 字段（榜单与内部逻辑需要），但**前端展示层不再据此渲染「系统内置」**（T10）。后端无需删列、无需改榜单 SQL。

### 4.2 后端公开浏览与复制（R5/R6）

**R5 browse**：三类方案新增按 `source=tenant|public` + `q`（名称模糊匹配）+ 分页的浏览查询：
- 复用 `visible_sql`/`visible_params` 的 tenant/public 分支，**排除自己**（`NOT (tenant_id=? AND owner_user_id=?)`），对齐回测 `backtest_service.py:477-485`。
- 返回经 `decorate_asset_row`/`summarize_asset_row` 脱敏（opaque `profile_ref`、`owner_label`），禁止回显真实 owner。
- 关键字 `q` 走参数化 `ILIKE`，注意索引/结果集规模。
- 复制沿用已有 `/copy`（落当前 owner private）。
- 榜单方案 browse 复用评分方案 browse。

**R6 回测另存**（遗留取向，阶段二决策，推荐 6a）：
- 6a（推荐）：新增 `POST /api/backtest/runs/{run_ref}/copy`，克隆参数+结果快照为当前 owner、visibility=private，复用 `_visible_run_row` 解析可见源，复用复制审计。
- 6b（备选）：定义「另存=以公开参数重跑保存」，复用现有重跑链路 + `source_run_ref` 审计。
- 回测 list 补 `q` 关键字。

### 4.3 前端统一组件与页面接入（R1/R5/R7/R10）

**页面结构决策（P1 搜索抽屉，对齐原型）**：
- 页面类型：抽屉（`PageDrawer` 承载，teleport 到 LayoutHost）。
- 固定区：页头（标题「浏览公开的{资产类型}」+ 关闭）、工具栏（来源分段 `AppFilterSelect`/segment + 关键字搜索框）、底部分页 `AppPagination`。
- 滚动区：中部 `AppDataTable` 列表（名称、来源徽标 `AssetVisibilityTag`、脱敏 owner、版本、更新时间、操作列「加载查看」「复制为我的」）。
- 状态：加载中/空态/错误态用 `AppStateBlock`；复制中/成功 toast/409 冲突提示；窄视口抽屉转全宽。

**组件抽取（R7）**：
- 新增 `AssetSearchDrawer.vue`（通用公开资产搜索抽屉，props：`assetType`、browse/copy 回调或 API 注入；events：`load`（只读加载）、`copied`（复制成功刷新））。
- 评估新增 `AssetProfileSelect.vue`（统一「我的方案」选择器 + 「搜索」按钮入口）：评分/买卖当前是侧栏 `<ul>` 列表形态，筛选/榜单/回测/个股是 `el-select`；抽取以「选择器 + 搜索按钮」为最小公共契约，保留各页列表/下拉形态差异，优先复用 `AssetProfileLabel`。若形态差异过大，至少统一「搜索按钮 + AssetSearchDrawer」这一段，选择器本体分两种形态封装。

**R1 移除系统内置徽标**：
- `AssetVisibilityTag.vue:55` 移除 `source==='preset'` 的「系统内置」分支；各页传参去掉 `p.is_preset ? 'preset' : ...`，统一按真实 `visibility/source` 渲染。
- `SystemBuiltinTag.vue` 组件本体保留（system/layout/menu/tenant/config 仍在用其 `is_builtin` 语义），仅切断资产类对它的引用路径。

**页面接入**：各资产页下拉调用改 `source=mine`；新增「搜索」按钮打开 `AssetSearchDrawer`；发布按钮权限位随后端放开自动生效（无需改前端权限判断）。

### 4.4 页面 P1 技术实现表（公开资产搜索抽屉）

| 页面功能点 | 需求编号 | 需求交互要点 | 技术实现 | 涉及组件/模块 | 数据/API | 状态与异常处理 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 来源分段+关键字检索 | R5 | 默认全体公开，空关键字返回全部，排除自己 | segment 切 source + 防抖 q，触发 browse | `AssetSearchDrawer.vue`、`AppFilterSelect`、`AppDataTable` | browse `source=tenant\|public`+`q`+分页 | 加载态/空态/错误可重试（`AppStateBlock`） | T8 |
| 加载查看 | R5 | 关闭抽屉，只读载入当前页 | emit `load(row)`，父页选择器只读回显 | `AssetSearchDrawer` + 各页选择器 | 复用已返回 ref | 只读态 `AssetVisibilityTag readonly` | T8/T10 |
| 复制为我的 | R5 | 调 /copy，落 private，刷新我的下拉并选中 | emit `copied`，父页刷新 `source=mine` 列表 | `AssetSearchDrawer` + `/copy` API | `POST .../{ref}/copy` | 复制中/成功 toast/409 冲突提示 | T8/T10 |
| 各页「搜索」入口 | R5/R7/R10 | 选择器区新增搜索按钮 | 按钮打开 `AssetSearchDrawer` | 各资产页 + 共享组件 | - | 无权限/无数据兜底 | T10/T11 |
| 下拉仅自己 | R3 | 下拉不含他人/内置 | list 调 `source=mine` | 各页 loadProfiles | list `source=mine` | 空态引导搜索 | T10/T11 |
| 移除系统内置徽标 | R1/R2 | 无「系统内置」字样 | 去 `preset` 分支与传参 | `AssetVisibilityTag`、各页 | - | - | T10 |

### 4.5 组件资产闭环

| 页面/区域 | 运行时复用组件 | 布局/配置组件种类 | 组件配置字段/页面注册 | 设计规范/组件清单更新 | 真实消费与验证 | 对应任务 |
| --- | --- | --- | --- | --- | --- | --- |
| 公开资产搜索抽屉 | 新增 `AssetSearchDrawer`（复用 PageDrawer/AppDataTable/AppFilterSelect/AppStateBlock/AppPagination/AssetVisibilityTag/AssetProfileLabel） | 不涉及 | 不涉及 | 是——按 DESIGN 组件/布局维护矩阵登记新通用组件 | 5+页真实接入（评分/筛选/买卖/回测/榜单/个股） | T8/T10/T11 |
| 资产选择器 | 新增/复用 `AssetProfileSelect`（复用 AssetProfileLabel） | 不涉及 | 不涉及 | 是——登记或说明保留双形态 | 各页选择器替换 | T9/T10 |
| 系统内置徽标 | 复用（切断资产引用，不删组件） | 不涉及 | 不涉及 | 是——DESIGN 说明资产不再用 preset 徽标 | 各页目视 + Vitest | T10 |

## 5. 需求与开发内容映射和开发状态

| 范围类别 | 需求编号 | 需求内容/来源 | 计划开发内容 | 对应任务 | 状态 | 偏差判断 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 必须实现 | R1 | 移除系统内置可见概念 | 去 AssetVisibilityTag preset 分支+各页传参 | T10 | 待开始 | 一致 | |
| 必须实现 | R2 | is_preset 降级后台标记 | 核实入库+前端解耦，后端不动榜单 | T1,T10 | 待开始 | 一致 | 方案 A |
| 必须实现 | R3 | 下拉仅自己 | list 加 source=mine + 各页接入 | T2,T10,T11 | 待开始 | 一致 | |
| 必须实现 | R4 | 放开普通用户发布权 | constants 重分类+撤 DELETE+新迁移回填 | T3 | 待开始 | 一致 | 安全边界变更 |
| 必须实现 | R5 | 统一公开资产搜索弹窗 | browse 接口 + AssetSearchDrawer | T5,T8,T10 | 待开始 | 一致 | |
| 必须实现 | R6 | 回测复制/另存 | 回测 copy（推荐6a）+ q | T6 | 待开始 | 待确认 | 6a/6b 阶段二定 |
| 必须实现 | R7 | 统一选择器+搜索组件 | AssetSearchDrawer/AssetProfileSelect | T8,T9 | 待开始 | 一致 | |
| 可选增强 | R10 | 个股详情接入 | 仅自己+搜索入口 | T11 | 待开始 | 一致 | 本次纳入 |
| 可选增强 | R9 | 新用户默认复制 | 暂不纳入 | - | 跳过 | 未覆盖 | 待产品确认 |
| 可选增强 | R8 | 公开资产治理入口 | 暂不纳入 | - | 跳过 | 未覆盖 | 后续建议 |
| 暂不实现 | R11 | 收藏 | 不做 | - | 跳过 | 未覆盖 | |
| 暂不实现 | R12 | 分组/训练接入 | 不做 | - | 跳过 | 未覆盖 | |
| 暂不实现 | R13 | 删 is_preset 列 | 不做（方案A） | - | 跳过 | 未覆盖 | |

## 6. 详细实施步骤与进度追踪

### 阶段一 · 后端资产可见性收口（R2/R3/R4）

#### 6.1 任务 T1：核实预设入库 + is_preset 解耦评估
- 状态：待开始
- 依赖：无
- 涉及文件/模块：`backend/scoring/score_profile.py:451`、`backend/signals/trade_profile.py:414`、`backend/screening/profile.py:266`、`backend/cli.py:221`、线上 PG
- 目标：确认评分/买卖预设线上真实入库方式，确认前端解耦后 `is_preset` 仅后台使用不受影响。
- 操作：查线上 `score_profile/trade_profile` 中 `is_preset=true` 行归属；确认榜单链路（`public_board.py`）不依赖前端传回 `is_preset` 标签。
- 产出：核实结论写入本任务「实际落地情况」。
- 影响范围：仅调研，无代码改动。
- 边界与异常：若线上预设入库方式与代码不一致，先记录风险再决定是否补 seed。
- 验证方式：SQL 抽样 + 榜单接口回归。
- 完成标准：明确预设归属与入库路径，无阻塞后进入 T2/T3。
- 实际落地情况：待实施。

#### 6.2 任务 T2：三类方案 list 增加 source=mine
- 状态：待开始
- 依赖：T1
- 涉及文件/模块：`score_profile.py`（repo）、`profile.py`、`trade_profile.py`、`api/score_profiles.py:52`、`api/profiles.py:67`、`api/trade_profiles.py:57`、`api/board.py:143`
- 目标：下拉可只取当前用户 owner 资产，返回结构与现有一致。
- 操作：repo 层新增 scoped 查询（source=mine 走归属过滤 + `decorate_asset_row`）；API 增加可选 `source` 参数，未传维持 `list_visible` 兼容；board 复用评分方案。
- 产出：三类方案 + 榜单方案 list 支持 `?source=mine`。
- 影响范围：list 接口向后兼容（默认不变）。
- 边界与异常：已选中的公开只读方案回显不能被 mine 过滤清空（前端 T10 配合）。
- 验证方式：`pytest backend/tests/`（新增 source=mine 用例，多账号归属断言）。
- 完成标准：mine 只返回自己资产，无他人/preset。
- 实际落地情况：待实施。

#### 6.3 任务 T3：放开普通用户发布权
- 状态：待开始
- 依赖：T1
- 涉及文件/模块：`backend/auth/constants.py:38-63`、`backend/storage/pg_ddl.py:1403-1408/1523-1568`、新迁移函数、`backend/main.py`（迁移装配）
- 目标：normal（及 tenant_admin 的 public）用户可自主租户/全体公开自己的资产。
- 操作：①constants 将 8 个发布码并入普通业务授权并改注释；②删除/反转两处撤权 DELETE；③新增带新 marker 的回填迁移，对存量库授 normal/tenant_admin 发布码 + 同事务 bump perm_ver；④确认 `require_visibility_perm` owner-only 与引用范围校验不变。
- 产出：发布码进入普通授权集合 + 存量库回填迁移。
- 影响范围：安全边界；受影响用户需重新登录（perm_ver）。
- 边界与异常：仍 owner-only；公开回测发布仍校验引用方案范围；新库 seed 与存量库回填两条路径都要覆盖。
- 验证方式：权限守卫测试 + 路由扫描测试 + 用普通调试账号验证发布生效且不能改他人资产。
- 完成标准：普通账号可发布自己资产到租户/全体；非 owner 仍 403。
- 实际落地情况：待实施。

#### 6.4 任务 T4：阶段一测试与留痕
- 状态：待开始
- 依赖：T2,T3
- 涉及文件/模块：`backend/tests/test_stage6_*`、`test_score_profile*`、权限/路由扫描测试、SQL 留痕文件
- 目标：可见性/发布权改动测试全绿，迁移留痕归档。
- 操作：更新受影响 stage6 断言（normal 现在有发布权）；补 source=mine 与发布放开用例；将回填迁移等价 SQL 留痕到 `agent-works/asset-ownership-refactor/asset-publish-open.sql`。
- 产出：测试通过 + SQL 留痕。
- 验证方式：`pytest backend/tests/ -q`（起测前按 AGENTS 判断 DuckDB 锁并 `./start.sh stop/restart`）。
- 完成标准：阶段一相关测试全绿。
- 实际落地情况：待实施。

### 阶段二 · 公开浏览接口与回测复制（R5 后端/R6）

#### 6.5 任务 T5：三类方案 browse 接口（source=tenant|public + q）
- 状态：待开始
- 依赖：T2
- 涉及文件/模块：三 repo、三 list API、`api/board.py`、`asset_visibility.py`
- 目标：为搜索弹窗提供公开资产浏览（脱敏 + 关键字 + 分页 + 排除自己）。
- 操作：扩展 scoped 查询支持 `source=tenant|public`（复用 `visible_sql` tenant/public 分支 + 排除自己）+ `q` 参数化 ILIKE + 分页；返回 `decorate_asset_row` 脱敏；榜单复用评分方案。
- 产出：三类方案 + 榜单 browse 能力。
- 影响范围：新增可授权浏览路径，需登记 `sys_resource`（若新增独立端点）或复用现有 list 守卫。
- 边界与异常：tenant 仅同租户；空 q 返回全部公开；结果集规模控制。
- 验证方式：接口测试（脱敏断言、排除自己、q 过滤、分页）。
- 完成标准：browse 只出公开、脱敏、可搜。
- 实际落地情况：待实施。

#### 6.6 任务 T6：回测复制/另存 + q
- 状态：待开始（含遗留取向确认）
- 依赖：T5
- 涉及文件/模块：`api/backtest.py`、`services/backtest_service.py`、`asset_audit.py`
- 目标：公开回测可复制/另存为当前用户 private；回测 browse 支持 q。
- 操作：按 6a 新增 `POST /api/backtest/runs/{run_ref}/copy`（复用 `_visible_run_row` 解析 + 复制审计），或 6b 定义重跑另存；回测 list 补 q。
- 产出：回测另存能力 + q。
- 边界与异常：引用方案可见性承接；`source_run_ref` 审计保留。
- 验证方式：接口测试（复制归属、可见源解析、q）。
- 完成标准：公开回测可另存为私有记录。
- 实际落地情况：待实施。

#### 6.7 任务 T7：阶段二接口测试
- 状态：待开始
- 依赖：T5,T6
- 目标：browse 与回测复制测试全绿。
- 操作：补脱敏、跨租户不可见、复制归属、q、分页用例。
- 验证方式：`pytest backend/tests/ -q`。
- 完成标准：阶段二相关测试全绿。
- 实际落地情况：待实施。

### 阶段三 · 前端统一组件与页面接入（R1/R5前端/R7/R10）

#### 6.8 任务 T8：新增通用组件 AssetSearchDrawer
- 状态：待开始
- 依赖：T5,T6
- 涉及文件/模块：新增 `frontend/src/components/AssetSearchDrawer.vue`；复用 `PageDrawer/AppDataTable/AppFilterSelect/AppStateBlock/AppPagination/AssetVisibilityTag/AssetProfileLabel`；各 `api/*.ts` 补 browse/copy 封装
- 目标：对齐原型的统一公开资产搜索抽屉。
- 操作：实现来源分段+防抖 q+分页+列表+行操作（加载查看 emit load / 复制 emit copied）；接入各资产类型 browse/copy API。
- 产出：可复用抽屉组件 + Vitest。
- 边界与异常：加载/空/错误/复制409/窄视口全宽。
- 验证方式：Vitest（分段切换、q、空态、复制事件）。
- 完成标准：组件覆盖原型全部区域与状态。
- 实际落地情况：待实施。

#### 6.9 任务 T9：资产选择器组件化（R7）
- 状态：待开始
- 依赖：T8
- 涉及文件/模块：新增 `AssetProfileSelect.vue`（或双形态封装）
- 目标：统一「我的方案选择器 + 搜索按钮」入口，减少 5 页重复。
- 操作：抽取选择器 + 搜索按钮公共契约，复用 `AssetProfileLabel`；评分/买卖侧栏列表形态与下拉形态差异做最小统一。
- 产出：选择器组件 + Vitest。
- 验证方式：Vitest + 各页接入回归。
- 完成标准：选择器与搜索入口共用组件。
- 实际落地情况：待实施。

#### 6.10 任务 T10：各资产页接入 + 移除系统内置徽标
- 状态：待开始
- 依赖：T8,T9
- 涉及文件/模块：`ScreenView.vue`、`ConfigView.vue`（评分+买卖）、`BacktestView.vue`、`BoardView.vue`、`AssetVisibilityTag.vue:55`
- 目标：下拉改 source=mine、接入搜索抽屉、去掉「系统内置」渲染、发布按钮随后端放开生效。
- 操作：各页 loadProfiles 改 source=mine；新增搜索按钮打开 `AssetSearchDrawer`；load 回显只读、copied 刷新我的下拉；删 `AssetVisibilityTag` preset 分支与各页 `p.is_preset?...` 传参。
- 产出：4 页接入 + 徽标移除。
- 边界与异常：已选中公开只读方案回显不被 mine 过滤清空。
- 验证方式：Vitest + E2E（`npm run test:e2e`，5181 端口）+ 目视无「系统内置」。
- 完成标准：各页仅自己下拉 + 搜索弹窗可用 + 普通用户可发布。
- 实际落地情况：待实施。

#### 6.11 任务 T11：个股详情接入（R10）
- 状态：待开始
- 依赖：T10
- 涉及文件/模块：`StockDetailView.vue:947-960`
- 目标：买卖方案选择仅自己 + 搜索入口。
- 操作：接入 `AssetProfileSelect` + `AssetSearchDrawer`（trade-profile）。
- 验证方式：页面验证 + E2E。
- 完成标准：个股详情买卖方案与其他页一致。
- 实际落地情况：待实施。

#### 6.12 任务 T12：前端测试、构建与设计闭环
- 状态：待开始
- 依赖：T10,T11
- 涉及文件/模块：Vitest、E2E、`DESIGN.md` 组件/布局维护矩阵、`frontend/dist`
- 目标：前端回归通过，新组件登记，构建同步。
- 操作：跑 Vitest + `npm run test:e2e`；DESIGN 登记 `AssetSearchDrawer`/`AssetProfileSelect` 与「资产不再用 preset 徽标」；`npm run build`。
- 验证方式：测试全绿 + build 成功 + dist 同步。
- 完成标准：前端交付红线满足（AGENTS 端口与构建）。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划

- 本次**不新增表、不删列**（保留 `is_preset`；不做收藏）。
- 数据变更为**权限授权回填**（Python 迁移 + 新 marker，遵循项目 `pg_ddl.py` seed 迁移模式，非独立 .sql 主执行）。
- SQL 留痕文件：`agent-works/asset-ownership-refactor/asset-publish-open.sql`
  - 用途：记录给 `ROLE_NORMAL`（及 `ROLE_TENANT_ADMIN` public）授 8 个发布码、撤销原撤权 DELETE 的等价 SQL，供审计与手工核对。
  - 执行时机：随后端启动迁移（新 marker）自动应用；留痕文件用于人工复核，不作为独立执行入口。
  - 影响范围：`sys_role_resource` + 受影响用户 `perm_ver`。
  - 回滚方式：可逆——反向 DELETE 已授发布码 + bump perm_ver；回滚会使普通用户失去发布权。

## 8. 测试与验证计划

- 单元测试：
  - 计划：repo scoped 查询（mine/tenant/public + q + 排除自己 + 脱敏）、发布码授权解析、回测 copy 归属。
  - 具体完成情况：待验证。
- 接口测试：
  - 计划：三类方案 list `source=mine`；browse `source=tenant|public`+q+分页+脱敏；发布放开后普通用户可发布、非 owner 403；回测 copy；路由扫描 + 资源码/菜单 seed。
  - 具体完成情况：待验证。
- 页面/交互测试：
  - 计划：Vitest（AssetSearchDrawer 分段/q/空态/复制事件、AssetVisibilityTag 无 preset）、E2E（搜索弹窗浏览→加载→复制→我的下拉出现；下拉仅自己；普通账号发布）。
  - 具体完成情况：待验证。
- 组件资产闭环测试：
  - 计划：验证 AssetSearchDrawer/AssetProfileSelect 在 5+ 页真实消费；DESIGN 组件矩阵登记；系统内置徽标资产引用已切断。
  - 具体完成情况：待验证。
- 权限与数据范围测试：
  - 计划：用 `test-users.md` 多角色账号验证发布放开、mine 隔离、跨租户 tenant 不可见、owner 脱敏。
  - 具体完成情况：待验证。
- 回归测试：
  - 计划：榜单接口（is_preset 保留）回归、现有 copy/visibility 链路回归、stage6 断言更新后回归。
  - 具体完成情况：待验证。
- 异常与边界测试：
  - 计划：下拉为空引导、已选公开只读回显不被清空、复制 409、q 空/特殊字符、停用降级复用。
  - 具体完成情况：待验证。
- 图示与原型一致性验证：AssetSearchDrawer 实现覆盖原型全部区域（页头/工具栏/列表/操作列/分页）、关键状态与窄视口退化。
- 需求映射验证：R1–R7、R10 均有任务与可观察验证；R8/R9/R11/R12/R13 跳过并说明。
- 页面功能点验证：§4.4 表所有功能点均有任务与状态。

## 9. 发布与回滚

- 发布前检查：核实预设入库（T1）；确认新迁移 marker 未与既有冲突；`pytest` 与前端测试全绿；`npm run build` 同步 dist。
- 发布步骤：后端先上（迁移随启动回填授权 + perm_ver bump，受影响用户重新登录）→ 前端上。
- 配置或环境变量：无新增；沿用 PG/Redis 与现有鉴权配置。
- 回滚方案：前端回滚独立；后端授权回填可逆（反向撤销发布码 + bump perm_ver）；`is_preset` 未改无数据回滚风险。

## 10. 风险、假设与待确认项

### 10.1 风险
- **[高] 放开发布权是安全边界变更**（R4/T3）：公开资产将显著增多。缓解：owner-only 校验不变、复用停用降级机制、保留引用范围校验；建议 R8 治理入口列后续。
- **[中] stage6 既有测试断言**：normal 无发布权的断言需批量更新，避免误判回归。
- **[中] 迁移对存量库**：旧 marker early-return，必须用新 marker 回填，否则存量库普通用户拿不到发布权。
- **[低] 选择器双形态**：评分/买卖侧栏列表与下拉形态差异，组件抽取需保留形态差异，避免过度统一破坏现有交互。

### 10.2 假设
- 采用方案 A：`is_preset` 列与榜单机制保留，仅前端解耦。
- R6 默认按 6a（新增回测 copy）推进，阶段二可改 6b。
- browse 复用现有 list 守卫资源码；若新增独立端点则同步 `sys_resource` seed 与路由扫描测试。

### 10.3 待确认项（不阻塞阶段一）
- R6 取向 6a/6b：阶段二动手前定。
- R9 新用户冷启动引导：待产品确认。
- T1 预设入库核实结论：影响是否需补 seed。
