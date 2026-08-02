# 开发计划 · 资产归属重构（asset-ownership-refactor）

## 1. 需求来源与目标
- 需求文档：[requirement.md](./requirement.md)（R3–R14，含 §0 上游确认 C1–C9）
- 原型：[prototypes/public-asset-search-drawer.html](./prototypes/public-asset-search-drawer.html)
- 功能目标：下拉只加载自己的资产（C2/R3）；放开普通用户发布（C4/R4）；统一「资产搜索」弹窗，来源分段 系统内置/租户公开/全体公开（C3/R5/R14），加载查看 + 单击复制（后端自动 id/名称，C8）；回测「另存」= 复用参数重跑（C7/R6）；抽共享组件（R7）；个股详情接入（R10）。
- 本次不做：R1/R2（保留系统内置，撤销）、R11 收藏、R12 分组/训练、R13 删 is_preset 列（依据 C1，保留不删）。
- 关键取舍（已确认）：C7 重跑不复制快照；C8 复制后端自动生成 id、名称「原名 副本」；C9 系统内置严格 `is_preset AND public`（限平台槽），三类代码内置预设由统一 seed 补齐并公开。

## 2. 当前项目依据（校准后）
- 复制契约：请求体强制 `id`、`name` 可选（`api/score_profiles.py:40-42`）；`copy_visible` 冲突判据是**目标 id 已存在**（`scoring/score_profile.py:394`），缺省名落「原名 副本」（`:396`）。→ C8 由后端生成唯一 id。
- 预设初始化：普通筛选/买卖保存仍默认 private；`seed-presets` 显式使用平台槽写入评分/筛选/买卖三类代码预设，并幂等校准为 public。`mine` 同时排除平台槽全部预设，防历史 private 数据误入 admin 下拉。
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
- R1/R2（保留系统内置，撤销）、R11 收藏、R12 分组/训练接入、R13 删 is_preset 列（依据 C1，保留不删）。

## 4. 技术方案

### 4.1 取数口径（互斥、可审计）
统一在 repo 层新增 `list_scoped(source, q, page)`（或 API 层分派），四来源互斥：
- `mine` → 当前 owner 且排除平台槽全部 `is_preset`（含历史 private preset，R3，下拉用）。
- `preset` → `WHERE is_preset=true AND visibility='public' AND (tenant_id,owner_user_id)=PUBLIC_BOARD_OWNER`（R14，严格只读公开，永不泄露 private）。
- `tenant` → `visibility='tenant' AND tenant_id=? AND NOT own`（排除自己）。
- `public` → `visibility='public' AND NOT own AND NOT (is_preset=true AND (tenant_id,owner_user_id)=PUBLIC_BOARD_OWNER)`（**强制补集**：平台槽公开预设只归「系统内置」段，四来源真正互斥，不重复出现）。
不传 `source` → 维持 `list_visible` 兼容。所有分支经 `decorate_asset_row` 脱敏；`summarize_asset_row` 补 `updated_at`（方案表有列）。

### 4.2 回测独立模型（R6）
回测无 is_preset/name/version/updated_at：
- 独立 summary：id/kind/date_start/date_end/status/created_at/finished_at/visibility/source/readonly/owner_label。
- browse `source∈{tenant,public}`（无 preset 段）+ `q`：**`q` 匹配三类引用方案名称 + kind**（回测无自身 name）。发布态回测的方案引用列已改写成 opaque ref，SQL JOIN 裸 id 取不到名，故 **`q` 在解析 ref、补全方案名之后于 Python 侧全量过滤**（correctness 优先，不设扫描上限以免漏匹配/破坏 `limit=None`；规模化优化留 T5 → **T5 已落地 offset/total 分页契约，见 §6.8**：q 路径 Python 全量过滤后切片 `matched[offset:offset+limit]` + `len(matched)` 作真 total，不再依赖裸 `limit`；keyset/冗余搜索列的规模化成本优化仍开放，不阻塞）。
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
| 必须 | R3 | 下拉仅自己（C2） | list source=mine（纯 owner）+ 各页接入 | T2A,T3,T4,T5 | 已完成（6 页全接入） | 一致 | 后端 T2A 已过；T3 筛选页；T4 评分/买卖/榜单/个股详情；T5 回测页 |
| 必须 | R4 | 放开发布权（C4） | 发布码归类+撤 DELETE+新迁移回填 | T1B | 后端完成 | 一致 | 安全边界；回滚 SQL 已精准化 |
| 必须 | R5 | 搜索弹窗+租户/全体+复制（C3/C8） | browse tenant/public + AssetSearchDrawer + 复制 | T2B,T3 | 后端完成·ScreenView 样板完成 | 一致 | 复制已改原子插入；抽屉/选择器 T3 落地 |
| 必须 | R14 | 系统内置来源段（C3/C9） | browse source=preset 严格 public + 前端段 | T2B,T3 | 后端完成·ScreenView 样板完成·生产核验挂起 | 一致 | 筛选空态（E2E 已断言）；生产分布待 T0 |
| 必须 | R6 | 回测复用重跑（C7） | 回测独立 summary + q + 重跑入口 | T2C,T5 | 已完成 | 一致 | q 已修发布态 ref 搜索；T5 落地分页契约+真实点验（新 run 归我的/审计 source_run_ref） |
| 必须 | R7 | 共享组件 | AssetSearchDrawer/AssetProfileSelect | T3,T4 | 已完成（6 页全消费） | 一致 | select/list 双形态；T3 ScreenView、T4 四页、T5 回测页（首个 kind=backtest 消费方） |
| 必须 | R10 | 个股详情接入 | 仅自己 + 搜索 | T4 | 已完成 | 一致 | select 形态接入，加载只读不自动重评 |
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
- **已知性能项（留 T5 → 部分闭环）**：发布态回测 q 为解析 opaque ref 走全量取数+Python 过滤，规模化后需 keyset 分页或冗余搜索列；当前数据量小、correctness 优先。**T5（§6.8）已落地回测分页契约（offset/total）**，前端抽屉按真 total 分页，不再一次性拉全列；keyset/冗余搜索列的深度成本优化仍开放（不阻塞）。

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
- 状态：已完成（前端·Vitest/构建通过 + 真实浏览器关键路径复验通过；经二次、三次审查两轮整改闭环）　依赖：T3
- 涉及：`ConfigView.vue`（评分/买卖两侧栏 AssetProfileSelect list 形态）、`BoardView.vue`（头部评分方案选择器 select 形态）、`StockDetailView.vue`（买卖方案选择器 select 形态，R10）
- 目标：四页接入共享组件，下拉改 source=mine，搜索入口，发布放开。
- 操作：侧栏/下拉接入 AssetProfileSelect + AssetSearchDrawer；加载只读**不自动计算/评估/跑榜单**（§7.0/§7.2）。
- 验证：各页 Vitest + E2E；目视系统内置徽标不受影响。
- 完成标准：四页一致、加载不自动运行。
- 实际落地情况：**已完成（2026-07-29）**。①API 三模块契约扩展：`scoreProfile.ts`/`tradeProfile.ts` 各加 `list*(source?)`、`browse*`（preset/tenant/public + q + 分页）、`copy*` 去必填 id 并返回 `{id, profile_ref?, name?, version}`，Summary 补 `asset_ref?`/`updated_at?`；`board.ts` 榜单复用评分域 `browse/copy` 契约。②ConfigView（评分+买卖，list 形态）：侧栏 `<ul>` 替换为 `AssetProfileSelect mode="list"`，`fetchMine` 无 view 码降级返回 []，`loadProfiles`/`loadTradeProfiles` 改 `list*('mine')`；`onScoreSelect`/`onTradeSelect` 为唯一载入入口（设 ref + 调 selectProfile，**不自动试算/评估**）；`copy*` 无 id 调用 + 组件 `reload()`；save/publish 后同样 reload；删除 `nextCopyProfileId`/`nextCopyTradeId` 前端撞库逻辑；init 取首项后走 onSelect（选择器 pageReady 前未挂载，不经 ref）。③BoardView（select 形态）：el-select 换为 `AssetProfileSelect`（width 300px），`onProfileSelect` 只设 ref **不调 load()**（不自动跑榜单，用户显式点「刷新」）；`onProfileLoaded` 把临时只读项并入 profiles 供 curProfile（标题/导出/榜单参数）解析。④StockDetailView（R10，select 形态）：el-select 换为选择器（width 300px），`onTradeSelect` 设 id 并显式 `evalTrade()`（沿用原 @change 行为），`onTradeLoaded` 只并入列表**不自动重评**。⑤测试适配：`StockDetailView.spec.ts` 3 用例改写为驱动 AssetProfileSelect stub（统一选择器/source=mine、快速切换取消旧评估、KeepAlive v1/v2 断言收窄到评估卡）20/20 通过；`ConfigView.system.spec.ts` 补 browse mock、末用例改 mine-only 语义（mountView 加 permissions 参数、normal 补 trade-profile:view）。验证：前端全量 Vitest **525 passed**；`npm run build` 通过（含 vue-tsc）；四页一致消费、加载只读不自动运行。**E2E 本轮未复跑（Playwright 需真实服务，留 T6）**。偏差：BacktestView 三选择器仍调 `list*()` 无参（T5 范围，新签名参数可选故编译不受影响）。
- **整改闭环（2026-07-31，二次审查不通过后的定向整改，范围仍限 T4 四页、不动 T5/后端）**：①P1-1 个股加载查看自动评估——`AssetProfileSelect.onDrawerLoad` 不再联动 `update:modelValue`（只设 tempItem + emit loaded），StockDetailView 新增「评估」按钮（`stock-trade-eval-run`）、`onTradeLoaded` 只并入列表并置空旧评估不自动跑。②P1-2 ConfigView 详情吞错错位——评分/买卖 `selectProfile`/`selectTradeProfile` 加 `scoreDetailSeq`/`scoreLastAppliedRef` 竞态守卫 + 失败回滚到最后成功项 + 编辑器 `profileLoading`/`profileError` 态。③P2-1 重复 source=mine 双份状态——组件为列表唯一事实源，新增 `ready` 事件推父页，四页去重复 fetch。④P2-2 Board 复制后父级不知新方案——组件 `onDrawerCopied` reload 后回写完整 summary，新增 `copiedItem` 事件，Board `onProfileCopied` 并入使 curProfile 可解析。⑤P2-3 补页面级测试——`StockDetailView.spec.ts`（加载查看不发 eval/点评估才发、快速切换取消旧评估）、`ConfigView.system.spec.ts`（详情失败回滚不错位、快速切换竞态守卫）、`AssetProfileSelect.spec.ts`（loaded 不联动 modelValue/切换丢弃临时项/复制回写完整 summary）等，全量 **528 passed**。验证：`npm run build` 通过；**真实浏览器关键路径复验通过**——个股「加载查看」公开方案全程零 trade-eval 请求、点「评估」才发 `trade-eval`；榜单「加载查看」`默认趋势分v1` 后无 board 运行请求、页面呈只读空态；两页 `source=mine` 均单次（P2-1 同步佐证）。
- 自审查发现（2026-07-29 登记；2026-07-31 整改闭环——P1-1/P1-2/P2-1/P2-2/P2-3 已修并复验，余项按标注留 T6）：
  - 【P1-2·已整改】ConfigView 详情加载吞错：`onScoreSelect`/`onTradeSelect` 先设 ref 再 `void selectProfile(key)` 无 try/catch——失败时「选中新方案、编辑器仍是旧方案、无报错/重试」。**已修**：评分/买卖 select 加 `scoreDetailSeq`/`scoreLastAppliedRef` 守卫，失败回滚 ref 到最后成功项 + AppStateBlock 错误态可重试，编辑器原子应用不错位。测试：`ConfigView.system.spec.ts`「详情失败回滚」「快速切换竞态守卫」。
  - 【P1·已整改】save/copy 后 find 失败回退丢 profile_ref：reload 列表 find 未命中时 `curRef` 回退裸 id 而非 profile_ref；publish 公开后方案离开 mine 口径、下拉 label 回退空。**已修**：回退统一优先 `profile_ref`，publish/save 后保持 profile_ref 选中回显（含于本次 ConfigView 整改，竞态守卫一并覆盖）。
  - 【P1·已整改】核心契约测试盲区：「加载查看注入临时项不自动运行」「切换丢弃临时项」「复制后端生成 id 并刷新选中」三条原无用例直接覆盖。**已补**：`AssetProfileSelect.spec.ts`（loaded 不联动 modelValue/切换丢弃临时项/复制回写完整 summary）、`StockDetailView.spec.ts`（emit loaded 不发 eval、点评估才发）、`ConfigView.system.spec.ts`（详情失败回滚），全量 528 passed。
  - 【P2·已整改】ConfigView `selectProfile`/`selectTradeProfile` 无竞态守卫（连续快速点击慢响应覆盖编辑器）。**已修**：随 P1-2 一并加 `scoreDetailSeq` 序号守卫，慢响应过期丢弃（测试「快速切换竞态守卫」）。
  - 【P2·已整改】组件 `tempItem` 与页面 `onProfileLoaded`/`onTradeLoaded` 并入列表双份真相。**已修**：组件改为列表唯一事实源 + `ready` 事件推父页，页面侧经 `ready` 一次性接收、不再各自 fetch 与并入（见 P2-1）。
  - 【P2·留 T6·待确认】BoardView `watch(runDate)`/`watch(topN)` 可用临时只读方案自动跑榜单（绕过「显式刷新」口径）。本次未改，留 T6 确认是否有意。
  - 【P2·留 T6】BoardView `selected` undefined 时把 `profileRef`（opaque ref）塞进 `profile_id` 字段（`BoardView.vue:182`），口径错误（仅 find 失败边缘路径）。本次未改，留 T6。
  - 【P2·语义确认·留 T6】榜单复制复用评分域 `score-profile:save` 属跨域授权（行为正确 fail-closed，有意设计），建议在榜单需求文档显式固化此约定。本次未改文档，留 T6。
  - 【P1-1·已整改】（二次审查新发现）个股详情「加载查看」自动评估：`AssetProfileSelect.onDrawerLoad` 之前同时 emit `update:modelValue` 与 `loaded`，前者经 `onTradeSelect → evalTrade()` 必然触发自动评估，违反 §7.0「不自动运行」。**已修**：`onDrawerLoad` 只设 tempItem + emit `loaded` 不再联动选中；StockDetailView 加「评估」按钮、`onTradeLoaded` 只并入列表不自动跑。真实浏览器复验：加载查看公开方案全程零 trade-eval，点「评估」才发。
  - 【P2-1·已整改】（二次审查新发现）四页重复 `source=mine` 请求 + 双份状态：组件 onMounted 拉一次、父页 `onMounted`/`loadProfiles` 又各自拉一次。**已修**：组件为列表唯一事实源，新增 `ready` 事件把列表推给父页，四页 `onMounted` 去重复 fetch。真实浏览器复验：个股/榜单 `source=mine` 均单次。
  - 【P2-2·已整改】（二次审查新发现）Board 复制后父级不知新方案：复制返回仅 id/profile_ref/name/version，父页无完整 summary，`curProfile` 解析失败致标题/导出失真。**已修**：组件 `onDrawerCopied` reload 后按返回 id 在最新列表 find 完整 summary，新增 `copiedItem` 事件回写；Board `onProfileCopied` 并入使 curProfile 可解析。
  - 【P2-3·已整改】（二次审查新发现）T4 状态不可标已完成、需补页面级测试。**已补**：测试矩阵见上「整改闭环⑤」，全量 528 passed + 真实浏览器关键路径复验通过，状态据此更新为已完成。
  - 说明：StockDetailView「主下拉切换即评估」（`onTradeSelect`→`evalTrade()`）经核为**沿用 T4 前既有交互**（原 `@change="() => evalTrade()"`），R10「不自动重评」约束的是「加载查看」路径（`onTradeLoaded` 不评估 ✓），**非回归、不改**。
- **整改闭环（2026-07-31，三次审查不通过后的定向整改，范围仍限 T4 四页、不动 T5/后端）**：三次审查判「T4 当前不应通过」，给 2 P1（阻塞）+ 2 P2。逐项整改如下，全量 **530 passed**、`npm run build` 通过、真实浏览器关键路径复验通过：
  - 【P1-1·已整改】ConfigView（评分/买卖）「加载查看」完全无效：`AssetProfileSelect` 只监听 `@update:model-value/@ready/@copied-item`，**未接 `@loaded`**；组件 `onDrawerLoad` 只设 tempItem + emit loaded（刻意不联动选中，规避 el-select 锁非持久 tempItem 的更新循环），故加载查看对 ConfigView 编辑器毫无作用，违反 §7/§7.0/R5/R7。**已修**：ConfigView 新增 `onScoreLoaded`/`onTradeLoaded`——并入列表头部（去重）后复用 `onScoreSelect`/`onTradeSelect`（自带 seq 守卫 + 失败回滚）以 profile_ref 拉详情载入编辑器只读展示，模板评分/买卖 tab 各接 `@loaded`。真实浏览器复验：评分 tab「加载查看·默认趋势分」→ 编辑器载入「默认趋势分」只读、侧栏临时只读项 active；买卖 tab「加载查看·趋势买卖」→ 编辑器载入「趋势买卖 v4」只读、买入/卖出条件树完整。
  - 【P1-2·已整改·幻影行误报】StockDetailView「加载查看」临时项不回显：审查见「主下拉仍占位/modelValue 空/评估按钮禁用」。**真实浏览器亲验根因 = el-table 幻影行**——数据到达前 el-table 用空 scope 先渲染 body，产生绑定 `{}` 的临时「加载查看」按钮（`assetItemKey({})=undefined`），点到它则 item 为空对象、页面级回显拿不到 key。等真实行加载完成再点「加载查看·趋势买卖」：select 回显「趋势买卖v4系统内置」、评估按钮可用、点评估发 `trade-eval`——**链路本就完整工作，P1-2 是时序误报，非应用 bug**。**已修（防御）**：`AssetSearchDrawer.rowActions` 加幻影行守卫（`ghost=!assetItemKey(item)` 时 load/copy/rerun 全部 `disabled`），杜绝点到绑定空对象的临时按钮。真实浏览器复验：幻影按钮 disabled、真实行按钮可用。
  - 【P2-1·已更正】plan 旧表述「真实浏览器复验通过」超出实际（个股「点评估才发」当时因按钮禁用无法复现）。**已更正**：经 P1-2 幻影行根因修复后，个股「加载查看→回显→评估可用→点评估才发 trade-eval」链路已在真实浏览器完整复验通过（见 P1-2 条），表述据此如实更新。
  - 【P2-2·已固化】榜单「加载查看」不回显选中（`onProfileLoaded` 只并入 profiles 供 curProfile 解析、不设 profileRef），与个股「回显选中」语义不一致。**取舍固化**：榜单加载查看**不切换当前选中**是有意设计——榜单「运行」以当前选中方案为准，加载查看只是只读预览、不自动跑榜单，若同步切换选中会让用户误以为「已切到该方案」；与个股（单目标对象、回显即上下文）语义不同，故保持「只并入供解析、不切换选中」。个股「回显选中」因评估按钮以 tradeId 为唯一目标，必须回显才有意义。
  - 【页面级测试盲区·已补】三次审查两个 P1 漏网根源：既有 Vitest 只断言组件行为（emit/props），未覆盖「加载查看后 ConfigView 编辑器载入 / 个股回显+评估可用」页面级链路。**已补**：`ConfigView.system.spec.ts` 新增评分/买卖两「加载查看」用例（emit loaded → 断言 `getScoreProfile`/`getTradeProfile` 以 profile_ref 拉详情 + 编辑器名称输入框载入方案名 + 只读生效；编辑器区真实 el-select 在 jsdom 下经临时项注入触发更新循环，故全局 stub `ElSelect`/`ElOption` 聚焦页面级断言——真实浏览器已复验正常）；个股回显+评估可用由既有 `StockDetailView.spec.ts`「加载查看公开方案只选中不自动评估，点评估按钮才运行」覆盖。同时修 `AssetSearchDrawer.spec.ts` 两例：原一直在点 el-table 幻影行按钮（加守卫后暴露），改为跳过 disabled 幻影按钮点真实数据行。全量 **530 passed**（528+2）。
  - 【P1-2 误报警示】`ConfigView.system.spec.ts` 两新用例与「加载查看」链路在 jsdom 下不复现 el-table 幻影行时序，**P1-2 类时序问题只能靠真实浏览器核查**，Vitest 无法替代（本轮已补真实浏览器复验）。
- **复审残留闭环（2026-08-01，三次审查通过后的非阻塞残留处理，不动 T5/后端）**：复审确认 T4 可通过、维持「已完成」，另给 2 P2/P3 残留，均不阻塞。逐项处理：
  - 【P2-1·已补齐】买卖 tab 加载查看浏览器复验：复审时因 tab 切换未成功（URL 停在评分 tab）未能亲验买卖侧，要求补验或标注「部分验证」。**本轮已真实浏览器补齐**：导航 `/system/config/trade` → 搜索买卖方案 → 点真实行「加载查看」→ 编辑器载入「趋势买卖」只读（`editDisabled=true`）、侧栏「趋势买卖v4 系统内置」active、买入/卖出条件树完整，截图留存。评分/买卖两 tab 浏览器复验均通过，无「部分验证」残留。
  - 【P3-1·已如实标注】新增 ConfigView 用例绕开真实 ElSelect 渲染：`ConfigView.system.spec.ts` 新用例「直接 emit loaded + 全局 stub ElSelect/ElOption」，覆盖页面级载入逻辑（`onScoreLoaded`→`selectProfile`→编辑器），但**不覆盖组件→页面的事件链路真实渲染**（el-select 被 stub）。这是为规避 jsdom ElSelect 递归的取舍，断言粒度比端到端真实渲染弱一层；组件→页面真实交互靠浏览器复验兜底（评分/买卖 tab 均已亲验）。**标注为可接受取舍**，不追求 jsdom 端到端。
  - 【P3-2·已登记已知坑】ElSelect 锁非持久 option 的递归循环根因仍在，当前仅「加载查看不设为选中、改走页面级状态」绕开。**已登记进 [DESIGN.md](../../DESIGN.md) 组件清单**「已知约束（ElSelect 递归）」：临时只读项 `tempItem` 不得同步设为当前选中（不 emit `update:modelValue`），否则 el-select 把 `selectedItem` 锁到非持久 option 形成稳定更新循环；契约 = 组件 `onDrawerLoad` 只设 `tempItem` + emit `loaded`，各页 `loaded` 回调在页面级状态载入。明确提示 T5 回测接入「加载查看」时须沿用此契约，避免重蹈。**T5 落地补充（2026-08-01 决策1 重裁）**：【历史误判，已由 §6.8.2 废止，勿再消费】该契约约束的是**组件**（不设 tempItem 为选中），不破；页面侧「临时选中」需求原认为可由 StockDetailView.onTradeLoaded 的规避法实现——页面 `loaded` 回调把临时项**并入持久列表**再设选中（option 变持久，天然避开锁非持久递归）。**此结论经二次复审证实错误**：组件持久 `items` 私有、页面数组不传回，「并入后选中」实际仍锁内部 tempItem，递归未真正消除。最终定为方案b：选择器外只读展示（见 §6.8 决策1、§6.8.2）。

### 阶段 5 · 回测专属接入

#### 6.8 任务 T5：回测页选择器 + 历史浏览 + 同步重跑
- 状态：已完成（2026-08-01 落地；经 2026-08-01/08-02 五轮 Request Changes 复审逐项整改后重验通过，第四次 5 P1+2 P2 见 §6.8.12、第五次 1 P1+2 P2 见 §6.8.13）　依赖：T3,T2C
- 涉及：`BacktestView.vue` 评分方案 `:1036`、选股方案 `:1075`、买卖方案 `:1118`、历史区 `:955-978`；**后端** `services/backtest_service.py::list_runs` + `api/backtest.py::list_runs`
- 目标：**3 个方案选择器**（评分/选股/买卖）各带搜索入口（方案有系统内置段）+ 历史回测浏览入口（tenant/public，无系统内置，默认全体）+「复用参数重跑」（同步，按钮 loading）。
- 操作：**4 个入口**（3 方案 + 1 历史）按 §7.2；方案选择器临时只读；历史浏览只读，仅同步重跑产生自己的新 run。
- **本轮范围扩为「前端 + 后端回测分页契约」（用户拍板）**：回测抽屉分页需真 `total`，原 `GET /api/backtest/runs` 仅 `limit`（无 offset/total）。后端 `list_runs` 抽共享 `_runs_where/_runs_q_filter/_runs_order`，加 `offset`，新增 `count_runs`；无 q 路径 SQL `LIMIT %s OFFSET %s`（仅 offset 时 `LIMIT ALL OFFSET %s`——PG 与 DuckDB 均合法，无需方言分支）+ 同 where `COUNT(*)`；q 路径 Python 全量过滤后 `matched[offset:offset+limit]` + `len(matched)`。API 加 `page/page_size`（ge=1/le=200），分页模式回 `{runs,total,page,page_size}`，兼容模式（不传 page/page_size）保持 `{runs}`，`runs` 键不变（平铺下拉 `listRuns` 无缝）。前端 `api/backtest.ts` 新增 `browseRuns`（契约适配，`listRuns` 不动）。
- **加载查看语义（决策1，两次拍板后于 2026-08-01 二次复审定为「选择器外只读展示」= 方案b）**：路径演化——① 原拍板「只并入候选不选中」→ ② 一次复审重裁「页面侧并入持久列表后选中」→ ③ **二次复审证实 ② 不成立并定为方案b**。② 的错误根源：组件持久 `items` 是私有、页面修改的 `scoreProfiles/profiles/tradeProfiles` 从不作为 props 传回组件，故「页面并入后选中」实际让组件仍锁在内部 `tempItem` 上（`options=[tempItem,...items]`、`selectedItem=options.find(key===modelValue)`），正是 DESIGN 禁止的「临时项成为当前选中」，递归未真正消除、「option 变持久」结论错误。**方案b（最终，用户拍板）**：不破「组件不设 tempItem 为选中」递归契约——加载查看只记 `tempSelected` 快照，**在选择器外**用只读 chip（`AssetProfileLabel` + `AppIconButton` 清除）显示名称（非 opaque ref）；选择器 `modelValue` 不锁临时项、递归天然消除；运行取 ref 优先级统一为 **tempSelected 快照 > mine 选择器值 > 空**（三次复审拍板：「加载查看」是用户最后一次明确操作、chip 即本次运行口径，不改选择器值与持久偏好）；不持久化、不自动运行；用户选 mine 项 / 复制为我的 / 载入历史 / 点 ✕ 即清（`@update:model-value` 无条件清 + `watch(profileId)` 值变化兜底）。**组件选中逻辑与 emits 均不改**。
- **复用参数重跑（决策2，用户拍板）前不弹确认**：`rerunPublicRun` 取详情→`buildBodyFromRun`（解析 params JSON→RunParams，不写回表单/不置脏）→`source_run_ref`→`runBacktest`，组件行内 loading；`onRunRerunDone` toast + `loadHistory` 选中新 run（归「我的」置顶）。`AssetSearchDrawer kind="backtest"`（BacktestView 是首个 kind=backtest 消费方）：segments=[tenant,public] 默认 public（无系统内置段）。
- **loadProfileOptions 删除**：组件为列表唯一事实源（P2-1），三选择器 `ready` 回调喂页面级 ref 并补 normalize；删聚合错误块（v-loading + AppStateBlock profileOptionsError），错误由组件内联 errorMine + AppStateBlock 重试承接。
- 验证（**首轮登记含不实结论，经 2026-08-01 复审 Request Changes 后整改、重新验证，见 §6.8.1**）：首轮登记「538/538 全绿、全部真实通过」**不成立**——实测当时 `npm test` 78 文件断言全过但报 10 个 unhandled errors、退出码 1（假绿）。整改后真实验证见 §6.8.1。后端 `test_backtest_browse_q.py` 3 passed（含新增 `test_backtest_pagination_offset_and_total`）+ 回归 40 passed 仍成立。真实浏览器 5181 复验（debug_system）与决策1/2 临时种子点验为首轮所做，决策1 语义经重裁后已于 §6.8.1 重新复验。
- **本轮不补回测 Playwright E2E，留 T6（决策4，用户拍板）**。
- **遗留候选（T6，不阻塞）**：`AssetSearchDrawer` 幻影行守卫——el-table 数据到达前以空 scope 渲染 body 留下一个 disabled 同名按钮副本（真实数据行按钮正常 enabled），建议 T6 评估用 `:key` 或 v-if 杜绝残留副本。
- **遗留候选（T6，不阻塞，P2-6 复审登记）**：回测 q 分页双查——`list_runs(q=...)` 与 `count_runs(q=...)` 对同一请求各跑一遍 `_query_runs_decorated` 全量读取+装饰（`backtest_service.py:556` 全量过滤切片 + `:518` 再全量），数据量小暂未构成瓶颈。**遗留方案**：一次全量过滤同时产出 page items + total（消除双查），或落实冗余搜索列/keyset 分页。当前不称规模化优化已闭环。
- 完成标准：回测交互符合 §7.2（4 入口）。

#### 6.8.1 T5 复审整改（2026-08-01，Request Changes 后逐项修复重验）

复审判「T5 当前不应通过」，给 4 P1（阻塞）+ 2 P2。逐项核实全部属实、整改并重验如下。整改后真实验证：前端全量 **541/541 退出码 0**（78 文件，无 unhandled errors）、`npm run build`（含 vue-tsc）通过、后端 `test_backtest*`/`test_asset*`/`test_stage6_backtest*` ~~37 passed~~【数量误记，三次复审 P2-3 更正为 **53 passed**（确切 7 文件命令见 §8），本条 37 为分批跑只报一部分的误记，勿再消费】（停服跑、已重启 health=200）。

- 【P1-1·已整改】「复用参数重跑」未复用完整参数：`buildBodyFromRun` 原只复制日期/三方案/持仓数/本金/行业上限，并用当前常量覆盖历史 `horizons/thresholds`，遗漏 `sell_ma_period/take_profit/stop_loss/max_hold_days/rebalance_days/benchmark`（engine.py:244 读取、直接改变撮合与收益），违反 R6。**已修**：改白名单完整复制——`RERUN_BASE_FIELDS`（date_start/date_end/三方案/horizons/thresholds/benchmark）+ `RERUN_STRATEGY_FIELDS`（top_n/initial_capital/industry_max_pct/sell_ma_period/take_profit/stop_loss/max_hold_days/rebalance_days），仅剔除 `source_run_ref`（另附）。**回归测试**：`BacktestView.spec.ts`「复用重跑完整参数白名单」逐字段断言（含撮合参数、基准、评分验证阈值不被常量覆盖）。
- 【P1-2·已整改】`source=mine` 接入后旧 public/preset ref 残留显示 opaque ref：`normalize*ProfileKey` 找不到 mine 匹配原样返回、`restoreParams` 恢复旧值未清。**已修**：`onXReady`（mine 列表 ready 后）若当前值既不在 mine 列表、也不是本次会话注入的临时只读项，则清空并 `ElMessage` 提示重新选择（R3 下拉仅 mine）。**回归测试**：「旧 public/preset ref 恢复后 ready 清空并提示重新选择」。**连带修**：`restoreParams` 在列表未落地（onMounted 早期）时误判清残留——恢复阶段只归一化、清残留统一交给 `onXReady` 兜底（否则真实浏览器把有效裸 id 也清掉，破坏运行校验）。
- 【P1-3·已整改】新增测试假绿、退出码 1：`BacktestView.spec.ts` 把 `layers` mock 成 `{}`（渲染访问不存在的 `grades_order` 抛 unhandled error）+ 布尔 stub 触发 emitsOptions 空引用 + wrapper 未卸载，10 个 unhandled errors、退出码 1，却登记「538 全绿」。**已修**：`validLayers()` 合法 fixture（grades_order/by_grade/base_rate 齐全）；布尔 stub(true) 改占位 defineComponent；AssetProfileSelect stub 持 item 渲染选中项名称（jsdom 需 nextTick 物化）；每个 it 末尾 `wrapper.unmount()`。**连带修**：`state-block-regression.spec.ts`「回测运行失败落到结果区错误态」因 P1-2 连带问题被掩盖，restoreParams 时序修复后恢复。整改后全量 541/541 **退出码 0**（符合「只有退出码 0 才能记全绿」）。
- 【P1-4·已整改】抽屉加载公开回测丢失只读、误启用删除：`onRunLoaded` 只设 selectedRun 不注入 readonly 行、`selectedRunReadonly` 缺 summary 默认 false。**已修**：`onRunLoaded` 把 readonly 公开行注入 `runHistory`（去重）；`selectedRunReadonly` 改 fail-closed（缺 summary 时按 `loadingRun` 而非默认可写）。**回归测试**：「加载查看公开回测 → 删除不可见（readonly fail-closed）」。
- 【P2-5·已整改】重跑完成未按返回值选中新 run：抽屉丢弃 `rerunItem` 返回值只回传原公开记录、父级盲选 `runHistory[0]`。**已修**（用户拍板允许最小扩展两组件 emits）：`AssetSearchDrawer.emit('rerunDone', result, item)` 携带返回值、`AssetProfileSelect` 补透传；`onRunRerunDone` 按 `result.run_id` 精确选中（切 `historySource='mine'` 后 `loadHistory` 选中，找不到回退首行）。**回归测试**：「rerunDone 按 run_id 精确选中」（new_run 不在列表首行，证明非盲选 [0]）。**不改组件选中逻辑**（仅扩展 emits 契约）。
- 【P2-6·已登记遗留】q 分页双查：见上「遗留候选（T6）」，不阻塞、不称规模化优化已闭环。

#### 6.8.2 T5 二次复审整改（2026-08-01，第二次 Request Changes 后逐项修复重验）

第二次复审判「T5 仍有 3 个 P1 阻塞」，给 3 P1（阻塞）+ 3 P2。逐项核实全部属实、整改并重验如下。**关键更正**：本轮推翻了 §6.8 决策1 第②版「页面侧并入持久列表后选中」的核心假设（组件 `items` 私有、页面数组不传回，「并入后选中」实际仍锁内部 `tempItem`，递归未真正消除），经用户拍板定为**方案b：选择器外只读展示**（决策1 段已同步撤销更正）。整改后真实验证：前端全量 **546/546 退出码 0**（79 文件，无 unhandled errors）、`npm run build`（含 vue-tsc）通过、后端 7 文件 **53 passed**（命令见 §8，停服跑、已重启 health=200）、新增真实组件 spec 2/2。

- 【P1-1·已整改】旧 ref 清理存在真实时序竞态、页面仍显示 opaque ref：`onXReady` 只在 mine 列表首次 ready 时清非法 ref，但远端偏好稍后 hydrated（rememberedParamsHydrated watcher）再次 `restoreParams()` 重新写入旧 ref 后没再校验，5181 实测评分选择器持续显示 `avr_WyJzY29yZV9...` 不回弹。**已修（初始化屏障）**：`readyFlags = ref({screen,score,trade})` 记录三类 mine 列表是否 ready；`reconcileProfileRefs()` 统一校验——列表 ready 与偏好 hydration 两个时点任一发生后，对已 ready 的类校验并清掉既不在 mine 列表、也不是本次会话临时只读项的残留；hydrated watcher 在 `restoreParams()` 后追加 `reconcileProfileRefs()` 防回弹。**回归测试**：「旧 ref：ready 后 hydration 再 restore 最终清空不回弹」。
- 【P1-2·已整改】临时项状态未随选择切换清理、复制后的 mine 方案被误标临时：两个确定性失败路径——①加载公开方案→切到自己的方案→运行/保存，自己的有效选择被写成空值；②复制为我的成功并选中→保存，复制后的 mine 方案被当临时剔除、刷新后不能恢复。**已修（方案b 下）**：`onXCopied` 不再调 `onXLoaded`（不再把已归 mine 的复制结果标临时），改独立「并入 mine 并选中」+ 清对应 `tempSelected`；`watch(profileId/scoreProfileId/tradeProfileId)` 当前 key≠临时项 key 立即清临时项；`saveParams` 直接持久化选择器值（方案b 下选择器值即真实 mine 选择，临时快照从不写入，不再按 tempSelected 剔除）。**回归测试**：「临时→mine 切换即丢弃临时项」「复制为我的→不标临时、保存偏好可恢复」。
- 【P1-3·已整改】「页面侧并入持久列表」并未进入选择器的持久 options、递归守卫结论不成立：组件持久 `items` 是私有（`:64`），页面改的 `scoreProfiles/profiles/tradeProfiles` 从不作为 props 传回，故「并入后选中」实际命中内部 `tempItem`——正是 DESIGN 禁止的「临时项成为当前选中」结构；`BacktestView.spec.ts` 用 stub 只验证父页面数组，无法发现真实组件 option 所属关系。**已修（用户拍板方案b：选择器外只读展示）**：加载查看只记 `tempSelected` 快照，**在选择器外**用只读 chip（`AssetProfileLabel` + `AppIconButton` 清除）显示名称（非 opaque ref）；不并入选择器候选、不设为选择器 `modelValue`（组件仍只锁 mine/tempItem、递归天然消除）；运行按 `buildBody` 的 `tempSelected` 快照取 ref（仅当对应选择器为空）；不持久化、不自动运行；切换/复制/载入历史/点 ✕ 即清。**新增 `BacktestView.real-component.spec.ts`（真实 AssetProfileSelect，非 stub）2/2**：验证加载查看后真实选择器 `selectedItem` 为 null、不锁 tempItem、无递归超限、名称经选择器外 chip 展示；临时→改选真实 mine 项后正常选中、chip 清除。**撤销 §6.8 决策1 第②版「option 变持久即避开递归」错误结论**（决策1 段已更正）。
- 【P2-1·已整改】`selectedRunReadonly` 仍不是真正 fail-closed：selectedRun 非空、摘要缺失且 `loadingRun=false` 时返回 false、删除按钮会显示。**已修**：改 `selectedRunSummary ? !!readonly : !!selectedRun`（缺摘要但存在选中值时一律只读）。**回归测试**：非 loading 场景摘要缺失仍只读。
- 【P2-2·已整改】重跑完成会重复加载 mine 历史：改 historySource 触发 watcher 的 `loadHistory()`、紧接着又显式调一次，形成两个并发请求且缺响应序列守卫。**已修**：`pendingRerunSelect` 传递 run_id——已 mine 则 `loadHistory().then(选中)` 单次；否则置 `pendingRerunSelect` + 切 historySource，由 watcher 唯一一次 `loadHistory` 后按 run_id 选中。**回归测试**：「rerunDone 精确选中」覆盖单次加载选中。
- 【P2-3·已整改】后端验证记录数量无法复现：首轮登记「test_backtest*/test_asset*/test_stage6_backtest* 37 passed」，按该范围实际运行得 53 passed（结果更强但命令/数量不一致、留痕不精确）。**已更正**：登记确切命令及实际数量 53 passed（见 §8 后端条目）。

#### 6.8.3 T5 三次复审整改（2026-08-01，第三次 Request Changes 后逐项修复重验）

第三次复审确认前一轮 3 P1 + 3 P2 直接问题基本修复，但方案b 新增 1 个 P1 行为缺口 + 2 个 P2（核心测试盲区、文档旧结论/旧数量未废止）。逐项核实全部属实、整改并重验如下。**关键更正**：本轮放宽方案b 的运行口径限制——删除「仅当选择器为空才用快照」，统一为 **tempSelected 快照 > mine 选择器值 > 空**（用户拍板）；并补「重选同一 mine 值不清临时」这一 watch 不触发边界。整改后真实验证：前端 `BacktestView.spec.ts` 16/16 + `BacktestView.real-component.spec.ts` 2/2、全量 **退出码 0**（见 §8）、`npm run build`（含 vue-tsc）通过。

- 【P1·已整改】已有 mine 选择时「加载查看」公开 chip 不参与运行：`onXLoaded` 只写 `tempSelected` 不清 mine 选择，而 `buildBody` 以 mine 选择器值优先、仅选择器为空才用快照——确定性路径「已选 mine-A → 加载 public-B → 页面同时显示 mine-A 与 chip public-B → 运行仍用 mine-A」，与「运行按快照取 ref」交付表述不符、参数口径错配。**已修（用户拍板：临时快照优先）**：`buildBody` 三类统一为 `tempSelected 快照 > mine 选择器值 > 空`；chip 文案加前缀「本次运行：」避免被理解成纯预览；`saveParams` 仍保存原 mine（不动选择器与持久偏好）；清除 chip/改选 mine/复制/载入历史后快照被清、自然恢复 mine。**删除方案b「仅当选择器为空」限制**（DESIGN/requirement/plan 同步）。**回归测试**：「快照优先：已选 mine→加载公开 chip 后 buildBody 用公开、saveParams 仍 mine」「清除 chip 后 buildBody 恢复 mine」「改选 mine→chip 消失用新 mine」。
- 【P2·已整改】真实组件测试仍绕开核心 `onDrawerLoad` 路径：原 `real-component.spec.ts` 直接 `score.vm.$emit('loaded', pub)`，不经真实 `onDrawerLoad`、不设组件内部 `tempItem`，证据强度被高估。**已修**：改为对真实 AssetProfileSelect 内部的 AssetSearchDrawer stub 发 `load`，让真实 `onDrawerLoad` 完整执行（设 `tempItem` + emit loaded → 页面记 tempSelected）；断言内部 `tempItem` 已存在、`selectedItem` 不锁 temp、chip 显示、无递归、已有 mine 场景运行用公开快照。**连带发现并修复边界**：「已选 mine-A → 加载公开 → 重选同一 mine-A」时组件 `watch(modelValue)` 与页面 `watch(scoreProfileId)` 均因值不变不触发、临时快照不清——按系统设计规范（不改组件选中逻辑、改动最小、不破递归）在页面 `@update:model-value` 回调里无条件清 `tempSelected`；组件 `tempItem` 残留自管、不影响运行口径（运行取页面 tempSelected 快照）也不破递归。
- 【P2·已整改】plan 仍保留互相冲突的旧结论与旧数量：`:302`（T4 复审残留段）仍以「已落地」语气写「页面并入持久列表、option 变持久」旧结论、`:323`（§6.8.1）仍登记 `37 passed`。**已修**：旧段显式标「历史误判，已由 §6.8.2 废止，勿再消费」；37 标误记并指向最终 7 文件、53 passed 命令（§8）。

#### 6.8.4 T5 默认预设与下拉归类收尾（2026-08-01）

- **状态：已完成代码与文档，验证结果见 §8 新增记录。**
- 【P1·已整改】平台账号下拉混入“系统内置”：`mine` 旧谓词只排除 public 平台预设，历史 `private + is_preset` 筛选预设因此被 admin 当作“我的方案”返回。现改为排除平台槽全部预设，不依赖 visibility；普通平台私有资产仍保留在 mine。
- 【P1·已整改】“默认趋势分”代码存在但数据库缺行：旧 CLI 只 seed 筛选，评分/买卖 `seed_defaults()` 无生产入口。现保留 `seed-presets` 命令并扩为三类统一初始化，显式使用 `PUBLIC_BOARD_OWNER`，补齐缺失记录并把稳定预设 id 幂等校准为 public；重复执行不重复插入、不无故改版本。
- 数据影响：无 DDL；只新增/更新平台槽代码登记的稳定预设 id。执行前按项目规则停后端释放 DuckDB，再运行 `python -m backend.cli seed-presets`，完成后恢复服务并核验 health。回滚如需撤销公开状态，应先停止使用统一 seed，再按稳定 id 收回 visibility；删除默认记录会使引用它的历史业务对象失去可解析方案，不建议直接删除。

#### 6.8.5 T5 历史方案展示与运行口径收尾（2026-08-02）

- **状态：已完成代码、测试、构建与文档同步；浏览器验证结果见 §8。**
- 【P1·已整改】自动载入历史回测时，`applyRunParams` 把系统/公开方案 raw ref 直接写入 mine-only `AssetProfileSelect.modelValue`；候选中无对应 option 时退化显示 `default` / `preset_trend_leader`。现统一做历史方案投影：属于 mine 的 ref 正常选中；系统/公开 ref 不写选择器，以选择器外只读 chip 显示历史摘要返回的中文名称与版本；既无名称又不在 mine 的 ref 显示“历史方案已不可用”并 fail-closed，禁止静默换口径。评分验证历史也同步应用其评分参数，不再保留旧表单值。
- 【P1·已整改】稳健性测试 `buildStrategyParams` 只读 mine 选择器值，忽略页面明确展示的 `tempSelected`，与普通回测 `buildBody` 口径分叉。现抽取唯一 `effectiveProfileRefs()`，普通回测、稳健性测试和校验统一消费 **tempSelected 快照 > mine 选择器值 > 空**。
- 【P1·已整改】评分/买卖占位文案标“可选”但运行校验实际必选。现改为“请选择评分方案（必选）”“请选择买卖方案（必选）”；选股最终收敛为“不使用选股方案（默认）”，含义是“不额外套用选股方案”，基础池仍排除 ST 并执行评分与买入条件。后端 nullable 字段继续仅承担旧式回测兼容，当前页面新建策略仍要求评分与买卖方案。
- **回归验证**：`BacktestView.spec.ts` 19/19 + `BacktestView.real-component.spec.ts` 2/2；前端全量 79 文件 **551/551、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。新增覆盖系统历史方案中文投影/raw ref 不入选择器、失效历史 fail-closed、普通回测与稳健性测试同 ref、三类空值文案契约。

#### 6.8.6 T5 回测控件语义收敛（2026-08-02）

- **状态：已完成代码、测试、构建与文档同步；浏览器验证结果见 §8。**
- 用户确认移除页头重复的历史来源下拉：页头「回测记录」固定只加载当前用户自己的记录并用于精确选择；租户公开/全体公开记录继续统一由既有「浏览公开回测」抽屉承接，加载查看与复用参数重跑能力不变。
- 选股方案空值文案由容易误解为“无过滤全市场”的表述改成「不使用选股方案（默认）」；帮助说明明确基础股票池仍排除 ST，并继续执行评分与买入条件，避免把“未叠加选股方案”误读为“所有股票无条件进入回测”。
- `onRunRerunDone` 收敛为只刷新一次 mine 记录，再按返回的 `run_id` 精确选中新记录；删除已无职责的来源状态、watch、空态分支与样式。
- **回归验证**：`BacktestView.spec.ts` 20/20 + `BacktestView.real-component.spec.ts` 2/2；前端全量 79 文件 **552/552、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。

#### 6.8.7 T5 控件语义复核整改（2026-08-02）

- **状态：已完成代码、测试、构建与文档同步；浏览器验证结果见 §8。**
- 【P1·已整改】重跑成功后 mine 列表刷新失败仍回退选旧记录：`loadHistory()` 改返回明确成功状态；刷新失败、接口无 `run_id`、目标记录暂未出现三条失败路径均只提示、不改当前选中，只有找到返回的 `run_id` 才加载新记录。
- 【P1·已整改】公开记录「加载查看」会 prepend 到 mine-only `runHistory`：新增单个 `externalRunSummary` 只读快照，复用已有只读 chip、来源标签和关闭按钮在选择器外展示；顶部候选始终只来自 mine，公开 ref 不写入 ElSelect，复用参数仍通过统一 `activeRunRef` 工作。
- 【P2·已整改】失效偏好在三类 ready 与 hydration 时重复告警：按失效 ref 会话去重，等三类列表及偏好 hydration 全部完成后合并为一次提示。
- 【P2·已整改】页头 mine 历史无上限全量加载：`listRuns` 默认传 `limit=100`，顶部只承载最近 100 条，避免不同签名长期积累后全量 JOIN、传输和渲染。
- **回归验证**：`BacktestView.spec.ts` 23/23 + `BacktestView.real-component.spec.ts` 2/2；前端全量 79 文件 **555/555、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。新增覆盖公开快照不污染 mine、刷新失败不误选、目标缺失不误选、失效提示只出现一次。

#### 6.8.8 每日榜单选择与交易日体验收敛（2026-08-02）

- **状态：已完成代码、测试、构建、浏览器验证与文档同步；结果见 §8。**
- 用户重裁榜单交互：它是“选择即查看结果”页面，加载查看公开/系统方案后应直接成为当前只读选项并自动刷新；普通方案改选、交易日和 Top N 变化同样自动刷新，“刷新”保留为显式重试/重算入口。此结论取代 T4 的“榜单加载查看不切换、不自动运行”旧口径。
- `AssetProfileSelect` 新增默认关闭的 `selectLoaded` 能力：启用时加载项进入独立稳定 `selectedLoadedItem` 后回写 `modelValue`，不把一次性 `tempItem` 锁为 ElSelect 当前选项；仅 BoardView 启用，回测等页面仍保持既有选择器外快照/显式执行契约。
- 榜单首屏等待方案列表与交易日历两路 ready 后只发一次请求，日期明确显示数据最新交易日；请求加入序号守卫，快速切换时旧响应不得覆盖新方案。筛选页与配置页评分试算的同类单日控件统一使用 `TradeDatePicker.defaultLatest`；训练、回测和数据任务的显式日期区间不改。
- mine-only 资产下拉不再重复展示“我的”来源标签；只有系统内置、租户公开和全体公开只读项保留来源标签。

#### 6.8.9 回测记录来源标签复核整改（2026-08-02）

- **状态：已完成代码、测试、构建与文档同步；浏览器验证结果见 §8。**
- 【P2·已整改】上一轮只覆盖统一 `AssetProfileSelect`，遗漏 `BacktestView` 页头自定义回测记录 `el-select`；该列表固定请求 `source=mine`，却仍无条件渲染 `AssetVisibilityTag`，导致候选重复显示“我的”。
- 抽取共享 `assetDisplaySource()`，统一约束 mine 返回空展示来源、preset/tenant/public 保留来源；`AssetProfileSelect` 与回测记录下拉共同消费，公开回测选择器外只读快照继续保留来源标签。
- 【P1·复核新增并整改】5181 在偏好 hydration 已完成、mine 列表尚未 ready 的短暂窗口真实复现买卖方案 opaque ref 闪现，约 1 秒后才被 `reconcileProfileRefs()` 清空。新增三类 `guardedProfileModel` 初始化显示屏障：ready 前选择器只接收空值，ready 后再投影有效 mine ref 或清理失效 ref；回归同时断言页面内部可暂存待校验 ref，但任何时点不得传给 ElSelect。
- **复核范围**：全仓 `AssetVisibilityTag mode=source` 与 `AssetProfileLabel` 消费点；资产方案下拉均走 `AssetProfileSelect`，唯一自定义资产下拉为回测记录，已收敛。资源库抽屉本身用于跨来源浏览，继续显示来源属于必要信息。

#### 6.8.10 回测记录下拉定位整改（2026-08-02）

- **状态：已完成代码、回归测试、构建、浏览器空数据交互验证与设计文档同步；结果见 §8。**
- 【P1·已整改】历史记录名称、日期和收益共同撑大下拉内容宽度，Element Plus 的 Popper 在右侧空间不足时从默认 `bottom-start` 回退到 `left`，导致弹层覆盖页面左上区域、与触发控件失去视觉关联。
- 回测记录选择器启用 `fit-input-width` 并显式声明 `placement=bottom-start`：弹层宽度与 340px 输入框一致、优先在控件正下方展开；候选行改为 flex 布局，长名称省略并保留完整 title，日期与收益固定可见。继续复用原生 `el-select/el-option`，未新增平行弹层组件。

#### 6.8.11 全量复核阻塞项统一整改（2026-08-02）

- **状态：已完成代码、回归测试、构建、文档同步与可用数据范围内的浏览器验证。**
- 【P1·已整改】公开回测关闭后遗留方案参数且按钮仍置灰：进入公开查看前保存完整页面快照，关闭时原子恢复表单、结果、选中记录、来源和 dirty 状态；无快照兜底明确恢复为可运行态。
- 【P1·已整改】回测 A→B 快速选择、加载中关闭和复用参数请求存在迟到覆盖：统一使用 `runLoadSequence`，只有当前代次可写表单、结果、错误和 loading；加载新记录时先清旧结果，避免失败时出现“新选中+旧结果”。
- 【P1·已整改】榜单清空方案未使在途请求失效：所有方案变化先递增请求代次；后端日期回写保持同步屏障到 nextTick，避免归一化日期触发第二次请求。
- 【P1·已整改】买卖方案说明优先显示 mine、实际运行却取公开快照：新增唯一 `effectiveTradeProfile`，卖出规则展示与 `effectiveProfileRefs()` 同为临时快照优先。
- 【P1·已整改】评分验证页面复用参数后运行丢 `source_run_ref`：来源引用移出 strategy 分支，策略与评分验证统一透传审计来源。
- 【P2·已整改】`AssetProfileSelect` mine 列表失败新增 `loadFailed`，榜单首屏结束 pending 并显示可重试错误；重试成功后自动选中并加载。`TradeDatePicker` 监听共享 `dataMax` 后续恢复，展开空日历时可重试首次失败。
- **复用判断**：请求竞态复用项目既有 sequence 模式；方案列表失败复用统一选择器事件，不在榜单复制 fetch；交易日恢复继续消费 `useTradeDates` 单例；买卖展示与请求共用有效方案计算。未新增平行组件、API 或样式。

#### 6.8.12 T5 四次复审整改（2026-08-02，第四次 Request Changes 后逐项修复重验）

- **状态：已完成代码、回归测试、构建、后端重验与文档同步；可用数据范围内的浏览器验证见 §8。**
- 第四次复审判「T5 不能通过」，给 5 P1（阻塞）+ 2 P2。逐项核实全部属实、整改并重验如下。**整改后真实验证**：前端全量 **80 文件 569/569、退出码 0**（无 unhandled errors）、`npm run build`（vue-tsc + Vite）通过；后端 8 文件 **61 passed**（含新增 `test_backtest_review4_failclosed.py` 7 例；停服跑、已重启 health=200）。
- 【P1-1·已整改】公开回测复用成功后没有正确退出「公开查看态」：`reuseCurrentRunParams` 保留 `externalRunSummary/beforeExternalRun`、`doRun` 成功后只清 `nextRunSourceRef`、`onRunRerunDone` 只清公开摘要未清进入前快照——运行成功后页面仍可能显示「正在查看公开回测」，关闭公开快照会把刚产生的新结果恢复成旧状态。**已修**：抽取统一 `commitMineRun()` 状态转换——mine 新结果成为当前结果时同时清 `externalRunSummary` + `beforeExternalRun`；覆盖页面运行（`doRun`）、抽屉直接重跑（`onRunRerunDone`）、查重后加载 mine（`run()` choice==='load'）三条路径。
- 【P1-2·已整改】「查看买入当日榜单」仍使用 mine 选择器值、与实际回测口径分叉：`openDayBoard` 调 `computeBoard` 传 `scoreProfileId.value`，加载系统/公开历史后选择器为空或仍 mine-A，下钻退回默认评分或 mine-A。**已修**：新增 `resultScoreRef` 保存当前结果实际评分 ref（`doRun` 用冻结 body、`loadRun` 用该 run params 写入，纳入 `RunViewSnapshot` 快照/恢复）；`openDayBoard` 改用 `resultScoreRef`，与回测口径一致。
- 【P1-3·已整改】复制成功但 mine 刷新失败时选中无法解析的 opaque ref：`reload()` 失败清 `items` 吞异常、`onDrawerCopied` 无论成功与否都写新 `modelValue`。**已修**：`reload()` 失败保留旧列表并返回 `null`；`onDrawerCopied` 刷新失败时用复制响应构造临时 mine summary（含名称）置顶进 `items` 再选中并 emit `copiedItem`，不写无法解析的裸 ref。**回归测试**：real-component.spec「复制成功但 mine 刷新失败：显示名称非 opaque ref」。
- 【P1-4·已整改】评分验证对显式不可见/失效方案 fail-open、静默改用默认评分：`run_signal` 的 `_load_score_profile` 返回 `None` 交给分析器等同默认方案，失效/下架/跨租户竞态时「复用重跑」可能成功落库并审计但实际非按原方案。**已修**：新增 `_ensure_explicit_deps_visible()` 统一解析三类显式依赖，任一显式 ref 当前用户不可见/不存在即 `ValueError`（API 转 400），在 `prepare`/`run_signal`/`run_strategy` 持久化与审计前调用（strategy 的 trade/score 本由引擎 fail-closed，此补齐 screen 与 signal 的 score 并前置到持久化之前）。**回归测试**：不存在/跨租户私有/失效 screen/score/trade ref 均拒绝且不落库。
- 【P1-5·已整改】回测 ID 只有秒级精度、同一用户并发互相覆盖：`_new_id` 生成 `bt_{kind}_YYYYMMDDHHMMSS`、`_persist_run` 先 DELETE 再 INSERT——同秒多标签/重试/并发得到相同 ID 交叉删除记录。**已修**：`_new_id` 加短 UUID 后缀（同秒 200 次生成全唯一）；`_persist_run` 状态转换改 `UPDATE`（running→done/failed 不删行），唯一性由 `_new_id` 保证、同条件去重仍由 `_purge_signature` 负责，不再用 DELETE 承担 ID 生成。**回归测试**：并发唯一 + 状态转换单行不丢记录。
- 【P2-1·已登记遗留，不阻塞】带 q 分页仍两次全量读取+装饰：`count_runs(q)` 与 `list_runs(q)` 各跑一遍 `_query_runs_decorated`。计划已明确登记 T6（一次过滤同时产出 items+total，或冗余搜索列 SQL 层分页），不能称性能闭环。
- 【P2-2·已整改】注释/行号/状态未同步：`BacktestView` 头注释仍写「只并入候选」→ 改方案b 快照优先口径；`requirement.md:249` 旧行号 `:1036/:1075/:1118` → 改组件 test-id/函数定位；T5 状态行按 P1 未闭环如实降级后于本轮验证通过恢复。

#### 6.8.13 T5 五次复审整改（2026-08-02，第五次 Request Changes 后逐项修复重验）

- **状态：已完成代码、回归测试、构建与文档同步；本轮纯前端 + 类型契约（未改后端逻辑）。**
- 第五次复审确认第四次 4 个 P1 已修复，但 P1-1 仍存在失败路径，判 T5 暂不能恢复「已完成通过」，给 1 P1（阻塞）+ 2 P2（P2-1 随 P1-1 阻塞）。逐项核实属实、整改并重验。**整改后真实验证**：前端全量 **80 文件 576/576、退出码 0**（无 unhandled errors）、`npm run build`（vue-tsc + Vite）通过。
- 【P1-1·已整改】commitMineRun 在新 mine 详情加载成功前提交：`onRunRerunDone` 与查重「加载历史」分支都先 `commitMineRun()` 再 `loadRun()`——重跑已落库但 `getRun()` 网络/服务异常失败时，公开摘要与 `beforeExternalRun` 已永久清除、结果被 `loadRun` 清空，用户既看不到新结果也无法关闭公开查看恢复原现场。**已修**：`loadRun` 拆为 `fetchRunDetail`（只发请求取详情、不碰任何页面状态）+ `applyRunDetail`（应用详情到表单/结果/resultScoreRef）；两条路径改为「先成功取得详情 → 原子执行 commitMineRun + 选中 + applyRunDetail」，详情加载失败时不动 `externalRunSummary/beforeExternalRun`，用户仍可关闭公开查看恢复。**回归测试**：抽屉重跑成功但详情失败仍可恢复公开 A；抽屉重跑成功且详情成功则公开摘要+快照同清；查重 load 详情失败不销毁快照、成功则同清。
- 【P2-1·已整改，随 P1-1 闭环】前端补 P1-1/P1-2 行为覆盖：`BacktestView.spec.ts` 新增 describe「公开查看态原子提交 + 冻结评分口径」5 例——三条 commitMineRun 路径中两条（抽屉重跑、查重 load）的失败与成功分支；`loadRun → resultScoreRef → openDayBoard` 的 computeBoard 第三参实际断言；`doRun` 冻结 body 评分写 resultScoreRef + 快照恢复 resultScoreRef 断言。原「复制成功但刷新失败」1 例保留。
- 【P2-2·已整改】复制兜底仍存在无 summary 分支：`onDrawerCopied` 原仅 `reload()===null` 才构造 fallback——刷新成功但新记录暂未出现仍写无 option 裸 ref；`AssetCopyResult.name` 可选，fallback 名称退化为 `profile_ref/id`（opaque ref）。**已修**：① 统一为「刷新失败 或 列表暂缺新项」都构造可解析临时 mine summary；② `AssetCopyResult.name/version` 收紧为必填（后端复制契约默认「原名 副本」+version=1），三个复制 API（score/screen/trade）返回类型同步收紧；③ 兜底名防 null/空串退化，用中文「{assetLabel} 副本」。**回归测试**：real-component.spec 增至 5 例（列表缺新项兜底、name 空串中文兜底）。

### 阶段 6 · 全链路验收

#### 6.9 任务 T6：验收、测试与构建
- 状态：待开始　依赖：T3,T4,T5,T1B
- 涉及：Vitest、E2E、stage6 测试、`DESIGN.md` 组件矩阵、`frontend/dist`
- 目标：多租户/多角色 E2E、路由守卫、组件测试、关键视口、构建同步。
- 操作：跑 `pytest backend/tests/`、`npm run test:e2e`、`npm run build`；DESIGN 登记新组件；更新 stage6 断言；**整改 T4 自审查登记项**（§6.7：ConfigView 详情吞错、save/copy 丢 profile_ref、契约测试盲区，及各项 P2）；**补回测 Playwright E2E（T5 决策4 留项：4 入口计数、加载查看不运行、复用重跑归属+loading+source_run_ref 审计）**；**评估 T5 遗留的幻影行守卫残留副本（§6.8）**。
- 验证：全绿 + build 成功 + dist 同步 + 三视口。
- 完成标准：交付红线满足（AGENTS 端口/构建）。
- 实际落地情况：待实施。

## 7. 数据库与 SQL 计划
- 不新增表、不删列；统一 seed 仅补齐/校准平台槽代码预设（C9）。
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
> **前端（2026-07-31，T4 四页接入 + 二/三次审查整改闭环）**：Vitest 全量 `530 passed`（`StockDetailView.spec.ts`、`ConfigView.system.spec.ts`、`AssetProfileSelect.spec.ts` 含整改新增用例——ConfigView 评分/买卖「加载查看」页面级用例、AssetSearchDrawer 幻影行守卫适配）；`npm run build` 通过（含 vue-tsc）。四页一致消费 AssetProfileSelect（ConfigView 评分/买卖 list 形态、BoardView/StockDetailView select 形态），下拉统一 `source=mine`（组件为列表唯一事实源、单请求）、加载只读不自动运行（榜单显式刷新、个股显式评估按钮、评分/买卖不自动试算）。**真实浏览器关键路径复验通过**：评分 tab 加载查看载入「默认趋势分」编辑器只读、买卖 tab 载入「趋势买卖 v4」编辑器只读（ConfigView `@loaded` 接入）；个股加载查看零 trade-eval、点评估才发；榜单加载查看无运行请求、页面只读空态；两页 source=mine 单次。**全量 Playwright E2E 本轮未复跑（留 T6）**；系统内置徽标走 AssetProfileLabel 复用路径未改。
> **前后端（2026-08-01，T5 回测页接入 + 回测分页契约，经两次复审 Request Changes 整改后重验）**：后端 `pytest tests/test_backtest.py tests/test_backtest_browse_q.py tests/test_stage6_backtest_visibility.py tests/test_asset_browse_copy.py tests/test_asset_list_mine.py tests/test_asset_repository.py tests/test_asset_review_fixes.py` = **53 passed**（停服释放 DuckDB 锁后跑、已重启 health=200；含 `test_backtest_browse_q.py` 3 passed 分页用例 `test_backtest_pagination_offset_and_total`——q 路径 count==5/offset 切片不漏不重、无 q 路径分页拼接==全列）。前端 `BacktestView.spec.ts`（三次复审整改后 16/16）+ `BacktestView.real-component.spec.ts`（真实 AssetProfileSelect 挂 BacktestView、经真实 onDrawerLoad 完整链路验证递归契约+快照优先，2/2）+ 全量 **548/548 退出码 0**（79 文件，无 unhandled errors）、`npm run build`（含 vue-tsc）通过。BacktestView 三选择器（评分/选股/买卖 select 形态）+ 历史区「浏览公开回测」（首个 kind=backtest 消费方）接入；**范围扩为前端+后端回测分页契约（用户拍板）**——`list_runs`+`count_runs` offset/total、API `page/page_size` 回 `{runs,total,page,page_size}`、`runs` 键兼容。**一次复审整改（§6.8.1）**：4 P1（重跑完整参数白名单、旧 ref 残留清空、假绿退出码归 0、公开回测只读 fail-closed）+ 1 P2（rerunDone 精确选中）逐项修复重验；1 P2（q 双查）登记 T6 遗留。**二次复审整改（§6.8.2）**：3 P1（旧 ref 时序竞态 readyFlags 屏障+reconcileProfileRefs、临时项切换清理+onXCopied 独立、方案b 选择器外只读展示+真实组件测试）+ 3 P2（readonly fail-closed、重跑单载、后端数量 37→53 留痕更正）逐项修复重验；**推翻一次复审「页面侧并入持久列表后选中」结论，用户拍板定为方案b：选择器外只读展示**。**三次复审整改（§6.8.3）**：1 P1（已选 mine 时 chip 不参与运行——buildBody 改快照优先 tempSelected>mine>空、chip 标「本次运行：」、删「仅当选择器为空」限制）+ 2 P2（真实组件测试改走真实 onDrawerLoad 完整链路并补「重选同值」边界、plan 旧结论/旧数量显式废止标注）逐项修复重验。**真实浏览器 5181 复验**：确认选择器无 opaque ref（readyFlags 屏障生效）、4 入口正常渲染、无控制台错误；本地库 preset/tenant/public 方案为空（一次复审种子已回滚），「加载查看 → chip → 运行参数」链路未能在浏览器亲验——该链路改由 `BacktestView.real-component.spec.ts` 真实组件测试覆盖，记为**部分验证**。**全量 Playwright E2E 本轮未复跑（决策4 留 T6）**；遗留幻影行守卫残留副本与 q 双查（T6 评估）。**说明**：本条为首轮登记（含「538/538 全绿」「37 passed」不实/不精确结论）经三次复审更正后的如实口径——当时退出码实为 1、后端实为 53 passed，整改后才达成 548/548 退出码 0。
> **后端与页面（2026-08-01，§6.8.4 平台预设收尾）**：资产相关 9 文件定向回归 **73 passed**；后端全量排除已登记既有失败 `test_stage5_audit_tenant_admin_is_scoped_to_own_tenant` 后 **731 passed, 1 deselected**，该既有用例单跑仍为期望 200/实际 403，与上方历史记录一致。统一 `python -m backend.cli seed-presets` 连续执行两次均成功，真实库结果为 `mine_preset_ids` 三类全空、系统内置筛选 5 / 评分 1（`default`）/ 买卖 2。5181 真实浏览器复验：筛选“我的方案”下拉为空且系统内置抽屉显示 5 项；评分系统内置抽屉显示“默认趋势分 v1”。本轮未改 `frontend/src`，故未重跑前端 build/Vitest；Ruff 环境未安装，未验证。后端已按测试前状态恢复，`/api/health=200`。
> **前端（2026-08-02，§6.8.5 历史方案展示与运行口径收尾）**：`BacktestView.spec.ts` **19/19**、`BacktestView.real-component.spec.ts` **2/2**；Vitest 全量 79 文件 **551/551、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。覆盖系统历史方案中文投影、raw ref 不进入 mine-only 选择器、失效历史 fail-closed、评分验证历史参数同步、普通回测与稳健性测试统一 `effectiveProfileRefs()`、评分/买卖必选及选股不选=全市场文案。5181 浏览器验证：无历史账号下三项新占位文案与页面渲染已验证；admin 特定历史记录的中文 chip 实际链路因本轮未使用 admin 会话，记为**未验证**，由历史参数与真实 PG 摘要匹配的组件回归覆盖。
> **前端（2026-08-02，§6.8.8 每日榜单交互收敛）**：定向 `AssetProfileSelect.spec.ts` + `TradeDatePicker.spec.ts` + `state-block-regression.spec.ts` **24/24**；Vitest 全量 **80 文件 559/559、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。5181 使用 `debug_normal` 真实验证：榜单首屏交易日显示 `2026-07-31`；系统内置「默认趋势分 v1」点“加载查看”后直接成为当前选项（保留“系统内置”来源标签），无需二次下拉选择即自动展示 Top 50 榜单与“已缓存”状态；筛选页单日控件、配置页评分试算单日控件均显示同一最新交易日；控制台 error 日志为空。mine-only 候选不显示“我的”标签由真实 `AssetProfileSelect` 组件测试覆盖；本地 `debug_normal` 无 mine 方案，故该标签在浏览器有数据场景记为**未验证**。训练/回测/数据任务显式日期区间经代码范围复核未启用 `defaultLatest`。
> **前端（2026-08-02，§6.8.9 回测记录来源标签整改）**：定向 `AssetProfileSelect.spec.ts` + `BacktestView.spec.ts` + `BacktestView.real-component.spec.ts` **36/36**；Vitest 全量 **80 文件 560/560、退出码 0**，无 unhandled errors；最终 `BacktestView.spec.ts` 24/24 与 `npm run build`（vue-tsc + Vite）再次通过。新增断言 mine 回测记录保留完整名称但不渲染来源标签，公开回测快照仍显示 public 来源；并覆盖 ready 前旧偏好 ref 不传给选择器、ready 后清理。5181 初次复核真实发现初始化短暂显示 opaque ref，整改后在加载后 250ms 快照已只显示中文占位、无内部 ref，控制台 error 为空。`debug_normal` 与 `debug_system` 均无 mine 回测记录，故“有数据下拉展开后不显示我的”的真实浏览器数据场景明确记为**未验证**，由 BacktestView 渲染回归覆盖。
> **前端（2026-08-02，§6.8.10 回测记录下拉定位整改）**：`BacktestView.spec.ts` **24/24**，新增断言历史选择器 `fitInputWidth=true`、`placement=bottom-start`；设计间距契约 **5/5**，Vitest 全量 **80 文件 560/560、退出码 0**，`npm run build`（vue-tsc + Vite）通过。5181 真实打开空记录下拉，量测触发框与弹层均为 **340px**，弹层 `data-popper-placement=bottom-start` 且坐标位于触发框下方；当前调试账号无 mine 回测，故多条长名称候选的真实数据页面明确记为**未验证**，长名称省略、日期收益固定与完整 title 由代码和组件回归覆盖。
> **前端（2026-08-02，§6.8.11 全量复核统一整改）**：新增覆盖公开查看关闭恢复、历史请求乱序、加载中关闭、评分验证来源审计、mine+公开买卖展示/运行同口径、榜单清空废弃迟到响应、方案列表失败重试和交易日后续恢复；定向 **56/56**，Vitest 全量 **80 文件 568/568、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。5181 `debug_normal` 真实验证：榜单默认交易日 `2026-07-31`，系统内置「默认趋势分 v1」加载后直接选中并自动展示 Top 50 与“已缓存”，控制台 error 为空。公开回测抽屉实际为 0 条，故真实“加载→关闭恢复”和公开评分验证页面复用链路为**未验证**，由新增页面级状态/竞态回归覆盖。本轮未改后端；复核阶段相关后端定向 **84 passed**，服务保持 `/api/health=200`。
> **前端（2026-08-02，§6.8.13 第五次复审 1 P1+2 P2 统一整改）**：Vitest 全量 **80 文件 576/576、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。本轮纯前端 + 类型契约（未改后端逻辑，后端测试不受影响）。`BacktestView.spec.ts` 增至 **34/34**（新增 describe「公开查看态原子提交 + 冻结评分口径」5 例：抽屉重跑详情失败可恢复公开 A、详情成功则公开摘要+快照同清、查重 load 失败不销毁快照/成功同清、loadRun→resultScoreRef→openDayBoard computeBoard 第三参断言、doRun 冻结 body 评分+快照恢复 resultScoreRef）；`BacktestView.real-component.spec.ts` 增至 **5/5**（新增 P2-2 列表缺新项兜底、name 空串中文兜底）。类型契约收紧（`AssetCopyResult.name/version` 必填 + 三个复制 API 同步）经 vue-tsc 全量通过。浏览器侧：公开回测抽屉仍为 0 条，真实「重跑落库但详情加载失败」链路浏览器未验证，由上述失败/成功分支页面级测试覆盖。
> **前后端（2026-08-02，§6.8.12 第四次复审 5 P1+2 P2 统一整改）**：Vitest 全量 **80 文件 569/569、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。后端 8 文件 **61 passed**（停服跑、已 `./start.sh dev` 重启 `/api/health=200`），含新增 `test_backtest_review4_failclosed.py` **7/7**（P1-4 五例：不存在/跨租户私有/失效 screen、score、trade ref 均 `ValueError` 拒绝且不落库；P1-5 两例：同秒 200 次 `_new_id` 全唯一、`_persist_run` 状态转换 UPDATE 单行不丢记录）。前端 `BacktestView.real-component.spec.ts` 增至 **3/3**（新增 P1-3「复制成功但 mine 刷新失败不写 opaque ref」）。本轮改动前端 2 文件（BacktestView/AssetProfileSelect）+ 后端 1 文件（backtest_service）+ 测试 2 文件。浏览器侧：公开回测抽屉仍为 0 条，真实「加载→复用→运行→再次查看/关闭」与「复制成功但刷新失败」链路浏览器未验证，由上述前端真实组件测试 + 后端 fail-closed/唯一性回归覆盖。
> **前端（2026-08-02，§6.8.6 回测控件语义收敛）**：`BacktestView.spec.ts` **20/20**、`BacktestView.real-component.spec.ts` **2/2**；Vitest 全量 79 文件 **552/552、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。覆盖页头仅请求 `source=mine`、不再渲染重复来源下拉、公开浏览入口保留、选股方案空值语义更新，以及重跑完成后单次刷新并按 `run_id` 精确选中。5181 真实页面验证：页头只显示「回测记录」和精确记录选择器，未再出现「全部/我的/租户公开/全体公开」来源下拉；空记录显示「暂无我的回测」；选股方案显示「不使用选股方案（默认）」；点击「浏览公开回测」后抽屉正常显示「租户公开/全体公开」来源段及空态。
> **前端（2026-08-02，§6.8.7 控件语义复核整改）**：`BacktestView.spec.ts` **23/23**、`BacktestView.real-component.spec.ts` **2/2**；Vitest 全量 79 文件 **555/555、退出码 0**，无 unhandled errors；`npm run build`（vue-tsc + Vite）通过。覆盖重跑刷新失败/目标缺失均不误选旧记录、公开加载使用独立只读快照且不污染 mine 候选、失效偏好提示聚合去重、mine 列表限制最近 100 条。5181 真实页面验证：页头仍只显示 mine 记录选择器，控件 title 明示最近 100 条；失效评分/买卖偏好合并为**一次**提示；公开抽屉的租户/全体来源段及空态正常。本地无公开回测，故「真实公开行加载 → 选择器外只读快照」浏览器链路记为**未验证**，由页面级真实状态测试覆盖。
> **前端（2026-07-29，T3 ScreenView 样板，含 R1/R2 两轮审查整改）**：Vitest 全量 `525 passed`（组件用例：抽屉 11 + 选择器 9 = 20）；`npm run build` 通过（含 vue-tsc）；Playwright `asset-search-drawer.spec.ts` 跨用户链路三视口（1100×620/1366×768/1440×900）通过并附截图——截图前等待抽屉 `offsetWidth===560` 稳定、对抽屉面板 locator 截图；列断言覆盖需求合并后的方案类列集合「方案名称（含次行『更新于』)/来源（title 含提供者）/操作」三列头左右边界均在抽屉可视区、操作列 `fixed="right"` 完整可见、无权态 fail-closed 不调 browse。**全量 Playwright 本轮未复跑（未验证，留 T6）**；后端曾按 E2E 写模式重启、验收后已恢复日常模式（/api/health=200）。
- 单元测试：`scoped_where` 四来源互斥（含 **mine 平台槽排除预设**）、preset 负例（private 不出现）、summary 含 updated_at、回测独立 summary、发布码授权解析。具体完成情况：**定向通过**（`test_stage6_asset_visibility` 等）。
- 接口测试：list `source=mine`（**含平台槽 owner 互斥**）；browse `preset|tenant|public`+q+分页+脱敏（preset 严格公开负例）；未知 source 返回 400；发布放开后 normal 可发布/非 owner 403；回测重跑归属+审计；**发布态回测按引用方案名 q 命中**；**复制原子插入不覆盖同 id 既有资产**。具体完成情况：**定向通过**（含 `test_asset_review_fixes` 3 例 P1 回归）。
- 页面/交互测试：Vitest（AssetSearchDrawer 三段/q/空态/复制/临时只读、AssetProfileSelect 双形态）、E2E（搜索→加载只读→复制→我的下拉；下拉仅自己；normal 发布；回测重跑）。具体完成情况：**ScreenView 样板通过（T3，2026-07-29）**——组件 Vitest 20 用例（抽屉 11 + 选择器 9）全过、前端全量 525 passed；`asset-search-drawer.spec.ts` 跨用户链路（发布租户公开→浏览/复制/临时只读/脱敏/系统内置空态/合并列集合可视）三视口通过并附截图；**T4 四页（评分/买卖/榜单/个股详情）真实消费通过**——下拉统一 source=mine（组件唯一事实源、单请求）、加载只读不自动运行、临时项并入 profiles 供 curProfile 解析、ConfigView 评分/买卖 `@loaded` 载入编辑器只读，全量 530 passed、build 通过、真实浏览器关键路径复验通过（ConfigView 双 tab 加载查看载入编辑器只读、个股/榜单加载查看不自动运行）；**T5 回测页真实消费通过（2026-08-01，经两次复审整改）**——三选择器统一 AssetProfileSelect（select 形态、fetchMine source=mine）、历史区首个 kind=backtest 抽屉（两段默认全体）+ 复用重跑（完整参数白名单），全量 546 passed 退出码 0、build 通过、真实浏览器 4 入口复验通过、决策1（最终定为方案b：选择器外只读展示，见 §6.8/§6.8.2）/决策2 点验通过（复用重跑归我的+source_run_ref 审计）；Playwright E2E 留 T6。
- 组件资产闭环测试：AssetSearchDrawer/AssetProfileSelect 在 ScreenView 样板 + 4 页真实消费；DESIGN 矩阵登记；无 Unicode 图标、PageDrawer xl、AppDataTable/AppRowActions。具体完成情况：**DESIGN 真实复用组件清单已登记（T3）**；ScreenView 真实消费通过；**T4 四页真实消费通过**（ConfigView list 形态、BoardView/StockDetailView select 形态，E2E 留 T6）；按钮文案/间距契约扫描全过（button-system/typography-spacing-system）。
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
- 回滚：前端独立回滚；后端授权回填可逆（`asset-publish-open.sql` 回滚段**确定性恢复 C4 前默认角色策略**，属默认策略迁移语义、不保留迁移后人工增删）；平台预设校准不建议删除记录，确需回退时按稳定 id 收回 visibility，并同步回退 seed 入口。

## 10. 风险、假设与待确认项
### 10.1 风险
- [高] R4 安全边界变更：公开资产增多；缓解 owner-only、停用降级、引用范围校验；R8 治理列后续。
- [中] stage6 既有断言（normal 无发布权）需批量更新。
- [中] 存量库迁移必须新 marker，否则 normal 拿不到发布权。
- [中] 部署或库重建后漏执行统一 seed 会使系统内置段为空；页面空态兜底保留，发布流程必须执行并核验三类预设。
- [低] 选择器双形态抽取需保留评分/买卖侧栏形态。

### 10.2 假设
- C1–C9 已确认（§0）。系统内置/`is_preset`/榜单前后端不动。
- R6 = 重跑（不新增 copy）；复制 = 后端自动 id/名称；系统内置 = 严格 `is_preset AND public`，由统一 seed 维护平台预设。

### 10.3 前置核验 / 发布门禁
- **T0（只读事实核验）**：核实线上评分/筛选/买卖预设真实 owner/is_preset/visibility 分布。**只门禁 R14 数据验收与发布**，不阻塞 T1A/T1B（依赖：无，可与 T0 并行）；结论影响 R14 系统内置段实际内容/空态兜底。

### 10.4 待确认项（不阻塞）
- R9 新用户冷启动引导，待产品确认。
