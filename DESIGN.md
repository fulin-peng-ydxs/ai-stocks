---
version: alpha
name: 复盘啦
description: A 股趋势研究工作台，面向高密度行情、筛选、回测、训练、权限管理和数据治理工作流，采用克制、可配置、可验证的专业后台界面。
typography:
  button-md:
    fontWeight: 650
---

# 复盘啦 Design System

> 本文是前端页面、视觉样式、布局系统和组件配置的长期事实源。强制规则在 `frontend/src/layout/`、后端 layout 配置校验和 `frontend/src/layout/__tests__/` 中；新页面执行流程和可复制计划块放在 `agent-works/configurable-layout-system/page-template.md`。

关键事实源：

- 全局样式与主题变量：`frontend/src/styles/global.css`
- 应用外壳：`frontend/src/App.vue`
- 页面注册：`frontend/src/layout/pageRegistry.ts`
- 原型：`frontend/src/layout/archetypes.ts`
- 组件目录：`frontend/src/layout/components.ts`
- 组件字段：`frontend/src/layout/componentConfig.ts`
- 预设 token：`frontend/src/layout/presets.ts`
- schema 校验：`frontend/src/layout/validator.ts`、`componentSchemas.ts`
- 响应式摘要：`frontend/src/layout/responsive.ts`
- 配置中心：`frontend/src/views/layout/{LayoutPresetsView,LayoutPagesView,LayoutComponentsView}.vue`
- 后端持久化与校验：`backend/storage/layout_config.py`、`backend/api/layout.py`
- 新页面模板：`agent-works/configurable-layout-system/page-template.md`

文件头 frontmatter 只保留已被自动化读取的兼容字段；运行时 token 以 `global.css`、`presets.ts` 和 `themeSurfaces.ts` 为准。新增 token 不回填 frontmatter，除非同步新增机器读取契约和测试。

## 1. Visual Theme & Atmosphere

复盘啦是专业金融研究空间，不是传统后台、营销页或内容站。界面优先支持反复扫描、比较、筛选、回测和配置，视觉应当安静、克制、可读，并通过统一材质与清晰层级保持金融科技气质。

Key Characteristics：

- 信息密度偏高，但通过表格内滚、抽屉分段、字段收纳和提示悬浮保持可扫读。
- 默认气质为冷静、均衡的金融科技研究终端；金融数据场景允许红绿涨跌色，但不以过度紧凑和控件堆叠表达专业。
- 页面首屏直接呈现业务工具，不做大 hero、不做营销式空白、不做卡片堆叠式装饰。
- 所有业务页面通过布局系统组织，页面结构由 schema 和测试约束，不依赖临时 CSS 猜高度。
- 视觉预设可以改变 token、密度和受控组件默认策略，但不能改变页面业务结构。

## 2. Color Palette & Roles

颜色以 Element Plus 变量、`global.css` 的 `--chrome-*` / `--page-settings-*` 变量和 `LAYOUT_PRESETS` 为事实源。内置预设只保留 `daylight`、`nocturne`、`balanced` 三套，默认使用 `balanced`；三套预设必须同时覆盖登录页、应用外壳、业务内容区和外观选择预览。

| 角色 | 默认值 | 使用规则 |
|---|---:|---|
| 主交互色 | `#409eff` | 主按钮、当前菜单、可点击强调、选中边框 |
| 页面背景 | `#f5f7fa` | 工作区底色，不直接承载业务控件 |
| 表面色 | `#ffffff` | 卡片、表格、输入框、抽屉内容面 |
| 悬停表面 | `#eef1f6` | 菜单、表格行、轻量按钮 hover |
| 主文字 | `#1f2937` | 标题、表头、关键字段 |
| 正文文字 | `#4b5563` | 表格正文、表单值、说明正文 |
| 次要文字 | `#8a94a6` | 提示、辅助说明、弱化信息 |
| 边框 | `#e4e7ed` | 卡片、表格、分割线、输入框 |
| 强边框 | `#d0d5dd` | 选中、强调分区、高对比预设 |
| 成功 | `#2f9e44` | 健康状态、成功提示、部分下跌色 |
| 警告 | `#d97706` | 异常但未失败、样本不足、风险提示 |
| 危险 | `#dc2626` | 失败、删除、风险、金融上涨色 |

金融涨跌色遵循当前项目口径：上涨/正收益多用红色，下跌/负收益多用绿色；不要套用海外红跌绿涨习惯。

语义 token 规则：

- 权限树颜色使用 `--perm-group-color`、`--perm-feature-color`；菜单点使用 Element Plus 成功色，不在页面内写死色值。
- 金融涨跌使用 `--market-up-color` / `--market-down-color`，不要在页面里直接写红绿 hex。
- `StockChartWorkspace` 及个股详情股票画布通过 `stock-chart/chartUtils.ts::stockChartTheme()` 读取 CSS 语义色；该工作区的 MACD 正柱与金叉使用 `--market-up-color`，负柱与死叉使用 `--market-down-color`。交叉事件必须同时使用“金叉/死叉”文字、标签轮廓、数据点锚点和交易日引导线表达，不得只依赖红绿颜色，也不为金叉新增独立金色 token。
- 个股 K 线 MA5 复用 `--market-up-color` 红色系，MA60 复用 Element Plus `warning` 主题黄色；两者只表达序列身份，不表达买卖信号。K 线 tooltip 的收盘与涨幅才按相对昨收使用涨跌色，平盘保持中性。
- `StockChartWorkspace` 的 Canvas 不会随 CSS 变量自动重绘；该组件必须监听预设系统在完整 token 写入后递增的 `themeRevision`，同时覆盖明暗切换、预设 key 切换和当前预设同 key 后端覆盖更新。本条只适用于 `StockChartWorkspace`/个股详情股票画布；其它图表不会自动继承，扩大适用范围时必须同步完成运行时改造和独立回归。
- 分项评分徽章使用 `--score-high-*` / `--score-mid-*`，低分使用弱底色和占位文字色。
- 页面提示、弱文本、占位文本优先使用 `--app-warning-text`、`--app-muted-text`、`--app-placeholder-text`；确属 Element Plus 标准状态时可直接用 `var(--el-color-*)`。
- 普通操作文字与禁用操作文字分别使用 `text`、`textMuted`；二者按 WCAG 线性相对亮度计算的差值必须 `≥ 0.06`。这是文字层级阈值的唯一数值事实源，预设保存和运行时合并均须守卫。
- 预设运行时必须同步覆盖 Element Plus 语义色的基础色、RGB 通道、`light-3/5/7/8/9` 与 `dark-2` 派生色；`error` 与项目危险色同源。按钮、链接、提示、分段控件、焦点和禁用态不得回退到组件库默认蓝绿橙红色阶。

预设规则：

- 每套预设的登录页与工作台必须同源：同一 `preset + light/dark` 下，登录页右侧交互区基础色等于工作台 `pageBg`；登录卡片可保留透明、模糊、边框和阴影，但卡片叠加到右侧基础色后的肉眼可见色必须等于工作台 `surfaceBg`。该关系以 `frontend/src/layout/themeSurfaces.ts` 为登录/工作台底色事实源，并由 `presets.spec.ts` 守卫；禁止只改登录页或只改主页造成同主题内体验漂移。
- 登录页可保留光晕、网格、轨迹、透明和模糊等品牌装饰，但装饰层不能改变 `themeSurfaces.ts` 和 `presets.ts` 定义的基础底色事实源。
- `daylight`（日曜）：铂金银灰、瓷白表面、蓝宝石电光与精密石墨构成高照度研究舱；不使用米黄、香槟、金色、铜色或琥珀色表现高级感，材质层级由明度、银灰边界与克制冷影建立，蓝色承担轨迹信号与精密交互，优先服务白天长时间阅读。其暗色模式使用蓝黑石墨、银灰边界与蓝宝石信号，不得回落为夜航的深海青蓝色系。
- `nocturne`（夜航）：深海蓝、冷青与铂金边界，优先服务低照度夜间复盘；禁止使用纯黑大底。
- `balanced`（晨昏）：日间以海军蓝与香槟金保持明暗平衡；夜间以登录交互区既有的深蓝黑为视觉基准，并配合暖石墨边界和小面积香槟金信号建立克制的黑金层级。登录页颜色不得因主页试色而反向漂移。
- 明暗模式与三套预设正交；每套仍需维护完整 `light` / `dark` token，并在切换时保持控件对比度。
- 存量 `technology` / `finance` 页面引用升级时迁移到 `balanced`；其预设默认密度从 `compact` 回落为 `standard`，页面层或用户层已有 `density` 覆盖继续保留。
- 新增或调整预设必须维护 `light`、`dark`、共享形态 token、`themeSurfaces.ts` 登录/工作台底色事实源，并通过 `presets.spec.ts`。

## 3. Typography Rules

字体栈以系统中文字体为主：`PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif`。不得引入需要联网加载的字体。

排版事实源：

- token 落地在 `frontend/src/styles/global.css`，包括 `--app-font-family-base`、`--app-font-size-*`、`--app-line-height-*`、`--app-font-weight-*`。
- 页面私有样式不得新增游离字体族；除品牌字标、登录主视觉、代码/配置值、图表 tooltip 外，必须继承 `body` 的 `--app-font-family-base`。
- 新增文字样式必须先判断是否能消费 `.app-page-title`、`.app-section-title`、`.app-body-text`、`.app-caption-text`、`.app-micro-text`、`.app-data-text`、`.app-data-emphasis` 或对应 token。
- 常规行高使用表内 token；图标/徽标贴边用 `--app-line-height-solid`，紧凑说明用 `--app-line-height-compact` / `--app-line-height-comfy`，长说明用 `--app-line-height-reading` / `--app-line-height-longform`，极小角标用 `--app-line-height-ornament` / `--app-line-height-tiny`。

| 层级 | 强制 token / 值 | 使用场景 |
|---|---|---|
| 页面标题 | `--app-font-size-page-title` 22px / 700 / 30px；紧凑页可用 20px | 页面主标题、工作台名称、配置中心一级标题 |
| 分区标题 | `--app-font-size-section-title` 15px / 650 / 22px；抽屉或大面板可用 18px | 卡片标题、抽屉标题、配置组标题 |
| 正文 | `--app-font-size-body` 14px / 400 / 22px | 表单、普通说明、主体内容 |
| 表格正文 | `--app-font-size-table` 13px / 400 / 20px | 数据表格、列表、密集参数行 |
| 辅助标签 | `--app-font-size-caption` 12px / 400 / 18px | 单位、提示、来源、次级说明、tag 内文 |
| 微型标签 | `--app-font-size-micro` 11px / 400 / 16px | 顶栏弱标签、状态小字、空间极窄的 badge；禁止用于正文 |
| 数字强调 | `--app-font-size-data` 16px / 650 / 24px；大 KPI 可用 `--app-font-size-kpi-lg` 26px / 700 / 32px | KPI、收益、评分、排名、需要横向比较的数字 |

排版规则：

- 标题用于定位页面和分区，不用于装饰性大字。
- 页面主体新增 `font-size`、`line-height`、`font-weight` 时必须引用上述 token 或语义类；直接写 px/数字只允许在以下特例：品牌字标、登录主视觉、图表 canvas/tooltip、第三方组件适配、极窄状态点/角标、图标尺寸。特例必须是局部私有，不得被复制为普通页面模式。
- 10px 以下只允许使用 `--app-font-size-ornament` 或 `--app-icon-size-xs`，用于图标内部标记、红点角标或不可读正文之外的装饰性标尺；不得用于业务说明、表格、表单、按钮、筛选项。
- 11px 只用于弱标签或极窄 chrome 信息；业务内容、表格单元格、表单 label、按钮文案不得小于 12px。
- 表格内长文本默认省略、tooltip 或详情承接，不默认自动换行撑高行高。
- 说明性长文优先进入 `HelpTip` / `HelpHint`，页面上只保留必要短标签。
- 组件内提示、说明、空状态、校验文案必须按容器宽度排版，避免长句硬塞一行；必要时分行、缩短文案或交给 tooltip / popover 承接，不得挤压主操作区或造成文本重叠。
- 按钮、标签、抽屉标题、表格控件中的文字不得溢出容器。
- 金融数字按列右对齐或按业务组件一致处理，避免同列数字参差。
- 股票代码、配置 key、日志字段、接口路径等技术标识可使用 `--app-font-family-mono`，但仅限值本身，不把整段说明改成等宽体。

### 3.1 Spacing & Rhythm Rules

间距事实源在 `global.css`：`--app-space-1=4px`、`--app-space-2=8px`、`--app-space-3=12px`、`--app-space-4=16px`、`--app-space-5=24px`、`--app-space-6=32px`，控件内部图文间距使用 `--app-space-control-gap=6px`。

| 场景 | 强制节奏 | 说明 |
|---|---|---|
| 页面 slot 间距 | `--layout-page-gap` = 12px | `LayoutHost` / `.v-page` 默认节奏，不在页面内重复手写 |
| 固定操作区多行 | `.lh-action` / 12px | 工具栏 + 筛选栏纵向排列 |
| 普通横向控件组 | `.app-cluster-md` / 8px；按钮图文 6px | 筛选项、按钮组、状态项 |
| 表单/设置项纵向 | `.app-stack-sm` 8px 或 `.app-stack-md` 12px | label、控件、说明成组 |
| 卡片/面板内边距 | `--layout-card-padding` = 16px；密集面板可 12px | 高密表格容器可压缩但不得牺牲可读性 |
| 大区块分隔 | 16px 或 24px | 独立业务块、KPI 到主表、说明组到表单 |
| 空态/异常态 | 使用 `app-empty*` / `AppStateBlock` | 不自定义另一套图标、字号、间距 |

间距规则：

- 页面新增 `gap`、`padding`、`margin` 时优先使用 spacing token 或语义类；不得随手新增 5px、7px、9px、11px、13px、15px 这类游离节奏。
- 6px 仅用于控件内部图文、顶栏轻量状态组、极小图标与文字之间；10px、14px、18px 只作为已有组件历史兼容或特定密度调优，不作为新增页面默认节奏。
- 同一行内控件必须在视觉基线上对齐；说明文字和控件作为一个整体时使用 `AppControlItem`，多个控件行使用 `AppControlRow`。
- 同一页面内不得同时出现多套标题上/下边距节奏；分区标题下接正文用 4-8px，下接表格或复杂控件用 8-12px。
- 精细特例可以保留，但必须局部、少量、可解释，且不改变页面主体网格和信息层级。

## 4. Component Stylings

组件样式基于 Element Plus 和项目 token，不另建并行组件库。新增组件先判断能否复用 Element Plus、项目已有基础组件和 `frontend/src/layout/components.ts` 中的组件能力目录。

### 组件化复用约束

前端通用 UI、交互逻辑、状态处理、数据展示模式或参数处理逻辑，只要在代码中第二次出现，就必须优先抽取为复用单元。

- UI 结构和交互表现抽 Vue 组件。
- 组合状态、表单联动、权限判断、布局计算抽 composable。
- 纯数据转换、格式化、字段映射、参数归一化抽 util 或 API helper。
- 表格列、筛选项、弹窗/抽屉结构、空态/加载/错误态、操作按钮组第二次出现时，也纳入复用判断。
- 不抽取时必须有明确理由，例如领域语义不同、生命周期明显不同、抽象后反而增加调用复杂度。
- 复用单元形成后，后续同类实现必须消费该组件、composable 或 helper，禁止继续复制同类代码。
- 用户偏好同步只能消费既有偏好骨架：全局 singleton 偏好使用 `useGlobalPreferenceSync`，页面/feature 级实例偏好使用 `useUserPreference`；禁止在页面或业务 composable 内另写 token 守卫、身份重同步、debounce、PG 读写和 localStorage fallback 的并行实现。

### 组件资产分层

项目内“组件”分两层治理，不能混用：

- **真实复用组件**：位于 `frontend/src/components/**` 或 `frontend/src/layout/components/**` 的 Vue 运行时组件，负责真实渲染和交互，例如 `PageSettingsDrawer.vue`、`ComponentAutoSettings.vue`、`AppPagination.vue`、`AppFilterSelect.vue`。
- **系统组件种类**：位于 `frontend/src/layout/components.ts`、`componentConfig.ts`、`componentSchemas.ts` 的布局/配置元数据，例如 `data-table`、`wide-table`、`tabs`、`settings-drawer`；它让页面布局、系统组件页、页面设置抽屉和配置中心识别组件能力，但不必然对应一个同名 Vue 组件。

关系规则：

- 页面外壳、slot、滚动归属、可配置字段必须走系统组件种类和 `pageRegistry`。
- 真实 UI 行为优先复用真实复用组件；当同类控件在两个及以上页面出现，或承载全局交互规则时，必须登记到下方“真实复用组件清单”。
- 真实组件只有需要进入布局配置、系统组件页、页面设置抽屉或页面布局编辑器时，才新增或关联系统组件种类。
- 禁止只在 `COMPONENT_CATALOG` 登记但页面不读取的“假配置”；也禁止已有真实复用组件时继续在页面内复制同类控件行为。

系统组件页信息维护规则：

- `LayoutComponentsView` 展示的组件名称、说明、最低尺寸、滚动归属、成长/重排能力和专属特性来自 `COMPONENT_CATALOG`；这些信息变化时必须优先更新 `frontend/src/layout/components.ts`，不要在页面内硬编码第二套说明。
- `configCapabilities` 是英文能力 key 摘要，用于系统组件页展示组件具备的能力，不等同于“已开放 Web 配置字段”；不要为了展示把它本地化成另一套中文映射。
- 组件 kind 的语义变化时，必须同步检查 `components.ts` 的 `label`、`description`、`configCapabilities`，`componentSchemas.ts` 的 config shape，`componentPreview.ts` 的预览归类，以及 `schema.ts` 中该 kind 的说明。
- 系统组件页的可视化预览是给开发和验收人员对照组件形态、状态语义、文案与稳定占位的规范样板，不是业务页面截图，也不证明消费页面已经完成接入。`ready` 可使用代表性原型；`loading / empty / error` 必须直接复用 `AppStateBlock`，不得在预览层维护第二套状态视觉。
- 只有真实可被页面设置、页面布局或预设消费的字段，才进入 `COMPONENT_FIELD_DEFS`、后端 `layout_config.py` 字段规则和 `pageRegistry.consumedComponentFields`；否则只能停留在 `componentSchemas.ts` 的结构校验或 `configCapabilities` 的能力摘要。
- 改动系统组件信息后至少运行相关布局测试；改动预览四态时必须验证预览复用 `AppStateBlock`；涉及前端源码时同时运行构建。

核心真实复用组件清单：

| 真实组件 | 路径 | 用途 | 系统组件关系 | 使用规则 |
|---|---|---|---|---|
| `PageSettingsDrawer` | `frontend/src/components/PageSettingsDrawer.vue` | 统一页面设置抽屉运行时组件 | 对应 `settings-drawer` 种类；`size/defaultCollapsed` 的用户偏好走 PG `user_preference`，`bodyScroll/collapsibleSections` 只允许 preset/page 层 | registry 页面统一使用，禁止页面另写第二套设置抽屉 |
| `PageDrawer` | `frontend/src/components/PageDrawer.vue` | 页面级抽屉边界组件 | 无直接系统组件种类 | 页面打开的设置、详情、日志抽屉统一挂载到 `LayoutHost` 内容区；禁止直接覆盖应用顶栏与导航 |
| `ComponentAutoSettings` | `frontend/src/components/ComponentAutoSettings.vue` | 组件特性唯一渲染器 | 消费 `pageRegistry.consumedComponentFields`、`componentMeta` 和 `COMPONENT_FIELD_DEFS` | 设置抽屉 user 层与页面布局编辑器 page 层共用；候选项可由页面按当前业务上下文传入运行时 meta 覆盖，避免不同面板的分区混显 |
| `SettingsGroup` | `frontend/src/components/SettingsGroup.vue` | 设置抽屉的分组容器 | 无直接系统组件种类 | 页面设置抽屉分组优先复用；不直接用于主内容区配置面板 |
| `ConfigPanelSection` | `frontend/src/components/config/ConfigPanelSection.vue` | 主内容区配置面板的可折叠分组容器 | 对应 `config-panel` 种类；读取 `collapsibleSections`、`defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | 系统设置等主面板配置分组优先复用；配置项说明/默认值继续放 `HelpHint`，一级组说明在组头展示，二级分区说明随分区内容一起展开/收起 |
| `PageSegmented` | `frontend/src/components/PageSegmented.vue` | 页面设置和业务偏好的分段选择控件 | 无直接系统组件种类 | 业务选项、组件设置中的枚举选择优先复用 |
| `PageToggleRow` | `frontend/src/components/PageToggleRow.vue` | 页面设置和业务偏好的开关行 | 无直接系统组件种类 | 业务选项、列显隐、布尔设置优先复用 |
| `AppControlRow` / `AppControlItem` | `frontend/src/components/AppControlRow.vue`、`frontend/src/components/AppControlItem.vue` | 页面工具行、查询行和参数行的通用横向控件容器；控件行默认按控件自然宽度排列，空间不足时换行，不自动拉伸填满；控件项把标签和控件作为一个整体换行 | `filter-bar`、`toolbar` 等系统组件种类的真实渲染基础 | 多个输入、选择器、按钮组成的横向行优先使用 `AppControlRow`；存在“说明文字 + 控件”时必须用 `AppControlItem` 包裹，避免标签和控件被拆到不同行；只有明确需要均分或撑满时才传 `fill` 或让具体 `AppControlItem` 设置 `grow` |
| `AppIconButton` | `frontend/src/components/AppIconButton.vue` | 全站纯图标操作按钮，统一可访问名称、尺寸、圆角、悬浮、聚焦、禁用、loading 和语义色 | 无直接系统组件种类 | 顶栏工具、抽屉关闭、刷新、页面设置等仅图标操作统一复用；必须传 `label`，异步纯图标操作使用 `AppIconButton` 的 `loading`，外层 `el-tooltip` 承载长说明时关闭原生 `title`；图形使用 Element Plus 图标或项目既有 SVG，禁止页面手写 Unicode 符号按钮 |
| `AppRowActions` | `frontend/src/components/AppRowActions.vue` | 表格行操作列和列表项操作区的统一动作组，按权限过滤、单行排列、动作颜色层级、禁用/加载态展示和轻量“更多”菜单收纳 | 无直接系统组件种类 | 表格 `label="操作"`、自绘表格行、列表项和编辑器条件行的行内按钮组优先复用；首个未显式指定语义色的行内高频动作使用主色，普通次要动作使用常规正文色，禁用态使用弱文本色并满足语义 token 规则定义的文字层级阈值，停用/禁用/终止/删除等破坏性动作使用危险色；动作始终清晰可见，不对整组做透明度弱显；低频或危险动作可设置 `placement: 'more'`，菜单命令继续使用 Element Plus 按钮并呈现真实 loading，不得在页面内手写多行按钮或原生命令按钮 |
| `AppDataTable` | `frontend/src/components/AppDataTable.vue` | 数据表格/宽表运行时外壳，统一表头排序布局、表体内滚、分页承载、空态插槽和行点击样式 | 对应 `data-table`、`wide-table` 种类；读取页面传入的排序、分页、列显隐等消费结果 | 登记为 `data-table`/`wide-table` 的主列表、成长表和宽表优先复用；复杂单元格继续由业务页通过列插槽声明，不在页面复制表格外壳、分页容器和排序表头样式 |
| `AppStateBlock` | `frontend/src/components/AppStateBlock.vue` | 页面和组件的加载、空、异常、无权反馈块，统一 `ready / loading / empty / error` 四态中的非 ready 呈现、重试入口和尺寸档位 | 对应布局系统中的 `loading-state`、`empty-state`、`error-state`、`skeleton` 语义，但作为真实运行时复用组件消费 | 主加载失败、局部列表失败、无权态、非表格空态和稳定骨架占位优先复用；表格数据的 loading/empty 仍优先由 `AppDataTable` / `el-table` 承接，不在页面手写第二套错误块、空态图标或重试布局 |
| `StockChartWorkspace` | `frontend/src/components/stock-chart/StockChartWorkspace.vue` | 个股 K线、量能和 MACD 的纵向联动工作区，统一日期轴、光标、显式缩放同步、局部状态和可访问高度分隔线 | 无系统组件种类；图表组合与高度属于 `stock-detail` 页面业务偏好，不进入布局字段 | 个股详情统一消费；行情与指标按交易日对齐，MACD 局部失败不得阻断 K线/量能；只有 K线显示固定在绘图区左上角的行情 tooltip，量能和 MACD 只保留联动光标与标题当前值，不显示内容浮层；三图标题值与实际序列必须复用同一主题调色映射，柱宽按 K线、量能、MACD 明显递减，底部日期标签不得被缩放滑块遮挡；任一图的 `dataZoom` 必须显式同步给其余可见图并在主题重绘后保留；画布必须监听预设系统在完整 CSS token 写入后发布的主题修订版本，覆盖明暗、预设 key 和同 key 后端覆盖变化，分隔线遵守 reduced-motion；页面不得再拼装第二套多图联动和分隔线逻辑 |
| `AppPagination` | `frontend/src/components/AppPagination.vue` | 列表页统一分页 | 由 `data-table`/`wide-table` 的 `pageSize` 配置间接驱动 | 服务端分页页脚优先复用 |
| `AppFilterSelect` | `frontend/src/components/AppFilterSelect.vue` | 列表页筛选下拉 | 无直接系统组件种类 | 默认多选、可搜索、可清空；业务只允许单选时必须传 `multiple=false`；默认最多展示 3 个选中标签，溢出时提前折叠；筛选下拉优先复用 |
| `BrandMark` | `frontend/src/components/BrandMark.vue` | 应用品牌图形与「复盘啦」字标 | 无直接系统组件种类 | 应用外壳、登录页等品牌露出统一复用；禁止在页面内另画私有 logo 或手写第二套字标 |
| `SideMenu` / `TopNavigation` / `WorkspaceTabs` / `WorkspaceRouteView` / `MenuIcon` | `frontend/src/components/SideMenu.vue`、`frontend/src/components/TopNavigation.vue`、`frontend/src/components/WorkspaceTabs.vue`、`frontend/src/components/WorkspaceRouteView.vue`、`frontend/src/components/MenuIcon.vue` | 应用级菜单树、双层顶栏、保留现场的工作标签页、路由缓存与统一菜单图标渲染 | 无直接系统组件种类 | 菜单统一消费 `/me` 授权树和 `utils/permission.ts` 的路由归属口径；工作页面统一由 `WorkspaceRouteView` 渲染并按标签独立缓存，禁止业务页私建 KeepAlive；关闭标签必须同步移除对应缓存；侧栏、双层顶栏和菜单管理页统一用 `MenuIcon` 消费后端图标名；新增导航模式时复用 `useAppNavigation` 持久化偏好 |
| `AssetVisibilityTag` / `AssetProfileLabel` / `AssetVisibilityActions` | `frontend/src/components/AssetVisibilityTag.vue`、`frontend/src/components/AssetProfileLabel.vue`、`frontend/src/components/AssetVisibilityActions.vue` | 公开资产来源、可见范围、只读状态、方案名称+版本+归属标签、发布/收回、复制为我的方案和复用参数动作 | 无直接系统组件种类 | 评分、筛选、买卖、回测等公开资产页面必须复用；方案选择/列表入口统一用 `AssetProfileLabel`，消费页包括 `BoardView`、`ScreenView`、`ConfigView` 评分 tab、`ConfigView` 买卖 tab、`BacktestView` |
| `ConfigGroupForm` | `frontend/src/components/config/ConfigGroupForm.vue` | 系统设置配置组表单 | 消费 `config-panel` 的折叠与说明展示配置 | 动态配置组字段渲染优先复用 |
| `HelpTip` / `HelpHint` | `frontend/src/components/HelpTip.vue`、`frontend/src/components/HelpHint.vue` | 页面说明和短提示 | 无直接系统组件种类 | 说明性长文收进提示组件，不在页面堆长文 |

核心 composable 复用清单：

| Composable | 路径 | 用途 | 使用规则 |
|---|---|---|---|
| `useGlobalPreferenceSync` | `frontend/src/composables/useGlobalPreferenceSync.ts` | 全局 singleton 用户偏好同步内核，统一 token/身份守卫、PG `user_preference` 读写、debounce、加载失败回调和本地 fallback 钩子 | 主题、导航模式、跨页面设置抽屉等全局偏好必须消费；调用方只保留值归一化、DOM 副作用和本地存储 key 差异，不得复制远端同步流程 |
| `useUserPreference` | `frontend/src/composables/useUserPreference.ts` | 页面或 feature 实例级用户偏好骨架，统一默认值合并、PG `user_preference` 读写、本地 fallback、dirty-before-hydrate 保护和重置入口 | 页面业务选项、K 线偏好、回测参数记忆等按页面或功能隔离的偏好必须消费；页面只声明 defaults、scope、pageKey/prefKey 和业务字段 |

### 应用外壳

- 侧栏宽度固定为 `208px`，顶栏高度 `67px`，主工作区 padding 为 `20px 24px`。
- 应用提供 `sidebar-tabs` 与 `dual-topbar` 两种导航布局：侧栏模式在内容区上方显示可关闭工作标签；双层顶栏模式把一级菜单放在品牌顶栏、当前一级下的二级菜单放在独立次栏，三级页面由二级菜单下拉承接。
- 工作标签按路由路径保留页面组件实例、表单筛选与独立滚动位置，最多缓存 12 个；同一页面类型的不同详情路由必须拥有独立缓存身份，关闭标签或超过上限时同步销毁对应实例与滚动记录。
- 导航布局是独立用户偏好，不与明暗模式或颜色预设绑定；外观抽屉中的主题缩略图只表达色彩和材质，不暗示固定导航结构。
- `.main` 必须保持 `overflow: hidden` 和 flex 填充；页面滚动由布局系统内部区域承载。
- 菜单激活态使用主色边线和轻背景，不使用大面积高饱和底色。

### 按钮与输入

- 普通业务命令统一使用 Element Plus `<el-button>`：主命令用 `primary`，危险操作用 `danger`，次要命令用默认、plain、text 或 link；禁止页面再封装一套并行命令按钮。
- 纯图标操作统一使用 `AppIconButton`，默认 `md=32px / glyph=16px`，紧凑区用 `sm=28px / glyph=14px`，微型附属操作用 `xs=24px / glyph=12px`。所有纯图标操作必须提供可访问 `label`。
- 标准命令按钮为 `32px` 高、左右 padding `12px`、文字 `13px / --app-font-weight-section`、图文间距 `6px`；small 为 `28px`、large 为 `36px`。输入框、选择器、按钮统一使用 `--layout-control-radius=6px`，主题只改变颜色和材质，不改变基础控件形态。
- 同一页面主工作区原则上最多一个实体 `primary` 主按钮；页面工具栏先确定当前唯一主任务，其他并发命令使用默认、plain、warning、success、danger 等与动作含义一致的语义色，不用多个实体主按钮竞争。行级和列表项的轻量文字操作按 `AppRowActions` 的首个高频动作规则处理，不计作页面主按钮；危险色只用于删除、退出、停用、终止、标记退市等破坏性动作，不能用来制造普通视觉重点。
- 工作区按钮保持平面、清晰边界和轻状态反馈，不使用渐变、高光内阴影、厚重投影或装饰性位移。hover、focus-visible、disabled、loading 必须可辨；loading 使用 Element Plus `:loading`。
- 图标统一使用 Element Plus 图标或项目既有 SVG，同一区域保持相同描边气质；禁止用 `⚙`、`✕`、emoji 等 Unicode 字符充当界面图标。
- 纯图标异步操作必须使用 `AppIconButton` 的 `loading`，不得在页面内为图标按钮新增私有旋转动画或把 loading 混同为 disabled 灰态。外层 `el-tooltip` 承载完整说明时，应关闭 `AppIconButton` 原生 `title`，避免双提示。
- Unicode 禁令针对交互图标、操作按钮和纯图标控件；业务公式、状态文案里的箭头/对勾/叉号可作为局部文案保留，但不得用于按钮图标。选择态勾选标记也使用 Element Plus 图标或项目 SVG，不使用 Unicode 字形。
- 自定义原生 `<button>` 仅保留给导航、标签页关闭、登录主视觉切换等具有独立语义和结构的专用控件，并在实现中保持专用 class；普通命令和纯图标操作不得借此绕过统一组件。
- 夜间模式的复选框、单选框、输入边界和表格行悬浮必须使用强边框或主色反馈；空框、选中、禁用三态均需肉眼可辨。
- 工具栏按钮应贴近其影响区域，避免页面右上角堆积所有操作。
- 顶栏状态和工具按 `32px` 控件基线对齐、间距 `6px`。交易日等状态项使用“图标 + 弱标签 + 强值 + 5px 状态点”的轻量结构；无详情权限时使用只读 `role=status`，不得伪装成禁用按钮，也不得使用永久渐变、内阴影或大胶囊底板。

### 表格与列表

- 主数据表应作为 `growMain` 占据剩余空间，使用 `height="100%"` 让表体内部滚动。
- 表头保持稳定，分页、批量操作和关键筛选不被表体滚动带走。
- 不使用隔行变色作为默认识别手段；当前全局样式会取消 stripe 背景。
- 列宽按信息类型分配：编号、状态、日期、操作列稳定窄列；名称、标题、描述、备注更宽；数字列保持易比较。
- `data-table` / `wide-table` 的稳定字段只要支持排序，就必须同时支持列头直接排序和设置抽屉默认排序；分页表优先服务端排序，纯本地完整数据表可用 Element Plus 本地排序。
- `pageRegistry.componentMeta[slot].sortFields` 是可交互排序字段和默认排序候选的单一事实源；登记了 `sortFields` 的 slot 必须在 `consumedComponentFields` 消费 `defaultSort`，页面表格必须把对应列接入 `sortable` / `@sort-change`。
- 操作列、展开列、按钮列、开关列、多值标签组合列、长说明/详情文本列默认不排序；若业务需要排序，必须明确映射到稳定字段并登记到 `sortFields`。
- 操作列和列表项操作区优先单行可见；行内按钮组优先使用 `AppRowActions`，普通操作使用常规正文色，禁用操作降为弱文本色并满足语义 token 规则定义的文字层级阈值；hover / focus-visible 只做轻量文字色反馈，不对整组做透明度显隐；操作过多时用轻量“更多”菜单、分组、详情入口或抽屉，不用多行按钮堆叠；“更多”菜单不得引入重动画、布局跳动或遮挡表格内容，菜单命令仍消费 Element Plus 按钮的 disabled/loading 状态。
- 宽表通过表体横向滚动承载，不让整页横向滚动。

### 四态反馈总则

页面和组件的数据反馈统一按 `ready / loading / empty / error` 四态处理，代码枚举以 `frontend/src/layout/schema.ts` 的 `COMPONENT_STATES` 为事实源。文档、`COMPONENT_CATALOG.defaultStates`、`LayoutComponentPreview` 和页面实现必须使用同一语义，不新增“暂无/失败/加载中”的私有视觉体系。

| 状态 | 中文口径 | 使用场景 | 组件和图标 | 文案模板 |
|---|---|---|---|---|
| `ready` | 价值态 / 有数据态 | 接口或本地计算已返回可行动内容 | 不额外加状态图标；价值由表格、KPI、图表、详情、状态 tag 自身承载 | 标题或摘要写清范围、日期、数量、来源，例如“2026-07-10 · 预设榜单 · 320 条” |
| `loading` | 加载态 | 首次加载、刷新、保存、运行、远程下拉 | 区域用 `v-loading` 或 `el-skeleton`；按钮用 `:loading`；小型导航可用 Element Plus `Loading` 图标 | 页面级“正在加载{对象}…”，按钮级“{动作}中…”，下拉级“加载中…” |
| `empty` | 空态 | 请求成功但当前条件下没有可展示数据，或用户尚未完成前置选择 | 表格走全局 `el-table` 空态；非表格走 `el-empty.app-empty*`；很小区域走 `app-empty-inline` | “暂无{对象}”“请选择{对象}”“运行后在这里展示{结果}”“当前条件无命中” |
| `error` | 异常态 / 无权态 | 主请求失败、局部依赖失败、403/权限失败、详情读取失败 | 整区用 `el-result icon="warning"`；表格局部失败可用表内错误行；必须提供重试入口或说明不可重试原因 | “{对象}加载失败”+“请检查网络或稍后重试”；403 用“无权限{操作/查看对象}”+“请联系系统管理员调整权限” |

状态互斥与降级规则：

- 首次进入页面时，`loading` 不和 `empty` 同时出现；已有数据刷新时保留旧 `ready` 内容并覆盖 `v-loading`，避免闪回空态。
- `error` 不只依赖全局 toast；主内容、侧栏列表、详情面板、表格局部依赖失败时，失败区域必须留下页内错误态和“重试”或明确原因。
- 无权限是 `error` 的语义变体，运行时使用 `AppStateBlock state="error" variant="permission"`，不得扩展为第五种顶层状态。
- `empty` 表示“成功返回但无数据”，不能混用来表达接口失败、无权限或加载中。
- `ready` 必须呈现业务价值：至少有主体数据、摘要指标、当前过滤条件或来源说明之一；不要用大段说明文字替代真实数据展示。
- 四态切换不得改变外层 slot 的稳定尺寸；布局系统组件种类的 `loading-state`、`empty-state`、`error-state`、`skeleton` 只作为系统组件和预览语义，业务页面运行时优先复用真实组件和 Element Plus 状态能力。

### 空状态

空状态的视觉事实源在 `frontend/src/styles/global.css`，后续新页面必须复用同一套类名和全局表格空态，不允许临时手写不同图标、不同字号或不同位置。

- `el-table` 无数据时默认使用全局表格空态：居中图标 + 当前表格文案。新页面优先使用表格默认空态或 `<template #empty>` 只提供业务文案，不再自绘图标和布局。
- 非表格的大区域空态使用 `<el-empty class="app-empty" description="..." />`。
- 小面板、抽屉、弹窗内空态使用 `<el-empty class="app-empty app-empty--compact" description="..." />`。
- 很小的内嵌区域使用 `<el-empty class="app-empty app-empty--tiny" description="..." />`。
- 不适合放图标的原生小表格、日志区、选择器下拉空态使用 `class="app-empty-inline"`。
- 文案按业务场景保留差异，例如“运行后在这里展示筛选结果”“暂无历史版本”“请选择左侧角色”；统一的是图标、字号、颜色、间距和居中方式。
- 避免同一区域出现两套空态：若表格后面还需要自定义 `el-empty`，必须用 `v-if` 在有数据时才渲染表格，无数据时只渲染一套统一空态。

### 加载态与异常态

- 页面级初始化失败用 `el-result icon="warning"`，标题使用“{页面对象}加载失败”，副标题说明“请检查网络或稍后重试”，`#extra` 放一个主按钮“重试”。
- 局部依赖失败只阻断该区域，不阻断已可用的其他区域；例如主表可加载但摘要失败时，摘要区显示局部错误态，主表保持可用。
- 403 / 无权限态不能伪装为空态；标题使用“无权限查看{对象}”或“无权限维护{对象}”，副标题说明联系管理员或切换账号。
- 运行、保存、删除、发布等动作使用按钮 `:loading` 和禁用重复提交；动作失败用 `ElMessage.error`，若失败会影响当前区域继续使用，还要同步页内错误态。
- 远程选择器、懒加载下拉和日志区使用紧凑文案，不放大图标；下拉末尾可用“向下滚动加载更多”“无匹配结果”这类短句。

### 卡片、面板与分区

- 卡片只用于承载独立数据块、表格容器、设置组、弹层内容，不把页面 section 都做成浮动卡片。
- 卡片默认圆角 4px；设置抽屉和用户中心等浮层卡片可使用 12-16px。
- 卡片内 padding 默认 14-16px；高密表格容器可压缩，但不能牺牲可读性。

### 弹窗与抽屉

- 弹窗/抽屉必须放在 `#overlays` 插槽。
- 页面触发的抽屉必须使用 `PageDrawer`，遮罩和抽屉高度限制在当前 `LayoutHost` 内容区；只有应用顶栏触发的用户中心、外观等全局抽屉可以使用视口级浮层。
- Element Plus teleport 生成的浮层 DOM 必须使用唯一全局类或 `:global` 定位内部样式，不要依赖 scoped 深层样式碰运气。
- 普通 modal 用于确认、短表单、少字段编辑；宽表、长流程、跨模块设置优先 drawer、全屏弹窗或独立页面。
- 抽屉正文可以内滚，但外层页面不能跟随滚动；footer 或关键操作应保持稳定位置。

### 设置抽屉

- 页面设置抽屉三段**固定顺序**：`布局` → `组件设置` → `业务选项`；每段**仅在该页有对应内容时渲染**。`布局` 恒在，`组件设置` 仅当 registry 声明了可配置组件字段，`业务选项` 仅当页面提供 `#business` 插槽；不得为了形式完整强插空段。
- `布局` 和 `组件设置` 可由元数据自动渲染；`业务选项` 由页面声明，仅承载页面记忆或业务偏好。
- 设置项必须有默认值、来源展示、合法值域和重置路径；页面设置抽屉 footer 的「恢复默认」必须同时重置页面业务偏好、页面布局/组件用户层，以及抽屉自身 `size/defaultCollapsed` 用户偏好。
- 「组件设置」段与系统管理→布局配置→**页面布局**编辑器的「组件特性」**共用唯一渲染器** `components/ComponentAutoSettings.vue`（抽屉=user 层、页面布局编辑器=page 层，经 `layer`/`slotIds`/`allowedLayersOf`/`collapsibleSlot`/`clearable` 适配），不得另写第二套组件特性表单。
- 折叠规则统一：每个 slot 为可折叠组（`SettingsGroup` level 2；编辑器聚焦单 slot 时仅作标题锚点不折叠）；多行清单类特性（列显隐）为可折叠子组（level 3）；单字段为叶子不折叠。深层标题字号随层级递减但不低于正文。

## 5. Layout Principles

所有业务页面走可配置布局系统：页面声明 `PageLayout`，通过 `<LayoutHost>` 渲染，不手写 `.v-page` / `.v-grow` / 视口高度。配置合并顺序固定为：

`default < preset < page < user`

| 层 | 职责 | 维护入口 |
|---|---|---|
| `default` | 页面原型、slot、组件代码默认值 | `frontend/src/layout/pageRegistry.ts`、组件代码 |
| `preset` | 风格 token、预设级组件默认、响应式默认枚举 | 系统管理 → 布局配置 → 预设管理 |
| `page` | 单页面默认布局旋钮与组件默认值 | 系统管理 → 布局配置 → 页面布局 |
| `user` | 当前登录用户的布局、组件和业务偏好 | 页面设置抽屉；PG `layout_user_config`、PG `user_preference` |

用户层以 PostgreSQL 为权威：页面布局和组件字段写入真实 pageKey 的 `layout_user_config`，页面业务偏好、主题、导航模式、K 线偏好、回测参数记忆和跨页面设置抽屉偏好写入 `user_preference`。localStorage 只允许作为未登录/离线 fallback、旧偏好迁移源、登录前主题读取和临时交互态，不得作为登录用户配置权威。

### 5.1 新建或改造页面

新页面和布局改造必须先选择原型，再声明 slot、组件种类、滚动归属、`growMain` 和配置字段。优先使用脚手架生成骨架；需要手写时也必须从 `pageRegistry.ts` 的 `PageLayout` 单一事实源开始，不从旧页面复制临时 CSS。

```bash
cd frontend
npm run scaffold-page -- --pageKey <key> --label <中文名> --archetype <原型> --route /path --view XxxView
```

可复制流程、计划块和页面登记格式见 `agent-works/configurable-layout-system/page-template.md`。本文件只保留稳定原则、原型边界和机器登记区块。

### 5.2 页面设计闭环触发条件

涉及新页面，或改造既有页面的布局、组件、设置抽屉、表格、弹窗/抽屉、页面设置入口时，开发计划必须包含页面设计闭环。只改后端、接口、文案或不影响布局的业务逻辑时，计划中写明“不涉及前端页面设计闭环”。

页面设计闭环至少覆盖：页面定位、原型选择和理由、slot 与组件设计、四态反馈设计、配置层级、复用/新增判断、维护清单、测试与关键视口验收。声明新增布局原型、组件种类或组件配置字段时，必须同步给出维护清单。

### 5.3 原型清单与决策流程

| 原型 | 适用 |
|---|---|
| `list` | 筛选/批量 + 一张主表 |
| `master-detail` | 左列表 + 右详情，两栏各自内滚 |
| `dashboard` | KPI、图表、概览面板，平级块可安全重排 |
| `form` | 创建/编辑表单，字段区内滚，按钮稳定 |
| `detail` | 摘要、操作、分区详情 |
| `workbench` | 参数区固定 + 固定分析块 + 主表/主图成长区 |
| `wizard` | 步骤条 + 当前步骤内容 + 导航 |

决策顺序：

1. 有“操作 → 内容”上下级关系时，使用固定操作区 + 主内容区；否则按平级面板处理。
2. 数清主内容区组件数量、最低宽高和主成长组件。
3. 能放下时富余空间给主表/主图；放不下时按“组件内部滚动 → 满足条件才重排多列 → 主内容区整体滚动兜底”处理。
4. 单个大表不做多列重排，直接表体内滚。

### 5.4 主内容区策略

`LayoutHost` 根据 schema 自动选择主区策略：

| 策略 | 触发 | 行为 |
|---|---|---|
| `grow` | 单组件、非整区滚动型 | 主组件填满剩余空间，表体内滚 |
| `scroll` | 单组件整区滚动型 / 多组件无主成长组件 | 主内容区内部滚动 |
| `mixed` | 多组件且恰一个 `growMain` | 固定块自然高，主表/主图成长 |
| `columns` | 多组件且允许重排 | 容器宽度足够时多列，窄屏回退单列 |

## 6. Depth & Elevation

层级主要通过背景、边框、轻阴影和密度表达，不使用强装饰和多层浮动卡片。

| 层级 | 表达方式 | 使用场景 |
|---|---|---|
| 页面底 | `--el-bg-color-page` | 工作区背景 |
| 基础表面 | `--el-bg-color` / `--chrome-bg-soft` | 卡片、表格、输入框 |
| 分区表面 | `--el-fill-color-light` | KPI、提示条、配置组内部 |
| 浮层 | `--el-bg-color-overlay`、遮罩、边框 | dialog、drawer、popover |
| 强浮层 | `box-shadow: 0 10px 30px ...` | 页面设置抽屉、用户中心 |

规则：

- 默认卡片圆角 4px，控件圆角 4-6px，抽屉卡片可到 16px。
- 业务页面不通过多层阴影表达层级，优先用边框、间距、标题和背景差异。
- 弹窗遮罩保持轻压暗，不能让背景表格干扰当前任务。
- 高对比预设必须提高边框和文字对比，而不是仅加深背景。

## 7. Do's and Don'ts

### 7.1 必须遵守

- 所有 registry 业务页面必须走 `<LayoutHost>`。
- 新页面必须使用脚手架或 `pageRegistry.ts` 中的 `PageLayout` 单一事实源。
- 主数据区优先占据可用空间，表格表体内滚，分页和关键操作稳定展示。
- 所有滚动祖先保持 `min-height: 0`。
- 页面和主要组件必须声明 `ready / loading / empty / error` 四态处理；空态、错误态和加载态不得用彼此替代。
- 列表页分页/排序走服务端；筛选变更自动触发；多选跨分页/搜索累积。
- 列表页筛选下拉优先复用 `AppFilterSelect`；默认多选、可搜索、可清空，业务只允许单选时必须传 `multiple=false`，最多展示 3 个选中标签并在溢出时提前折叠，选择变更即向页面发出筛选事件，页面负责触发服务端查询。
- 普通命令使用 `el-button`，纯图标操作使用 `AppIconButton`；同一操作组只保留一个主按钮，并保持尺寸、图标和状态反馈一致。
- 页面主体字体、字号、行高、字重和间距必须优先消费 `global.css` 的 `--app-font-*`、`--app-line-height-*`、`--app-space-*` token 或 `.app-*` 语义类；新增 px 值必须属于文档允许的局部特例。
- 说明性/描述性文字只要不是极短标签或必要操作指引/实时状态说明，收进 `HelpTip` / `HelpHint`。
- 新增可配置能力必须同时具备组件能力事实源、字段配置事实源、页面消费事实源。

### 7.2 禁止事项

- 禁止使用 `height: calc(100vh - Npx)` 或等价视口硬编码高度。该规则由 `layout-contract.spec.ts` 扫描 `src/views` 强制。
- 禁止绕过 `LayoutHost` 手写 `.v-page` / `.v-grow` / `.v-scroll` 页面外壳。
- 禁止新增页面不读取的“假配置”。
- 禁止预设改变页面业务结构、slot、原型或任意 CSS。
- 禁止复杂表格、批量操作、长流程录入塞进普通小弹窗。
- 禁止所有列平均等宽；列宽必须跟信息类型匹配。
- 禁止页面 section 全部做成浮动卡片，只有独立重复项、工具面板或弹层内容适合卡片。
- 禁止让 tooltip、popover、说明提示溢出到左侧菜单。
- 禁止接口失败只弹 toast 后留下空白区域；失败区域必须有可见错误态。
- 禁止把 403、接口错误或未加载完成写成“暂无数据”。
- 禁止页面为普通命令另写原生按钮皮肤，禁止用 Unicode / emoji 代替图标，禁止顶栏状态项使用永久渐变、内阴影或悬浮胶囊制造层级。
- 禁止新增未登记的普通文字字号、游离字体族和随机间距；禁止把登录页、品牌字标、图表 tooltip 的特殊排版复制到业务页面。

### 7.3 组件特性配置治理

组件配置路径固定为：

`slots.<slotId>.config.<field>`

字段事实源为 `COMPONENT_FIELD_DEFS`。只登记页面真实消费的字段，不预设无消费项。新增字段必须同时满足：

- 字段在 `COMPONENT_FIELD_DEFS` 中声明 label、control、layers、默认值和值域。
- `componentSchemas.ts` 接受该字段。
- 后端 `layout_config.py` 同步字段规则和归属校验。
- 消费页面在 `pageRegistry.consumedComponentFields` 登记。
- 页面通过 `componentMeta` 提供安全枚举（列、可交互排序字段、tabs 等）。
- 页面实际读取并应用字段值。
- 配置中心和设置抽屉可按层级渲染。
- 测试覆盖合并、越权、类型和值域。

当前受控字段摘要：

下表只记录字段和开放层级；消费页面、slot、候选列、排序字段和 tab 项不在 DESIGN 手写维护，统一以 `pageRegistry.consumedComponentFields`、`componentMeta` 和 `COMPONENT_FIELD_DEFS` 为准。`data-table` / `wide-table` 的 `border` 由 `pageRegistry.ts` 对所有表格 slot 自动补登，并由 `pageRegistry.spec.ts` 校验真实页面接入。

| 组件 | 字段 | 层级 | 归属事实源 |
|---|---|---|---|
| `data-table` | `border` | page | 全部 `data-table` slot 自动补登；页面需实际消费 `tableBorder(slotId)` |
| `data-table` | `pageSize` | preset/page/user | 消费 slot 以 `pageRegistry.consumedComponentFields` 为准 |
| `data-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `data-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `wide-table` | `border` | page | 全部 `wide-table` slot 自动补登；页面需实际消费 `tableBorder(slotId)` |
| `wide-table` | `pageSize` | preset/page/user | 消费 slot 以 `pageRegistry.consumedComponentFields` 为准 |
| `wide-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `wide-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `tabs` | `defaultActive` | page/user | 仅在页面登记 tabs slot 且 `componentMeta.tabs` 提供候选时渲染 |
| `settings-drawer` | `size`、`defaultCollapsed` | preset/page/user | 全部 registry 页面共享 `settings` overlay slot |
| `settings-drawer` | `bodyScroll`、`collapsibleSections` | preset/page | 全部 registry 页面共享 `settings` overlay slot |
| `config-panel` | `collapsibleSections` | preset/page | `config-system.configPanel` |
| `config-panel` | `defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | preset/page/user | `config-system.configPanel`；分区候选以 `componentMeta.collapseSections` 为准 |

`usePageSettings` 只保留页面业务态/页面记忆，不承载通用组件展示能力。
`settings-drawer` 的用户层只允许 `size/defaultCollapsed`；跨页面个人值写入 `user_preference(global/settings-drawer)`，不写伪页面的 `layout_user_config`。`bodyScroll/collapsibleSections` 只能由 preset/page 层控制。

### 7.4 页面 / 组件 / 布局变更维护闭环

具体维护矩阵、计划块和验收命令统一维护在 `agent-works/configurable-layout-system/page-template.md`。本节只保留长期规则：

- 页面、布局原型、系统组件种类、组件字段、真实复用组件、按钮图标体系或业务偏好发生变化时，必须同步对应代码事实源、页面消费事实源、文档入口和测试。
- DESIGN 只维护稳定设计规则、组件关系、字段治理原则和机器读取的页面登记 marker；不展开可复制流程和命令清单。
- `page-template.md` 是执行清单；如它与本文件或布局测试冲突，优先修正模板或代码事实源，不在 DESIGN 复制第二套矩阵。

### 7.5 自动化测试锚点

关键点击链路允许使用 `data-testid` 作为测试锚点，但只服务自动化测试，不表达样式或业务状态。

- 自动化测试流程、Playwright 与交互式浏览器工具的适用边界，以 `agent-works/e2e-automation/guide.md` 为入口；本节只约束 UI 组件如何提供稳定锚点。
- 必须加锚点的对象：页面级入口按钮、抽屉/弹窗容器、提交/重置/删除等关键命令、分段控件中会被 E2E 断言的选项。
- 不给普通文本、布局装饰、一次性容器批量加锚点；能通过稳定复用组件承载时，不在页面私有 DOM 上重复加。
- 复用组件提供可选 `testId` 时，页面或配置渲染器只在需要 E2E 覆盖的关键实例上传入。
- Playwright E2E 优先用 `getByTestId` 和项目 helper；临时浏览器复核可以用可见文本定位，但不能把脆弱定位沉淀成长期用例。

## 8. Responsive Behavior

当前项目主要面向桌面端本地工作台，仍必须保证低高度和常见桌面宽度下可用。

| 视口 | 规则 |
|---|---|
| `1100×620` | 页面不得整页滚动；固定区保持可用，主内容区内部滚动 |
| `1366×768` | 主操作、状态列、时间列、核心业务列优先可见；次要说明列截断或进详情 |
| `1440×900` | 默认桌面验收视口；表格、抽屉、工作台应无重叠和无文本溢出 |
| `1920×1080` | 不无限拉宽说明文本；宽屏富余给主表、主图或多列概览 |

响应式原则：

- 响应式配置必须有 `minWidth=0` 的基础断点。
- 单个大表、大图、大列表不靠多列重排解决高度问题，优先内部滚动。
- 多组件平级块只有在都允许重排、无强阅读顺序且最小宽度满足时才进入 `columns`。
- `workbench` 类页面采用固定分析块 + 主成长区，放不下时由主区域兜底滚动。
- 抽屉宽度使用受控档位：`sm=320px`、`md=360px`、`lg=440px`。
- 弹窗和抽屉允许 `max-height` 作为视口安全上限，但不能用视口高度驱动页面主体布局。

## 9. AI 开发入口

本节只做入口，不维护可复制 prompt、计划块或验证命令。新增或改造前端页面时，固定流程、页面设计闭环、维护清单、页面登记模板和验收命令统一维护在 `agent-works/configurable-layout-system/page-template.md`。

执行边界：

- 凡涉及新增或改造前端页面、布局、组件配置、抽屉、表格、样式或交互表现，必须先读取并执行 `agent-works/configurable-layout-system/page-template.md`；未在计划或回复中明确该入口和适用结论，视为执行不完整。
- 设计规则以本文件 §1~§8 为准；代码事实以 `frontend/src/layout/`、`frontend/src/components/`、`frontend/src/styles/global.css` 和后端 layout 校验为准。
- 页面原型、slot、滚动归属、`growMain`、组件字段和页面登记按 `page-template.md` 执行。
- 新增组件字段必须回到 §7.3 的字段治理闭环，不在 prompt 或计划里临时声明第二套配置口径。
- 如 `page-template.md` 与本文件或布局测试冲突，优先修正下游模板，不在 DESIGN 复制流程细节。

### Page Registry Index

该区块只作为机器读取和轻量人工索引，不承载组件字段、slot 配置、列、排序或业务状态事实源。新增 registry 页面必须写入 `pageRegistry.ts` 并出现在下方 marker 内；`pageRegistry.spec.ts` 和 `scaffold-page` 会读取此区块。

<!-- page-registry:start -->
| 页面 | 原型 | 可编辑旋钮 | 组件清单 |
|---|---|---|---|
| `BoardView`（每日榜单） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `ScreenView`（策略筛选） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `StocksView`（个股查询） | `list` | `density` | action:`filter-bar` / main:`data-table` / nested:`data-table` / footer |
| `QualityView`（数据质量） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `ScheduleView`（任务调度） | `detail` | `density` | action:`toolbar` / main:`section` |
| `IngestView`（数据采集） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `OverviewView`（数据概览） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `BacktestView`（策略回测） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` |
| `TrainingView`（盘感训练） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `StockDetailView`（个股详情） | `detail` | `density` | action:`toolbar` / main:`detail` |
| `ConfigView`（评分规则） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `ConfigView`（买卖指标） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `ConfigView`（技术指标） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `ConfigView`（系统设置） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `UserManageView`（用户管理） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `RoleManageView`（角色管理） | `list` | `density` | action:`toolbar` / main:`section` |
| `MenuResourceView`（菜单与功能） | `list` | `density` | action:`toolbar` / main:`section` |
| `TenantManageView`（租户管理） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `LayoutPresetsView`（预设管理） | `list` | 暂无 | action:`toolbar` / main:`section` |
| `LayoutPagesView`（页面布局） | `list` | 暂无 | action:`toolbar` / main:`section` |
| `LayoutComponentsView`（系统组件） | `list` | 暂无 | action:`toolbar` / main:`section` |
| `AuditLogView`（审计日志） | `list` | `density` | action:`toolbar` / main:`kpi-grid` / main:`filter-bar` / main:`wide-table` / overlay:`detail` |
| `DataDictionaryView`（数据字典） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`simple-list` / nested:`data-table` / overlay:`form` / overlay:`dialog` |
<!-- page-registry:end -->

全部 registry 页面必须有 `settings-drawer` overlay slot。组件字段、slot 细节和候选项事实源在 `COMPONENT_FIELD_DEFS`、`pageRegistry.consumedComponentFields` 和 `componentMeta`，不要在本表重复维护。

## 10. Scope & Exceptions

- 本项目桌面工作台优先；响应式规则覆盖低高度和常见桌面宽度，移动端不是当前验收重点。
- 当前没有独立品牌设计稿；视觉方向以本文件的金融科技研究终端规则和现有品牌组件为准。
- 品牌字标、登录主视觉、图表 tooltip、代码值和极窄 badge 允许局部排版特例；新增业务页面不得复制这些特例作为普通排版。
- 页面登记区块通过 `<!-- page-registry:start/end -->` marker 被 `pageRegistry.spec.ts` 和 `scaffold-page` 读取；marker 是机器契约，不要移除。
