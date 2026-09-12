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
4. 优先运行 `npm run scaffold-page -- --pageKey <key> --label <中文名> --archetype <原型>` 生成骨架；脚手架中的 `data-scaffold-placeholder` 是未完成标记，接入真实组件和四态后必须删除，否则契约测试会失败。需要手写时再用 `createLayout(archetype, pageKey)` 起默认 `PageLayout`，按需覆盖 `slots`/`editable`/`responsive`。
5. 模板用 `<LayoutHost :layout="effective">` + 具名插槽（`slot.id`）填业务组件；弹窗/抽屉放 `#overlays`。页面业务抽屉使用 `PageDrawer`，页面设置使用 `PageSettingsDrawer`，页面禁止直接使用 `el-drawer`。数据表格使用 `AppDataTable + AppTableColumn`，列只声明 `label/prop/role` 等语义，不声明 `width/min-width`；普通名称列使用 `name`，带前置控件和主副信息的对象识别列使用 `entity`；日期、单位或短口径摘要统一传 `header-meta` 并保持同行单行，主内容前有紧凑控件时传 `leading-controls` 由组件统一对齐，不在页面拼私有表头；主表使用默认成长模式，只有抽屉、展开行和局部明细等非主表使用 `embedded`。
6. 若新增真实复用组件，补 DESIGN.md 清单、至少一个消费页面和测试；新增系统组件种类时同步 `COMPONENT_CATALOG`、schema 和预览；新增 Web 配置字段时同步字段定义、后端规则、pageRegistry 真实消费和配置中心验证。两类登记按职责维护，不机械捆绑。
7. 跑校验：`npm test`（validator + 契约测试）；DEV 期 `LayoutHost` 会 `assertLayout` 直接抛。
8. `npm run build`（含 vue-tsc 类型检查；改 `frontend/src` 后必构建）。
9. 核对 DESIGN.md 的 `page-registry` 区块已有唯一同名行：脚手架会自动写入；仅未使用脚手架时按下方 §8 手工补一行，禁止重复登记。
10. 新页面如需要出现在侧栏或有受控 API / 按钮动作，同步菜单 seed、功能点 seed、后端守卫、`v-permission`、默认角色授权决策，并按 [system-rbac-tenant.md](../architecture/system-rbac-tenant.md) 验收。

### 1.1 页面使用或新增组件的登记决策

按以下顺序判断，不能依赖系统从 Vue 标签自动猜测组件 kind：

1. **先复用真实组件**：查 `DESIGN.md`“真实复用组件清单”、`frontend/src/components/**`、业务组件目录和同类页面。已有同类 UI 或行为时直接复用；相同模式第二次出现时按项目复用规则抽取组件、composable、util 或 schema。
2. **判断是否是独立系统组件实例**：已有系统组件种类若在页面中承担独立布局区、成长区、滚动区或可配置能力，必须在 `pageRegistry.ts` 登记对应 slot，并由 `<LayoutHost>` 的同名插槽承载真实组件。仅作为另一个真实组件内部实现细节、没有独立布局或配置语义的子组件，不登记假 slot。
3. **消费已有受控字段**：登记 slot 后按 kind 自动继承字段。结构能力写 `slot.config`，安全候选写 `componentMeta`，明确例外写 `fieldApplicability` 与原因；页面必须读取并应用生效值，普通页面必须把 `componentAllowedLayers` 接入 `PageSettingsDrawer`。不得增加逐页面字段白名单。
4. **没有匹配的系统组件种类**：如果新能力只负责真实 UI 复用，不需要进入布局配置、系统组件页、页面设置抽屉或页面布局编辑器，不新增 kind；如果需要这些平台能力，则按本文 §3“新组件种类”维护目录、schema、预览、页面 slot 和测试。
5. **新开发真实 Vue 组件**：先判定页面私有业务片段、业务域复用组件或全局真实复用组件。形成稳定复用单元时维护 `DESIGN.md` 真实组件清单、至少一个实际消费点和组件/消费页测试；不要为了组件文件存在而机械新增系统 kind。
6. **新增可配置属性**：只有属性会被页面设置、页面布局或预设真实消费时，才进入组件配置层；按本文 §3“新组件配置字段”同步 `COMPONENT_FIELD_DEFS`、前端 schema、后端字段和值域/归属规则、安全渲染器、页面实际效果、系统组件覆盖状态和测试。纯组件内部 props 不进入该契约。

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
- 纯图标操作：使用 `AppIconButton`；异步纯图标操作使用 `:loading`；具体尺寸、tooltip 和 Unicode 禁令见 DESIGN。
- 专用原生按钮例外：
- 自检结论：

### 字体与间距规范
规则入口：[DESIGN.md](../../DESIGN.md) §3「Typography Rules / Spacing & Rhythm Rules」。

- 新增或复用的语义类 / token：
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
| 布局旋钮 | density | page/user | editable | 信息密度 |
| 组件设置 |  | preset/page/user | COMPONENT_FIELD_DEFS |  |
| 页面记忆 |  | usePageSettings | 业务选项 |  |

### 浮层设计
规则入口：[DESIGN.md](../../DESIGN.md) §4「弹窗与抽屉 / 设置抽屉」。

- 触发来源：页面 / 应用顶栏
- 浮层类型：dialog / 页面业务抽屉 / 页面设置抽屉 / 视口级全局抽屉
- 组件选型：`el-dialog` / `PageDrawer` / `PageSettingsDrawer` / 应用外壳 `el-drawer`
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
- cd frontend && npm test
- cd frontend && npm run build
- 视口验证：按 DESIGN.md §8 选择关键视口，默认覆盖 1100×620 / 1366×768 / 1440×900
- 检查无整页滚动、无视口高度硬编码、设置抽屉分段正常
- 检查按钮、图标、排版、间距、表格、抽屉和四态反馈均符合 DESIGN 对应章节；例外写明原因
```

如果计划声明“新增布局原型 / 组件种类 / 组件配置字段”，但没有维护清单，计划视为不完整，不能直接进入开发。

## 3. 组件 / 布局维护矩阵

| 变更类型 | 必须同步维护 | 必须验证 |
|---|---|---|
| 新页面 | 脚手架、`pageRegistry.ts`、`router/index.ts`、DESIGN 页面登记区块；四处 `pageKey` 必须一致；需要侧栏/权限时同步 RBAC 菜单与功能点 | `pageRegistry.spec.ts`、`layout-contract.spec.ts`、权限相关测试、build、关键视口 |
| 新布局原型 | `archetypes.ts`、`schema.ts`、`validator.ts`、`LayoutHost.vue`、DESIGN 原型说明 | `validator.spec.ts`、布局契约测试 |
| 新组件种类 | `COMPONENT_CATALOG`、`componentSchemas.ts`、`componentPreview.ts`、系统组件页展示 | `componentPreview.spec.ts`、`pageRegistry.spec.ts` |
| 新组件配置字段 | `COMPONENT_FIELD_DEFS`、`componentSchemas.ts`、后端 `layout_config.py` 字段/值域/实例归属规则、`ComponentAutoSettings` 通用或专用安全渲染器、系统组件覆盖页、页面真实消费、DESIGN 字段治理入口 | `component-config-contract.spec.ts`、`componentConfig.spec.ts`、后端 layout 测试、保存/回显与策略收紧验证 |
| 页面消费已有字段 | 登记组件 slot 即自动继承该 kind 的适用字段；结构能力写 slot `config`，候选能力写 `componentMeta`，明确例外写 `fieldApplicability` 和原因；页面仍必须读取/应用值，并把 `useRemoteLayoutConfig.componentAllowedLayers` 传给统一抽屉。需要会话交互时走“配置默认值 → session state”，页面操作不反写默认值 | `pageRegistry.spec.ts` 自动继承、适用性、策略接线、正向消费与禁止页面直写契约，页面交互验证 |
| 新真实复用组件 | 组件文件、DESIGN 真实复用组件清单、至少一个消费页面；需要配置化时再同步系统组件种类/字段事实源 | 组件/消费页测试、build；涉及页面布局时做关键视口 |
| 业务域内复用组件 | 组件文件、DESIGN 真实复用组件清单、明确业务边界与消费页面；仅在需要布局配置时登记系统组件 kind | 组件/消费页测试、build、对应业务页面交互验收 |
| 按钮 / 图标操作体系 | `global.css` 控件 token、`AppIconButton`、DESIGN 按钮规范；确需新增专用原生按钮时同步契约允许项和理由 | `button-system.spec.ts`、组件测试、build、顶栏与操作区视觉验收 |
| 字体 / 间距体系 | `global.css` typography/spacing token、DESIGN 排版与节奏规范；新增语义层级时同步 token、文档和消费点 | 相关样式契约测试、build、关键页面视觉验收 |
| 全局界面比例 | `useDisplayScale`、`useLayoutViewport`、`displayScaleGeometry`、根画布与独立遮罩、视觉环境入口和 DESIGN；偏好复用 `useGlobalPreferenceSync`；自动缩放指数由预设管理、后端校验、登录公开白名单和运行时缓存共同承接，默认 0.10；尺寸断点使用 `app-viewport`，第三方坐标补丁随安装校验 | composable/坐标换算和真实组件交互单测、尺寸断点契约、build、分隔条/图表/滚动恢复与 Teleport 浮层视觉验收 |
| 品牌字标 / 主题强调色 | `BrandMark.vue`、`useLayoutPreset.ts`、登录页与应用外壳消费点、DESIGN 品牌规则；不得新增场景变体或消费侧颜色覆盖 | `BrandMark.spec.ts`、`useLayoutPreset.spec.ts`、build、登录页与工作台同模式同预设视觉验收 |
| 页面抽屉 | `#overlays`、`PageDrawer` / `PageSettingsDrawer`、唯一浮层类；新增公共能力时同步 DESIGN 组件清单 | `PageDrawer.spec.ts`、`layout-contract.spec.ts`、页面与顶部栏边界、正文内滚、关闭行为 |
| 纯业务偏好 | `usePageSettings` / 页面业务态，放入「业务选项」并标注「页面记忆」 | 业务行为验证、必要时 build |

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
// preset/page/user 层与管理员字段策略。
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

### 6.1 抽屉选型

| 触发位置与用途 | 使用组件 | 覆盖范围 | 规则 |
|---|---|---|---|
| 页面内业务详情、日志、长流程 | `PageDrawer` | 当前 `LayoutHost` 内容区 | 放在 `#overlays`；正文内滚；宽度只用 `sm/md/lg/xl/xxl/wide/full` 语义档位；`wide` 仅日志、字段差异、长 JSON 等横向内容，`xl` 用于固定宽度复杂详情/预览，`xxl` 用于资产搜索等需要更宽横向空间的复杂详情，`full` 仅用于窄屏承载桌面同等复杂工作台；页面不得传 px/%；不得遮挡应用顶栏、导航和工作标签 |
| 页面右上角设置入口 | `PageSettingsDrawer` | 当前 `LayoutHost` 内容区 | 内部复用 `PageDrawer`；固定承载布局、组件设置和业务选项 |
| 应用顶栏的用户中心、外观等全局能力 | 应用外壳中的 `el-drawer` | 整个视口 | 仅允许在 `App.vue` 等应用外壳使用，不属于业务页面模板 |

组件关系：

```text
PageSettingsDrawer
└── PageDrawer
    └── el-drawer
```

`PageDrawer` 负责页面边界、遮罩、挂载位置和通用插槽；`PageSettingsDrawer` 负责页面设置的固定内容结构。二者不是并列替代关系。

### 6.2 页面骨架

```vue
<template>
  <LayoutHost :layout="effective">
    <template #action> <!-- 筛选/批量/工具栏，固定不滚；多个固定块用 <div class="lh-action"> 包一层 --> </template>
    <template #main>   <!-- 主表/主图/主列表 --> </template>
    <template #footer> <!-- 可选：固定底部批量条/购物车条（选择跨页累积）；纯渲染槽，不入 schema --> </template>
    <template #overlays>
      <PageDrawer v-model="detailOpen" title="业务详情" class="my-detail-drawer">
        <!-- 页面业务详情；长内容在抽屉正文内滚 -->
      </PageDrawer>

      <PageSettingsDrawer
        v-model="settingsOpen"
        title="页面名称"
        :page-key="pageKey"
        :config="drawerConfig"
        @reset="resetPageSettings(); resetLayout()"
      >
        <template #business>
          <!-- 页面记忆或业务偏好 -->
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>
```

> 多组件主区（mixed/columns）按 `slot.id` 具名放置：`<template #<slotId>>…</template>`。可参考已登记且通过契约测试的同原型页面。
> `el-dialog` 仍可放在 `#overlays`；页面抽屉不得用 `el-drawer` 替代 `PageDrawer`。Teleport 生成的内部 DOM 样式使用唯一全局类或 `:global`。

## 7. 验收红线（机制性强制，违反则对应 `npm test` / `npm run test:design` 门禁失败）

- 后端按项目约束以明确的本地环境和 `AI_STOCKS_E2E_WRITE=1` 健康启动、并校准调试账号后，完整设计验收统一执行 `AI_STOCKS_ENV=dev AI_STOCKS_E2E_WRITE=1 npm run test:design`（`dev` 可按实际环境替换为 `test` 或 `local`）；命令会先校验调用方安全环境，再请求 `E2E_API_URL`（默认 `http://127.0.0.1:8000/api`）下的 `/health/e2e`，只有响应 `code: 0` 且返回合法 PG 指纹时才继续 Vitest、生产构建和串行 Playwright 响应式回归。后端未启动或未以 E2E 写模式启动时必须在前置检查中 fail-fast，并给出带相同环境变量的重启指引。串行用于避免多个视口并发复用调试账号造成鉴权级联失败，日常快速门禁仍可单独执行 `npm test`。
- 不得新增视口硬编码高度（`height:/min-height: …vh` 或 `calc(…vh)`）——`layout-contract.spec.ts` 扫描 `src/views` 拦截。`max-height: …vh` 仅限弹层安全上限。
- 非公开 View 路由、`pageRegistry` 和 DESIGN marker 必须以 `pageKey` 双向一致；registry 页面必须真实导入和渲染 `LayoutHost`，并通过 `getPageLayout` 消费布局——`pageRegistry.spec.ts` 使用 TypeScript AST 与页面源码共同拦截。
- 页面不得绕过 `LayoutHost` 手写 `.v-page/.v-grow/.v-scroll`——`layout-contract.spec.ts` 拦截。
- 页面不得保留脚手架 `data-scaffold-placeholder`——必须接入真实组件和四态后再交付。
- 页面源码不得直接使用 `<el-drawer>`；业务抽屉必须使用 `PageDrawer`，页面设置必须使用 `PageSettingsDrawer`——`layout-contract.spec.ts` 扫描拦截。
- 不得使用未登记组件种类——`validateLayout` 拦截。
- 不得把页面业务结构放进用户级配置；不得把不可重排的大表放进多列重排——`validateLayout` 拦截。
- 列表交互：分页/排序默认走服务端、筛选变更自动触发（不设“查询”按钮）、多选跨页累积；“重置筛选”与“刷新”的准入、稳定命名、操作状态机、锁定范围、过期响应保护和触发边界统一遵守 [DESIGN.md](../../DESIGN.md)「按钮与输入 › 查询、重置与刷新」，页面不得私有改名或用 disabled 冒充 loading。**例外判据**：当数据为固定小集合（如一次性取全、无分页的 Top N 榜单）时，可允许客户端重排，且须在设计中注明为有意差异。
- 真实组件：已有真实复用组件能覆盖的控件行为，不得继续在页面内复制手写；`data-table` / `wide-table`、`settings-drawer` 等逻辑种类由 `pageRegistry.spec.ts` 校验真实导入和渲染，`config-panel` 校验页面级入口 `ConfigGroupForm`，再由该组件复用 `ConfigPanelSection`；组合型 `toolbar` / `section` / `tabs` 不要求虚构同名空壳组件。
- 表格列宽：页面不得直接使用原生 `<table>`、`el-table`、`el-table-column`，不得向 `AppTableColumn` 传 `width/min-width`；宽度统一由语义基础宽、表头字符权重、排序/筛选控件和可选 `header-meta` 推导。`label="操作"` 必须按动作密度显式声明 `role="action-compact"`（单动作或仅“更多”入口，默认下限 96px）或 `role="action"`（两个及以上候选动作，默认下限 144px）；两档默认统一居中表头与单元格、不参与表格富余空间分配，但由 `AppRowActions` 按当前已渲染行的最低可用组合向上扩展。单动作最低完整显示该动作；多动作最低保留两个入口，可由两个直接动作或“首个直接动作 + 更多”构成，“更多”计作一个入口；除调用方明确把全部动作收进更多外，禁止退化为仅“更多”；数据事实不得复用“操作”标签，应使用“操作笔数”等准确名称和真实字段语义。
- 高度与滚动：`list` 必须唯一 `growMain`；`LayoutHost` 统一应用组件有效 `minH`。剩余高度达到 `minH` 时由组件内部滚动，低于 `minH` 时才由主内容区滚动兜底。页面不得用 `fill`、私有视口高度或外层滚动覆盖该决策。
- 四态反馈：registry 页面必须真实复用 `AppStateBlock` 承接非 ready 状态；ready / loading / empty / error 互斥。无旧内容首次加载使用 `AppStateBlock loading` 骨架，已有内容刷新才使用 `v-loading` 遮罩；表格由 `AppDataTable` 自动完成该分流并承接空态，`#empty` 只能补充 `app-table-empty*` 文案和操作，禁止嵌套 `el-empty`。用户主动刷新、筛选、分页、排序或切换主结果口径失败后，`error` 必须接管受影响区域并隐藏旧 ready 内容。缓存数据仍可安全使用的后台保鲜、偏好或参考选项同步失败，使用 `AppStatusNotice` 承接 ready 的持久降级说明，不得同时渲染整区异常态。多个相邻区域因同一请求、同一空集合或同一必需依赖进入非 ready 时，必须在最近公共父级聚合为一个主状态；主从两侧不得重复大图标和主动作。错误态必须可见且有真实重试或原因说明，具体分支由消费页测试或关键视口 E2E 验证。

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

结构：`action:filter-bar` + `main:data-table` + `main:detail`。适合左侧列表、右侧详情；两栏各自承载滚动，不把详情塞进弹窗替代主流程。行情列表+分析图表必须复用 `MarketMasterDetailWorkspace`；列表按工作台容器的 `masterRatio` 连续计算，系统默认 `45%`、允许配置 `30%–70%`，仅在列表至少 `360px` 或详情至少 `240px` 的真实内容安全边界触发时偏离配置比例，不设置列表固定像素上限。工作区布局宽度不超过 `720px` 时统一退化为列表单区，选择对象后由工作台的全屏抽屉承载详情或分析，页面不得私建紧凑抽屉。主区拖动只修改会话比例；“使用页面当前比例”保存当前工作区宽度与比例，同页同用户可保存多项，当前宽度在档案 `±15%` 范围内时使用最近项，`5%` 内重复保存更新原项，无匹配时回退默认比例；双击分隔条恢复当前匹配或默认比例。设置抽屉只保留默认占比和紧随其后的共享主色采用按钮，不直接展示档案与匹配算法。历史 `masterWidth` 固定像素值只允许兼容读取，不再作为页面分栏依据。

### 9.3 dashboard

```bash
npm run scaffold-page -- --pageKey my-dashboard --label "仪表盘" --archetype dashboard --route /my-dashboard --view MyDashboardView
```

结构：`main:kpi-grid` + `main:chart`。适合 KPI、图表和概览面板；只对平级块做安全重排，单个大表仍走内滚。

### 9.4 form

```bash
npm run scaffold-page -- --pageKey my-form --label "表单页" --archetype form --route /my-form --view MyFormView
```

结构：`main:form`。适合创建/编辑页；字段区内滚，提交按钮应固定在表单语义尾部或 footer，不写视口高度。

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
