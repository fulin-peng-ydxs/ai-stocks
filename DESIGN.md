---
version: alpha
name: 复盘啦
description: 本地单用户 A 股趋势龙头研究系统，面向高密度行情、筛选、回测、训练和数据管理工作流，采用克制、可配置、可验证的专业后台界面。
colors:
  primary: "#409eff"
  secondary: "#0891b2"
  background: "#f5f7fa"
  surface: "#ffffff"
  surface-hover: "#eef1f6"
  text-primary: "#1f2937"
  text-regular: "#4b5563"
  text-secondary: "#8a94a6"
  border: "#e4e7ed"
  border-strong: "#d0d5dd"
  success: "#2f9e44"
  warning: "#d97706"
  danger: "#dc2626"
typography:
  heading-lg:
    fontFamily: "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif"
    fontSize: 22px
    fontWeight: 700
    lineHeight: 30px
  heading-md:
    fontFamily: "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif"
    fontSize: 18px
    fontWeight: 650
    lineHeight: 26px
  body-md:
    fontFamily: "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 22px
  label-sm:
    fontFamily: "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 18px
rounded:
  xs: 2px
  sm: 4px
  md: 6px
  lg: 8px
  drawer: 16px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
components:
  app-shell:
    sidebarWidth: 208px
    topbarHeight: 67px
    mainPadding: "20px 24px"
  card-default:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.sm}"
    padding: 16px
  control-default:
    borderColor: "{colors.border}"
    rounded: "{rounded.md}"
  data-table:
    cellPaddingY: 10px
    headerTextColor: "{colors.text-primary}"
    bodyTextColor: "{colors.text-regular}"
  page-settings-drawer:
    rounded: "{rounded.drawer}"
    bodyWidth: "320px / 360px / 440px"
---

# 复盘啦 Design System

> 本文是前端页面、视觉样式、布局系统、组件配置和 AI 开发流程的长期事实源。强制规则在 `frontend/src/layout/`、后端 layout 配置校验和 `frontend/src/layout/__tests__/` 中；本文负责说明如何选型、如何接入、如何维护，以及哪些视觉和交互规则不能漂移。

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

## 1. Visual Theme & Atmosphere

复盘啦是高密度金融研究工作台，不是营销页或内容站。界面优先支持反复扫描、比较、筛选、回测和配置，视觉应当安静、克制、可读，避免装饰性布局占用业务空间。

Key Characteristics：

- 信息密度偏高，但通过表格内滚、抽屉分段、字段收纳和提示悬浮保持可扫读。
- 默认气质为中性蓝灰专业后台；金融数据场景允许红绿涨跌色和更紧凑密度。
- 页面首屏直接呈现业务工具，不做大 hero、不做营销式空白、不做卡片堆叠式装饰。
- 所有业务页面通过布局系统组织，页面结构由 schema 和测试约束，不依赖临时 CSS 猜高度。
- 视觉预设可以改变 token、密度和受控组件默认策略，但不能改变页面业务结构。

## 2. Color Palette & Roles

颜色以 Element Plus 变量、`global.css` 的 `--chrome-*` / `--page-settings-*` 变量和 `LAYOUT_PRESETS` 为事实源。默认预设为 `professional`，同时支持 `government`、`technology`、`finance`、`high-contrast`。

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

预设规则：

- `professional`：默认后台风，适合绝大多数管理和研究页面。
- `government`：更低圆角、更强边界，适合稳重场景。
- `technology`：青蓝高亮，适合行情分析和图表工作台。
- `finance`：更紧凑、更表格化，适合高频数据比较。
- `high-contrast`：提高文字与边框对比，优先保证可访问性。
- 新增或调整预设必须维护 `light`、`dark`、共享形态 token，并通过 `presets.spec.ts`。

## 3. Typography Rules

字体栈以系统中文字体为主：`PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif`。不得引入需要联网加载的字体。

| 层级 | 建议值 | 使用场景 |
|---|---|---|
| 页面标题 | 20-22px / 700 | 页面主标题、工作台名称 |
| 分区标题 | 15-18px / 600-650 | 卡片标题、抽屉标题、配置组标题 |
| 正文 | 14px / 400 | 表单、普通说明、主体内容 |
| 表格正文 | 13-14px / 400 | 数据表格、列表 |
| 辅助标签 | 12px / 400 | 单位、提示、来源、次级说明 |
| 数字强调 | 16-20px / 600-700 | KPI、收益、评分、排名 |

排版规则：

- 标题用于定位页面和分区，不用于装饰性大字。
- 表格内长文本默认省略、tooltip 或详情承接，不默认自动换行撑高行高。
- 说明性长文优先进入 `HelpTip` / `HelpHint`，页面上只保留必要短标签。
- 按钮、标签、抽屉标题、表格控件中的文字不得溢出容器。
- 金融数字按列右对齐或按业务组件一致处理，避免同列数字参差。

## 4. Component Stylings

组件样式基于 Element Plus 和项目 token，不另建并行组件库。新增组件先判断能否复用 Element Plus、项目已有基础组件和 `frontend/src/layout/components.ts` 中的组件能力目录。

### 应用外壳

- 侧栏宽度固定为 `208px`，顶栏高度 `67px`，主工作区 padding 为 `20px 24px`。
- `.main` 必须保持 `overflow: hidden` 和 flex 填充；页面滚动由布局系统内部区域承载。
- 菜单激活态使用主色边线和轻背景，不使用大面积高饱和底色。

### 按钮与输入

- 主命令用 Element Plus `primary`，危险操作用 `danger`，普通工具用默认或 plain。
- 输入框、选择器、按钮统一使用 `--layout-control-radius`，默认 4-6px。
- 图标按钮优先使用图标或现有组件，不要用冗长文字按钮替代明确符号。
- 工具栏按钮应贴近其影响区域，避免页面右上角堆积所有操作。

### 表格与列表

- 主数据表应作为 `growMain` 占据剩余空间，使用 `height="100%"` 让表体内部滚动。
- 表头保持稳定，分页、批量操作和关键筛选不被表体滚动带走。
- 不使用隔行变色作为默认识别手段；当前全局样式会取消 stripe 背景。
- 列宽按信息类型分配：编号、状态、日期、操作列稳定窄列；名称、标题、描述、备注更宽；数字列保持易比较。
- 操作列优先单行可见；操作过多时用分组、下拉、详情入口或抽屉，不用多行按钮堆叠。
- 宽表通过表体横向滚动承载，不让整页横向滚动。

### 卡片、面板与分区

- 卡片只用于承载独立数据块、表格容器、设置组、弹层内容，不把页面 section 都做成浮动卡片。
- 卡片默认圆角 4px；设置抽屉和用户中心等浮层卡片可使用 12-16px。
- 卡片内 padding 默认 14-16px；高密表格容器可压缩，但不能牺牲可读性。

### 弹窗与抽屉

- 弹窗/抽屉必须放在 `#overlays` 插槽。
- Element Plus teleport 到 body 的内部样式必须使用唯一全局类或 `:global`，不要依赖 scoped 深层样式碰运气。
- 普通 modal 用于确认、短表单、少字段编辑；宽表、长流程、跨模块设置优先 drawer、全屏弹窗或独立页面。
- 抽屉正文可以内滚，但外层页面不能跟随滚动；footer 或关键操作应保持稳定位置。

### 设置抽屉

- 页面设置抽屉固定三段：`布局`、`组件设置`、`业务选项`。
- `布局` 和 `组件设置` 可由元数据自动渲染；`业务选项` 由页面声明，仅承载页面记忆或业务偏好。
- 设置项必须有默认值、来源展示、合法值域和重置路径。
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
| `user` | 当前用户/本机展示偏好 | 页面设置抽屉，localStorage `ai-stocks:layout:*` / `ai-stocks:layout-cc:*` |

### 5.1 新建一个页面

新页面开发已闭环：脚手架、原型选择、`pageRegistry`、`LayoutHost`、设置抽屉三段、组件字段消费登记、DESIGN 登记、契约测试和构建校验均已具备。

1. 判断业务页面类型，用 §5.3 选择一个原型。
2. 向用户说明推荐原型、组件清单和理由，关键方案确认后开发。
3. 优先运行脚手架：

```bash
cd frontend
npm run scaffold-page -- --pageKey <key> --label <中文名> --archetype <原型> --route /path --view XxxView
```

4. 模板使用 `<LayoutHost :layout="effective">` + 具名插槽填业务组件：`#action`、`#main`、按 `slot.id` 命名的主区插槽、`#footer`、`#overlays`。
5. 页面设置抽屉使用 `PageSettingsDrawer`，保持“布局 / 组件设置 / 业务选项”三段。
6. 运行 `cd frontend && npm test` 和 `cd frontend && npm run build`。
7. 在 §9 登记页面原型、组件清单和可编辑旋钮。

样板参考：`frontend/src/views/BoardView.vue`。可复制模板见 `agent-works/configurable-layout-system/page-template.md`。

### 5.2 开发计划必须包含的页面设计闭环

涉及新页面，或改造既有页面的布局、组件、设置抽屉、表格、弹窗/抽屉、页面设置入口时，开发计划必须包含下列内容。只改后端、接口、文案或不影响布局的业务逻辑时，计划中写明“不涉及前端页面设计闭环”。

| 计划项 | 必填内容 |
|---|---|
| 页面定位 | 页面类型、用户主流程、新页面或改造页面 |
| 布局选型 | 选用原型、选择理由、是否需要新增布局原型 |
| Slot 与组件设计 | `region`、`slotId`、组件种类、`growMain`、滚动归属、是否可重排、业务说明 |
| 配置设计 | 布局旋钮、组件设置、页面记忆分别落在哪一层和哪个字段 |
| 复用与新增判断 | 复用哪些布局/组件；是否新增组件种类、组件配置字段或页面业务态 |
| 维护清单 | 是否同步 `pageRegistry`、组件目录、字段元数据、后端规则、预览、DESIGN 登记和测试 |
| 验收项 | `npm test`、`npm run build`、关键视口验证、无整页滚动与设置抽屉检查 |

计划声明“新增布局原型 / 组件种类 / 组件配置字段”但没有维护清单时，计划不完整。

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
- 列表页分页/排序走服务端；筛选变更自动触发；多选跨分页/搜索累积。
- 说明性/描述性文字只要不是极短标签或必要操作指引，收进 `HelpTip` / `HelpHint`。
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

### 7.3 组件特性配置治理

组件配置路径固定为：

`slots.<slotId>.config.<field>`

字段事实源为 `COMPONENT_FIELD_DEFS`。只登记页面真实消费的字段，不预设无消费项。新增字段必须同时满足：

- 字段在 `COMPONENT_FIELD_DEFS` 中声明 label、control、layers、默认值和值域。
- `componentSchemas.ts` 接受该字段。
- 后端 `layout_config.py` 同步字段规则和归属校验。
- 消费页面在 `pageRegistry.consumedComponentFields` 登记。
- 页面通过 `componentMeta` 提供安全枚举（列、排序字段、tabs 等）。
- 页面实际读取并应用字段值。
- 配置中心和设置抽屉可按层级渲染。
- 测试覆盖合并、越权、类型和值域。

当前已接入字段：

| 组件 | 字段 | 层级 | 消费 |
|---|---|---|---|
| `data-table` | `defaultSort` | page/user | board、screen、data-quality、stocks、backtest |
| `data-table` | `hiddenColumns` | page/user | board、screen、data-quality、stocks、backtest |
| `data-table` | `pageSize` | preset/page/user | stocks 普通列表 |
| `tabs` | `defaultActive` | page/user | config |
| `settings-drawer` | `size`、`bodyScroll`、`defaultCollapsed` | preset/page/user | 全部 registry 页面 |
| `settings-drawer` | `collapsibleSections` | preset/page | 全部 registry 页面 |

`usePageSettings` 只保留页面业务态/页面记忆，不承载通用组件展示能力。

### 7.4 页面 / 组件 / 布局变更维护闭环

| 变更类型 | 必须同步维护 | 必须验证 |
|---|---|---|
| 新页面 | 脚手架、`pageRegistry.ts`、`router/index.ts`、`DESIGN.md §9` | `pageRegistry.spec.ts`、`layout-contract.spec.ts`、build、关键视口 |
| 新布局原型 | `archetypes.ts`、`schema.ts`、`validator.ts`、`LayoutHost.vue`、DESIGN 原型说明 | `validator.spec.ts`、布局契约测试 |
| 新组件种类 | `COMPONENT_CATALOG`、`componentSchemas.ts`、`componentPreview.ts`、系统组件页展示 | `componentPreview.spec.ts`、`pageRegistry.spec.ts` |
| 新组件配置字段 | `COMPONENT_FIELD_DEFS`、`componentSchemas.ts`、后端 `layout_config.py`、页面真实消费、DESIGN 字段表 | `componentConfig.spec.ts`、后端 layout 测试、保存/回显验证 |
| 页面消费已有字段 | `pageRegistry.consumedComponentFields`、`componentMeta`、页面读取/写入逻辑 | `pageRegistry.spec.ts`、页面交互验证 |
| 纯业务偏好 | `usePageSettings` / 页面业务态，放入「业务选项」并标注「页面记忆」 | 业务行为验证、必要时 build |

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

## 9. 已迁移页面登记

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
| `ConfigView`（配置管理） | `workbench` | `density` | action:`toolbar` / main:`tabs` |
| `LayoutPresetsView`（预设管理） | `list` | 暂无 | action:`toolbar` / main:`section` |
| `LayoutPagesView`（页面布局） | `list` | 暂无 | action:`toolbar` / main:`section` |
| `LayoutComponentsView`（系统组件） | `list` | 暂无 | action:`toolbar` / main:`section` |

全部 registry 页面必须有 `settings-drawer` overlay slot。新增页面必须出现在本节，否则 `pageRegistry.spec.ts` 失败。

## 10. Agent Prompt Guide

后续 AI 新增或改造前端时，按以下提示执行：

- 先读本文件、`frontend/src/layout/pageRegistry.ts`、`frontend/src/layout/components.ts` 和相关样板页面。
- 先判断页面原型，再列 slot、组件种类、滚动归属、`growMain` 和配置字段。
- 需要新页面时优先用 `npm run scaffold-page`，不要复制旧页面临时改 CSS。
- 如果新增配置项，必须写清谁定义、谁保存、谁读取、谁消费、谁校验、如何回退。
- 如果改表格，必须说明列宽、长文本、排序/分页、操作列和低宽度降级。
- 如果改弹窗/抽屉，必须说明承载边界、滚动归属、teleport 样式入口和关闭策略。
- 改完前端必须运行 `cd frontend && npm test` 和 `cd frontend && npm run build`。

Example Component Prompts：

- “新增一个列表页：使用 `list` 原型，action 为筛选工具栏，main 为 `data-table(growMain)`，表体内滚，页面设置抽屉包含布局和表格列设置。”
- “改造一个工作台：使用 `workbench` 原型，action 固定参数区，main 为 `section`，内部固定摘要块 + 主图/主表成长区。”
- “新增组件配置字段：先在字段事实源登记，再同步 schema、后端规则、页面消费、设置抽屉、配置中心和测试。”

## 11. Known Gaps

- 本文件已补齐设计系统入口，但视觉 token 仍以当前代码事实为主，未引入独立设计稿或品牌规范。
- 移动端不是当前产品重点，当前响应式规则优先覆盖桌面低宽度和低高度场景。
- 仍有部分页面局部样式带有业务特例颜色或局部 class，后续如要统一视觉，应逐页复核后再沉淀为 token。
- `DESIGN.md §9` 被 `pageRegistry.spec.ts` 读取，标题和页面登记表是测试契约，不要随意改名或移除。

## 12. 验收命令

```bash
cd frontend
npm test
npm run build
```

重点测试：

- `layout-contract.spec.ts`：禁止视口硬编码高度、禁止手写布局类。
- `pageRegistry.spec.ts`：页面登记、settings overlay、组件消费字段一致性。
- `componentConfig.spec.ts`：字段元数据、分层合并、越权/非法值守门。
- `validator.spec.ts`：原型、尺寸、滚动、重排、editable path。
- `presets.spec.ts`：预设 token 和明暗对比。
- `responsive.spec.ts`：响应式摘要和档位策略。
