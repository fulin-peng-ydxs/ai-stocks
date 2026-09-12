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
- K 线 tooltip 左右切换必须同时满足光标进入当前浮层水平占用区、浮层与当前蜡烛高低价像素矩形发生二维重叠；蜡烛矩形由当前 ECharts 实例实时换算。任一条件不成立或无法取得像素矩形时保持左侧，禁止仅凭光标位置或 candlestick 参数猜测遮挡。
- `StockChartWorkspace` 的 Canvas 不会随 CSS 变量自动重绘；必须只通过 `stock-chart/useStockChartTheme.ts::useStockChartTheme()` 消费响应式股票画布主题，不得自行组合 `useTheme`、`useLayoutPreset`、`themeRevision` 和 `stockChartTheme()`。该入口统一覆盖明暗切换、预设 key 切换和当前预设同 key 后端覆盖更新。本条适用于个股详情、板块行情、盘感训练和回测的股票画布；其它图表不会自动继承，扩大适用范围时必须同步完成运行时改造和独立回归。
- `StockIntradayChart` 与日 K 共用上述股票画布主题：价格使用主题主色，均价复用 MA5 身份色，昨收使用中性虚线并以 `0%` 标注；分钟成交量统一以手展示，量能标题同步展示当前全部分钟点之和，量柱优先按有效分钟开收方向取金融涨跌色，源端开盘为零时按上一分钟收盘判断，首点无法判断时使用中性色。价格与量能数值轴固定在左侧，价格区右轴按昨收映射涨跌幅；共享十字光标 tooltip 继续展示分钟明细，不另做指标卡或页面私有色板。日 K 与分时必须共同消费 `app-stock-chart-frame` 外框、`StockChartPanelHeader` 标题栏、`StockChartLegend` 图例项、`StockChartPanelDivider` 面板分隔和 `buildStockVolumeBarSeries()` 量柱构造；折线统一使用短线标识，柱状序列统一使用小柱标识，标签使用中性文字、当前值使用序列身份色。分时上图标题为“分时”并承载价格/均价图例，下图标题为“量能”，两图之间使用独立的 8px 双边框分隔区，不允许拿上下绘图区的边界网格线冒充分隔线；标题栏是图表容器的 DOM 结构，不得通过 ECharts `title`、`graphic` 或页面私有边线仿制。标题栏与绘图区保留紧凑安全间距，量能图区顶部留白不得小于 12px；分时两个横轴不重复绘制坐标轴边线，价格与量能纵轴网格不显示最小值和最大值边界线，底部时间轴只显示 `09:30`、`11:30`、`15:00` 三个市场时点，不把午休两端拼成复合标签。涨跌停边界不得额外扩展纵轴造成顶部无意义留白。
- 非股票 ECharts 统一通过 `components/chartTheme.ts::useEChartsTheme()` 消费画布背景、坐标、文字、tooltip 和序列语义色；该入口与股票主题共同复用 `useResponsiveEChartsTheme()`，覆盖明暗、预设 key 和同 key 后端覆盖更新。`EquityChart`、`GrowthChart` 已纳入，不再作为固定明暗色板例外；新增 Canvas 主题消费者不得只监听 `isDark` 或在组件内维护第二套基础色板。
- 股票分时与日 K 的绘图区必须统一隐藏左右数值轴边框，价格与量能水平网格线统一使用实线；只有昨收 `0%` 基准线保留虚线语义，不得把普通网格线整体改为虚线。
- 分项评分徽章使用 `--score-high-*` / `--score-mid-*`，低分使用弱底色和占位文字色；评分热力格（`SubScoreBars`）、训练评级、买卖标记等**内联 style 颜色的组件统一经 `components/chartTheme.ts::useStatusColorPalette()` 消费当前生效 token**（强弱梯度=跌绿→成功→警示→危险→涨红；买卖=主色蓝/警示橙；评级 S/A/B/C/D=警示/成功/主色/中性/危险），不得在该组件内维护私有绿橙红色阶或 Element 默认色。
- 页面提示、弱文本、占位文本优先使用 `--app-warning-text`、`--app-muted-text`、`--app-placeholder-text`；确属 Element Plus 标准状态时可直接用 `var(--el-color-*)`。
- **颜色单一事实源**：任何状态/金融/评分/评级/买卖颜色只允许来自 `LAYOUT_PRESETS` token（经 `--el-color-*`、`--market-*`、`--app-*-text`、`--score-*` 或 `useStatusColorPalette()` 消费）；页面、组件、Canvas fallback 一律与 `balanced` 预设同值，禁止出现 `global.css` 或组件内平行硬编码的第二套色板。图表 fallback（`chartTheme.ts`/`chartUtils.ts`）也必须与预设当前值保持一致并随色板演进同步更新。
- 普通操作文字与禁用操作文字分别使用 `text`、`textMuted`；二者按 WCAG 线性相对亮度计算的差值必须 `≥ 0.06`。这是文字层级阈值的唯一数值事实源，预设保存和运行时合并均须守卫。
- 预设运行时必须同步覆盖 Element Plus 语义色的基础色、RGB 通道、`light-3/5/7/8/9` 与 `dark-2` 派生色；`error` 与项目危险色同源。按钮、链接、提示、分段控件、焦点和禁用态不得回退到组件库默认蓝绿橙红色阶。**金融涨跌色与状态/评分文本色不走 el 的 light-*/dark-2 派生，而是直接消费预设 `marketUp`/`marketDown`/`success`/`warning`/`danger` 主色（亮色模式该主色即为提彩后的鲜亮值），避免派生工艺造成哑光。**

预设规则：

- 登录页与工作台必须同源：同一 `light/dark` 下，登录右侧交互区基础色等于工作台 `pageBg`，登录卡片可见色等于工作台 `surfaceBg`；白天和夜间的 `pageBg`、`surfaceBg` 分别保持相同，页面与卡片主体通过边框、间距和交互态表达层级，不用常驻底色色块互相分层。结构化信息内部可使用下述 `--app-section-bg` 区分标签格、KPI 与摘要组，不得借此改变图表或卡片主体底色。该关系以 `frontend/src/layout/themeSurfaces.ts` 为底色事实源，并由 `presets.spec.ts` 守卫。
- 登录或注册成功时，登录页当前可见的 `light/dark` 是本次会话的明确模式：进入工作台前先暂存，鉴权后优先写回用户偏好；只有登录页没有形成待同步模式时，才允许远端用户偏好覆盖本地模式。
- 登录页恢复为修改前的全屏左右品牌布局：左侧承载品牌字标、趋势轨迹与“看见趋势，先于共识。”主视觉文案，右侧承载独立登录/注册卡片；页面结构、文案层级与交互以 `LoginView.vue` 的恢复版本为准。
- 登录页可保留原有光晕、网格、轨迹、透明和模糊等品牌装饰，但装饰层不能改变 `themeSurfaces.ts` 和 `presets.ts` 定义的基础底色事实源；按钮、焦点、品牌强调、趋势轨迹、Logo 渐变和光晕必须消费当前运行时 `primary`，禁止遗留独立硬编码主题色。
- 登录页与应用外壳的「复盘啦」必须直接复用 `BrandMark` 的同一几何、尺寸、渐变、文字与描边定义；组件不提供 `login/shell` 场景变体，消费容器不得覆盖 `--brand-*` 形成第二套字标。只有容器不足 `184×52px` 时允许按原始宽高比整体缩放。Logo 渐变由运行时 `primary` 派生，因此新增并启用颜色预设后，登录页与工作台会同步更新。
- `balanced`（澄空蓝）使用鲜明蓝色信号；页面、边栏、卡片、悬停、边框和文字属于固定中性基础表面，只受明暗模式控制，禁止预设覆盖。预设允许覆盖 `primary/success/warning/danger`、共享形态、响应式默认和组件默认策略。
- 外观抽屉必须保留视觉预设区：当前只有一套时显示唯一选中项；预设管理新增并启用自定义项后，无需改前端代码即可出现在抽屉并驱动运行时。登录页不提供预设管理入口。
- 外观抽屉必须提供独立的「界面比例」：100% 表示设计 token 的原始尺寸，不表示某台屏幕的自动推荐值。`auto` 使用操作系统已经折算后的当前屏幕可用 CSS 宽高，以 `2560×1440` 可用面积作为原始设计尺寸的自动参考点，按面积的低指数连续曲线双向微调；指数由当前视觉预设的 `responsiveDefaults.autoScaleResponsiveExponent` 提供，在预设管理编辑，默认 `0.10`、范围 `0～1`、步长 `0.01`，`0` 表示自动保持 100%；缺项或非法运行时值回退默认，保存、切换、停用回退与首屏缓存恢复必须同步应用，手动模式和手动比例不随预设改变；小屏缩小以保留总览、大屏放大以改善远距离阅读，自动范围限制为 `90%~110%`。不得枚举设备型号、分辨率档位，也不得把物理像素、`devicePixelRatio` 或浏览器页级缩放当成目标比例。`custom` 允许在 `50%~150%` 内按 1% 连续微调，首次从自动切换时继承当前比例，避免视觉跳变；滑块调整自动保存当前显示器可用 CSS 宽高与比例档案，宽高均在档案 `±15%` 内时使用综合距离最近项，`5%` 内重复调整更新原项，无匹配时回退最近一次自定义比例，档案只属于当前用户且不直接暴露管理界面。「恢复100%」进入自定义 100% 并更新当前尺寸档案。该能力通过应用根级 `--app-display-scale` 与倒数画布尺寸，将 `#app` 以左上角为原点整体 `transform`，统一缩放字体、控件、间距、图表容器和应用内抽屉；滑块不重复显示会遮挡模式选项的数值气泡。禁止在 `body` 使用 CSS `zoom`，避免 ECharts 指针坐标和 Teleport 浮层定位偏移。布局宽高、滚动量和组件配置必须使用 `client/offset` 布局像素；只有命中测试、指针位置和视口对齐使用 `getBoundingClientRect/clientX/clientY`，两套坐标相减后必须通过共享换算工具转回布局像素。缩放后必须触发依赖尺寸的画布重测；脱离 `#app` 挂载并依赖触发器坐标的 Tooltip、Popover、Select、DatePicker 等 Popper 浮层必须保持浏览器视口坐标和 100% 自身比例，禁止再次 `scale` 导致箭头、选项或日期面板偏离触发器；Dialog、Drawer、MessageBox 的 body 级遮罩复用倒数尺寸与整体 transform，内部面板不得重复缩放；全屏抽屉高度和弹窗视口上限必须服从该画布。Message、Notification 按浏览器视口堆叠，保持 100% 自身比例。
- 启用预设的名称、明暗语义强调色及自动缩放指数通过登录公开配置下发，并写入首屏安全缓存；登录页与工作台必须共同消费 `setRuntimePresetSources()`，不得各自解析或维护另一套预设。公开配置禁止携带页面、组件或其他平台布局字段。
- 调整基础表面必须同步维护 `light`、`dark`、`themeSurfaces.ts` 与 `presets.spec.ts`；调整预设能力必须验证后端目录、运行时选择和固定表面不受覆盖。
- 页面设置抽屉保留 `32%` 黑色遮光层，用于明确浮层焦点和点击外部关闭边界；遮光层属于临时交互状态，不参与主题底色定义，抽屉内容面与页面常驻容器仍必须使用中性明暗表面。
- `surfaceHover` 只用于 hover、选中或明确可操作控件状态；常驻的 KPI、指标标签格、查询摘要和配置分组等内部信息分区统一使用 `--app-section-bg`。该语义变量由主题运行时映射当前中性分区色，当前视觉值与 `surfaceHover` 同源但职责独立，页面不得直接借用悬停 token，也不得自行调深；图表画布、卡片主体和工作区内容面继续使用 `surfaceBg`。

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
| 数字强调 | `--app-font-size-data` 16px / 600 / 24px；大 KPI 可用 `--app-font-size-kpi-lg` 26px / 700 / 32px；单组唯一主数值可用 `--app-font-size-kpi-xl` 32px / 700 / 38px | KPI、收益、评分、排名、需要横向比较的数字 |

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
- 单块纯文本说明优先进入 `HelpHint` 的 tooltip；需要标题、分段、列表、示例或同时解释多个独立要点时使用 `HelpTip` 的 popover。`HelpHint` 长文必须在共享浮层中换行并限制视口内最大宽度，不得撑成横跨页面的单行提示。`HelpTip` 的默认插槽只放 `HelpTipItem`，每个独立说明项固定两层：传 `question="具体问题文本"` 时，第一行显示该问题文本并由组件追加冒号；传 `warning` 时，第一行固定显示“注意：”并消费当前视觉预设的 `--app-warning-text`。第二行的全部内容无论长短都必须使用语义化 `ul/li`，由组件统一渲染为以 `.` 开头的无序列表。同一项必须且只能在 `question` 与 `warning` 中选择一个，调用方不得自行拼接标签、冒号、列表符号、颜色或项间距。页面上只保留必要短标签，不以字符数作为两者的硬边界。
- 组件内提示、说明、空状态、校验文案必须按容器宽度排版，避免长句硬塞一行；必要时分行、缩短文案或交给 tooltip / popover 承接，不得挤压主操作区或造成文本重叠。
- 按钮、标签、抽屉标题、表格控件中的文字不得溢出容器。
- 金融数字按列右对齐或按业务组件一致处理，避免同列数字参差。
- 同一行并列的对象识别块、摘要组、状态块等同层信息块，外层默认在交叉轴居中；表单和工具栏继续遵守各自的控件基线规则。只有明确包含多行标题/说明、且右侧操作需要钉住首行的页面页头使用顶部对齐。不得把页面页头的顶部对齐规则套用到单行摘要或指标组。
- 行情摘要统一消费 `StockQuoteSummary` 与 `stockQuoteSummaryHtml()`：无标签最新价主列垂直居中，可在主值下展示涨跌额与涨跌幅辅助行，并以主题边框和信息列分隔；列宽由内容自动撑开，禁止固定像素列宽。调用方通过 `rowsPerColumn` 决定每列行数，通过 `columnGap=standard|relaxed` 选择标准或宽松列距，默认 `standard` 以保持既有消费者不变；个股详情显式使用 `relaxed`。K 线和个股详情头部每列四行，分时每列两行；开盘位于信息首项。所属行业等对象关系不得混入行情数值字段，统一由所属板块面板承载。K 线浮层、分时弹窗顶部与个股详情共享同一字段分组模型，不再使用全局 `.app-metric-*` 等宽指标网格；个股详情仅关闭 K 线内容浮层，仍保留十字光标、标题联动、缩放与分时下钻，其他消费者默认开启。
- 股票代码、配置 key、日志字段、接口路径等技术标识可使用 `--app-font-family-mono`，但仅限值本身，不把整段说明改成等宽体。
- 不使用英文 eyebrow、kicker 或类似小标题作为纯装饰；页面层级使用清晰的中文标题、副标题和业务状态。股票代码、MACD、HTTP 方法等真实业务或技术标识不属于装饰英文。

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

### 3.2 Inline Information Unit Rules

同行内容必须先判断是一个连续文本，还是多个独立信息单元；明显不是同一个连贯内容单位的信息不得直接相邻。统一按以下契约表达：

- 同一自然语言句子使用中文标点，不拆成标签，也不靠空格制造停顿。
- 同一对象的复合身份或同级短字段使用带两侧空格的中点 ` · `，例如 `600519 · 贵州茅台`、`选股规则 · 买入规则 · 操作时间`；中文界面不得使用英文句点 `.` 充当同行信息分隔符。
- 主文本后附状态、分类、来源、板块或其他独立标签时，必须使用 `.app-inline-info` 包裹；默认间距为 `--app-space-control-gap`（6px），主信息与次级元信息需要更明显分组时叠加 `.app-inline-info--md` 使用 8px。
- 时间、对象名称等主信息与紧随标签在表格中需要保持一行时叠加 `.app-inline-info--nowrap`；主文本必须允许省略，标签 `flex: none` 保持完整。普通内容区允许容器自然换行，换行后仍保留统一 gap。
- 图标与文字、标签与标签、正文与状态标签均通过容器 `gap` 分隔；禁止依赖模板换行、普通空格、`&nbsp;`、相邻节点间的源码空白或页面私有固定值 `margin-left/right` 修补。用于两端对齐的 `margin-left: auto` 不属于间距修补，可在明确布局容器内保留。
- 推荐层级为“主信息正文 > 次级弱文本 > 状态标签”；标签用于增加离散语义，不能取代主信息。
- Element Plus Select、Popover、Tooltip 等 Teleport 浮层中的复合选项必须声明唯一 `popper-class`，通过该全局边界设置行内布局与 gap；不得使用无法命中 `body` 下浮层的 scoped 后代选择器。
- 标准表单下拉和日期面板默认位于触发器下方，只在下方左右对齐间回退；共享控件与页面特殊选择器统一消费 `floatingPlacement.ts` 的位置契约。只有经明确交互证明的场景才允许覆盖到其他方位。

### 3.3 Tag, Badge & Chip Rules

标签体系采用“Element Plus 基础几何 + 语义规则 + 领域复用单元”。规范定义目标一致性；实现与本节冲突时应修正实现，不将已有差异视为新的设计分支。

| 密度层级 | 几何 | 使用边界 |
|---|---|---|
| 紧凑 | `el-tag size="small"`，20px | 高密表格中的辅助状态、筛选结果和次级属性；不承载多项复合数据 |
| 标准 | Element Plus 默认尺寸，24px | 普通内容区的分类、对象关系和主要状态，以及表格中需要完整识别的主要业务标签 |
| 强调 | `el-tag size="large"`，32px | 仅用于低密度、需要显著识别的状态组；不进入普通表格、筛选栏或密集摘要 |
| 依附 badge | `--app-font-size-micro`，不单独承担主体信息 | “最相关”等依附于主体标签的次级标记 |
| chip | 领域组件定义的自适应胶囊 | 评分拆分、对比队列、已选对象等复合或可操作单元；不伪装成普通状态标签 |

- 标签只承载需要快速扫描、筛选或判断的离散属性；普通说明、时间和连续句子使用正文或弱文本。
- 尺寸由所处区域的信息密度和标签层级决定，不由页面偏好决定；同一语义在同等密度下使用同一尺寸。表格中的主要业务标签或需要内部省略的复合标签使用 `.app-table-tag-shell` 统一为 24px 基线；辅助状态使用 20px 紧凑档，不要将所有表格标签一律放大。
- 多标签容器使用 `display:flex + flex-wrap` 和 `--app-space-control-gap`；标签保持内容宽度及 `max-width:100%`，禁止使用 `1fr`、`width:100%` 或固定宽度把标签拉成卡片。
- 标签正文使用 `--app-font-size-caption`；11px 只用于依附 badge，业务主体不得低于12px。名称过长时在标签内部省略，并由 `AppOverflowTooltipHost` 承接完整内容。
- `plain` 用于中性分类和对象关系，`light` 用于当前选中或需要增强识别的状态，`dark` 仅用于少量高优先级状态；不为装饰改变 effect。
- 金融涨跌使用 `--market-up-color` / `--market-down-color`；系统状态使用 Element Plus `type`；字典色和股票分组色分别通过 `dictTagStyle()` 与 `stockGroupTagStyle()` 收口，页面不复制颜色、透明度或边框算法。
- 稳定业务语义出现在第二个消费点时，必须根据变化原因收口为领域组件、helper 或 schema；不创建只转发 `el-tag` 属性的万能 `AppTag`，也不强行合并语义或生命周期不同的标签。已有领域组件以下方“真实复用组件清单”为唯一目录。

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
- 系统不会根据页面模板里的 Vue 标签自动推断系统组件 kind；`pageRegistry` 是组件实例登记事实源。页面把一个已有系统组件种类作为独立布局区、成长区、滚动区或可配置实例使用时，必须登记对应 slot；只作为另一个真实组件内部实现细节、且没有独立布局或配置语义的子组件不得登记假 slot。
- 真实 UI 行为优先复用真实复用组件；当同类控件在两个及以上页面出现，或承载全局交互规则时，必须登记到下方“真实复用组件清单”。
- 真实组件只有需要进入布局配置、系统组件页、页面设置抽屉或页面布局编辑器时，才新增或关联系统组件种类。
- 新开发 Vue 组件时先判断它是页面私有业务片段、业务域复用组件还是全局真实复用组件；复用组件必须维护组件清单、消费页面和测试。只有需要被布局或组件配置体系识别时，才继续新增系统组件 kind；只有存在真实可消费的 Web 可配置属性时，才继续登记 `COMPONENT_FIELD_DEFS` 并完成四层配置闭环。
- `COMPONENT_CATALOG` 是系统允许的组件种类与能力词汇表，允许先登记当前尚无页面消费者的 kind，供 schema、预览和后续布局选型复用；“假配置”指 `COMPONENT_FIELD_DEFS` 暴露了组件实例并未真实读取应用的 Web 字段。已有真实复用组件时仍禁止页面复制同类控件行为。

系统组件页信息维护规则：

- `LayoutComponentsView` 展示的组件名称、说明、最低尺寸、滚动归属、成长/重排能力和专属特性来自 `COMPONENT_CATALOG`；这些信息变化时必须优先更新 `frontend/src/layout/components.ts`，不要在页面内硬编码第二套说明。
- `configCapabilities` 是英文能力 key 摘要，用于系统组件页展示组件具备的能力，不等同于“已开放 Web 配置字段”；不要为了展示把它本地化成另一套中文映射。
- 组件 kind 的语义变化时，必须同步检查 `components.ts` 的 `label`、`description`、`configCapabilities`，`componentSchemas.ts` 的 config shape，`componentPreview.ts` 的预览归类，以及 `schema.ts` 中该 kind 的说明。
- 系统组件页的可视化预览是给开发和验收人员对照组件形态、状态语义、文案与稳定占位的规范样板，不是业务页面截图，也不证明消费页面已经完成接入。`ready` 可使用代表性原型；`loading / empty / error` 必须直接复用 `AppStateBlock`，不得在预览层维护第二套状态视觉。
- 只有真实可被页面设置、页面布局或预设消费的字段，才进入 `COMPONENT_FIELD_DEFS` 和后端 `layout_config.py` 字段规则。页面登记某个组件 slot 后自动继承该 kind 的字段；候选型能力由 `componentMeta`、结构型能力由 slot `config`、明确例外由 `fieldApplicability` 判定是否适用。
- 系统组件页必须按“组件字段 × 消费页面 slot”展示自动继承、管理员策略关闭或实例不适用状态；不适用项必须显示可追溯原因，不能只展示组件级字段总表而掩盖页面漏接。
- 改动系统组件信息后至少运行相关布局测试；改动预览四态时必须验证预览复用 `AppStateBlock`；涉及前端源码时同时运行构建。

核心真实复用组件清单：

| 真实组件 | 路径 | 用途 | 系统组件关系 | 使用规则 |
|---|---|---|---|---|
| `PageSettingsDrawer` | `frontend/src/components/PageSettingsDrawer.vue` | 统一页面设置抽屉运行时组件 | 对应 `settings-drawer` 种类；`size/defaultCollapsed` 的用户偏好走 PG `user_preference`，`bodyScroll/collapsibleSections` 只允许 preset/page 层 | `supportsPageSettings !== false` 的 registry 页面统一使用，禁止页面另写第二套设置抽屉 |
| `PageSettingsTrigger` | `frontend/src/components/PageSettingsTrigger.vue` | 页面设置统一入口 | 触发 registry 页面中的 `settings-drawer` | 仅 `pageRegistry.supportsPageSettings !== false` 的真实消费页面显示；平台布局管理页不开放个人设置，不登记假入口 |
| `PageDrawer` | `frontend/src/components/PageDrawer.vue` | 页面级抽屉边界组件 | 无直接系统组件种类 | 页面打开的设置、详情、日志抽屉统一挂载到 `LayoutHost` 内容区；宽度只传 `sm/md/lg/xl/xxl/wide/full` 语义档位，禁止页面私传 px/%；`wide` 仅供日志、字段差异和长 JSON 等宽内容，`xxl` 供资产搜索等需更宽横向空间的复杂详情，`full` 仅供窄屏承载桌面同等复杂工作台；禁止直接覆盖应用顶栏与导航 |
| `LayoutHost` | `frontend/src/layout/components/LayoutHost.vue` | registry 页面统一布局、slot、滚动和 overlay 运行时宿主 | 消费 `PageLayout` 中登记的系统组件种类与区域 | 所有 registry 业务页面统一消费；页面不得绕过宿主手写页面外壳、主成长区、滚动归属或 overlay 边界 |
| `ComponentAutoSettings` | `frontend/src/components/ComponentAutoSettings.vue` | 组件特性唯一渲染器 | 按 slot kind 自动消费 `COMPONENT_FIELD_DEFS`，再结合 `componentMeta` / slot `config` / `fieldApplicability` 判定实例适用性 | 设置抽屉 user 层与页面布局编辑器 page 层共用；候选项可由页面按当前业务上下文传入运行时 meta 覆盖，避免不同面板的分区混显；布尔、枚举、数值、字符串和静态字符串多选控件按字段元数据通用渲染，动态候选字段复用专用安全渲染器 |
| `SettingsGroup` | `frontend/src/components/SettingsGroup.vue` | 设置抽屉的分组容器 | 无直接系统组件种类 | 页面设置抽屉分组优先复用；不直接用于主内容区配置面板 |
| `PageSettingSection` | `frontend/src/components/PageSettingSection.vue` | 页面设置业务选项分区 | 无直接系统组件种类 | `PageSettingsDrawer` 的业务选项统一复用；不得在页面内复制标题、说明和分区间距 |
| `ConfigPanelSection` | `frontend/src/components/config/ConfigPanelSection.vue` | 主内容区配置面板的可折叠分组容器 | 对应 `config-panel` 种类；读取 `collapsibleSections`、`defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | 系统设置等主面板配置分组优先复用；配置项中可作为单块纯文本理解的说明/默认值放 `HelpHint`，需要结构化排版时改用 `HelpTip`；一级组说明在组头展示，二级分区说明随分区内容一起展开/收起 |
| `PageSegmented` | `frontend/src/components/PageSegmented.vue` | 页面设置和业务偏好的分段选择控件 | 无直接系统组件种类 | 业务选项、组件设置中的枚举选择优先复用；整组选项使用连续底板与基础边框，选中项在组内浮起，不把选项渲染成彼此分散的独立按钮；页面级模式/范围切换使用 `tone="primary"` 跟随系统主色，设置抽屉枚举保持默认中性色；固定操作区使用 `small`，设置抽屉与表单使用默认尺寸；每个选项必须通过 `aria-pressed` 暴露程序化选中状态，多组并列使用时由消费页提供可访问名称 |
| `PageSettingsApplyButton` | `frontend/src/components/PageSettingsApplyButton.vue` | 设置抽屉采用当前页面值的统一按钮 | 无直接系统组件种类 | “使用/采用页面当前值”统一复用，固定为主题主色 `primary + plain` 和整行宽度；不得在字段组件内复制按钮颜色、宽度和边距样式 |
| `BoardTaskScopeFields` | `frontend/src/components/data/BoardTaskScopeFields.vue` | 板块采集范围和分阶段参数组 | 无直接系统组件种类 | 数据采集与任务调度的板块任务统一复用；模式、板块类型、采集内容、增量当日退级和成分强刷文案/参数不得在消费页再维护第二套 |
| `CurrentDayFallbackField` | `frontend/src/components/data/CurrentDayFallbackField.vue` | 增量行情的当日退级开关 | 无直接系统组件种类 | 个股与板块增量采集统一复用；保持普通表单背景与复选框样式，仅在支持当日退级的增量方案中展示 |
| `StockCodeMultiSelect` | `frontend/src/components/data/StockCodeMultiSelect.vue` | 股票代码/名称远程搜索与多选输入，统一已选项保留、批量粘贴、大小写规范化、稳定去重、候选错误和搜索竞态保护 | 无直接系统组件种类；作为业务表单内的股票范围控件 | 个股采集范围、数据概览逐股体检、个股走势关联板块调度统一消费；允许保留用户手工输入并由业务提交接口做最终合法性校验，候选加载失败不得清空已选值；消费页只响应标准 `v-model` 与 `change`，不得复制远程搜索、粘贴拆分或去重逻辑 |
| `StockIngestScopeFields` | `frontend/src/components/data/StockIngestScopeFields.vue` | 个股一体化采集的场景、范围和安全参数组 | 无直接系统组件种类 | 数据采集与任务调度统一复用；方案、股票范围、日期、年限、并发、增量当日退级、风险提示和执行摘要不得在消费页维护第二套；底层步骤有依赖时使用场景方案，不开放任意组合 |
| `ResultMaintenanceTaskFields` | `frontend/src/components/data/ResultMaintenanceTaskFields.vue` | 结果失效与重算任务的目标范围、日期和股票范围字段组 | 无直接系统组件种类 | 数据采集与任务调度统一复用；页面只传任务类型和表单值，不复制目标范围候选、股票范围分支或任务说明 |
| `PageToggleRow` | `frontend/src/components/PageToggleRow.vue` | 页面设置和业务偏好的开关行 | 无直接系统组件种类 | 业务选项、列显隐、布尔设置优先复用 |
| `AppControlRow` / `AppControlItem` | `frontend/src/components/AppControlRow.vue`、`frontend/src/components/AppControlItem.vue` | 页面工具行、查询行和参数行的通用横向控件容器；控件行默认按控件自然宽度排列，空间不足时换行，不自动拉伸填满；控件项把标签和控件作为一个整体换行 | `filter-bar`、`toolbar` 等系统组件种类的真实渲染基础 | 多个输入、选择器、按钮组成的横向行优先使用 `AppControlRow`；存在“说明文字 + 控件”时必须用 `AppControlItem` 包裹，避免标签和控件被拆到不同行；选择器与其浏览、搜索等内置附属动作属于一个复合控件，在支持的桌面宽度内必须保持同行，空间不足时由复合控件整体随控件项换行，不得只把附属动作挤到下一行；只有明确需要均分或撑满时才传 `fill` 或让具体 `AppControlItem` 设置 `grow` |
| `AppTabToolbar` | `frontend/src/components/AppTabToolbar.vue` | Tab 内容区的统一操作栏，左侧承载筛选或命令，右侧承载当前面板的简短说明，并在空间不足时自然换行 | `tabs` 下属 `filter-bar` / `toolbar` 的真实组合外壳，内部复用 `AppControlRow` | Tab 标签已表达面板名称时，内容区不得重复标题；操作和筛选统一放 `#actions`，说明统一放 `#description`；没有操作时允许仅右对齐展示说明，不得为填空新增无业务意义的按钮 |
| `AppIconButton` | `frontend/src/components/AppIconButton.vue` | 全站纯图标操作按钮，统一可访问名称、尺寸、圆角、悬浮、聚焦、禁用、loading 和语义色 | 无直接系统组件种类 | 顶栏工具、抽屉关闭、刷新、页面设置等仅图标操作统一复用；必须传 `label`，异步纯图标操作使用 `AppIconButton` 的 `loading`，外层 `el-tooltip` 承载长说明时关闭原生 `title`；图形使用 Element Plus 图标或项目既有 SVG，禁止页面手写 Unicode 符号按钮 |
| `HelpTip` / `HelpTipItem` | `frontend/src/components/HelpTip.vue`、`frontend/src/components/HelpTipItem.vue` | 全站结构化“？”说明入口与说明项，统一键盘可达、两层结构、点号列表和警告语义色 | 无直接系统组件种类 | `HelpTip` 默认插槽只放 `HelpTipItem`；每项必须且只能传 `question="具体问题文本"` 或 `warning`：前者显示具体问题文本并自动追加冒号，后者固定显示黄色“注意：”；第二行无论内容长短都使用 `ul/li`，组件统一渲染为 `.` 开头的无序列表；禁止页面私写 `<br>`、冒号、列表符号、段落外边距或警告色 |
| `RelatedBoardCell` | `frontend/src/components/RelatedBoardCell.vue` | 个股行业走势/概念走势冠军的业务域复用单元格，统一名称、结构化相关性说明、低可信提示、首次计算、历史日期保护和权限感知导航 | 无直接系统组件种类；作为既有 `data-table` / `wide-table` 业务列内容 | 个股查询普通表与分组表、每日榜单、策略筛选统一消费；调用方只传完整摘要和 `industry|concept` 类型，不拆散日期或异常判断；只展示单个冠军，名称统一使用小号朴素标签，指标最多四位小数；首次任务等待或执行时显示“计算中”，四个表格通过 `useRelatedBoardFirstLoad`、天梯通过自身状态适配共同消费 `useAsyncResultPolling` 的绝对超时、串行请求、迟到响应和卸载清理；表格后台轮询只合并走势摘要，不得切整表 loading、替换原行对象或连带刷新股票分析区；无冠军、摘要不可用和历史不匹配均 fail-closed 显示“—”，不为不同缺失原因增加页面标签或悬浮说明；只有 `sectors:view` 才渲染 `/sectors/:code` 链接，且链接点击必须阻止表格行详情冒泡；四个表格 slot 通过统一列 key 消费现有列显隐，不复制私有 popover 或任务轮询，不依赖任务中心管理权限 |
| `BuiltinOptionRow` | `frontend/src/components/BuiltinOptionRow.vue` | 可创建下拉项的统一行结构，区分内置项和可操作自定义项，并统一标签截断、来源提示与尾部动作对齐 | 无直接系统组件种类 | 交易纪律的内置/自定义原因和买卖类型选择统一复用；内置项只显示中性“内置”提示，自定义项的删除等动作通过默认插槽注入，不在消费页复制选项行布局 |
| `AppSummaryDisclosureCard` | `frontend/src/components/AppSummaryDisclosureCard.vue` | 高密编辑器的通用折叠摘要卡外壳，统一序号、标题、元信息、单行摘要、工具区、展开边界与键盘可访问 disclosure | 无直接系统组件种类 | 规则、操作事实等“列表摘要 + 展开编辑”场景统一复用；业务状态和命令通过插槽注入，组件不持有启停、删除或校验等领域逻辑；展开编辑区保持基础表面并用边框与主色边线表达层级，不使用常驻填充色形成嵌套色块；整块摘要使用带完整 `aria-expanded`、`aria-controls` 和可访问名称的专用原生 disclosure button，不得在消费页复制卡片结构 |
| `TradeDirectionGroupGrid` | `frontend/src/components/trade-discipline/TradeDirectionGroupGrid.vue` | 交易纪律中按买入、卖出方向并列组织卡片清单，统一分组标题、说明、动作区和桌面降级布局 | 无直接系统组件种类；仅承载交易纪律方向分组 | 买卖规则与操作事实统一消费；分组即方向事实源，组内卡片不得再展示重复方向选择器；规则或成交的领域状态留在调用方，通过分组动作和内容插槽注入；桌面宽屏保持买入在左、卖出在右，紧凑桌面视口降为单列，不在消费组件复制方向分组结构与样式 |
| `RuleSummaryCard` | `frontend/src/components/trade-discipline/RuleSummaryCard.vue` | 买入、卖出和选股规则的紧凑摘要卡，基于 `AppSummaryDisclosureCard` 组合规则启停与动作区 | 无直接系统组件种类；仅承载交易纪律规则编辑 | 同类规则统一复用；默认只展示摘要并一次展开一项，动作通过插槽注入；不得把规则启停语义下沉到通用卡片外壳 |
| `TradeDisciplineSectionPanel` | `frontend/src/components/trade-discipline/TradeDisciplineSectionPanel.vue` | 交易纪律编辑器的统一分区面板，承载标题、说明、摘要、展开编辑区和分区动作 | 无直接系统组件种类；仅承载交易纪律编辑分区 | 规则、操作事实和履约编辑的同层分区统一复用；领域字段与动作通过插槽注入，不在消费页复制分区外壳、标题层级和间距 |
| `AppRowActions` | `frontend/src/components/AppRowActions.vue` | 表格行操作列和列表项操作区的统一动作组，按权限过滤、单行排列、动作颜色层级、禁用/加载态展示、轻量“更多”菜单收纳和**宽度自适应折叠** | 无直接系统组件种类 | 表格 `label="操作"`、自绘表格行、列表项和编辑器条件行的行内按钮组优先复用；首个未显式指定语义色的行内高频动作使用主色，普通次要动作使用常规正文色，禁用态使用弱文本色并满足语义 token 规则定义的文字层级阈值，停用/禁用/终止/删除等破坏性动作使用危险色；动作始终清晰可见，不对整组做透明度弱显；低频或危险动作可设置 `placement: 'more'`，更多入口必须由 Element Plus 点击浮层承接定位、层级、点击外部关闭与 Esc 关闭，菜单命令继续使用 Element Plus 按钮并呈现真实 loading，不得在页面内手写多行按钮、原生命令按钮或自建全局浮层监听。**宽度折叠契约**：单动作或仅需“更多”入口的列声明 `role="action-compact"`，96px 是默认下限；两个及以上候选动作声明 `role="action"`，144px 是默认下限；各行按实测按钮宽度向所属列上报最低可用组合，整列取当前已渲染行最大值向上扩展。两类操作列默认统一居中表头与单元格，确有业务对齐理由时才显式覆盖。单动作最低完整显示；多动作最低保留两个操作入口，可由两个直接动作或“首个直接动作 + 更多”构成，“更多”本身计作一个入口；除调用方明确把全部动作设置为 `placement: 'more'` 外，禁止退化为仅“更多”。操作列不参与表格富余空间分配，余量留给名称、描述等内容列；超过最低组合后仍按实际可用宽度尽量展示更多直接动作，装不下的动作自动收进“更多”菜单，不硬截断；`inline-limit` 是行内数量硬性上限；显式 `placement: 'more'` 的动作恒入更多；可用宽度或按钮实测宽度不可用时使用文字估算与纯数量逻辑兜底 |
| `SystemBuiltinTag` | `frontend/src/components/SystemBuiltinTag.vue` | 全站“系统内置”来源标记，固定使用灰色文字、灰色描边和中性浅底 | 无直接系统组件种类 | 菜单、功能点、角色、租户、布局预设、技术指标和系统内置方案等来源标记统一复用；文案固定为“系统内置”，不追加对象名称或保护规则说明；与对象名称或标识并列时统一放在对象后面，独立的来源/类型字段保持标签单独展示 |
| `AppDataTable` | `frontend/src/components/AppDataTable.vue` | 数据表格/宽表运行时外壳，统一表头排序布局、表体内滚、分页承载、加载分流、空态插槽、行点击样式和成长/嵌入模式 | 对应 `data-table`、`wide-table` 种类；读取页面传入的排序、分页、列显隐等消费结果 | 页面中的数据表格统一复用；`loading && data.length === 0` 自动显示 `AppStateBlock` 骨架，有旧数据刷新时保留表格并使用 `v-loading` 遮罩；主列表默认成长，抽屉、展开行和局部明细等非主表显式使用 `embedded`；`#empty` 只补充业务文案与操作并复用 `app-table-empty*`，禁止嵌套 `el-empty` 形成双图；`wide-table` 默认常显 Element Plus 内部滚动条，禁止页面再给 `el-table__body-wrapper` 添加第二层横向滚动；禁止用 `fill` 布尔值绕过主表语义；复杂单元格继续由业务页通过列插槽声明 |
| `AppTableColumn` | `frontend/src/components/AppTableColumn.vue`、`frontend/src/components/table/adaptiveColumnWidth.ts` | 表格列运行时组件，根据结构类型、字段名和标签推导语义角色，以稳定字符权重结合排序/筛选控件计算弹性最小宽，并统一渲染单行表头及同行元信息 | `data-table`、`wide-table` 的稳定列宽、内容对齐和表头能力；不是用户可配置字段 | 页面表格列统一复用，禁止传 `width/min-width`；确有歧义的动态标签只传 `role`；日期、单位或短口径摘要传 `header-meta`；单元格主内容前存在紧凑控件时传 `leading-controls`，组件统一预留宽度并让表头对齐主内容；自定义 header slot 只用于复选、帮助入口等真实交互结构；数值事实只维护在 `ADAPTIVE_COLUMN_RULES` |
| `AppOverflowTooltipHost` | `frontend/src/components/AppOverflowTooltipHost.vue`、`frontend/src/components/overflow/overflowTooltip.ts` | 全站省略内容的单一悬浮提示宿主，事件委托检测原生 CSS 省略和表格复合内容视觉溢出 | 无直接系统组件种类；由应用根节点挂载一次 | 任何 `text-overflow: ellipsis` 内容只有在真实截断时自动显示完整文本，页面和业务组件不得手工配置列级 `show-overflow-tooltip`、私建 `ResizeObserver + title` 或复制 tooltip；已有结构化 popover/tooltip、操作列及动作组保持自身交互并自动跳过，避免双层浮层或把隐藏测量内容拼成提示 |
| `AppStateBlock` | `frontend/src/components/AppStateBlock.vue` | 页面和组件的加载、空、异常、无权反馈块，统一 `ready / loading / empty / error` 四态中的非 ready 呈现、重试入口和尺寸档位 | 对应布局系统中的 `loading-state`、`empty-state`、`error-state`、`skeleton` 语义，但作为真实运行时复用组件消费 | 主加载失败、局部列表失败、无权态、非表格空态和稳定骨架占位优先复用；空态同时提供 `title + description` 时由组件统一展示两层信息，不得让说明覆盖标题或由页面私写重复结构；表格数据的 loading/empty 仍优先由 `AppDataTable` / `el-table` 承接，不在页面手写第二套错误块、空态图标或重试布局 |
| `AppWorkspacePane` | `frontend/src/components/AppWorkspacePane.vue` | 主从工作区单栏的统一栏级外壳，承载标题、可选辅助行、操作区和自适应内容区 | `master-detail` 左右栏的内部面板 | 个股查询、每日榜单、连板天梯、板块行情通过 `MarketMasterDetailWorkspace` 共同消费，个股详情与板块详情直接用于各自两栏；栏级标题统一高度、边框和间距，蓝色小号辅助行承载稳定的业务类型，当前日期或结果批次作为主标题展示；双栏默认仅主栏显式传入 `primary` 使用主色浅背景，次栏保持中性背景，禁止两栏同时强调或由页面复制背景样式；不与图表内部 `StockChartPanelHeader` 合并；图表范围、分栏收展等栏级操作通过 `actions` 插槽承载；紧凑抽屉已有标题时可隐藏重复栏头 |
| `AppStatusNotice` | `frontend/src/components/AppStatusNotice.vue` | ready 内容仍可继续使用时的轻量持久提示，统一信息、成功、警告、失败语义、紧凑尺寸和可选动作 | 不属于第五种顶层状态；作为 ready 的辅助消息层 | 缓存数据过期、后台同步失败、本地降级、只读说明和局部依赖不完整但主体仍可用时统一复用；不得替代区域不可用时的 `AppStateBlock error`，同一原因不得同时显示 notice 与阻断错误态；动作使用明确的重新加载、刷新状态等文案，不使用实体主按钮抢占页面主任务 |
| `StockChartPanelHeader` / `StockChartLegend` / `StockChartPanelDivider` | `frontend/src/components/stock-chart/StockChartPanelHeader.vue`、`frontend/src/components/stock-chart/StockChartLegend.vue`、`frontend/src/components/stock-chart/StockChartPanelDivider.vue` | 股票图表面板的共享标题栏、图例项与独立分隔区，统一 32px 高度、标题层级、水平对齐、序列形态标识、图例文字层级以及双边框分隔 | 股票画布内部结构，不直接映射布局系统组件种类 | `StockChartWorkspace` 的 K线、MACD、量能面板和 `StockIntradayChart` 的分时、量能面板统一消费；调用方以 `items` 提供图例，不复制短线/小柱标识、标签、当前值、边框、内边距或响应式间距；相邻图区使用独立 `StockChartPanelDivider`，只有可拖动工作区启用 `interactive`，不得借用绘图区边界网格线或页面私有边线仿制 |
| `StockChartWorkspace` | `frontend/src/components/stock-chart/StockChartWorkspace.vue` | 行情 K线、量能和可选 MACD 的纵向联动工作区，统一日期轴、光标、显式缩放同步、局部状态、买卖标记和可访问高度分隔线 | `chart.minHeight`（仅由固定高度详情实例消费） | 个股详情、个股查询/每日榜单/连板天梯 K线模式、板块行情 K线模式、板块详情、盘感训练和回测交易回放统一消费 K线/量能/MACD，并通过共享图表设置选择图表二、图表三；工作区统一上报自身 CSS 布局宽高，供共享偏好层匹配内部高度比例档案，消费页不得读取物理屏幕或自行维护尺寸监听；盘感训练等固定行情区域通过 `chart.minHeight` 配置整体高度，个股详情、板块详情和列表等随视口填充的主从工作台不套用固定高度字段，并显式启用可用高度适配，使面板在低高度工作区采用共享紧凑下限而不被外层裁切；其它实例仍以标准可见面板最小高度之和加分隔线作为硬下限；所有实例按底部面板真实画布高度使用同一套日期轴与缩放规则，空间足够时显示标准可视滑动条，空间不足时隐藏可视滑动条但保留内部缩放，页面不得传入私有轴间距；行情与指标按交易日和所选截止日对齐，MACD 局部失败不得阻断 K线/量能；三图统一预留 64px 左右边界，轴值必须经过领域格式化、不得用原始浮点长度挤压绘图区，K线左轴显示价格、右轴按当前查询区间首根 K 线的前收映射区间涨跌幅，量能与 MACD 数值轴统一在左侧；K 线浮层的单日涨幅始终使用该根 K 线自己的前收，板块区间接口必须携带区间开始日前一交易点收盘，不能让区间第一根因裁剪丢失涨跌幅；只有 K线显示定宽行情 tooltip 和唯一光标轴日期气泡，tooltip 默认停靠左侧且避开左侧价格轴，仅当光标进入其实际占用范围时切换到右侧，右侧停靠同样避开百分比轴；位置切换不得产生位移动画，只使用短促显隐过渡且遵守 reduced-motion；量能和 MACD 普通柱线只保留联动光标与标题当前值，不显示行情内容浮层、日期气泡或标题日期，MACD 信号 item 悬停例外显示信号类型与完整日期；三图标题值与实际序列必须复用盘感训练共享色板，标题指标单项不得无限扩宽，柱宽按 K线、量能、MACD 明显递减，底部日期标签不得被缩放滑块遮挡；任一图的 `dataZoom` 必须显式同步给其余可见图并在主题重绘后保留；画布必须监听预设系统在完整 CSS token 写入后发布的主题修订版本，覆盖明暗、预设 key 和同 key 后端覆盖变化，分隔线遵守 reduced-motion；光标跟随指标值不得设置 `aria-live`，避免三组高频播报；需要图外行情摘要联动时消费统一 `activeBarChange` 事件，离开画布收到 `null` 后恢复最新行情，页面不得另监听 ECharts；消费页面不得再拼装第二套多图联动、尺寸档案和分隔线逻辑 |
| `StockIntradayDialog` / `StockIntradayChart` | `frontend/src/components/stock-chart/StockIntradayDialog.vue`、`frontend/src/components/stock-chart/StockIntradayChart.vue` | 日 K 蜡烛下钻的共享分时弹窗与双绘图区，统一按需请求、取消/迟到响应、范围/空/错误/部分状态、行情摘要、价格/均价/昨收和分钟量能联动 | 无直接系统组件种类；作为股票画布的按需覆盖层 | 只在个股详情与 `StockAnalysisPanel` 的 K 线模式启用；板块、盘感训练和回测消费者保持关闭。`StockChartWorkspace` 默认不得响应点击，只有显式开启时才为 candlestick 提供点击光标并发出交易日，均线、量能、MACD 与缩放不得触发。弹窗顶部统一展示股票身份、突出收盘，并辅助展示涨跌幅、高/低和成交额；身份与指标组垂直居中，指标内部统一标签行和数值行基线，四个指标使用紧凑固定列宽，禁止按内容任意拉开间距；主体只包含价格/均价/昨收和分钟成交量两个绘图区，外框、上下分隔、标题和图例复用股票画布公共入口，分时图例中的价格与均价默认显示最后一个真实分钟点，悬浮时联动显示光标所在分钟值；并统一预留 64px 左右轴边界，价格左轴显示价格、右轴按昨收显示涨跌幅，量能数值轴在左侧且单位固定为手，昨收位于价格轴正中且只标 `0%`，价格轴不得同时显示精确边界标签与内部自动刻度，共享时间轴与十字光标，午休不补假点；内容缩放与底部可见缩放条必须同步两图并在主题/尺寸重绘后保留范围。`ready` 展示、`partial` 保留真实点并复用 `AppStatusNotice` 横向警告，`out_of_range`/`no_data` 用 `AppStateBlock`，503 就地重试；打开才请求，关闭、切股、换日和重复点击必须取消或隔离旧响应，不自动轮询 |
| `StockChartRegion` | `frontend/src/components/stock-chart/StockChartRegion.vue` | 固定高度股票图表的外层区域，统一接收组件实例总高度、测量可选标题区并把剩余可用高度传给工作区 | `chart.minHeight` + `chart.stockChart` 的当前组合 | 盘感训练等声明固定图表高度的页面统一消费；页面只传外层总高度及当前图表组合，禁止再手工减标题高度或把总高度直接当工作区高度；容器根据真实标题高度和边框自动计算内容高度，可见面板硬下限不足时扩展外层而不得裁切；个股与板块详情等主从工作台随剩余空间成长，不使用本容器 |
| `MarketDetailHero` | `frontend/src/components/MarketDetailHero.vue` | 行情详情页的对象身份、摘要、元信息与上下文操作头部 | 无直接系统组件种类；承载详情页头部内容 | 板块详情与个股详情共同消费；不渲染英文装饰 eyebrow，状态标签、操作、行情摘要、元信息和上下文条分别进入具名插槽；页面不得复制 hero 外壳、背景、间距或响应式规则；默认保持两端布局，摘要需要紧随身份区时显式使用 `asideAlign="start"` |
| `MarketBoardTag` | `frontend/src/components/MarketBoardTag.vue` | 行业与概念名称、同日涨跌和走势相关性的统一领域标签 | 无直接系统组件种类；内部消费 Element Plus 默认尺寸 `el-tag` | 个股详情所属板块面板中的相关行业与概念共同消费；使用默认 24px 控件档，宽度随内容且允许外层换行，不使用等宽网格或固定宽度；名称保持中性文字，仅涨跌幅数值消费金融涨跌色，统一相关标记、内容省略、键盘焦点和可选板块详情地址 |
| `StockBoardMembershipPanel` | `frontend/src/components/StockBoardMembershipPanel.vue` | 个股所属板块行情标签，统一同日涨跌、走势冠军标记和权限感知导航 | `section` | 走势最相关行业标签位于卡片标题旁，其余概念标签直接在正文自然换行，不显示“所属行业”“所属概念”分组字样；接口必须批量返回个股行情日对应的板块涨跌幅，无同日行情保持空值；板块项统一消费 `MarketBoardTag`，不使用 `1fr` 拉满或页面私有固定宽度；有 `sectors:view` 时才进入板块详情并携带可信返回地址 |
| `AppSplitWorkspace` | `frontend/src/components/AppSplitWorkspace.vue` | 通用左右分栏工作区，统一比例计算、尺寸档案、可访问分隔条、单栏回退和窄屏全屏抽屉 | 作为 `master-detail` 的内部真实组件，消费 `masterRatio`、`masterRatioProfiles` | `MarketMasterDetailWorkspace`、个股详情与板块详情共同消费；业务标题、列表、图表和辅助卡均由调用方插槽提供。默认允许 `30%–70%`，实际栏宽、上报比例与持久化样本必须一致，并仅在内容安全宽度冲突时偏离比例边界；两栏各自承接滚动；工作区不超过 `720px` 时只渲染主栏，次栏由调用方操作打开共享全屏抽屉，抽屉填充容器和基础内边距由组件统一提供；页面禁止复制 ResizeObserver、拖拽、键盘调整、比例档案或抽屉基础样式 |
| `MarketMasterDetailWorkspace` | `frontend/src/components/MarketMasterDetailWorkspace.vue` | 行情列表与走势分析区的双栏业务外壳；基于 `AppSplitWorkspace` 补充分栏与分析区收展，列表栏外壳委托 `AppWorkspacePane`，保留既有公开属性、事件与紧凑抽屉控制接口 | `master-detail.masterRatio`、`master-detail.masterRatioProfiles` | 个股查询、每日榜单、连板天梯、板块行情共同消费；列表按工作台容器的配置比例连续计算，系统默认 `45%`、允许配置 `30%–70%`，仅在列表至少 `360px` 或分析区至少 `240px` 的真实内容安全边界触发时偏离配置比例，不设置列表固定像素上限；工作区自身布局宽度不超过 `720px` 时统一退化为列表单区，选择对象后由共享全屏抽屉承载分析区，页面不得再维护私有紧凑抽屉。用户拖动和键盘调整只改会话值；“使用页面当前比例”同步更新 `masterRatio` 并保存 `{width, ratio}` 尺寸档案，上方默认占比必须立即回显，同页同用户可保存多项，当前宽度在档案宽度 `±15%` 内时取相对差最小者，`5%` 内重复保存更新原项，无匹配时回退 `masterRatio`；明显换屏后重新匹配，双击分隔条恢复当前匹配或默认比例。历史 `masterWidth` 只兼容读取、不参与布局；列表空间不足由内部横向滚动承接；个股类页面继续通过共享选择状态维护当前观察与对比队列，禁止复制页面私有状态机 |
| `MarketCompareMetricStrip` | `frontend/src/components/MarketCompareMetricStrip.vue` | 行情走势对比的指标摘要与切换条；单项固定为指标名称在上、指标值在下并左对齐，统一激活态、涨跌语义色、键盘按钮语义和紧凑视口降级 | 无直接系统组件种类；由行情分析区承载 | 板块行情、个股查询、每日榜单共同消费；消费页只提供指标元数据和值，不复制指标条结构或样式；个股页面只接累计及 5/10/20/30/60 日涨跌，不接板块资金流、成员涨跌或领涨股口径 |
| `CompareQueueRail` | `frontend/src/components/CompareQueueRail.vue` | 走势对比的对比对象队列条，统一队列标签、chip（名称/激活/错误/移除）与“最多 N 个”上限提示 | 无直接系统组件种类；由行情分析区承载 | 板块行情、个股查询、每日榜单共同消费，禁止页面内再写第二套队列 chip；chip 为 `role=button` 容器承载激活（点击 + Enter/Space，`.self` 避免焦点在移除钮时连击激活），名称为纯 `span` 继承 chip 颜色（激活/悬浮随主色变化），移除用 `AppIconButton`；遵守按钮契约——不引入原生 `<button>`，也不用 `el-button` 包裹名称（其特异性会覆盖继承色）；消费页只提供归一化 `{ key, label, active, error }` 列表与 `activate`/`remove` 事件，上限提示文案按对象（板块/股票）传入；队列顺序稳定（进入先后），激活/切换主观察只移动高亮不重排，该状态机由共享纯函数 `frontend/src/utils/compareQueue.ts` 维护，`useStockAnalysisSelection`（个股/榜单）与板块行情视图都委托给它，禁止再各自实现“激活项置顶”的派生队列 |
| `MarketBenchmarkSelect` | `frontend/src/components/MarketBenchmarkSelect.vue` | 市场基准指数单选，统一已选标签、宽度入口和 `MARKET_BENCHMARK_OPTIONS` 选项源 | 无直接系统组件种类；由走势分析面板和默认字段组承载 | `StockAnalysisPanel` 与 `StockAnalysisDefaultFields` 共同消费，禁止再用面向列表多选筛选的 `AppFilterSelect` 代替或在消费页复制指数选项 |
| `StockAnalysisDefaultFields` | `frontend/src/components/StockAnalysisDefaultFields.vue` | 个股走势分析的默认模式、周期、指数、指标和分析区显隐设置字段组 | 无直接系统组件种类；嵌入页面设置业务分区 | 个股查询、每日榜单、连板天梯共同消费；指标列表不可为空，移除当前默认指标时统一回退到首个可见指标；组件只统一字段与校验，持久化仍由消费页各自的 `stocks` / `board` / `limit-ladder` 页面键负责，禁止共享同一个设置对象 |
| `StockAnalysisPanel` | `frontend/src/components/StockAnalysisPanel.vue` | 股票走势对比与 K 线的统一分析面板，负责当前观察、对比队列、指标、基准指数、周期、局部加载降级和模式切换 | `chart`（作为 master-detail 的分析子区） | 个股查询、每日榜单、连板天梯共同消费；行情复权口径由抽屉「业务选项 → 行情口径」驱动（不复权/前复权/后复权，默认前复权），经 `useStockAnalysisSession` 投影为 `adjustMode`，走势对比与 K 线共用同一口径且界面文案随之标注；连板天梯必须传选中交易日为 `endDate`，并按 `stocks:view` 传 `canOpenDetail`，无详情权限时不渲染入口；走势对比按统一市场交易日前向延续停牌收盘；对比指数时统一从首个共同有效日期起算（共同基期归零），纯股票间对比时各序列从自身首个有效值起算、上市前留空，固定 N 日仍须取 N+1 个市场收盘点，最多6只；抽屉默认值经 `useStockAnalysisSession` 单向投影且按 `stocks` / `board` / `limit-ladder` 页面键隔离；部分股票加载失败时保留可用曲线，重试仅重新请求失败股票，不刷新已成功曲线；市场交易日请求失败或返回空数据时必须进入可重试错误态，重试只重拉日历且不刷新已成功股票；K线直接消费 `StockChartWorkspace`，不得在页面内重做 K线、量能、MACD 联动 |
| `StockAnalysisNameCell` | `frontend/src/components/StockAnalysisNameCell.vue` | 股票列表名称单元格中的走势对比加入/移除入口，统一图标、可访问名称和激活反馈 | 无直接系统组件种类 | 个股查询普通列表、分组列表和每日榜单共同消费；只管理入口展示与事件，不持有对比队列状态 |
| `StockGroupBatchActions` | `frontend/src/components/StockGroupBatchActions.vue` | 批量观察、创建分组、加入分组与移出分组 | 无独立系统组件种类；由列表工具区消费 | 个股查询与每日榜单共享批量操作，消费页控制权限与选中集合，组件统一弹窗校验、请求和成功后清空选择；不得在页面复制分组操作流程 |
| `StockCompareChart` | `frontend/src/components/StockCompareChart.vue` | 多股票前复权序列与可选市场指数的涨跌幅对比折线（对比指数统一共同基期，纯股票间对比各序列从自身首值起算），统一交易日、主题、图例、tooltip、超额收益和缩放 | 无直接系统组件种类；由 `StockAnalysisPanel` 承载 | 只表达股票相对走势，不扩展板块资金流、成员涨跌、领涨股等截面指标；与 `SectorCompareChart` 共同消费 `marketCompareChart.ts` 的序列色、金融涨跌色、tooltip 转义及折线坐标轴/缩放 option 骨架；统一使用显式市场日历；对比指数统一从首个共同有效日期起算并据此计算超额，个别序列上市较晚只缩短基准期、不否决整体，仅连一个共同有效日期都没有时才显示不可比较空态；纯股票间对比时各序列从自身首个有效值起算，上市前留空、停牌期前向延续为 0%，不因个别序列缺起点而否决整体；当前观察线可强化，但所有序列仍须可辨识且不依赖单一颜色 |
| `SectorCompareChart` | `frontend/src/components/SectorCompareChart.vue` | 多板块连续指数的涨跌幅对比折线、市场指数超额和资金流/成员涨跌截面柱图 | 无直接系统组件种类；由板块行情分析区承载 | 折线与股票对比复用 `marketCompare` 的 N+1、统一交易日、停牌补齐和对比基期算法，并共同消费 `marketCompareChart.ts` 的折线 option 骨架；板块资金流和成员涨跌柱图保留领域私有配置，不并入通用折线组件；资金流、当日涨跌和成员涨跌缺失值保持空值，不得代填 0；页面偏好只消费 `sectors` 页面键，禁止与 `stocks` / `board` 串用默认指标或基准配置 |
| `AppPagination` | `frontend/src/components/AppPagination.vue` | 列表页统一分页 | 由 `data-table`/`wide-table` 的 `pageSize` 配置间接驱动 | 服务端分页页脚优先复用 |
| `AppFilterSelect` | `frontend/src/components/AppFilterSelect.vue` | 列表页筛选下拉 | 无直接系统组件种类 | 默认多选、可搜索、可清空；业务只允许单选时必须传 `multiple=false`；选择区固定单行，默认最多展示 3 个选中标签并在宽度不足时提前折叠，消费页可按已知小集合下调数量；空值未聚焦时必须直接显示占位文案，只有实际存在选中项时才能启用标签裁剪；未显式提供可访问名称时统一继承占位文案；筛选下拉优先复用 |
| `AppSearchInput` | `frontend/src/components/AppSearchInput.vue` | 列表页关键字搜索输入，统一"输入即防抖查 + 回车/清空立即查" | 无直接系统组件种类 | 关键字输入防抖（默认 300ms，可传 `debounceMs`）后 `@search`，回车/清空立即 `@search`；消费页绑定 `v-model` + `@search`（`@search` = 重置第 1 页 + 加载）。查询触发、重置筛选和手动刷新的通用行为以「按钮与输入 › 查询、重置与刷新」为准。查询防抖编排统一走 `frontend/src/composables/useDebouncedQuery.ts`；关键字字段不得再用裸 `<el-input>` 手写防抖 |
| `AppDatePicker` / `TradeDatePicker` | `frontend/src/components/AppDatePicker.vue`、`frontend/src/components/TradeDatePicker.vue` | 通用日期浮层入口与交易日选择器 | 无直接系统组件种类 | 页面和业务组件的日期、日期时间及范围选择必须经过 `AppDatePicker`，浮层默认在触发器下方，仅在下方左右对齐间回退；有明确交互理由时才允许覆盖到其他方位。交易日输入继续统一复用基于它封装的 `TradeDatePicker`，不得退回普通日期选择后自行补交易日校验。单日查询类页面若语义是“默认最新、允许回看”，统一使用 `defaultLatest` 显示数据最新交易日；训练区间、回测区间和数据任务边界等显式范围不得擅自默认 |
| `KlineRangeSelect` / `KlineSettingSection` | `frontend/src/components/KlineRangeSelect.vue`、`frontend/src/components/KlineSettingSection.vue` | K线范围快捷选择与共享设置分区 | 无系统组件种类；消费全局 K线偏好 | 个股详情、盘感训练等 K线页面统一复用，不复制范围选项或偏好写入逻辑 |
| `StockChartSettingSection` | `frontend/src/components/StockChartSettingSection.vue` | `ComponentAutoSettings` 内股票多图实例的专用字段编辑器，负责图表二/图表三选择、默认高度比例编辑和页面当前比例采用入口 | `chart.stockChart` | 每日榜单、个股查询、个股详情、板块行情、板块详情、盘感训练和回测交易回放统一通过 `ComponentAutoSettings` 间接复用；值按 `pageKey + slotId` 隔离，字段结构共享但不同页面实例不共享取值；编辑任一比例时，其余可见图表平均分配剩余额度并实时持久化，合计始终为 100%；拖动只改当前会话，“使用页面当前比例”同步更新当前组合的默认比例，并保存 `{width, height, ratios}` 工作区尺寸档案；同一组合可保存多项，当前宽高均在档案 `±15%` 范围内时使用综合距离最近项，`5%` 内重复保存更新原项，无匹配时回退该组合默认比例，不同图表组合的档案互不混用；匹配距离、容差和数量上限复用全局尺寸档案能力；复权、查询范围等业务口径不得塞入该字段，辅助图选择、比例计算、尺寸匹配与恢复默认不得在消费页维护第二套 |
| `EquityChart` / `GrowthChart` | `frontend/src/components/EquityChart.vue`、`frontend/src/components/GrowthChart.vue` | 回测/训练净值与成长曲线 | 无直接系统组件种类 | 保持各自数据与布局职责；画布主题统一消费 `useEChartsTheme()`，不得私有维护明暗基础色板。净值图「对比指数」虚线由父页注入 `extraBenchmark`（父页按各自日期区间拉指数行情并归一成资金净值），组件不内建数据获取；`fill` 撑满等高列仅在结算详情等需要时启用。基准可见性由 `showBenchmark` 控制：缺省 true 渲染基准线（无 `extraBenchmark` 时用 points 自带 `benchmark_equity` 实线，如训练「满仓持有」），显式 false（回测选「不对比指数」）整条隐藏。`setOption` 用 `notMerge: true` 整图重建，切「不对比」时基准 series 彻底移除不残留。配色：组合=focus 蓝，基准=`t.label` 灰（与板块行情对比图基准一致），回撤=`--el-color-danger` 红（面积用 `light-9` 浅红）；各 series 的 `color`/`itemStyle.color` 与线色同值，保证图例/悬浮圆点与线色一致。悬浮 tooltip 按「相对首日涨跌幅 %」展示组合/基准，并在基准可见时给组合一行「超额」（组合涨跌幅−基准涨跌幅），与板块行情对比图悬浮口径一致；回撤子图仍按 % 原值展示 |
| `BrandMark` | `frontend/src/components/BrandMark.vue` | 应用品牌图形与「复盘啦」字标 | 无直接系统组件种类 | 应用外壳、登录页等品牌露出直接复用同一外观；禁止场景变体、消费侧 `--brand-*` 覆盖、私有 logo 或第二套字标；窄容器只允许等比缩放 |
| `SideMenu` / `TopNavigation` / `WorkspaceTabs` / `WorkspaceRouteView` / `MenuIcon` | `frontend/src/components/SideMenu.vue`、`frontend/src/components/TopNavigation.vue`、`frontend/src/components/WorkspaceTabs.vue`、`frontend/src/components/WorkspaceRouteView.vue`、`frontend/src/components/MenuIcon.vue` | 应用级菜单树、双层顶栏、保留现场的工作标签页、路由缓存与统一菜单图标渲染 | 无直接系统组件种类 | 菜单统一消费 `/me` 授权树和 `utils/permission.ts` 的路由归属口径；工作页面统一由 `WorkspaceRouteView` 渲染并按标签独立缓存，禁止业务页私建 KeepAlive；关闭标签必须同步移除对应缓存；侧栏、双层顶栏和菜单管理页统一用 `MenuIcon` 消费后端图标名；新增导航模式时复用 `useAppNavigation` 持久化偏好 |
| `AssetVisibilityTag` / `AssetProfileLabel` / `AssetVisibilityActions` | `frontend/src/components/AssetVisibilityTag.vue`、`frontend/src/components/AssetProfileLabel.vue`、`frontend/src/components/AssetVisibilityActions.vue` | 公开资产来源、可见范围、只读状态、方案名称+版本+归属标签、发布/收回、复制为我的方案和复用参数动作 | 无直接系统组件种类 | 评分、筛选、买卖、回测等公开资产页面必须复用；方案选择/列表入口统一用 `AssetProfileLabel`，消费页包括 `BoardView`、`ScreenView`、`StockDetailView`、`ConfigView` 评分 tab、`ConfigView` 买卖 tab、`BacktestView` |
| `ScoreGradeTag` | `frontend/src/components/ScoreGradeTag.vue` | 统一综合评分评级标签：主升浪核心=`danger`、龙头候选=`warning`、观察=`success`、未知评级=`info` | 无直接系统组件种类 | 每日榜单、策略筛选、评分试算、回测交易及回测当日榜单统一复用；默认使用表格小号标签和统一垂直居中几何；训练模块的 S/A/B/C/D 属于另一套评级，不套用本组件 |
| `SubScoreChips` | `frontend/src/components/SubScoreChips.vue` | 分项达标分的业务域复用单元格，统一评分等级、胶囊样式、末尾截断与完整内容提示 | 无直接系统组件种类；作为既有 `data-table` 业务列内容 | 每日榜单与评分试算共同消费；保留评分胶囊原有的紧凑自适应高度与间距，不为统一提示机制改变业务组件外观；超长内容在胶囊末尾使用原生省略号，不得叠加单元格公共省略遮罩或留下被截断的分数字符；完整内容提示由全局省略宿主自动承接 |
| `AssetSearchDrawer` / `AssetProfileSelect` | `frontend/src/components/asset-search/AssetSearchDrawer.vue`、`frontend/src/components/asset-search/AssetProfileSelect.vue` | 统一跨来源资产搜索抽屉与“我的资产”选择器，支持 `select` / `list` 形态、服务端搜索分页、加载查看、复制或复用 | 无直接系统组件种类 | 公开资产页面统一消费，禁止私建同类选择器或搜索弹窗。资产浏览统一使用 `PageDrawer` 的 `xl` 语义宽度；从下拉选择器打开抽屉前必须先收起下拉浮层，禁止两个操作层重叠。无浏览权限时隐藏入口并显示明确无权态，不伪装成空态；加载查看默认不改变当前选择，需要外部展示时使用只读快照，只有“加载即展示结果”的场景才启用 `selectLoaded`。移除临时预览不等于删除资产，消费页必须同步清理对应请求和外部状态。mine-only 候选不显示“我的”，外部只读项保留来源；列表失败发 `loadFailed`，消费页结束等待并提供错误反馈和重试。mine ref 才进入选择器，系统或公开 ref 使用外部只读展示，不可解析时明示失效并阻止执行。具体 props、emits 和状态机以组件类型、实现及 `AssetProfileSelect.spec.ts` 为准 |
| `ConfigGroupForm` | `frontend/src/components/config/ConfigGroupForm.vue` | 系统设置配置组表单 | 消费 `config-panel` 的折叠与说明展示配置 | 动态配置组字段渲染优先复用 |
| `HelpTip` / `HelpHint` | `frontend/src/components/HelpTip.vue`、`frontend/src/components/HelpHint.vue` | 页面说明和短提示 | 无直接系统组件种类 | 字段或配置项旁可作为一个纯文本块理解的说明使用 `HelpHint`；需要标题、分段、列表、示例或多要点结构化排版时使用 `HelpTip`；不按字符数机械分流，也不在页面堆长文 |

### 应用外壳

- 侧栏宽度固定为 `208px`，顶栏高度 `67px`，主工作区 padding 为 `20px 24px`。
- 应用提供 `sidebar-tabs` 与 `dual-topbar` 两种导航布局：侧栏模式在内容区上方显示可关闭工作标签；双层顶栏模式把一级菜单放在品牌顶栏、当前一级下的二级菜单放在独立次栏，三级页面由二级菜单下拉承接。
- 工作标签按路由路径保留页面组件实例、表单筛选与独立滚动位置，最多缓存 12 个；同一页面类型的不同详情路由必须拥有独立缓存身份，关闭标签或超过上限时同步销毁对应实例与滚动记录。**菜单记忆只记菜单主页自身的访问（含查询态），不记详情子路由**——再次点击某菜单永远回该菜单主页，详情现场只由工作标签恢复；避免从榜单/板块等来源进详情后，菜单记忆被劫持到详情路由。
- **详情页返回键的来源必须可信**：个股/板块详情的返回键必须显示具体目标（如“返回每日榜单”），统一消费返回目标文案映射。以来源集合上下文（`stockSet.returnPath`）为目标时，仅当当前对象仍属于该集合才有效；从菜单、标签或直接链接进入（对象不在集合中）时禁用残留来源、归位默认列表。任何从列表/榜单/板块/筛选页跳进个股详情的入口都必须 `setSet` 写入本次来源路径与集合，不得依赖上一次进入的残留值。
- 图表范围等只影响单个内容面板的操作放入该面板标题行，与标题、图例和当前数据上下文就近编组；不得因页面分栏而放到远离图表的页头操作区。
- 导航布局、界面比例模式和手动比例都是独立用户偏好，不与明暗模式或颜色预设绑定；自动模式的计算指数由当前预设提供；外观抽屉中的主题缩略图只表达色彩和材质，不暗示固定导航结构或显示比例。
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
- 操作位置按真实影响范围判断，不按“新建 / 保存 / 刷新”等动词机械归类：作用于整页或页面唯一主任务的主操作统一放页头 `.page-head-actions`，位于 `PageSettingsTrigger` 左侧并使用默认 32px 尺寸；只作用于当前页签、局部表单、选中对象或局部区块的命令必须留在对应区域工具区，不进总页头。
- 顶栏状态和工具按 `32px` 控件基线对齐、间距 `6px`。交易日等状态项使用“图标 + 弱标签 + 强值 + 5px 状态点”的轻量结构；无详情权限时使用只读 `role=status`，不得伪装成禁用按钮，也不得使用永久渐变、内阴影或大胶囊底板。

#### 查询、重置与刷新

- 筛选/查询类控件（关键字、下拉、日期、分段、勾选、分页、排序）改选或输入后必须自动查询；除分页换页只查询当前页外，条件变化同时回到第 1 页。关键字统一防抖，列表筛选条不设置“查询”按钮。一次性执行、运行、评估、保存等动作型提交不属于筛选查询，继续使用显式命令。
- 列表筛选条按“范围/日期/下拉/勾选等条件 → 文本搜索框 → 重置筛选等命令”排列；存在多个文本搜索框时连续放在全部条件选择之后。空间不足时保持该 DOM 阅读顺序自然换行，不把搜索框插入条件选择之间。
- “重置筛选”只用于恢复用户主动改变的查询条件。存在两个及以上独立筛选项、复合条件、持久化或不易识别的非默认条件，或者筛选无结果后需要一键恢复时，应提供“重置筛选”；只有一个可清空输入或一个带“全部”的简单选择时，优先使用控件自身清空能力，不机械增加按钮。控件数量只是辅助判据，若页面的工作对象、运行参数或必选业务上下文没有合理默认值，不得为了凑重置按钮而清空。
- 回测、试算等多参数执行表单使用“重置参数”，恢复当前模式的初始日期、数值和开关，并清除资产选择、临时加载项、历史记录投影、执行结果及错误；不得连带清空历史记录列表或修改页面设置中的长期默认值。默认参数且没有载入记录/结果时按钮禁用；重置后的必选资产允许为空，由现有必填校验阻止无效执行。
- 筛选条中的按钮统一命名为“重置筛选”，当前声明的筛选状态与页面默认值一致时禁用；筛选无结果空态可在确有生效条件时补充同名按钮。点击后只恢复该区域声明的筛选默认值、回到第 1 页并合并触发一次查询；不得顺带改变排序、当前业务对象、表格选择、页面布局或用户偏好，除非这些状态在该页面被明确声明为筛选条件。
- “刷新”只用于按当前上下文重新同步服务端数据。当数据在页面之外由后台任务、定时采集、其他协作者或外部数据源变化，且立即获知变化属于当前页面的正常任务时，应保留手动刷新；当前页面操作成功后已自动重载、数据只随本页操作变化、或自动刷新已足够及时且手动同步没有额外价值时，不增加刷新按钮。不能仅以“接口可以再次请求”为理由添加刷新。
- 刷新必须保留筛选、排序、分页、当前对象、选择状态和已输入但未提交的草稿，只重新请求对应数据；异步刷新使用 `loading` 防重复提交。整页刷新放页头，局部表格或页签刷新贴近受影响区域；加载失败由对应异常态提供“重试”，不因已有重试入口机械增加常驻刷新。
- 重置与刷新分别按“是否需要恢复用户查询状态”和“是否需要同步独立变化的服务端数据”判断，不默认成对出现。存在自动刷新时，只有用户仍需要立即同步才同时保留手动刷新，并明确自动刷新状态。
- 编辑草稿回到已加载版本使用“还原修改”或同等明确文案；已保存配置回到系统基线使用“恢复默认”，并按未保存内容或持久化影响决定是否确认；密码重置等业务命令必须写明对象或在弹层标题中建立明确上下文。以上命令不属于“重置筛选”，不得共用其状态或行为。

查询区域的内容状态与操作状态分开建模：内容继续使用 `ready / loading / empty / error`，操作只使用下表状态。页面可以用现有 `ref / computed` 表达，不要求为了状态名创建同名变量，但行为必须一致。

| 操作状态 | 进入条件 | 查询控件 | 重置筛选 | 刷新 | 结果与退出 |
| --- | --- | --- | --- | --- | --- |
| `idle-clean` | 无前台请求，查询条件等于声明默认值 | 可用 | 禁用 | 满足刷新准入时可用 | 修改条件进入 `idle-dirty` 或 `querying` |
| `idle-dirty` | 无前台请求，至少一个查询条件偏离默认值 | 可用 | 可用 | 满足刷新准入时可用 | 重置先同步写回默认值，再合并发起一次查询 |
| `querying` | 条件、防抖、分页或排序触发前台查询 | 保持可用，不锁死连续输入 | 仍按条件是否偏离默认值判断 | 同一数据区域正在同步时锁定 | 最新有效请求成功后进入 clean/dirty；失败进入 `error` |
| `resetting` | 用户点击“重置筛选”到默认值写回完成 | 默认值必须同步写回 | 立即禁用，防止双击 | 同一数据区域锁定 | 不单独停留；合并为一次 `querying`，不得触发多次 watcher 请求 |
| `refreshing` | 用户主动按当前上下文同步服务端数据 | 保持当前值，不清空、不改写 | 保持原有 clean/dirty 判定 | 使用 `loading` 并阻止重复点击 | 成功回到原 clean/dirty；失败进入 `error` |
| `error` | 用户主动查询、重置后的查询或刷新失败 | 保留用户当前值，可继续修正 | 仍按 clean/dirty 判定 | 解除锁定，可再次刷新 | 对应区域由错误态接管；新请求进入 querying/refreshing |

- 查询控件在 `querying` 中保持可操作，连续输入产生的请求必须取消旧请求、合并串行，或用请求序号保证只有最后一次有效响应可以提交到页面状态；禁止较慢旧响应覆盖较新条件。输入防抖只减少请求，不替代过期响应保护。使用请求序号时统一复用 `frontend/src/utils/latestRequestGuard.ts`，不得在新页面继续复制私有计数器；已有取消请求或领域级竞态编排可以保留，但必须覆盖同一不变量。
- 同一数据区域的刷新按钮以该区域前台同步状态绑定 `:loading`；Element Plus loading 作为可见反馈并阻止重复点击，不得只用 `:disabled` 冒充进行中。业务前置条件不满足时可以额外 `:disabled`，但 loading 与 disabled 必须分别表达“正在执行”和“当前不可执行”。请求无论成功、失败、取消或过期都必须在 `finally` 或等价收口中释放锁定态。
- “重置筛选”是同步恢复查询状态后触发查询，不把列表查询耗时伪装成持久化重置，因此通常不显示独立 loading；按钮必须通过 `:disabled="!hasFilters"` 或等价计算在 clean 状态立即锁定。仅在有生效筛选的空态中出现时，可以通过条件渲染代替 disabled。若动作会写服务端、清除覆盖或恢复持久化配置，它不属于筛选重置，必须使用对应明确命名、独立 loading，并按影响决定确认。
- 同一数据区域同一时刻只允许一个会提交结果的前台请求；不同独立区域可以并行。自动轮询属于后台保鲜，不占用手动按钮 loading，但必须与前台请求共享过期响应保护，不能覆盖更新的数据。
- loading 期间保留按钮稳定语义名称，由组件旋转图标表达进行中，不把“刷新”临时改成“刷新中”导致宽度跳动。纯图标刷新同样必须把同一同步状态传给 `AppIconButton.loading`。
- 后续页面固定使用：筛选恢复为“重置筛选”，同上下文同步为“刷新”，失败请求重放为“重试”，只读取任务状态为“刷新状态”，重新运行业务任务为“重新执行”或“重新计算”，草稿回退为“还原修改”，持久化基线恢复为“恢复默认”，覆盖删除为“清除用户覆盖”，领域重置必须带对象名。普通列表不设“查询”按钮；确需显式提交的完整条件或高成本查询使用“查询”并标记为显式查询主命令。

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
- 列宽采用语义自适应契约：选择、展开、序号等结构列保持稳定窄宽；普通名称使用 `name`，含前置选择/收藏等控件并展示主副信息的对象识别列使用 `entity`；其余列取“语义内容基础宽度”和“表头标签 + 同行元信息 + 排序/筛选控件 + 主内容前置控件”估算宽度的较大值，并按 8px 网格取整。中英文混排使用稳定字符权重估算，不做运行时 DOM/数据采样，避免数据变化触发列宽跳动；异常长表头受角色上限保护，真实截断时由全局省略提示展示完整内容。容器有余量时由 Element Plus `fit` 按最小宽度权重分配并铺满，空间不足时保持最小可读宽度并由表体横向滚动。
- 横向滚动与单元格溢出是两套独立机制：前者只由所有列的语义最小宽度总和是否超过表格可视宽度决定；后者由 `AppDataTable` 递归比较单元格内文字、标签和嵌套结构的真实矩形是否越过该单元格边界。不得使用包含透明 padding / margin 的 `scrollWidth` 制造虚假省略号。省略号只有一种视觉规则：必须由实际承载文字的内容容器通过原生 `text-overflow: ellipsis` 绘制在自身末尾；表格只负责检测真实遮挡和触发统一悬浮，不得使用渐隐遮罩、伪元素或独立字符在单元格外层补画省略号。表格内标签、评分胶囊及其它有边界的复合内容必须在自身内部收缩，禁止切断背景、边框、文字或数字。全站完整内容统一由 `AppOverflowTooltipHost` 自动承接，只在真实截断时显示；页面不得传列级 `show-overflow-tooltip` 或自行维护截断 tooltip。操作列及动作组属于命令交互边界，不接入普通文本省略悬浮，也不得把隐藏测量副本纳入提示内容；结构列与操作列继续使用各自专用契约。
- 自适应列宽的角色、字符权重、控件预留、上限和数值唯一维护在 `components/table/adaptiveColumnWidth.ts`；页面只在动态标签无法推导时声明语义 `role`，不得复制数值。所有标准表头保持单行且不换行；日期、单位或短口径摘要使用 `header-meta` 在标签后同行弱化展示；主内容前存在紧凑控件时使用 `leading-controls` 让组件统一缩进表头并预留列宽。说明性长文本继续放 `HelpTip` / `HelpHint`，不得通过私有 header slot 拼接第二套样式。
- 表头保持稳定，分页、批量操作和关键筛选不被表体滚动带走。
- 不使用隔行变色作为默认识别手段；当前全局样式会取消 stripe 背景。
- 列宽按信息类型分配：编号、状态、日期、操作列稳定窄列；名称、标题、描述、备注更宽；数字列保持易比较。
- `data-table` / `wide-table` 的稳定字段只要支持排序，就必须同时支持列头直接排序和设置抽屉默认排序；分页表优先服务端排序，纯本地完整数据表可用 Element Plus 本地排序。
- 多级排序统一按“全量一级、页内二级”解释：默认或用户选择的一级字段必须由接口对完整结果集排序；只在当前已加载页提供的其它候选字段属于二级排序，只能在一级值相同的分组内稳定排序，并在二级值相同时保留接口顺序。纯本地完整结果可在本地完成全部层级；禁止把打乱接口一级顺序的当前页排序展示成全量排序。存在业务分层的视图以分层键作为不可破坏的一级边界，例如连板天梯固定按连板高度分层，卡片自定义排序只作用于各层内部。
- `pageRegistry.componentMeta[slot].sortFields` 是可交互排序字段和默认排序候选的单一事实源；登记后该 slot 自动继承 `defaultSort`，页面表格必须把对应列接入 `sortable` / `@sort-change`。**反向契约**：页面列头可排序的字段必须登记进 `sortFields`，二者双向一致，由 `pageRegistry.spec.ts` 契约测试强制拦截漂移。
- 操作列、展开列、按钮列、开关列、多值标签组合列、长说明/详情文本列默认不排序；若业务需要排序，必须明确映射到稳定字段并登记到 `sortFields`。
- 操作列和列表项操作区优先单行可见；表格中 `label="操作"` 必须按动作密度显式声明 `action-compact`（单动作或仅“更多”入口，默认下限 96px）或 `action`（两个及以上候选动作，默认下限 144px），不得只靠标签推导；两档默认统一居中表头与单元格，宽度均可由当前已渲染行的最低可用组合向上扩展，但不参与表格富余空间分配。单动作最低完整显示该动作；多动作最低保留两个操作入口，可由两个直接动作或“首个直接动作 + 更多”构成，“更多”计作一个入口；除调用方明确把全部动作收进更多外，禁止退化为仅“更多”。行内按钮组优先使用 `AppRowActions`，普通操作使用常规正文色，禁用操作降为弱文本色并满足语义 token 规则定义的文字层级阈值；hover / focus-visible 只做轻量文字色反馈，不对整组做透明度显隐；操作过多时用轻量“更多”菜单、分组、详情入口或抽屉，不用多行按钮堆叠；超过最低组合后按操作列实际宽度尽量展示更多直接动作，放不下的按钮自动收进“更多”菜单，不硬截断；“更多”菜单不得引入重动画、布局跳动或遮挡表格内容，菜单命令仍消费 Element Plus 按钮的 disabled/loading 状态。业务事实字段不得使用含糊的“操作”标签冒充动作列，应改为“操作笔数”等准确名称并声明真实语义角色。
- 宽表通过表体横向滚动承载，不让整页横向滚动。
- `data-overview/assetTable` 保持单一 `wide-table` 主成长实例和内部双向滚动。其“全部 / DuckDB / PG / 规划中”场景只切换业务列，不创建并列表格：全部显示双库共同字段，DuckDB 承载数据源/业务日/鲜活度/质量，PG 承载归属/空间，规划中不展示物理统计。质量列中 `0` 表示已纳入质检且零问题，`—` 表示不适用或未纳入；字段展开区必须展示中文名/说明及其元数据来源。所有可显隐列登记在 `pageRegistry.componentMeta.assetTable.columns` 并消费既有 `hiddenColumns`；筛选只属于会话态。低高度由表体内滚承接，窄屏工具栏自然换行，字段展开区保持独立嵌入表并允许横向滚动。

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
- 状态作用域按“最小可独立恢复的数据区域”确定。多个相邻面板因同一个请求、同一空集合或同一必需依赖失败时，在最近公共父级聚合为一个主状态；主从工作区不得在列表和详情两侧重复大图标、标题和主动作。次级区域确需保留上下文时只显示无图标短文案，不再生成第二个主状态。
- 同一工作区存在多个必需依赖失败时，优先聚合失败对象和一个恢复动作；可选依赖失败只贴近对应控件显示紧凑提示。不得让多个局部实体主按钮与页面主任务竞争。
- 首次进入或当前区域没有可复用旧内容时，使用 `AppStateBlock loading` 的骨架占位，不在空白内容上只放转圈遮罩，也不和 `empty` 同时出现；已有数据刷新过程中可以暂时保留旧 `ready` 内容并覆盖 `v-loading`，避免闪回空态，但请求失败后必须由 `error` 接管受影响区域并隐藏旧内容，不能继续显示“异常态 + 旧 ready 内容”。表格由 `AppDataTable` 统一执行该分流，消费页不得重复实现。
- `error` 不只依赖全局 toast；主内容、侧栏列表、详情面板、表格局部依赖失败时，失败区域必须留下页内错误态和“重试”或明确原因。
- 自动轮询、后台保鲜、偏好同步和参考选项同步失败，若当前缓存内容仍有明确来源且可安全继续使用，可以保持 `ready` 并使用 `AppStatusNotice` 说明降级内容与恢复动作；此时不得同时渲染整区 `AppStateBlock error`。用户主动刷新、筛选、分页、排序或切换主结果口径失败不属于该例外，必须由 `error` 接管受影响的主结果区域。
- 自动轮询必须有页面可见的等待说明和固定硬截止时间；服务端任务实例、请求 ID 或重试批次变化不得自动延长同一用户操作的截止时间。服务端返回失败、未就绪或中断终态后必须停止轮询并展示具体原因与可执行恢复动作，禁止失败任务被查询接口反复重建后让页面永久停留在 loading。
- 失败态操作必须真实对应恢复能力：有权限重新执行时使用“重新计算/重新执行”并进入该动作的确认与提交链路；只能重新读取服务端状态时使用“刷新状态”。禁止按钮写“重试”但实际只重复读取同一失败结果。
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
- 空态按“插画（可选）→标题→一句说明→动作区”组成。页面和大面板可使用插画；侧栏、字段、选择器和主状态旁的次级区域使用 `inline` 短文案，不使用插画。说明到动作区统一间隔 `--app-space-3`，动作间隔 `--app-space-2`。
- 空态最多提供一个实体主动作，且仅用于创建首条数据、完成必要前置选择、清除当前筛选或返回可用上下文；没有可执行恢复路径时不放按钮。次要动作使用 plain、text 或 link。

### 加载态与异常态

- 页面级初始化失败用 `AppStateBlock state="error"`（内部统一呈现 `el-result`），标题使用“{页面对象}加载失败”，说明“请检查网络或稍后重试”，并只提供一个主动作“重试”。
- 用户主动刷新、筛选、分页、排序或切换查询口径失败时，受影响区域使用同一 `error` 结构接管并隐藏旧内容；标题可按动作使用“{对象}刷新失败”，但不得把紧凑错误块堆在旧表格、旧图表或旧摘要上方。
- 查询、重置与刷新按钮必须通过交互契约测试：禁止含糊的“重置/还原”裸文案；“重置筛选”必须具备 clean 禁用或有筛选条件渲染；“刷新”及刷新类纯图标命令必须绑定 loading；普通列表禁止无声明的显式“查询”按钮。业务前置 disabled 不得替代异步 loading。
- 局部依赖失败只阻断该区域，不阻断已可用的其他区域；例如主表可加载但摘要失败时，摘要区显示局部错误态，主表保持可用。
- 403 / 无权限态不能伪装为空态；标题使用“无权限查看{对象}”或“无权限维护{对象}”，副标题说明联系管理员或切换账号（即不可重试原因）；不放“重试”按钮（重试对无权无意义，实现见 `AppStateBlock variant="permission"` 默认 `retry:false`）。
- 运行、保存、删除、发布等动作使用按钮 `:loading` 和禁用重复提交；动作失败用 `ElMessage.error`，若失败会影响当前区域继续使用，还要同步页内错误态。
- 远程选择器、懒加载下拉和日志区使用紧凑文案，不放大图标；下拉末尾可用“向下滚动加载更多”“无匹配结果”这类短句。

### 消息反馈层级

消息反馈不扩展四态，而是按对当前内容可用性的影响分层：

| 层级 | 使用条件 | 组件与持续时间 | 动作规则 |
|---|---|---|---|
| 瞬时操作反馈 | 保存、复制、删除、提交等动作已完成或失败，但页面当前区域仍可继续使用 | `ElMessage`，自动消失；同一动作不得同时连续弹出同义消息 | 不承载重试入口；需要恢复时由对应区域状态或持久提示提供 |
| 持久降级提示 | 旧数据、本地配置或主体功能仍可安全使用，但同步、保鲜或可选依赖失败 | `AppStatusNotice`，跟随原因持续存在；恢复后自动移除 | 最多一个 link 动作，写明“重新加载”“刷新状态”等真实行为 |
| 阻断状态 | 当前区域没有可行动内容或继续操作会产生错误结果 | `AppStateBlock error`，替换该区域 ready 内容 | 异常态提供一个真实恢复动作；无权态不重试 |
| 确认消息 | 破坏性、高影响或不可逆命令执行前 | `ElMessageBox` / 业务对话框，等待用户决策 | 主按钮写明动作与对象，危险操作使用 danger |

- `AppStatusNotice` 的信息层级为“语义图标→短标题→补充说明→可选文字动作”，不显示大插画，不使用实体 primary。`inline` 用于页头和控件旁，`compact` 用于抽屉、表单和面板内，默认尺寸用于横跨工作区的状态条。
- `el-alert` 只用于不随异步状态变化的说明性提示、字段风险说明和校验结果列表；缓存过期、同步失败、只读模式等运行时状态必须使用 `AppStatusNotice`，页面不得再维护私有 status/readonly/error banner。
- 同一原因只能选择一个反馈层级；禁止同时显示 toast、持久 notice 和阻断 error 三份同义信息。动作失败可先用 toast 告知，若它使区域不可用，随后由阻断状态接管，二者文案分别表达“动作结果”和“当前区域状态”。

### 卡片、面板与分区

- 卡片只用于承载独立数据块、表格容器、设置组、弹层内容，不把页面 section 都做成浮动卡片。
- 卡片默认圆角 4px；设置抽屉和用户中心等浮层卡片可使用 12-16px。
- 卡片内 padding 默认 14-16px；高密表格容器可压缩，但不能牺牲可读性。

### 弹窗与抽屉

- 弹窗/抽屉必须放在 `#overlays` 插槽。
- 页面触发的抽屉必须使用 `PageDrawer`，遮罩和抽屉高度限制在当前 `LayoutHost` 内容区；只有应用顶栏触发的用户中心、外观等全局抽屉可以使用视口级浮层。
- Element Plus teleport 生成的浮层 DOM 必须使用唯一全局类或 `:global` 定位内部样式，不要依赖 scoped 深层样式碰运气。
- 普通 modal 用于确认、短表单、少字段编辑；宽表、长流程、跨模块设置优先 drawer、全屏弹窗或独立页面。
- 同一操作组内的同类任务必须采用一致的弹窗触发模型、对齐方式、footer 顺序和提交文案；只要同组任务需要在执行前展示参数，就统一使用参数弹窗，不得混用直接提交、`ElMessageBox` 和表单弹窗。
- 异步任务参数弹窗提交期间，主按钮必须有 loading 并阻止重复提交；提交失败时保留弹窗与已填内容，只有成功后才关闭。
- 抽屉正文可以内滚，但外层页面不能跟随滚动；footer 或关键操作应保持稳定位置。

弹窗文案容量规则（解决窄弹窗内占位/说明文字被截断）：

- 弹窗宽度只使用语义档位（420 / 440 / 460 / 480 / 520 / 560 / 640 px），窄档位只放短字段；宽度不足时优先压缩文案、调整字段布局或改用 `PageDrawer`，不靠继续加宽弹窗绕过。
- 控件内直接可见的提示文案（`placeholder`、单选/复选后缀）控制在 15 字以内；更完整的说明移出控件，按内容结构使用 `HelpHint` / `HelpTip`，或放在字段 `label` 下方的辅助说明行（`*` 起头）及 `el-form` 底部的补充说明行。tooltip 与 popover 的选择遵循 §3 和真实复用组件清单，不受该可见文案字数边界约束。
- `el-select` 等多选控件的占位只写「动作 + 对象」（如「输入代码或名称搜索」）；「可多选」「留空=默认值」等可操作语义放到字段辅助说明行，不拼进 `placeholder`，占位文案在输入框内不换行、不省略。
- 单选项文案过长时拆为「主文案（行内）+ 补充说明（辅助行）」，不让单选标签撑满或截断。
- 验收自检：弹窗内最宽控件的可用宽度 = 弹窗宽度 − 左右内边距（约 48px）− `label-width`；文案超宽就压缩文案或改布局，不能靠改 `width` 硬撑。
- 同页长说明分散到各字段且不重复；新写弹窗时优先复用字段内短占位 + 行内辅助说明的结构，不复制 `IngestView` 中已修正的长占位写法。

### 设置抽屉

- 页面设置抽屉三段**固定顺序**：`布局` → `组件设置` → `业务选项`；每段**仅在该页有对应内容时渲染**。`布局` 恒在，`组件设置` 仅当 registry 声明了可配置组件字段，`业务选项` 仅当页面提供 `#business` 插槽；不得为了形式完整强插空段。
- 抽屉两条配置通道的分工：**组件设置段**收当前页面所用组件实例的共有展示能力——列显隐、默认排序、每页条数、区域高度、默认 tab、主从区宽度、股票多图组合与内部比例；字段能力由组件种类共享，取值按 `pageKey + slotId` 隔离，所以不同页面表格列候选不同也仍属于组件设置。**业务选项段**只收页面业务默认/偏好——模式、行情口径、业务开关和筛选默认。持久化位置必须服从字段职责，不得仅因同一页面消费就把组件字段复制进 `usePageSettings`。
- `布局` 和 `组件设置` 由元数据自动渲染；`业务选项` 由页面声明。组件配置不得通过业务插槽再次渲染或移动到业务段，避免同一字段出现双入口、双持久化和职责漂移。
- 设置项必须有默认值、来源展示、合法值域和重置路径；页面设置抽屉 footer 的「恢复默认」必须同时重置页面业务偏好、页面布局/组件用户层，以及抽屉自身 `size/defaultCollapsed` 用户偏好。
- 「组件设置」段与系统管理→布局配置→**页面布局**编辑器的「组件特性」**共用唯一渲染器** `components/ComponentAutoSettings.vue`（抽屉=user 层、页面布局编辑器=page 层，经 `layer`/`slotIds`/`allowedLayersOf`/`collapsibleSlot`/`clearable` 适配），不得另写第二套组件特性表单。
- 折叠规则统一：每个 slot 为可折叠组（`SettingsGroup` level 2；编辑器聚焦单 slot 时仅作标题锚点不折叠）；多行清单类特性（列显隐）为可折叠子组（level 3）；单字段为叶子不折叠。深层标题字号随层级递减但不低于正文。
- 设置抽屉中将页面当前会话值保存为默认或尺寸档案的操作，统一复用 `PageSettingsApplyButton`，使用主题主色 `primary + plain`；普通编辑与恢复默认保持中性，危险操作才使用 `danger`。采用入口紧跟对应字段，不额外展示工作区像素、匹配阈值或档案清单等实现细节。
- **页面可改动属性单向默认机制**：抽屉/组件配置层只提供**默认值**，页面主区可直接交互改动的属性必须用独立会话 ref 承载；重复的默认值投影统一复用 `composables/useDefaultedSessionValue.ts`，组件配置分页统一经 `composables/useComponentPageSizeSession.ts` 完成默认值解析、会话投影、归页和重载，**页面改动只进会话态、绝不写回默认值**——刷新/重进页面后重新应用抽屉默认。这样「默认」才有意义：用户临时改动不污染长期偏好。禁止可写 computed 或主区 `v-model` 直写持久层；设置抽屉内的默认值编辑，以及带有明确“设为默认”语义的显式操作，才是默认值持久化入口。初始化优先级固定为：先完成页面业务偏好与远端布局默认值水合，再应用 URL query、返回列表态等显式会话恢复，最后才接受用户交互；迟到的默认值不得清除已经恢复的显式会话覆盖。URL query/分享链接恢复只写会话 ref，不触碰默认。**会话态清单**（本就该会话级、也不进抽屉）：纯查询条件（关键字/日期口径/方案选择）、业务资产选择、运行参数（如回测日期、所选方案和当次执行参数）。
- **新增属性登记判断（开发闭环必经步骤）**：新增页面、改造页面或给页面/组件新增任何可交互属性后，必须逐一回答三个问题再收尾——①该属性是否需要跨会话记住（默认值/偏好）？②需要时登记到哪条链路（业务偏好进 `usePageSettings` defaults + `#business` 插槽；组件展示字段按 §7.3 进 `COMPONENT_FIELD_DEFS`/后端规则，页面 slot 自动继承，仅候选或实例例外进 `componentMeta`）？③需要默认值时页面是否已按上条单向机制消费（读默认初始化会话 ref、不写回）？三问任一答「是」却未落地，即视为本次改动未完成。反向同样成立：不再需要或语义失效的已登记项必须及时下线，不得在抽屉里堆积死项。

## 5. Layout Principles

所有业务页面走可配置布局系统：页面声明 `PageLayout`，通过 `<LayoutHost>` 渲染，不手写 `.v-page` / `.v-grow` / 视口高度。配置合并顺序固定为：

`default < preset < page < user`

| 层 | 职责 | 维护入口 |
|---|---|---|
| `default` | 页面原型、slot、组件代码默认值 | `frontend/src/layout/pageRegistry.ts`、组件代码 |
| `preset` | 风格 token、预设级组件默认、响应式默认枚举 | 系统管理 → 布局配置 → 预设管理 |
| `page` | 单页面默认布局旋钮与组件默认值 | 系统管理 → 布局配置 → 页面布局 |
| `user` | 当前登录用户的布局、组件和业务偏好 | 页面设置抽屉；PG `layout_user_config`、PG `user_preference` |

用户层以 PostgreSQL 为权威：页面布局和组件字段写入真实 pageKey 的 `layout_user_config`，页面业务偏好、主题、导航模式、界面比例、K 线偏好和跨页面设置抽屉偏好写入 `user_preference`。回测日期、方案选择和当次运行参数只属于会话态，不得写入用户偏好。localStorage 只允许作为未登录/离线 fallback、旧偏好迁移源和登录前主题读取，不得作为登录用户配置权威，也不得保存页面查询现场。列表进入详情再返回所需的现场统一使用按租户和用户隔离的 sessionStorage：刷新可恢复，返回页消费一次，关闭 Tab、退出登录或切换身份后清理。

页面状态生命周期统一按语义选择入口：抽屉默认值投影到当前 Vue 实例时使用 `useDefaultedSessionValue`，由 KeepAlive 保留的只是该实例内存，刷新或实例重建后重新应用默认；需要分享、前进后退或刷新复现的查询状态写入 URL；确需跨路由返回且不适合暴露在 URL 的一次性现场使用 `utils/pageSessionStorage.ts`，页面不得直接调用 localStorage/sessionStorage。`pageSessionStorage` 统一负责 page namespace、租户/用户隔离、旧键迁移和退出/身份切换清理，业务 Store 只负责状态结构及消费时机。

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
| 分区表面 | `--app-section-bg` | KPI、指标标签格、查询摘要、配置组内部 |
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
- 列表页筛选下拉优先复用 `AppFilterSelect`；默认多选、可搜索、可清空，业务只允许单选时必须传 `multiple=false`；选择区必须保持单行，默认最多展示 3 个选中标签并在宽度不足时提前折叠；标签裁剪只在实际存在选中项时启用，空值未聚焦时必须显示占位文案；未显式提供可访问名称时继承占位文案；选择变更即向页面发出筛选事件，页面负责触发服务端查询。
- 普通命令使用 `el-button`，纯图标操作使用 `AppIconButton`；同一操作组只保留一个主按钮，并保持尺寸、图标和状态反馈一致。
- 页面主体字体、字号、行高、字重和间距必须优先消费 `global.css` 的 `--app-font-*`、`--app-line-height-*`、`--app-space-*` token 或 `.app-*` 语义类；新增 px 值必须属于文档允许的局部特例。
- 说明性/描述性文字只要不是极短标签或必要操作指引/实时状态说明，按内容复杂度收进 `HelpHint` / `HelpTip`：单块纯文本用 tooltip，需要标题、分段、列表、示例或多要点排版时用 popover。
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
- 禁止绕开 `HelpTip` / `HelpHint` 手写问号图标或私有 tooltip 说明结构；说明入口只有这两个组件。
- 禁止新增未登记的普通文字字号、游离字体族和随机间距；禁止把登录页、品牌字标、图表 tooltip 的特殊排版复制到业务页面。

### 7.3 组件特性配置治理

组件配置路径固定为：

`slots.<slotId>.config.<field>`

字段事实源为 `COMPONENT_FIELD_DEFS`。它描述组件 kind 真实支持的属性；页面只要登记该 kind 的 slot，就按 `default < preset < page < user` 自动继承适用字段，禁止再维护逐页字段白名单。新增字段必须同时满足：

- 字段在 `COMPONENT_FIELD_DEFS` 中声明 label、control、layers、默认值和值域。
- `componentSchemas.ts` 接受该字段。
- 后端 `layout_config.py` 同步字段规则和归属校验；同名字段在不同组件种类中值域不同时，静态值域必须按 `(component kind, field)` 维护，不得只按字段名合并。
- 字段必须能由 `ComponentAutoSettings` 的通用控件安全渲染，或登记到专用动态候选渲染器；自动继承但没有安全控件的字段由组件配置契约测试直接拒绝。
- 适用性为 `always` 的字段自动进入每个同 kind slot；候选型字段由 `componentMeta.columns/sortFields/tabs/collapseSections` 有值时自动启用；结构型字段由 slot `config` 声明，例如 `pagination: true` 启用 `pageSize`。
- 实例明确不适用时必须在 `componentMeta.fieldApplicability[field]` 设置 `enabled: false` 并填写原因；不得以“没登记”隐式漏掉字段。
- 页面通过 `componentMeta` 提供安全枚举（列、可交互排序字段、tabs 等）。
- `componentMeta.columns` 只声明列显隐候选，不负责生成业务表格列；每个候选 key 必须在消费页面进入真实显隐判断并控制对应列或列内业务片段。该正向消费关系由 `pageRegistry.spec.ts` 契约测试强制，禁止“设置里可勾选、页面没有可渲染节点”的假配置。
- 页面实际读取并应用字段值。
- 配置中心和设置抽屉共用 `ComponentAutoSettings`，且同时受字段代码最大层级与管理员当前开放策略限制。
- 普通页面从 `/layout/effective/{pageKey}` 一次获取 preset/page/user 层和字段开放策略，前端结合本地 default 做四层合并；历史上已存但现策略禁止或实例不适用的值必须丢弃。
- `useRemoteLayoutConfig` 返回的 `componentAllowedLayers` 必须传入 `PageSettingsDrawer`；页面脚手架和 `pageRegistry.spec.ts` 同时守卫该接线，禁止只在配置中心消费管理员策略。
- 测试覆盖自动继承、实例适用性、四层合并、策略收紧、越权、类型和值域。

当前受控字段摘要：

下表只记录字段和开放层级；消费页面、slot、候选列、排序字段和 tab 项不在 DESIGN 手写维护，统一以 `COMPONENT_FIELD_DEFS`、slot `config` 和 `componentMeta` 为准。`pageRegistry.spec.ts` 校验每个适用字段都被页面真实消费，且明确例外都有原因。

| 组件 | 字段 | 层级 | 归属事实源 |
|---|---|---|---|
| `data-table` | `border` | page | 全部 `data-table` slot 自动继承；页面需实际消费 `tableBorder(slotId)` |
| `data-table` | `pageSize` | preset/page/user | slot `config.pagination=true` 时自动启用 |
| `data-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `data-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `wide-table` | `border` | page | 全部 `wide-table` slot 自动继承；页面需实际消费 `tableBorder(slotId)` |
| `wide-table` | `pageSize` | preset/page/user | slot `config.pagination=true` 时自动启用 |
| `wide-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `wide-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `chart` | `minHeight` | page/user | 图表 slot 以 `config.minHeight` 明确开放；自适应高度的工作台通过 `fieldApplicability.minHeight` 明确关闭并说明原因 |
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

- 自动界面比例先按当前屏幕有效逻辑面积连续确定整套 UI 的视觉尺度；响应式布局再按缩放后的窗口可用空间处理重排、伸缩、截断和滚动。两者共同完成适配，不能把屏幕差异只交给响应式，也不得用大量字号断点模拟整体缩放或让用户依赖浏览器缩放获得合理桌面密度。
- 尺寸断点使用 `@container app-viewport`，由 `#app` 与 body 级独立遮罩提供具名 size 容器；尺寸上限使用布局容器单位 `cqw/cqh`，JavaScript 通过 `useLayoutViewport` 读取同一根画布的 `clientWidth/clientHeight`。`@media` 仅用于主题、像素密度、减少动画、输入能力、打印等设备特性。挂到 body 的锚点浮层自身仍用浏览器视口单位。
- 第三方控件的拖拽、滚动、溢出测量和位置指示也必须遵守坐标契约；依赖补丁统一在 `frontend/patches/` 维护并锁定依赖版本，由安装脚本强制应用，补丁失配必须中断安装。升级时同时复核 ESM/CJS 入口及真实组件交互测试，禁止只修改本机 `node_modules` 或在各页面重复修补。
- `pageRegistry.responsiveProfile` 是页面类型的目标响应式画像，用于说明设计意图，不等同于已完成浏览器验收；实际列数和重排由 `layout.responsive` 决定，运行时滚动由 `LayoutHost` 决定，最终可用性以关键视口 E2E 为准。页面布局工作台必须显示为“目标响应式策略”，不得把画像名称当成已验证结论。
- 响应式配置必须有 `minWidth=0` 的基础断点。
- 单个大表、大图、大列表不靠多列重排解决高度问题，优先内部滚动。
- 主从布局两侧都是表格、图表等主内容区时，默认分栏必须按容器比例连续计算并设置双侧最小可用宽度与配置比例上限，禁止用单侧固定像素上限让跨屏占比失衡；导航树、索引栏等语义窄栏可以固定宽度，但必须具备窄屏折叠、转单列或滚动兜底。
- 多组件平级块只有在都允许重排、无强阅读顺序且最小宽度满足时才进入 `columns`。
- `workbench` 类页面采用固定分析块 + 主成长区，放不下时由主区域兜底滚动。
- 抽屉宽度使用 `PageDrawer` 的受控档位：`sm=320px`、`md=360px`、`lg=440px`、`xl=560px`、`xxl=clamp(640px, 60%, 820px)`、`wide=clamp(560px, 46%, 760px)`、`full=100%`。`wide` 只用于日志、字段差异、长 JSON 等需要横向阅读且应随页面内容区增长的场景；`xl` 用于固定宽度的复杂详情和组件预览；`xxl` 用于资产搜索等需要比 `xl` 更宽横向空间的复杂详情；`full` 只用于窄屏承载与桌面同等复杂的业务工作台，仍只铺满 `LayoutHost` 页面区域，不覆盖应用顶栏和导航。页面只传语义档位，不得私传 px 或百分比；页面设置抽屉只开放 `sm/md/lg`。
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
| `limit-ladder` | `LimitLadderView`（连板天梯） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`section` / nested:`chart` |
| `screen` | `ScreenView`（策略筛选） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `stocks` | `StocksView`（个股查询） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`wide-table` / nested:`wide-table` / nested:`chart` / footer |
| `data-quality` | `QualityView`（数据质量） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `data-schedule` | `ScheduleView`（任务调度） | `detail` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`data-table` / overlay:`detail` |
| `data-ingest` | `IngestView`（数据采集） | `workbench` | `density` | action:`toolbar` / main:`section` / main:`tabs(growMain)` / nested:`data-table` / nested:`data-table` / overlay:`form` / overlay:`form` / overlay:`detail` |
| `data-overview` | `OverviewView`（数据概览） | `workbench` | `density` | action:`toolbar` / main:`kpi-grid` / main:`stat-strip` / main:`tabs` / nested:`wide-table` / nested:`data-table` |
| `backtest` | `BacktestView`（策略回测） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`chart` |
| `training` | `TrainingView`（盘感训练） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`chart` |
| `trade-discipline` | `TradeDisciplineView`（交易纪律） | `workbench` | `density` | action:`toolbar` / main:`tabs(growMain)` / nested:`section` / nested:`section` / nested:`data-table` / overlay:`detail` |
| `stock-detail` | `StockDetailView`（个股详情） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`chart` / nested:`section` / nested:`section` / nested:`section` / nested:`section` |
| `config-score` | `ConfigView`（评分规则） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `config-trade` | `ConfigView`（买卖指标） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `config-tech` | `ConfigView`（技术指标） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`filter-bar` / nested:`data-table` |
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
| `sectors-detail` | `SectorDetailView`（板块详情） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`section` / nested:`chart` / nested:`data-table` |
<!-- page-registry:end -->

除 `supportsPageSettings=false` 的预设管理、页面布局、系统组件三个平台管理页外，registry 页面必须有 `settings-drawer` overlay slot。三个管理页只管理系统配置，不开放或持久化个人页面设置。组件字段、slot 结构、候选项和明确例外的事实源在 `COMPONENT_FIELD_DEFS`、slot `config` 和 `componentMeta`，不要在本表重复维护。

## 10. Scope & Exceptions

- 本项目桌面工作台优先；响应式规则覆盖低高度和常见桌面宽度，移动端不是当前验收重点。
- 当前没有独立品牌设计稿；视觉方向以本文件的金融科技研究终端规则和现有品牌组件为准。
- 品牌字标、登录主视觉、图表 tooltip、代码值和极窄 badge 允许局部排版特例；新增业务页面不得复制这些特例作为普通排版。
- 页面登记区块通过 `<!-- page-registry:start/end -->` marker 被 `pageRegistry.spec.ts` 和 `scaffold-page` 读取；marker 是机器契约，不要移除。
