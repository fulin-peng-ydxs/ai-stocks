# 新页面开发模板与选型清单（AI 固定流程）

## 文档边界

本文维护新建和改造页面的执行流程、计划填写项、维护矩阵与可复制骨架；设计规则由 [DESIGN.md](../../DESIGN.md) 定义，服务保护及构建准入由 [AGENTS.md](../../AGENTS.md) 定义，E2E 生命周期由 [执行指南](../e2e-automation/guide.md) 定义。这里只引用规则并安排实施与验证，不另立视觉、数据口径或夹具操作规范。

共享入口或开发流程变化时同步本文示例与维护矩阵；具体功能的设计决策、计划和验收结果写入对应功能目录，不把一次性实现固化为通用模板。

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
5. 模板用 `<LayoutHost :layout="effective" :component-value-of="componentValueOf">` + 具名插槽（`slot.id`）承载业务组件，浮层放 `#overlays`。表格复用 `AppDataTable + AppTableColumn`，按 [DESIGN「表格与列表」](../../DESIGN.md#表格与列表) 声明列语义和成长/嵌入模式；浮层按本文 §6.1 选型。不得在页面复制共享布局或表头、列宽及状态配方。
6. 若新增真实复用组件，补 DESIGN.md 清单、至少一个消费页面和测试；新增系统组件种类时同步 `COMPONENT_CATALOG`、schema 和预览；新增 Web 配置字段时同步字段定义、后端规则、pageRegistry 真实消费和配置中心验证。两类登记按职责维护，不机械捆绑。
7. 跑校验：`npm run check`（静态规范、validator / 布局契约测试及类型检查，无后端依赖）；组件行为另按风险运行定向 `npm test -- <文件>`。DEV 期 `LayoutHost` 会 `assertLayout` 直接抛。
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
规则入口：[DESIGN.md](../../DESIGN.md) §4「按钮与输入」和 §7「使用规范与禁用事项」。

- 主 / 次 / 危险操作选型，以及轻量导航 link / 本地命令 text 的真实行为与声明：
- 按钮位置：按真实影响范围判断，不按动词机械归类；作用于整页或页面唯一主任务的主操作放 `.page-head-actions`、位于 `PageSettingsTrigger` 左侧并使用默认 32px 尺寸；当前页签、局部表单、选中对象或局部区块命令留在对应区域工具区；区域内再按内容和相邻结构选择对齐，筛选与对象选择从左起排，独立纯命令组优先右对齐，具体判断及共享入口见 DESIGN.md §4「按钮与输入」。
- 下拉选型：普通下拉使用 `AppSelect`，筛选/紧凑多选使用 `AppFilterSelect`，已有领域选择器继续复用；默认搜索、短枚举关闭及远程搜索边界见 DESIGN「按钮与输入」。禁止页面直接使用原生 `el-select` 或 HTML `<select>`。面板默认按内容扩展到共享上限后换行，等宽例外按 DESIGN「按钮与输入」登记，消费页无需重复配置定位。
- 控件宽度：`AppSelect` 的 `width` 使用 `compact / short / medium / long / wide / fill` 档位（如 `width="short"`）；普通控件按内容容量选择 `.app-control-width-compact/short/medium/long/wide/fill` 中能完整承载常态内容的最小档位；多选 `AppFilterSelect` 必须按使用场景声明 `visibleTagCount=1..3`，由组件确定可见值、`+N` 与宽度档位，或使用 `displayMode=count` 只显示“已选 N”；不得另加宽度 class 或内联宽度；独立复合组件例外必须使用具名 class 并说明理由。
- 自定义条目顺序：按 [DESIGN.md「自定义顺序」](../../DESIGN.md#自定义顺序) 选择共享组件，核对允许调整的范围、稳定标识及业务保存流程。
- 排序操作：统一复用 `AppSortControl`，并作为所属筛选/操作栏的最后一个控件；空间不足保持 DOM 顺序整体换行。
- 图标关闭/移除临时界面：使用 `AppCloseButton`；库内置关闭由全局适配，档位、状态、适用范围和业务边界统一引用 DESIGN §4，不私写配方。
- 纯图标操作：使用 `AppIconButton`；异步纯图标操作使用 `:loading`；具体尺寸、默认 tooltip／显式豁免和 Unicode 禁令见 DESIGN。
- 控件样式差异按 DESIGN §4「样式归属」通过尺寸属性或共享变体表达；核对 `design-contracts.json` 的受保护属性、精确持有者及绑定转发，覆盖输入/选择/日期、选择项、表单、表格/分页、卡片/页签和弹窗/抽屉。禁止以 scoped、deep/global、合法 token 或库组件样式属性绕过；需要文本域填充、技术文本、多行候选或紧凑/成长卡片时消费 DESIGN 登记的共享变体，不复制内部选择器。
- 新增基础控件核对 DESIGN §4 的样式接入登记；重置、脚本写入、专项归属和根包装继承统一由 `check:contracts` 检查，例外只能登记到已有 `design-contracts.json`，不得另设页面放行列表。
- 提示与可访问名称：图标默认用途提示与明确豁免、必要说明、禁用原因和真实截断统一引用 DESIGN §4“提示、截断与可访问名称”；分别复用 `AppIconButton` / `AppHoverInfo` / `AppActionHint` / `AppOverflowTooltipHost`，其他控件不因名称自动生成气泡。
- 专用原生按钮例外：
- 自检结论：

- 分段选择在抽屉内由共享外壳统一启用 `fill`，抽屉外默认按内容排宽、需铺满字段时使用 `PageSegmented fill`，禁止私有宽高覆盖。编辑表单统一使用 `AppForm` 默认跟随页面密度，与相邻常规工具栏保持同档，动态字段继承尺寸；紧凑行内编辑等例外按角色区分，具体范围与例外见 [DESIGN.md「弹窗与抽屉」](../../DESIGN.md#弹窗与抽屉)，不得逐页指定默认高度；行外常规操作也由所属操作组提供尺寸，不逐控件定档。
- 表单常显辅助说明统一使用 `AppFormHelp`；单行/多行标记、正文续行、控件列对齐及语义边界见 [DESIGN.md「表单辅助说明」](../../DESIGN.md#表单辅助说明)，不得恢复页面私有说明类或手写星号。

### 字体与间距规范
规则入口：[DESIGN.md](../../DESIGN.md) §3「字体与排版规范 / 间距与节奏规范」。

- 新增或复用的语义类 / token：
- 可导航页面标题是否通过 `useMenuPageTitle()` 消费当前菜单名称；阶段状态是否使用 `suffix` 拼接且未复制基础菜单标题：
- 页面密度：视觉环境的一键统一是否只批量更新用户层 density、仍允许后续逐页修改；紧凑/标准/宽松是否复用共享变量矩阵（页面由 `LayoutHost` 提供，视觉环境抽屉固定使用宽松宿主），卡片、控件行、表单、表格和页面浮层是否共同消费 `--app-density-*`，且未改变字号或显式 small/large 层级：
- 页面布局工作台预览：结构与配置是否左右分工；无响应式列数差异时是否隐藏预览宽度切换；配置诊断是否默认折叠：
- 行内信息单元：非连续内容是否按 DESIGN §3.2 使用 ` · `、`.app-inline-info` 或 Teleport 浮层唯一 `popper-class`，且未用手工空格、`&nbsp;`、私有 `margin-left/right` 修补：
- 排版或间距特例：
- 页头容器对齐：`.page-head` / `.page-toolbar` 是否 `align-items: flex-start`（动作区钉标题顶）——禁止 `flex-end` / `center` 使抽屉触发钮跨页高度不一致；内嵌标题行 `.page-title-row` / `.title-row` 与右侧 `.page-head-actions` 不属此列。
- 自检结论：

### 主题底色规范
规则入口：[DESIGN.md](../../DESIGN.md) §2「色彩体系与语义角色」。

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
- 组件选型：`AppDialog` / `AppDetailDrawer` / 专用 `PageDrawer` / `PageSettingsDrawer` / 应用级 `PageDrawer boundary="app"`
- 承载边界：当前 `LayoutHost` 内容区 / 整个视口
- 滚动归属：抽屉正文内滚，页面不跟随滚动
- 关闭策略：关闭按钮 / 遮罩 / Esc / 完成动作后关闭
- Teleport 样式入口：唯一全局类或 `:global`
- 文案容量、占位与宽度自检统一引用 [DESIGN 弹窗与抽屉](../../DESIGN.md#弹窗与抽屉)中的文案容量规则，常显字段说明引用[表单辅助说明](../../DESIGN.md#表单辅助说明)，图标选型及帮助正文格式引用[提示契约](../../DESIGN.md#提示截断与可访问名称)。

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
- 字体与间距契约：是否消费 typography/spacing token；行情摘要是否按 DESIGN 的行情摘要契约复用 `StockQuoteSummary`，匹配当前场景的容量和列距；是否存在合理特例、是否影响低宽度文本溢出：

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

下表的“必须验证”按变更实际影响选择；`build` 仅在 AGENTS.md 的构建准入条件成立时执行，不因普通组件文件或局部模板变化默认构建。命令含义与范围见本文 §7。

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
| 按钮 / 图标操作体系 | `buttonStates.css` 命令状态、`global.css` 链接/选择状态、`AppIconButton` / `AppCloseButton`、真实消费者与 DESIGN 按钮规范；专用原生按钮按文件和角色登记，不按页面前缀放行 | `check:close-controls`、`button-system.spec.ts`、`interaction-color-consumers.spec.ts`、受影响消费者测试、build；内置浏览器复核实际颜色、焦点、选中与禁用/加载，不能以 class 存在代替呈现 |
| 操作行共同尺寸 | `controlRowSizing.ts`、`AppControlRow` / `AppTabToolbar` / `AppAdvancedSearch`、公共控件适配、表单/浮层/表格边界及 DESIGN 操作行规则；页面只声明行尺寸，附属角色例外精确登记 | `check:control-rows`、`AppControlRow.spec.ts`、`control-row-consumers.spec.ts`、`control-presentation.spec.ts`、相关控件与消费者定向测试；全局样式/构建门禁变化时 build；真实混合控件组合、三档密度、关键视口、动态尺寸、输入保留及独立浮层实际外框验证 |
| 分段选择状态 | `PageSegmented`、`useLayoutPreset.ts` 分段变量及 `global.css` 兜底、DESIGN 分段矩阵；复用共享控件，不逐页覆盖 | `PageSegmented.spec.ts`、`useLayoutPreset.spec.ts`、全局资源变化时 build；分别检查 contained neutral/primary 与 tabs、明暗底板/悬浮/按下差异及选中/禁用/焦点 |
| 提示 / 截断机制 | DESIGN 提示契约、AppHoverInfo / useHoverIntent、AppIconButton / AppActionHint、AppOverflowTooltipHost；涉及原文时同步专用内容来源，不恢复原生 title 自动提示 | `check:tooltips`、提示/消费者定向测试、build、实际停留/移动/点击/键盘与主题验收 |
| 字体 / 间距体系 | `global.css` typography/spacing token、DESIGN 排版与节奏规范；新增语义层级时同步 token、文档和消费点 | 相关样式契约测试、build、关键页面视觉验收 |
| 滚动条与滚动容器 | DESIGN「滚动条显隐」、`AppScrollArea`、公共策略/Element Plus 适配层和 `scrollbar.css`；迁移时同步真实 viewport 引用、位置恢复、主从测高、成长布局及已有断言；内部实现组件不登记假 slot | `check:scrollbars`、显隐/清理/消费者定向测试、全局变更 build；内置浏览器核对悬停、键盘、滚动、拖出与低高度，禁止新增局部显隐 E2E |
| 基础密度与一键统一 | `LayoutHost`、`useRemoteLayoutConfig`、`pageDensitySync`、视觉环境的 `PageDensitySyncSettings`、registry 和 `layout/user-density`；复用既有个人布局权限与存储，仅补丁 density，不建立全局覆盖层；平台管理页不新增个人设置入口 | 配置保留、事务回滚、账号/租户隔离、缓存/在途请求/后续逐页编辑定向测试；代表性页面、三档密度和浮层浏览器复核 |
| 全局界面比例 | `useDisplayScale`、`displayScaleProfiles`、`sizeProfileMatching`、`useLayoutViewport`、`displayScaleGeometry`、根画布与独立遮罩、视觉环境入口和 DESIGN；偏好复用 `useGlobalPreferenceSync`；自动缩放指数由系统外观配置 `ui.display.auto_scale_exponent`、后端校验、登录公开白名单和运行时缓存共同承接，默认 0.10；自定义比例按显示器可用 CSS 宽高保存个人尺寸档案，并与主从工作台复用尺寸匹配容差及距离工具；尺寸断点使用 `app-viewport`，第三方坐标补丁随安装校验 | composable/尺寸档案/坐标换算和真实组件交互单测、尺寸断点契约、build、分隔条/图表/滚动恢复与 Teleport 浮层视觉验收 |
| 共享交互状态 | `global.css` 配方、`scripts/design-contracts.json` 已登记的状态/变量和受保护角色、消费者与 DESIGN 对应契约；差异经共享扩展点表达 | `check:contracts`、键盘/选择/嵌套操作/禁用定向测试、明暗主题焦点及悬停临时复核 |
| 规范规则 / 检查器变更或漏检修复 | 先判断既有检查器能否覆盖；必要时扩展对应机器契约和共享检查器、合法及违规样例，并接入 `check:design` / `check` 或适用的领域门禁；文档只维护该规则的权威定义 | 定向正反例、真实消费者扫描、统一入口及按风险选定的行为/页面验证；既有漏检用最小夹具复现并确认修复后被拒绝 |
| 共享边框 | `themeSurfaces.ts::themeBorderVariables()`、`useLayoutPreset.ts`、实际消费者与 DESIGN §6；股票画布的嵌入外沿统一由共享 `embedded` 模式承接 | `useLayoutPreset.spec.ts`、`borderContract.spec.ts` 的消费者扫描与删除声明变异、`StockChartWorkspace.spec.ts` 的真实宿主/异步层组合、相关组件测试、build、受影响页面明暗模式临时复核 |
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
import { ref } from 'vue'
import { getPageLayout } from '@/layout'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'

const pageKey = 'my-page'
const settingsOpen = ref(false)
const editOpen = ref(false)
const detailOpen = ref(false)
const pageLayout = getPageLayout(pageKey)
const {
  effective,
  resetAll: resetLayout,
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

按任务填写以下选型结果；语义尺寸、关闭/焦点、滚动及分组行为统一遵守 [DESIGN「弹窗与抽屉」](../../DESIGN.md#弹窗与抽屉) 与[「设置抽屉」](../../DESIGN.md#设置抽屉)，不在模板复制组件内部结构或状态配方。

| 触发位置与用途 | 共享入口 | 计划中核对 |
|---|---|---|
| 破坏性确认 | `ElMessageBox` | 动作、对象、取消与失败恢复 |
| 短表单、单组编辑、轻量查看 | `AppDialog` | 内容容量、语义档位、提交状态 |
| 完整业务详情、长编辑、历史版本 | `AppDetailDrawer` | 四态、正文分区、关闭与草稿保护 |
| 实时日志、资产搜索、窄屏工作区回退 | 专用 `PageDrawer` | 专用交互模型及所属页面边界 |
| 页面设置 | `PageSettingsDrawer` | 自动配置/业务偏好归属、来源与重置 |
| 用户中心、视觉环境等应用级入口 | `PageDrawer boundary="app"` | 应用级覆盖边界与返回焦点 |

页面和应用外壳均不得直接使用 `el-drawer`，也不得直接消费 `PageDrawerSurface`。共享组件关系见 DESIGN 的真实组件清单；具体 props、插槽和实现以组件源码为准。

### 6.2 页面骨架

```vue
<template>
  <LayoutHost :layout="effective" :component-value-of="componentValueOf">
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
        @reset="resetLayout"
      />
    </template>
  </LayoutHost>
</template>
```

> 使用 `usePageSettings` 业务偏好的页面，需把其 reset 与 `resetLayout` 组合为同一重置函数并绑定 `@reset`；上述最小骨架未声明业务偏好；仅在有实际业务项时添加 `#business` 插槽。组件导入和业务字段由实际页面补齐；完整可运行的初始文件优先由脚手架生成。
> 多组件主区（mixed/columns）按 `slot.id` 具名放置：`<template #<slotId>>…</template>`。可参考已登记且通过契约测试的同原型页面。
> 业务代码不得直接使用 `el-dialog`、`el-descriptions` 或 `el-drawer`。Teleport 生成的内部 DOM 样式使用唯一全局类或 `:global`。

## 7. 验证入口与交付检查

先按全局测试完成条件检查本次变更的覆盖缺口；项目命令按下表选取。已有入口不足时扩展共享检查器和契约，不另建页面私有检查流程。

| 入口（在 `frontend/` 下执行） | 覆盖与使用时机 |
|---|---|
| `npm run check` | 日常统一快检：静态规范、布局契约测试和类型检查；无后端或浏览器依赖 |
| `npm test -- <测试文件>` | 受影响组件/逻辑的定向回归；自动先跑共享静态检查 |
| `npm run build` | 仅构建准入触发时执行，验证类型和生产产物；不替代行为测试 |
| `AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design` | 满足完整验收准入时执行安全前检、全量 Vitest、构建和五组串行 E2E；生命周期及失败恢复见 [E2E 指南](../e2e-automation/guide.md#运行入口与生命周期) |

完整验收前检不要求后端预先启动；runner 在安全环境及本机目标确认后管理健康检查、PG 指纹、互斥夹具及原运行档案恢复。普通页面交付不因此默认启动完整设计验收。

| 检查对象 | 权威规则 / 实现 | 可自动覆盖的部分 |
|---|---|---|
| 路由、页面登记、占位与布局合法性 | DESIGN §5、§7 与 `pageRegistry` / validator | `pageRegistry.spec.ts`、`layout-contract.spec.ts`、`validator.spec.ts` |
| 受控控件与共享状态接入 | DESIGN §4、`design-contracts.json` 及共享组件 | `check:contracts`、`design-contract-gates.spec.ts`、相关消费者及行为测试 |
| 字体、边框、提示、滚动和共同尺寸 | DESIGN 对应专章与共享实现 | `check:design` 中对应扫描器及其定向测试 |
| 基础控件与容器的属性归属 | DESIGN §4、`design-contracts.json` 的 `styleRoles`、共享适配及布局所有者 | `check:contracts` 的覆盖/失效登记/精确绑定检查、各家族合法与违规样例、all 重置、运行时精确授权、新增控件/专项登记与根包装继承；真实样板和代表性页面的字阶、尺寸、浮层、明暗主题及缩放复核 |
| 新字段和配置消费 | DESIGN §7.3 与前后端配置事实源 | 配置契约、后端 layout 测试及真实保存/回显验证 |
| 四态、响应式及实际交互 | DESIGN §4、§8 和本模板的计划/维护矩阵 | 低层边界测试及登记检查；实际几何、可达性、恢复和最终呈现由受影响页面浏览器复核 |

自动检查通过只证明其覆盖范围。按本次风险完成必要的低层测试和浏览器实测，交付分别说明执行命令、实际状态、结果及未验证项；必要检查失败或未完成时不得宣称验收通过。静态扫描不能证明全部语义复用或整站视觉状态成立。

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

结构：`action:filter-bar` + `main:data-table` + `main:detail`。适合列表与详情各自内滚的双栏页面。行情列表与分析区复用 `MarketMasterDetailWorkspace`；按滚动所有权选择 `fill` / `adaptive`，比例、窄屏回退和尺寸档案统一遵循 [DESIGN §5.5](../../DESIGN.md#55-共享工作区与尺寸档案)。计划只记录本页面选型及例外，不再抄录共享尺寸、匹配算法或保存流程。

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

页面设置抽屉沿用 `ComponentAutoSettings`，保存回调接入 `saveRemoteUserConfig`；运行时权限候选由公共组件共享给设置消费，禁止页面复制配置编辑器。临时展开状态不保存为长期偏好。测试覆盖阈值、动态权限回退、控件实例保留、隐藏限制摘要的状态角色及明暗呈现、字段定位/清除、错误聚焦与保存失败重试；维护入口见 DESIGN「列表高级搜索」。

### 键盘接入维护检查

键盘能力及适用范围以 [DESIGN.md「键盘能力与适用边界」](../../DESIGN.md#键盘能力与适用边界) 为唯一契约。按控件语义复用原生行为或共享实现；具体按键、适用范围和实现入口统一查阅该契约，禁止页面重复实现全局键盘监听。

维护矩阵：改变共享行为时同步入口与消费点测试；增加快捷键时同步可见说明、可访问快捷键属性、权限和忙态守卫；改变焦点路径时复核弹层、关闭恢复及 KeepAlive。上述机制不增加布局 kind、slot 或用户持久化配置，既有页面布局与响应式画像保持原边界。

### 按钮状态维护

按 [DESIGN 按钮与输入](../../DESIGN.md#按钮与输入)选择组件与角色，不在模板重复定义颜色配方。新增角色须同步其状态矩阵、对应共享样式入口及代表性消费验证；仅状态调整不新增布局 kind 或持久化字段。验收先检查链接、命令、选择项及静态标签的角色，再追踪局部 scoped 及子文字覆盖；复核启用预设的明暗主题、键盘焦点、加载/禁用、选中与代表性浮层消费点。仅规范或源码检查通过不能声明全站呈现通过，交付须说明实际覆盖和缺口。


全组件边界维护：面板、控件子件、弹层、提示、结构网格与图表边界统一引用 [DESIGN §6](../../DESIGN.md#全组件边界所有权与状态适配)。普通页面面板优先复用已有外壳，结构不同才消费 `.app-surface`；不复制输入焦点或禁用配方。共享边界改动触发页面设计闭环和组件/布局维护矩阵：登记角色与例外，核对错误+焦点、选中+禁用、loading与宿主边界，按影响选择真实样板及消费页验证；`check:borders`纳入构建，不能代替视觉证据。
