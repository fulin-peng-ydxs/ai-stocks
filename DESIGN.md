---
version: alpha
name: 复盘啦
description: A 股趋势研究工作台，面向高密度行情、筛选、回测、训练、权限管理和数据治理工作流，采用明亮蓝色信号、中性明暗表面和可验证的专业后台界面。
typography:
  button-md:
    fontWeight: 600
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

复盘啦是专业金融研究空间，不是传统后台、营销页或内容站。界面优先支持反复扫描、比较、筛选、回测和配置，以高辨识蓝色信号、中性黑白表面和清晰层级保持明亮、现代的金融科技气质。

Key Characteristics：

- 信息密度偏高，但通过表格内滚、抽屉分段、字段收纳和提示悬浮保持可扫读。
- 默认气质为明亮、清晰的金融科技研究终端；主交互蓝保持鲜明，不通过低饱和暖灰、金棕或泛黄底色营造所谓护眼感。**亮色模式一切信号色（成功/警告/危险/金融涨跌/状态与评分文本）走提彩提亮、与主交互蓝同亮档，禁止 dark-2 式向黑收敛或 blend 向白稀释造成的哑光/发灰。**金融数据场景允许红绿涨跌色，但不以过度紧凑和控件堆叠表达专业。
- 明暗模式缩略图、外观预览和装饰性状态图形也必须使用冷白、亮蓝、深蓝与中性灰；不得用金黄、棕灰或泛黄色模拟“白天”，避免预览层与真实页面色彩语言脱节。
- 页面首屏直接呈现业务工具，不做大 hero、不做营销式空白、不做卡片堆叠式装饰。
- 所有业务页面通过布局系统组织，页面结构由 schema 和测试约束，不依赖临时 CSS 猜高度。
- 视觉预设可以改变 token、密度和受控组件默认策略，但不能改变页面业务结构。

## 2. Color Palette & Roles

颜色以 Element Plus 变量、`global.css` 的 `--chrome-*` / `--page-settings-*` 变量和 `LAYOUT_PRESETS` 为事实源。**金融涨跌色（`--market-up-color` / `--market-down-color`）与状态/评分文本色（`--app-warning-text` / `--app-danger-text` / `--score-high-*` / `--score-mid-*`）唯一事实源是 `LAYOUT_PRESETS` 的 `marketUp` / `marketDown` / `success` / `warning` / `danger` token，由 `useLayoutPreset.applyPreset()` 统一写入，禁止在 `global.css`、页面或组件内平行硬编码第二套色值（含 Element/AntD 默认蓝绿橙红）。**内置视觉只保留 `balanced` 一个稳定 key，对外名称为“澄空蓝”；历史内置项统一迁移到该默认项。预设管理仍可新增自定义预设，启用项会自动进入外观抽屉并真实驱动强调色、形态和组件默认策略。

| 角色 | 默认值 | 使用规则 |
|---|---:|---|
| 主交互色 | 白天 `#1677ff` / 夜间 `#3b8cff` | 主按钮、当前菜单、可点击强调、选中边框 |
| 页面背景 | 白天 `#ffffff` / 夜间 `#171717` | 对齐参考原型主区；工作区与登录页统一画布，只受明暗模式控制 |
| 边栏背景 | 白天 `#fcfcfc` / 夜间 `#1f1f1f` | 对齐参考原型侧栏；固定中性表面，不随预设强调色变化 |
| 表面色 | 白天 `#ffffff` / 夜间 `#171717` | 卡片、表格、输入框、抽屉内容面；与同模式页面背景连续，避免主体区域出现无业务意义的色块断层，不随预设变化 |
| 悬停表面 | 白天 `#f3f3f3` / 夜间 `#292929` | 菜单、表格行、轻量按钮 hover |
| 主文字 | 白天 `#17181c` / 夜间 `#f4f4f4` | 标题、表头、关键字段 |
| 正文文字 | 白天 `#44464d` / 夜间 `#d2d2d2` | 表格正文、表单值、说明正文 |
| 次要文字 | 白天 `#73757d` / 夜间 `#9a9a9a` | 提示、辅助说明、弱化信息 |
| 边框 | 白天 `#e5e5e5` / 夜间 `#353535` | 卡片、表格、分割线、输入框 |
| 强边框 | 白天 `#c9c9c9` / 夜间 `#545454` | 选中、强调分区、高对比控件 |
| 成功 | 白天 `#0ea968` / 夜间 `#3ecf8e` | 健康状态、成功提示、评分高档 |
| 警告 | 白天 `#f58a07` / 夜间 `#f5a623` | 异常但未失败、样本不足、风险提示、评分中档 |
| 危险 | 白天 `#f04438` / 夜间 `#ff6b66` | 失败、删除、风险 |
| 金融上涨 | 白天 `#f66055` / 夜间 `#ff7a72` | 涨/正收益；感知亮度恒高于危险红一档，区分金融与主体语义 |
| 金融下跌 | 白天 `#1ec96e` / 夜间 `#3fdd90` | 跌/负收益；感知亮度恒高于成功绿一档 |

金融涨跌色遵循当前项目口径：上涨/正收益多用红色，下跌/负收益多用绿色；不要套用海外红跌绿涨习惯。**金融色（`marketUp`/`marketDown`）与同名主体信号色（`danger`/`success`）是两个独立 token：金融色更鲜亮（亮色模式感知亮度约高 25%~47%），用于涨跌数据、K线、净值等金融语境；主体信号色用于状态、提示、评分档。二者不得互相替代或合并。**

语义 token 规则：

- 权限树颜色使用 `--perm-group-color`、`--perm-feature-color`；菜单点使用 Element Plus 成功色，不在页面内写死色值。
- 金融涨跌使用 `--market-up-color` / `--market-down-color`，不要在页面里直接写红绿 hex。
- `StockChartWorkspace` 及个股详情股票画布通过 `stock-chart/chartUtils.ts::stockChartTheme()` 读取 CSS 语义色；该工作区的 MACD 正柱与金叉使用 `--market-up-color`，负柱与死叉使用 `--market-down-color`。交叉事件使用贴近当日 DIFF 点的“金叉/死叉”标签表达，标签只保留连接事件点的短三角指针，不显示贯穿面板的长引导线或独立圆形锚点；不得只依赖红绿颜色，也不为金叉新增独立金色 token。信号标签使用主题中性表面和高对比中性文字，方向色只用于轮廓和短指针；信号 item 悬停必须显示类型与完整交易日期。
- 股票 MA/VMA/MACD 折线的序列身份色统一以 `stock-chart/chartUtils.ts::trainingChartSeriesPalette()` 为事实源：MA5/VMA5/DIFF 使用橙色 `#e28a35`，MA10/VMA10/DEA 使用蓝色 `#418af5`，MA20 浅色使用洋红 `#9f3793`、暗色使用 `#c53c92`，MA30 使用青色 `#56c3df`，MA60 使用橙红 `#e56023`。K线和量能均线的周期、标题、ECharts 名称与色板键分别由 `KLINE_MA_DEFINITIONS`、`VOLUME_MA_DEFINITIONS` 唯一声明，序列、有数据标题和空数据标题必须共同消费，不得复制周期数组、标签映射或颜色。盘感训练、回测和个股详情必须共同消费该色板；序列色只表达指标身份，不表达涨跌方向。K 线 tooltip 的收盘与涨幅才按相对昨收使用涨跌色，平盘保持中性。
- `StockChartWorkspace` 与兼容 `CandleChart` 的 Canvas 不会随 CSS 变量自动重绘；两者必须只通过 `stock-chart/useStockChartTheme.ts::useStockChartTheme()` 消费响应式股票画布主题，不得分别组合 `useTheme`、`useLayoutPreset`、`themeRevision` 和 `stockChartTheme()`。该入口统一覆盖明暗切换、预设 key 切换和当前预设同 key 后端覆盖更新。本条适用于个股详情、盘感训练和回测的股票画布；其它图表不会自动继承，扩大适用范围时必须同步完成运行时改造和独立回归。
- 非股票 ECharts 统一通过 `components/chartTheme.ts::useEChartsTheme()` 消费画布背景、坐标、文字、tooltip 和序列语义色；该入口与股票主题共同复用 `useResponsiveEChartsTheme()`，覆盖明暗、预设 key 和同 key 后端覆盖更新。`EquityChart`、`GrowthChart` 已纳入，不再作为固定明暗色板例外；新增 Canvas 主题消费者不得只监听 `isDark` 或在组件内维护第二套基础色板。
- 分项评分徽章使用 `--score-high-*` / `--score-mid-*`，低分使用弱底色和占位文字色；评分热力格（`SubScoreBars`）、训练评级、买卖标记等**内联 style 颜色的组件统一经 `components/chartTheme.ts::useStatusColorPalette()` 消费当前生效 token**（强弱梯度=跌绿→成功→警示→危险→涨红；买卖=主色蓝/警示橙；评级 S/A/B/C/D=警示/成功/主色/中性/危险），不得在该组件内维护私有绿橙红色阶或 Element 默认色。
- 页面提示、弱文本、占位文本优先使用 `--app-warning-text`、`--app-muted-text`、`--app-placeholder-text`；确属 Element Plus 标准状态时可直接用 `var(--el-color-*)`。
- **颜色单一事实源**：任何状态/金融/评分/评级/买卖颜色只允许来自 `LAYOUT_PRESETS` token（经 `--el-color-*`、`--market-*`、`--app-*-text`、`--score-*` 或 `useStatusColorPalette()` 消费）；页面、组件、Canvas fallback 一律与 `balanced` 预设同值，禁止出现 `global.css` 或组件内平行硬编码的第二套色板。图表 fallback（`chartTheme.ts`/`chartUtils.ts`）也必须与预设当前值保持一致并随色板演进同步更新。
- 普通操作文字与禁用操作文字分别使用 `text`、`textMuted`；二者按 WCAG 线性相对亮度计算的差值必须 `≥ 0.06`。这是文字层级阈值的唯一数值事实源，预设保存和运行时合并均须守卫。
- 预设运行时必须同步覆盖 Element Plus 语义色的基础色、RGB 通道、`light-3/5/7/8/9` 与 `dark-2` 派生色；`error` 与项目危险色同源。按钮、链接、提示、分段控件、焦点和禁用态不得回退到组件库默认蓝绿橙红色阶。**金融涨跌色与状态/评分文本色不走 el 的 light-*/dark-2 派生，而是直接消费预设 `marketUp`/`marketDown`/`success`/`warning`/`danger` 主色（亮色模式该主色即为提彩后的鲜亮值），避免派生工艺造成哑光。**

预设规则：

- 登录页与工作台必须同源：同一 `light/dark` 下，登录右侧交互区基础色等于工作台 `pageBg`，登录卡片可见色等于工作台 `surfaceBg`；白天和夜间的 `pageBg`、`surfaceBg` 分别保持相同，主体区通过边框、间距和交互态表达层级，不用常驻底色色块分层。该关系以 `frontend/src/layout/themeSurfaces.ts` 为底色事实源，并由 `presets.spec.ts` 守卫。
- 登录或注册成功时，登录页当前可见的 `light/dark` 是本次会话的明确模式：进入工作台前先暂存，鉴权后优先写回用户偏好；只有登录页没有形成待同步模式时，才允许远端用户偏好覆盖本地模式。
- 登录页恢复为修改前的全屏左右品牌布局：左侧承载品牌字标、趋势轨迹与“看见趋势，先于共识。”主视觉文案，右侧承载独立登录/注册卡片；页面结构、文案层级与交互以 `LoginView.vue` 的恢复版本为准。
- 登录页可保留原有光晕、网格、轨迹、透明和模糊等品牌装饰，但装饰层不能改变 `themeSurfaces.ts` 和 `presets.ts` 定义的基础底色事实源；按钮、焦点、品牌强调、趋势轨迹、Logo 渐变和光晕必须消费当前运行时 `primary`，禁止遗留独立硬编码主题色。
- 登录页与应用外壳的「复盘啦」必须直接复用 `BrandMark` 的同一几何、尺寸、渐变、文字与描边定义；组件不提供 `login/shell` 场景变体，消费容器不得覆盖 `--brand-*` 形成第二套字标。只有容器不足 `184×52px` 时允许按原始宽高比整体缩放。Logo 渐变由运行时 `primary` 派生，因此新增并启用颜色预设后，登录页与工作台会同步更新。
- `balanced`（澄空蓝）使用鲜明蓝色信号；页面、边栏、卡片、悬停、边框和文字属于固定中性基础表面，只受明暗模式控制，禁止预设覆盖。预设允许覆盖 `primary/success/warning/danger`、共享形态、响应式默认和组件默认策略。
- 外观抽屉必须保留视觉预设区：当前只有一套时显示唯一选中项；预设管理新增并启用自定义项后，无需改前端代码即可出现在抽屉并驱动运行时。登录页不提供预设管理入口。
- 启用预设的名称和明暗语义强调色通过登录公开配置下发，并写入首屏安全缓存；登录页与工作台必须共同消费 `setRuntimePresetSources()`，不得各自解析或维护另一套预设。公开配置禁止携带页面、组件或其他平台布局字段。
- 调整基础表面必须同步维护 `light`、`dark`、`themeSurfaces.ts` 与 `presets.spec.ts`；调整预设能力必须验证后端目录、运行时选择和固定表面不受覆盖。
- 页面设置抽屉保留 `32%` 黑色遮光层，用于明确浮层焦点和点击外部关闭边界；遮光层属于临时交互状态，不参与主题底色定义，抽屉内容面与页面常驻容器仍必须使用中性明暗表面。
- `surfaceHover` 只用于 hover、选中或明确可操作控件状态；查询摘要、图表分隔带、设置分组等常驻容器必须使用 `surfaceBg`，禁止把悬停灰当作静态页面底色。

## 3. Typography Rules

字体栈以系统 UI 字体为主：`system-ui, -apple-system, BlinkMacSystemFont, Segoe UI Variable, Segoe UI, Microsoft YaHei UI, PingFang SC, Hiragino Sans GB, sans-serif`。macOS 由系统字体与苹方承接，Windows 由 Segoe UI 与微软雅黑 UI 承接；不得引入需要联网加载的字体。

排版事实源：

- token 落地在 `frontend/src/styles/global.css`，包括 `--app-font-family-base`、`--app-font-size-*`、`--app-line-height-*`、`--app-font-weight-*`。
- 页面私有样式不得新增游离字体族；除品牌字标、登录主视觉、代码/配置值、图表 tooltip 外，必须继承 `body` 的 `--app-font-family-base`。
- 新增文字样式必须先判断是否能消费 `.app-page-title`、`.app-section-title`、`.app-body-text`、`.app-caption-text`、`.app-micro-text`、`.app-data-text`、`.app-data-emphasis` 或对应 token。
- 常规行高使用表内 token；图标/徽标贴边用 `--app-line-height-solid`，紧凑说明用 `--app-line-height-compact` / `--app-line-height-comfy`，长说明用 `--app-line-height-reading` / `--app-line-height-longform`，极小角标用 `--app-line-height-ornament` / `--app-line-height-tiny`。

| 层级 | 强制 token / 值 | 使用场景 |
|---|---|---|
| 页面标题 | `--app-font-size-page-title` 22px / 700 / 30px；紧凑页可用 20px | 页面主标题、工作台名称、配置中心一级标题 |
| 分区标题 | `--app-font-size-section-title` 15px / 600 / 22px；抽屉或大面板可用 18px | 卡片标题、抽屉标题、配置组标题 |
| 正文 | `--app-font-size-body` 14px / 400 / 22px | 表单、普通说明、主体内容 |
| 表格正文 | 默认 `--app-font-size-table` 13px / 400 / 20px；`comfortable` 密度或不高于 `1.5dppx` 的低像素密度屏幕使用 14px / 22px | 数据表格、列表、密集参数行 |
| 辅助标签 | `--app-font-size-caption` 12px / 400 / 18px | 单位、提示、来源、次级说明、tag 内文 |
| 微型标签 | `--app-font-size-micro` 11px / 400 / 16px | 顶栏弱标签、状态小字、空间极窄的 badge；禁止用于正文 |
| 数字强调 | `--app-font-size-data` 16px / 600 / 24px；大 KPI 可用 `--app-font-size-kpi-lg` 26px / 700 / 32px | KPI、收益、评分、排名、需要横向比较的数字 |

排版规则：

- 标题用于定位页面和分区，不用于装饰性大字。
- 页面顶部标题区统一结构：`<h2 class="app-page-title">` 承载页面标题，说明性长文进 `HelpTip`（内嵌标题内，勿放工具栏/`<p>` 内避免下沉），标题下用一行 `<p class="page-subtitle">` 说明页面用途。`page-subtitle` 为全局语义类（`--el-text-color-secondary` + caption），禁止页面私有定义 `.page-subtitle`/`.page-sub`/`.sub` 颜色字号。
- 页面顶部标题字号唯一来源是全局 `app-page-title`（22px），禁止页面用 `.page-head h2`/`.title h2`/`.title-row` 等私有选择器覆盖标题字号或边距；详情页对象标题（个股/板块名）同样走 `app-page-title`。
- 标题内嵌 `HelpTip` 时，标题行使用 `align-items: center`（flex 或 `vertical-align: middle`）保证圆点与标题垂直居中，不随行高下沉。
- 页面主体新增 `font-size`、`line-height`、`font-weight` 时必须引用上述 token 或语义类；直接写 px/数字只允许在以下特例：品牌字标、登录主视觉、图表 canvas/tooltip、第三方组件适配、极窄状态点/角标、图标尺寸。特例必须是局部私有，不得被复制为普通页面模式。
- 10px 以下只允许使用 `--app-font-size-ornament` 或 `--app-icon-size-xs`，用于图标内部标记、红点角标或不可读正文之外的装饰性标尺；不得用于业务说明、表格、表单、按钮、筛选项。
- 11px 只用于弱标签或极窄 chrome 信息；业务内容、表格单元格、表单 label、按钮文案不得小于 12px。
- 微字号（`--app-font-size-micro`/`tiny`/`ornament`）不得通过无 `>` 限定的宽泛后代选择器（如 `.xx span`、`.xx strong`）声明——此类规则会把它误传给嵌套的数值、标题等本不该用小字号的元素。微字号只允许作用于语义类、`:global` 或 `>` 限定的直接子级；容器用常规字号，内部小字通过独立子级规则声明。该约束由 `typography-spacing-system.spec.ts` 强制，禁止用 `>` 缺失的选择器绕过。
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
- 用户偏好同步只能消费既有偏好骨架：全局 singleton 偏好使用 `useGlobalPreferenceSync`，由它统一 token/身份守卫、PG `user_preference` 读写、debounce、加载失败回调和本地 fallback，调用方只保留值归一化、DOM 副作用和本地 key 差异；页面/feature 级实例偏好使用 `useUserPreference`，由它统一默认值合并、scope/pageKey/prefKey、PG 与本地回退、hydrate 前 dirty 保护和重置入口，页面只声明业务字段。禁止在页面或业务 composable 内复制这些同步流程。

### 组件资产分层

项目内“组件”分两层治理，不能混用：

- **真实复用组件**：位于 `frontend/src/components/**` 或 `frontend/src/layout/components/**` 的 Vue 运行时组件，负责真实渲染和交互，例如 `PageSettingsDrawer.vue`、`ComponentAutoSettings.vue`、`AppPagination.vue`、`AppFilterSelect.vue`。
- **系统组件种类**：位于 `frontend/src/layout/components.ts`、`componentConfig.ts`、`componentSchemas.ts` 的布局/配置元数据，例如 `data-table`、`wide-table`、`tabs`、`settings-drawer`；它让页面布局、系统组件页、页面设置抽屉和配置中心识别组件能力，但不必然对应一个同名 Vue 组件。

关系规则：

- 页面外壳、slot、滚动归属、可配置字段必须走系统组件种类和 `pageRegistry`。
- 真实 UI 行为优先复用真实复用组件；当同类控件在两个及以上页面出现，或承载全局交互规则时，必须登记到下方“真实复用组件清单”。
- 真实组件只有需要进入布局配置、系统组件页、页面设置抽屉或页面布局编辑器时，才新增或关联系统组件种类。
- `COMPONENT_CATALOG` 是系统允许的组件种类与能力词汇表，允许先登记当前尚无页面消费者的 kind，供 schema、预览和后续布局选型复用；“假配置”指 `COMPONENT_FIELD_DEFS` / `pageRegistry.consumedComponentFields` 暴露了页面并未真实读取应用的 Web 字段。已有真实复用组件时仍禁止页面复制同类控件行为。

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
| `PageSettingsDrawer` | `frontend/src/components/PageSettingsDrawer.vue` | 统一页面设置抽屉运行时组件 | 对应 `settings-drawer` 种类；`size/defaultCollapsed` 的用户偏好走 PG `user_preference`，`bodyScroll/collapsibleSections` 只允许 preset/page 层 | `supportsPageSettings !== false` 的 registry 页面统一使用，禁止页面另写第二套设置抽屉 |
| `PageSettingsTrigger` | `frontend/src/components/PageSettingsTrigger.vue` | 页面设置统一入口 | 触发 registry 页面中的 `settings-drawer` | 仅 `pageRegistry.supportsPageSettings !== false` 的真实消费页面显示；平台布局管理页不开放个人设置，不登记假入口 |
| `PageDrawer` | `frontend/src/components/PageDrawer.vue` | 页面级抽屉边界组件 | 无直接系统组件种类 | 页面打开的设置、详情、日志抽屉统一挂载到 `LayoutHost` 内容区；宽度只传 `sm/md/lg/xl/xxl/wide` 语义档位，禁止页面私传 px/%；`wide` 仅供日志、字段差异和长 JSON 等宽内容，`xxl` 供资产搜索等需更宽横向空间的复杂详情；禁止直接覆盖应用顶栏与导航 |
| `LayoutHost` | `frontend/src/layout/components/LayoutHost.vue` | registry 页面统一布局、slot、滚动和 overlay 运行时宿主 | 消费 `PageLayout` 中登记的系统组件种类与区域 | 所有 registry 业务页面统一消费；页面不得绕过宿主手写页面外壳、主成长区、滚动归属或 overlay 边界 |
| `ComponentAutoSettings` | `frontend/src/components/ComponentAutoSettings.vue` | 组件特性唯一渲染器 | 消费 `pageRegistry.consumedComponentFields`、`componentMeta` 和 `COMPONENT_FIELD_DEFS` | 设置抽屉 user 层与页面布局编辑器 page 层共用；候选项可由页面按当前业务上下文传入运行时 meta 覆盖，避免不同面板的分区混显；枚举候选较多而使用下拉框时，输入框必须与 `PageSegmented` 共用连续底板、基础边框和明确聚焦态 |
| `SettingsGroup` | `frontend/src/components/SettingsGroup.vue` | 设置抽屉的分组容器 | 无直接系统组件种类 | 页面设置抽屉分组优先复用；不直接用于主内容区配置面板 |
| `PageSettingSection` | `frontend/src/components/PageSettingSection.vue` | 页面设置业务选项分区 | 无直接系统组件种类 | `PageSettingsDrawer` 的业务选项统一复用；不得在页面内复制标题、说明和分区间距 |
| `ConfigPanelSection` | `frontend/src/components/config/ConfigPanelSection.vue` | 主内容区配置面板的可折叠分组容器 | 对应 `config-panel` 种类；读取 `collapsibleSections`、`defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | 系统设置等主面板配置分组优先复用；配置项说明/默认值继续放 `HelpHint`，一级组说明在组头展示，二级分区说明随分区内容一起展开/收起 |
| `PageSegmented` | `frontend/src/components/PageSegmented.vue` | 页面设置和业务偏好的分段选择控件 | 无直接系统组件种类 | 业务选项、组件设置中的枚举选择优先复用；整组选项使用连续底板与基础边框，选中项在组内浮起，不把选项渲染成彼此分散的独立按钮；页面级模式/范围切换使用 `tone="primary"` 跟随系统主色，设置抽屉枚举保持默认中性色；固定操作区使用 `small`，设置抽屉与表单使用默认尺寸；每个选项必须通过 `aria-pressed` 暴露程序化选中状态，多组并列使用时由消费页提供可访问名称 |
| `BoardTaskScopeFields` | `frontend/src/components/data/BoardTaskScopeFields.vue` | 板块采集范围和分阶段参数组 | 无直接系统组件种类 | 数据采集与任务调度的板块任务统一复用；模式、板块类型、采集内容和成分强刷文案/参数不得在消费页再维护第二套 |
| `PageToggleRow` | `frontend/src/components/PageToggleRow.vue` | 页面设置和业务偏好的开关行 | 无直接系统组件种类 | 业务选项、列显隐、布尔设置优先复用 |
| `AppControlRow` / `AppControlItem` | `frontend/src/components/AppControlRow.vue`、`frontend/src/components/AppControlItem.vue` | 页面工具行、查询行和参数行的通用横向控件容器；控件行默认按控件自然宽度排列，空间不足时换行，不自动拉伸填满；控件项把标签和控件作为一个整体换行 | `filter-bar`、`toolbar` 等系统组件种类的真实渲染基础 | 多个输入、选择器、按钮组成的横向行优先使用 `AppControlRow`；存在“说明文字 + 控件”时必须用 `AppControlItem` 包裹，避免标签和控件被拆到不同行；只有明确需要均分或撑满时才传 `fill` 或让具体 `AppControlItem` 设置 `grow` |
| `AppIconButton` | `frontend/src/components/AppIconButton.vue` | 全站纯图标操作按钮，统一可访问名称、尺寸、圆角、悬浮、聚焦、禁用、loading 和语义色 | 无直接系统组件种类 | 顶栏工具、抽屉关闭、刷新、页面设置等仅图标操作统一复用；必须传 `label`，异步纯图标操作使用 `AppIconButton` 的 `loading`，外层 `el-tooltip` 承载长说明时关闭原生 `title`；图形使用 Element Plus 图标或项目既有 SVG，禁止页面手写 Unicode 符号按钮 |
| `AppSummaryDisclosureCard` | `frontend/src/components/AppSummaryDisclosureCard.vue` | 高密编辑器的通用折叠摘要卡外壳，统一序号、标题、元信息、单行摘要、工具区、展开边界与键盘可访问 disclosure | 无直接系统组件种类 | 规则、操作事实等“列表摘要 + 展开编辑”场景统一复用；业务状态和命令通过插槽注入，组件不持有启停、删除或校验等领域逻辑；展开编辑区保持基础表面并用边框与主色边线表达层级，不使用常驻填充色形成嵌套色块；整块摘要使用带完整 `aria-expanded`、`aria-controls` 和可访问名称的专用原生 disclosure button，不得在消费页复制卡片结构 |
| `RuleSummaryCard` | `frontend/src/components/trade-discipline/RuleSummaryCard.vue` | 买入、卖出和选股规则的紧凑摘要卡，基于 `AppSummaryDisclosureCard` 组合规则启停与动作区 | 无直接系统组件种类；仅承载交易纪律规则编辑 | 同类规则统一复用；默认只展示摘要并一次展开一项，动作通过插槽注入；不得把规则启停语义下沉到通用卡片外壳 |
| `AppRowActions` | `frontend/src/components/AppRowActions.vue` | 表格行操作列和列表项操作区的统一动作组，按权限过滤、单行排列、动作颜色层级、禁用/加载态展示、轻量“更多”菜单收纳和**宽度自适应折叠** | 无直接系统组件种类 | 表格 `label="操作"`、自绘表格行、列表项和编辑器条件行的行内按钮组优先复用；首个未显式指定语义色的行内高频动作使用主色，普通次要动作使用常规正文色，禁用态使用弱文本色并满足语义 token 规则定义的文字层级阈值，停用/禁用/终止/删除等破坏性动作使用危险色；动作始终清晰可见，不对整组做透明度弱显；低频或危险动作可设置 `placement: 'more'`，菜单命令继续使用 Element Plus 按钮并呈现真实 loading，不得在页面内手写多行按钮或原生命令按钮。**宽度折叠契约**：行内按钮按操作列实际可用宽度自适应折叠——宽度装不下的按钮自动收进“更多”菜单，不硬截断；`inline-limit` 退化为行内数量硬性上限（宽度能装下时仍不超过它）；显式 `placement: 'more'` 的动作恒入更多；可用宽度或按钮实测宽度不可用（如 jsdom）时退化为纯数量逻辑 |
| `SystemBuiltinTag` | `frontend/src/components/SystemBuiltinTag.vue` | 全站“系统内置”来源标记，固定使用灰色文字、灰色描边和中性浅底 | 无直接系统组件种类 | 菜单、功能点、角色、租户、布局预设、技术指标和系统内置方案等来源标记统一复用；文案固定为“系统内置”，不追加对象名称或保护规则说明；与对象名称或标识并列时统一放在对象后面，独立的来源/类型字段保持标签单独展示 |
| `AppDataTable` | `frontend/src/components/AppDataTable.vue` | 数据表格/宽表运行时外壳，统一表头排序布局、表体内滚、分页承载、加载分流、空态插槽、行点击样式和成长/嵌入模式 | 对应 `data-table`、`wide-table` 种类；读取页面传入的排序、分页、列显隐等消费结果 | 页面中的数据表格统一复用；`loading && data.length === 0` 自动显示 `AppStateBlock` 骨架，有旧数据刷新时保留表格并使用 `v-loading` 遮罩；主列表默认成长，抽屉、展开行和局部明细等非主表显式使用 `embedded`；`#empty` 只补充业务文案与操作并复用 `app-table-empty*`，禁止嵌套 `el-empty` 形成双图；`wide-table` 默认常显 Element Plus 内部滚动条，禁止页面再给 `el-table__body-wrapper` 添加第二层横向滚动；禁止用 `fill` 布尔值绕过主表语义；复杂单元格继续由业务页通过列插槽声明 |
| `AppTableColumn` | `frontend/src/components/AppTableColumn.vue`、`frontend/src/components/table/adaptiveColumnWidth.ts` | 表格列运行时组件，根据结构类型、字段名和标签推导语义角色，以稳定字符权重结合排序/筛选控件计算弹性最小宽，并统一渲染单行表头及同行元信息 | `data-table`、`wide-table` 的稳定列宽、内容对齐和表头能力；不是用户可配置字段 | 页面表格列统一复用，禁止传 `width/min-width`；确有歧义的动态标签只传 `role`；日期、单位或短口径摘要传 `header-meta`；单元格主内容前存在紧凑控件时传 `leading-controls`，组件统一预留宽度并让表头对齐主内容；自定义 header slot 只用于复选、帮助入口等真实交互结构；数值事实只维护在 `ADAPTIVE_COLUMN_RULES` |
| `AppStateBlock` | `frontend/src/components/AppStateBlock.vue` | 页面和组件的加载、空、异常、无权反馈块，统一 `ready / loading / empty / error` 四态中的非 ready 呈现、重试入口和尺寸档位 | 对应布局系统中的 `loading-state`、`empty-state`、`error-state`、`skeleton` 语义，但作为真实运行时复用组件消费 | 主加载失败、局部列表失败、无权态、非表格空态和稳定骨架占位优先复用；表格数据的 loading/empty 仍优先由 `AppDataTable` / `el-table` 承接，不在页面手写第二套错误块、空态图标或重试布局 |
| `CandleChart` | `frontend/src/components/CandleChart.vue` | 盘感训练、回测复用的 K线、量能、MA/VMA 与买卖标记画布 | 无系统组件种类；图表参数由消费页面管理 | 独立使用保持默认画布高度，受控工作台通过 `fill` 填满父容器；保持单实例双网格与既有 props 契约，并与 `StockChartWorkspace` 共用 MA/VMA 定义、tooltip helper 和 `useStockChartTheme()`，不得复制股票画布基础能力 |
| `StockChartWorkspace` | `frontend/src/components/stock-chart/StockChartWorkspace.vue` | 行情 K线、量能和可选 MACD 的纵向联动工作区，统一日期轴、光标、显式缩放同步、局部状态和可访问高度分隔线 | `chart.minHeight`（由详情页 chart slot 消费） | 个股详情、个股查询/每日榜单 K线模式、板块行情 K线模式和板块详情统一消费 K线/量能/MACD，并通过共享图表设置选择图表二、图表三；独立详情行情区域统一通过 `chart.minHeight` 配置整体高度，组件仍须以所有可见面板最小高度之和加分隔线作为硬下限，禁止用外层裁切换取紧凑；列表等随视口填充的主从工作台不套用固定高度字段；行情与指标按交易日和所选截止日对齐，MACD 局部失败不得阻断 K线/量能；只有 K线显示固定在绘图区左上角的行情 tooltip 和唯一光标轴日期气泡，量能和 MACD 普通柱线只保留联动光标与标题当前值，不显示行情内容浮层、日期气泡或标题日期，MACD 信号 item 悬停例外显示信号类型与完整日期；三图标题值与实际序列必须复用盘感训练共享色板，柱宽按 K线、量能、MACD 明显递减，底部日期标签不得被缩放滑块遮挡；任一图的 `dataZoom` 必须显式同步给其余可见图并在主题重绘后保留；画布必须监听预设系统在完整 CSS token 写入后发布的主题修订版本，覆盖明暗、预设 key 和同 key 后端覆盖变化，分隔线遵守 reduced-motion；光标跟随指标值不得设置 `aria-live`，避免三组高频播报；消费页面不得再拼装第二套多图联动和分隔线逻辑 |
| `MarketMasterDetailWorkspace` | `frontend/src/components/MarketMasterDetailWorkspace.vue` | 行情列表与走势分析区的双栏工作台外壳，统一列表头、收起/展开、整宽回退和主区滚动边界 | `master-detail` | 个股查询、每日榜单共同消费；业务表格和分析面板通过具名插槽传入，组件不持有股票选择、查询或权限状态；页面必须通过 `useStockAnalysisSession` 投影抽屉默认值，并通过 `useStockAnalysisSelection` 维护当前观察与对比队列，禁止复制页面私有状态机 |
| `MarketCompareMetricStrip` | `frontend/src/components/MarketCompareMetricStrip.vue` | 行情走势对比的指标摘要与切换条；单项固定为指标名称在上、指标值在下并左对齐，统一激活态、涨跌语义色、键盘按钮语义和紧凑视口降级 | 无直接系统组件种类；由行情分析区承载 | 板块行情、个股查询、每日榜单共同消费；消费页只提供指标元数据和值，不复制指标条结构或样式；个股页面只接累计及 5/10/20/30/60 日涨跌，不接板块资金流、成员涨跌或领涨股口径 |
| `CompareQueueRail` | `frontend/src/components/CompareQueueRail.vue` | 走势对比的对比对象队列条，统一队列标签、chip（名称/激活/错误/移除）与“最多 N 个”上限提示 | 无直接系统组件种类；由行情分析区承载 | 板块行情、个股查询、每日榜单共同消费，禁止页面内再写第二套队列 chip；chip 为 `role=button` 容器承载激活（点击 + Enter/Space，`.self` 避免焦点在移除钮时连击激活），名称为纯 `span` 继承 chip 颜色（激活/悬浮随主色变化），移除用 `AppIconButton`；遵守按钮契约——不引入原生 `<button>`，也不用 `el-button` 包裹名称（其特异性会覆盖继承色）；消费页只提供归一化 `{ key, label, active, error }` 列表与 `activate`/`remove` 事件，上限提示文案按对象（板块/股票）传入；队列顺序稳定（进入先后），激活/切换主观察只移动高亮不重排，该状态机由共享纯函数 `frontend/src/utils/compareQueue.ts` 维护，`useStockAnalysisSelection`（个股/榜单）与板块行情视图都委托给它，禁止再各自实现“激活项置顶”的派生队列 |
| `StockAnalysisDefaultFields` | `frontend/src/components/StockAnalysisDefaultFields.vue` | 个股走势分析的默认模式、周期、指数、指标和分析区显隐设置字段组 | 无直接系统组件种类；嵌入页面设置业务分区 | 个股查询、每日榜单共同消费；指标列表不可为空，移除当前默认指标时统一回退到首个可见指标；组件只统一字段与校验，持久化仍由消费页各自的 `stocks` / `board` 页面键负责，禁止共享同一个设置对象 |
| `StockAnalysisPanel` | `frontend/src/components/StockAnalysisPanel.vue` | 股票走势对比与 K 线的统一分析面板，负责当前观察、对比队列、指标、基准指数、周期、局部加载降级和模式切换 | `chart`（作为 master-detail 的分析子区） | 个股查询、每日榜单共同消费；行情复权口径由抽屉「复权模式」默认驱动（不复权/前复权/后复权，默认前复权，位于 `StockChartSettingSection` `#before` 插槽，与个股详情页同位同控件），经 `useStockAnalysisSession` 投影为 `adjustMode`，走势对比与 K 线共用同一口径且界面文案随之标注；走势对比按统一市场交易日前向延续停牌收盘；对比指数时统一从首个共同有效日期起算（共同基期归零），纯股票间对比时各序列从自身首个有效值起算、上市前留空，固定 N 日仍须取 N+1 个市场收盘点，最多6只；抽屉默认值经 `useStockAnalysisSession` 单向投影且按 `stocks` / `board` 页面键隔离；部分股票加载失败时保留可用曲线，重试仅重新请求失败股票，不刷新已成功曲线；市场交易日请求失败或返回空数据时必须进入可重试错误态，重试只重拉日历且不刷新已成功股票；K线直接消费 `StockChartWorkspace`，不得在页面内重做 K线、量能、MACD 联动 |
| `StockAnalysisNameCell` | `frontend/src/components/StockAnalysisNameCell.vue` | 股票列表名称单元格中的走势对比加入/移除入口，统一图标、可访问名称和激活反馈 | 无直接系统组件种类 | 个股查询普通列表、分组列表和每日榜单共同消费；只管理入口展示与事件，不持有对比队列状态 |
| `StockCompareChart` | `frontend/src/components/StockCompareChart.vue` | 多股票前复权序列与可选市场指数的涨跌幅对比折线（对比指数统一共同基期，纯股票间对比各序列从自身首值起算），统一交易日、主题、图例、tooltip、超额收益和缩放 | 无直接系统组件种类；由 `StockAnalysisPanel` 承载 | 只表达股票相对走势，不扩展板块资金流、成员涨跌、领涨股等截面指标；统一使用显式市场日历；对比指数统一从首个共同有效日期起算并据此计算超额，个别序列上市较晚只缩短基准期、不否决整体，仅连一个共同有效日期都没有时才显示不可比较空态；纯股票间对比时各序列从自身首个有效值起算，上市前留空、停牌期前向延续为 0%，不因个别序列缺起点而否决整体；当前观察线可强化，但所有序列仍须可辨识且不依赖单一颜色 |
| `SectorCompareChart` | `frontend/src/components/SectorCompareChart.vue` | 多板块连续指数的涨跌幅对比折线、市场指数超额和资金流/成员涨跌截面柱图 | 无直接系统组件种类；由板块行情分析区承载 | 折线与股票对比复用 `marketCompare` 的 N+1、统一交易日、停牌补齐和对比基期算法（对比指数统一共同基期，纯板块间对比各序列从自身首值起算）；资金流、当日涨跌和成员涨跌缺失值保持空值，不得代填 0；页面偏好只消费 `sectors` 页面键，禁止与 `stocks` / `board` 串用默认指标或基准配置 |
| `AppPagination` | `frontend/src/components/AppPagination.vue` | 列表页统一分页 | 由 `data-table`/`wide-table` 的 `pageSize` 配置间接驱动 | 服务端分页页脚优先复用 |
| `AppFilterSelect` | `frontend/src/components/AppFilterSelect.vue` | 列表页筛选下拉 | 无直接系统组件种类 | 默认多选、可搜索、可清空；业务只允许单选时必须传 `multiple=false`；默认最多展示 3 个选中标签，溢出时提前折叠；筛选下拉优先复用 |
| `AppSearchInput` | `frontend/src/components/AppSearchInput.vue` | 列表页关键字搜索输入，统一"输入即防抖查 + 回车/清空立即查" | 无直接系统组件种类 | 关键字输入防抖（默认 300ms，可传 `debounceMs`）后 `@search`，回车/清空立即 `@search`；消费页绑定 `v-model` + `@search`（`@search` = 重置第 1 页 + 加载）。**查询触发通用不变式**：筛选/查询类控件（关键字、下拉、日期、分段、勾选、分页、排序）改选或输入即自动触发查询并重置第 1 页（分页换页只查当页不重置）；列表筛选条不设"查询"按钮。**动作型提交**（一次性执行/运行/评估/保存）与**手动同步刷新**（重新拉取当前数据）保留显式按钮，不属筛选查询。查询防抖编排统一走 `frontend/src/composables/useDebouncedQuery.ts`；关键字字段不得再用裸 `<el-input>` 手写防抖 |
| `TradeDatePicker` | `frontend/src/components/TradeDatePicker.vue` | 交易日选择器 | 无直接系统组件种类 | 回测、筛选、训练和数据任务等交易日输入统一复用；不得退回普通日期选择后自行补交易日校验。单日查询类页面若语义是“默认最新、允许回看”，统一使用 `defaultLatest` 显示数据最新交易日；训练区间、回测区间和数据任务边界等显式范围不得擅自默认 |
| `KlineRangeSelect` / `KlineSettingSection` | `frontend/src/components/KlineRangeSelect.vue`、`frontend/src/components/KlineSettingSection.vue` | K线范围快捷选择与共享设置分区 | 无系统组件种类；消费全局 K线偏好 | 个股详情、盘感训练等 K线页面统一复用，不复制范围选项或偏好写入逻辑 |
| `StockChartSettingSection` | `frontend/src/components/StockChartSettingSection.vue` | 多图行情工作区的图表二/图表三选择、默认高度比例编辑和“将当前比例设为默认”显式操作 | 无系统组件种类；消费 `useStockChartPreferences` | 每日榜单、个股查询、个股详情、板块行情、板块详情和盘感训练统一复用；复权模式等行情口径字段经 `#before` 插槽置于图表设置首位，消费页同位同控件（个股详情、个股查询、每日榜单一致）；主区拖动只改会话比例，抽屉编辑默认比例或显式将当前比例设为默认时才允许持久化；辅助图选择、比例草稿/提交/取消与恢复默认不得在消费页维护第二套 |
| `EquityChart` / `GrowthChart` | `frontend/src/components/EquityChart.vue`、`frontend/src/components/GrowthChart.vue` | 回测/训练净值与成长曲线 | 无直接系统组件种类 | 保持各自数据与布局职责；画布主题统一消费 `useEChartsTheme()`，不得私有维护明暗基础色板。净值图「对比指数」虚线由父页注入 `extraBenchmark`（父页按各自日期区间拉指数行情并归一成资金净值），组件不内建数据获取；`fill` 撑满等高列仅在结算详情等需要时启用。基准可见性由 `showBenchmark` 控制：缺省 true 渲染基准线（无 `extraBenchmark` 时用 points 自带 `benchmark_equity` 实线，如训练「满仓持有」），显式 false（回测选「不对比指数」）整条隐藏。`setOption` 用 `notMerge: true` 整图重建，切「不对比」时基准 series 彻底移除不残留。配色：组合=focus 蓝，基准=`t.label` 灰（与板块行情对比图基准一致），回撤=`--el-color-danger` 红（面积用 `light-9` 浅红）；各 series 的 `color`/`itemStyle.color` 与线色同值，保证图例/悬浮圆点与线色一致。悬浮 tooltip 按「相对首日涨跌幅 %」展示组合/基准，并在基准可见时给组合一行「超额」（组合涨跌幅−基准涨跌幅），与板块行情对比图悬浮口径一致；回撤子图仍按 % 原值展示 |
| `BrandMark` | `frontend/src/components/BrandMark.vue` | 应用品牌图形与「复盘啦」字标 | 无直接系统组件种类 | 应用外壳、登录页等品牌露出直接复用同一外观；禁止场景变体、消费侧 `--brand-*` 覆盖、私有 logo 或第二套字标；窄容器只允许等比缩放 |
| `SideMenu` / `TopNavigation` / `WorkspaceTabs` / `WorkspaceRouteView` / `MenuIcon` | `frontend/src/components/SideMenu.vue`、`frontend/src/components/TopNavigation.vue`、`frontend/src/components/WorkspaceTabs.vue`、`frontend/src/components/WorkspaceRouteView.vue`、`frontend/src/components/MenuIcon.vue` | 应用级菜单树、双层顶栏、保留现场的工作标签页、路由缓存与统一菜单图标渲染 | 无直接系统组件种类 | 菜单统一消费 `/me` 授权树和 `utils/permission.ts` 的路由归属口径；工作页面统一由 `WorkspaceRouteView` 渲染并按标签独立缓存，禁止业务页私建 KeepAlive；关闭标签必须同步移除对应缓存；侧栏、双层顶栏和菜单管理页统一用 `MenuIcon` 消费后端图标名；新增导航模式时复用 `useAppNavigation` 持久化偏好 |
| `AssetVisibilityTag` / `AssetProfileLabel` / `AssetVisibilityActions` | `frontend/src/components/AssetVisibilityTag.vue`、`frontend/src/components/AssetProfileLabel.vue`、`frontend/src/components/AssetVisibilityActions.vue` | 公开资产来源、可见范围、只读状态、方案名称+版本+归属标签、发布/收回、复制为我的方案和复用参数动作 | 无直接系统组件种类 | 评分、筛选、买卖、回测等公开资产页面必须复用；方案选择/列表入口统一用 `AssetProfileLabel`，消费页包括 `BoardView`、`ScreenView`、`StockDetailView`、`ConfigView` 评分 tab、`ConfigView` 买卖 tab、`BacktestView` |
| `ScoreGradeTag` | `frontend/src/components/ScoreGradeTag.vue` | 统一综合评分评级标签：主升浪核心=`danger`、龙头候选=`warning`、观察=`success`、未知评级=`info` | 无直接系统组件种类 | 每日榜单、策略筛选、评分试算、回测交易及回测当日榜单统一复用；训练模块的 S/A/B/C/D 属于另一套评级，不套用本组件 |
| `AssetSearchDrawer` / `AssetProfileSelect` | `frontend/src/components/asset-search/AssetSearchDrawer.vue`、`frontend/src/components/asset-search/AssetProfileSelect.vue` | 统一跨来源资产搜索抽屉与“我的资产”选择器，支持 `select` / `list` 形态、服务端搜索分页、加载查看、复制或复用 | 无直接系统组件种类 | 公开资产页面统一消费，禁止私建同类选择器或搜索弹窗。无浏览权限时隐藏入口并显示明确无权态，不伪装成空态；加载查看默认不改变当前选择，需要外部展示时使用只读快照，只有“加载即展示结果”的场景才启用 `selectLoaded`。移除临时预览不等于删除资产，消费页必须同步清理对应请求和外部状态。mine-only 候选不显示“我的”，外部只读项保留来源；列表失败发 `loadFailed`，消费页结束等待并提供错误反馈和重试。mine ref 才进入选择器，系统或公开 ref 使用外部只读展示，不可解析时明示失效并阻止执行。具体 props、emits 和状态机以组件类型、实现及 `AssetProfileSelect.spec.ts` 为准 |
| `ConfigGroupForm` | `frontend/src/components/config/ConfigGroupForm.vue` | 系统设置配置组表单 | 消费 `config-panel` 的折叠与说明展示配置 | 动态配置组字段渲染优先复用 |
| `HelpTip` / `HelpHint` | `frontend/src/components/HelpTip.vue`、`frontend/src/components/HelpHint.vue` | 页面说明和短提示 | 无直接系统组件种类 | 说明性长文收进提示组件，不在页面堆长文 |

### 应用外壳

- 侧栏宽度固定为 `208px`，顶栏高度 `67px`，主工作区 padding 为 `20px 24px`。
- 应用提供 `sidebar-tabs` 与 `dual-topbar` 两种导航布局：侧栏模式在内容区上方显示可关闭工作标签；双层顶栏模式把一级菜单放在品牌顶栏、当前一级下的二级菜单放在独立次栏，三级页面由二级菜单下拉承接。
- 工作标签按路由路径保留页面组件实例、表单筛选与独立滚动位置，最多缓存 12 个；同一页面类型的不同详情路由必须拥有独立缓存身份，关闭标签或超过上限时同步销毁对应实例与滚动记录。**菜单记忆只记菜单主页自身的访问（含查询态），不记详情子路由**——再次点击某菜单永远回该菜单主页，详情现场只由工作标签恢复；避免从榜单/板块等来源进详情后，菜单记忆被劫持到详情路由。
- **详情页返回键的来源必须可信**：个股/板块详情的「返回」以来源集合上下文（`stockSet.returnPath`）为目标时，仅当当前对象仍属于该集合才有效；从菜单、标签或直接链接进入（对象不在集合中）时禁用残留来源、归位默认列表。任何从列表/榜单/板块/筛选页跳进个股详情的入口都必须 `setSet` 写入本次来源路径与集合，不得依赖上一次进入的残留值。
- 导航布局是独立用户偏好，不与明暗模式或颜色预设绑定；外观抽屉中的主题缩略图只表达色彩和材质，不暗示固定导航结构。
- 双层顶栏的二级导航与侧栏模式的工作标签栏统一消费 `--chrome-context-bar-bg`：以固定中性 chrome 底色为主体，仅混入当前预设强调色形成轻量横向渐变；两处不得维护私有背景配方。
- `.main` 必须保持 `overflow: clip` 和 flex 填充，禁止浏览器把隐藏外层变成可滚动容器；页面滚动由布局系统内部区域承载。
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
- 自定义原生 `<button>` 仅保留给导航、标签页关闭、登录主视觉切换、规则摘要 disclosure 等具有独立语义和结构的专用控件，并在实现中保持专用 class、键盘语义和必要的 ARIA 状态；普通命令和纯图标操作不得借此绕过统一组件。
- 夜间模式的复选框、单选框、输入边界和表格行悬浮必须使用强边框或主色反馈；空框、选中、禁用三态均需肉眼可辨。
- 工具栏按钮应贴近其影响区域，避免页面右上角堆积所有操作。
- 顶栏状态和工具按 `32px` 控件基线对齐、间距 `6px`。交易日等状态项使用“图标 + 弱标签 + 强值 + 5px 状态点”的轻量结构；无详情权限时使用只读 `role=status`，不得伪装成禁用按钮，也不得使用永久渐变、内阴影或大胶囊底板。

### 金额展示与输入

- 金额格式化的唯一前端事实源是 `frontend/src/utils/money.ts`。本金、资金、现金、资产、成交金额、费用、盈亏、市值、净流入、价格，以及图表中的金额轴和金额 tooltip，必须消费 `formatMoney` 或该文件导出的缩放/输入 helper；页面和业务组件不得再定义私有 `money`、`wan`、金额 `toLocaleString` 或正则分组逻辑。
- 所有可见金额从个位起每三位使用英文逗号分组，例如 `1,000,000,000`。金额精度沿用业务口径：普通金额默认两位小数，明确的整数金额可用零位，成交价等价格按接口口径使用两位或四位；千分位规范不得擅自改变存储精度。
- 使用“万/亿”等缩放单位时必须明确展示单位，缩放后的数值部分仍使用三位分组；不得以缩写为由绕过格式化。正数是否显示 `+` 由涨跌、净流入等业务语义决定，负号保留在数值最前。
- 精确十进制字符串禁止先转成 JavaScript `number` 再格式化；使用 `formatMoney` 保留数据库定点精度。既有浮点业务字段可按既有精度归整后格式化。
- 金额输入控件展示千分位、业务状态和接口值不带分隔符：Element Plus 数字输入统一使用 `formatMoneyInput` / `parseMoneyInput`；精确定点字符串输入在非编辑态显示千分位，聚焦编辑时可以显示无分隔原值。粘贴带逗号金额必须能够正常解析。
- 百分比、数量、手数、代码和日期不是金额，不得为了套用本规范改变其业务单位；其中确需数值分组时使用相应数值工具，不冒充金额格式化。

### 表格与列表

- 主数据表应作为 `growMain` 占据剩余空间，使用 `height="100%"` 让表体内部滚动；当一个标签页工作区承载多个互斥主表时，由 `tabs` 作为唯一 `growMain`，当前面板内的表体承接滚动。
- `list` 原型必须且只能有一个顶层 `growMain`；主列表不得使用 `embedded`。
- 页面数据表格统一使用 `AppDataTable + AppTableColumn`。页面不得直接使用原生 `<table>`、`el-table`、`el-table-column`，也不得向列传 `width/min-width`。
- 列宽采用语义自适应契约：选择、展开、序号等结构列保持稳定窄宽；普通名称使用 `name`，含前置选择/收藏等控件并展示主副信息的对象识别列使用 `entity`；其余列取“语义内容基础宽度”和“表头标签 + 同行元信息 + 排序/筛选控件 + 主内容前置控件”估算宽度的较大值，并按 8px 网格取整。中英文混排使用稳定字符权重估算，不做运行时 DOM/数据采样，避免数据变化触发列宽跳动；异常长表头受角色上限保护并保留完整 `title`。容器有余量时由 Element Plus `fit` 按最小宽度权重分配并铺满，空间不足时保持最小可读宽度并由表体横向滚动。
- 自适应列宽的角色、字符权重、控件预留、上限和数值唯一维护在 `components/table/adaptiveColumnWidth.ts`；页面只在动态标签无法推导时声明语义 `role`，不得复制数值。所有标准表头保持单行且不换行；日期、单位或短口径摘要使用 `header-meta` 在标签后同行弱化展示；主内容前存在紧凑控件时使用 `leading-controls` 让组件统一缩进表头并预留列宽。说明性长文本继续放 `HelpTip` / `HelpHint`，不得通过私有 header slot 拼接第二套样式。
- 表头保持稳定，分页、批量操作和关键筛选不被表体滚动带走。
- 不使用隔行变色作为默认识别手段；当前全局样式会取消 stripe 背景。
- 列宽按信息类型分配：编号、状态、日期、操作列稳定窄列；名称、标题、描述、备注更宽；数字列保持易比较。
- `data-table` / `wide-table` 的稳定字段只要支持排序，就必须同时支持列头直接排序和设置抽屉默认排序；分页表优先服务端排序，纯本地完整数据表可用 Element Plus 本地排序。
- `pageRegistry.componentMeta[slot].sortFields` 是可交互排序字段和默认排序候选的单一事实源；登记了 `sortFields` 的 slot 必须在 `consumedComponentFields` 消费 `defaultSort`，页面表格必须把对应列接入 `sortable` / `@sort-change`。**反向契约**：页面列头可排序的字段必须登记进 `sortFields`，二者双向一致，由 `pageRegistry.spec.ts` 契约测试强制拦截漂移。
- 操作列、展开列、按钮列、开关列、多值标签组合列、长说明/详情文本列默认不排序；若业务需要排序，必须明确映射到稳定字段并登记到 `sortFields`。
- 操作列和列表项操作区优先单行可见；行内按钮组优先使用 `AppRowActions`，普通操作使用常规正文色，禁用操作降为弱文本色并满足语义 token 规则定义的文字层级阈值；hover / focus-visible 只做轻量文字色反馈，不对整组做透明度显隐；操作过多时用轻量“更多”菜单、分组、详情入口或抽屉，不用多行按钮堆叠；`AppRowActions` 按操作列实际宽度自适应折叠，放不下的按钮自动收进“更多”菜单，不硬截断；“更多”菜单不得引入重动画、布局跳动或遮挡表格内容，菜单命令仍消费 Element Plus 按钮的 disabled/loading 状态。
- 宽表通过表体横向滚动承载，不让整页横向滚动。

### 四态反馈总则

页面和组件的数据反馈统一按 `ready / loading / empty / error` 四态处理，代码枚举以 `frontend/src/layout/schema.ts` 的 `COMPONENT_STATES` 为事实源。文档、`COMPONENT_CATALOG.defaultStates`、`LayoutComponentPreview` 和页面实现必须使用同一语义，不新增“暂无/失败/加载中”的私有视觉体系。

| 状态 | 中文口径 | 使用场景 | 组件和图标 | 文案模板 |
|---|---|---|---|---|
| `ready` | 价值态 / 有数据态 | 接口或本地计算已返回可行动内容 | 不额外加状态图标；价值由表格、KPI、图表、详情、状态 tag 自身承载 | 标题或摘要写清范围、日期、数量、来源，例如“2026-07-10 · 预设榜单 · 320 条” |
| `loading` | 加载态 | 首次加载、刷新、保存、运行、远程下拉 | 无旧内容的独立区域用 `AppStateBlock loading` / `el-skeleton`；已有内容刷新用 `v-loading`；按钮用 `:loading`；小型导航可用 Element Plus `Loading` 图标 | 页面级“正在加载{对象}…”，按钮级“{动作}中…”，下拉级“加载中…” |
| `empty` | 空态 | 请求成功但当前条件下没有可展示数据，或用户尚未完成前置选择 | 表格走全局 `el-table` 空态；非表格走 `el-empty.app-empty*`；很小区域走 `app-empty-inline` | “暂无{对象}”“请选择{对象}”“运行后在这里展示{结果}”“当前条件无命中” |
| `error` | 异常态 / 无权态 | 主请求失败、局部依赖失败、403/权限失败、详情读取失败 | 整区用 `el-result icon="warning"`；表格局部失败可用表内错误行。两变体二选一：**异常态**必须提供重试入口；**无权态**不提供重试（重试无意义），以「请联系系统管理员调整权限」说明不可重试原因（见 §312、§219；`AppStateBlock variant="permission"` 默认 `retry:false`） | 异常态“{对象}加载失败”+“请检查网络或稍后重试”；无权态“无权限{操作/查看对象}”+“请联系系统管理员调整权限” |

状态互斥与降级规则：

- 每个独立数据区域同一时间只能有一个顶层状态；`ready / loading / empty / error` 不得在同一区域并排或叠加渲染。刷新按钮的 loading、`v-loading` 遮罩等属于当前请求的操作反馈，不扩展顶层状态。
- 首次进入或当前区域没有可复用旧内容时，使用 `AppStateBlock loading` 的骨架占位，不在空白内容上只放转圈遮罩，也不和 `empty` 同时出现；已有数据刷新过程中可以暂时保留旧 `ready` 内容并覆盖 `v-loading`，避免闪回空态，但请求失败后必须由 `error` 接管受影响区域并隐藏旧内容，不能继续显示“异常态 + 旧 ready 内容”。表格由 `AppDataTable` 统一执行该分流，消费页不得重复实现。
- `error` 不只依赖全局 toast；主内容、侧栏列表、详情面板、表格局部依赖失败时，失败区域必须留下页内错误态和“重试”或明确原因。
- 自动轮询、后台保鲜等非用户发起的静默刷新失败，若当前内容仍有明确时间范围且可继续使用，可以保持 `ready` 并使用轻量更新提示；此时不得同时渲染整区 `AppStateBlock error`。用户主动刷新、筛选、分页、排序或切换查询口径失败不属于该例外。
- 无权限是 `error` 的语义变体，运行时使用 `AppStateBlock state="error" variant="permission"`，不得扩展为第五种顶层状态。
- `empty` 表示“成功返回但无数据”，不能混用来表达接口失败、无权限或加载中。
- `ready` 必须呈现业务价值：至少有主体数据、摘要指标、当前过滤条件或来源说明之一；不要用大段说明文字替代真实数据展示。
- 四态切换不得改变外层 slot 的稳定尺寸；布局系统组件种类的 `loading-state`、`empty-state`、`error-state`、`skeleton` 只作为系统组件和预览语义，业务页面运行时优先复用真实组件和 Element Plus 状态能力。

### 空状态

空状态的视觉事实源在 `frontend/src/styles/global.css`，后续新页面必须复用同一套类名和全局表格空态，不允许临时手写不同图标、不同字号或不同位置。

- `el-table` 无数据时默认使用全局表格空态：居中图标 + 当前表格文案。新页面优先使用表格默认空态；需要补充操作时，`<template #empty>` 使用 `app-table-empty` / `app-table-empty__description` 只提供业务文案和按钮，不得嵌套 `el-empty`、自绘图标或另一套布局。该规则由 `table-system.spec.ts` 契约测试拦截。
- 非表格的大区域空态使用 `<el-empty class="app-empty" description="..." />`。
- 小面板、抽屉、弹窗内空态使用 `<el-empty class="app-empty app-empty--compact" description="..." />`。
- 很小的内嵌区域使用 `<el-empty class="app-empty app-empty--tiny" description="..." />`。
- 不适合放图标的原生小表格、日志区、选择器下拉空态使用 `class="app-empty-inline"`。
- 文案按业务场景保留差异，例如“运行后在这里展示筛选结果”“暂无历史版本”“请选择左侧角色”；统一的是图标、字号、颜色、间距和居中方式。
- 避免同一区域出现两套空态：若表格后面还需要自定义 `el-empty`，必须用 `v-if` 在有数据时才渲染表格，无数据时只渲染一套统一空态。

### 加载态与异常态

- 页面级初始化失败用 `el-result icon="warning"`，标题使用“{页面对象}加载失败”，副标题说明“请检查网络或稍后重试”，`#extra` 放一个主按钮“重试”。
- 用户主动刷新、筛选、分页、排序或切换查询口径失败时，受影响区域使用同一 `error` 结构接管并隐藏旧内容；标题可按动作使用“{对象}刷新失败”，但不得把紧凑错误块堆在旧表格、旧图表或旧摘要上方。
- 局部依赖失败只阻断该区域，不阻断已可用的其他区域；例如主表可加载但摘要失败时，摘要区显示局部错误态，主表保持可用。
- 403 / 无权限态不能伪装为空态；标题使用“无权限查看{对象}”或“无权限维护{对象}”，副标题说明联系管理员或切换账号（即不可重试原因）；不放“重试”按钮（重试对无权无意义，实现见 `AppStateBlock variant="permission"` 默认 `retry:false`）。
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

弹窗文案容量规则（解决窄弹窗内占位/说明文字被截断）：

- 弹窗宽度只使用语义档位（420 / 440 / 460 / 480 / 520 / 560 / 640 px），窄档位只放短字段；宽度不足时优先压缩文案、调整字段布局或改用 `PageDrawer`，不靠继续加宽弹窗绕过。
- 控件内提示文案（`placeholder`、单选/复选后缀、`el-tooltip` 内容）控制在 15 字以内；超 15 字的长说明移出控件，放在字段 `label` 下方的辅助说明行（`*` 起头）或 `el-form` 底部的补充说明行。
- `el-select` 等多选控件的占位只写「动作 + 对象」（如「输入代码或名称搜索」）；「可多选」「留空=默认值」等可操作语义放到字段辅助说明行，不拼进 `placeholder`，占位文案在输入框内不换行、不省略。
- 单选项文案过长时拆为「主文案（行内）+ 补充说明（辅助行）」，不让单选标签撑满或截断。
- 验收自检：弹窗内最宽控件的可用宽度 = 弹窗宽度 − 左右内边距（约 48px）− `label-width`；文案超宽就压缩文案或改布局，不能靠改 `width` 硬撑。
- 同页长说明分散到各字段且不重复；新写弹窗时优先复用字段内短占位 + 行内辅助说明的结构，不复制 `IngestView` 中已修正的长占位写法。

### 设置抽屉

- 页面设置抽屉三段**固定顺序**：`布局` → `组件设置` → `业务选项`；每段**仅在该页有对应内容时渲染**。`布局` 恒在，`组件设置` 仅当 registry 声明了可配置组件字段，`业务选项` 仅当页面提供 `#business` 插槽；不得为了形式完整强插空段。
- 抽屉两条配置通道的分工：**组件设置段**收「组件展示能力」字段——列显隐、默认排序、每页条数、区域高度、默认 tab（判定：它改的是组件怎么展示）；**业务选项段**收「业务默认/偏好」——模式、口径、开关、筛选默认（判定：隔几天再来，用户希望它保持这样吗）。**持久化是进抽屉的必要条件而非充分条件**；「主区已有同义控件」也不是排除理由——真正的排除边界是语义：查询口径/本次研究对象（关键字、日期范围、方案选择、运行参数）属会话态，不进抽屉。
- `布局` 和 `组件设置` 可由元数据自动渲染；`业务选项` 由页面声明，仅承载页面记忆或业务偏好。
- 设置项必须有默认值、来源展示、合法值域和重置路径；页面设置抽屉 footer 的「恢复默认」必须同时重置页面业务偏好、页面布局/组件用户层，以及抽屉自身 `size/defaultCollapsed` 用户偏好。
- 「组件设置」段与系统管理→布局配置→**页面布局**编辑器的「组件特性」**共用唯一渲染器** `components/ComponentAutoSettings.vue`（抽屉=user 层、页面布局编辑器=page 层，经 `layer`/`slotIds`/`allowedLayersOf`/`collapsibleSlot`/`clearable` 适配），不得另写第二套组件特性表单。
- 折叠规则统一：每个 slot 为可折叠组（`SettingsGroup` level 2；编辑器聚焦单 slot 时仅作标题锚点不折叠）；多行清单类特性（列显隐）为可折叠子组（level 3）；单字段为叶子不折叠。深层标题字号随层级递减但不低于正文。
- **页面可改动属性单向默认机制**：抽屉/组件配置层只提供**默认值**，页面主区可直接交互改动的属性必须用独立会话 ref 承载；重复的默认值投影统一复用 `composables/useDefaultedSessionValue.ts`，组件配置分页统一经 `composables/useComponentPageSizeSession.ts` 完成默认值解析、会话投影、归页和重载，**页面改动只进会话态、绝不写回默认值**——刷新/重进页面后重新应用抽屉默认。这样「默认」才有意义：用户临时改动不污染长期偏好。禁止可写 computed 或主区 `v-model` 直写持久层；设置抽屉内的默认值编辑，以及带有明确“设为默认”语义的显式操作，才是默认值持久化入口。初始化优先级固定为：先完成页面业务偏好与远端布局默认值水合，再应用 URL query、返回列表态等显式会话恢复，最后才接受用户交互；迟到的默认值不得清除已经恢复的显式会话覆盖。URL query/分享链接恢复只写会话 ref，不触碰默认。**会话态清单**（本就该会话级、也不进抽屉）：纯查询条件（关键字/日期口径/方案选择）、业务资产选择、运行参数（如回测日期、所选方案和当次执行参数）。
- **新增属性登记判断（开发闭环必经步骤）**：新增页面、改造页面或给页面/组件新增任何可交互属性后，必须逐一回答三个问题再收尾——①该属性是否需要跨会话记住（默认值/偏好）？②需要时登记到哪条链路（业务偏好进 `usePageSettings` defaults + `#business` 插槽；组件展示字段按 §7.3 进 `consumedComponentFields`/`componentMeta`/`COMPONENT_FIELD_DEFS`/后端规则）？③需要默认值时页面是否已按上条单向机制消费（读默认初始化会话 ref、不写回）？三问任一答「是」却未落地，即视为本次改动未完成。反向同样成立：不再需要或语义失效的已登记项（如已被主区表单覆盖、关闭后无法再开启的开关）必须及时下线，不得在抽屉里堆积死项。

## 5. Layout Principles

所有业务页面走可配置布局系统：页面声明 `PageLayout`，通过 `<LayoutHost>` 渲染，不手写 `.v-page` / `.v-grow` / 视口高度。配置合并顺序固定为：

`default < preset < page < user`

| 层 | 职责 | 维护入口 |
|---|---|---|
| `default` | 页面原型、slot、组件代码默认值 | `frontend/src/layout/pageRegistry.ts`、组件代码 |
| `preset` | 风格 token、预设级组件默认、响应式默认枚举 | 系统管理 → 布局配置 → 预设管理 |
| `page` | 单页面默认布局旋钮与组件默认值 | 系统管理 → 布局配置 → 页面布局 |
| `user` | 当前登录用户的布局、组件和业务偏好 | 页面设置抽屉；PG `layout_user_config`、PG `user_preference` |

用户层以 PostgreSQL 为权威：页面布局和组件字段写入真实 pageKey 的 `layout_user_config`，页面业务偏好、主题、导航模式、K 线偏好和跨页面设置抽屉偏好写入 `user_preference`。回测日期、方案选择和当次运行参数只属于会话态，不得写入用户偏好。localStorage 只允许作为未登录/离线 fallback、旧偏好迁移源、登录前主题读取和临时交互态，不得作为登录用户配置权威。

### 5.1 新建或改造页面

新页面和布局改造必须先选择原型，再声明 slot、组件种类、滚动归属、`growMain` 和配置字段。优先使用脚手架生成骨架；需要手写时也必须从 `pageRegistry.ts` 的 `PageLayout` 单一事实源开始，不从旧页面复制临时 CSS。

```bash
cd frontend
npm run scaffold-page -- --pageKey <key> --label <中文名> --archetype <原型> --route /path --view XxxView
```

可复制流程、计划块和页面登记格式见 `agent-works/configurable-layout-system/page-template.md`。本文件只保留稳定原则、原型边界和机器登记区块。

### 5.1.1 搜索/筛选行边框

列表页的搜索/筛选交互行统一用卡片边框承载：`<el-card shadow="never" class="filter-card">` 包裹 `AppControlRow`，`filter-card` 使用全局样式（`margin-bottom: 0`，卡片体内边距 `var(--app-space-3) var(--app-space-4)`）。禁止搜索行裸 div 无边框散落在页面。工具栏/操作按钮行不强制套卡。

### 5.1.2 页面间距承载

页面标题行到主内容区的间距由布局系统统一承载，页面禁止叠加私有间距：

- 操作区内块间距 = `.lh-action` 的 `gap: var(--app-space-3)`（12px）。
- 页面级间距 = `.v-page` 的 `gap: var(--layout-page-gap)`，由预设 `pageGap`（默认 14px）运行时覆盖。
- `.page-head` / `.page-title-row` / `.title-row` 等标题行选择器**禁止再声明 `margin-bottom` / `padding-bottom`**，否则与 `.lh-action` gap 叠加成双倍间距（曾出现 26px/28px）。标题行必须包在 `<div class="lh-action">` 内，间距交给 gap。
- 页头容器（`.page-head` / `.page-toolbar`，以及页头同义换名宿主 `.audit-head` / `.dict-page-head`）统一 `align-items: flex-start`：动作按钮（按钮组、设置抽屉触发钮）与标题顶部平齐，锚定标题顶这条固定水平线，避免随副标题有无或长短浮动。禁止用 `flex-end` / `center` 让动作区随「标题+副标题」整块下沉或居中（曾造成跨页按钮高度不一致）。页头右侧子容器 `.page-head-actions`（承载 32px 控件组）保持 `align-items: center` 不变。内嵌 `HelpTip` 的标题行选择器 `.page-title-row` / `.title-row` 按 §3 保持 `align-items: center`，不在本条范围内。无页面标题的导航工具栏（如板块详情的 `.detail-nav`）不适用本条。该约束由 `typography-spacing-system.spec.ts` 强制。

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
3. 能放下时富余空间给主表/主图；当剩余高度不低于其有效 `minH` 时，主内容区本身不滚动，由组件内部滚动；只有剩余高度低于 `minH` 时，主内容区才整体滚动兜底。
4. 多组件只有满足宽度、阅读顺序和组件可重排条件时才重排；否则保持业务顺序。
5. 单个大表不做多列重排，直接表体内滚。

### 5.4 主内容区策略

`LayoutHost` 根据 schema 自动选择主区策略：

| 策略 | 触发 | 行为 |
|---|---|---|
| `grow` | 单组件、非整区滚动型 | `VAdaptiveGrow` 应用有效 `minH`：余量足够时主组件填满且内部滚动，余量不足时主内容区滚动兜底 |
| `scroll` | 单组件整区滚动型 / 多组件无主成长组件 | 主内容区内部滚动 |
| `mixed` | 多组件且恰一个 `growMain` | `VMixedGrow` 保持固定块自然高，并对主成长组件执行同一 `minH` 条件滚动规则 |
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
- 新增系统组件 kind 必须维护组件能力事实源；新增 Web 配置字段必须同时维护字段配置事实源和页面消费事实源。只有 kind 语义能力发生变化时才同步修改 `COMPONENT_CATALOG`，不得为凑登记机械添加能力 key。

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
- 后端 `layout_config.py` 同步字段规则和归属校验；同名字段在不同组件种类中值域不同时，静态值域必须按 `(component kind, field)` 维护，不得只按字段名合并。
- 消费页面在 `pageRegistry.consumedComponentFields` 登记。
- 页面通过 `componentMeta` 提供安全枚举（列、可交互排序字段、tabs 等）。
- `componentMeta.columns` 只声明列显隐候选，不负责生成业务表格列；每个候选 key 必须在消费页面进入真实显隐判断并控制对应列或列内业务片段。该正向消费关系由 `pageRegistry.spec.ts` 契约测试强制，禁止“设置里可勾选、页面没有可渲染节点”的假配置。
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
| `chart` | `minHeight` | page/user | 由独立详情行情的图表 slot 登记；控制包含标题和完整画布的区域高度，页面必须保留内部图表安全下限；随视口填充的主从工作台和流程内局部图表不机械套用 |
| `tabs` | `defaultActive` | page/user | 仅在页面登记 tabs slot 且 `componentMeta.tabs` 提供候选时渲染 |
| `settings-drawer` | `size`、`defaultCollapsed` | preset/page/user（全局偏好持久化） | `supportsPageSettings !== false` 的 registry 页面共享 `settings` overlay slot；具体 slotId 不作为存储判定条件 |
| `settings-drawer` | `bodyScroll`、`collapsibleSections` | preset/page | `supportsPageSettings !== false` 的 registry 页面共享 `settings` overlay slot |
| `config-panel` | `collapsibleSections` | preset/page | `config-system.configPanel` |
| `config-panel` | `defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | preset/page/user | `config-system.configPanel`；分区候选以 `componentMeta.collapseSections` 为准 |

`usePageSettings` 只保留页面业务态/页面记忆，不承载通用组件展示能力。
`settings-drawer` 的用户层只允许 `size/defaultCollapsed`；字段元数据将其 `userPersistence` 标为 `global-preference`，跨页面个人值写入 `user_preference(global/settings-drawer)`。后端布局写接口按 `(component kind, field)` 反向拒绝这两项进入 `layout_user_config`，不绑定具体 pageKey 或 slotId。`bodyScroll/collapsibleSections` 只能由 preset/page 层控制。其他未声明 `userPersistence` 的 user 字段默认写页面布局用户层。
页面可改动的组件字段，组件配置层只提供默认值，页面读默认初始化会话态、改动不回写，规则见「设置抽屉」节「页面可改动属性单向默认机制」。

### 7.4 页面 / 组件 / 布局变更维护闭环

具体维护矩阵、计划块和验收命令统一维护在 `agent-works/configurable-layout-system/page-template.md`。本节只保留长期规则：

- 页面、布局原型、系统组件种类、组件字段、真实复用组件、按钮图标体系或业务偏好发生变化时，必须同步对应代码事实源、页面消费事实源、文档入口和测试。
- 非公开 View 路由、`pageRegistry` 和页面登记 marker 必须以 `pageKey` 双向一致；registry 页面必须真实渲染 `LayoutHost`、通过 `getPageLayout` 消费布局，并复用 `AppStateBlock` 承接非 ready 状态。
- 已有稳定真实实现的系统组件种类必须由消费页面实际导入并渲染对应复用入口；当前强映射包括 `data-table` / `wide-table` → `AppDataTable + AppTableColumn`、`settings-drawer` → `PageSettingsDrawer`、`config-panel` → `ConfigGroupForm → ConfigPanelSection`。`toolbar`、`section`、`tabs` 等组合型种类不要求虚构一对一空壳组件。
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
| `1100×620` | 应用外壳不得滚动；固定区保持可用；余量达到组件 `minH` 时组件内部滚动，否则主内容区滚动兜底 |
| `1366×768` | 主操作、状态列、时间列、核心业务列优先可见；次要说明列截断或进详情 |
| `1440×900` | 默认桌面验收视口；表格、抽屉、工作台应无重叠和无文本溢出 |
| `1920×1080` | 不无限拉宽说明文本；宽屏富余给主表、主图或多列概览 |

响应式原则：

- `pageRegistry.responsiveProfile` 是页面类型的目标响应式画像，用于说明设计意图，不等同于已完成浏览器验收；实际列数和重排由 `layout.responsive` 决定，运行时滚动由 `LayoutHost` 决定，最终可用性以关键视口 E2E 为准。页面布局工作台必须显示为“目标响应式策略”，不得把画像名称当成已验证结论。
- 响应式配置必须有 `minWidth=0` 的基础断点。
- 单个大表、大图、大列表不靠多列重排解决高度问题，优先内部滚动。
- 多组件平级块只有在都允许重排、无强阅读顺序且最小宽度满足时才进入 `columns`。
- `workbench` 类页面采用固定分析块 + 主成长区，放不下时由主区域兜底滚动。
- 抽屉宽度使用 `PageDrawer` 的受控档位：`sm=320px`、`md=360px`、`lg=440px`、`xl=560px`、`xxl=clamp(640px, 60%, 820px)`、`wide=clamp(560px, 46%, 760px)`。`wide` 只用于日志、字段差异、长 JSON 等需要横向阅读且应随页面内容区增长的场景；`xl` 用于固定宽度的复杂详情和组件预览；`xxl` 用于资产搜索等需要比 `xl` 更宽横向空间的复杂详情，窄屏下仍有限度下探。页面只传语义档位，不得私传 px 或百分比；页面设置抽屉只开放 `sm/md/lg`。
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

该区块只作为机器读取和轻量人工索引，不承载组件字段、slot 配置、列、排序或业务状态事实源。新增 registry 页面必须写入 `pageRegistry.ts` 并以相同 `pageKey` 出现在下方 marker 内；`pageRegistry.spec.ts` 会校验受控路由、registry 与 marker 的 `pageKey` 双向一致，`scaffold-page` 负责同步生成三处登记。

<!-- page-registry:start -->
| pageKey | 页面 | 原型 | 可编辑旋钮 | 组件清单 |
|---|---|---|---|---|
| `board` | `BoardView`（每日榜单） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`wide-table` / nested:`chart` |
| `screen` | `ScreenView`（策略筛选） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `stocks` | `StocksView`（个股查询） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`wide-table` / nested:`wide-table` / nested:`chart` / footer |
| `data-quality` | `QualityView`（数据质量） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `data-schedule` | `ScheduleView`（任务调度） | `detail` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`data-table` |
| `data-ingest` | `IngestView`（数据采集） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`data-table` |
| `data-overview` | `OverviewView`（数据概览） | `workbench` | `density` | action:`toolbar` / main:`kpi-grid` / main:`stat-strip` / main:`tabs` / nested:`wide-table` / nested:`data-table` |
| `backtest` | `BacktestView`（策略回测） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` |
| `training` | `TrainingView`（盘感训练） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`chart` |
| `trade-discipline` | `TradeDisciplineView`（交易纪律） | `workbench` | `density` | action:`toolbar` / main:`tabs(growMain)` / nested:`section` / nested:`section` / nested:`data-table` / overlay:`detail` |
| `stock-detail` | `StockDetailView`（个股详情） | `detail` | `density` | action:`toolbar` / main:`detail` / nested:`chart` |
| `config-score` | `ConfigView`（评分规则） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `config-trade` | `ConfigView`（买卖指标） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `config-tech` | `ConfigView`（技术指标） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` |
| `config-system` | `ConfigView`（系统设置） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`tabs` / nested:`config-panel` |
| `user-manage` | `UserManageView`（用户管理） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `role-manage` | `RoleManageView`（角色管理） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` |
| `menu-manage` | `MenuResourceView`（菜单与功能） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`wide-table` |
| `tenant-manage` | `TenantManageView`（租户管理） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `layout-presets` | `LayoutPresetsView`（预设管理） | `list` | 暂无 | action:`toolbar` / main:`data-table(growMain)` |
| `layout-pages` | `LayoutPagesView`（页面布局） | `workbench` | 暂无 | action:`toolbar` / main:`tabs(growMain)` |
| `layout-components` | `LayoutComponentsView`（系统组件） | `detail` | 暂无 | action:`toolbar` / main:`section` |
| `audit-log` | `AuditLogView`（审计日志） | `list` | `density` | action:`toolbar` / main:`kpi-grid` / main:`filter-bar` / main:`wide-table` / overlay:`detail` |
| `data-dictionary` | `DataDictionaryView`（数据字典） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`simple-list` / nested:`data-table` / overlay:`form` / overlay:`form` / overlay:`dialog` |
| `sectors` | `SectorsView`（板块行情） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`wide-table` / nested:`chart` |
| `sectors-detail` | `SectorDetailView`（板块详情） | `detail` | `density` | action:`toolbar` / main:`detail` / nested:`chart` / nested:`data-table` |
<!-- page-registry:end -->

除 `supportsPageSettings=false` 的预设管理、页面布局、系统组件三个平台管理页外，registry 页面必须有 `settings-drawer` overlay slot。三个管理页只管理系统配置，不开放或持久化个人页面设置。组件字段、slot 细节和候选项事实源在 `COMPONENT_FIELD_DEFS`、`pageRegistry.consumedComponentFields` 和 `componentMeta`，不要在本表重复维护。

## 10. Scope & Exceptions

- 本项目桌面工作台优先；响应式规则覆盖低高度和常见桌面宽度，移动端不是当前验收重点。
- 当前没有独立品牌设计稿；视觉方向以本文件的金融科技研究终端规则和现有品牌组件为准。
- 品牌字标、登录主视觉、图表 tooltip、代码值和极窄 badge 允许局部排版特例；新增业务页面不得复制这些特例作为普通排版。
- 页面登记区块通过 `<!-- page-registry:start/end -->` marker 被 `pageRegistry.spec.ts` 和 `scaffold-page` 读取；marker 是机器契约，不要移除。
