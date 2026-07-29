# 开发计划 · 资产归属重构（asset-ownership-refactor）

## 1. 需求来源与目标
- 需求文档：[requirement.md](./requirement.md)（R3–R14，含 §0 上游确认 C1–C9）
- 原型：[prototypes/public-asset-search-drawer.html](./prototypes/public-asset-search-drawer.html)
- 功能目标：下拉只加载自己的资产（C2/R3）；放开普通用户发布（C4/R4）；统一「资产搜索」弹窗，来源分段 系统内置/租户公开/全体公开（C3/R5/R14），加载查看 + 单击复制（后端自动 id/名称，C8）；回测「另存」= 复用参数重跑（C7/R6）；抽共享组件（R7）；个股详情接入（R10）。
- 本次不做：R1/R2（保留系统内置，撤销）、R11 收藏、R12 分组/训练、R13 删 is_preset 列（依据 C1，保留不删）。「不迁移预设」为 C9/R14 范围边界，非 R13。
- 关键取舍（已确认）：C7 重跑不复制快照；C8 复制后端自动生成 id、名称「原名 副本」；C9 系统内置严格 `is_preset AND public`（限平台槽）、不迁移。

## 2. 当前项目依据（校准后）
- 复制契约：请求体强制 `id`、`name` 可选（`api/score_profiles.py:40-42`）；`copy_visible` 冲突判据是**目标 id 已存在**（`scoring/score_profile.py:394`），缺省名落「原名 副本」（`:396`）。→ C8 由后端生成唯一 id。
- 预设自动公开：**仅评分方案**在平台槽下 save 自动置 public（`score_profile.py:288-290`）；筛选/买卖 save 无 public 联动（`screening/profile.py:76`、`signals/trade_profile.py:206`）→ R14 严格条件下筛选/买卖系统内置段常态可能为空。
- 可见性工具：`visible_sql`（`services/asset_visibility.py:231-237`）是**单一合并表达式**，source 分段需在其上叠加独立条件（回测 `services/backtest_service.py:477-485` 即此模式）；`summarize_asset_row`（`:199-228`）**不含 `updated_at`**，需补。
- 回测表：`backtest_run` **无 is_preset/name/version/updated_at**，有 kind/date_start/date_end/status/created_at/finished_at/visibility（`storage/pg_ddl.py:333-354`）→ 回测需独立 summary 与表格列。
- 角色：仅 `system/tenant_admin/normal`（`auth/constants.py:10-15`），无 paid。
- 发布权：`constants.py:52-63` 发布码未入 BUSINESS；撤权 DELETE `pg_ddl.py:1403-1408`（stage4）与 `1543-1548`（stage6）；stage6 迁移 `seed_stage6_asset_visibility:1523-1568` 有 marker 提前返回（存量库须新 marker 回填）。
- 前端权限位：各页 `hasPermission(...'*:publish-tenant/public')` 计算 `canPublishTenant/canPublishPublic`（`ScreenView.vue:261-264` 等），放开后端后自动生效。
- DESIGN 硬契约：`PageDrawer` 语义档位（本抽屉 `xl`，`DESIGN.md:194`）、`AppDataTable+AppTableColumn`（`:258`）、`AppRowActions`（`:204,267`）、`AppIconButton` 且禁 Unicode 图标（`:203,246-248`）、`AppStateBlock` 四态（`:139,292`）、关键视口 1100×620/1366×768/1440×900。

## 3. 实施范围
### 3.1 必须实现
- R3 下拉仅自己（T2A + T3/T4/T5 接入）
- R4 放开普通用户发布权（T1B）
- R5 搜索弹窗外壳 + 租户/全体浏览 + 复制（T2B 后端 + T3 前端）
- R14 系统内置来源段（严格 public，T2B 后端 + T3 前端）
- R6 回测复用参数重跑（T2C）
- R7 共享组件（T3）
- R10 个股详情接入（T4）

### 3.2 可选增强
| 需求编号 | 内容 | 需求处理状态 | 开发状态 | 对应任务 | 说明 |
| --- | --- | --- | --- | --- | --- |
| R9 | 新用户默认复制基础方案 | 待确认 | 跳过 | - | 需产品确认 |
| R8 | 公开资产治理/下架入口 | 后续建议 | 跳过 | - | 现有停用降级先兜底 |

### 3.3 暂不实现
- R1/R2（保留系统内置，撤销）、R11 收藏、R12 分组/训练接入、R13 删 is_preset 列（依据 C1，保留不删）。「不迁移预设」为 C9/R14 范围边界，非 R13。

## 4. 技术方案

### 4.1 取数口径（互斥、可审计）
统一在 repo 层新增 `list_scoped(source, q, page)`（或 API 层分派），四来源互斥：
- `mine` → `WHERE tenant_id=? AND owner_user_id=?`（纯 owner，R3，下拉用）。
- `preset` → `WHERE is_preset=true AND visibility='public' AND (tenant_id,owner_user_id)=PUBLIC_BOARD_OWNER`（R14，严格只读公开，永不泄露 private）。
- `tenant` → `visibility='tenant' AND tenant_id=? AND NOT own`（排除自己）。
- `public` → `visibility='public' AND NOT own AND NOT (is_preset=true AND (tenant_id,owner_user_id)=PUBLIC_BOARD_OWNER)`（**强制补集**：平台槽公开预设只归「系统内置」段，四来源真正互斥，不重复出现）。
不传 `source` → 维持 `list_visible` 兼容。所有分支经 `decorate_asset_row` 脱敏；`summarize_asset_row` 补 `updated_at`（方案表有列）。

### 4.2 回测独立模型（R6）
回测无 is_preset/name/version/updated_at：
- 独立 summary：id/kind/date_start/date_end/status/created_at/finished_at/visibility/source/readonly/owner_label。
- browse `source∈{tenant,public}`（无 preset 段）+ `q`：**`q` 匹配三类引用方案名称 + kind**（回测无自身 name）。发布态回测的方案引用列已改写成 opaque ref，SQL JOIN 裸 id 取不到名，故 **`q` 在解析 ref、补全方案名之后于 Python 侧全量过滤**（correctness 优先，不设扫描上限以免漏匹配/破坏 `limit=None`；规模化优化留 T5）。
- 「另存」= 复用参数重跑：走现有重跑链路（`source_run_ref` 透传 + `_record_reuse_if_needed` 审计），新 run 归当前 owner private；**不新增 copy 接口**（C7）。
- **执行模型（已核实）**：现有 `POST /api/backtest/run` **同步执行**、同步返回落库（`backtest.py:3,7-8`，异步是 M7 规划）。R6 **保持同步**：前端按钮 loading + 成功/失败反馈；DuckDB 单写锁串行；**本次不做异步化**。

### 4.3 发布权放开（R4，安全边界）
1. `constants.py`：8 个发布码并入普通业务授权，改注释。
2. 删除/反转撤权 DELETE（`pg_ddl.py:1403-1408`、`1543-1548`）。
3. 新增 marker（`migration.asset_publish_open_v2`）回填迁移：事务级 advisory lock 串行 + 锁内 marker 判定（已应用则整段 no-op）；给 normal（及 tenant_admin 的 public）授 8 码 `ON CONFLICT DO NOTHING`，仅确有新增才 bump `perm_ver`。回滚走**确定性基线恢复**（恢复 C4 前默认角色策略，见 §9），不依赖 marker 内容。
4. 守卫 owner-only 与引用范围校验不变；SQL 留痕 `asset-publish-open.sql`（含回滚）。

### 4.4 复制流程（C8）
**接口契约变更（必须）**：三类 `*CopyBody`（`api/score_profiles.py:40`、`profiles.py:43`、`trade_profiles.py:45`）当前强制 `id: str` → 改为**去掉必填 id、仅保留可选 `name`**（前端不传 id）。`copy_visible(profile_ref_or_id, new_name)` 调用方改为：后端生成 `new_id`（基于名称的可读 id + 撞库追加序号后缀去重），**撞库有限次（5 次）换新 id 重试**，仍失败回可读错误码；`new_name` 缺省「原名 副本」。写入用**同一事务同一游标**原子插入主表 + 版本表（`ON CONFLICT DO NOTHING`；主表 0 行即撞库、版本表失败整体回滚，杜绝半成品）。**路由返回体扩展为含新 `id`/`profile_ref`/`name`/`version`**，前端据此刷新「我的」下拉并选中。三类方案各改一处请求模型 + 路由 + repo 调用 + 返回结构（落 T2B）。

### 4.5 前端组件与页面（R5/R14/R7/R10）
- 新增 `AssetSearchDrawer.vue`：`PageDrawer size="xl"`（挂 `#overlays`）+ `AppDataTable/AppTableColumn` + `AppRowActions` + `AppStateBlock` + `AppIconButton`（关闭/搜索，**无 Unicode 图标**）；props：`assetType`、来源段配置（回测隐藏 preset）、列配置（方案类/回测两套）、browse/copy/rerun 回调；events：`load`（临时只读注入）、`copied`（刷新我的）、`rerun`（回测重跑）。
- 新增/封装 `AssetProfileSelect.vue`：五页**全部**方案选择器实例（含回测评分/选股/买卖 3 个）统一消费同一组件，通过 `mode`（`list` 侧栏列表 / `select` 下拉）保留形态差异，复用 `AssetProfileLabel`；不允许任一页保留私有同类选择器逻辑。
- 临时只读契约（§7.0）：加载对象注入选择器顶部标 readonly，不进「我的」，不持久化，不自动运行。
- 系统内置徽标/`AssetVisibilityTag`/`is_preset` 传参**全部保持现状**，仅展示位置从下拉挪到搜索弹窗系统内置段。

### 4.6 页面 P1 技术实现表

| 页面功能点 | 需求编号 | 交互要点 | 技术实现 | 组件/模块 | 数据/API | 状态与异常 | 任务 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 来源分段+关键字 | R5/R14 | 三段（回测无 preset），防抖 q | segment + 防抖，触发 browse | AssetSearchDrawer/AppDataTable/AppStateBlock | browse `source=preset\|tenant\|public`+q+分页 | 加载/空（含系统内置空态）/错误重试 | T3 |
| 加载查看 | R5/R14 | 关闭抽屉，临时只读注入 | emit load，父页顶部只读项 | 各页选择器 | 复用返回 ref | readonly 展示，不自动运行 | T3/T4/T5 |
| 复制为我的 | R5/R14 | 单击，后端自动 id/名称 | emit copied，刷新我的 | /copy | `POST .../{ref}/copy` | 成功 toast / 撞库重试 / 无权错误 | T3 |
| 回测复用重跑 | R6 | 公开回测参数**同步**重跑 | emit rerun，按钮 loading | 回测同步重跑链路 | 现有 sync run + source_run_ref | loading/成功/失败 | T5 |
| 下拉仅自己 | R3 | 纯 owner，空态引导搜索 | list `source=mine` | 各页 loadProfiles | list `source=mine` | 空态引导「系统内置」段 | T3/T4/T5 |

组件资产闭环：

| 页面/区域 | 运行时复用组件 | 配置字段/页面注册 | 组件清单更新 | 真实消费与验证 | 任务 |
| --- | --- | --- | --- | --- | --- |
| 资产搜索抽屉 | 新增 AssetSearchDrawer（复用 PageDrawer xl/AppDataTable/AppTableColumn/AppRowActions/AppStateBlock/AppIconButton/AssetVisibilityTag/AssetProfileLabel） | 不涉及 | 是——DESIGN 组件/布局矩阵登记 | 先 ScreenView 样板，再 4 页扩展 | T3/T4/T5 |
| 资产选择器 | 新增 AssetProfileSelect（复用 AssetProfileLabel + 现有系统内置徽标） | 不涉及 | 是——说明双形态 | 各页选择器替换（含回测 3 个，T5） | T3/T4/T5 |

## 5. 需求与开发内容映射和开发状态

| 范围 | 需求编号 | 需求内容/来源 | 开发内容 | 任务 | 状态 | 偏差 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 必须 | R3 | 下拉仅自己（C2） | list source=mine（纯 owner）+ 各页接入 | T2A,T3,T4,T5 | 后端完成·ScreenView 样板完成·3 页待扩展 | 一致 | 后端 T2A 已过；T3 筛选页接入；含平台槽互斥修复 |
| 必须 | R4 | 放开发布权（C4） | 发布码归类+撤 DELETE+新迁移回填 | T1B | 后端完成 | 一致 | 安全边界；回滚 SQL 已精准化 |
| 必须 | R5 | 搜索弹窗+租户/全体+复制（C3/C8） | browse tenant/public + AssetSearchDrawer + 复制 | T2B,T3 | 后端完成·ScreenView 样板完成 | 一致 | 复制已改原子插入；抽屉/选择器 T3 落地 |
| 必须 | R14 | 系统内置来源段（C3/C9） | browse source=preset 严格 public + 前端段 | T2B,T3 | 后端完成·ScreenView 样板完成·生产核验挂起 | 一致 | 筛选空态（E2E 已断言）；生产分布待 T0 |
| 必须 | R6 | 回测复用重跑（C7） | 回测独立 summary + q + 重跑入口 | T2C,T5 | 后端完成·前端待 | 一致 | q 已修发布态 ref 搜索 |
| 必须 | R7 | 共享组件 | AssetSearchDrawer/AssetProfileSelect | T3 | 组件完成·ScreenView 已消费·4 页待扩展 | 一致 | select/list 双形态已实现；list 真实消费留 T4 |
| 必须 | R10 | 个股详情接入 | 仅自己 + 搜索 | T4 | 待开始 | 一致 | |
| 可选 | R9 | 新用户默认复制 | 暂不纳入 | - | 跳过 | 未覆盖 | 待产品确认 |
| 可选 | R8 | 公开资产治理 | 暂不纳入 | - | 跳过 | 未覆盖 | 后续建议 |
| 暂不 | R1 | 移除系统内置徽标 | 撤销（保留） | - | 跳过 | 未覆盖 | C1 |
| 暂不 | R2 | is_preset 降级 | 撤销（保留） | - | 跳过 | 未覆盖 | C1 |
| 暂不 | R11 | 收藏 | 不做 | - | 跳过 | 未覆盖 | C6 |
| 暂不 | R12 | 分组/训练接入 | 不做 | - | 跳过 | 未覆盖 | |
| 暂不 | R13 | 删 is_preset 列 | 不删除 is_preset 列 | - | 跳过 | 未覆盖 | C1 |

## 6. 详细实施步骤与进度追踪

### 阶段 0 · 线上数据基线核验（发布门禁，不阻塞开工）

#### 6.0 任务 T0：预设归属线上数据基线核验
- 状态：已完成（本地/dev 只读核验）·生产核验挂起　依赖：无（可与 T1A/T1B 并行；仅门禁 R14 数据验收与发布，不决定是否进入 T1）
- 涉及：线上 PG（`score_profile/screen_profile/trade_profile`）、`services/public_board.py`、§0 映射
- 目标：核实线上评分/筛选/买卖预设真实 `owner/is_preset/visibility`，确认 R14 严格条件（`is_preset AND public AND 平台槽`）命中数量符合预期、筛选/买卖系统内置段是否常态为空。产出：命中数量与预期空态核验报告（不冻结取数契约、不作为进入 T1 的前置）。
- 操作：SQL 抽样统计三类预设的 owner/is_preset/visibility 分布；确认是否存在 is_preset 但非平台槽/非 public 的数据。
- 产出：命中数量与预期空态核验报告写入本任务「实际落地情况」。
- 验证：SQL 抽样 + 榜单接口回归。
- 完成标准：线上预设 owner/is_preset/visibility 分布已核实，R14 数据验收与发布门禁可判定（不作为 T1A/T1B 开工前置）。
- 实际落地情况：**已核验（2026-07-27，本地/dev 库，只读 PG，未写库）**。`PUBLIC_BOARD_OWNER=('default','admin')`。分布：
  - 评分 `score_profile`：共 2 行 = 1 preset(public，平台槽) + 1 私有；**R14 命中 1**；不满足严格条件的 preset = 0。
  - 筛选 `screen_profile`：共 7 行 = 5 preset(**全 private**，平台槽) + 2 私有；**R14 命中 0（系统内置段常态为空，符合预期）**；5 条 private preset 被严格条件挡住、**零泄露**。
  - 买卖 `trade_profile`：共 2 行 = 2 preset(public，平台槽)；**R14 命中 2**；不满足严格条件的 preset = 0。
  - **结论**：严格条件 `is_preset AND public AND 平台槽` 逻辑正确，private preset 零泄露；R14 命中数 = 平台槽 public preset 数。**偏差修正**：原预期「仅评分系统内置段有内容、筛选/买卖常态空」不准确——实测**买卖系统内置段非空(2 条)**，**只有筛选是空态**。空态兜底文案对筛选必需、对买卖非必需。
  - **样本边界**：本地 dev 库总量极小(2/7/2)，不代表生产分布；生产上线前须在生产库重跑本核验作为 R14 数据验收门禁。核验脚本口径见本条 SQL（`GROUP BY is_preset,visibility` + 平台槽严格命中/泄露探针）。

### 阶段 1 · 数据与权限契约

> **T0 门禁范围（重要）**：T0 是只读事实核验，**仅门禁 R14 系统内置段的数据验收与上线发布**（决定各类系统内置段实际内容/空态）；**不门禁** T1A/T1B/T2A/T2C/前端组件等与预设分布无关的任务，它们可与 T0 并行。

#### 6.1 任务 T1A：取数契约与 summary 字段
- 状态：已完成（后端·定向测试通过）　依赖：无（可与 T0 并行）
- 涉及：三 repo、`services/asset_visibility.py:199`（summarize 补 updated_at）
- 目标：定 `mine/preset/tenant/public` 互斥取数；方案类 summary 补 `updated_at`；回测独立 summary 字段清单。
- 操作：实现/约定 `list_scoped`；`summarize_asset_row` 增加 `updated_at`；回测定义独立 summary。
- 产出：可复用取数与 summary 契约 + 单测。
- 验证：单测（四来源互斥、preset 负例不含 private、updated_at 存在）。
- 完成标准：契约与单测通过。
- 实际落地情况：**已完成**。`asset_visibility.py` 新增 `scoped_where(source,...,has_preset)` 四来源互斥纯函数（mine/preset/tenant/public，public 强制补集排除平台槽预设；has_preset=False 时 preset 不支持、public 省略补集）+ `SCOPE_*`/`PROFILE_SCOPES`/`BACKTEST_SCOPES` 常量；`summarize_asset_row` 补 `updated_at`；新增 `summarize_backtest_row`（独立字段、无 name/version/is_preset、owner 脱敏、run_ref）。单测 `test_stage6_asset_visibility.py` +8 用例，全量 19 passed。repo 层 `list_scoped`/API 接入落 T2A/T2B/T2C。

#### 6.2 任务 T1B：放开普通用户发布权
- 状态：已完成（后端·定向测试通过；回滚 SQL 已精准化）　依赖：无（与 T0 无关，可并行）
- 涉及：`auth/constants.py:52-63`、`pg_ddl.py:1403-1408/1523-1568`、新迁移、`asset-publish-open.sql`
- 目标：normal（及 tenant_admin 的 public）可自主公开。
- 操作：①发布码并入普通授权+改注释；②删/反转两处撤权 DELETE；③新 marker 回填迁移（授权 + perm_ver bump，同事务）；④owner-only/引用范围校验不变；⑤SQL 留痕含回滚。
- 产出：发布放开 + 存量库回填 + 留痕。
- 影响：安全边界；受影响用户需重新登录（perm_ver）。
- 验证：权限守卫 + 路由扫描 + stage6 断言更新；normal 账号可发布、非 owner 403。
- 完成标准：普通用户可发布自己资产、不能改他人。
- 实际落地情况：**已完成**。①`constants.py` 发布码注释改为 C4 语义（放开、仍 owner-only）；②`_seed_role_grants` 给 normal/tenant_admin 授全部 8 发布码（新装）；③移除 stage4 的 normal `publish-tenant` 撤权 DELETE、stage6 的两处撤权 DELETE（改为 tenant_admin 授 tenant+public）；④新增 `_backfill_asset_publish_open_v1`（marker=`migration.asset_publish_open_v2`、advisory lock 串行、锁内判定 no-op、`ON CONFLICT DO NOTHING`、仅确有新增才 bump perm_ver）存量回填，接入 seed 序列；⑤`asset-publish-open.sql` 留痕含**确定性基线回滚**（plpgsql，lock+守卫+条件 bump，等价 Python）；⑥更新 `test_rbac_schema.py` 断言（normal/tenant_admin 现有全部发布码、stage6 授 tenant+public、stage4 解耦发布码）+ 新增 `test_asset_publish_open_backfilled_for_normal`（授权+perm_ver+幂等）。守卫 owner-only 未改。测试：发布/可见性 + RBAC 全绿 37 passed（停服释放 DuckDB 锁后跑，已重启健康 200）。

### 阶段 2 · 后端接口

#### 6.3 任务 T2A：三类方案 list source=mine（纯 owner）
- 状态：已完成（后端·定向测试通过）　依赖：T1A
- 涉及：三 repo、`api/score_profiles.py:52`、`api/profiles.py:67`、`api/trade_profiles.py:57`、`api/board.py:143`
- 目标：下拉仅自己。
- 操作：list 增加 `source=mine`（纯归属 + decorate）；未传维持 list_visible；board 复用评分；回测沿用现状。
- 验证：多账号 list 测试（仅自己、排除系统内置与他人公开）。
- 完成标准：mine 只返回自己资产。
- 实际落地情况：**已完成**。`asset_visibility.py` 新增依赖注入 `scoped_query(pg,table,source,...)`（方案类共用列/排序，支持分页与 q）；三 repo 各加 `list_mine()`（复用 scoped_query mine 段）；`api/score_profiles.py`/`profiles.py`/`trade_profiles.py`/`board.py` 的 list 端点加 `source` 参数：`source=mine` 走 `list_mine`，不传维持 `list_visible` 兼容。新增 `test_asset_list_mine.py`（2 用例：只返回自己、排除他人租户/全体公开与系统内置预设），4 passed（含既有 screen repo 回归）。

#### 6.4 任务 T2B：三类方案 browse（preset|tenant|public + q）
- 状态：已完成（后端·定向测试通过）　依赖：T1A
- 涉及：三 repo、三 list API、`api/board.py`
- 目标：搜索弹窗三来源浏览。
- 操作：`preset` → 严格 `is_preset AND public AND 平台槽`；`tenant|public` → 叠加 source 条件 + 排除自己，**`public` 强制补集排除平台槽公开预设**（§4.1）；`q` ILIKE + 分页；summary 脱敏；榜单复用评分。**并含复制接口契约变更**（三类 `*CopyBody` 去必填 id、后端生成 id/名称、有限次撞库重试、返回 new id/ref/name/version，§4.4）。
- 影响：新增浏览路径，登记 `sys_resource`（若独立端点）或复用 list 守卫 + 路由扫描测试。
- 验证：接口测试（三来源互斥、public 不含平台槽预设、preset 负例 private 不出现、脱敏、排除自己、q、分页、复制返回新标识）。
- 完成标准：三来源真正互斥、系统内置严格公开、复制返回可用标识。
- **R14 数据验收门禁 T0**：系统内置段「实际返回内容」的验收在 T0 核实后进行；代码实现不被 T0 阻塞。
- 实际落地情况：**已完成**。①三 repo 各加 `browse(source,q,page,page_size)`（复用 scoped_query，preset 严格公开/tenant/public 强制补集，分页+q），list API（score/screen/trade/board）`source∈{preset,tenant,public}` 分派 browse，复用 `*:view` 守卫，不新增端点/资源码；②复制契约（C8）：三类 `*CopyBody` 去掉必填 `id`，`copy_visible(ref,new_name)` 后端生成唯一 id + 名称「原名 副本」+ 撞库 5 次换 id 重试，写入走同一事务原子插入主表+版本表，路由返回 `id/profile_ref/name/version`；③更新既有 copy 测试（score repo + 三处 API 可见性）为单击即复制无 409、按返回 id 查审计；新增 `test_asset_browse_copy.py`（preset 私有零泄露、public 强制补集排除平台槽预设、tenant/public 排除自己+q+分页+脱敏、复制后端生成 id/返回 ref）。测试：T2A/T2B + 相关回归 45 passed（停服跑，已重启健康 200）。

#### 6.5 任务 T2C：回测独立 summary + q + 重跑另存
- 状态：已完成（后端·定向测试通过）　依赖：T1A
- 涉及：`api/backtest.py`、`services/backtest_service.py`
- 目标：回测浏览（tenant/public，无 preset）+ 复用参数重跑。
- 操作：回测独立 summary（无 name/version/is_preset）；`q` 匹配三类引用方案名称 + kind（发布态方案引用为 opaque ref，**解析 ref、补名后 Python 侧全量过滤**，不设上限）；「另存」= 现有**同步**重跑链路（source_run_ref + 审计），**保持同步、本次不异步化**（`backtest.py:3,7`），不新增 copy。
- 验证：接口测试（回测 summary 字段、q 口径、同步重跑归属当前 owner、审计 source_run_ref）。
- 完成标准：回测浏览与同步重跑符合 C7。
- 实际落地情况：**已完成**。①回测独立 summary：`list_runs`/`_decorate_run_row` 已产出独立字段（kind/date/status/visibility/source/readonly/owner_label + 三方案名，无自身 name/version/is_preset）并 owner 脱敏；T1A 另留 `summarize_backtest_row` 作契约。②`list_runs`+API 新增 `q` 参数：匹配三类引用方案名（screen/score/trade）+ kind，**解析发布态 opaque ref、补名后 Python 侧全量过滤**（correctness 优先、不设上限；ORDER BY 末位补完整主键三元组稳定唯一键）；`source` 复用现有 mine/tenant/public（无 preset 段）。③同步重跑：`/api/backtest/run` 同步执行、`_record_reuse_if_needed` 在 run_signal/run_strategy 记录 `source_run_ref` 审计——本就实现，未改。新增 `test_backtest_browse_q.py`（q 命中方案名/kind、无 q 全出）；重跑审计由既有 `test_stage6_backtest_visibility` 覆盖。测试 9 passed（停服跑，已重启健康 200）。

#### 6.5.1 阶段 2 审查修复（Request Changes 闭环）
一轮阶段 2 审查提出 4 个 P1 + 若干 P2，已逐条核实（均属实、非误报）并修复：
- **P1-1 发布态回测 q 失效**：发布回测的方案引用列被改写成 opaque ref，`list_runs` 原在 SQL 侧按 JOIN 裸 id 的方案名过滤 → 发布态 0 命中。改为**解析 ref、补全方案名后在 Python 侧过滤**（名称 + kind），`limit` 在过滤后截断。新增 `test_asset_review_fixes::test_published_backtest_q_matches_referenced_profile_name`。
- **P1-2 复制并发原子性**：copy「先查后 save」+ `save` 的 `ON CONFLICT DO UPDATE` 在并发/双击撞库时会合并甚至覆盖同 id 既有资产。三类 repo 改用专用 `_insert_copy`（`INSERT ... ON CONFLICT DO NOTHING` + 受影响行数判定），仅真正插入才返回，撞库换新 id 重试（5 次）。新增不覆盖既有资产的回归。
- **P1-3 平台槽 mine 与 preset 不互斥**：`scoped_where` mine 段在 `has_preset` 时补 `NOT(平台槽公开预设)`，使平台槽（`default/admin`）账号下 mine 不再混入系统内置；非平台槽用户不受影响。新增平台槽 owner 集成回归。
- **P1-4 回滚 SQL 过度删除**：一轮改为「精准恢复假定基线」（normal 删 8 码、tenant_admin 仅删 4 个 public 码）——**此口径已被 R2/R3 的 granted 精准回滚取代**（见下），不再依赖任何基线假定。
- **P2**：未知 `source` 四处 list 端点返回 400（原静默回退 list_visible）；`browse` 回显 clamp 后的 page/page_size；plan 状态闭环 + T0 生产核验挂起表述；原型空态按本地 dev 事实（评分/买卖非空、筛选空）同步。

**二轮审查（R2）复审关闭**——一轮修复中两处仅「半修」，二轮补齐为真原子/真可逆：
- **R2-P1 复制事务原子性**：一轮 `_insert_copy` 主表、版本表是两次独立 `execute()`（各自提交），故障注入下会残留「主表有行、无版本历史」。改为**同一 `transaction()` 同一 `cursor()`** 写两表：主表 `ON CONFLICT DO NOTHING` 0 行即撞库（换 id 重试），版本表失败整体回滚。三类 repo 一致。
- **R2-P1 回滚精准可逆**：一轮回滚是「恢复假定基线」，若存在人工授权会误删。改为正向迁移用 `INSERT ... ON CONFLICT DO NOTHING RETURNING` 记录**本迁移实际新增**的 `(role_id,resource_id)` 进 marker.value 的 `granted`；回滚只删这批记录行（SQL 用 `jsonb_array_elements` 读 granted），不误伤迁移前已存在/人工授予的授权。
- **R2-P2 回测 q 有界扫描**：一轮有 q 时取消 SQL LIMIT 拉全集再逐条解析 ref，成本随公开回测增长无界。二轮改为有界分批扫描——**但引入了新的漏匹配（见 R3）**，三轮撤销。
- **R2 测试补齐**：三类 repo 事务回滚（主表成功/版本表失败 → 双表零残留）、撞库候选（同 id 既有 → 第二次插入 False 不覆盖）、score/trade 两实现、未知 source 400 + 分页 clamp API 回归。

**三轮审查（R3）复审关闭**——R2 又引入/遗留 4 处，三轮逐条修正：
- **R3-P1 回测 q 上限静默漏匹配**：R2 的有界扫描（上限 2000）会漏掉靠后的匹配、且破坏 `limit=None` 全列契约。**撤销上限**，恢复「全量取数 + 解析 ref 补名 + Python 过滤」的正确语义，`ORDER BY` 末位补 `r.id` 稳定唯一键。规模化的成本优化（keyset/冗余搜索列）留 T5 回测前端按其分页 UX 设计（本节末备注 + 跟踪任务），**correctness 优先，不以静默截断冒充完整搜索**。
- **R3-P1 复用 v1 marker 使新回滚失效**：已跑过 v1 的库停在 `{"applied":true}` 旧格式、`granted` 永不落地。**换新 marker `..._v2`**（已跑 v1 的库会重新执行 v2 记录 granted）；生产尚未执行任何版本（T0 生产核验挂起），故生产 granted 天然准确。
- **R3-P1 迁移并发/SQL 幂等破坏 granted**：marker 判定移入**同一事务**并先取**事务级 advisory lock** 串行化多实例；marker 已存在则整段 no-op（普通 INSERT 写 marker，不 upsert 覆盖 granted）。SQL 留痕改 plpgsql，同口径（lock + 存在即 no-op + 仅 granted 非空才 bump），与 Python 严格等价。
- **R3-P1 版本表 `DO NOTHING` 吞冲突致孤儿不一致**：三类版本表 INSERT 去掉 `ON CONFLICT DO NOTHING` 改**普通 INSERT**——新 id 下若存在同版本孤儿即冲突抛错、整事务回滚，不再静默吞成「主表新、版本旧」。
- **R3-P2 文档/docstring 对齐**：plan 回滚口径全部改为「只删 marker.granted 实际新增行」；`seed_stage6_asset_visibility` docstring 更正（tenant_admin 现授 tenant+public，非「public 仅 system」）。
- **R3 测试补齐**：孤儿版本冲突→回滚；marker 内容 + 重跑幂等 no-op；q 匹配项位于「原上限之后」仍命中（撤上限验证）。

**四轮审查（R4）复审关闭**——R2/R3 的「granted 账本可逆」被证实无效，R4 改走正确方向：
- **R4-P1 granted 账本形同虚设**：发布权在多处 seed（新装 `_seed_role_grants`、存量 `seed_stage6`、v2 回填）写入；v2 回填执行时发布码多已存在 → `RETURNING` 为空 → `granted=[]`（本地 marker 实测即空），回滚删不掉任何行，「真可逆」不成立。**决策（用户确认）**：改用**确定性基线回滚**——不再记 granted，回滚恢复 C4 前默认角色策略（normal 删全部 8、tenant_admin 仅删 4 个 public 保留 tenant）。正向迁移去 `RETURNING`/granted、marker 仅记 `{"applied":true}`、仅确有新增才 bump；回滚 plpgsql 带 advisory lock + marker 缺失 no-op + 条件 bump。**诚实边界**：与所有默认策略迁移一致，不保留迁移后经角色管理页的人工增删。
- **R4-P2 排序键不唯一**：回测主键是三元组且 `created_at` 仅秒级、跨 owner 可同 id，只补 `r.id` 仍抖动。`ORDER BY` 末位补**完整主键** `r.tenant_id, r.owner_user_id, r.id`。
- **R4-P2 文档/留痕对齐**：plan 与 `asset-publish-open.sql` 中「有界分批扫描」「granted 账本回滚」等被撤销口径全部改为「全量过滤 / 确定性基线回滚」；回滚脚本补 advisory lock + marker 缺失 no-op + 条件 bump（与正向同锁同口径）。
- **R4 测试更新**：`test_asset_publish_open_backfilled_for_normal` 去掉 granted 断言，保留「授权 + 单次 bump + 幂等 no-op + marker.applied」。

**五轮审查（R5）复审关闭**——R4 回滚只删未补、且从未被测试执行，五轮补齐：
- **R5-P1 回滚未真正恢复 tenant_admin 基线**：R4 回滚只删 tenant_admin 4 个 public，未补回基线要求的 4 个 tenant（迁移期间若被人工移除则回滚后仍缺）。**新增可执行 `rollback_asset_publish_open_v1`**：同一 advisory-lock 事务内 normal 删 8、tenant_admin 删 4 public + **`ON CONFLICT DO NOTHING` 补齐 4 tenant**、增删行数共同计入条件 bump、删 marker、marker 缺失 no-op。`.sql` 留痕同步。
- **R5-P1 回滚路径无可执行测试**：R4 回滚仍是注释 SQL、测试套件不加载。**回滚落为 Python 函数 + 真实 PG 测试**：`test_asset_publish_open_rollback_restores_c4_baseline`（normal 清空/tenant_admin 删 public 补 tenant/marker 删除/确有增删 bump/二次回滚 no-op）+ `test_asset_publish_open_rollback_is_atomic_on_failure`（marker DELETE 故障 → 授权/marker/perm_ver 整体回滚）。
- **R5-P2 回测 `limit` 边界**：API `Query(None, ge=1)` 拒负值/0；服务层防御把非正 limit 归一为「不截断」，消除有无 q 两路语义差与 `LIMIT -1` 报错。
- **R5-P2 文档同步**：requirement.md 的「有界分批扫描/2000 上限」同步为「全量过滤、correctness 优先、优化留 T5」（已确认需求决策）；plan 全量验证记录更新为 R5。

**六轮审查（R6）复审关闭**——R5 回滚删 marker 导致不持久，六轮补齐：
- **R6-P1 回滚不持久、重启复活权限**：R5 回滚**删除 marker**，而正向迁移每次 init 都跑、见 marker 缺失即重新授权 → 「回滚→重启→发布权复活」，安全边界被自动反向覆盖。**改 tombstone**：回滚不删 marker，改写成 `{"applied":false,"rolled_back":true}`；正向迁移「marker 存在即 no-op」故重启后不复活；重新启用须显式删 tombstone。新增真实 PG 回归 `回滚 → 模拟 init（再跑正向迁移）→ 权限仍 C4 基线、tombstone 未被覆盖、不再 bump`。
- **R6-P2 故障原子测试断言不足**：R5 故障测试只查 normal 授权 + marker，未查 perm_ver / tenant_admin（名不副实）。改为故障前完整快照 normal/tenant_admin 授权集合 + 全体 perm_ver + marker 值，异常后逐项断言完全不变；注入点改为 tombstone 写入（`UPDATE app_config`）以覆盖「授权已改、提交前失败」。
- **R6-P2 plan 数据库回滚章节对齐**：§9 SQL 计划的回滚口径同步为「删 public + 补 tenant、增删共同 bump」+ tombstone 持久性与显式重新启用步骤。

**七轮审查（R7）复审关闭**——tombstone 只堵住 backfill，未堵住更早的 seed 写入者，七轮补齐：
- **R7-P1 `_seed_role_grants` 旁路复活发布权**：其重授门槛是「无 role_menu」（非无授权），角色管理接口允许 normal/tenant_admin 清空菜单 → 「回滚→清空菜单→重启→seed_rbac 先重授 8 码」，tombstone 只在其后的 backfill 才 no-op。**抽统一状态判断 `_asset_publish_rolled_back`**（读 tombstone），由 `_seed_role_grants`（回滚态：normal 无发布码、tenant_admin 仅 tenant）、`seed_stage6_asset_visibility`（回滚态：只授 tenant 不补 public）、`_backfill`（marker 存在天然 no-op）**共同消费**，杜绝第三个旁路。
- **R7-P2 “模拟 init”测试只调 backfill**：改为**真实启动顺序**——构造角色管理允许的边界（清空 normal 菜单、删 stage6 marker），依次跑 `_seed_role_grants → seed_stage6 → backfill`，断言发布权仍 C4 基线、tombstone 未被覆盖、不再 bump。
- **R7-P3 回滚测试 docstring 过期**：由「marker 删除/marker 缺失二次回滚」更正为「marker 写 tombstone / rolled_back 短路」。

**八轮审查（R8）复审关闭**——发布权状态机的并发与容错，八轮补齐：
- **R8-P1 三写入者未同锁串行，并发 seed 反向覆盖回滚**：`_seed_role_grants`/`seed_stage6` 在事务外读状态，与回滚并发时可据旧状态写回 public。**统一状态机 + 同锁串行**：新增 `_publish_policy_state_cur(cur)`（四态）+ `_publish_suppressed`，`_seed_role_grants`（非系统角色改「共享 `_ASSET_PUBLISH_OPEN_LOCK` + 单事务」，锁内读状态门控发布码）、`seed_stage6`（tx 起始取同锁、锁内读状态）、`backfill`、`rollback` **全部取同一把锁、同事务读状态**。新增锁获取阻塞测试（持锁 → seed 阻塞 → 释放 → 完成）。
- **R8-P2 `_seed_role_grants` 授权非原子、不 bump perm_ver**：R7 把它变成「清空菜单后重授」的状态机入口，却仍逐条 autocommit、不更新 perm_ver（违反 perm_resolver 硬契约）。改为**单事务**写菜单+资源+发布码，授权确有变化则**同事务 bump 该角色用户 perm_ver**。新增故障注入测试（perm_ver bump 失败 → 菜单/资源整体回滚、perm_ver 不变）。
- **R8-P1 tombstone 解析 fail-open**：marker 损坏/结构冲突时旧 helper 返回 False（=未回滚→放开发布权）。改为**四态显式建模**（missing/applied/rolled_back/invalid），非法/冲突 → INVALID → **fail-closed**（抑制发布权、按基线处理；backfill 亦因 marker 存在 no-op，两者不再冲突解读）。新增非法 JSON/`{}`/冲突字段/非 dict 的状态测试。
- **R8-P2 plan 门禁同步**：全量验证记录更新为 R2–R8 并标注 R7 覆盖顺序重启、R8 覆盖并发+容错；发布前检查改为「T0 本地已核验、生产核验为 R14 上线前置」。

**九轮审查（R9）复审关闭**——perm_ver 变更计数漏了菜单，九轮补齐：
- **R9-P1 菜单恢复漏 bump perm_ver**：`_seed_role_grants` 的变更计数只算资源/发布码插入，不算菜单插入；角色管理允许「菜单空、资源完整」合法态，seed 恢复菜单时资源 INSERT 全冲突（计数=0）→ 菜单权限扩大却不 bump，与 token 版本脱节（违反 perm_resolver 硬契约）。改 `res_changed → grant_changed`，**菜单/资源/发布码任一插入都计数**，确有变化即同事务 bump；提交后 best-effort 清受影响用户 perms 缓存。
- **R9-P2 测试名实不符**：R8 的 `..._is_atomic_and_bumps_perm_ver` 删了菜单+资源（res 计数>0）恰好绕开菜单-only 漏 bump，且只断言故障回滚、无成功 bump 断言。**拆为三例**：故障回滚（改名 `..._atomic_rollback_on_failure`）、成功重授 bump（`..._full_reseed_bumps_perm_ver`）、**仅清空菜单也 bump 的正向回归**（`..._menu_only_reseed_bumps_perm_ver`，直击本 P1）。

- **遗留（非本重构，另行处理）**：`test_stage5_audit_tenant_admin_is_scoped_to_own_tenant` 既有失败（tenant_admin 审计默认授权被既有迁移撤销）。
- **已知性能项（留 T5）**：发布态回测 q 为解析 opaque ref 走全量取数+Python 过滤，规模化后需 keyset 分页或冗余搜索列；当前数据量小、correctness 优先，随 T5 回测前端分页 UX 统一优化。

### 阶段 3 · 前端垂直样板（只接入 ScreenView）

#### 6.6 任务 T3：共享组件 + ScreenView 样板
- 状态：已完成（前端·Vitest/构建/E2E 三视口通过；审查整改已闭环）　依赖：T2A,T2B
- 涉及：新增 `AssetSearchDrawer.vue`、`AssetProfileSelect.vue`；`ScreenView.vue:539-571`；`api/screening.ts`
- 目标：共享抽屉/选择器在筛选页跑通全链路，DESIGN 合规。
- 操作：实现三来源段（防抖 q、分页）、加载查看（临时只读注入）、单击复制（自动 id/名称）、四态；PageDrawer `xl`、AppDataTable/AppTableColumn/AppRowActions/AppIconButton、无 Unicode 图标；ScreenView 下拉改 source=mine、接入抽屉、发布按钮随后端放开。
- 产出：两个共享组件 + ScreenView 接入 + Vitest。
- 边界：临时只读不进我的、不持久化、不自动跑筛选。
- 验证：Vitest（三段/q/空态/复制/临时只读）+ E2E + 三视口（1100×620/1366×768/1440×900）截图。
- 完成标准：筛选页全链路可用且 DESIGN 合规。
- 实际落地情况：**已完成（2026-07-29）**。①新增 `components/asset-search/`：`types.ts`（方案/回测 summary 契约对齐后端 summarize_*、assetItemKey/formatAssetTime）+ `AssetSearchDrawer.vue`（PageDrawer xl 挂 #overlays；PageSegmented 来源三段、回测形态隐藏系统内置段；防抖 q 300ms；服务端分页；四态——表体 loading/空态由 AppDataTable 承接、错误 AppStateBlock+重试；操作列 AppRowActions「加载查看/复制为我的」（回测「加载查看/复用参数重跑」），复制按 `copyPermission` 过滤；方案列（合并形态）=方案名称(名称+版本/次行「更新于 {时间}」)/来源徽标(title 含提供者)/操作(固定右缘)，回测列=kind+日期区间/状态/来源/提供者/创建时间；openWith 支持空态引导直达「系统内置」段）+ `AssetProfileSelect.vue`（`select`/`list` 双形态；fetchMine 只拉 source=mine；「我的」空态引导去系统内置搜索复制；「加载查看」注入会话内临时只读项——置顶候选、切换即丢弃、不持久化；「复制为我的」成功后 reload 我的列表并选中新 ref；暴露 reload/openSearch）。②`api/screening.ts`：`listProfiles(source?)`、`browseProfiles(source|q|page|pageSize)`、`copyProfile` 去必填 id 并返回新标识、`Profile` 补 `updated_at`。③ScreenView 样板：el-select 私有选择器整体替换为 AssetProfileSelect（保留 view 码降级守卫在 fetchMine 回调）；doSave/publish/copyCurrentProfile 改为组件 reload + 后端生成 id；删除 `nextCopyProfileId` 前端撞库逻辑。④`AppPagination` 内部 `small` 改映射 `size="small"`（消除 el-pagination 弃用告警，E2E console 契约拦截发现）。⑤DESIGN.md 真实复用组件清单登记两组件。验证：Vitest 组件用例全过，前端全量 **525 passed**；`npm run build` 通过（含 vue-tsc）；E2E `asset-search-drawer.spec.ts`（跨用户真实链路：debug_normal 发布租户公开 → debug_tenant_admin 浏览/复制/临时只读，含系统内置空态与脱敏断言）**三视口全过**并附截图；**全量 Playwright 本轮未复跑（未验证，留 T6）**。偏差：回测形态列/重跑 UI 已实现但真实消费留 T5；`list` 形态已实现、真实消费留 T4（ConfigView）。

**T3 审查整改（2026-07-29，复核 AI 审查 2×P1 + 2×P2，四条均属实已修复）**：
- **P1-1 无查看权限仍暴露搜索入口**：`AssetProfileSelect` 新增 `viewPermission`（经 `hasPermission` 判定 `canBrowse`，缺省可浏览），无权限时不渲染搜索按钮与「去系统内置搜索复制」空态引导、不调 browse；`AssetSearchDrawer` 新增 `canBrowse`，`fetchPage` 顶部短路，无权时显示 `AppStateBlock state="error" variant="permission"`「无权限查看{对象}/请联系系统管理员调整权限」并整体隐藏工具栏与分页页脚（对齐 DESIGN §286/§307 权限态，不把无权伪装成空态）；`ScreenView` 传入 `view-permission="screen-profile:view"`。
- **P1-2 三视口看不到操作列**：操作列改 `role="action" fixed="right"` 固定右缘（后续见 R2 整改的列合并，此处「移除更新时间列」已被回滚）。
- **P2-1 空态截图非有效视觉证据**：E2E 截图前等待 `.el-drawer` `offsetWidth===560`（进场动画结束），并改对抽屉面板 locator 截图而非整页。
- **P2-2 关闭/卸载仍可能发防抖请求**：`watch(open)` 关闭分支清理 `searchTimer` 并 `fetchSeq+=1` 使在途响应失效；`onBeforeUnmount` 同口径清理。
- **复查新发现问题（审查者未提，已一并修）**：初版无权态仍显示工具栏（分段/搜索框）与「共 0 条」分页页脚，语义矛盾——改为无权态整体隐藏。
- 整改验证：两组件定向 Vitest **20 passed**（新增无权态×2、防抖清理×1、权限入口×1 共 4 例），前端全量 **525 passed**；`npm run build` 通过（含 vue-tsc）；定向 E2E 三视口 **3 passed**（新增列头/操作列可视断言全部成立）。**本轮全量 Playwright 未复跑（未验证，留 T6）**。

**T3 审查整改 R2（2026-07-29，复核二轮审查 1×P1 + 3×P2；P1 属实并已按用户确认的「改需求·合并」方案修复）**：
- **R2-P1 擅删需求强制的「更新时间」列**：一轮为适配宽度直接删列，属需求偏离（requirement 表格列契约明确方案类含更新时间）。**回滚删列**，改按用户确认的**合并方案**（并同步修改需求契约）：方案类列收敛为「方案名称（名称+版本，次行「更新于 {时间}」）/ 来源徽标（`title` 含脱敏提供者）/ 操作（固定右缘）」三列——版本并入名称行、更新时间并入名称次行、提供者并入来源徽标 tooltip，信息项不丢，对齐 `xl=560px` 抽屉保证全部完整可见、无横向滚动。回测类列契约不变（创建时间本为独立列）。**同步修改** requirement 表格列契约与原型 `public-asset-search-drawer.html` 列说明。
- **R2-P2-1 E2E 用删减列集合证明「全部可见」**：断言改为需求合并后的真实列集合「方案名称/来源/操作」三列头**左右边界均在抽屉可视区**，并新增「名称次行含『更新于』」「来源徽标 title 含提供者（脱敏）」「操作列完整可见」断言；提供者文本断言同步改为 title 承载。
- **R2-P2-2 提供者被固定列裁切**：合并后提供者不再是被挤的独立列，改由来源徽标 title 完整承载（`{来源} · {提供者} · 只读`），单元格无裁切。
- **R2-P2-3 plan 验收事实自相矛盾**：①实际落地描述的方案列口径改为合并形态；②用例数/通过数更正为 **20 用例 / 525 passed**；③全量 Playwright 明确标注「**本轮未验证，留 T6**」，不再用旧 `58 passed / 3 failed` 充当整改后回归证据。
- R2 整改验证：两组件定向 Vitest **20 passed**；前端全量 **525 passed**；`npm run build` 通过（含 vue-tsc）；定向 E2E 三视口 **3 passed**（合并列集合 + 左右边界 + 更新时间/提供者/操作列断言全部成立）。**全量 Playwright 本轮仍未复跑（未验证，留 T6）**。

### 阶段 4 · 普通方案页扩展

#### 6.7 任务 T4：评分/买卖/榜单/个股详情接入
- 状态：待开始　依赖：T3
- 涉及：`ConfigView.vue`（评分 1093-1118 / 买卖 1450-1470）、`BoardView.vue:228-249`、`StockDetailView.vue:947-960`（R10）
- 目标：四页接入共享组件，下拉改 source=mine，搜索入口，发布放开。
- 操作：侧栏/下拉接入 AssetProfileSelect + AssetSearchDrawer；加载只读**不自动计算/评估/跑榜单**（§7.0/§7.2）。
- 验证：各页 Vitest + E2E；目视系统内置徽标不受影响。
- 完成标准：四页一致、加载不自动运行。
- 实际落地情况：待实施。

### 阶段 5 · 回测专属接入

#### 6.8 任务 T5：回测页选择器 + 历史浏览 + 同步重跑
- 状态：待开始　依赖：T3,T2C
- 涉及：`BacktestView.vue` 评分方案 `:1036`、选股方案 `:1075`、买卖方案 `:1118`、历史区 `:955-978`
- 目标：**3 个方案选择器**（评分/选股/买卖）各带搜索入口（方案有系统内置段）+ 历史回测浏览入口（tenant/public，无系统内置，默认全体）+「复用参数重跑」（同步，按钮 loading）。
- 操作：**4 个入口**（3 方案 + 1 历史）按 §7.2；方案选择器临时只读；历史浏览只读，仅同步重跑产生自己的新 run。
- 验证：E2E（4 个入口计数、同步重跑归属+loading 反馈、状态流转）。
- 完成标准：回测交互符合 §7.2（4 入口）。
- 实际落地情况：待实施。

### 阶段 6 · 全链路验收

#### 6.9 任务 T6：验收、测试与构建
- 状态：待开始　依赖：T3,T4,T5,T1B
- 涉及：Vitest、E2E、stage6 测试、`DESIGN.md` 组件矩阵、`frontend/dist`
- 目标：多租户/多角色 E2E、路由守卫、组件测试、关键视口、构建同步。
- 操作：跑 `pytest backend/tests/`、`npm run test:e2e`、`npm run build`；DESIGN 登记新组件；更新 stage6 断言。
- 验证：全绿 + build 成功 + dist 同步 + 三视口。
- 完成标准：交付红线满足（AGENTS 端口/构建）。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划
- 不新增表、不删列、不迁移预设（C9）。
- 权限授权回填（Python 迁移 + 新 marker，遵循 `pg_ddl.py` seed 模式）。
- SQL 留痕：`agent-works/asset-ownership-refactor/asset-publish-open.sql`
  - 用途：记录给 normal（及 tenant_admin public）授 8 发布码、撤销原撤权 DELETE 的等价 SQL 与**回滚 SQL**。
  - 执行时机：随后端启动迁移（新 marker）自动应用；留痕用于人工复核。
  - 影响：`sys_role_resource` + 受影响用户 `perm_ver`。
  - 回滚：**确定性基线恢复**（可执行 `rollback_asset_publish_open_v1` + plpgsql 留痕，advisory lock）——normal 删全部 8；tenant_admin 删 4 个 public **并 `ON CONFLICT DO NOTHING` 补齐 4 个 tenant**（迁移期间被人工移除也恢复）；**增、删行数共同计入、确有增删才 bump** perm_ver。
  - **回滚持久性（tombstone）**：回滚**不删 marker**，改写成 `{"applied":false,"rolled_back":true}`；正向迁移「marker 存在即 no-op」，故回滚后当前版本重启、init 重跑正向迁移也不会复活发布权。**重新启用须显式操作**：删 tombstone 后再跑正向段。marker 缺失（从未应用）或已是 tombstone → 回滚整段 no-op。与所有默认策略迁移一致，不保留迁移后人工增删（固有边界）。

## 8. 测试与验证计划
> **口径**：区分「定向测试通过」（本阶段新增/相关用例）、「全量后端结果」、「未验证（前端未实施）」。
> **全量后端（2026-07-28，停服释放 DuckDB 锁后跑，含 R2–R9 补测）**：`728 passed`（R9 新增「仅清空菜单也 bump perm_ver」正向回归 + 成功重授 bump，故障回滚用例改名保留）。**R7 覆盖顺序重启，R8 覆盖并发锁串行+fail-closed，R9 覆盖菜单变化的 perm_ver 一致性**。恒有 1 例**既有失败**（`test_stage5_audit.py::test_stage5_audit_tenant_admin_is_scoped_to_own_tenant`，期望 200 实得 403），根因是既有 `revoke_tenant_admin_audit_default_grants` 迁移撤销 tenant_admin 审计默认授权，**与本重构无关、不在本次 diff**，已单列待处理。Ruff：环境未安装，未验证。
> **前端（2026-07-29，T3 ScreenView 样板，含 R1/R2 两轮审查整改）**：Vitest 全量 `525 passed`（组件用例：抽屉 11 + 选择器 9 = 20）；`npm run build` 通过（含 vue-tsc）；Playwright `asset-search-drawer.spec.ts` 跨用户链路三视口（1100×620/1366×768/1440×900）通过并附截图——截图前等待抽屉 `offsetWidth===560` 稳定、对抽屉面板 locator 截图；列断言覆盖需求合并后的方案类列集合「方案名称（含次行『更新于』)/来源（title 含提供者）/操作」三列头左右边界均在抽屉可视区、操作列 `fixed="right"` 完整可见、无权态 fail-closed 不调 browse。**全量 Playwright 本轮未复跑（未验证，留 T6）**；后端曾按 E2E 写模式重启、验收后已恢复日常模式（/api/health=200）。
- 单元测试：`scoped_where` 四来源互斥（含 **mine 平台槽排除预设**）、preset 负例（private 不出现）、summary 含 updated_at、回测独立 summary、发布码授权解析。具体完成情况：**定向通过**（`test_stage6_asset_visibility` 等）。
- 接口测试：list `source=mine`（**含平台槽 owner 互斥**）；browse `preset|tenant|public`+q+分页+脱敏（preset 严格公开负例）；未知 source 返回 400；发布放开后 normal 可发布/非 owner 403；回测重跑归属+审计；**发布态回测按引用方案名 q 命中**；**复制原子插入不覆盖同 id 既有资产**。具体完成情况：**定向通过**（含 `test_asset_review_fixes` 3 例 P1 回归）。
- 页面/交互测试：Vitest（AssetSearchDrawer 三段/q/空态/复制/临时只读、AssetProfileSelect 双形态）、E2E（搜索→加载只读→复制→我的下拉；下拉仅自己；normal 发布；回测重跑）。具体完成情况：**ScreenView 样板通过（T3，2026-07-29）**——组件 Vitest 20 用例（抽屉 11 + 选择器 9）全过、前端全量 525 passed；`asset-search-drawer.spec.ts` 跨用户链路（发布租户公开→浏览/复制/临时只读/脱敏/系统内置空态/合并列集合可视）三视口通过并附截图；其余页面待 T4/T5。
- 组件资产闭环测试：AssetSearchDrawer/AssetProfileSelect 在 ScreenView 样板 + 4 页真实消费；DESIGN 矩阵登记；无 Unicode 图标、PageDrawer xl、AppDataTable/AppRowActions。具体完成情况：**DESIGN 真实复用组件清单已登记（T3）**；ScreenView 真实消费通过；4 页消费待 T4/T5；按钮文案/间距契约扫描全过（button-system/typography-spacing-system）。
- 权限与数据范围测试：多角色（`test-users.md`）验证发布放开、mine 隔离、跨租户 tenant 不可见、preset 严格公开、owner 脱敏。具体完成情况：**后端定向通过**；多角色端到端待前端。
- 回归测试：系统内置徽标/`is_preset`/榜单零改动回归；现有 copy/visibility 链路；stage6 断言更新。具体完成情况：**定向通过**（copy/visibility 簇 57 passed）。
- 异常与边界：下拉空态、系统内置段空态（筛选）、临时只读不持久化、复制撞库/并发有限次重试（原子插入）、回测同步重跑 DuckDB 单写锁串行、停用降级。具体完成情况：**后端边界定向通过**；前端空态/临时只读 ScreenView 样板通过（T3，空态引导直达系统内置段、临时项切换丢弃/不持久化均由组件 Vitest + E2E 覆盖），其余页面待 T4/T5。
- 图示与原型一致性：AssetSearchDrawer 覆盖原型区域（三来源段/搜索/列表/操作列/分页/四态）+ 三关键视口 + DESIGN 合规。具体完成情况：**ScreenView 样板通过（T3）**——抽屉实现与原型 §7.1 逐条对齐（来源分段/防抖搜索/操作列/分页/四态/提供者脱敏），三视口 E2E 截图留存于 playwright-report；其余页面待 T4/T5。
- 需求映射验证：R3/R4/R5/R6/R7/R10/R14 均有任务与可观察验证；R1/R2/R8/R9/R11/R12/R13 跳过并说明。
- 负向验收：R1/R2/R11/R12/R13 对应区域零 diff。

## 9. 发布与回滚
- 发布前检查：**T0 本地/dev 已核验；生产只读核验必须在 R14 上线门禁前完成**（本地样本不代表生产分布）；新 marker 不冲突；`pytest` 与前端测试全绿；`npm run build` 同步 dist。
- 发布步骤：后端先上（迁移回填授权 + perm_ver bump，受影响用户重登）→ 前端上。
- 配置/环境：无新增。
- 回滚：前端独立回滚；后端授权回填可逆（`asset-publish-open.sql` 回滚段**确定性恢复 C4 前默认角色策略**，属默认策略迁移语义、不保留迁移后人工增删）；预设/is_preset 未改无数据回滚风险。

## 10. 风险、假设与待确认项
### 10.1 风险
- [高] R4 安全边界变更：公开资产增多；缓解 owner-only、停用降级、引用范围校验；R8 治理列后续。
- [中] stage6 既有断言（normal 无发布权）需批量更新。
- [中] 存量库迁移必须新 marker，否则 normal 拿不到发布权。
- [中] R14 严格条件下筛选/买卖系统内置段常态可能为空——需 T0 核实并做空态兜底，避免被误判为 bug。
- [低] 选择器双形态抽取需保留评分/买卖侧栏形态。

### 10.2 假设
- C1–C9 已确认（§0）。系统内置/`is_preset`/榜单前后端不动。
- R6 = 重跑（不新增 copy）；复制 = 后端自动 id/名称；系统内置 = 严格 `is_preset AND public`、不迁移。

### 10.3 前置核验 / 发布门禁
- **T0（只读事实核验）**：核实线上评分/筛选/买卖预设真实 owner/is_preset/visibility 分布。**只门禁 R14 数据验收与发布**，不阻塞 T1A/T1B（依赖：无，可与 T0 并行）；结论影响 R14 系统内置段实际内容/空态兜底。

### 10.4 待确认项（不阻塞）
- R9 新用户冷启动引导，待产品确认。
