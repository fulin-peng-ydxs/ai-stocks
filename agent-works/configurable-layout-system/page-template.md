# 新页面开发模板与选型清单（AI 固定流程）

> 本文是「把页面交给 AI 开发」的固定抓手：照此选型、声明、填充、校验、登记，减少随机 CSS / 随机滚动 / 随机布局层级。
> 强制规则在代码（`frontend/src/layout/` 校验器 + 契约测试），本文只给流程与可复制骨架。前端规范事实源是 [DESIGN.md](../../DESIGN.md)。

## 0. 开工前必读

1. 读 [DESIGN.md](../../DESIGN.md) §1~§8（视觉主题、颜色预设、排版间距、组件关系、布局原则、层级、禁止事项、响应式）。
2. 读 `frontend/src/layout/archetypes.ts`（原型预设）和 `frontend/src/layout/components.ts`（组件能力目录）。
3. 涉及新增可导航页面、系统页、API 动作或按钮权限时，读 [system-rbac-tenant.md](../architecture/system-rbac-tenant.md) 的“新页面接入菜单和权限”。
4. 守 [AGENTS.md](../../AGENTS.md) 的协作约束：原型与组件清单选定后，先给用户推荐 + 理由再开发。

## 1. 固定流程

1. 判断业务页面类型 → 按 [DESIGN.md](../../DESIGN.md) §5.3 选一个**原型**，并按本文 §2 / §4 写明选择理由。
2. 把推荐原型 + 理由告诉用户，确认后开发。
3. 检查 DESIGN.md “真实复用组件清单”和 `frontend/src/components/**`，先复用已有真实组件；控件选型、图标按钮和系统组件种类边界按 DESIGN 执行。
4. 优先运行 `npm run scaffold-page -- --pageKey <key> --label <中文名> --archetype <原型>` 生成骨架；脚手架中的 `data-scaffold-placeholder` 是未完成标记，接入真实组件和四态后必须删除；独立的 `responsive-review-pending` 按下方「响应式设计」完成设计与实测后替换为具体结论，两类未完成标记均由契约测试拦截。需要手写时必须同样添加 `responsive-review-pending` 待验收标记，再用 `createLayout(archetype, pageKey)` 起默认 `PageLayout`，按需覆盖 `slots`/`editable`/`responsive`。
5. 模板用 `<LayoutHost :layout="effective">` + 具名插槽（`slot.id`）填业务组件；浮层放 `#overlays`。短表单和轻量查看使用 `AppDialog`，完整业务详情使用 `AppDetailDrawer`，专用底层抽屉使用 `PageDrawer`，页面设置使用 `PageSettingsDrawer`；页面禁止直接使用 `el-dialog`、`el-descriptions` 或 `el-drawer`。数据表格使用 `AppDataTable + AppTableColumn`，列只声明 `label/prop/role` 等语义，不声明 `width/min-width/align/header-align`；语义角色同时统一表头和单元格对齐，横向比较矩阵数值使用 `comparison-number`；普通名称列使用 `name`，带前置控件和主副信息的对象识别列使用 `entity`；日期、单位或短口径摘要统一传 `header-meta` 并保持同行单行，主内容前有紧凑控件时传 `leading-controls` 由组件统一对齐，不在页面拼私有表头；主表使用默认成长模式，只有抽屉、展开行、局部明细或后方仍有同级内容的长文档局部表格使用 `embedded`（共享组件默认应用 `LONG_DOCUMENT_TABLE_MAX_HEIGHT`）。纵向混合工作台的前置主业务表使用 `embedded + LEADING_WORKBENCH_TABLE_MAX_HEIGHT`，通过 slot 的 `minH + idealH` 声明受控收缩范围；末尾组件在 `pageRegistry` 声明为唯一 `growMain` 吃掉剩余高度。禁止复制高度公式、用页面 CSS 模拟成长关系或无限推远后续内容。
6. 若新增真实复用组件，补 DESIGN.md 清单、至少一个消费页面和测试；新增系统组件种类时同步 `COMPONENT_CATALOG`、schema 和预览；新增 Web 配置字段时同步字段定义、后端规则、pageRegistry 真实消费和配置中心验证。两类登记按职责维护，不机械捆绑。
7. 跑校验：`npm test`（validator + 契约测试）；DEV 期 `LayoutHost` 会 `assertLayout` 直接抛。
8. 构建按 AGENTS.md 的风险门槛执行；新增页面影响路由或懒加载，须运行 `npm run build`（含 vue-tsc）。普通局部模板、逻辑和样式改动只做定向验证。
9. 核对 DESIGN.md 的 `page-registry` 区块已有唯一同名行：脚手架会自动写入；仅未使用脚手架时按下方 §8 手工补一行，禁止重复登记。
10. 新页面如需要出现在侧栏或有受控 API / 按钮动作，同步菜单 seed、功能点 seed、后端守卫、`v-permission`、默认角色授权决策，并按 [system-rbac-tenant.md](../architecture/system-rbac-tenant.md) 验收。

### 1.1 页面使用或新增组件的登记决策

按以下顺序判断，不能依赖系统从 Vue 标签自动猜测组件 kind：

1. **先复用真实组件**：查 `DESIGN.md`“真实复用组件清单”、`frontend/src/components/**`、业务组件目录和同类页面。已有同类 UI 或行为时直接复用；相同模式第二次出现时按项目复用规则抽取组件、composable、util 或 schema。
2. **判断是否是独立系统组件实例**：已有系统组件种类若在页面中承担独立布局区、成长区、滚动区或可配置能力，必须在 `pageRegistry.ts` 登记对应 slot，并由 `<LayoutHost>` 的同名插槽承载真实组件。仅作为另一个真实组件内部实现细节、没有独立布局或配置语义的子组件，不登记假 slot。
   - 复合业务组件封装多个可配置系统组件实例或承接页面业务口径时，必须登记到 `layout/compositeComponentContracts.ts`，消费点通过 `registryPageKey`（或组件约定的等价必填标识）声明所属页面；该契约列出必需子 slot、字段和运行时绑定。影响结果或展示口径的业务偏好另登记到 `layout/pageBusinessPreferenceContracts.ts`，业务口径 prop 必须为必填且由中间组件原样透传；测试从所有直接或间接消费点反查抽屉控件、默认值与动态 prop 传递。不得只做 registry → 页面消费或 defaults → 抽屉的单向校验，否则整个 slot 或业务偏好从未声明时不会进入校验集合。
3. **消费已有受控字段**：登记 slot 后按 kind 自动继承字段。结构能力写 `slot.config`，安全候选写 `componentMeta`，明确例外写 `fieldApplicability` 与原因；页面必须读取并应用生效值，普通页面必须把 `componentAllowedLayers` 接入 `PageSettingsDrawer`。不得增加逐页面字段白名单。
4. **没有匹配的系统组件种类**：如果新能力只负责真实 UI 复用，不需要进入布局配置、系统组件页、页面设置抽屉或页面布局编辑器，不新增 kind；如果需要这些平台能力，则按本文 §3“新组件种类”维护目录、schema、预览、页面 slot 和测试。
5. **新开发真实 Vue 组件**：先判定页面私有业务片段、业务域复用组件或全局真实复用组件。形成稳定复用单元时维护 `DESIGN.md` 真实组件清单、至少一个实际消费点和组件/消费页测试；不要为了组件文件存在而机械新增系统 kind。
6. **新增可配置属性**：只有属性会被页面设置或页面布局真实消费时，才进入组件配置层；视觉预设不承载组件字段。按本文 §3“新组件配置字段”同步 `COMPONENT_FIELD_DEFS`、前端 schema、后端字段和值域/归属规则、安全渲染器、页面实际效果、系统组件覆盖状态和测试。纯组件内部 props 不进入该契约。

最终判定覆盖五种：复用且登记已有 slot、复用但仅作为内部实现、复用已有真实组件并新增系统 kind/配置字段、新增真实组件但不新增系统 kind、新增真实组件并完成系统 kind/配置字段闭环。任何一种都必须在开发计划的“复用与新增判断”和“维护清单”中写明。

## 2. 开发计划页面设计块（复制到计划里）

涉及新页面，或改造既有页面的布局、组件、设置抽屉、表格、弹窗/抽屉、页面设置入口时，开发计划必须包含本节；只改后端、接口、文案或不影响布局的业务逻辑时，在计划里写明“不涉及前端页面设计闭环”。

```md
## 前端页面设计闭环

### 页面定位
- 页面类型：
- 用户主流程：
- 是否新页面：
- 是否改造已有页面：

### 布局选型
- 选用原型：list / master-detail / dashboard / form / detail / workbench / wizard
- 选择理由：
- 是否需要新增布局原型：否 / 是，原因：

### Slot 与组件设计
| 区域 | slotId | 组件种类 | 是否 growMain | 滚动归属 | 是否可重排 | 说明 |
|---|---|---|---|---|---|---|
| action |  |  | 否 |  | 否 |  |
| main |  |  |  |  |  |  |
| overlay | settings | settings-drawer | 否 |  | 否 | 页面设置 |

### 响应式设计
规则入口：[DESIGN.md](../../DESIGN.md) §8.1–§8.3；本节记录本页面的实施与验收，不重新定义全站规则。

| 区域 / 组件 | 核心内容 | 辅助内容 | 尺寸来源与触发条件 | 换行 / 折叠 / 隐藏 / 抽屉 / 内滚 | 恢复入口与状态保留 |
|---|---|---|---|---|---|
| action / 筛选操作 |  |  |  |  |  |
| main / 主结果与分析 |  |  |  |  |  |
| footer / 分页 |  |  |  |  |  |
| overlay / 浮层 |  |  |  |  |  |

- 页面目标画像、实际断点、slot 最小尺寸与滚动所有者：
- 复用的响应式组件及消费点：
- 低高度时固定区和主内容的空间冲突如何解决：
- 宽屏富余分配给哪一主表 / 主图 / 概览：
- 无辅助内容或不适用区域写明理由；不得留空或只写“自适应”。
- 新增降级行为必须补最低层边界测试（触发、恢复和状态保留）；CSS 几何以实际浏览器复核为准，不用 jsdom 证明。
- 新页面默认临时复核 1100×620 / 1366×768 / 1440×900；涉及宽屏分栏增加1920×1080，新增局部断点检查临界两侧。采用不同界面比例时确认仍按布局尺寸触发。
- 实测须覆盖代表性长名称、多条件、大总数以及加载/空/错误态，检查核心操作可达、无整页溢出、展开/恢复不丢筛选与草稿；记录实际视口、界面比例、结果和未验证项。已有 E2E 仅满足准入时执行最小范围。
- 实施和实测完成后，将脚手架 `responsive-review-pending` 整段替换为简短的页面响应式说明与验证结论；手写页面遵循同一流程。

### 四态反馈设计
规则入口：[DESIGN.md](../../DESIGN.md) §4「四态反馈总则 / 空状态 / 加载态与异常态」。

| 状态 | 页面 / 组件处理 | 复用组件 / 样式 | 结论 |
|---|---|---|---|
| ready / 价值态 |  |  |  |
| loading / 加载态 |  |  |  |
| empty / 空态 |  |  |  |
| error / 异常态 |  |  |  |

- 自检结论：四态互斥、空态/错误态/重试入口按 DESIGN 处理；如有例外写明原因。

### 控件与操作规范
规则入口：[DESIGN.md](../../DESIGN.md) §4「按钮与输入」和 §7「Do's and Don'ts」。

- 主 / 次 / 危险操作选型：
- 按钮位置：按真实影响范围判断，不按动词机械归类；作用于整页或页面唯一主任务的主操作放 `.page-head-actions`、位于 `PageSettingsTrigger` 左侧并使用默认 32px 尺寸；当前页签、局部表单、选中对象或局部区块命令留在对应区域工具区（见 DESIGN.md §4「按钮与输入」）。
- 控件宽度：普通控件按内容容量选择 `.app-control-width-compact/short/medium/long/wide/fill` 中能完整承载常态内容的最小档位；多选 `AppFilterSelect` 必须按使用场景声明 `visibleTagCount=1..3`，由组件确定可见值、`+N` 与宽度档位，或使用 `displayMode=count` 只显示“已选 N”；不得另加宽度 class 或内联宽度；独立复合组件例外必须使用具名 class 并说明理由。
- 自定义条目顺序：统一复用 `AppReorderList`，使用稳定 key、组内拖动与键盘确认/取消；不新增上移/下移按钮，保存沿用业务流程。层级树沿用树组件拖动契约。
- 排序操作：统一复用 `AppSortControl`，并作为所属筛选/操作栏的最后一个控件；空间不足保持 DOM 顺序整体换行。
- 图标关闭/移除临时界面：使用 `AppCloseButton`；库内置关闭由全局适配，档位、状态、适用范围和业务边界统一引用 DESIGN §4，不私写配方。
- 纯图标操作：使用 `AppIconButton`；异步纯图标操作使用 `:loading`；具体尺寸、显式 tooltip 和 Unicode 禁令见 DESIGN。
- 提示与可访问名称：默认名称不生成气泡；必要说明、禁用原因和真实截断分别消费 `AppHoverInfo` / `AppActionHint` / `AppOverflowTooltipHost`，完整规则统一引用 DESIGN §4“提示、截断与可访问名称”。
- 专用原生按钮例外：
- 自检结论：

### 字体与间距规范
规则入口：[DESIGN.md](../../DESIGN.md) §3「Typography Rules / Spacing & Rhythm Rules」。

- 新增或复用的语义类 / token：
- 可导航页面标题是否通过 `useMenuPageTitle()` 消费当前菜单名称；阶段状态是否使用 `suffix` 拼接且未复制基础菜单标题：
- 页面密度：紧凑/标准/宽松是否由 `LayoutHost` 唯一提供，卡片、控件行、表单、表格和页面浮层是否共同消费 `--app-density-*`，且未改变字号或显式 small/large 层级：
- 页面布局工作台预览：结构与配置是否左右分工；无响应式列数差异时是否隐藏预览宽度切换；配置诊断是否默认折叠：
- 行内信息单元：非连续内容是否按 DESIGN §3.2 使用 ` · `、`.app-inline-info` 或 Teleport 浮层唯一 `popper-class`，且未用手工空格、`&nbsp;`、私有 `margin-left/right` 修补：
- 排版或间距特例：
- 页头容器对齐：`.page-head` / `.page-toolbar` 是否 `align-items: flex-start`（动作区钉标题顶）——禁止 `flex-end` / `center` 使抽屉触发钮跨页高度不一致；内嵌标题行 `.page-title-row` / `.title-row` 与右侧 `.page-head-actions` 不属此列。
- 自检结论：

### 主题底色规范
规则入口：[DESIGN.md](../../DESIGN.md) §2「Color Palette & Roles」。

- 是否调整主题底色 / 预设：
- 涉及 `themeSurfaces.ts` / `presets.ts`：
- 是否涉及品牌露出：涉及时必须直接复用 `BrandMark`，不得新增场景变体或消费侧 `--brand-*` 覆盖：
- 登录页 / 应用外壳同明暗模式、同预设下的品牌与基础表面是否一致：
- 新增预设是否只通过运行时 `primary` 驱动两处品牌色：
- 自检结论：

### 配置设计
| 类型 | 字段 | 层级 | 落点 | 说明 |
|---|---|---|---|---|
| 布局旋钮 | density | page/user | editable / 基础布局 | 信息密度 |
| 布局旋钮 | slots.&lt;slotId&gt;.visible | page/user | editable / 模块显示 | 完整模块显隐 |
| 组件设置 |  | page/user | COMPONENT_FIELD_DEFS |  |
| 业务偏好 |  | usePageSettings | 业务选项 |  |

分类先判断属性所有者，不按控件所在页面、字段名或当前存储表判断：

- 控制完整 slot / 模块是否存在、顺序、尺寸或密度：登记为布局旋钮；完整模块显隐统一使用 `slots.<slotId>.visible`，不得登记为组件内部 `config.visible`。
- 布局旋钮必须声明稳定的二级章节；基础密度归“基础布局”，完整模块显隐归“模块显示”，禁止在布局一级平铺不断增长。
- 能力由已登记组件实例拥有，更换或移除该组件后能力随之消失：登记为组件设置，并完成字段定义、后端规则、实例适用性、自动渲染和页面消费闭环；组件内部项显隐、日志跟随等展示/交互默认也适用此规则，不得因页面当前使用 `usePageSettings` 就留在业务段。
- 语义由页面业务流程拥有，更换承载 UI 后业务含义仍存在：登记为业务偏好，使用 `usePageSettings` 与 `#business`。
- 跨页面共享不改变属性归属：属于已登记组件实例的字段仍在组件设置中展示，并可通过 `userPersistence=global-preference` 接入专用全局偏好；不归属于当前组件实例的产品偏好才独立设置入口。两者都不得复制平行字段。
- “模式”“显示”“默认”等命名不能决定分类；同一字段不得同时出现在组件设置与业务选项。

### 动效验收
规则入口：[DESIGN.md](../../DESIGN.md) §4「动效与状态过渡」。

- 页面与标准异步区域是否复用 `WorkspaceRouteView` / `AppAsyncRegion` / `AppDataTable` 的共享显现能力，避免页面再次叠加动画：
- 折叠是否复用 `SettingsGroup` / `AppSummaryDisclosureCard`，保持编辑值和原挂载语义：
- 是否覆盖快速切换、已有内容刷新不重播、错误立即接管、减少动画偏好和缓存页现场恢复：
- 共享动效变更同步维护 `global.css`、`directives/reveal.ts`、消费组件和定向测试；不新增系统组件种类、slot 或可配置字段：

### 浮层设计
规则入口：[DESIGN.md](../../DESIGN.md) §4「弹窗与抽屉 / 设置抽屉」。

- 触发来源：页面 / 应用顶栏
- 浮层类型：dialog / 页面业务抽屉 / 页面设置抽屉 / 视口级全局抽屉
- 组件选型：`AppDialog` / `AppDetailDrawer` / 专用 `PageDrawer` / `PageSettingsDrawer` / 应用外壳 `el-drawer`
- 承载边界：当前 `LayoutHost` 内容区 / 整个视口
- 滚动归属：抽屉正文内滚，页面不跟随滚动
- 关闭策略：关闭按钮 / 遮罩 / Esc / 完成动作后关闭
- Teleport 样式入口：唯一全局类或 `:global`
- 文案容量：控件内直接可见的占位/后缀说明 ≤15 字，更完整的说明按内容结构使用 `HelpHint` / `HelpTip` 或移到字段辅助说明行；`HelpTipItem` 必须且只能传 `question="具体问题文本"` 或 `warning`，前者第一行显示具体问题文本并自动追加冒号，后者固定显示黄色“注意：”，第二行无论内容长短都使用由组件统一呈现为 `.` 开头的 `ul/li` 无序列表；`el-select` 占位只写「动作+对象」；验收按「弹窗宽 − 48px − label 宽」自检，不靠加宽弹窗绕过（见 DESIGN.md §3「排版规则」与 §4「组件资产分层」）

### 复用与新增判断
- 复用已有布局：
- 复用已有组件：
- 复用/新增真实组件：
- 是否为独立系统组件实例；若是，已有 kind 与 slotId：
- 若仅作为内部实现而不登记 slot，理由：
- 真实组件是否进入 DESIGN.md 清单：
- 是否关联系统组件种类：
- 是否新增组件种类：
- 是否新增组件配置字段：
- 是否新增页面专属业务态：

### 维护清单
- pageRegistry：
- COMPONENT_CATALOG：
- COMPONENT_FIELD_DEFS：
- componentSchemas：
- 后端 layout_config 字段规则：
- componentPreview：
- DESIGN.md 真实复用组件清单：
- DESIGN.md `page-registry` 区块：
- RBAC 接入结论：是否触发 [system-rbac-tenant.md](../architecture/system-rbac-tenant.md)“新页面接入菜单和权限”；涉及项：
- 测试：
- 按钮契约：命令按钮 / 图标按钮选型、每组主按钮数量、loading / disabled / focus 状态：
- 字体与间距契约：是否消费 typography/spacing token；行情摘要是否复用 `StockQuoteSummary`，保持垂直居中的主值列、两列最多四行的信息、自适应列宽和紧凑列间距；是否存在合理特例、是否影响低宽度文本溢出：

### 验收
- 定向运行 registry / validator / layout-contract / typography-spacing-system 与变更组件测试；只有发布门禁或明确需求才全量测试
- 构建按 AGENTS.md 门槛执行；新增路由 / 懒加载页面必须 build
- 视口验证：按 DESIGN.md §8 选择关键视口，默认覆盖 1100×620 / 1366×768 / 1440×900
- 检查无整页滚动、无视口高度硬编码、设置抽屉分段正常
- 检查按钮、图标、排版、间距、表格、抽屉和四态反馈均符合 DESIGN 对应章节；例外写明原因
```

如果缺少「响应式设计」或适用项未填写，计划视为不完整，不能直接进入开发。

如果计划声明“新增布局原型 / 组件种类 / 组件配置字段”，但没有维护清单，计划视为不完整，不能直接进入开发。

## 3. 组件 / 布局维护矩阵

| 变更类型 | 必须同步维护 | 必须验证 |
|---|---|---|
| 新页面 | 响应式设计与实测结论、完整组件触发清单、页面检查表、脚手架、`pageRegistry.ts`、`router/index.ts`、DESIGN 页面登记区块；四处 `pageKey` 必须一致；需要侧栏/权限时同步 RBAC 菜单与功能点 | `pageRegistry.spec.ts`、`layout-contract.spec.ts`、权限相关测试、build、关键视口 |
| 响应式降级变化 | DESIGN §8、`responsive-components.md` 逐文件触发清单、`responsive-pages.md` 受影响页面的当前验收行（日期、视口、已观察状态、结论与缺口；不追加过程记录）、真实消费组件、计划中的降级表；复用现有布局和组件，不新增平行配置 | `responsive-inventory.spec.ts`、边界/恢复/状态保留定向测试、尺寸断点契约、相关关键视口临时复核 |
| 新布局原型 | `archetypes.ts`、`schema.ts`、`validator.ts`、`LayoutHost.vue`、DESIGN 原型说明 | `validator.spec.ts`、布局契约测试 |
| 新组件种类 | `COMPONENT_CATALOG`、`componentSchemas.ts`、`componentPreview.ts`、系统组件页展示 | `componentPreview.spec.ts`、`pageRegistry.spec.ts` |
| 新组件配置字段 | `COMPONENT_FIELD_DEFS`、`componentSchemas.ts`、后端 `layout_config.py` 字段/值域/实例归属规则、`ComponentAutoSettings` 通用或专用安全渲染器、系统组件覆盖页、页面真实消费、DESIGN 字段治理入口 | `component-config-contract.spec.ts`、`componentConfig.spec.ts`、后端 layout 测试、保存/回显与策略收紧验证 |
| 页面消费已有字段 | 登记组件 slot 即自动继承该 kind 的适用字段；结构能力写 slot `config`，候选能力写 `componentMeta`，明确例外写 `fieldApplicability` 和原因；页面仍必须读取/应用值，并把 `useRemoteLayoutConfig.componentAllowedLayers` 传给统一抽屉。需要会话交互时走“配置默认值 → session state”，页面操作不反写默认值 | `pageRegistry.spec.ts` 自动继承、适用性、策略接线、正向消费与禁止页面直写契约，页面交互验证 |
| 新真实复用组件 | 组件文件、DESIGN 真实复用组件清单、至少一个消费页面；需要配置化时再同步系统组件种类/字段事实源 | 组件/消费页测试、build；涉及页面布局时做关键视口 |
| 业务域内复用组件 | 组件文件、DESIGN 真实复用组件清单、明确业务边界与消费页面；仅在需要布局配置时登记系统组件 kind | 组件/消费页测试、build、对应业务页面交互验收 |
| 按钮 / 图标操作体系 | `global.css` 控件 token、`AppIconButton` / `AppCloseButton`、DESIGN 按钮规范；确需新增专用原生按钮时同步契约允许项和理由 | `check:close-controls`、`button-system.spec.ts`、关闭/离开拦截组件测试、build、顶栏与操作区视觉验收 |
| 提示 / 截断机制 | DESIGN 提示契约、AppHoverInfo / useHoverIntent、AppIconButton / AppActionHint、AppOverflowTooltipHost；涉及原文时同步专用内容来源，不恢复原生 title 自动提示 | `check:tooltips`、提示/消费者定向测试、build、实际停留/移动/点击/键盘与主题验收 |
| 字体 / 间距体系 | `global.css` typography/spacing token、DESIGN 排版与节奏规范；新增语义层级时同步 token、文档和消费点 | 相关样式契约测试、build、关键页面视觉验收 |
| 滚动条与滚动容器 | DESIGN「滚动条显隐」、`AppScrollArea`、公共策略/Element Plus 适配层和 `scrollbar.css`；迁移时同步真实 viewport 引用、位置恢复、主从测高、成长布局及已有断言；内部实现组件不登记假 slot | `check:scrollbars`、显隐/清理/消费者定向测试、全局变更 build；内置浏览器核对悬停、键盘、滚动、拖出与低高度，禁止新增局部显隐 E2E |
| 全局界面比例 | `useDisplayScale`、`displayScaleProfiles`、`sizeProfileMatching`、`useLayoutViewport`、`displayScaleGeometry`、根画布与独立遮罩、视觉环境入口和 DESIGN；偏好复用 `useGlobalPreferenceSync`；自动缩放指数由系统外观配置 `ui.display.auto_scale_exponent`、后端校验、登录公开白名单和运行时缓存共同承接，默认 0.10；自定义比例按显示器可用 CSS 宽高保存个人尺寸档案，并与主从工作台复用尺寸匹配容差及距离工具；尺寸断点使用 `app-viewport`，第三方坐标补丁随安装校验 | composable/尺寸档案/坐标换算和真实组件交互单测、尺寸断点契约、build、分隔条/图表/滚动恢复与 Teleport 浮层视觉验收 |
| 共享交互状态 | `global.css` 的焦点、紧凑列表和语义链接配方、实际消费者与 DESIGN「按钮与输入」；同角色不得页面私配高亮亮度 | 键盘/选择/嵌套操作/禁用定向测试、build、明暗主题焦点及悬停临时复核 |
| 共享边框 | `themeSurfaces.ts::themeBorderVariables()`、`useLayoutPreset.ts`、实际消费者与 DESIGN §6 | `useLayoutPreset.spec.ts`、相关组件测试、build、明暗模式普通/禁用/选中态临时复核 |
| 品牌字标 / 主题强调色 | `BrandMark.vue`、`useLayoutPreset.ts`、登录页与应用外壳消费点、DESIGN 品牌规则；不得新增场景变体或消费侧颜色覆盖 | `BrandMark.spec.ts`、`useLayoutPreset.spec.ts`、build、登录页与工作台同模式同预设视觉验收 |
| 页面浮层 | `#overlays`、`AppDialog` / `AppDetailDrawer` / 专用 `PageDrawer` / `PageSettingsDrawer`、唯一浮层类；新增公共能力时同步 DESIGN 组件清单 | 统一组件测试、`layout-contract.spec.ts`、页面与顶部栏边界、正文内滚、关闭行为 |
| 纯业务偏好 | `usePageSettings` / 页面业务态，放入「业务选项」；不追加存储实现类徽标 | 业务行为验证、必要时 build |

新增系统组件 kind 必须维护组件能力事实源（`COMPONENT_CATALOG`、schema、预览），即使当前尚无页面消费者也可作为受控能力词汇存在。新增 Web 配置字段必须维护字段配置事实源（`COMPONENT_FIELD_DEFS`、后端规则）和安全渲染入口；所有同 kind slot 自动继承，页面只维护 slot `config`、`componentMeta` 和真实读取逻辑。结构型适用条件还必须同步后端实例归属校验，避免前端隐藏而保存接口仍放行。系统组件页逐 slot 展示自动继承、策略关闭和不适用原因。只有 kind 的语义能力摘要变化时才同步 `COMPONENT_CATALOG.configCapabilities`。`componentMeta.columns` 只提供设置候选，不自动生成业务列；每个候选 key 都必须由页面真实消费显隐状态。禁止新增页面不读取的 Web“假配置”；禁止绕过 `LayoutHost`、绕过 `pageRegistry` 或另建并行配置体系。
字段允许 `user` 层不代表一定写 `layout_user_config`：跨页面偏好必须在字段定义声明专用 `userPersistence`，前端统一路由到对应偏好存储，后端布局写接口按 `(component kind, field)` 拒绝误写；未声明时才按页面布局用户层处理。不得用 pageKey 或固定 slotId 判断存储目标。
新增真实复用组件不等于必须新增系统组件种类；只有当该组件需要被布局配置、系统组件页、页面设置抽屉或页面布局编辑器识别和调参时，才进入系统组件种类和组件配置字段闭环。

## 4. 原型决策

原型语义和决策顺序以 [DESIGN.md](../../DESIGN.md) §5.3 为准；执行时只需要在计划中填写“选择的原型 + 选择理由 + 是否需要新增原型”。可复制骨架见本文 §9。

## 5. PageLayout 骨架（列表页示例）

```ts
// pageRegistry.ts：页面结构与组件实例适用性事实源。
import type { PageLayout } from '@/layout'

const registryLayout: PageLayout = {
  pageKey: 'my-page',          // 与 usePageSettings 同源，便于偏好聚合
  archetype: 'list',
  hasActionRegion: true,
  density: 'standard',
  responsive: { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] },
  slots: [
    { id: 'filters', component: 'filter-bar', region: 'action', order: 1 },
    {
      id: 'table',
      component: 'data-table',
      region: 'main',
      growMain: true,
      minH: 360,
      order: 1,
      config: { pagination: true },
    },
  ],
  editable: [
    { path: 'density', label: '信息密度', type: 'enum', options: ['compact', 'standard', 'comfortable'] },
    { path: 'slots.table.minH', label: '主表最低高', type: 'int', min: 300, max: 760 },
  ],
}
```

```ts
// 页面运行时：必须从 registry 取布局并使用远端入口，不能直接 useLayoutConfig 绕过
// page/user 层与管理员字段策略。
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const pageLayout = getPageLayout('my-page')
const {
  effective,
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  layerValuesOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
} = useRemoteLayoutConfig(pageLayout)

const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  layerValuesOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
}
```

## 6. 模板骨架

### 6.1 浮层选型

| 触发位置与用途 | 使用组件 | 覆盖范围 | 规则 |
|---|---|---|---|
| 破坏性确认 | `ElMessageBox` | 当前交互上下文 | 明确动作与对象；不使用表单弹窗模拟确认 |
| 短表单、单组编辑、轻量查看 | `AppDialog` | 当前 `LayoutHost` 内容区 | 只用 `compact/narrow/medium/large/xlarge/max/workspace` 语义档位；普通表单不得使用 `workspace`；页面不得直接使用 `el-dialog` |
| 完整业务详情、长编辑、历史版本 | `AppDetailDrawer` | 当前 `LayoutHost` 内容区 | 基于 `PageDrawer`；统一标题、四态、正文和 footer；内容使用 `AppDetailSection` 与 `AppDetailFields/Field`，禁止私有详情网格和 `el-descriptions` |
| 实时日志、资产搜索、窄屏工作区回退 | `PageDrawer` | 当前 `LayoutHost` 内容区 | 仅专用交互模型可直接使用；宽度只用 `xs/sm/md/lg/xl/xxl/wide/full` 语义档位；页面不得传 px/% |
| 页面右上角设置入口 | `PageSettingsDrawer` | 当前 `LayoutHost` 内容区 | 内部复用 `PageDrawer`；固定承载布局、组件设置和业务选项；抽屉根部控制一级分组，嵌套父分组自动控制自己的直接子分组 |
| 应用顶栏的用户中心、外观等全局能力 | `PageDrawer boundary="app"` | 整个视口 | 与页面抽屉共用唯一外壳，只切换挂载边界；应用外壳也不得直接使用 `el-drawer` 或私传 px/% |

组件关系：

```text
PageSettingsDrawer
└── PageDrawer
    ├── el-drawer
    └── PageDrawerSurface

AppDetailDrawer
└── PageDrawer
    ├── el-drawer
    └── PageDrawerSurface

AppDialog
└── el-dialog
```

`PageDrawer` 是全站抽屉唯一入口，负责页面/应用挂载边界、遮罩、语义宽度和通用插槽，并在内部唯一消费 `PageDrawerSurface` 与 `el-drawer`；`PageDrawerSurface` 统一可见外边界、标题/副标题、关闭入口、正文滚动或填充布局和 footer，不允许业务代码直接消费。抽屉正文中同层功能分组统一使用 `SettingsGroup level=1` 的卡片边界，无需折叠时传 `collapsible=false`。消费方只保留业务内容样式，不得覆盖 `.el-drawer__header/body/footer`、复制视觉外壳或私建分组边框；`AppDetailDrawer` 只补充详情四态与内容结构，`PageSettingsDrawer` 负责页面设置结构，`AppDialog` 负责短内容。它们按内容职责选择，不按开发者偏好互换。

页面设置抽屉不开放“允许折叠”和“默认折叠段”配置。首次使用全部展开；用户逐组折叠或使用抽屉根部一键操作后，统一记忆当前顶层折叠态。每个存在直接子分组的 `SettingsGroup` 由共享折叠树自动显示本层一键操作；父级收起直接子节点即可隐藏其子树，重新展开时保留更深层原状态。页面不得覆写这套策略、手工枚举子节点或添加第二套批量折叠入口。

抽屉字体角色、标题档位与共享上下文统一遵守 [DESIGN.md §3](../../DESIGN.md#3-typography-rules)，本模板不另行维护字阶。所有可折叠节点使用箭头，并以最多两档缩进和纵向结构线表达父子关系。业务分区使用 `PageSettingSection`，它仅是 `SettingsGroup level=2` 的语义薄封装；设置事项统一使用 `PageSettingItem`，开关等短控件可选行内布局，页面不得复制 `.setting-item/.setting-label`。

### 6.2 页面骨架

```vue
<template>
  <LayoutHost :layout="effective">
    <template #action> <!-- 筛选/批量/工具栏，固定不滚；多个固定块用 <div class="lh-action"> 包一层 --> </template>
    <template #main>   <!-- 主表/主图/主列表 --> </template>
    <template #footer> <!-- 可选：固定底部批量条/购物车条（选择跨页累积）；纯渲染槽，不入 schema --> </template>
    <template #overlays>
      <AppDialog v-model="editOpen" title="编辑名称" size="medium">
        <!-- 短表单或轻量查看 -->
      </AppDialog>

      <AppDetailDrawer v-model="detailOpen" title="业务详情" size="xl">
        <!-- 页面业务详情；长内容在抽屉正文内滚 -->
      </AppDetailDrawer>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="页面名称"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetPageSettings(); resetLayout()"
      >
        <template #business>
          <!-- 页面业务偏好 -->
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>
```

> 多组件主区（mixed/columns）按 `slot.id` 具名放置：`<template #<slotId>>…</template>`。可参考已登记且通过契约测试的同原型页面。
> 业务代码不得直接使用 `el-dialog`、`el-descriptions` 或 `el-drawer`。Teleport 生成的内部 DOM 样式使用唯一全局类或 `:global`。

## 7. 验收红线（机制性强制，违反则对应 `npm test` / `npm run test:design` 门禁失败）

- 后端按项目约束以明确的本地环境和 `AI_STOCKS_E2E_WRITE=1` 健康启动、并校准调试账号后，完整设计验收统一执行 `AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design`（`dev` 可按实际环境替换为 `test` 或 `local`）；命令会先校验调用方安全环境，再请求 `E2E_API_URL`（默认 `http://127.0.0.1:8000/api`）下的 `/health/e2e`，只有响应 `code: 0` 且返回合法 PG 指纹时才继续 Vitest、生产构建和串行 Playwright 响应式回归。后端未启动或未以 E2E 写模式启动时必须在前置检查中 fail-fast，并给出带相同环境变量的重启指引。串行用于避免多个视口并发复用调试账号造成鉴权级联失败，日常快速门禁仍可单独执行 `npm test`。
- 不得新增视口硬编码高度（`height:/min-height: …vh` 或 `calc(…vh)`）——`layout-contract.spec.ts` 扫描 `src/views` 拦截。`max-height: …vh` 仅限弹层安全上限。
- 非公开 View 路由、`pageRegistry` 和 DESIGN marker 必须以 `pageKey` 双向一致；registry 页面必须真实导入和渲染 `LayoutHost`，并通过 `getPageLayout` 消费布局——`pageRegistry.spec.ts` 使用 TypeScript AST 与页面源码共同拦截。
- 页面不得绕过 `LayoutHost` 手写 `.v-page/.v-grow/.v-scroll`——`layout-contract.spec.ts` 拦截。
- 页面不得保留脚手架 `data-scaffold-placeholder`——必须接入真实组件和四态后再交付。
- 页面源码不得直接使用 `<el-dialog>`、`<el-descriptions>` 或 `<el-drawer>`；短内容、普通详情、专用抽屉和页面设置分别使用 `AppDialog`、`AppDetailDrawer`、`PageDrawer`、`PageSettingsDrawer`——`layout-contract.spec.ts` 扫描拦截。
- 不得使用未登记组件种类——`validateLayout` 拦截。
- 不得把页面业务结构放进用户级配置；不得把不可重排的大表放进多列重排——`validateLayout` 拦截。
- 列表交互：分页/排序默认走服务端、筛选变更自动触发（不设“查询”按钮）、多选跨页累积；“重置筛选”与“刷新”的准入、稳定命名、操作状态机、锁定范围、过期响应保护和触发边界统一遵守 [DESIGN.md](../../DESIGN.md)「按钮与输入 › 查询、重置与刷新」，页面不得私有改名或用 disabled 冒充 loading。**例外判据**：当数据具备明确规模上限且一次性返回完整集合时，可采用客户端排序或分页；分页场景必须先全量排序再截取当前页，并在设计中注明为有意差异。
- 真实组件：已有真实复用组件能覆盖的控件行为，不得继续在页面内复制手写；`data-table` / `wide-table`、`settings-drawer` 等逻辑种类由 `pageRegistry.spec.ts` 校验真实导入和渲染，`config-panel` 校验页面级入口 `ConfigGroupForm`，再由该组件复用 `ConfigPanelSection`；组合型 `toolbar` / `section` / `tabs` 不要求虚构同名空壳组件。
- 表格容器：纯表格的 `el-card` 使用共享 `app-table-card` 类，内容体贴边；标题/工具栏放 header 插槽，状态反馈与分页保留共享内距。普通混合内容卡片保留密度内距，已有 `AppWorkspacePane` 不重复包卡片。
- 表格列呈现：页面不得直接使用原生 `<table>`、`el-table`、`el-table-column`，不得向 `AppTableColumn` 传 `width/min-width/align/header-align`，也不得通过私有表格 CSS 覆盖对齐；宽度、表头与值对齐、等宽数字统一由语义角色推导。文本、代码、名称、日期左对齐，排名、结构、状态、操作居中，普通数值右对齐；横向比较矩阵数值声明 `comparison-number` 居中，不允许手写例外。单元格使用多选 `AppFilterSelect` 时，标签模式下列的 `filterSelectVisibleTagCount` 必须与选择器的 `visibleTagCount` 一致；数量摘要模式下列与选择器分别声明 `filterSelectDisplayMode=count`、`displayMode=count`，使列宽完整承载“已选 N”；总宽超出后由表体横向滚动，不裁切交互控件。`label="操作"` 必须按动作密度显式声明 `role="action-compact"`（单动作或仅“更多”入口，默认下限 96px）或 `role="action"`（两个及以上候选动作，默认下限 144px）；两档默认统一居中表头与单元格、不参与表格富余空间分配，但由 `AppRowActions` 按当前已渲染行的最低可用组合向上扩展。单动作最低完整显示该动作；多动作最低保留两个入口，可由两个直接动作或“首个直接动作 + 更多”构成，“更多”计作一个入口；除调用方明确把全部动作收进更多外，禁止退化为仅“更多”；数据事实不得复用“操作”标签，应使用“操作笔数”等准确名称和真实字段语义。
- 高度与滚动：`list` 必须唯一 `growMain`；`LayoutHost` 统一应用组件有效 `minH`。剩余高度达到 `minH` 时由组件内部滚动，低于 `minH` 时才由主内容区滚动兜底。页面不得用 `fill`、私有视口高度或外层滚动覆盖该决策。
- 四态反馈：按 [DESIGN.md](../../DESIGN.md)「四态反馈总则」的运行时入口矩阵选择 `AppDataTable`、`AppAsyncRegion`、`AppStateBlock` 或 `AppStatusNotice`，不得在页面重复实现标准分流；在本模板的四态反馈设计表中记录区域、内容归属、异常恢复和特殊生命周期例外，并由消费页测试或关键视口 E2E 验证。

## 8. 页面登记块（填好贴进 DESIGN.md `page-registry` 表格）

```text
| pageKey | 页面 | 原型 | 可编辑旋钮 | 组件清单 |
| `<page-key>` | `<PageView>`（中文名） | `<archetype>` | `density` | action:`toolbar` / main:`section` |
```

## 9. 7 个原型可复制骨架

> 推荐先用脚手架生成，再按以下原型补业务内容：
>
> ```bash
> npm run scaffold-page -- --pageKey demo-list --label "示例列表" --archetype list --route /demo/list --view DemoListView
> ```

### 9.1 list

```bash
npm run scaffold-page -- --pageKey my-list --label "列表页" --archetype list --route /my-list --view MyListView
```

结构：`action:filter-bar` + `main:data-table(growMain)`。适合筛选、批量操作和一张主表；主表内部滚动，不做多列重排。

### 9.2 master-detail

```bash
npm run scaffold-page -- --pageKey my-master-detail --label "主从页" --archetype master-detail --route /my-master-detail --view MyMasterDetailView
```

结构：`action:filter-bar` + `main:data-table` + `main:detail`。适合左侧列表、右侧详情；两栏各自承载滚动，不把详情塞进弹窗替代主流程。行情列表+分析图表必须复用 `MarketMasterDetailWorkspace`；高度按滚动所有权选择模式：独占页面主内容区时使用默认 `fill`；作为可滚动长文档中的末段工作台时使用 `adaptive`，页面内容尚未溢出时填满当前滚动容器的剩余空间，上方内容增长到空间不足后守住常规 `480px`、紧凑 `400px` 的可读下限并由外层页面滚动，列表和图表各自内部滚动，禁止结果行数撑高整页。`RankedStockWorkbench` 统一代表长文档中的排名结果区并默认使用 `adaptive`，筛选、试算等页面不得重复传递高度模式；只有工作台独占页面主区时才显式覆盖为 `fill`。运行时组件和行情页面布局登记共用尺寸常量，页面不得另写私有工作台高度。列表按工作台容器的 `masterRatio` 连续计算，系统默认 `45%`、允许配置 `30%–70%`，仅在列表至少 `360px` 或详情至少 `240px` 的真实内容安全边界触发时偏离配置比例，不设置列表固定像素上限。工作区布局宽度不超过 `720px` 时统一退化为列表单区，选择对象后由工作台的全屏抽屉承载详情或分析，页面不得私建紧凑抽屉。主区拖动只修改会话比例；“使用页面当前比例”同时更新默认占比并保存当前工作区宽度与比例；设置抽屉直接编辑占比时，若当前工作区已上报有效尺寸，必须同步更新该尺寸档案，避免旧档案覆盖新值。抽屉数值优先回显当前工作区由默认值或尺寸档案形成、并经过内容安全边界调整后的配置基线；手动拖动只更新按钮待采用的会话样本，不得提前覆盖抽屉数值，点击采用后才更新回显。没有工作区样本时显示默认值。同页同用户可保存多项，当前宽度在档案 `±15%` 范围内时使用最近项，`5%` 内重复保存更新原项，无匹配时回退默认比例；双击分隔条恢复当前匹配或默认比例。设置抽屉只保留占比和紧随其后的共享主色采用按钮，不直接展示档案与匹配算法。历史 `masterWidth` 固定像素值只允许兼容读取，不再作为页面分栏依据。

股票多图的纵向面板比例同样遵循尺寸档案原则。位于主从分栏时，档案以外层工作区的 CSS 布局宽高作为稳定视觉环境尺寸；图表右栏自身宽高只用于重绘和最低比例，左右分隔条改变右栏宽度时不得切换纵向比例档案。无外层尺寸上下文的独立图表才使用自身 CSS 宽高，任何场景都不使用物理屏幕尺寸。档案随 `chart.stockChart` 按 `pageKey + slotId + 图表组合` 隔离；拖动仅更新会话值，“使用页面当前比例”保存拖动结果，直接编辑高度比例则同步更新组合默认值与当前视觉环境尺寸档案。工作区存在时比例控件回显默认值或匹配档案经过最低高度约束后的配置基线；手动拖动不得提前覆盖控件，点击采用后才更新回显。尚未提供有效宽高时回退默认比例并禁用采用入口，禁止假保存。宽高均在 `±15%` 内时使用综合距离最近项，`5%` 内保存覆盖原项，无匹配时回退组合默认比例。旧的右栏自身尺寸档案不得按新基准误匹配，仅保留默认高度比例，待用户显式采用当前比例后生成新档案。页面只转发共享工作区尺寸事件，不得复制尺寸监听、距离计算或档案持久化逻辑。

### 9.3 dashboard

```bash
npm run scaffold-page -- --pageKey my-dashboard --label "仪表盘" --archetype dashboard --route /my-dashboard --view MyDashboardView
```

结构：`main:kpi-grid` + `main:chart`。适合 KPI、图表和概览面板；只对平级块做安全重排，单个大表仍走内滚。

### 9.4 form

```bash
npm run scaffold-page -- --pageKey my-form --label "表单页" --archetype form --route /my-form --view MyFormView
```

结构：`main:form`。适合创建/编辑页；字段区内滚，提交按钮应固定在表单语义尾部或 footer，不写视口高度。保存型表单在回填完成或打开时记录实际提交负载基线，仅有实质变更时启用保存，提交函数同步拒绝无变更请求，成功后更新基线、失败时保留编辑现场。

### 9.5 detail

```bash
npm run scaffold-page -- --pageKey my-detail --label "详情页" --archetype detail --route /my-detail --view MyDetailView
```

结构：`main:detail`。适合摘要、分区详情和审阅页；长内容由详情区内滚，关键操作放 action 或详情吸顶区。

### 9.6 workbench

```bash
npm run scaffold-page -- --pageKey my-workbench --label "工作台" --archetype workbench --route /my-workbench --view MyWorkbenchView
```

结构：`action:toolbar` + `main:section`。适合参数区固定、结果区混合成长的分析工作台；固定分析块和成长表放在主 section 内组织。

### 9.7 wizard

```bash
npm run scaffold-page -- --pageKey my-wizard --label "向导页" --archetype wizard --route /my-wizard --view MyWizardView
```

结构：`main:steps`。适合多步骤流程；步骤条稳定展示，当前步骤内容内滚，导航按钮保持在流程底部。

### 列表高级搜索接入

每个独立列表有三个及以上可收纳条件时使用 `AppAdvancedSearch`。候选、中文名与两个默认常显项登记在 `frontend/src/layout/searchGroups.ts`；注册表把该组映射到 `filter-bar` slot 和 `commonFields` 配置，不另写页面私有偏好。已有 slot 复用，新嵌套列表只补登记可寻址 slot。

消费页向 `LayoutHost` 传递 `:component-value-of="componentValueOf"`，组件通过宿主读取已合并的组件配置（结构布局 `effective` 不包含组件覆盖值），按同名字段插槽承载原有控件。`states` 提供各字段当前值、选项中文映射、实际限制判定、清除回调、业务适用性与错误；`context` 承载固定工作上下文，`commands` 承载重置和末位排序。条件变化仍由页面原有领域事件负责，不能因收展或替换常显项额外查询。全选、false 表示排除某类内容等特殊语义必须显式声明 `active` 和 `summary`，不能仅凭值是否为空判断。

页面设置抽屉沿用 `ComponentAutoSettings`，保存回调接入 `saveRemoteUserConfig`；运行时权限候选由公共组件共享给设置消费，禁止页面复制配置编辑器。临时展开状态不保存为长期偏好。测试覆盖阈值、动态权限回退、控件实例保留、隐藏限制摘要、字段清除、错误聚焦与保存失败重试；维护入口见 DESIGN「列表高级搜索」。

### 键盘接入维护检查

键盘能力及适用范围以 [DESIGN.md](../../DESIGN.md)「键盘能力与适用边界」为唯一契约。普通按钮/链接复用原生语义；自定义命令接入 `v-keyboard-activate`，单行输入确认使用 `submitOnEnter`，范围调整使用 `keyboardRangeValue`，页面快捷键使用 `usePageShortcuts`。不得复制页面级 window keydown 监听。

维护矩阵：改变共享行为时同步入口与消费点测试；增加快捷键时同步可见说明、可访问快捷键属性、权限和忙态守卫；改变焦点路径时复核弹层、关闭恢复及 KeepAlive。上述机制不增加布局 kind、slot 或用户持久化配置，既有页面布局与响应式画像保持原边界。

### 按钮状态维护

按 [DESIGN 按钮与输入](../../DESIGN.md#按钮与输入)选择组件与角色，不在模板重复定义颜色配方。新增角色须同步其状态矩阵、共享实现及代表性消费验证；仅状态调整不新增布局 kind 或持久化字段。验收复核明暗主题、键盘焦点、加载/禁用与代表性浮层消费点。
