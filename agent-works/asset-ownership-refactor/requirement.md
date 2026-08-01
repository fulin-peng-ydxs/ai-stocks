# 需求文档 · 资产归属重构（asset-ownership-refactor）

> 本文档为正式开发依据。所有现状判断均给出代码事实源（`file:line`）；所有范围结论均可回溯到 §0 上游确认。

## 0. 上游确认来源与继承映射

本需求的闭环在本项目对话中以「逐轮确认 + 结构化选择」方式完成（未单独产出 `requirement-closure.md`）。为可审计，下表把每条已确认结论固化为编号 C，正文一律引用 C 编号，不再使用「用户诉求②」等未定义来源。

| 确认编号 | 已确认结论 | 映射需求项 |
| --- | --- | --- |
| C1 | 保留「系统内置」概念：`is_preset` 列、`AssetVisibilityTag` 徽标、榜单对 `is_preset` 依赖、预设 save 自动置 public 逻辑，前后端一律不改 | R1/R2 撤销（§4.3） |
| C2 | 各资产下拉只加载「自己的资产」（纯 owner，不含系统内置/他人公开） | R3 |
| C3 | 系统内置移入统一搜索弹窗，作为单独一类来源分段（与租户公开/全体公开并列） | R14、R5 |
| C4 | 放开普通用户发布权：`normal` 可自主把自己的资产公开到租户或全体 | R4 |
| C5 | 每日榜单 / `PUBLIC_BOARD_OWNER` 平台槽机制保持现状，不拆 | 无改动（§2.2） |
| C6 | 本次不做收藏 | R11 暂不实现 |
| C7 | 回测「另存为我的」= 复用参数重跑（不复制他人结果快照） | R6 |
| C8 | 搜索弹窗「复制为我的」= 单击即复制，后端自动生成唯一 id、名称默认「原名 副本」 | R5 |
| C9 | 系统内置浏览严格取 `is_preset=true AND visibility=public`（限平台槽），不迁移筛选/买卖预设可见性 | R14（范围边界：只读公开、不迁移） |

## 1. 背景与目标

评分/筛选/买卖三类方案的下拉与列表接口当前一次性返回「自己 + 租户公开 + 全体公开 + 系统内置」混合集（`list_visible`），用户下拉里混着他人和系统内置资产；公开资产没有独立浏览/搜索入口，也没有关键字搜索；发布权限只给管理员（普通用户不能公开自己的资产）。

**本次目标**（在完全保留「系统内置」概念的前提下，C1）：
1. 各资产下拉只加载「自己的资产」（纯 owner，C2）；
2. 放开普通用户自主公开（C4）；
3. 各资产页新增统一「资产搜索」弹窗，来源分段为 **系统内置 / 租户公开 / 全体公开**（C3），支持关键字检索、加载查看、复制保存为「我的方案」（C8）；
4. 回测补「另存为我的」= 复用参数重跑（C7）。

每日榜单机制、系统内置徽标与 `is_preset` 逻辑一律不动（C1/C5）。

## 2. 当前项目现状

### 2.1 「系统内置」的真实构成（保留，不改）
- 常量 `PUBLIC_BOARD_OWNER=("default","admin")`（`backend/storage/pg_ddl.py:42-50`）；**代码 seed / 默认保存路径显示预设归属平台槽 `default/admin`**（`get_current_owner` 非请求链路回落 default/admin）；**线上真实归属分布待 T0 核实**（§13）。
- **仅评分方案**在 owner 恰为平台槽且 `is_preset` 时，`save` 自动置 `visibility=public`（`backend/scoring/score_profile.py:288-290`）。
- **筛选、买卖预设 `save` 不自动公开**（`backend/screening/profile.py:76-77`、`backend/signals/trade_profile.py:206-207` 只写 `is_preset`，无 public 联动）→ 它们即使 `is_preset=true`，默认 `visibility=private`。
- 前端徽标：`AssetVisibilityTag.vue:55`（`source==='preset'`）+ 各页 `:source="p.is_preset ? 'preset' : ..."`；`SystemBuiltinTag.vue`。以上全部保留。

### 2.2 `is_preset` 与每日榜单（保留，不改）
榜单生产/查询按 `is_preset` 圈定方案：`backend/services/public_board.py:54,61,89,136,138`。本次不动。

### 2.3 各类资产 list / copy / 可见性现状

| 资产 | list 接口 | 现状口径 | copy | 关键字段 |
| --- | --- | --- | --- | --- |
| 评分 | `GET /api/score-profiles`（`api/score_profiles.py:52-55`） | `list_visible` 混合（`scoring/score_profile.py:327-343`） | `POST /copy`（`api/score_profiles.py:133-154`→`copy_visible:387-396`） | name/version/is_preset/visibility/updated_at |
| 筛选 | `GET /api/profiles`（`api/profiles.py:67-70`） | `list_visible`（`screening/profile.py:144`） | `POST /copy`（`profiles.py:154-175`→`profile.py:215`） | 同上 |
| 买卖 | `GET /api/trade-profiles`（`api/trade_profiles.py:57-60`） | `list_visible`（`signals/trade_profile.py:271`） | `POST /copy`（`trade_profiles.py:139-160`→`trade_profile.py:342`） | 同上 |
| 回测 | `GET /api/backtest/runs`（`api/backtest.py:132-160`） | `list_runs` 已支持 `?source=mine\|tenant\|public`（`services/backtest_service.py:463-557`，source 分支 `477-485`） | **无 copy**，仅重跑 `source_run_ref`（`backtest.py:55`、`_record_reuse_if_needed:559-566`） | **无 is_preset/name/version/updated_at**；有 kind/date_start/date_end/status/created_at/finished_at/visibility（`pg_ddl.py:333-354`） |
| 榜单方案下拉 | `GET /api/board/profiles`（`api/board.py:143-149`） | 复用评分 `list_visible` | 复用评分 | 同评分 |

- 纯自己查询已存在：`ScoreProfileRepo.list()`（`score_profile.py:321-325`，`WHERE tenant_id AND owner_user_id`），筛选/买卖同构。
- **所有 list 接口均无关键字搜索参数。**

### 2.4 复制接口的真实契约（影响交互设计）
- 复制请求体强制 `id`（必填），`name` 可选（`api/score_profiles.py:40-42` `ScoreProfileCopyBody`）。
- `copy_visible(profile_ref_or_id, new_id, new_name)`：`new_id` 为空报错；**冲突判据是「目标 id 已存在」**（`score_profile.py:394` `"目标方案已存在，请改名后再复制"`），不是「同名 409」；缺省 `new_name` 落 `"{原名} 副本"`（`:396`）。
- 结论（C8，接口必须变更）：**前端一律不传 id**。三类复制请求体（`ScoreProfileCopyBody`/`ProfileCopyBody`/`TradeProfileCopyBody`）改为：去掉必填 `id`，仅保留可选 `name`（前端也不传，用后端默认）。**后端生成唯一 `new_id`**（基于名称的可读 id + 撞库追加序号后缀去重），撞库时**有限次数**（5 次）换 id 重试，仍失败回可读错误码；写入用同一事务原子插入主表 + 版本表（版本表失败整体回滚）；`new_name` 默认「原名 副本」。**返回体必须含新 `id` / `profile_ref` / `name` / `version`**，供前端刷新并选中。此为后端接口契约变更，落在 T2B。

### 2.5 可见性与脱敏工具（复用）
- `backend/services/asset_visibility.py`：`make_asset_ref:58` / `parse_asset_ref:88` / `resolve_asset_ref_or_legacy_id:115` / `decorate_asset_row:164` / `owner_label:155`（脱敏，从不回显真实 user_id）。
- **`visible_sql(alias)`（`:231-237`）是单一合并表达式** `((own) OR public OR (tenant AND same-tenant))`，**不含 preset/tenant/public 分支**；按来源分段是「在其上叠加 source 条件」的独立逻辑（回测 `backtest_service.py:477-485` 即此模式），不是 `visible_sql` 自带。
- **`summarize_asset_row`（`:199-228`）返回 id/asset_ref/name/version/is_preset/visibility/source/readonly/owner_label + ref_key，但不返回 `updated_at`**。搜索弹窗若要展示「更新时间」，需在 summary 补 `updated_at`（方案表有该列）；回测另需独立 summary（无 name/version/is_preset/updated_at）。

### 2.6 发布权限现状（R4 核心改点）
- 发布码分类：`backend/auth/constants.py:52-63`（`ASSET_TENANT_PUBLISH_RESOURCE_CODES` / `ASSET_PUBLIC_PUBLISH_RESOURCE_CODES`，注释「不放入 BUSINESS 避免 normal 获得发布能力」）。
- 撤权 DELETE 两处：`pg_ddl.py:1403-1408`（stage4 撤 `normal` 的 `score-profile:publish-tenant`）、`pg_ddl.py:1543-1548`（stage6 撤 `normal` 全部发布 + 撤 `tenant_admin` 的 public）。
- stage6 授权迁移 `seed_stage6_asset_visibility`（`pg_ddl.py:1523-1568`）用 `_STAGE6_ASSET_VISIBILITY_MARKER` 提前返回；**存量库已跑过，放开必须新增带新 marker 的回填迁移**。
- 守卫 `require_visibility_perm`（`backend/auth/deps.py:59`）：owner-only + publish 权限校验，运行时按规范化 visibility 写 resource_code。
- 角色：**只有 `system` / `tenant_admin` / `normal`**（`backend/auth/constants.py:10-15`），无 `paid`。

### 2.7 前端复用面与 DESIGN 硬契约
- 已有：`AssetVisibilityActions.vue`（发布三档 + copy + reuse，权限位 `canPublishTenant/canPublishPublic` 由各页 `hasPermission` 计算，放开后端后自动生效）、`AssetVisibilityTag.vue`、`AssetProfileLabel.vue`。
- 缺口：**无统一「方案选择器」组件**（5 页各写一份，`ScreenView.vue:539-571`、`ConfigView.vue:1093-1118/1450-1470`、`BacktestView.vue:955-978/1074-1137`、`BoardView.vue:228-249`、`StockDetailView.vue:947-960`）；**无收藏**。
- DESIGN 硬契约（真实实现必须遵守，`DESIGN.md`）：
  - 抽屉用 `PageDrawer`，宽度只传语义档位 `sm/md/lg/xl/wide`，禁止私传 px/%，挂 `LayoutHost`（`DESIGN.md:194`）；本抽屉取 **`xl`**。
  - 表格用 `AppDataTable + AppTableColumn`，禁止原生 `<table>`/`el-table`、禁止传 `width/min-width`（`DESIGN.md:258`）；行操作用 `AppRowActions`（`DESIGN.md:204,267`）。
  - 纯图标操作用 `AppIconButton`（`DESIGN.md:203`）；**禁止 `⚙`/`✕`/emoji/🔍 等 Unicode 充当界面图标**（`DESIGN.md:246-248`）。
  - 四态用 `AppStateBlock` / 表格空态（`DESIGN.md:139,292-294`）。
  - 关键视口至少覆盖 1100×620 / 1366×768 / 1440×900。

## 3. 用户角色与使用场景

角色：`system` / `tenant_admin` / `normal`（无 paid）。
- **normal**：拥有并维护自己的方案；**本次新增**可把自己的方案公开到本租户或全体（C4）；可在搜索弹窗「系统内置/租户公开/全体公开」三段浏览、加载查看、复制为自己的私有方案。
- **tenant_admin**：同 normal（历史已有租户发布权）。
- **system / admin**：维持现状；系统内置（`is_preset` 平台槽）逻辑不变；其公开的评分预设在搜索弹窗「系统内置」段供全体浏览/复制。

场景：
1. 新用户下拉为空（仅自己的资产，C2）→ 点「搜索」→「系统内置」段选官方预设 → 复制为私有 → 使用；也可在「租户/全体公开」段浏览他人方案复制。
2. 资深用户把方案公开到全体，供他人搜索、复制。

## 4. 功能范围

### 4.1 必须实现

| 需求编号 | 需求项 | 来源 | 验收意图 |
| --- | --- | --- | --- |
| R3 | 各资产下拉只加载「自己的」资产（纯 owner，不含系统内置/他人公开） | C2 | 各页方案下拉仅出现当前用户 owner 资产 |
| R4 | 放开普通用户发布权（改发布码归类 + 撤权 DELETE + 新迁移回填 + 默认授权） | C4 | normal 可对自己方案租户/全体公开并生效，不能改他人资产 |
| R5 | 统一「资产搜索」弹窗外壳 + 租户公开/全体公开浏览 + 关键字 + 加载查看 + 复制为我的（单击、后端自动 id/名称） | C3/C8 | 各页有搜索入口；tenant/public 分段可检索、脱敏、可加载/复制 |
| R14 | 搜索弹窗「系统内置」来源分段：严格取 `is_preset=true AND visibility=public`（限平台槽），带系统内置徽标，可加载/复制 | C3/C9 | 系统内置段只出平台槽公开预设，永不泄露 private；筛选/买卖若无公开预设则空态 |
| R6 | 回测「另存为我的」= 以公开回测参数在当前用户环境重跑，生成归属自己的新 run | C7 | 公开回测可复用参数重跑，新 run 归当前执行者，审计保留 `source_run_ref` |
| R7 | 抽取统一 `AssetProfileSelect` + `AssetSearchDrawer`，五页全部选择器实例共用同一组件（通过 list/select 模式保留形态差异，非各页重写） | 复用优先（`frontend-reuse-enforcer`） | 五个页面的全部方案选择器实例均消费同一 `AssetProfileSelect` + `AssetSearchDrawer` |
| R10 | 个股详情买卖方案选择接入「仅自己下拉 + 搜索弹窗」 | C2/C3，与 R3/R5 一致性 | 个股详情与其他页一致 |

### 4.2 建议实现

| 需求编号 | 需求项 | 来源 | 纳入条件 | 处理状态 |
| --- | --- | --- | --- | --- |
| R8 | 放开发布权后为公开资产增加「举报/下架」或管理员治理入口 | 安全边界扩大 | 出现滥用/规模变大 | 后续建议 |
| R9 | 新用户首登默认复制一份 admin 基础公开方案，缓解下拉冷启动 | §3 场景1 | 产品确认要做引导 | 待确认 |

### 4.3 暂不实现

| 需求编号 | 需求项 | 不做原因 | 后续触发 |
| --- | --- | --- | --- |
| R1 | 前端移除「系统内置」徽标 | C1 保留系统内置概念，撤销 | 产品重新决定弱化系统内置展示 |
| R2 | `is_preset` 降级为后台标记 | C1，撤销；`is_preset` 前后端不动 | 同上 |
| R11 | 收藏 / favorite | C6 本次不做；全仓无收藏代码，需全栈从零 | 用户提出常用公开资产管理 |
| R12 | 自选分组、盘感训练接入可见性 | 二者无 visibility/copy/ref 模型，需从零补底座 | 提出跨用户共享分组/训练配置 |
| R13 | 删除 `is_preset` 列 | C1 保留系统内置概念，`is_preset` 不动 | 产品决定重构系统内置/榜单来源机制 |

> 说明：「不迁移筛选/买卖预设可见性」不单列编号，它是 C9/R14 的**范围边界**（R14 严格取平台槽公开预设，筛选/买卖预设不因本次而被改为 public）。

## 5. 详细功能需求

### R3 下拉仅加载自己的资产（纯 owner）
- 功能描述：评分/筛选/买卖/回测/榜单方案下拉只返回当前用户 owner 的资产，不含系统内置、不含他人租户/全体公开。
- 操作流程（后端）：三类方案 list 增加 `source=mine` → `WHERE tenant_id=? AND owner_user_id=?`（复用 `list()` 语义 + `decorate_asset_row`）；回测下拉沿用其 `source=mine`；不传 `source` 维持 `list_visible` 兼容。
- 输入输出：入参 `source=mine`；出参仅自己的资产。
- 异常/边界：新用户下拉为空为正常态，空态引导去「搜索」；搜索弹窗「加载查看」的只读对象作为临时选中项回显，不能被 mine 过滤清空（详见 §7 页面状态流转）。
- 影响：各页 `loadProfiles/loadProfileOptions` 调用参数。

### R4 放开普通用户发布权
- 功能描述：`normal` 可对自己拥有的资产执行「租户公开 / 全体公开 / 收回私有」。
- 操作流程（后端）：①`constants.py` 将 8 个发布码纳入普通业务授权（并入 `BUSINESS_RESOURCE_CODES` 或 seed 授权集合显式并入 normal）并改注释；②删除/反转两处撤权 DELETE（`pg_ddl.py:1403-1408/1543-1548`）；③新增带新 marker（如 `migration.asset_publish_open_v1`）的回填迁移，对存量库给 normal（及 tenant_admin 的 public）授 8 码 + 同事务 bump `perm_ver`；④`require_visibility_perm` owner-only 与「引用方案不低于目标公开范围」校验不变。
- 校验：仍 owner-only；公开回测发布仍校验引用方案范围。
- 影响：`constants.py`、`pg_ddl.py` seed、`seed_stage6_asset_visibility`、权限/路由扫描与 stage6 可见性测试断言。

### R5 统一资产搜索弹窗（外壳 + 租户/全体公开 + 复制）
- 功能描述：资产页点「搜索」打开抽屉，按来源分段 + 关键字浏览资产，可加载查看、复制为自己的私有方案。本条负责抽屉外壳、「租户公开/全体公开」两段与复制；「系统内置」段见 R14。
- 前置条件：用户已登录。
- 操作流程：打开抽屉 → 选来源分段 + 输入关键字 → 分页列表 → 行操作「加载查看」/「复制为我的」。
- 输入输出（后端 browse）：入参 `source∈{tenant,public}`、`q`（名称 ILIKE）、分页；出参走 `summarize_asset_row` 脱敏（含 opaque `profile_ref`/`run_ref`、`source`、`readonly`、`owner_label`、补充 `updated_at`），**不回显真实 owner/tenant/user_id**。
- 复制（C8，§2.4）：单击「复制为我的」→ 前端不弹窗、**不传 id** → 调 `/copy`（请求体去掉必填 id、仅可选 name）→ 后端生成唯一 id + 名称「原名 副本」、有限次重试撞库 → 落当前 owner private → **接口返回新 id/profile_ref/name/version** → 前端刷新「我的」下拉并选中。
- 校验/异常：`tenant` 限同租户且排除自己；`public` 全体且排除自己**并强制排除平台槽公开预设**（`AND NOT (is_preset AND owner=PUBLIC_BOARD_OWNER)`，与系统内置段严格互斥，见 §12 取数规则）；空 q 返回该来源全部；复制失败（撞库重试耗尽/无权）给可读错误；空/错/加载态用 `AppStateBlock`。
- 影响：三类方案新增 browse 接口 + `q`；回测复用现有 `source` 补 `q`。

### R14 搜索弹窗「系统内置」来源段
- 功能描述：搜索弹窗来源分段含「系统内置」，列出平台槽公开预设，带系统内置徽标，可加载查看与复制为我的。
- 操作流程（后端）：browse 支持 `source=preset` → `WHERE is_preset=true AND visibility='public' AND (tenant_id,owner_user_id)=PUBLIC_BOARD_OWNER`（**严格只读公开，C9，永不泄露 private**）；返回经 `summarize_asset_row`（`source='preset'` 触发徽标）。
- 边界（重要）：**按代码**，仅评分方案 save 在平台槽下自动 public（`score_profile.py:288`），筛选/买卖 save 无 public 联动（`profile.py:76`、`trade_profile.py:206`）；**因此筛选/买卖预设默认 private，其「系统内置」段常态可能为空 → 显示空态「暂无系统内置{类型}」（正常态，非缺陷）**；**线上真实分布以 T0 核实为准**。本次不迁移（见 §4.3）。回测无 `is_preset` → 回测搜索弹窗无「系统内置」段。
- 影响：browse 接口 `source` 增加 `preset` 取值；前端来源分段增加一项（回测隐藏）。
- 前置核实：动手前须核实线上评分/买卖/筛选预设的真实 `owner/is_preset/visibility`（§2.1、§13 T0），确保严格条件命中预期数据。

### R6 回测「另存为我的」= 复用参数重跑
- 功能描述：公开回测记录可「以其参数在当前用户环境重跑」，产生一条归属当前用户的新 run（不复制他人结果快照，C7）。
- 操作流程：搜索弹窗/历史区选公开回测 →「复用参数重跑」→ 走现有重跑链路（`source_run_ref` 透传、`_record_reuse_if_needed` 审计），新 run 归当前 owner、visibility=private。
- **执行模型（已核实）**：现有回测 `POST /api/backtest/run` 是**同步执行**、同步返回并落库（`backtest.py:3,7-8`，异步+进度轮询是 M7 规划、不在本次）。因此 R6 重跑**保持同步**：前端只需按钮 `loading` + 成功/失败反馈（区间数月约 10 秒级）；DuckDB 单写锁使并发重跑串行。**本次不做回测异步化**（如需异步须另立独立需求/任务/轮询契约/验收，不由 C7 扩展）。
- 校验/异常：引用方案可见性承接不变；同步重跑超时/失败给可读错误。
- 影响：回测 list 补 `q`；前端回测历史/搜索接入「复用参数重跑」入口（不新增 copy 接口）。

### R7 统一「资产选择器 + 搜索弹窗」组件
- 功能描述：抽取**同一** `AssetProfileSelect`（「我的方案选择器 + 来源徽标 + 搜索按钮入口」）与**同一** `AssetSearchDrawer`，五页全部选择器实例统一消费；通过 `mode`（`list` 侧栏列表 / `select` 下拉）保留形态差异，而非各页重写同类逻辑。
- 影响与验收：`ScreenView`、`ConfigView`（评分+买卖）、`BacktestView`（评分/选股/买卖 3 个）、`BoardView`、`StockDetailView` 的**全部方案选择器实例**都改为消费 `AssetProfileSelect`；验收覆盖「五个页面的每一个选择器实例」，不写「五处」。

### R10 个股详情接入
- 功能描述：个股详情买卖方案选择改「仅自己下拉 + 搜索弹窗」，与其他页一致。

## 6. 数据与接口需求

- **数据表**：无新增表、不删列、不迁移预设（C9）。沿用现有 `tenant_id + owner_user_id + visibility + is_preset` 列。
- **权限元数据**：调整发布码归类使 `*:publish-tenant/public` 进入普通授权；删除撤权 DELETE；新增带新 marker 的回填迁移（含 `perm_ver` bump）。
- **接口**：
  - 三类方案 list：新增 `source=mine`（纯 owner）；browse `source=preset|tenant|public` + `q` + 分页（或独立 `GET .../browse`）。命名/形态对齐回测 `source`。
  - `summarize_asset_row` 补 `updated_at`（方案表有列）；回测单独 summary（id/kind/date_start/date_end/status/created_at/finished_at/visibility/source/readonly/owner_label，无 name/version/is_preset）。
  - 回测浏览关键字：回测 summary 无 `name`，`q` **匹配三类引用方案名称 + kind**（评分/选股/买卖方案名 + 回测类型），不匹配 run id。发布态回测方案引用列为 opaque ref、SQL JOIN 裸 id 取不到名，故 **`q` 在解析 ref、补名后于 Python 侧全量过滤**（**correctness 优先，不设扫描上限/不静默截断**，以免漏匹配或破坏 `limit=None` 全列语义；规模化性能优化留 T5——已确认需求决策）。「另存」= 同步重跑（不新增 copy）。
- **复制接口变更（C8）**：三类 `*CopyBody` 去掉必填 `id`（仅可选 `name`，前端不传）；`copy_visible` 由后端生成唯一 `new_id`、名称默认「原名 副本」、撞库有限次重试；**返回新 id/profile_ref/name/version**；冲突判据是目标 id 存在（非同名）。
- **不变量**：opaque ref 默认只作对外句柄、不落业务表；**唯一例外**是发布态回测——公开/租户可见时把方案引用列（profile_id/score_profile_id/trade_profile_id）改写为 opaque ref 落库以对外脱敏一致，收回 private 时还原为裸 id（见 `_normalize_run_dependencies_for_visibility`/`_restore_run_dependencies`）。browse/list/复制全部经归属键与 `resolve_asset_ref_or_legacy_id`；owner 全程脱敏。

## 7. 页面与交互开发需求

统一「资产搜索抽屉」为跨页复用组件，出 1 份原型代表所有资产类型；各资产页为局部更新，不逐页出原型，但**逐页定义页面状态流转**（下）。

### 7.0 统一「临时只读对象」状态契约（所有资产页共用）
- 搜索弹窗「加载查看」的对象为**会话内临时只读选中项**：注入当前页选择器顶部并标 `readonly`，**不进入「我的」列表/下拉候选**。
- 切换到其他对象即丢弃临时项；**刷新页面 / 关闭标签不保留**（不持久化）。
- 只有「复制为我的」才落库，进入「我的」下拉并选中。
- 「加载查看」只做**选中+只读展示**，**不自动触发计算/评估/回测**；是否运行由用户在该页显式触发（保持各页现状交互）。
- **「选中回显」的页面级语义差异（固化取舍）**：加载查看是否把临时只读项**切换为页面当前选中对象**，按页面交互模型定——
  - **配置页（评分/买卖）/个股详情**：载入即回显。配置页编辑器以当前选中方案为编辑上下文，加载查看须把它载入编辑器只读展示（`@loaded` → 以 profile_ref 拉详情载入，不经选择器选中态）；个股详情评估按钮以当前买卖方案为唯一目标，加载查看须回显选中，用户随后显式点「评估」。
  - **榜单**：**不切换当前选中**。榜单「运行/刷新」以当前选中方案为准，加载查看只是把临时只读对象并入候选供标题/导出/参数解析（`curProfile`），不改变当前选中——避免让用户误以为「已切到该方案」。榜单的运行始终由用户显式点「刷新」触发。
  - **回测（T5，2026-08-01 经两次复审后定为方案b：选择器外只读展示）**：路径演化——① 原拍板「只并入候选不选中」→ ② 一次复审重裁「页面侧并入持久列表后选中」→ ③ **二次复审证实 ② 不成立（组件持久 `items` 私有、页面数组不传回，「并入后选中」实际仍锁内部 `tempItem`，递归未真正消除），用户拍板定为方案b**。**方案b（最终）**：加载查看只记临时只读快照 `tempSelected`，**在选择器外**用只读 chip 显示名称（非 opaque ref）；**不并入选择器候选、不设为选择器选中**（组件仍只锁 mine/内部 tempItem，不破 ElSelect 递归契约）；不改持久偏好、不自动运行；运行按 `buildBody` 的 `tempSelected` 快照取 ref（仅当对应选择器为空）；用户选 mine 项 / 复制为我的 / 载入历史 / 点 ✕ 即清临时项。**组件选中逻辑与 emits 均不改**。

### 7.1 页面 P1：资产搜索抽屉（统一组件）
- 对应需求编号：R5、R14、R7、R10
- 页面类型：抽屉（`PageDrawer` size=`xl`，挂 `LayoutHost`/`#overlays`）
- 页面入口：各资产页选择器区新增「搜索」按钮（`AppIconButton` 或带文案按钮，非 Unicode 图标）
- 原型文件：`prototypes/public-asset-search-drawer.html`
- 页面布局（对齐原型）：
  - 页头：标题「浏览{资产类型}」+ 关闭按钮（`AppIconButton`，非 `×` 字符）
  - 工具栏：来源分段（**系统内置 / 租户公开 / 全体公开**；回测隐藏系统内置段）+ 关键字搜索输入
  - 主区：`AppDataTable + AppTableColumn`（列随资产类型不同，见下）；操作列 `AppRowActions`（「加载查看」「复制为我的」）
  - 分页：`AppPagination`
  - 四态：`AppStateBlock`（加载/空/错误/无权）；空态文案「暂无{来源}{类型}」
  - 关键视口：1100×620 / 1366×768 / 1440×900 均可用；窄侧抽屉按 `xl` 语义档位自适应，不写私有 px 全宽逻辑
- 数据来源：browse（`source=preset|tenant|public` + `q`）；方案类走 `summarize_asset_row`(+`updated_at`)，回测走独立 summary
- 表格列契约（按资产类型）：
  - 方案类（评分/筛选/买卖/榜单方案）：**方案名称**（名称 + 版本，次行显示「更新于 {更新时间}」）、**来源徽标**（含系统内置；`title` 含脱敏提供者）、**操作**——信息项 = 名称、版本、来源、提供者、更新时间、操作，其中版本并入名称行、更新时间并入名称次行、提供者并入来源徽标 tooltip（对齐 `xl=560px` 抽屉，保证全部完整可见、操作列固定右缘、无横向滚动）
  - 回测：回测标识（kind + 日期区间）、状态、创建时间、来源徽标（无系统内置）、提供者（脱敏）、操作（加载查看 / 复用参数重跑）
- 权限与可见性：系统内置段严格 `is_preset AND public`（限平台槽）；租户/全体段脱敏且排除自己；复制/重跑归当前用户 private

#### 7.1.1 功能点：来源分段 + 关键字检索（R5/R14）
- 默认展示：方案类默认「系统内置」段；回测无系统内置段，默认「全体公开」段
- 用户操作：切换来源、输入关键字（防抖）
- 状态变化：切换/输入触发重查，加载态覆盖列表
- 空/错误：空态「暂无{来源}{类型}」（筛选/买卖系统内置段常态可能为空）；错误可重试
- 验收：三来源+关键字正确过滤；系统内置段只出平台槽公开预设；租户/全体排除自己

#### 7.1.2 功能点：加载查看（R5/R14）
- 用户操作：点行「加载查看」→ 关闭抽屉 → 按 §7.0 注入临时只读选中项
- 联动：复用 `AssetVisibilityTag` readonly；不自动运行
- 验收：当前页只读展示该对象，不进入「我的」下拉，刷新后不保留

#### 7.1.3 功能点：复制为我的（R5/R14，C8）
- 用户操作：单击「复制为我的」→ 无弹窗 → `/copy`（后端生成唯一 id、名称「原名 副本」）→ 刷新「我的」下拉并选中
- 保存/异常：成功 toast；极端撞库/无权给可读错误
- 验收：复制后出现在「仅自己」下拉，visibility=private，owner=当前用户（系统内置段同理）

#### 7.1.4 功能点：回测「复用参数重跑」（R6）
- 用户操作：回测搜索/历史区点「复用参数重跑」→ 以公开回测参数在当前环境发起**同步重跑**
- 状态：HTTP 请求期间按钮 loading；响应后成功/失败反馈；成功后新 run 进入「我的」历史
- 验收：新 run 归当前 owner、private；审计含 `source_run_ref`；不复制他人结果快照

### 7.2 更新页面（不单独出原型，逐页状态流转）

| 页面 | 文件:行 | 变更区域 | 页面状态流转要点 |
| --- | --- | --- | --- |
| 筛选方案 | `ScreenView.vue`（载入方案选择器） | 下拉改仅自己 + 「搜索」入口（含三来源段）+ 发布按钮对 normal 可见 | 临时只读按 §7.0；加载后不自动跑筛选 |
| 评分方案 | `ConfigView.vue`（评分侧栏 AssetProfileSelect list 形态） | 侧栏列表改仅自己 + 「搜索」入口 + 发布放开 | 侧栏 `<ul>` 保留；加载后不自动计算 |
| 买卖方案 | `ConfigView.vue`（买卖侧栏 AssetProfileSelect list 形态） | 同评分 | 同上 |
| 榜单 | `BoardView.vue`（头部评分方案选择器 select 形态） | 方案下拉改仅自己 + 「搜索」入口 | 加载只读方案后**不自动跑榜单**、**不切换当前选中**（只并入候选供 curProfile 解析，§7.0 页面级语义差异），由用户显式触发（保持现状） |
| 个股详情 | `StockDetailView.vue`（买卖方案选择器 select 形态） | 买卖方案选择改仅自己 + 「搜索」入口 | 加载只读方案后**不自动重评**，由用户显式触发（R10） |
| 回测 | `BacktestView.vue`：评分方案 `:1036`、选股方案 `:1075`、买卖方案 `:1118`、历史区 `:955-978` | **3 个方案选择器**（评分/选股/买卖）各带「搜索」入口（方案有 is_preset → 有系统内置段）；**历史回测区 1 个「浏览公开回测」入口**（来源 tenant/public，无系统内置，默认全体公开）+「复用参数重跑」 | 方案选择器临时只读按 §7.0；历史区浏览的公开回测只读，仅「复用参数重跑」产生自己的新 run |

> 回测页搜索入口计数明确：**3 个方案选择器各 1 个搜索入口（评分/选股/买卖）+ 历史回测浏览 1 个入口**，共 4 个入口。方案选择器弹窗（评分/选股/买卖方案）有系统内置段（方案有 is_preset）；历史回测浏览弹窗无系统内置段（回测无 is_preset）。

## 8. 边界条件与异常场景
- 新用户下拉为空：正常态，空态引导「搜索」→「系统内置」段复制官方评分预设起步。
- 系统内置段空态：T0 实测（本地库）**筛选预设全 private → 筛选系统内置段常态为空**；评分/买卖预设为 public → 系统内置段有内容。空态时显示空态、不报错、不迁移（生产分布以上线前 T0 复核为准）。
- 临时只读对象：切换/刷新/关闭不保留；不进入「我的」。
- 发布权放开后被停用/删除：复用现有「非 private 资产下线为 private、回测引用恢复裸 id」下架机制（`system-rbac-tenant.md` 用户/租户操作闭环）。
- 复制：后端生成唯一 id，撞库有限次重试；名称默认「原名 副本」；返回新 id/ref/name/version。
- 回测重跑：**同步执行**（现有 `POST /api/backtest/run` 同步，`backtest.py:3,7`），DuckDB 单写锁串行；前端按钮 loading + 成功/失败反馈；本次不做异步化。

## 9. 性能、安全与兼容性
- **安全（重点，R4/R14）**：R4 是安全边界变更；R14 系统内置段严格 `is_preset AND public`（限平台槽）永不泄露 private。必须：owner-only 改可见性；browse/list/copy 全程经 `visible_sql`+归属键，禁信任前端 owner；owner 脱敏不回退；新增 browse 端点挂后端守卫 + 登记 `sys_resource` + 路由扫描测试。
- **性能**：browse 分页 + 关键字 ILIKE，控制结果集与索引。
- **兼容**：`is_preset`/榜单/徽标不动；opaque ref 兼容旧前缀；list 不传 source 维持现状。
- **测试**：波及 `test_stage6_*_visibility`、`test_score_profile*`、路由扫描、资源码/菜单 seed、Vitest 与相关 E2E。

## 10. 业务亮点与优化建议

| 编号 | 优化建议 | 价值 | 处理状态 | 说明 |
| --- | --- | --- | --- | --- |
| R7 | 统一选择器+搜索抽屉组件 | 消除 5 页重复 | 本次纳入 | 复用优先 |
| R9 | 新用户默认复制基础方案 | 缓解冷启动 | 待确认 | 需产品确认 |
| R8 | 公开资产治理/下架入口 | 放开发布兜底 | 后续建议 | 规模变大再做 |

## 11. 验收标准

| 需求编号 | 验收标准 | 验证方式 |
| --- | --- | --- |
| R3 | 下拉仅当前用户 owner 资产（无系统内置/他人公开） | 多角色调试账号（`test-users.md`）验证 + 后端 list 测试 |
| R4 | normal 可对自己方案租户/全体公开并生效，不能改他人资产 | normal 账号 E2E/接口 + 权限守卫测试 |
| R5 | 搜索弹窗租户/全体段可检索、脱敏、加载查看、单击复制（自动 id/名称） | E2E + browse 接口测试（脱敏、排除自己） |
| R14 | 系统内置段严格只出平台槽公开预设（无 private 泄露）；筛选/买卖无公开预设时空态 | browse `source=preset` 接口测试（含负例：private 预设不出现） |
| R6 | 公开回测「复用参数重跑」生成归属自己的新 run，审计含 `source_run_ref`，不复制快照 | 回测接口/前端验证 |
| R7 | 五个页面的全部选择器实例（含回测 3 个）与搜索弹窗共用同一 `AssetProfileSelect`/`AssetSearchDrawer` | 代码审查 + Vitest |
| R10 | 个股详情买卖方案接入仅自己+搜索，加载不自动重评 | 页面验证 |
| R1/R2/R11/R12/R13 | 系统内置徽标不变（R1/R2）；`is_preset` 列保留不删（R13）；榜单不变；无收藏（R11）；无分组/训练接入（R12） | 回归确认无关联改动（负向验收：这些区域零 diff） |
| R8/R9 | 本次不做 | 需求映射标注 `后续建议`/`待确认`，无对应任务 |

## 12. 建议开发顺序（垂直样板优先，验证前移）

1. **阶段 0 · 线上数据基线核验（T0，发布门禁、不阻塞开工）**：**核实线上评分/筛选/买卖预设真实 owner/is_preset/visibility**，确认 R14 严格条件命中数量符合预期、筛选/买卖系统内置段是否常态为空。可与阶段 1 并行；仅门禁 R14 数据验收与发布，不冻结取数契约、不作为进入阶段 1 的前置。里程碑：命中数量与预期空态核验报告。
2. **阶段 1 · 数据与权限契约（T1）**：定 `mine/preset(public)/tenant/public` 互斥取数规则、`summarize_asset_row` 补 `updated_at`、回测独立 summary 字段；发布权回填迁移（新 marker）+ 回滚 SQL 留痕。里程碑：契约与权限迁移测试通过。
3. **阶段 2 · 后端接口（T2）**：三类方案 `source=mine` + browse(`preset|tenant|public`+`q`)；回测按独立字段模型补 `q` + 「复用参数重跑」入口（不新增 copy）。里程碑：接口测试（脱敏、排除自己、preset 负例、q、分页）通过。
4. **阶段 3 · 前端垂直样板（T3，只接入 ScreenView）**：共享抽屉 + 选择器先在筛选页跑通四态、复制、临时只读、关键视口，DESIGN 合规（PageDrawer xl、AppDataTable、AppRowActions、无 Unicode）。里程碑：ScreenView 全链路可用 + Vitest/E2E + 三视口截图。
5. **阶段 4 · 普通方案页扩展（T4）**：接入评分/买卖（ConfigView）、榜单（BoardView）、个股详情（StockDetailView，R10）。里程碑：各页一致、加载不自动运行。
6. **阶段 5 · 回测专属接入（T5）**：3 个方案选择器（评分/选股/买卖）+ 历史浏览入口 + R6 同步重跑。里程碑：回测搜索入口计数（4 个）与状态流转符合 §7.2。
7. **阶段 6 · 全链路验收（T6）**：多租户/多角色 E2E、路由守卫、组件测试、关键视口、`npm run build` 同步 dist、stage6 测试更新。

## 13. 前置核实任务与遗留确认项

**T0 是只读事实核验任务（非"遗留确认项"），门禁范围有限**：
- T0 = 连库核实线上评分/筛选/买卖预设的真实 `owner/is_preset/visibility` 分布。
- **仅门禁**：R14 系统内置段的**数据验收**与**上线发布**（决定各类系统内置段实际内容与空态范围）。
- **不门禁**：R4 权限迁移（T1B）、R3/R5 的 tenant/public 取数与前端组件等与预设分布无关的任务可并行推进。

**真正的遗留确认项（不阻塞任何开发）**：
- **R9 冷启动引导**：是否给新用户默认复制一份基础公开方案，待产品确认。
