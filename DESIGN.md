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

本文维护全站界面规则和共享组件契约；各页面的指标清单、业务含义与操作目的地由对应架构文档维护，实际业务文案保留在领域代码中。响应式清单登记实现与验证证据，不另行定义设计规则。

文件头 frontmatter 只保留已被自动化读取的兼容字段；运行时 token 以 `global.css`、`presets.ts` 和 `themeSurfaces.ts` 为准。新增 token 不回填 frontmatter，除非同步新增机器读取契约和测试。

## 1. Visual Theme & Atmosphere

复盘啦是专业金融研究空间，不是传统后台、营销页或内容站。界面优先支持反复扫描、比较、筛选、回测和配置，以高辨识蓝色信号、中性黑白表面和清晰层级保持明亮、现代的金融科技气质。

Key Characteristics：

- 信息密度偏高，但通过表格内滚、抽屉分段、字段收纳和提示悬浮保持可扫读。
- 默认气质为明亮、清晰的金融科技研究终端；主交互蓝保持鲜明，不通过低饱和暖灰、金棕或泛黄底色营造所谓护眼感。**亮色模式信号文字与实色按钮的常态直接消费预设原色，不额外向黑或白混色；浅底、边框及悬浮/按下反馈按按钮状态矩阵消费共享配方。**金融数据场景允许红绿涨跌色，但不以过度紧凑和控件堆叠表达专业。
- 明暗模式缩略图、外观预览和装饰性状态图形也必须使用冷白、亮蓝、深蓝与中性灰；不得用金黄、棕灰或泛黄色模拟“白天”，避免预览层与真实页面色彩语言脱节。
- 页面首屏直接呈现业务工具，不做大 hero、不做营销式空白、不做卡片堆叠式装饰。
- 所有业务页面通过布局系统组织，页面结构由 schema 和测试约束，不依赖临时 CSS 猜高度。
- 视觉预设只改变白天/夜间语义色、边框、阴影和共享圆角，不改变页面密度、组件行为或业务结构。

## 2. Color Palette & Roles

颜色以 Element Plus 变量、`global.css` 的 `--chrome-*` / `--page-settings-*` 变量和 `LAYOUT_PRESETS` 为事实源。**金融涨跌色（`--market-up-color` / `--market-down-color`）与状态/评分文本色（`--app-warning-text` / `--app-danger-text` / `--score-high-*` / `--score-mid-*`）唯一事实源是 `LAYOUT_PRESETS` 的 `marketUp` / `marketDown` / `success` / `warning` / `danger` token，由 `useLayoutPreset.applyPreset()` 统一写入，禁止在 `global.css`、页面或组件内平行硬编码第二套色值（含 Element/AntD 默认蓝绿橙红）。**内置视觉只保留 `balanced` 一个稳定 key，对外名称为“澄空蓝”；历史内置项统一迁移到该默认项。“视觉预设”页仍可新增自定义预设，启用项会自动进入外观抽屉并真实驱动语义色、边框、阴影和共享圆角。

| 角色 | 默认值 | 使用规则 |
|---|---:|---|
| 主交互色 | 白天 `#1677ff` / 夜间 `#3b8cff` | 主按钮、当前菜单、可点击强调、选中边框 |
| 页面背景 | 白天 `#ffffff` / 夜间 `#171717` | 对齐参考原型主区；工作区与登录页统一画布，只受明暗模式控制 |
| 边栏背景 | 白天 `#fcfcfc` / 夜间 `#1f1f1f` | 对齐参考原型侧栏；固定中性表面，不随预设强调色变化 |
| 表面色 | 白天 `#ffffff` / 夜间 `#171717` | 卡片、表格、输入框、抽屉内容面；与同模式页面背景连续，避免主体区域出现无业务意义的色块断层，不随预设变化 |
| 悬停表面 | 白天 `#f3f3f3` / 夜间 `#292929` | 菜单、表格行、轻量按钮 hover |
| 主文字 | 白天 `#17181c` / 夜间 `#f4f4f4` | 标题、表头、关键字段 |
| 正文文字 | 白天 `#44464d` / 夜间 `#d2d2d2` | 表格正文、表单值、说明正文 |
| 次要文字 | 白天 `#6e7078` / 夜间 `#9a9a9a` | 提示、辅助说明、弱化信息 |
| 边框 | 白天 `#d4d4d4` / 夜间 `#454545` | 卡片、表格、分割线、输入框 |
| 强边框 | 白天 `#c9c9c9` / 夜间 `#545454` | 选中、强调分区、高对比控件 |
| 成功 | 白天 `#0ea968` / 夜间 `#3ecf8e` | 健康状态、成功提示、评分高档 |
| 警告 | 白天 `#f58a07` / 夜间 `#f5a623` | 异常但未失败、样本不足、风险提示、评分中档 |
| 危险 | 白天 `#f04438` / 夜间 `#ff6b66` | 失败、删除、风险 |
| 金融上涨 | 白天 `#f66055` / 夜间 `#ff7a72` | 涨/正收益；感知亮度恒高于危险红一档，区分金融与主体语义 |
| 金融下跌 | 白天 `#1ec96e` / 夜间 `#3fdd90` | 跌/负收益；感知亮度恒高于成功绿一档 |

金融涨跌色遵循当前项目口径：上涨/正收益多用红色，下跌/负收益多用绿色；不要套用海外红跌绿涨习惯。**金融色（`marketUp`/`marketDown`）与同名主体信号色（`danger`/`success`）是两个独立 token：金融色更鲜亮（亮色模式感知亮度约高 25%~47%），用于涨跌数据、K线、净值等金融语境；主体信号色用于状态、提示、评分档。二者不得互相替代或合并。**

语义 token 规则：

- 权限树颜色使用 `--perm-group-color`、`--perm-feature-color`；权限树内的菜单类型点使用 Element Plus 成功色，应用导航当前位置圆点按外壳规则使用 `--shell-accent`，不在页面内写死色值。
- 金融涨跌使用 `--market-up-color` / `--market-down-color`，不要在页面里直接写红绿 hex。
- `StockChartWorkspace` 及个股详情股票画布通过 `stock-chart/chartUtils.ts::stockChartTheme()` 读取 CSS 语义色；该工作区的 MACD 正柱与金叉使用 `--market-up-color`，负柱与死叉使用 `--market-down-color`。交叉事件使用贴近当日 DIFF 点的“金叉/死叉”标签表达，标签只保留连接事件点的短三角指针，不显示贯穿面板的长引导线或独立圆形锚点；不得只依赖红绿颜色，也不为金叉新增独立金色 token。信号标签使用主题中性表面和高对比中性文字，方向色只用于轮廓和短指针；信号 item 悬停必须显示类型与完整交易日期。
- 股票 MA/VMA/MACD 折线的序列身份色统一以 `stock-chart/chartUtils.ts::trainingChartSeriesPalette()` 为事实源：MA5/VMA5/DIFF 使用橙色 `#e28a35`，MA10/VMA10/DEA 使用蓝色 `#418af5`，MA20 浅色使用洋红 `#9f3793`、暗色使用 `#c53c92`，MA30 使用青色 `#56c3df`，MA60 使用橙红 `#e56023`。K线和量能均线的周期、标题、ECharts 名称与色板键分别由 `KLINE_MA_DEFINITIONS`、`VOLUME_MA_DEFINITIONS` 唯一声明，序列、有数据标题和空数据标题必须共同消费，不得复制周期数组、标签映射或颜色。盘感训练、回测和个股详情必须共同消费该色板；序列色只表达指标身份，不表达涨跌方向。K 线 tooltip 的收盘与涨幅才按相对昨收使用涨跌色，平盘保持中性。
- K 线 tooltip 的顶部和左右停靠位置必须与 K 线绘图区共同消费 `STOCK_CHART_GRID_TOP`、`STOCK_CHART_GRID_SIDE`，不得在浮层侧追加近似内缩量。应用启用非 100% 显示比例时，HTML tooltip 必须挂到未缩放的 `body` 避免父级缩放与自身 `translate3d` 叠加导致文字模糊，并把浮层视口尺寸按实际显示比例换回图表布局坐标后再计算避让与右侧停靠。左右切换必须同时满足光标进入当前浮层水平占用区、浮层与当前蜡烛高低价像素矩形发生二维重叠；蜡烛矩形由当前 ECharts 实例实时换算。任一条件不成立或无法取得像素矩形时保持左侧，禁止仅凭光标位置或 candlestick 参数猜测遮挡。行情摘要必须使用稳定表格网格：时间与日期共用浮层左右边界，主价格纵向跨越全部指标行，字段名左对齐、字段值右对齐，相同行保持统一基线；禁止以多个独立 flex 列和内容宽度近似对齐。点击日 K 下钻分时后，分时弹窗存续期间只锁定所点蜡烛的竖向日期线、横向数值线、右轴百分比标签和底部日期标签；不强制显示左上行情内容浮层。关闭弹窗后再清理锁定状态并恢复消费页原行为。
- 普通 ECharts 提示行共用 `chartTooltipRowHtml()` 外壳，领域字段和专用表格由各图表提供。
- `StockChartWorkspace` 的 K 线左轴显示价格，右轴显示同一基准下的涨跌幅，十字光标两侧标签必须保持各自语义。K 线必须标出当前可视窗口内基于实际 `high` / `low` 的最高价和最低价，缩放或拖动窗口后实时重算；“截止”涨跌测算以当前可视窗口最后一根 K 线为终点，图内浮层与图外摘要保持一致；标签使用主题中性色并朝绘图区内部展开，不得使用涨跌色暗示方向，也不得由消费页面重复实现。多粒度行情统一消费共享周期切换与暖机数据；对应周期的技术指标必须由后端原子定义计算并携带明确周期上下文，前端只聚合展示序列和对齐结果。历史不足显示“—”，请求完成前不得把旧周期指标复用到新周期。标题行只承载视图切换、日期和操作入口，标题不重复当前选项，固定指标行纳入面板最小高度。只有语义适用的图表实例才登记周期与测算能力，页面内切换使用会话态，不隐式改写默认配置。
- 低频图表操作统一进入 `StockChartOperationsDrawer`：抽屉默认关闭且边界限制在所属工作区，支持遮罩、关闭按钮与 Escape 关闭并恢复入口焦点；操作按职责进入独立 `ChartOperationGroup`，禁止无分组堆叠。由默认配置派生的页面操作只更新会话值，除非用户执行明确的持久化动作。派生行情结果统一复用 `StockQuoteSummary` 数据模型：页面已有常驻摘要区时追加独立分区，否则附加到图表 tooltip；图内浮层只保留下一步操作指引，不重复结果。切换数据粒度或模式时必须清理不兼容的光标、选点与缩放状态；日期与统计说明保持中性色，只有涨跌值使用金融语义色。
- `StockChartWorkspace` 不会随 CSS 变量自动重绘；必须只通过 `stock-chart/useStockChartTheme.ts::useStockChartTheme()` 消费响应式股票图表主题，不得自行组合 `useTheme`、`useLayoutPreset`、`themeRevision` 和 `stockChartTheme()`。该入口统一覆盖明暗切换、预设 key 切换和当前预设同 key 后端覆盖更新。本条适用于个股详情、板块行情、盘感训练和回测的股票图表；其它图表不会自动继承，扩大适用范围时必须同步完成运行时改造和独立回归。日 K 与分时必须使用 SVG renderer，避免应用根非整数缩放反复采样 Canvas 位图；分类柱宽必须额外乘元素实际显示比例，禁止 `zoom` 扩展后的布局宽度把 K 柱、量柱或 MACD 柱的视觉缩放抵消。
- `StockIntradayChart` 与日 K 共用上述股票图表主题：价格线与价格图例使用主题中性主文字色（浅色近黑、暗色近白），价格悬浮圆点外圈沿用线色、内部跟随图表背景，避免暗色白线上的圆点被白色填实；分钟浮层主价格与涨跌幅按相对昨收使用金融涨跌色，平盘或缺少有效昨收时保持中性；均价复用 MA5 身份色，昨收使用中性虚线并以 `0%` 标注；分钟成交量统一以手展示，量能标题同步展示当前全部分钟点之和。分时量柱按“当前分钟收盘价相对上一分钟收盘价”判色：上涨使用金融上涨色、下跌使用金融下跌色、持平在浅色主题使用中性灰、黑色主题使用白色；首分钟以前收为参考，前收也不可用时使用弱中性色。平盘量柱禁止悬停提亮，并须在 SVG 缩放后保持设备像素边缘对齐，避免同一中性色因半像素抗锯齿呈现多档深浅。日 K 量柱仍按当日开收方向判色，两者只共享 `buildStockVolumeBarSeries()` 的柱形构造，不得混用方向口径。价格与量能数值轴固定在左侧，价格区右轴按昨收映射涨跌幅；共享十字光标 tooltip 继续展示分钟明细，不另做指标卡或页面私有色板。日 K 与分时必须共同消费 `app-stock-chart-frame` 外框、`StockChartPanelHeader` 标题栏、`StockChartLegend` 图例项、`StockChartPanelDivider` 面板分隔和 `buildStockVolumeBarSeries()` 量柱构造；折线统一使用短线标识，柱状序列统一使用小柱标识，标签使用中性文字、当前值使用序列身份色。分时上图标题为“分时”并承载价格/均价图例，下图标题为“量能”，两图之间使用独立的 8px 双边框分隔区，不允许拿上下绘图区的边界网格线冒充分隔线；标题栏是图表容器的 DOM 结构，不得通过 ECharts `title`、`graphic` 或页面私有边线仿制。标题栏与绘图区保留紧凑安全间距，量能图区顶部留白不得小于 12px；分时两个横轴不重复绘制坐标轴边线，价格与量能纵轴网格不显示最小值和最大值边界线，底部时间轴只显示 `09:30`、`11:30`、`15:00` 三个市场时点，不把午休两端拼成复合标签。涨跌停边界不得额外扩展纵轴造成顶部无意义留白。
- 全站 ECharts 统一通过 `components/echartsRenderer.ts::initVectorEChart()` 使用 SVG renderer，并在共享入口把根级缩放后的指针视口坐标换回图表布局坐标，避免非整数缩放造成 Canvas 位图重采样模糊或光标命中偏移；禁止页面直接调用 `echarts.init()` 或增加私有坐标补偿。非股票 ECharts 统一通过 `components/chartTheme.ts::useEChartsTheme()` 消费背景、坐标、文字、tooltip 和序列语义色；该入口与股票主题共同复用 `useResponsiveEChartsTheme()`，覆盖明暗、预设 key 和同 key 后端覆盖更新。`EquityChart`、`GrowthChart` 已纳入，不再作为固定明暗色板例外；新增图表主题消费者不得只监听 `isDark` 或在组件内维护第二套基础色板。
- 股票分时与日 K 的绘图区必须统一隐藏左右数值轴边框，价格与量能水平网格线统一使用实线；只有昨收 `0%` 基准线保留虚线语义，不得把普通网格线整体改为虚线。
- 相对走势类折线图统一遵循“左具体值、右百分比”轴契约：百分比序列和右轴保持共同相对尺度，左轴按当前主观察对象（无主观察对象时按首个序列）的基准价反算对应价格或指数点位；多标的绝对值不得直接混画到同一尺度。股票与板块走势对比统一消费 `marketCompareChart.ts::buildMarketCompareLineOption()`，禁止页面私有交换左右轴或维护第二套换算。图表内部可为边界与分隔保留更高计算精度，但所有用户可见的百分比轴标签、光标标签和悬浮值必须统一消费 `utils/marketValue.ts::formatMarketPercent()` 并显示两位小数。
- 分项评分徽章使用 `--score-high-*` / `--score-mid-*`，低分使用弱底色和占位文字色；评分热力格（`SubScoreBars`）、训练评级、买卖标记等**内联 style 颜色的组件统一经 `components/chartTheme.ts::useStatusColorPalette()` 消费当前生效 token**（强弱梯度=跌绿→成功→警示→危险→涨红；买卖=主色蓝/警示橙；评级 S/A/B/C/D=警示/成功/主色/中性/危险），不得在该组件内维护私有绿橙红色阶或 Element 默认色。
- 页面提示、弱文本、占位文本优先使用 `--app-warning-text`、`--app-muted-text`、`--app-placeholder-text`；确属 Element Plus 标准状态时可直接用 `var(--el-color-*)`。
- **颜色单一事实源**：任何状态/金融/评分/评级/买卖颜色只允许来自 `LAYOUT_PRESETS` token（经 `--el-color-*`、`--market-*`、`--app-*-text`、`--score-*` 或 `useStatusColorPalette()` 消费）；页面、组件、Canvas fallback 一律与 `balanced` 预设同值，禁止出现 `global.css` 或组件内平行硬编码的第二套色板。图表 fallback（`chartTheme.ts`/`chartUtils.ts`）也必须与预设当前值保持一致并随色板演进同步更新。
- 普通操作文字与禁用操作文字分别使用 `text`、`textMuted`；二者按 WCAG 线性相对亮度计算的差值必须 `≥ 0.06`。这是文字层级阈值的唯一数值事实源，内置 token 校验和运行时合并均须守卫；管理员预设不开放正文颜色。
- 预设运行时必须同步覆盖 Element Plus 语义色的基础色、RGB 通道、`light-3/5/7/8/9` 与 `dark-2` 派生色；`error` 与项目危险色同源。按钮、链接、提示、分段控件、焦点和禁用态不得回退到组件库默认蓝绿橙红色阶。**金融涨跌色与状态/评分文本色不走 el 的 light-*/dark-2 派生，而是直接消费预设 `marketUp`/`marketDown`/`success`/`warning`/`danger` 主色（亮色模式该主色即为提彩后的鲜亮值），避免派生工艺造成哑光。**

预设规则：

- 登录页与工作台必须同源：同一 `light/dark` 下，登录右侧交互区基础色等于工作台 `pageBg`，登录卡片可见色等于工作台 `surfaceBg`；白天和夜间的 `pageBg`、`surfaceBg` 分别保持相同，页面与卡片主体通过边框、间距和交互态表达层级，不用常驻底色色块互相分层。结构化信息内部可使用下述 `--app-section-bg` 区分标签格、KPI 与摘要组，不得借此改变图表或卡片主体底色。该关系以 `frontend/src/layout/themeSurfaces.ts` 为底色事实源，并由 `presets.spec.ts` 守卫。
- 登录或注册成功时，登录页当前可见的 `light/dark` 是本次会话的明确模式：进入工作台前先暂存，鉴权后优先写回用户偏好；只有登录页没有形成待同步模式时，才允许远端用户偏好覆盖本地模式。
- 登录页恢复为修改前的全屏左右品牌布局：左侧承载品牌字标、趋势轨迹与“看见趋势，先于共识。”主视觉文案，右侧承载独立登录/注册卡片；页面结构、文案层级与交互以 `LoginView.vue` 的恢复版本为准。
- 登录页桌面双栏以左侧约 55%、右侧约 45% 分配可用宽度，登录/注册卡片最大宽度 480px，空间不足时随右栏收缩；进入单栏布局后卡片最大宽度 430px。账号、密码、验证码等表单标签至少使用 12px 辅助标签 token，标题下说明、登录/注册切换标签和输入值使用 14px 正文 token，卡片底部说明至少使用 12px 辅助标签 token；左侧趋势数据标注中的名称和涨跌值同样不得使用装饰字号。登录页的独立品牌排版不豁免可读业务文字的字号下限。
- 登录/注册字段名由输入框内的浮动标签呈现一次：空值时标签以正文字号垂直居中，输入或浏览器自动填充后移到框内顶部并使用辅助字号，清空后恢复居中；空值聚焦不提前上移。占位属性仅用空格承接原生空值状态，不重复显示字段名；用户输入值用正文字号。
- 登录页可保留原有光晕、网格、轨迹、透明和模糊等品牌装饰，但装饰层不能改变 `themeSurfaces.ts` 和 `presets.ts` 定义的基础底色事实源；按钮、焦点、品牌强调、趋势轨迹、Logo 渐变和光晕必须消费当前运行时 `primary`，禁止遗留独立硬编码主题色。
- 登录页与应用外壳的「复盘啦」必须直接复用 `BrandMark` 的同一几何、尺寸、渐变、文字与描边定义；组件不提供 `login/shell` 场景变体，消费容器不得覆盖 `--brand-*` 形成第二套字标。只有容器不足 `184×52px` 时允许按原始宽高比整体缩放。Logo 渐变由运行时 `primary` 派生，因此新增并启用颜色预设后，登录页与工作台会同步更新。
- `balanced`（澄空蓝）使用鲜明蓝色信号；页面、边栏、卡片、悬停和文字属于固定中性基础表面，只受明暗模式控制。视觉预设只管理明暗语义色、边框、阴影和共享圆角，不得携带密度、间距、分页、抽屉、筛选状态、组件默认或响应式策略。
- 外观抽屉必须保留视觉预设区：当前只有一套时显示唯一选中项；“视觉预设”页新增并启用自定义项后，无需改前端代码即可出现在抽屉并驱动运行时。登录页不提供视觉预设管理入口。
- 外观抽屉必须提供独立的「界面比例」：100% 表示设计 token 的原始尺寸，不表示某台屏幕的自动推荐值。`auto` 使用操作系统已经折算后的当前屏幕可用 CSS 宽高，以 `2560×1440` 可用面积作为原始设计尺寸的自动参考点，按面积的低指数连续曲线双向微调；指数由系统外观配置 `ui.display.auto_scale_exponent` 提供，默认 `0.10`、范围 `0～1`、步长 `0.01`，`0` 表示自动保持 100%；缺项或非法运行时值回退默认，保存与首屏缓存恢复必须同步应用，手动模式和手动比例不受该系统值变化影响；小屏缩小以保留总览、大屏放大以改善远距离阅读，自动范围限制为 `90%~110%`。不得枚举设备型号、分辨率档位，也不得把物理像素、`devicePixelRatio` 或浏览器页级缩放当成目标比例。`custom` 允许在 `50%~150%` 内按 1% 连续微调，首次从自动切换时继承当前比例，避免视觉跳变；滑块调整自动保存当前显示器可用 CSS 宽高与比例档案，宽高均在档案 `±15%` 内时使用综合距离最近项，`5%` 内重复调整更新原项，无匹配时回退最近一次自定义比例，档案只属于当前用户且不直接暴露管理界面。「恢复100%」进入自定义 100% 并更新当前尺寸档案。该能力通过应用根级 `--app-display-scale` 将 `#app` 以左上角为原点整体 `zoom`，统一缩放字体、控件、间距、图表容器、应用内抽屉与锚点浮层，并让布局与原生命中测试消费同一坐标系；浏览器会按 `zoom` 自动折算布局画布，禁止再叠加倒数宽高补偿。滑块不重复显示会遮挡模式选项的数值气泡。布局宽高、滚动量和组件配置必须使用 `client/offset` 布局像素；只有命中测试、指针位置和视口对齐使用 `getBoundingClientRect/clientX/clientY`，两套坐标相减后必须通过共享换算工具转回布局像素。缩放后必须触发依赖尺寸的画布重测；Tooltip、Popover、Select、DatePicker 等依赖触发器坐标的 Popper 浮层必须通过应用级唯一容器管理入口挂入 `#app`，与触发器共同消费浏览器原生 `zoom` 坐标系；依赖层允许通过锁版本补丁把视口裁剪边界换算到该布局坐标系，页面不得再增加私有补偿、二次缩放或逐个关闭 Teleport。Dialog、Drawer、MessageBox 的 body 级遮罩复用整体 `zoom`，内部面板不得重复缩放；全屏抽屉高度和弹窗视口上限必须服从该画布。Message、Notification 按浏览器视口堆叠，保持 100% 自身比例。
- 启用预设的名称与视觉 token、独立的自动缩放指数通过登录公开配置下发，并分别写入首屏安全缓存。登录页与工作台必须共同消费同一公开配置，不得各自解析或维护另一套。公开配置禁止携带页面、组件或响应式布局字段。
- 行情身份摘要（`MarketDetailHero`）、行情主次栏头（`AppWorkspacePane`）、板块静态指标和交易纪律快捷卡保持中性底色，不恢复主色浅背景或渐变强调；真实选中、悬停及状态反馈继续沿用既有语义。
- 调整基础表面必须同步维护 `light`、`dark`、`themeSurfaces.ts` 与 `presets.spec.ts`；调整预设能力必须验证后端目录、运行时选择和固定表面不受覆盖。
- 页面设置抽屉保留 `32%` 黑色遮光层，用于明确浮层焦点和点击外部关闭边界；遮光层属于临时交互状态，不参与主题底色定义，抽屉内容面与页面常驻容器仍必须使用中性明暗表面。
- `surfaceHover` 用于 hover、选中或明确可操作控件状态；禁用控件复用该基础色值的约定见 §4「按钮与输入」。常驻信息分区与抽屉设置组按 §6 的职责分别使用分区面和内容面；`--app-section-bg` 当前与 `surfaceHover` 同源，但职责独立，页面不得直接借用悬停 token 代替分区变量或自行调深。

## 3. Typography Rules

字体栈以系统 UI 字体为主：`system-ui, -apple-system, BlinkMacSystemFont, Segoe UI Variable, Segoe UI, Microsoft YaHei UI, PingFang SC, Hiragino Sans GB, sans-serif`。macOS 由系统字体与苹方承接，Windows 由 Segoe UI 与微软雅黑 UI 承接；不得引入需要联网加载的字体。

排版事实源：

- token 落地在 `frontend/src/styles/global.css`，包括 `--app-font-family-base`、`--app-font-size-*`、`--app-line-height-*`、`--app-font-weight-*`。
- 页面私有样式不得新增游离字体族；正文、导航、表单、图表均使用 `--app-font-family-base`。代码/配置值可消费 `--app-font-family-mono`；品牌和登录主视觉的局部例外见 §3.5。
- 新增文字样式必须先判断是否能消费 `.app-page-title`、`.app-section-title`、`.app-drawer-title`、`.app-drawer-subtitle`、`.app-body-text`、`.app-caption-text`、`.app-micro-text`、`.app-data-text`、`.app-data-emphasis` 或对应 token。
- 常规行高使用表内 token；图标/徽标贴边用 `--app-line-height-solid`，紧凑说明用 `--app-line-height-compact` / `--app-line-height-comfy`，长说明用 `--app-line-height-reading` / `--app-line-height-longform`，极小角标用 `--app-line-height-ornament` / `--app-line-height-tiny`。

| 层级 | 强制 token / 值 | 使用场景 |
|---|---|---|
| 页面标题 | `--app-font-size-page-title` 22px / 700 / 30px；紧凑页可用 `--app-font-size-page-title-sm` 20px | 页面主标题、工作台名称、配置中心一级标题 |
| 工作区对象标题 | `--app-font-size-title-md` 18px / 700 / 26px | 分析区对象名、头像首字；不得替代页面主标题 |
| 分区标题 | `--app-font-size-section-title` 15px / 600 / 22px | 卡片标题、标准抽屉配置组标题、局部紧凑工具抽屉标题；紧凑抽屉内的一级分组降为正文尺寸 14px / 600 / 22px |
| 标准抽屉标题 | `--app-font-size-drawer-title` 16px / 600 / 24px | 页面详情、页面设置、全局功能抽屉标题 |
| 正文 | `--app-font-size-body` 14px / 400 / 22px | 表单、普通说明、主体内容 |
| 表格正文 | 默认 `--app-font-size-table` 13px / 400 / 20px；不高于 `1.5dppx` 的低像素密度屏幕使用 14px / 22px | 数据表格、列表、密集参数行 |
| 辅助标签 | `--app-font-size-caption` 12px / 400 / 18px | 单位、提示、来源、次级说明、tag 内文 |
| 微型标签 | `--app-font-size-micro` 11px / 400 / 16px | 顶栏弱标签、状态小字、空间极窄的 badge；禁止用于正文 |
| 数字强调 | `--app-font-size-data` 16px / 600 / 24px；大 KPI 可用 `--app-font-size-kpi-lg` 26px / 700 / 32px；单组唯一主数值可用 `--app-font-size-kpi-xl` 32px / 700 / 38px | KPI、收益、评分、排名、需要横向比较的数字；紧凑统计主值可用 `--app-font-size-page-title-sm` / 700，常驻行情摘要由共享组件承载主值和补充值的角色差异 |

排版规则：

- 标题用于定位页面和分区，不用于装饰性大字。
- 页面顶部标题区统一结构：`<h2 class="app-page-title">` 承载页面标题，说明性长文进 `HelpTip`（内嵌标题内，勿放工具栏/`<p>` 内避免下沉），标题下用一行 `<p class="page-subtitle">` 说明页面用途。`page-subtitle` 为全局语义类（`--el-text-color-secondary` + caption），禁止页面私有定义 `.page-subtitle`/`.page-sub`/`.sub` 颜色字号。
- 可导航页面标题必须通过 `useMenuPageTitle()` 读取后端菜单树中的当前名称，路由 `meta.title` 只作菜单未就绪时的稳定回退；页面不得重复硬编码菜单标题。阶段标题通过该入口的 `suffix` 统一拼接，保持菜单改名后基础标题同步变化。
- 页面顶部标题字号唯一来源是全局 `app-page-title`（22px），禁止页面用 `.page-head h2`/`.title h2`/`.title-row` 等私有选择器覆盖标题字号或边距；详情页对象标题（个股/板块名）同样走 `app-page-title`。
- 标题内嵌 `HelpTip` 时，标题行使用 `align-items: center`（flex 或 `vertical-align: middle`）保证圆点与标题垂直居中，不随行高下沉。
- 页面、分区、组件组和弹层标题只保留名称，不在标题中用中文或英文括号追加用途、适用范围、技术标识等说明；简短说明使用 `HelpHint`，多段说明使用 `HelpTip`。标题收展和帮助入口独立操作，不因查看说明改变折叠状态。
- 页面主体新增 `font-size`、`line-height`、`font-weight` 时必须引用上述 token 或语义类；原始数字仅允许出现在共享 token 定义、§3.5 登记的品牌选择器或图表数字适配器中；第三方适配、角标和图标同样消费已有 token，不是整文件豁免。禁止页面内联添加另一套字体规则。
- 10px 以下只允许使用 `--app-font-size-ornament` 或 `--app-icon-size-xs`，用于图标内部标记、红点角标或不可读正文之外的装饰性标尺；不得用于业务说明、表格、表单、按钮、筛选项。
- 11px 只用于弱标签或极窄 chrome 信息；业务内容、表格单元格、表单 label、按钮文案不得小于 12px。
- 页面设置抽屉的字体按语义角色固定：抽屉标题 16px，一级分类 15px，二级及更深可折叠节点统一 14px，事项名 13px，辅助说明 12px。禁止按 DOM 深度继续缩小节点字号，也不得通过全大写、字距或虚下划线代替真实层级；页面密度只调整间距，不改写这套字体角色。
- 抽屉标题统一消费 `PageDrawer` 的标题档位或 `.app-drawer-title`：标准抽屉使用 16px / 600 / 24px，嵌入局部工作区且空间受限的工具抽屉可声明 `compact`，使用 15px / 600 / 22px；标准抽屉内的一级 `SettingsGroup` 为 15px / 600 / 22px，紧凑抽屉内自动降为 14px / 600 / 22px，分段选项使用 13px / 600，形成清晰的标题—分组—选项层级。该差异由 `PageDrawerSurface` 与 `SettingsGroup` 的共享上下文承载，业务抽屉不得私自覆盖。副标题统一消费 `.app-drawer-subtitle` 的 12px / 400 / 18px。禁止依赖 Element Plus、原生标题标签默认字号字重或页面私有字号。
- 微字号（`--app-font-size-micro`/`tiny`/`ornament`）不得通过无 `>` 限定的宽泛后代选择器（如 `.xx span`、`.xx strong`）声明——此类规则会把它误传给嵌套的数值、标题等本不该用小字号的元素。微字号只允许作用于语义类、`:global` 或 `>` 限定的直接子级；容器用常规字号，内部小字通过独立子级规则声明。该约束由 `typography-spacing-system.spec.ts` 强制，禁止用 `>` 缺失的选择器绕过。
- 表格内长文本默认省略、tooltip 或详情承接，不默认自动换行撑高行高。
- 说明入口的选型、正文结构和可访问名称统一见[提示、截断与可访问名称](#提示截断与可访问名称)；字号与行高继续消费本节 token。
- 组件内提示、说明、空状态、校验文案必须按容器宽度排版，避免长句硬塞一行；必要时分行、缩短文案或交给 tooltip / popover 承接，不得挤压主操作区或造成文本重叠。
- 按钮、标签、抽屉标题、表格控件中的文字不得溢出容器。
- 金融数字按列右对齐或按业务组件一致处理，避免同列数字参差。
- 同一行并列的对象识别块、摘要组、状态块等同层信息块，外层默认在交叉轴居中；表单和工具栏继续遵守各自的控件基线规则。只有明确包含多行标题/说明、且右侧操作需要钉住首行的页面页头使用顶部对齐。不得把页面页头的顶部对齐规则套用到单行摘要或指标组。
- 行情摘要统一消费 `StockQuoteSummary` 与 `stockQuoteSummaryHtml()`：无标签最新价主列垂直居中，可在主值下展示涨跌额与涨跌幅辅助行，并以主题边框和信息列分隔；列宽由内容推导，禁止消费页硬编码固定像素列宽。K 线浮层与个股详情采用共享字符容量：以最新 K 线为基线，只汇总当前可视窗口内的格式化行情与测算结果，主值与辅助行均额外预留一个数字字符，中文单位与数字串按实际出现的组合取最大宽度，不叠加不同字段各自的最长部分；光标移动只更新内容，切股、换周期、刷新或调整窗口时重新计算并允许收窄，不扫描窗口外历史或均线热身数据。个股详情附加字段一并参与容量汇总；详情市值随光标日期联动，周期 K 线取最后实际交易日的市值，缺口显示空值；股本随历史日期读取同日逐日事实，周期 K 线取最后实际交易日股本，缺口保持为空，不回退到最新股本；字段名保持总股本/流通股，通过共享 HelpHint 解释日期和来源口径，图标支持悬浮及键盘焦点提示；历史估值没有逐日事实时保持为空，单位按当前数值换算且不触发光标列宽重算；字符容量跟随字体与界面比例，空间不足时由摘要区内横向滚动承接。分时等未指定容量的消费者保留内容自适应。调用方通过 `rowsPerColumn` 决定每列行数，通过 `columnGap=standard|relaxed` 选择标准或宽松列距，默认 `standard` 以保持既有消费者不变；个股详情显式使用 `relaxed`。常驻头部补充分区的分隔线两侧统一消费 `--stock-quote-section-gap`；行情浮层采用紧凑表格和共享内距，截止测算在表格下方单行展示，不额外占旁列；分时分钟浮层复用同一 HTML、字阶与缩放外壳，均价保持序列身份色。K 线和个股详情头部每列四行，分时每列两行；开盘位于信息首项。K 线浮层与个股详情头部的单根行情字段必须共同消费 `buildKlineQuoteSummary()`，统一字段名称、顺序、精度、单位和空值，详情头部只在该基础摘要后追加量比、市值、估值和股本；总市值、流通市值、总股本、流通股必须连续组成同一信息列。所属行业等对象关系不得混入行情数值字段，统一由所属板块面板承载。K 线浮层、分时弹窗顶部与个股详情共享同一字段分组模型，不再使用全局 `.app-metric-*` 等宽指标网格；个股详情仅关闭 K 线内容浮层，仍保留十字光标、标题联动、缩放与分时下钻，其他消费者默认开启。
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
| 普通内容卡片/面板内边距 | `--layout-card-padding` = 16px；密集面板可 12px | 高密表格容器可压缩但不得牺牲可读性 |
| 大区块分隔 | 16px 或 24px | 独立业务块、KPI 到主表、说明组到表单 |
| 空态/异常态 | 使用 `app-empty*` / `AppStateBlock` | 不自定义另一套图标、字号、间距 |

页面密度是独立于视觉预设的系统契约，只调整空间，不改变字号、字重、颜色、图标与文字的 6px 内部间距或显式 `small` / `large` 的业务层级。三档矩阵为：

| 语义变量 | 紧凑 | 标准 | 宽松 |
|---|---:|---:|---:|
| 页面/分区间距 | 8px | 12px | 16px |
| 卡片/面板内距 | 12px | 16px | 24px |
| 控件行/按钮组间距 | 6px | 8px | 12px |
| 表单/设置项纵向间距 | 8px | 12px | 16px |
| 默认控件高度 | 28px | 32px | 36px |
| 默认按钮水平内距 | 10px | 12px | 14px |
| 表格单元格上下内距 | 6px | 10px | 14px |
| 页面浮层内距/分组间距 | 12px / 8px | 16px / 12px | 24px / 16px |

矩阵由 `LayoutHost` 的有效 `density` 写入 `--app-density-*`，`--app-space-*` 始终是固定基础刻度。页面主体、页面设置抽屉与由页面触发的 Drawer/Dialog/Popover 共享密度；全局导航、消息通知和外观设置保持标准密度。页面不得编写私有 `.lh-density-*` 或表格密度规则。

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
- Element Plus Select、Popover、Tooltip 等 Teleport 浮层中的复合选项必须声明唯一 `popper-class`，通过该全局边界设置行内布局与 gap；通用选项行复用 `.app-option-popper`，名称与次级信息消费 `.app-option-label` / `.app-option-meta`，内部信息组继续复用 `.app-inline-info`；不得使用无法命中 `body` 下浮层的 scoped 后代选择器。
- 标准表单下拉和日期面板默认位于触发器下方，只在下方左右对齐间回退；共享控件与页面特殊选择器统一消费 `floatingPlacement.ts` 的位置契约。只有经明确交互证明的场景才允许覆盖到其他方位。

### 3.3 Tag, Badge & Chip Rules

依附主体的非阻断辅助状态（如历史结果沿用、待处理提醒）优先使用 `AppStatusDot` 的黄色状态点，避免另加文字标签挤占主体；说明通过 `AppHoverInfo` 悬浮或键盘聚焦显示，并保留可访问名称。圆形头像/图标入口使用 `placement="top-right"` 依附右上角，宿主提供定位容器；`AppIconButton` 使用 `badge` 插槽，不把角标放进图形的横向排列。文本旁的提示保持默认 `inline`。已有整体说明时复用该浮层，不叠加第二个提示。独立主要业务状态仍按下表使用标签。

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
- 标签正文使用 `--app-font-size-caption`；11px 只用于依附 badge，业务主体不得低于12px。名称过长时在标签内部省略，并由 `AppOverflowTooltipHost` 承接原文；超长提示按统一高度截断。
- `plain` 用于中性分类和对象关系，`light` 用于当前选中或需要增强识别的状态，`dark` 仅用于少量高优先级状态；不为装饰改变 effect。
- 金融涨跌使用 `--market-up-color` / `--market-down-color`；系统状态使用 Element Plus `type`；字典色和股票分组色分别通过 `dictTagStyle()` 与 `stockGroupTagStyle()` 收口，页面不复制颜色、透明度或边框算法。
- 外观相似的标签先按行为分类：静态属性使用中性文字和边框，不响应 hover；进入详情的名称使用主题主色及共享链接悬浮／按下／焦点反馈，无导航权限时文字与边框一起退回中性；切换筛选或当前观察的 chip 使用 `aria-pressed`（多选可用 `aria-checked`）及对应选择态，不增加链接下划线。明确承载警告等业务状态的筛选标签保留语义色，以选中外观和 ARIA 表达选择，不强制变蓝。字典和自选分组等已登记身份色保留其专用 helper，分组导航复用链接下划线而不覆盖身份色。标签内部涨跌幅继续使用金融色，不能把整个标签染成涨跌色。
- 已生效搜索条件摘要是可编辑／清除的条件单元，不按静态元信息标签中性化；统一消费 `AppAdvancedSearch`，视觉与交互规则见[列表高级搜索](#列表高级搜索)。
- 稳定业务语义出现在第二个消费点时，必须根据变化原因收口为领域组件、helper 或 schema；不创建只转发 `el-tag` 属性的万能 `AppTag`，也不强行合并语义或生命周期不同的标签。已有领域组件以下方“真实复用组件清单”为唯一目录。

### 3.4 应用导航字阶与尺寸

适用于应用侧栏、双层顶栏、顶栏下拉、工作标签、辅助分组提示与面包屑。字体和尺寸的实现入口为 `styles/global.css` 的 `--app-nav-*`，字体继承 `--app-font-family-base` 的系统无衬线栈。不同操作系统按字体栈回退，保持同一字号/字重角色，不要求字形完全相同。下表是100%界面比例下的CSS基线摘要；应用显示比例统一缩放导航及浮层，禁止按单个菜单补偿字号。

| 导航角色 | 字号 | 普通 / 当前字重 | 文字行高 | 行容器高度 |
|---|---:|---:|---:|---|
| 侧栏常驻分区标题 | 12px | 600 / 600 | 18px | 自然高度，保持分区标题内距 |
| 侧栏主入口（含原二级提升项、一级直达页及直接下级分组） | 14px | 600 / 600 | 22px | 44px |
| 侧栏三级及更深入口 | 14px | 400 / 600 | 22px | 36px |
| 双顶栏一级菜单 | 14px | 600 / 600 | 22px | 宿主随顶栏高度；悬停/焦点面为32px |
| 双顶栏二级菜单 | 14px | 600 / 600 | 22px | 32px |
| 顶栏下拉叶子 | 14px | 400 / 600 | 22px | 最小32px |
| 工作标签 | 13px | 400 / 600 | 18px | 32px |
| 双顶栏辅助分组提示 | 12px | 400 / — | 18px | 次栏内自然高度 |
| 当前位置（面包屑） | 14px | 400 / 600 | 22px | 随顶栏高度，垂直居中 |

- 主菜单使用 `--app-nav-font-size` / `--app-nav-line-height`，分区标题及辅助提示使用 `--app-nav-meta-font-size` / `--app-nav-meta-line-height`。工作标签使用独立的 `--app-nav-tab-font-size`（复用13px基础字阶），行高沿用 `--app-nav-meta-line-height`，不随辅助标题字号联动。字重按 `--app-nav-weight-primary`、`--app-nav-weight-regular`、`--app-nav-weight-active` 分配；同角色不得回落组件库默认字号或另写私有字体。
- 主入口以14px/600保证定位强度；下级保留14px正文可读性，通过缩进、分组、当前字重和定位标记表达层级，不随菜单深度继续缩小。12px只用于本表列明的辅助导航，不能用于压缩主菜单或面包屑；长名称通过省略和溢出说明承接。
- 悬停、按下不改变字号或字重。当前项由现有路由/受控值决定，普通下级、下拉叶子及工作标签从400提升至600；主入口已为600，保持字重并通过颜色和定位标记强化。
- 行容器高度决定点击区域，文字行高决定排版，二者不得混用。侧栏下级每层缩进12px；主菜单图标使用18px占位，下级及横向二级/下拉图形为16px；顶栏一级保留24px图标框和15px图形，侧栏分区标题也保留18px图标。图标与文字角色分开定义，不以缩小文字去迁就图标。
- 二级顶栏和工作标签共用 `.app-nav-context-entry`：32px高、6px图文间距，圆角引用 `--layout-control-radius`；二级顶栏水平内距8px，工作页签水平内距12px。一级保留原有图标框与顶栏底部下划线，仅悬停/焦点面收紧；文字统一不改变其选中外观。外壳宽高、导航定位及颜色规则见“应用外壳”，悬停/选中状态见“动效与状态过渡”。

### 3.5 全站字体角色、例外与校验

本节与本章角色表是字体规范唯一入口；页面模板和组件清单只引用，不平行维护数值。适用范围包括全部业务页、系统页、登录表单、导航、抽屉、弹窗、表格、可操作卡片和图表文字；统一指同一角色共用规则，不要求标题、正文、说明和数据使用同一字号。

字重使用范围：`--app-font-weight-regular` 用于正文和辅助内容；`--app-font-weight-medium` 用于设置事项名、三级弱分组名、配置选项名及帮助/审计对象的轻强调；`--app-font-weight-section` 用于分区、主导航、选中项、控件和普通数字强调；`--app-font-weight-strong` 用于页面/对象标题、较大统计主值和行内语义强调。原生 `b/strong/h1…h6` 由全局样式固定为 strong，再由具体角色覆盖，禁止依赖浏览器 `bolder` 累积到 900。普通数据及对象强调必须完整消费 data 字号、section 字重和 data 行高，不能只换字号。

角色补充与底层 token 登记：

| 类别 | 共享 token / 入口 | 边界 |
|---|---|---|
| 字体 | `--app-font-family-base`、`--app-font-family-mono` | 基础界面和图表同栈；等宽仅用于代码、配置值、证券代码及技术数值 |
| 标题行高 | `--app-line-height-page-title`、`--app-line-height-title-md`、`--app-line-height-drawer-title`、`--app-line-height-section-title` | 按本章标题角色使用，不跟随 DOM 深度缩小 |
| 数据行高 | `--app-line-height-data`、`--app-line-height-kpi-lg`、`--app-line-height-kpi-xl` | 数值与对应字号成组使用 |
| 正文及说明行高 | `--app-line-height-body`、`--app-line-height-table`、`--app-line-height-caption`、`--app-line-height-micro` | 表格低像素密度分支仍由全局 token 管理 |
| 比例行高 | `--app-line-height-solid`、`--app-line-height-tight`、`--app-line-height-compact`、`--app-line-height-comfy`、`--app-line-height-reading`、`--app-line-height-longform` | 依次用于贴边标记、紧凑图形、短说明、普通多行说明、阅读和长说明 |
| 图标字号 | `--app-icon-size-xs`、`--app-icon-size-sm` | 图形内部标记与常规提示/工具图标，不借用数据字阶或附带文字字重 |
| 极小文字 | `--app-font-size-tiny`、`--app-font-size-ornament`，配合 `--app-line-height-tiny`、`--app-line-height-ornament` | 仅图表刻度、图形内部标记及非正文装饰；不得扩散到业务标签 |
| 图表 | `chartTheme.ts` 的 `chartTypography()`、`echartsRenderer.ts` | SVG 文字继承基础字体；axis/compact/body 分别读取 tiny/micro/caption，标注行高读取 ornament；字重读取全局字重 token。仅适配器提供 CSS 未就绪时的数字回退，消费页不得写数字字体对象 |
| 行情浮层 | `stockQuoteSummaryHtml()` | HTML 字号和行高直接引用 CSS token；主值 data/strong、底行测算值 caption/strong、辅助行 micro/regular，按已有浮层缩放机制换算。DOM 常驻摘要由 `StockQuoteSummary` 管理紧凑角色，页面不能复制配方 |

品牌例外只允许以下范围，例外值由源码守卫按选择器、属性和值精确登记：`BrandMark .brand-mark__word-main` 的字标字号和字重；登录 `.mr-value` 的流式主数值字号；`.login-brand-copy h1` 的流式字号、宋体栈和品牌行高；`.login-card-title h2` 的宋体栈和桌面字号。登录表单、切换标签和主按钮不在例外内，字重不得另设 650。斜体仅用于品牌字标、辅助副标或文本语义，普通标题和菜单不引入私有斜体。

实现与校验入口：

- CSS token 和语义类统一在 `frontend/src/styles/global.css`；抽屉层级仅允许 `PageDrawerSurface` 映射已有标题字号，不新造尺度。新增或变更根字体 token 必须同步本章角色登记。
- 执行 `cd frontend && npm run check:typography`：解析全部生产 Vue/CSS/TS，检查字体变量定义、角色类型、别名循环、CSS 简写、模板内联样式、脚本字体对象及 HTML tooltip 样式；品牌例外不豁免整个文件。`npm run build` 自动先执行该守卫。
- `typography-audit.spec.ts` 以违规夹具证明拦截有效；`typography-spacing-system.spec.ts` 保留语义组件、导航、微字号选择器和间距契约；`chartTypography.spec.ts` 验证图表真实读取 CSS token。
- 静态守卫不能代替浏览器的层叠、裁切和继承检查。全局字体变更还需生产构建，并用内置浏览器抽查导航、数据指标、长说明、表格、抽屉及图表；记录实际状态，不把未打开的页面或设备写成实测通过。

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
- 新开发 Vue 组件时先判断它是页面私有业务片段、业务域复用组件还是全局真实复用组件；复用组件必须维护组件清单、消费页面和测试。只有需要被布局或组件配置体系识别时，才继续新增系统组件 kind；只有存在真实可消费的 Web 可配置属性时，才继续登记 `COMPONENT_FIELD_DEFS` 并完成代码默认、页面、用户三层配置闭环。
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

清单只登记组件职责、路径、系统组件关系及复用边界；通用设计细则引用本文对应章节，业务规则引用模块架构。props、emits 和局部模板实现以组件源码与测试为准，不在每行重复排版、状态或采集参数规则。

| 真实组件 | 路径 | 用途 | 系统组件关系 | 使用规则 |
|---|---|---|---|---|
| `PageSettingsDrawer` | `frontend/src/components/PageSettingsDrawer.vue` | 统一页面设置抽屉运行时组件 | 对应 `settings-drawer` 种类；`size` 及内部折叠偏好由 PG `user_preference` 承接，`bodyScroll` 只允许 page 层；分组固定可折叠，首次全部展开，记忆边界见本节“设置抽屉” | registry 页面的页面设置统一复用；分组、偏好与默认值规则见[设置抽屉](#设置抽屉)。 |
| `AppStatusDot` | `frontend/src/components/AppStatusDot.vue` | 依附主体的黄色辅助状态点 | 无直接系统组件种类 | 头像待打卡、走势历史提示、天梯热点共用；统一 warning 色、圆点几何和可访问名称，简短说明复用 AppHoverInfo；圆形入口用 top-right 角标模式及宿主定位容器，文本用 inline，不用常驻文字扩宽主体 |
| `PageSettingsTrigger` | `frontend/src/components/PageSettingsTrigger.vue` | 页面设置统一入口 | 触发 registry 页面中的 `settings-drawer` | 仅 `pageRegistry.supportsPageSettings !== false` 的真实消费页面显示；平台布局管理页不开放个人设置，不登记假入口 |
| `PageDrawer` | `frontend/src/components/PageDrawer.vue` | 全站抽屉唯一外壳与边界组件 | 无直接系统组件种类；内部唯一消费 `el-drawer` 和 `PageDrawerSurface` | 仅供页面设置、实时日志、资产搜索、主从窄屏回退和应用级专用抽屉直接消费；普通详情使用 AppDetailDrawer，边界与宽度见[弹窗与抽屉](#弹窗与抽屉)。 |
| `PageDrawerSurface` | `frontend/src/components/PageDrawerSurface.vue` | 全站抽屉统一内容面板 | 无直接系统组件种类；仅由 `PageDrawer` 内部消费 | 仅由 PageDrawer 内部消费；外壳差异经语义属性和插槽表达，禁止页面复制面板外观。 |
| `AppDialog` | `frontend/src/components/AppDialog.vue` | 页面短表单、单组编辑和轻量查看的统一弹窗外壳 | 无直接系统组件种类；内部消费 `el-dialog` | 短表单与轻量查看统一消费；语义宽度、挂载边界及正文滚动见[弹窗与抽屉](#弹窗与抽屉)。 |
| `AppDetailDrawer` | `frontend/src/components/AppDetailDrawer.vue` | 完整详情、长编辑、历史版本和审计上下文的统一抽屉结构 | 无直接系统组件种类；内部消费 `PageDrawer` 的统一外壳 | 普通对象详情、长编辑和审计上下文统一消费；外壳委托 PageDrawer，详情分区见[弹窗与抽屉](#弹窗与抽屉)。 |
| `AppDetailSection` / `AppDetailFields` / `AppDetailField` | `frontend/src/components/AppDetailSection.vue`、`frontend/src/components/AppDetailFields.vue`、`frontend/src/components/AppDetailField.vue` | 详情分区和规则型键值展示 | 无直接系统组件种类；作为详情抽屉或页面详情的内容结构 | 详情分区和键值展示统一消费，禁止私建详情网格；布局及空值规则见[弹窗与抽屉](#弹窗与抽屉)。 |
| `LayoutHost` | `frontend/src/layout/components/LayoutHost.vue` | registry 页面统一布局、slot、滚动和 overlay 运行时宿主 | 消费 `PageLayout` 中登记的系统组件种类与区域 | 所有 registry 业务页面统一消费；页面不得绕过宿主手写页面外壳、主成长区、滚动归属或 overlay 边界 |
| `ComponentAutoSettings` | `frontend/src/components/ComponentAutoSettings.vue` | 组件特性唯一渲染器 | 按 slot kind 自动消费 `COMPONENT_FIELD_DEFS`，再结合 `componentMeta` / slot `config` / `fieldApplicability` 判定实例适用性 | 页面设置与布局编辑器共用唯一渲染器；候选、默认值和层级限制见[设置抽屉](#设置抽屉)与[组件特性配置治理](#73-组件特性配置治理)。 |
| `SettingsGroup` | `frontend/src/components/SettingsGroup.vue` | 设置型抽屉的递归分组与统一卡片边界 | 无直接系统组件种类 | 页面设置、视觉环境和局部工具抽屉的同层功能分组统一复用；一级使用卡片边界，二级及更深使用统一 14px 节点标题、箭头、缩进和结构线，不再逐级缩小字号；存在直接子节点时标题区自动显示“收起/展开下级分组”图标操作；无需折叠的固定分组传 `collapsible=false`，不得复制私有分组边框；不直接用于主内容区配置面板 |
| `PageSettingSection` | `frontend/src/components/PageSettingSection.vue` | 页面设置业务选项分区 | 无直接系统组件种类 | 仅作为 `SettingsGroup level=2` 的业务语义薄封装，以必填 `sectionKey` 声明稳定分区标识；不得维护第二套标题、折叠或间距样式 |
| `AppFormHelp` | `frontend/src/components/AppFormHelp.vue` | 全站表单字段与补充说明的标记、caption 字阶和续行排版 | 无直接系统组件种类或配置字段 | 表单字段及补充说明统一消费；语义、标记与排版见[表单辅助说明](#表单辅助说明)。 |
| `PageSettingItem` | `frontend/src/components/PageSettingItem.vue` | 设置抽屉的事项名、控件与辅助说明布局 | 无直接系统组件种类 | 设置抽屉字段块统一消费；简单开关可用行内布局，帮助选型与字阶见[设置抽屉](#设置抽屉)及[Typography Rules](#3-typography-rules)。 |
| `ConfigPanelSection` | `frontend/src/components/config/ConfigPanelSection.vue` | 主内容区配置面板的可折叠分组容器 | 对应 `config-panel` 种类；读取 `collapsibleSections`、`defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | 系统设置等主面板配置分组共用；字段帮助使用 HelpHint / HelpTip，组说明随所属层级展示或收展；可选 summary 在收起时保留简短摘要，紧凑子分区标题/摘要自然换行；摘要不伸展占满横向空间，分隔线紧接文案延伸，二级分区间距由共享组件统一维护；不传时保持原有布局。 |
| `PageSegmented` | `frontend/src/components/PageSegmented.vue` | 页面设置和业务偏好的分段选择控件 | 无直接系统组件种类 | 枚举选择与轻量视图切换复用；选型见[分段选择](#分段选择)，状态、键盘和动效分别引用对应规范 |
| `PageSettingsApplyButton` | `frontend/src/components/PageSettingsApplyButton.vue` | 设置抽屉采用当前页面值的统一按钮 | 无直接系统组件种类 | 采用页面当前值的共享入口；保存行为与布局见[设置抽屉](#设置抽屉)，视觉角色见[按钮角色与完整状态矩阵](#按钮角色与完整状态矩阵) |
| `BoardTaskScopeFields` | `frontend/src/components/data/BoardTaskScopeFields.vue` | 板块采集范围和分阶段参数组 | 无直接系统组件种类 | 数据采集与任务调度的板块参数表单共用；采集语义见[板块采集架构](agent-works/architecture/board-collection.md)。 |
| `CurrentDayFallbackField` | `frontend/src/components/data/CurrentDayFallbackField.vue` | 增量行情的当日退级开关 | 无直接系统组件种类 | 个股与板块增量表单共用；是否允许当日退级由任务方案决定，日期门禁见[采集架构](agent-works/architecture/stock-collection.md)。 |
| `StockCodeMultiSelect` | `frontend/src/components/data/StockCodeMultiSelect.vue` | 股票代码/名称远程搜索与多选输入，统一已选项保留、批量粘贴、大小写规范化、稳定去重、候选错误和搜索竞态保护 | 无直接系统组件种类；作为业务表单内的股票范围控件 | 个股采集范围、数据概览逐股体检、个股走势关联板块调度统一消费；允许保留用户手工输入并由业务提交接口做最终合法性校验，候选加载失败不得清空已选值；消费页只响应标准 `v-model` 与 `change`，不得复制远程搜索、粘贴拆分或去重逻辑 |
| `StockIngestScopeFields` | `frontend/src/components/data/StockIngestScopeFields.vue` | 个股一体化采集的场景、范围和安全参数组 | 无直接系统组件种类 | 数据采集与任务调度共用；场景编排及安全边界见[采集架构](agent-works/architecture/stock-collection.md)，页面不复制参数分支。 |
| `IntradayTaskScopeFields` | `frontend/src/components/data/IntradayTaskScopeFields.vue` | 分时手动采集与独立调度共用的模式、股票范围及重采日期字段 | 无直接系统组件种类 | 分时采集与任务调度共用；统一消费 `intradayIngest.ts` 参数校验、领域控件及 `AppFormHelp`；业务语义见[分时架构](agent-works/architecture/stock-intraday.md)。 |
| `ResultMaintenanceTaskFields` | `frontend/src/components/data/ResultMaintenanceTaskFields.vue` | 结果失效与重算任务的目标范围、日期和股票范围字段组 | 无直接系统组件种类 | 数据采集与任务调度统一复用；页面只传任务类型和表单值，不复制目标范围候选、股票范围分支或任务说明 |
| `PageToggleRow` | `frontend/src/components/PageToggleRow.vue` | 页面设置和业务偏好的开关行 | 无直接系统组件种类 | 业务选项、列显隐、布尔设置优先复用；事项名与 `PageSettingItem` 同为 13px，默认高度跟随页面密度，显式 `sm` 保持业务小尺寸；简短说明复用 `HelpHint` |
| `AppFilterSwitch` | `frontend/src/components/AppFilterSwitch.vue` | 筛选操作栏中独立布尔条件的紧凑开关 | `filter-bar` 内的业务条件，不新增系统组件种类 | 连板天梯的“忽略 ST”“仅一字板”共同消费；名称在开启和关闭时均可见，开关有同名可访问名称；切换只更新筛选值并沿用页面既有查询、默认值和重置流程，不用于表格批量选择或多选集合 |
| `AppAdvancedSearch` | `frontend/src/components/AppAdvancedSearch.vue` | 列表筛选常显与高级区统一收纳，复用 `AppControlRow`，保留控件实例、条件值与领域事件 | `filter-bar.commonFields`，候选与默认值统一由 `layout/searchGroups.ts` 驱动页面登记，运行时权限候选经 `LayoutHost` 共享给设置抽屉 | 每个独立列表 ≥3 个可收纳条件时常显两个，高级区默认收起；收起不清空、不查询；摘要体现隐藏的实际限制（包括默认限制），可定位和按字段清除；复杂日期范围算一个条件，整页上下文不收纳；禁止复制页面私有收展与配置保存逻辑 |
| `AppControlRow` / `AppControlItem` | `frontend/src/components/AppControlRow.vue`、`frontend/src/components/AppControlItem.vue` | 页面工具行、查询行和参数行的通用横向控件容器；控件行默认按控件自然宽度排列，空间不足时换行，不自动拉伸填满；控件项把标签和控件作为一个整体换行 | `filter-bar`、`toolbar` 等系统组件种类的真实渲染基础 | 横向条件、参数及操作组统一消费；整体换行与复合控件边界见[按钮与输入](#按钮与输入)。 |
| `AppTabToolbar` | `frontend/src/components/AppTabToolbar.vue` | Tab 内容区的统一操作栏，按内容安排筛选、命令和说明，并在空间不足时自然换行 | `tabs` 下属 `filter-bar` / `toolbar` 的真实组合外壳，内部复用 `AppControlRow` | Tab 标签已表达面板名称时，内容区不得重复标题；操作和筛选统一放 `#actions`，说明统一放 `#description`；筛选型默认从左起排，纯命令组可用 `actionsAlign=end` 在当前区域右对齐，此时反馈独立放下一行；没有操作时允许仅右对齐展示说明，不得为填空新增无业务意义的按钮 |
| `LayoutConfigTransferPanel` | `frontend/src/layout/components/LayoutConfigTransferPanel.vue` | 布局配置与视觉预设共用的 JSON 导入导出分区 | 无直接系统组件种类或配置字段 | 统一标题与帮助、工具行、伸展编辑区和底部右对齐操作；文件选择使用标准命令按钮，解析及保存仍由工作区负责。两处消费共用几何与间距，不改变各自校验、权限或持久化范围。 |
| `AppIconButton` | `frontend/src/components/AppIconButton.vue` | 全站纯图标操作按钮，统一可访问名称、尺寸、圆角、悬浮、聚焦、禁用、loading 和语义色 | 无直接系统组件种类 | 纯图标命令复用；尺寸、名称、加载与提示边界见[按钮与输入](#按钮与输入) |
| `AppCloseButton` | `frontend/src/components/AppCloseButton.vue` | 关闭与移除临时界面的语义入口 | 无直接系统组件种类；复用 `AppIconButton` | 工作标签、抽屉头部、对比队列及临时预览共同消费；档位、颜色、状态与事件边界统一遵循本节关闭契约，业务允许判断留在容器，库内置关闭由全局样式适配 |
| `AppHoverInfo` | `frontend/src/components/AppHoverInfo.ts`、`frontend/src/composables/useHoverIntent.ts`、`frontend/src/composables/useTooltipInputModality.ts` | 显式说明的共享 tooltip / popover 与悬停意图判定 | 无直接系统组件种类 | HelpHint、HelpTip、命令及状态说明共用；锚点、触发时序、禁用和清理规则见[提示、截断与可访问名称](#提示截断与可访问名称)。 |
| `AppActionHint` | `frontend/src/components/AppActionHint.vue` | 命令补充说明与禁用原因的可聚焦外壳 | 无直接系统组件种类；复用 AppHoverInfo | 行操作与独立业务命令共同消费；不持有业务执行逻辑，权限指令作用于其真实 span 根节点，使用边界见本节提示契约 |
| `HelpTip` / `HelpTipItem` / `HelpHint` | `frontend/src/components/HelpTip.vue`、`frontend/src/components/HelpTipItem.vue`、`frontend/src/components/HelpHint.vue` | 全站帮助入口与结构化说明项 | 无直接系统组件种类 | 选型、内容结构与交互统一见[提示、截断与可访问名称](#提示截断与可访问名称)。 |
| `DataMetricCard` / `DataMetricDetails` | `frontend/src/components/data/DataMetricCard.vue`、`frontend/src/components/data/DataMetricDetails.vue` | 数据管理域的统计卡及只读统计详情 | 业务域内复用，不新增系统组件种类或配置字段 | 卡片数值左对齐，复用 HelpHint 与明细入口；明细复用 AppHoverInfo、AppDetailFields 和 AppScrollArea，视口高度约束见[响应式组件登记](agent-works/configurable-layout-system/responsive-components.md)。遵循[统计摘要与下钻](#统计摘要与下钻)及全站提示契约。消费范围与业务映射见[数据概览说明](agent-works/architecture/data-management.md#统计内容与操作映射)。 |
| `RelatedBoardCell` / `RelatedBoardEmptyValue` / `RelatedBoardHistoryHint` | `frontend/src/components/RelatedBoardCell.vue`、`frontend/src/components/RelatedBoardEmptyValue.vue`、`frontend/src/components/RelatedBoardHistoryHint.vue` | 个股行业走势/概念走势冠军及可解释空值的业务域复用单元，统一名称、结构化相关性说明、低可信提示、首次计算、空结果原因、历史日期保护和权限感知导航 | 无直接系统组件种类；作为既有 `data-table` / `wide-table` 业务列内容及天梯卡片紧凑值 | 股票、榜单、筛选表格和天梯共用；调用方提供完整摘要与类型，显示、历史回退和权限见[关联板块架构](agent-works/architecture/stock-board-correlation.md#页面api-与权限)。 |
| `BuiltinOptionRow` | `frontend/src/components/BuiltinOptionRow.vue` | 下拉项和选中值的统一主辅行结构，统一名称截断、来源提示与尾部标签/动作对齐 | 无直接系统组件种类 | 交易纪律的内置/自定义原因及打卡买卖规则选择统一复用；内置项只显示中性“内置”提示，自定义项的删除等动作或小号中性类型标签通过默认插槽注入；尾部标签最多占半行并省略，名称使用剩余空间，不在消费页复制选项行布局 |
| `AppSummaryDisclosureCard` | `frontend/src/components/AppSummaryDisclosureCard.vue` | 编辑卡与只读检查清单的共享折叠摘要外壳，统一标题、元信息、工具区、展开边界与键盘可访问 disclosure | 无直接系统组件种类 | 可展开编辑与只读检查清单共用；变体、摘要和可访问性见[卡片、面板与分区](#卡片面板与分区)。 |
| `AppJsonViewer` | `frontend/src/components/AppJsonViewer.vue` | 具名技术详情中的只读原始数据查看器 | 不新增系统组件种类或配置字段 | 复用 Element Plus Tree 按需展开字段及数组，根字段默认可见；原值不经过业务摘要转换，旧文本保留原文，滚动委托 AppScrollArea 与共享文档高度。入口与业务摘要的边界遵循[业务内容与技术详情](#业务内容与技术详情)。 |
| `ProfileVersionContent` | `frontend/src/components/indicator/ProfileVersionContent.vue` | 评分与买卖方案历史版本的只读业务内容 | 业务域内复用，不新增系统组件种类或配置字段 | 历史参数按保存值展示；复用 AppDataTable、AppDetailFields 和 AppSummaryDisclosureCard，原始配置由默认收起的具名入口及 AppJsonViewer 承接，不承担载入或恢复操作。 |
| `TradeDirectionGroupGrid` | `frontend/src/components/trade-discipline/TradeDirectionGroupGrid.vue` | 交易纪律中按买入、卖出方向上下组织单列清单，统一分组标题、说明和动作区 | 无直接系统组件种类；仅承载交易纪律方向分组 | 买卖规则与操作事实统一消费；分组即方向事实源，组内卡片不得再展示重复方向选择器；规则或成交的领域状态留在调用方，通过分组动作和内容插槽注入；所有宽度保持买入在上、卖出在下，每条规则或操作独占一行，不在消费组件复制方向分组结构与样式 |
| `RuleSummaryCard` | `frontend/src/components/trade-discipline/RuleSummaryCard.vue` | 买入、卖出和选股规则的紧凑摘要卡，基于 `AppSummaryDisclosureCard` 组合规则启停与动作区 | 无直接系统组件种类；仅承载交易纪律规则编辑 | 同类规则统一复用；默认只展示摘要并一次展开一项，动作通过插槽注入；不得把规则启停语义下沉到通用卡片外壳 |
| `TradeDisciplineSectionPanel` | `frontend/src/components/trade-discipline/TradeDisciplineSectionPanel.vue` | 交易纪律编辑器的统一分区面板，承载标题、说明、摘要、展开编辑区和分区动作 | 无直接系统组件种类；仅承载交易纪律编辑分区 | 规则、操作事实和履约编辑的同层分区统一复用；领域字段与动作通过插槽注入，不在消费页复制分区外壳、标题层级和间距 |
| `StockRuleChecklistEditor` | `frontend/src/components/trade-discipline/StockRuleChecklistEditor.vue` | 分类检查项编辑与组内排序 | 消费 `config-panel` 的默认折叠配置 | 交易纪律规则编辑；消费 stockConditions 配置面板的 defaultCollapsed；字典分类和补充说明复用 ConfigPanelSection，代码默认独立收起，标题摘要保留，新建/校验错误展开定位；分类及排序逻辑复用条件工具和 AppReorderList，基本/风险字段经插槽消费；增删改由规则草稿统一保存；分类候选来自系统字典，未知或停用分类按既有条件保留，默认折叠候选同步字典编码 |
| `StockRuleConditionChecklist` | `frontend/src/components/trade-discipline/StockRuleConditionChecklist.vue` | 交易纪律分类条件、逐项核对与补充说明 | 消费 `config-panel` 的默认折叠配置 | 今日买入和历史规则/操作快照统一消费；消费同一 stockConditions.defaultCollapsed；字典分类与补充说明复用 ConfigPanelSection，代码默认收起、标题保留摘要/核对数量，开合不卸载字段，状态按操作隔离；结果通过 props/events 传递，未知与未记录分别展示，分类名读取版本快照，服务端负责版本归属与履约守卫；宽度不足自然换行，保留条件、结果与展开入口 |
| `AppRowActions` | `frontend/src/components/AppRowActions.vue` | 表格行操作列和列表项操作区的统一动作组，按权限过滤、单行排列、动作颜色层级、禁用/加载态展示、轻量“更多”菜单收纳和**宽度自适应折叠** | 无直接系统组件种类 | 行内动作组复用；动作层级、更多菜单及宽度折叠见[行操作组](#行操作组) |
| `SystemBuiltinTag` | `frontend/src/components/SystemBuiltinTag.vue` | 全站“系统内置”来源标记，固定使用灰色文字、灰色描边和中性浅底 | 无直接系统组件种类 | 菜单、功能点、角色、租户、视觉预设、技术指标和系统内置方案等来源标记统一复用；文案固定为“系统内置”，不追加对象名称或保护规则说明；与对象名称或标识并列时统一放在对象后面，独立的来源/类型字段保持标签单独展示 |
| `IndicatorSelect` / `IndicatorParamFields` | `frontend/src/components/indicator/IndicatorSelect.vue`、`frontend/src/components/indicator/IndicatorParamFields.vue` | 技术指标选择与计算参数值的领域复用组件，统一通用指标/快捷预设分组、停用历史项回显、参数单位与范围 | 无直接系统组件种类；作为方案编辑器内部字段 | 筛选、评分、买入和卖出方案统一消费；新选择只展示启用项，当前已选停用项保留“历史兼容”回显；参数值只表达计算口径，比较符、阈值、评分方式和权重仍由下游方案维护，页面不得复制参数循环和单位展示 |
| `StrategyItemEnabledSwitch` | `frontend/src/components/strategy/StrategyItemEnabledSwitch.vue` | 策略项启停开关，统一双向绑定、只读态和可访问名称 | 无直接系统组件种类；作为方案编辑器内部字段 | 筛选条件、评分因子及买卖条件统一复用；调用方传入领域化 `label`，不得在页面继续复制只透传启停值的裸开关包装 |
| `IndicatorParamSchemaEditor` | `frontend/src/components/indicator/IndicatorParamSchemaEditor.vue` | 自定义指标参数 schema 编辑器，统一参数名、标签、类型、默认值、上下限、单位和说明 | 无直接系统组件种类；作为指标定义抽屉内部字段 | 只用于平台指标定义维护，不与方案参数值编辑器合并；定义被引用时整体只读，后端仍负责最终占位符和范围校验 |
| `AppScrollArea` | `frontend/src/components/AppScrollArea.vue` | 自建滚动区域唯一入口，封装 Element Plus 并承接内容布局 | 内部实现组件，不单独登记系统组件种类或假 slot | 正文、侧栏、抽屉、导航、页签和局部列表统一消费；保留原有滚动归属、成长约束及布局，内部 viewport 和内容层由组件统一承载；表格与库控件内部滚动条由全站适配层接管，不再包第二层 |
| `AppDataTable` | `frontend/src/components/AppDataTable.vue` | 数据表格/宽表运行时外壳，统一表头排序布局、表体内滚、分页承载、加载分流、空态插槽、行点击样式和成长/嵌入模式 | 对应 `data-table`、`wide-table` 种类；读取页面传入的排序、分页、列显隐等消费结果 | 主表与局部明细统一复用；成长、嵌入、列宽和滚动见[表格与列表](#表格与列表)，加载/空态见[四态反馈总则](#四态反馈总则)。 |
| `AppTableCard` | `frontend/src/components/AppTableCard.vue` | 独立列表的统一结果外壳，复用 Element Plus 卡片及主题边框、圆角；承接标题、四态和分页 | 无独立系统组件种类或配置字段 | ConfigView、QualityView、ScheduleView、TrainingView、AuditLogView、UserManageView、TenantManageView、LayoutPresetsView、TradeDisciplineHistory；已有工作区面板的表格不重复套卡 |
| `AppAsyncRegion` | `frontend/src/components/AppAsyncRegion.vue` | 非表格异步内容区域外壳，统一首次加载、已有内容刷新、空态和异常态的互斥切换 | 消费 `AppStateBlock` 和 Element Plus `v-loading`，通过调用方提供的 `loading + hasContent + error` 推导区域状态；不负责请求、业务缓存或内容归属判断 | 标准非表格异步区统一复用；只消费调用方状态，不持有请求或缓存，接入边界见[四态反馈总则](#四态反馈总则)。 |
| `AppTableColumn` | `frontend/src/components/AppTableColumn.vue`、`frontend/src/components/table/adaptiveColumnWidth.ts` | 表格列运行时组件，根据结构类型、字段名和标签推导语义角色，以稳定字符权重结合排序/筛选控件计算弹性最小宽，并统一推导表头/单元格对齐、数字排版、单行表头及同行元信息 | `data-table`、`wide-table` 的稳定列宽、语义对齐和表头能力；不是用户可配置字段 | 数据表格列统一消费；语义角色、宽度、对齐和控件容量见[表格与列表](#表格与列表)，禁止页面覆盖列呈现。 |
| `AppOverflowTooltipHost` | `frontend/src/components/AppOverflowTooltipHost.vue`、`frontend/src/components/overflow/overflowTooltip.ts` | 全站真实截断原文提示宿主 | 无直接系统组件种类 | 唯一全局挂载于 App；只识别真实截断，不接管原生 title；触发、原文来源与边界见本节提示契约 |
| `AppStateBlock` | `frontend/src/components/AppStateBlock.vue` | 页面和组件的加载、空、异常、无权反馈块，统一 `ready / loading / empty / error` 四态中的非 ready 呈现、重试入口和尺寸档位 | 对应布局系统中的 `loading-state`、`empty-state`、`error-state`、`skeleton` 语义，但作为真实运行时复用组件消费 | 加载、空、异常与无权反馈统一消费；标准异步区由 AppAsyncRegion 编排，状态及尺寸规则见[四态反馈总则](#四态反馈总则)。 |
| `AppWorkspacePane` | `frontend/src/components/AppWorkspacePane.vue` | 主从工作区单栏的统一栏级外壳，承载标题、可选辅助行、操作区和自适应内容区 | `master-detail` 左右栏的内部面板 | 行情列表、分析及详情两栏共用；栏头与内容承接见[共享工作区与尺寸档案](#55-共享工作区与尺寸档案)。 |
| `AppStatusNotice` | `frontend/src/components/AppStatusNotice.vue` | ready 内容仍可继续使用时的轻量持久提示，统一信息、成功、警告、失败语义、紧凑尺寸和可选动作 | 不属于第五种顶层状态；作为 ready 的辅助消息层 | 可安全保留内容时的局部降级提示；使用边界见[四态反馈总则](#四态反馈总则)与[消息反馈层级](#消息反馈层级)。 |
| `StockChartPanelHeader` / `StockChartLegend` / `StockChartPanelDivider` | `frontend/src/components/stock-chart/StockChartPanelHeader.vue`、`frontend/src/components/stock-chart/StockChartLegend.vue`、`frontend/src/components/stock-chart/StockChartPanelDivider.vue` | 股票图表面板的共享标题栏、图例项与独立分隔区，统一 32px 高度、标题层级、水平对齐、序列形态标识、图例文字层级以及双边框分隔 | 股票画布内部结构，不直接映射布局系统组件种类 | 日 K 与分时面板共用；标题、图例与独立分隔区规则见[Color Palette & Roles](#2-color-palette--roles)，页面不另画同类结构。 |
| `StockChartOperationsDrawer` / `ChartOperationGroup` | `frontend/src/components/stock-chart/StockChartOperationsDrawer.vue`、`frontend/src/components/ChartOperationGroup.vue` | 图表工作区内部的局部操作抽屉与带名称边界的紧凑操作组，统一局部遮罩、关闭与焦点归还、分组边界、间距和组内控件高度 | 图表内部结构，不直接映射布局系统组件种类 | 使用与短选项内容匹配的受控紧凑宽度，边界只覆盖所属 `StockChartWorkspace`，不得进入页面级覆盖层或遮挡相邻区域；局部枚举保持中性色，主色只用于主视图切换；容器不持有图表领域状态或计算，每类操作独立成组，消费页不得复制同类抽屉、边框、标题和紧凑尺寸 |
| `StockChartWorkspace` | `frontend/src/components/stock-chart/StockChartWorkspace.vue` | 行情 K线、量能和可选 MACD 的纵向联动工作区，统一日期轴、光标、显式缩放同步、局部状态、买卖标记和可访问高度分隔线 | `chart.minHeight`（仅由固定高度详情实例消费） | 股票、板块、训练和回测画布共用；交互边界见[股票图表工作区](#股票图表工作区)，主题见 §2，尺寸见[共享工作区与尺寸档案](#55-共享工作区与尺寸档案)。 |
| `StockIntradayDialog` / `StockIntradayChart` | `frontend/src/components/stock-chart/StockIntradayDialog.vue`、`frontend/src/components/stock-chart/StockIntradayChart.vue` | 日 K 蜡烛下钻的共享分时弹窗与双绘图区，统一按需请求、取消/迟到响应、范围/空/错误/部分状态、行情摘要、价格/均价/昨收和分钟量能联动 | 无直接系统组件种类；作为股票画布的按需覆盖层 | 个股详情及 StockAnalysisPanel 的日 K 下钻共用；业务范围、状态与请求生命周期见[分时架构](agent-works/architecture/stock-intraday.md)，画布规范见 §2。 |
| `StockChartRegion` | `frontend/src/components/stock-chart/StockChartRegion.vue` | 固定高度股票图表的外层区域，统一接收组件实例总高度、测量可选标题区并把剩余可用高度传给工作区 | `chart.minHeight` + `chart.stockChart` 的当前组合 | 盘感训练等声明固定图表高度的页面统一消费；页面只传外层总高度及当前图表组合，禁止再手工减标题高度或把总高度直接当工作区高度；容器根据真实标题高度和边框自动计算内容高度，可见面板硬下限不足时扩展外层而不得裁切；个股与板块详情等主从工作台随剩余空间成长，不使用本容器 |
| `MarketDetailHero` | `frontend/src/components/MarketDetailHero.vue` | 行情详情页的对象身份、摘要、元信息与上下文操作头部 | 无直接系统组件种类；承载详情页头部内容 | 板块详情与个股详情共同消费；不渲染英文装饰 eyebrow，状态标签、操作、行情摘要、元信息和上下文条分别进入具名插槽；页面不得复制 hero 外壳、背景、间距或响应式规则；默认保持两端布局，摘要需要紧随身份区时显式使用 `asideAlign="start"` |
| `MarketBoardTag` | `frontend/src/components/MarketBoardTag.vue` | 行业与概念名称、同日涨跌和走势相关性的统一领域标签 | 无直接系统组件种类；内部消费 Element Plus 默认尺寸 `el-tag` | 个股详情所属板块面板中的相关行业与概念共同消费；使用默认 24px 控件档，宽度随内容且允许外层换行，不使用等宽网格或固定宽度；名称保持中性文字，仅涨跌幅数值消费金融涨跌色，相关状态统一控制高亮边框，并允许在上下文已明确时隐藏“最相关”文字；统一内容省略、键盘焦点和可选板块详情地址 |
| `StockBoardMembershipPanel` | `frontend/src/components/StockBoardMembershipPanel.vue` | 个股所属板块行情标签，统一同日涨跌、走势冠军标记和权限感知导航 | `section` | 个股详情统一消费；板块标签、同日涨跌与权限见[个股详情架构](agent-works/architecture/stocks-and-groups.md#2-个股详情页)。 |
| `AppSplitWorkspace` | `frontend/src/components/AppSplitWorkspace.vue` | 通用左右分栏工作区，统一比例计算、尺寸档案、可访问分隔条、单栏回退和窄屏全屏抽屉 | 作为 `master-detail` 的内部真实组件，消费 `masterRatio`、`masterRatioProfiles` | MarketMasterDetailWorkspace、个股及板块详情共用；比例、滚动和窄屏规则见[共享工作区与尺寸档案](#55-共享工作区与尺寸档案)。 |
| `MarketMasterDetailWorkspace` | `frontend/src/components/MarketMasterDetailWorkspace.vue` | 行情列表与走势分析区的双栏业务外壳；基于 `AppSplitWorkspace` 补充分栏与分析区收展，列表栏外壳委托 `AppWorkspacePane`，保留既有公开属性、事件与紧凑抽屉控制接口 | `master-detail.masterRatio`、`master-detail.masterRatioProfiles` | 个股、榜单、天梯和板块行情共用；高度模式、比例档案与窄屏承接见[共享工作区与尺寸档案](#55-共享工作区与尺寸档案)，业务选择状态由领域组件持有。 |
| `RankedStockResultTable` | `frontend/src/components/ranked-stock/RankedStockResultTable.vue` | 评分结果领域表格，统一全市场排名、股票名称、板块、综合分、评级、分项分、相关板块与不可评分状态 | 消费既有 `wide-table`，不新增系统组件 kind | 每日榜单、策略筛选、评分试算和回测当日榜单共同消费；页面差异只通过列 schema 与具名插槽表达。`rank` 永远是全市场排名，未参与评分时为空；ST 不单独占列，统一在名称后显示显式 `ST` 标签，名称不可见时跟随代码；评级和分项分不得再由页面维护平行实现 |
| `RankedStockWorkbench` | `frontend/src/components/ranked-stock/RankedStockWorkbench.vue` | 评分结果表格与股票走势分析的统一主从工作台，内建当前观察、对比队列、窄屏分析抽屉和详情次级入口 | 组合既有 `master-detail`、`wide-table` 与 `chart` | 策略筛选和评分试算直接消费；每日榜单因批量自选与可配置图表继续用同一底层表格、`MarketMasterDetailWorkspace` 和选择状态组合；回测弹窗只消费表格，不嵌入完整工作台 |
| `MarketAnalysisHeader` | `frontend/src/components/MarketAnalysisHeader.vue` | 行情分析右栏的当前对象、代码、详情入口、摘要和控制区统一头部 | `master-detail` 分析子区的内部真实组件 | `StockAnalysisPanel` 与板块行情共同消费；响应式必须按分析栏自身容器宽度判断，窄栏时身份与控制区上下排列、控制区自然换行并隐藏辅助摘要和控件标签，不得按整页宽度猜测右栏空间或在页面复制标题、代码、详情链接和断点样式 |
| `MarketCompareMetricStrip` | `frontend/src/components/MarketCompareMetricStrip.vue` | 行情走势对比的指标摘要与切换条；单项固定为指标名称在上、指标值在下并左对齐，统一激活态、涨跌语义色、键盘按钮语义和紧凑视口降级 | 无直接系统组件种类；由行情分析区承载 | 板块行情、个股查询、每日榜单共同消费；消费页只提供指标元数据和值，不复制指标条结构或样式；个股页面只接累计及 5/10/20/30/60 日涨跌，不接板块资金流、成员涨跌或领涨股口径 |
| `CompareQueueRail` | `frontend/src/components/CompareQueueRail.vue` | 走势对比的对比对象队列条，统一队列标签、chip（名称/激活/错误/移除）与“最多 N 个”上限提示 | 无直接系统组件种类；由行情分析区承载 | 股票、榜单和板块对比队列共用；队列交互与状态边界见[股票图表工作区](#股票图表工作区)。 |
| `MarketBenchmarkSelect` | `frontend/src/components/MarketBenchmarkSelect.vue` | 基于 `AppSelect` 的市场基准指数单选，统一短枚举容量、空值回显和 `MARKET_BENCHMARK_OPTIONS` 选项源 | 无直接系统组件种类；由走势分析面板和默认字段组承载 | 股票/板块走势面板与 `StockAnalysisDefaultFields`、`SectorAnalysisDefaultFields` 共同消费；输入宽度由组件持有，浮层继承 `AppSelect` 默认策略，消费页不得覆盖宽度；禁止再用面向列表多选筛选的 `AppFilterSelect` 代替或在消费页复制指数选项 |
| `StockAnalysisDefaultFields` | `frontend/src/components/StockAnalysisDefaultFields.vue` | 个股走势分析的默认模式、周期、指数、指标和分析区显隐设置字段组 | `chart.stockAnalysis` 的专用编辑器，嵌入统一组件设置渲染器 | 个股查询、每日榜单、连板天梯共同消费；指标列表不可为空，移除当前默认指标时统一回退到首个可见指标；持久化按 `pageKey + slotId` 隔离，禁止消费页再通过业务插槽维护平行字段 |
| `SectorAnalysisDefaultFields` | `frontend/src/components/SectorAnalysisDefaultFields.vue` | 板块走势分析的默认模式、指数、指标、周期和分析区显隐设置字段组 | `chart.sectorAnalysis` 的专用编辑器，嵌入统一组件设置渲染器 | 板块行情工作台消费；板块指标模型与股票收益指标模型分离，禁止复用 `stockAnalysis` 强行混装；指标列表不可为空，持久化按 `pageKey + slotId` 隔离 |
| `StockAnalysisPanel` | `frontend/src/components/StockAnalysisPanel.vue` | 股票走势对比与 K 线的统一分析面板，负责当前观察、对比队列、指标、基准指数、周期、局部加载降级和模式切换 | `chart.stockAnalysis`（作为 master-detail 的分析子区） | 个股、榜单和天梯共用；配置归属见[组件特性配置治理](#73-组件特性配置治理)，数据范围、口径及异常恢复见[行情分析架构](agent-works/architecture/stocks-and-groups.md#查询页共享行情分析工作台)。 |
| `StockAnalysisNameCell` | `frontend/src/components/StockAnalysisNameCell.vue` | 股票列表名称单元格中的前置操作、走势对比入口、名称与状态组合 | 无直接系统组件种类 | 个股查询普通列表、分组列表和每日榜单共同消费；默认统一走势对比图标、可访问名称和激活反馈，自选星标等同层前置操作通过 `leading` 插槽注入；名称按钮发出 `select`，与宿主整行点击共用业务入口；只管理单元格布局与事件，不持有对比队列或分组状态 |
| `StockStatusTag` | `frontend/src/components/StockStatusTag.vue` | 股票点时 ST 状态的统一显式标签、日期说明、未知态和上下文去重 | 无直接系统组件种类 | 研究、选择、交易和复盘场景共同消费；仅 `is_st=true` 默认显示危险语义 `ST`，非 ST 不显示，辅助入口可显式开启未知态；标签跟随名称、无名称时跟随代码，不新增独立列、不允许页面仅靠名称变色或从名称推断 ST；上层已明确限定为纯 ST 集合时通过统一上下文属性隐藏重复标签，离开该上下文后恢复 |
| `StockGroupFavoriteButton` | `frontend/src/components/StockGroupFavoriteButton.vue` | 股票加入/移出默认“自选”分组的星标入口，统一异步状态、可访问名称、成功反馈和激活色 | 无直接系统组件种类 | 个股查询普通列表与每日榜单共同消费，位于名称单元格的走势对比入口之前；空心表示未加入、实心主色表示已加入，点击不得触发行选择；只操作当前用户默认分组，其它自定义分组继续使用 `StockGroupBatchActions`，页面只负责提供默认分组、当前成员态和业务日期 |
| `StockGroupBatchActions` | `frontend/src/components/StockGroupBatchActions.vue` | 批量观察、创建分组、加入分组与移出分组 | 无独立系统组件种类；由列表工具区消费 | 个股查询与每日榜单共享批量操作，消费页控制权限与选中集合，组件统一弹窗校验、请求和成功后清空选择；不得在页面复制分组操作流程 |
| `StockCompareChart` | `frontend/src/components/StockCompareChart.vue` | 多股票与市场指数的相对走势折线图 | 无直接系统组件种类；由 `StockAnalysisPanel` 承载 | 股票相对走势消费方共用，与 SectorCompareChart 共用折线骨架；基期、日历及缺失值见[行情分析架构](agent-works/architecture/stocks-and-groups.md#查询页共享行情分析工作台)。 |
| `SectorCompareChart` | `frontend/src/components/SectorCompareChart.vue` | 多板块连续指数的涨跌幅对比折线、市场指数超额和资金流/成员涨跌截面柱图 | 无直接系统组件种类；由板块行情分析区承载 | 板块相对走势统一消费，共用股票对比算法及折线骨架；缺失值与偏好隔离见[股票图表工作区](#股票图表工作区)。 |
| `AppPagination` | `frontend/src/components/AppPagination.vue` | 列表页统一分页；按自身容器宽度从“总数 + 每页条数 + 页码导航”依次降级为“总数 + 页码导航”和紧凑页码导航，禁止完整分页器反向溢出窄分栏 | 由 `data-table`/`wide-table` 的 `pageSize` 配置间接驱动 | 分页页脚统一复用；页面不得直接使用 `el-pagination` 或复制宽度降级逻辑 |
| `AppSelect` | `frontend/src/components/AppSelect.vue` | 普通下拉唯一底层入口，统一语义宽度、浮层定位、内容扩展与长选项换行 | 无直接系统组件种类 | 普通下拉统一消费；容量、定位与等宽例外见[按钮与输入](#按钮与输入)，禁止页面直接使用 el-select。 |
| `AppFilterSelect` | `frontend/src/components/AppFilterSelect.vue` | 基于 `AppSelect` 的容量自适应选择器，统一列表筛选与紧凑多选编辑 | 无直接系统组件种类 | 列表筛选与紧凑多选编辑统一消费；标签/数量模式、全选文案、容量和输入属性见[按钮与输入](#按钮与输入)。 |
| `AppDragHandle` | `frontend/src/components/AppDragHandle.vue` | 列表与树共用的六点排序把手 | 无直接系统组件种类 | 基于 AppIconButton 统一尺寸、说明、焦点、禁用与拿起状态；与相邻内容保留 8px 间距，排序按键与指针事件交给共享会话处理 |
| `AppReorderTree` | `frontend/src/components/AppReorderTree.vue` | 层级树的把手拖动、同级键盘排序与合法落点反馈 | 无直接系统组件种类；树内部交互 | 菜单管理消费；和 AppReorderList 共用 AppDragHandle 与 useReorderInteraction，树导航委托 ElTree，业务调用方提供容器资格、权限、保存及失败恢复；保留选中、展开和保存后的焦点 |
| `AppReorderList` | `frontend/src/components/AppReorderList.vue` | 用户自定义顺序列表的共享拖动排序，统一六点 SVG 把手、落点、取消、滚动和键盘操作 | 无直接系统组件种类；列表内部交互 | 交易纪律选股、买入和卖出规则共用；稳定 key 不依赖下标；拖动松手或键盘确认才提交 reorder，保存归调用方；禁用及单项不显示把手；与树共用 AppDragHandle 和 useReorderInteraction，紧凑行通过 --app-reorder-handle-offset 调整把手对齐，不在页面复制排序输入或上移/下移按钮 |
| `AppSortControl` | `frontend/src/components/AppSortControl.vue` | 统一“排序字段菜单 + 升降序切换”的紧凑排序交互 | 无直接系统组件种类 | 页面只提供稳定选项、当前字段和方向，不得复制下拉菜单、选中勾选和方向按钮；位于筛选或操作栏时固定作为最后一个控件，空间不足按 DOM 顺序整体换行 |
| `AppSearchInput` | `frontend/src/components/AppSearchInput.vue` | 列表页关键字搜索输入，统一"输入即防抖查 + 回车/清空立即查" | 无直接系统组件种类 | 关键字输入统一消费；防抖编排复用 useDebouncedQuery，查询、归页及刷新见[查询、重置与刷新](#查询重置与刷新)。 |
| `AppDatePicker` / `TradeDatePicker` | `frontend/src/components/AppDatePicker.vue`、`frontend/src/components/TradeDatePicker.vue` | 通用日期浮层入口与交易日选择器 | 无直接系统组件种类 | 通用日期输入使用 AppDatePicker，交易日输入使用 TradeDatePicker；浮层与默认最新日期规则见[按钮与输入](#按钮与输入)。 |
| `KlineRangeSelect` / `KlineSettingSection` | `frontend/src/components/KlineRangeSelect.vue`、`frontend/src/components/KlineSettingSection.vue` | K线范围快捷选择与共享设置字段 | `chart.klineRangePreferences` 的专用全局偏好编辑器 | 个股详情、盘感训练等 K线页面统一复用；设置字段只由 `ComponentAutoSettings` 在组件设置中渲染，页面不得复制范围选项、偏好写入逻辑或业务入口 |
| `StockChartSettingSection` | `frontend/src/components/StockChartSettingSection.vue` | `ComponentAutoSettings` 内股票多图实例的专用字段编辑器，负责图表二/图表三选择、高度比例编辑和页面当前比例采用入口 | `chart.stockChart` | 股票多图实例统一由 ComponentAutoSettings 间接消费；尺寸及会话/默认值关系见[共享工作区与尺寸档案](#55-共享工作区与尺寸档案)。 |
| `EquityChart` / `GrowthChart` | `frontend/src/components/EquityChart.vue`、`frontend/src/components/GrowthChart.vue` | 回测/训练净值与成长曲线 | 无直接系统组件种类 | 回测与训练各自消费；主题见 §2，基准显隐、读数和颜色见[净值与成长图](#净值与成长图)。 |
| `BrandMark` | `frontend/src/components/BrandMark.vue` | 应用品牌图形与「复盘啦」字标 | 无直接系统组件种类 | 应用外壳、登录页等品牌露出直接复用同一外观；禁止场景变体、消费侧 `--brand-*` 覆盖、私有 logo 或第二套字标；窄容器只允许等比缩放 |
| `SideMenu` / `TopNavigation` / `WorkspaceTabs` / `WorkspaceRouteView` / `MenuIcon` | `frontend/src/components/SideMenu.vue`、`frontend/src/components/TopNavigation.vue`、`frontend/src/components/WorkspaceTabs.vue`、`frontend/src/components/WorkspaceRouteView.vue`、`frontend/src/components/MenuIcon.vue` | 应用级菜单树、双层顶栏、保留现场的工作标签页、路由缓存与统一菜单图标渲染 | 无直接系统组件种类 | 应用外壳共用菜单、页签与路由缓存；权限树、焦点和导航布局见[应用外壳](#应用外壳)，业务页不得另建缓存。 |
| `AssetVisibilityTag` / `AssetProfileLabel` / `AssetVisibilityActions` | `frontend/src/components/AssetVisibilityTag.vue`、`frontend/src/components/AssetProfileLabel.vue`、`frontend/src/components/AssetVisibilityActions.vue` | 公开资产来源、可见范围、只读状态、方案名称+版本+归属标签、发布/收回、复制为我的方案和复用参数动作 | 无直接系统组件种类 | 评分、筛选、买卖、回测等公开资产页面必须复用；方案选择/列表入口统一用 `AssetProfileLabel`，消费页包括 `BoardView`、`ScreenView`、`StockDetailView`、`ConfigView` 评分 tab、`ConfigView` 买卖 tab、`BacktestView` |
| `ScoreGradeTag` | `frontend/src/components/ScoreGradeTag.vue` | 统一综合评分评级标签：主升浪核心=`danger`、龙头候选=`warning`、观察=`success`、未知评级=`info` | 无直接系统组件种类 | 每日榜单、策略筛选、评分试算、回测交易及回测当日榜单统一复用；默认使用表格小号标签和统一垂直居中几何；训练模块的 S/A/B/C/D 属于另一套评级，不套用本组件 |
| `SubScoreChips` | `frontend/src/components/SubScoreChips.vue` | 分项达标分的业务域复用单元格，统一评分等级、胶囊样式、末尾截断与完整内容提示 | 无直接系统组件种类；作为既有 `data-table` 业务列内容 | 每日榜单与评分试算共同消费；保留评分胶囊原有的紧凑自适应高度与间距，不为统一提示机制改变业务组件外观；超长内容在胶囊末尾使用原生省略号，不得叠加单元格公共省略遮罩或留下被截断的分数字符；省略原文提示由全局省略宿主自动承接 |
| `AssetSearchDrawer` / `AssetProfileSelect` | `frontend/src/components/asset-search/AssetSearchDrawer.vue`、`frontend/src/components/asset-search/AssetProfileSelect.vue` | 统一跨来源资产搜索抽屉与“我的资产”选择器，支持 `select` / `list` 形态、服务端搜索分页、加载查看、复制或复用 | 无直接系统组件种类 | 公开资产页面统一消费；浏览、选择、只读预览与失败恢复见[弹窗与抽屉](#弹窗与抽屉)。 |
| `ConfigGroupForm` | `frontend/src/components/config/ConfigGroupForm.vue` | 系统设置配置组表单 | 消费 `config-panel` 的折叠与说明展示配置 | 动态配置组字段渲染优先复用 |

### 股票图表工作区

- `SectorCompareChart`：折线与股票对比复用 `marketCompare` 的 N+1、统一交易日、停牌补齐和对比基期算法，并共同消费 `marketCompareChart.ts` 的折线 option 骨架；板块资金流和成员涨跌柱图保留领域私有配置，不并入通用折线组件；资金流、当日涨跌和成员涨跌缺失值保持空值，不得代填 0；页面偏好只消费 `sectors` 页面键，禁止与 `stocks` / `board` 串用默认指标或基准配置。

- `CompareQueueRail`：板块行情、个股查询、每日榜单共同消费，禁止页面内再写第二套队列 chip；chip 为 `role=button` 容器承载激活（点击 + Enter/Space，`.self` 避免焦点在移除钮时连击激活），名称为纯 `span` 继承 chip 颜色（激活/悬浮随主色变化），移除用 `AppCloseButton size="inline"`；遵守按钮契约——不引入原生 `<button>`，也不用 `el-button` 包裹名称（其特异性会覆盖继承色）；消费页只提供归一化 `{ key, label, active, error }` 列表与 `activate`/`remove` 事件，上限提示文案按对象（板块/股票）传入；队列顺序稳定（进入先后），激活/切换主观察只移动高亮不重排，该状态机由共享纯函数 `frontend/src/utils/compareQueue.ts` 维护，`useStockAnalysisSelection`（个股/榜单）与板块行情视图都委托给它，禁止再各自实现“激活项置顶”的派生队列。

- 股票、板块、训练与回测的多图工作区统一消费 `StockChartWorkspace`；主题、序列身份色、浮层和分时几何遵循 §2，面板尺寸与档案遵循 §5.5。行情口径通过 `adjustLabel` 标注，MACD 口径不同时独立传 `macdAdjustLabel`，未传时才沿用行情口径。
- 行情与指标按交易日、截止日对齐；MACD 局部失败不阻断 K 线和量能。三图共用 64px 左右轴边界，轴值统一格式化：K 线左轴价格、右轴相对当前查询区间首根前收的涨跌幅，量能与 MACD 数值轴在左侧；单根 K 线的日涨幅仍使用自身前收，区间接口必须带首日前一交易点收盘。
- 只有 K 线显示定宽行情 tooltip、光标日期气泡和标题日期；量能与 MACD 普通柱线只联动光标及标题数值，MACD 信号悬浮例外展示类型和完整日期。浮层左右切换不做位移动画；标题指标不得无限扩宽，K 线、量能、MACD 柱宽依次递减，底部日期不被缩放条遮挡。
- 日期轴与缩放按底部面板真实高度统一计算；空间足够时显示滑动条，不足时隐藏可视条但保留内部缩放，不允许页面传私有轴间距。任一面板缩放必须同步其余可见图，并在主题重绘后保留。图外行情摘要通过 `activeBarChange` 联动，离开画布的 `null` 恢复最新行情，不另监听 ECharts；光标跟随数值不设置 `aria-live`。
- KeepAlive 恢复以画布尺寸有效且实例绑定当前 DOM 为完成条件；延后挂载的图表第一次恢复也必须重建，不能只依赖一次尺寸通知。页面不得复制多图联动、分隔线、主题监听或尺寸档案。

### 净值与成长图

- `EquityChart` / `GrowthChart` 复用 §2 的图表主题。对比指数由父页按业务区间归一成资金净值后通过 `extraBenchmark` 注入，组件不自行取数；仅需要等高列的详情场景启用 `fill`。
- `showBenchmark` 默认为 true；未注入外部基准时可使用 points 的 `benchmark_equity` 实线，外部指数使用虚线。显式 false 时彻底移除基准及其 tooltip/图例内容，不能残留旧序列。
- 组合使用 focus 蓝、基准使用 `t.label` 灰、回撤使用 danger 红及浅色面积；图例、线色与悬浮圆点一致。tooltip 显示组合/基准相对首日涨跌幅，基准可见时展示两者之差为超额；回撤子图保持原百分比。

### 应用外壳

- 侧栏宽度固定为 `208px`，顶栏高度 `67px`，主工作区 padding 为 `20px 24px`。
- 应用提供 `sidebar-tabs` 与 `dual-topbar` 两种导航布局：两种模式均在内容区上方显示同一套可关闭工作页签，切换布局不重建页签与工作页面实例；双层顶栏模式依次展示品牌与一级菜单、独立二级菜单栏、工作页签，三级菜单入口由二级菜单下拉承接。一级菜单保持完整内容宽度，空间不足由导航栏自身横向滚动承接，不允许压缩后文字重叠。
- 侧栏模式左栏贯穿应用全高：顶部复用 `BrandMark` 并展示用户指定的英文标语 `Fraudulent Market`，菜单区域独立滚动，底部研究说明固定；右侧顶栏显示由授权菜单树及当前路由标题生成的层级面包屑，详情继承最长匹配菜单归属，当前页强调、长标题省略。双层顶栏模式继续在顶栏显示品牌；切换模式不重建工作页面。
- 侧栏品牌区到菜单的底部留白为16px。一级分组常驻为不可点击、不可折叠的标题；连续的一级直达页面按原顺序合为无标题区段，各区段之间用中性细线和12px间距区分。初次加载、页面路径切换和授权菜单就绪时，收起不属于当前路径的下级分组，展开当前页面所属分组链，并按需在菜单区最小滚动露出当前叶子；同页允许手动浏览多个分组，查询参数变化不重置收展或滚动。加载、空授权菜单、失败重试分别呈现，不回退静态菜单。
- 应用导航字体、字号、字重、文字行高及入口尺寸统一按§3.4“应用导航字阶与尺寸”执行，侧栏、双顶栏、下拉、面包屑和工作标签必须消费共享`--app-nav-*`。字阶不随页面内容密度或颜色预设变化，普通主菜单文字使用`--chrome-text`、当前项使用`--chrome-text-strong`；侧栏/下拉当前叶子保留主色文字。
- 导航定位圆点4px、强调线2px；横向二级当前项使用30%强调色混合中性边框、中性选中背景及底线；工作标签复用同一高度与圆角，连续中性底托承接页签，当前项使用中性选中面、强边框、2px主色上沿与轻投影，不叠加定位圆点或底线；顶栏一级保留主色图标框与整栏底部下划线，不套用二级选中框。侧栏和下拉叶子共用12%主色背景，侧栏叶子悬停16%。下拉的指针焦点不代表选中，移出后恢复普通颜色；键盘焦点使用共享中性背景和焦点框，只有路由命中的叶子保留主色。禁止在消费组件另写同角色的高度、圆角或选中颜色配方。
- 面包屑用于说明当前位置在授权菜单中的层级，例如“系统管理 / 配置管理 / 技术指标”。本项目仅在侧栏模式顶栏显示这条只读路径，当前末项加粗并带`aria-current=page`，不提供节点点击跳转；一级分区等无页面节点也可作为路径文本。内容来自授权菜单树的最长匹配归属，菜单主页尊重运行时标题，详情再追加路由标题，不显示重复末项；权限未就绪或失败时只显示对应状态，不露出旧路径。最近打开页面由工作标签承接，页面返回使用已有返回入口。
- 工作标签按路由路径保留页面组件实例、表单筛选与独立滚动位置，最多缓存 12 个；同一页面类型的不同详情路由必须拥有独立缓存身份，关闭标签或超过上限时同步销毁对应实例与滚动记录。栏首提供“清除其他页签”，展开和折叠时均可使用；保留当前页签、查询态及页面实例，只确认并关闭非当前页签，只有当前页时禁用。所有目标页签的未保存离开确认通过后才统一关闭，任一取消保留全部页签；确认期间禁止重复清除与单页关闭，路由或页签现场变化时取消整批操作。允许关闭最后一个标签：整条工作区栏自动消失，正文显示空工作区；再次选择同一菜单也必须恢复页面，禁止只依赖路由地址变化。**菜单记忆只记菜单主页自身的访问（含查询态），不记详情子路由**——再次点击某菜单永远回该菜单主页，详情现场只由工作标签恢复；避免从榜单/板块等来源进详情后，菜单记忆被劫持到详情路由。
- **详情页返回键的来源必须可信**：个股/板块详情的返回键必须显示具体目标（如“返回每日榜单”），统一消费返回目标文案映射。以来源集合上下文（`stockSet.returnPath`）为目标时，仅当当前对象仍属于该集合才有效；从菜单、标签或直接链接进入（对象不在集合中）时禁用残留来源、归位默认列表。任何从列表/榜单/板块/筛选页跳进个股详情的入口都必须 `setSet` 写入本次来源路径与集合，不得依赖上一次进入的残留值。
- 图表范围等只影响单个内容面板的操作放入该面板标题行，与标题、图例和当前数据上下文就近编组；不得因页面分栏而放到远离图表的页头操作区。
- 导航布局、界面比例模式和手动比例都是独立用户偏好，不与明暗模式或颜色预设绑定；自动模式的计算指数由系统外观配置提供；外观抽屉中的主题缩略图只表达色彩和材质，不暗示固定导航结构或显示比例。
- 双层顶栏的二级导航与两种布局的工作标签栏统一消费 `--chrome-context-bar-bg = var(--chrome-bg)`，只随明暗模式切换中性底色，不混入预设强调色或渐变。二级导航保留选中边框和底部强调线。工作标签栏默认收起为28px摘要行，展开后恢复45px页签栏；箭头按钮可键盘操作，折叠不销毁页签或页面。展开/收起通过账号级 `workspace-tabs` 用户偏好自动记忆，按租户/用户隔离本地回退与待同步意图，快速刷新和旧响应不得覆盖手动选择。栏首固定显示折叠入口、“工作区”、已打开数量徽标和清除其他页签图标按钮（复用 `AppIconButton`），展开时显示“｜”，标题与徽标不参与标签滚动；标签轨道使用中性连续底托，每项展示所属授权菜单图标，缺失时回退统一文档图标，详情沿用最长匹配菜单归属。当前项通过中性选中面、强边框、主色图标和2px上沿强化；普通项不画重复分隔线。页签间距4px、水平内距12px、最大宽度180px；关闭入口始终预留空间，普通态弱显、当前项和悬停时清晰显示，避免切换时宽度跳动；窄宽继续由标签轨道内滚承接。
- 双层顶栏必须在显示比例和视口几何变化期间保持导航 DOM 稳定，禁止通过重挂载制造按钮短暂失效；应用缩放必须使用参与布局和原生命中测试的统一坐标系，浏览器视口变化，或跨屏导致可用区域、屏幕位置、DPR 任一变化时触发布局复测，禁止通过视觉偏移补偿命中区域。
- `.main` 必须保持 `overflow: clip` 和 flex 填充，禁止浏览器把隐藏外层变成可滚动容器；页面滚动由布局系统内部区域承载。
- 菜单激活态按“菜单与交互卡片”的角色规则表达，不统一叠加边线，不使用大面积高饱和底色。
- 侧栏品牌英文副标保留自然大小写，使用12px辅助字号、400字重、轻斜体与默认字距，左边界对齐品牌图标及一级菜单图标；品牌与副标间距8px。侧栏分区标题与其直接菜单的文字左边界一致，图标独立占18px对齐位；主入口行高44px、图标18px，三级起行高36px、图标16px且每层缩进12px，无图标节点也保留占位。标题沿用18px图标且不出现收展箭头。当前分区标题及其所在父菜单随最长匹配路由同步使用中性高对比文字高亮，当前分区标题右侧4px圆点使用 `--shell-accent`，标题图标使用 `--chrome-menu-icon-active-color`，不显示下划线；标题文字和父菜单仍保持中性高亮，选中叶子保留蓝色。手动展开其他分组不改变当前位置，详情页继承所属菜单。当前叶子使用12%主色背景（悬停16%），不叠加常驻左边线，图标不另加彩色底框；箭头固定在行尾，长名称省略并由全局溢出提示保留完整值。

### 按钮与输入

- 横向参数与操作组使用 `AppControlRow`，标签和控件通过 `AppControlItem` 整体换行；选择器及其浏览/搜索附属动作属于同一复合控件，支持的桌面宽度内保持同行，空间不足时整体换行。默认自然宽度，确需均分或填满时才声明 `fill` / `grow`。
- `AppFilterSelect` 的非空候选全部选中时优先显示全选摘要，默认“全部选中”，通过 `allSelectedLabel` 自定义或传空关闭；未全选时按标签/数量模式展示。需要创建候选时显式启用 `allowCreate`，未提供可访问名称时继承占位文案。
- 语义为“默认最新、允许回看”的交易日查询使用 `TradeDatePicker defaultLatest`；训练、回测和数据任务的显式区间不得擅自默认日期。

本节是按钮规范唯一维护入口：组件选型、尺寸及专用组件规则在本节维护，颜色状态在[按钮角色与完整状态矩阵](#按钮角色与完整状态矩阵)维护；键盘与动效分别引用专章。组件清单只作索引，页面模板只列接入与验收步骤；业务场景章节保留执行、保存与错误处理规则，不复制视觉配方。

- 普通业务命令统一使用 Element Plus `<el-button>`：主命令用 `primary`，危险操作用 `danger`，次要命令用默认、plain、text 或 link；禁止页面再封装一套并行命令按钮。
- 纯图标操作统一使用 `AppIconButton`，默认 `md=32px / glyph=16px`，紧凑区用 `sm=28px / glyph=14px`，微型附属操作用 `xs=24px / glyph=12px`。所有纯图标操作必须提供可访问 `label`。
- **关闭动作统一契约**：自有图标关闭、退出临时预览、移除对比对象使用 `AppCloseButton`（内部复用 `AppIconButton`）；组件库内置弹窗、确认框、标签、输入/选择/日期清空、消息、通知与 Alert 图标关闭入口由 `global.css` 唯一适配，禁止消费页面单独覆盖颜色、尺寸、圆角或动画。文字“取消/关闭”命令继续使用 `el-button`；删除真实参数、分段等数据继续使用危险操作，不能因图形相同套用普通关闭。
- 关闭入口按位置选档：`default=28px / glyph=14px` 用于弹窗、确认框与抽屉头部；`compact=24px / glyph=12px` 用于局部临时预览、消息与通知；`inline=16px / glyph=12px` 只用于工作标签、队列 chip、标签移除和字段清空等内嵌操作。尺寸和图形 token 在 `global.css` 的 `--app-close-size-*`、`--app-icon-close-glyph-*` 定义；不得借用内嵌档压缩独立工具按钮。Alert 自定义文字关闭保留组件库文字布局，不强制图标几何。
- 关闭入口的颜色、焦点、禁用和加载呈现见[按钮角色与完整状态矩阵](#按钮角色与完整状态矩阵)；不使用危险红、缩放、浮起或阴影。语义深色标签和告警保持必要的文字对比；页面只控制排列、间距和显隐。
- `AppCloseButton` 必须传具体 `label` 作为可访问名称；明确的关闭图形默认不显示重复文字气泡，名称不自动转成可见提示。阻止点击与 Enter/Space 传播到父菜单、标签或卡片，Escape 继续交给浮层。库内置控件保留原生事件、焦点及键盘模型（字段清空仍依附输入控件，不额外改造成独立 Tab 入口）。工作标签在无悬停/粗指针设备始终显示关闭，最后一个标签也可关闭并进入空工作区；等待离开确认时阻止重复关闭，成功移除焦点所在标签后，有剩余页签时将焦点交还当前标签，最后一页关闭时交给空工作区。取消关闭不改变选择或焦点。
- 关闭呈现不承担业务允许判断：未保存拦截、权限、异步状态由所属容器处理；`PageDrawer` 自定义关闭、遮罩与 Escape 共走组件库关闭链路，尊重 `before-close`，`show-close=false` 同时隐藏自定义头部入口。弹窗继续由 `AppDialog` / Element Plus 管理关闭与焦点归还。
- 校验入口为 `npm run check:close-controls`（构建门禁同时执行），检测直接手写关闭图形、缺少名称和私有视觉配方；允许危险删除与非交互预览图形。交互、离开拦截和焦点恢复由定向组件测试覆盖，明暗主题的实际命中区、裁切与状态须在内置浏览器复核，源码扫描不能替代页面验收。
- 标准命令按钮为 `32px` 高、左右 padding `12px`、文字 `13px / --app-font-weight-section`、图文间距 `6px`；small 为 `28px`、large 为 `36px`。输入框、选择器、按钮统一使用 `--layout-control-radius=6px`，主题只改变颜色和材质，不改变基础控件形态。
- 控件宽度不按组件类型强制等宽，而按内容容量使用全局语义档位：`compact=96px`（短数值/短状态）、`short=140px`（短枚举）、`medium=180px`（普通日期/选择）、`long=220px`（搜索/较长选择）、`wide=300px`（复杂多选/长输入），需要承接容器剩余空间时使用 `fill=100%`。事实源为 `global.css` 的 `--app-control-width-*` 与 `.app-control-width-*`；普通控件由页面选择能完整承载常态内容的最小档位。`AppFilterSelect` 全选摘要优先复用当前模式的容量档位；标签模式由 `visibleTagCount=1..3` 依次映射到 `medium / long / wide`，未全选时预留对应数量的值和 `+N`；`displayMode=count` 映射到 `short`，未全选时显示“已选 N”。页面不得再叠加宽度档位。窄容器统一由 `max-width: 100%` 收缩。新增或修改控件禁止匿名内联固定宽度；确有独立几何或响应式算法的复合组件使用具名组件 class，并说明不能消费通用档位的理由。
- **下拉选型与宽度契约**：普通单选/表单下拉使用 `AppSelect`，列表筛选与紧凑多选编辑使用 `AppFilterSelect`，已有领域选择器（如 `MarketBenchmarkSelect`、`IndicatorSelect`、`AssetProfileSelect`）继续复用其业务组件；这些组件内部统一使用 `AppSelect`。页面与业务组件禁止直接使用 `el-select` / `ElSelect` 或 HTML `<select>`；`el-option` / `el-option-group` 继续用于声明候选项。不要为视觉统一合并不同领域的选项、空值或搜索逻辑。
- `AppSelect` 与 `AppFilterSelect` 默认允许输入搜索；候选较多的页面、指标、方案、用户等选择器保留此能力，少量固定枚举可显式设置 `:filterable="false"`。本地搜索默认按候选 `label` 过滤，不自动匹配编码、说明或拼音；股票等远程搜索继续由领域组件提供 `remote` / `remote-method`。输入搜索只过滤候选，不提交业务值；仅业务明确允许新增值时显式启用 `allow-create`。
- `AppSelect` 输入宽度由 `width` 声明 `compact / short / medium / long / wide / fill` 语义档位（如 `width="short"`）；复合组件可用具名 class 承接自身布局。输入宽度与展开面板宽度分开管理：默认 `fitInputWidth=false`，面板至少与触发器等宽，按候选内容自然扩展；扩展上限取 `global.css` 的 `--app-select-panel-max-width` 与应用画布安全宽度中的较小值，触发器本身更宽时以触发器宽度为下限。超过上限的选项换行，不用省略号隐藏完整候选名称。
- `fit-input-width` 只用于有明确布局理由的等宽面板，当前登记例外为 `StockIngestScopeFields` 的「采集方案」：名称加长说明按两行结构在触发器宽度内换行。新增例外须在所属组件说明理由；禁止调用方用固定像素面板宽度或私有 CSS 绕过默认策略。默认定位和下方回退由 `AppSelect` 统一消费 `floatingPlacement.ts`，调用方无需重复传参；复合选项仍须声明唯一 `popper-class`。全站逐控件契约测试检查原生入口、宽度与复合选项边界。
- 同一页面主工作区原则上最多一个实体 `primary` 主按钮；页面工具栏先确定当前唯一主任务，其他并发命令使用默认、plain、warning、success、danger 等与动作含义一致的语义色，不用多个实体主按钮竞争。行级和列表项的轻量文字操作按 `AppRowActions` 的首个高频动作规则处理，不计作页面主按钮；危险色只用于删除、退出、停用、终止、标记退市等破坏性动作，不能用来制造普通视觉重点。
- **交互状态公共入口**：普通按钮、图标按钮、帮助入口及 disclosure 的键盘焦点使用 `--app-focus-ring`（2px 实色主色框），不得以低透明度光晕替代；外框用于独立按钮，内框用于列表、卡片及可能裁切的容器。导航的紧凑伪元素焦点面和输入框的原生焦点边界保留各自结构，不重复绘制焦点框。
- 紧凑对象列表（角色、字典类型、资产方案）与图标候选共用 `.app-interaction-list-item`：普通悬停为中性 `surfaceHover`，选中使用共享6%主色浅底，不叠加常驻左边线；键盘焦点独立显示；悬停不覆盖选中，按下只强调边界，不浮起。导航型语义标签使用 `.app-interaction-link`，悬停/焦点增加下划线并保留原有状态色；选择型标签按自身选中语义表达，不套用链接下划线。禁止用 `filter: brightness()` 同时改变文字、边框和底色。无悬停设备不新增 hover 反馈。
- 说明触发器 `HelpTip`、`HelpHint`、`DataMetricDetails` 复用 `.app-interaction-help` 的颜色：默认中性字和中性填充，精细指针悬浮或键盘聚焦时主色底和白字，聚焦独立显示共享焦点环；领域组件只维护内容和几何，不用于执行命令。
- 设置和配置折叠标题仅在可折叠时接入 `.app-interaction-disclosure`，共享中性悬浮、按下和内焦点环；静态标题不响应状态。
- 自定义入口与原生控件的按键、ARIA 状态、子控件事件和禁用行为统一遵循[键盘能力与适用边界](#键盘能力与适用边界)。
- 工作区命令按钮保持平面、清晰边界和轻状态反馈，不使用渐变、高光内阴影、厚重投影或装饰性位移；用按钮承载的导航入口、可选卡片遵循下文“菜单与交互卡片”角色规则。状态呈现见下方矩阵；loading 使用 Element Plus `:loading`。
- 图标统一使用 Element Plus 图标或项目既有 SVG，同一区域保持相同描边气质；禁止用 `⚙`、`✕`、emoji 等 Unicode 字符充当界面图标。
- 纯图标异步操作必须使用 `AppIconButton` 的 `loading`，不得在页面内为图标按钮新增私有旋转动画或把 loading 混同为 disabled 灰态。图标按钮有必要的功能说明时显式传 `tooltip`；外层已有 `AppHoverInfo` 时不再声明同一提示，统一遵循本节提示契约。
- Unicode 禁令针对交互图标、操作按钮和纯图标控件；业务公式、状态文案里的箭头/对勾/叉号可作为局部文案保留，但不得用于按钮图标。选择态勾选标记也使用 Element Plus 图标或项目 SVG，不使用 Unicode 字形。
- 自定义原生 `<button>` 仅保留给导航、登录主视觉切换、规则摘要 disclosure 等具有独立语义和结构的专用控件，并在实现中保持专用 class、键盘语义和必要的 ARIA 状态；普通命令和纯图标操作不得借此绕过统一组件。
- 输入与复合选择控件的禁用或只读状态保留外形，边框消费 `border`，文字消费 `textMuted`；Element Plus 的边框与文字适配统一由 `global.css` 承接。禁用控件底色通过 `--el-disabled-bg-color` 读取，当前由 `useLayoutPreset.ts` 映射为 `surfaceHover`；允许与悬停基础色同色，但不表示控件可交互，禁用状态仍通过文字、边框和光标表达，禁用项不响应 hover。按钮和分段选择的禁用呈现见下方矩阵。
- 夜间模式的复选框、单选框、输入边界和表格行悬浮必须使用强边框或主色反馈；空框、选中、禁用三态均需肉眼可辨。
- 多行对象选择卡片的普通项必须保留共享卡片的中性边框；选中项通过主色边框和定位标记强调，不能只给选中项画边界。宿主透明边框只用于共享交互表面占位，不得把可见表面的边框 token 置为透明。
- 工具栏按钮应贴近其影响区域，避免页面右上角堆积所有操作。
- 操作位置按真实影响范围判断，不按“新建 / 保存 / 刷新”等动词机械归类：作用于整页或页面唯一主任务的主操作统一放页头 `.page-head-actions`，位于 `PageSettingsTrigger` 左侧并使用默认 32px 尺寸；只作用于当前页签、局部表单、选中对象或局部区块的命令必须留在对应区域工具区，不进总页头。
- 确定操作归属后，再按实际内容和相邻结构选择横向位置，不将“局部工具区”等同于“统一靠左”：含筛选输入、工作对象或范围选择时，从左侧按任务阅读顺序排列；只有保存、还原、刷新等命令且左侧没有关联输入时，优先在所属内容区域内右对齐，避免紧贴左侧页签导航形成第二排竞争焦点。需要与具体对象或输入就近操作时保持关联，不将所有按钮机械推到最右侧。`AppTabToolbar` 以 `actionsAlign` 承接差异，页面不写私有对齐样式；纯命令组的错误或校验反馈独立放下方左对齐。空间不足时命令保持 DOM 顺序自然换行，核心操作不裁切或隐藏，输入和草稿不因重排重建。
- 顶栏状态和工具按 `32px` 控件基线对齐、间距 `6px`。交易日等状态项使用“图标 + 弱标签 + 强值 + 5px 状态点”的轻量结构；无详情权限时使用只读 `role=status`，不得伪装成禁用按钮，也不得使用永久渐变、内阴影或大胶囊底板。

#### 分段选择

业务选项、组件设置中的枚举选择优先复用；默认 `contained` 使用连续底板与基础边框，选中项在组内浮起，不把选项渲染成彼此分散的独立按钮；轻量视图切换通过 `variant="tabs"` 使用无底板文字与选中下划线，文字固定为表格正文 13px，未选中使用常规字重、选中使用分区字重，避免与同排标题争夺层级；同时继续复用同一组选项和测试锚点；页面级模式/范围切换使用 `tone="primary"` 跟随系统主色，局部工具与设置枚举保持默认中性色；固定操作区使用 `small`，设置抽屉与表单使用默认尺寸；只读资产使用 `disabled`；多组并列使用时由消费页提供可访问名称。状态见下方矩阵，键盘见[键盘能力与适用边界](#键盘能力与适用边界)，切换动画见动效规范。

带底板分段的中性悬浮面由 `--page-settings-seg-hover-bg` 唯一提供，运行时在 `useLayoutPreset.ts` 生成，首帧兜底在 `global.css` 保持一致；不能直接复用与底板同色的普通按钮悬浮面。默认、悬浮和按下须形成可辨层级，不能只以存在 hover 选择器作为验收依据。下划线式 `tabs` 的悬浮／按下保持透明，是独立外观规则；两种外观均保留键盘焦点，禁用不产生悬浮／按下反馈，减少动态效果时关闭过渡。

#### 行操作组

表格 `label="操作"`、自绘表格行、列表项和编辑器条件行的行内按钮组优先复用；首个未显式指定语义色的行内高频动作使用主色，普通次要动作使用常规正文色，禁用态使用弱文本色并满足语义 token 规则定义的文字层级阈值，停用/禁用/终止/删除等破坏性动作使用危险色；动作始终清晰可见，不对整组做透明度弱显；低频或危险动作可设置 `placement: 'more'`，更多入口必须由 Element Plus 点击浮层承接定位、层级、点击外部关闭与 Esc 关闭，菜单命令继续使用 Element Plus 按钮并呈现真实 loading，不得在页面内手写多行按钮、原生命令按钮或自建全局浮层监听。**宽度折叠契约**：单动作或仅需“更多”入口的列声明 `role="action-compact"`，96px 是默认下限；两个及以上候选动作声明 `role="action"`，144px 是默认下限；各行按实测按钮宽度向所属列上报最低可用组合，整列取当前已渲染行最大值向上扩展。动作折叠预算直接消费所属列的响应式宽度，并扣除单元格内边距与边框，避免筛选同帧先缩后扩时沿用中间 DOM 测量值；非表格动作组继续按容器实测宽度折叠。两类操作列统一居中表头与单元格，不允许调用方手写覆盖。单动作最低完整显示；多动作最低保留两个操作入口，可由两个直接动作或“首个直接动作 + 更多”构成，“更多”本身计作一个入口；除调用方明确把全部动作设置为 `placement: 'more'` 外，禁止退化为仅“更多”。操作列不参与表格富余空间分配，余量留给名称、描述等内容列；超过最低组合后仍按实际可用宽度尽量展示更多直接动作，装不下的动作自动收进“更多”菜单，不硬截断；`inline-limit` 是行内数量硬性上限；显式 `placement: 'more'` 的动作恒入更多；可用宽度或按钮实测宽度不可用时使用文字估算与纯数量逻辑兜底。状态颜色见下方矩阵。

隐藏测量副本须保留固有尺寸供宽度计算，同时隔离其布局与滚动溢出；不得撑大页面或表格的滚动范围，也不得用 `display: none` 使测量失效。

#### 按钮角色与完整状态矩阵

标准命令及图标按钮的状态颜色配方入口为 `frontend/src/styles/buttonStates.css`，由 `global.css` 引入；导航链接、说明触发器和紧凑选择的共享状态由 `global.css` 承接，专用导航、分段与品牌角色按本表指定入口维护。默认语义文字和实色背景直接读取当前主题原色；`type` 表达语义，`plain / text / link` 表达强调程度，`size` 只改变尺寸。默认、次要和大量非核心操作无需传特殊 class，直接使用标准组件即接入。禁止为普通按钮创建第二套包装组件或逐页覆盖颜色。

矩阵中的“中性悬浮／按下”分别指 `--app-button-neutral-hover-bg` / `--app-button-neutral-pressed-bg`；“语义浅／悬浮／按下”是该语义色与主题表面按 8% / 14% / 22% 混合；“实色悬浮／按下”为语义色分别向白／黑混合 12%。交互配方在共享样式维护，页面不复制比例。所有状态均包含文字、背景、边框，不使用整体 brightness 改变内容亮度。

| 角色及接入方式 | 默认 | 悬浮 | 按下 | 键盘聚焦 | 禁用 | 加载 | 选中／展开 |
|---|---|---|---|---|---|---|---|
| 次要命令：默认或 info `el-button`，含 plain/dashed | 中性正文、基础面、普通边框 | 强正文、中性悬浮、强边框 | 强正文、中性按下、强边框 | 共享焦点环 | 禁用文字／背景／边框 | 保留默认角色色＋旋转标识 | 无业务选中语义；is-active 仅持续按下外观 |
| 主要／语义实色：primary、success、warning、danger | 白字、主题原色边框和背景 | 实色悬浮 | 实色按下 | 共享焦点环 | 统一中性禁用态 | 保留默认角色色＋旋转标识 | 同上 |
| 语义轻量：primary/success/warning/danger 的 plain/dashed | 主题语义原色文字、语义浅面、40% 语义边框 | 语义悬浮面、实色语义边框 | 语义按下面、实色语义边框 | 共享焦点环 | 统一中性禁用态 | 保留默认角色色＋旋转标识 | 同上 |
| 文字命令：text | 中性或 type 语义文字、透明面／边框 | 中性或语义悬浮面 | 中性或语义按下面 | 共享焦点环 | 禁用文字、透明面 | 保留默认文字＋旋转标识 | 不以悬浮表示已选中 |
| 带底色文字命令：text + bg | 中性悬浮底、对应文字色 | 中性按下底 | 更深一档中性底（14% 强正文混入） | 共享焦点环 | 禁用文字、透明面 | 保留默认角色色＋旋转标识 | 不适用 |
| 链接式命令：link；表格内联操作 | 中性或语义文字、透明面／边框 | 保留文字语义、下划线 | 保留语义、加粗下划线 | 共享焦点环＋下划线 | 禁用文字、无下划线 | 保留文字＋旋转标识 | 更多菜单展开保留下划线 |
| 图标命令：AppIconButton ghost / soft | ghost 透明面，soft 中性底；default 中性文字，primary/danger 对应语义 | 对应中性／语义悬浮面；已选项保留选中底 | 对应中性／语义按下面 | 共享焦点环 | 禁用文字；ghost 透明，soft 禁用底 | 保留当前角色色，旋转图标替换原图标 | 展开用 aria-expanded；可切换项用 aria-pressed，选中为主色字和共享浅底，禁用仍呈禁用态 |
| 表格更多菜单行：AppRowActions | text 角色；info 使用中性正文 | 对应悬浮面 | 对应按下面 | 共享焦点环 | 同 text | 同 text | 菜单容器管理展开，不自建颜色配方 |
| 说明触发器：app-interaction-help | 中性文字、填充和边框 | 主色底、白字 | 保持说明语义，不模拟命令执行 | 主色底、白字及共享焦点环 | 不提供禁用态；无说明则不渲染入口 | 不提供加载态 | 浮层按焦点／悬浮生命周期展示，不表示业务选中 |
| 关闭／清除：AppCloseButton 及已登记库内入口 | 次要文字、透明面 | 强文字、中性悬浮面 | 强文字、中性按下面 | 共享焦点环 | 45% 可用性弱化，禁止操作 | 支持 loading 的关闭按钮保留原色＋旋转图标 | 不适用 |
| 带底板分段：PageSegmented contained | 中性文字、选项透明并露出连续底板 | 未选项：neutral 使用分段专用悬浮面，primary 使用主色浅面；两者须与底板可区分 | 未选项使用对应中性／主色按下面 | 共享内焦点环 | 保留当前选择，未选项弱化且禁止切换，不以整组透明度淡化边界 | 不提供加载状态，父容器负责 | neutral 使用选中表面和边框，primary 使用实色；悬浮不覆盖选中，按下保留选中标识 |
| 下划线页签：PageSegmented tabs | 无底板、次要文字 | 未选项增强中性文字，背景保持透明 | 增强中性文字，背景保持透明 | 共享内焦点环 | 保留当前选择，未选项弱化且禁止切换 | 不提供加载状态，父容器负责 | 保留底线和字重；tone 只改变底线语义，不改成实色选项 |
| 紧凑选择：热点筛选／对比队列（`.app-interaction-choice`） | 中性文字、基础面与边框 | 未选中为中性悬浮；选中面不被覆盖 | 强调边框，不把选中当持续按下 | 共享内焦点环 | 遵循宿主禁用属性 | 不提供加载状态 | `aria-pressed` 表达选择，共享6%主色浅底与主色边框 |
| 摘要折叠／顶栏状态 | 透明面、上下文文字 | 中性悬浮面（摘要保留轻量比例） | 中性按下面 | 共享焦点环 | 静态摘要无按钮；只读状态无点击入口 | 不提供加载状态 | 展开保留箭头和 aria-expanded |
| 导航、选项卡片、指标分段 | 继承 §菜单与交互卡片的专用表面 | 共享导航／卡片反馈，保留已有轻微位移 | 导航中性按下；卡片按下几何与投影遵循[菜单与交互卡片](#菜单与交互卡片)；指标分段中性按下 | 共享焦点环 | 禁用时不出现悬浮或位移 | 忙态不出现悬浮或位移 | 选中边线／底线始终保留，指标选中按下使用主色 14% 面 |
| 登录品牌提交：login-primary | LoginView 的品牌渐变及独立几何 | 保留品牌位移和投影 | 回到原位 | 品牌色 2px 焦点环 | 70% 透明度且不可操作 | 原按钮内显示加载文字／标识并禁止重复执行 | 仅限登录／注册提交；login-tab 是切换页签，当前项保留底线 |

按钮颜色选择按动作目的判断：

| 动作角色 | 接入方式 | 边界 |
|---|---|---|
| 页头唯一主命令 | 实色 primary | 如数据质量的“立即质检”；并行同级命令才按上下文使用 plain，不用颜色表达是否已成功 |
| 刷新、查看、标记正常、数量快捷填充等次要命令 | 默认或 info；按位置用 plain/text/link | 可用文字用正文色，不能伪装成禁用弱文字 |
| 恢复、覆盖、结算等需要用户留意后果的命令 | warning | 不按功能名称随意增加警告色 |
| 确认启用或明确正向状态变更 | success | 普通诊断／查询本身不表示成功 |
| 删除、停用、终止等破坏性命令 | danger | 买入／卖出使用命令主色，交易方向由文字及邻近金融色标识表达 |

- 状态优先级为禁用（未加载）／加载 > 按下 > 悬浮 > 默认；焦点环独立叠加，选中／展开独立表达。禁止把 focus、hover 当作业务 selected，禁止把 loading 画成灰色 disabled。库按钮 loading 不使用通用白蒙层，避免暗色主题突然泛白。
- 主色、成功、警告、危险使用同一算法；info 是中性角色，普通按钮与表格行操作都映射正文色，不能使用禁用弱文字。运行时 info 的基础色、RGB 与派生色从当前 `text` 生成。普通次要操作不得默认改成主色强调。
- 主题原色统一消费：主色链接式按钮、语义文字按钮及主色分段选项直接使用 `--el-color-primary` 等对应主题原色；实色按钮默认背景使用同一原色，白字保持现有设计。导航链接使用 `.app-interaction-link.app-interaction-link--primary` 共享颜色、悬停下划线和键盘焦点，保留 RouterLink 导航语义。禁止按对比度阈值自动生成另一套常态文字色或实色背景；可读性通过具体主题评审处理。
- 登录页例外只覆盖 `login-primary` 品牌提交和 `login-tab` 模式页签；创建账户、返回登录、发送验证码等文字命令使用 `el-button link`，切换预设用标准按钮，主题图标用 `AppIconButton`。不得按 `login-*` 前缀放行任意原生按钮或私有颜色配方。
- 样式复用必须消除覆盖：共享角色的消费者只维护几何，禁止在宿主、局部 scoped 选择器或动作名称子文字上覆盖共享交互色，复合卡片中独立的金融值与业务状态继续消费对应 token；静态值与导航值共用名称类时，静态颜色只匹配非链接分支。不得用整行或整个按钮组的 opacity 表示已办／只读，避免连同可用操作一起变淡；使用状态标签和中性表面表达。
- 标准命令按钮由共享 CSS 直接接管库内部 text/link/has-bg 的背景分支，不再回退通用 `--el-fill-color` 作为按下色。图标按钮与行操作只维护几何和行为，不重复定义状态颜色。关闭、导航、分段、品牌是明确的专用角色，不用于普通业务命令绕过矩阵。
- 鼠标悬浮反馈只面向支持 hover 的精细指针；触摸保留按下反馈。颜色过渡复用共享180ms配方；减少动态效果时关闭颜色过渡，保留必要加载标识。禁用和加载必须由组件属性阻止行为，CSS 只负责呈现。
- radio/checkbox/switch、输入附属箭头、分页和树节点属于复合选择／输入控件，遵循相应组件模型；不把它们伪装成命令按钮。新增按钮角色必须补本表、共享实现及代表性消费验证，不能用业务页面名称形成私有角色。

#### 列表高级搜索

- 列表筛选区统一判断 ≥3 个可收纳条件的门槛；0～2 个全部展示。搜索项与默认常显组合登记到 `searchGroups.ts`，页面按字段插槽提供原有控件和生效摘要、清除回调、适用性及错误状态。新增列表或增加搜索项时同步检查接入，不能仅按路由数量判断；静态表、编辑器和运行参数区不套用。
- 常显两个字段，其余放筛选条下方的高级区；每个分区内部保持条件选择在前、文本输入在后。工作对象、研究日期、统计窗口等整页上下文固定展示；范围输入保持整体。高级搜索入口与重置、排序位于常显命令区，排序仍为该命令区最后一项，命令区占满剩余宽度，保留排序控件右对齐。
- 收展和常显成员替换仅影响展示，不发查询、不归页、不清空、不重建字段控件。普通进入默认收起，查询条件仍为会话态。展开区域在分隔线下独立显示弱化标题“高级条件”，下方排列筛选控件，不增加图标、背景或按钮；收起时保留“高级条件：”摘要。标题、摘要与上方操作行使用相同横向内边距、保持左对齐。高级区限制摘要包含默认生效条件，计数按逻辑字段而非多选值数量；全选或无约束状态不计数。摘要删除只清除对应字段限制，重置筛选则按页面既有默认一次恢复全部筛选。
- 已生效条件摘要统一使用 `el-tag type="primary" effect="light"`：主题浅底与主题色边框表达条件正在生效，内部文字命令使用默认中性 `el-button link` 保持正文可读性，悬浮／按下／键盘焦点复用链接状态；清除入口复用库关闭行为及共享关闭配方。摘要不是静态属性或可切换选项，不使用 info 灰底、深色主按钮背景或伪选中属性表达状态；页面不覆盖其颜色。主题变化消费现有变量，不新增颜色算法。
- 页面设置的「组件设置 → 对应列表 → 常显搜索条件」用复选框勾选两个常显条件；未选满时保留草稿并提示，选满自动保存，配置走 PG 布局 page/user 层及既有归属隔离。动态权限、业务模式可收窄候选；旧字段失效时保留有效成员并补默认。保存失败保留待保存值并明确提供重试，不额外提供常显条件恢复按钮；统一通过抽屉底部恢复默认清除全部布局用户覆盖，同时丢弃未完成选择。关闭抽屉也丢弃未选满的草稿。
- 输入框、下拉已有占位提示以及自带标签的复选框/开关不重复添加标题；无可见提示的控件通过 `selfLabelled: false` 显示左侧标签。筛选控件统一垂直居中、同一行尺寸一致；百分比宽度依赖包裹层时须改为明确宽度与 `max-width` 上限，避免下拉收缩成箭头。
- 长条件区受控滚动，保证列表仍可操作；窄屏单列。条件错误显示在字段旁并阻止无效查询和收起；摘要定位展开后聚焦原控件，收起时焦点回到入口。

- 连板天梯同日筛选刷新保留热点入口和焦点，热点数量明确标为上次结果，旧摘要和内容由加载态接管；跨日、错误或无权限不展示旧热点。
- 连板天梯的日期、统计窗口及筛选操作栏独立置于页面 action 区，位于主从工作台上方；不嵌入天梯分层或随走势分析栏收窄。领域操作栏由 `LimitLadderFilters` 承载，继续复用公共高级搜索与排序控件。

#### 查询、重置与刷新

- 筛选/查询类控件（关键字、下拉、日期、分段、勾选、分页、排序）改选或输入后必须自动查询；除分页换页只查询当前页外，条件变化同时回到第 1 页。关键字统一防抖，列表筛选条不设置“查询”按钮。一次性执行、运行、评估、保存等动作型提交不属于筛选查询，继续使用显式命令。
- 列表筛选条按“范围/日期/下拉/勾选等条件 → 文本搜索框 → 重置筛选等命令 → 排序”排列；存在多个文本搜索框时连续放在全部条件选择之后。排序统一复用 `AppSortControl` 并固定为所属操作栏的最后一个控件；空间不足时保持该 DOM 阅读顺序自然换行，不把搜索框插入条件选择之间，也不把排序拆散到其它位置。
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


#### 键盘能力与适用边界

键盘支持按控件语义统一，不为所有可点击对象强加同一组按键。焦点只表示键盘操作目标，选中、展开和业务执行分别由 `aria-selected`、`aria-pressed`、`aria-expanded` 与实际状态表达。鼠标和键盘必须进入同一个业务处理函数，遵守同一权限、禁用、加载与确认流程。

| 能力 / 场景 | 支持按键与结果 | 实现入口与边界 |
|---|---|---|
| 顺序聚焦 | Tab / Shift+Tab 前后移动 | 原生 DOM 顺序；禁止正数 tabindex；禁用命令不进入正常焦点顺序，说明性只读入口可聚焦阅读 |
| 普通按钮、图标按钮、折叠按钮 | Enter / 空格执行；折叠保留展开状态语义 | 原生 button / Element Plus / AppIconButton 自带行为，不再合成第二次 click |
| 链接 | Enter 跳转；组合键、打开新标签等遵循浏览器 | 原生 a / RouterLink；空格仍用于滚动，不按命令按钮处理 |
| 自定义卡片、标签、列表命令 | Tab 到达，Enter / 空格复用 click | `directives/keyboardActivate.ts` 的 `v-keyboard-activate`；显式提供 role、tabindex、名称及动态状态；只接受焦点目标自身事件，不激活子按钮的父操作 |
| 工作标签 | ← / → 循环移动，Home / End 到首尾；Enter / 空格激活 | `WorkspaceTabs` 使用单一游走 tabindex；方向键仅移动焦点并滚动至可见，不提前切页；关闭按钮保持独立入口，沿用未保存确认和关闭后焦点恢复 |
| 分段选择、独立选择列表 | Tab 到各按钮，Enter / 空格选择 | `PageSegmented` 和规则列表使用 group + button / aria-pressed；tabs 外观不等同于 ARIA tablist，不虚报 listbox/option 的方向键能力 |
| 列表与树的条目排序 | 聚焦把手后空格 / Enter 拿起，再按 ↑ / ↓、Home / End 预览位置，空格 / Enter 确认；Esc、Tab 或失焦取消 | `AppDragHandle` → `useReorderInteraction` → `reorderKey`；未拿起时方向键不触发排序；树键盘排序限当前兄弟组，跨层通过拖动或已有上级选择与保存流程完成；命令拒绝重复和输入法/组合键，方向移动允许长按；仅接管把手自身事件，不覆盖树节点导航和浏览器快捷键 |
| 单行输入确认 | Enter 搜索、登录提交或提交周期参数 | `utils/keyboard.ts` 的 `submitOnEnter`，在 keydown 处理；输入法确认、长按及组合键不触发；多行输入保留换行；无自动提交语义的输入不添加 Enter 命令 |
| 左右分栏 / 图表上下分区 | 对应方向键按步长调整，Home / End 到允许边界；允许长按 | `keyboardRangeValue` 由 `AppSplitWorkspace`、`StockChartWorkspace` 共同消费；遵守当前最小尺寸，图表只调整相邻两区，沿用拖拽的草稿与提交链路 |
| 选择器、日期、菜单、树等复合控件 | 按组件库提供的方向键、确认、退出行为 | 优先复用 Element Plus；不得以全局事件覆盖其输入或导航，不承诺业务表格支持电子表格式方向键编辑 |
| 弹窗、抽屉与提示 | 弹层内焦点与 Escape 按共享组件配置；关闭后恢复有效触发目标 | AppDialog / PageDrawer / AppDetailDrawer 与组件库负责焦点约束；AppHoverInfo 负责聚焦说明和 Escape 收起；有未保存或提交约束时沿用业务关闭守卫，禁止新增全局 Escape 关闭全部弹层 |
| 可点击表格行 | Tab 到行内命令，Enter / 空格执行 | 整行点击只是快捷入口，必须保留行内按钮作为等价键盘入口；不把 tr 改为按钮，不接管表格方向键；可隐藏的业务列不能成为唯一入口 |
| 页面业务快捷键 | 当前仅盘感训练：→ 下一日 / 末日结算，B 买入当前量，S 卖出当前量 | `usePageShortcuts`；运行态、具备 training:trade 且对应动作可用时生效；鼠标与键盘共享异步互斥和错误反馈，按钮标注快捷键并提供适用说明 |

- 公共判断位于 `utils/keyboard.ts`：自定义命令不接管已消费事件、输入法组合期（含 keyCode 229）、Ctrl / Meta / Alt / Shift 组合键；命令不接受自动重复，方向导航与尺寸调整允许自动重复。浏览器复制、粘贴、查找、刷新、撤销等快捷键保持原行为。
- 页面快捷键还必须让位于 input、textarea、select、contenteditable、链接、按钮和所有 tabindex 控件；有可见 dialog、alertdialog、menu、listbox 或日期面板、页面隐藏或 KeepAlive 失活时暂停。监听在恢复时幂等注册，失活和卸载时清理；异步动作结束前不重复执行，失败需向用户反馈。
- 权限判断必须在快捷键的共享业务入口执行，不能仅依赖模板 `v-permission`。加载、无权限或数据状态不允许时，不消费按键、不发请求；快捷键不替代服务端鉴权。
- 未声明的全局保存、删除、返回、撤销、图表十字线键盘移动等不属于当前能力；需要时先明确作用域、冲突、替代入口和反馈，再接入共享机制。不得以“统一键盘”为由接管系统快捷键。
- 新增/修改入口须验证：鼠标与键盘等价、焦点可见、输入法与组合键不误触、禁用/忙态/权限一致、子控件不冒泡激活、弹层优先、缓存页面不残留监听。语义和事件用定向 Vitest 验证；真实焦点移动与滚动由内置浏览器复核。

### 提示、截断与可访问名称

以下是全站提示准入的唯一规则；表格、按钮和响应式清单引用本节，不另建默认行为。

| 对象 | 默认行为与接入方式 |
|---|---|
| 可访问名称 | 图标命令必须提供 `label` / `aria-label`；名称用于辅助技术，不自动生成可见气泡。 |
| 关闭、清空、移除临时界面，完整可见的名称、数值和普通文字命令 | 不显示重复说明。关闭入口复用 `AppCloseButton`；普通命令不因存在名称自动弹提示。 |
| 需要解释的纯图标入口 | 显式传 `AppIconButton.tooltip`，内部复用 `AppHoverInfo`；页面设置、任务中心、图标编辑/新增等依实际用途声明，不给所有图标统一默认提示。 |
| 必要的错误、状态和命令说明 | 使用 `AppHoverInfo`；命令或禁用原因使用 `AppActionHint`，行操作通过 `AppRowAction.tooltip` 接入；只读标签仅在拥有归属、日期或只读等补充信息时提示。 |
| 字段帮助与多段说明 | 单块解释使用可见 `HelpHint`，结构化说明使用 `HelpTip`；不得把整块指标或卡片变成无标记的隐形说明区。 |
| 真实截断的菜单、标签、选项和表格原文 | 由 `AppOverflowTooltipHost` 自动检测；原生省略判定须确认横向裁切生效，覆盖缩放下整数宽度相等但文字已发生亚像素截断的情况，同时容忍盒边界与文字坐标的取整误差，不能仅凭 `text-overflow` 声明或 `scrollWidth/clientWidth` 判定；内容完整时不显示。原文默认来自真实内容/输入值，原文不在 DOM 时显式提供 `data-overflow-tooltip-content`，该属性只提供内容，不强制触发。 |
| 图表行情读数、点击菜单与操作面板 | 保留所属共享图表或点击交互机制，不转换成普通悬停说明。 |

**说明图标与内容格式**：先判断读者要了解的是“规则”还是“当前对象的补充事实”，再选择入口；共用悬浮机制不意味着统一图标或强制统一正文结构。

| 场景 | 入口与组件 | 正文格式与边界 |
|---|---|---|
| 单一口径、单位、公式、适用范围或字段含义 | `?`，`HelpHint` tooltip | 直接说明一个概念，必要时附公式或范围；不把已显示的当前值再包装成明细表。 |
| 多个独立规则、使用步骤、例子或注意事项 | `?`，`HelpTip` popover | 沿用 `HelpTipItem` 的具体问题或 warning 标题与 `ul/li` 内容结构；不因内容较长就改为统计明细。 |
| 当前对象的额外日期、分母、覆盖分项、来源或状态事实 | `i`，`AppHoverInfo` popover 与所属领域的明细组件 | 对象标题、字段—值、可选简短口径备注；数字带单位，日期明确是业务日、归档日、采集时间还是质检时间。至少提供一项常驻区域未显示的有效事实；允许完整分项中保留必要的主值上下文。 |
| 当前事实同时需要简短规则解释 | 一个 `i` 明细入口 | 分项用字段—值，规则放底部备注；不在同一对象旁并列重复的 `?` 与 `i`。纯规则内容仍使用帮助入口。 |

- 结构化帮助的 `HelpTip` 默认插槽只放 `HelpTipItem`。每项必须且只能传 `question="具体问题文本"` 或 `warning`：标题分别为具体问题加冒号、固定“注意：”；警告消费 `--app-warning-text`。标题下全部正文无论长短都使用语义化 `ul/li`，点号标记由组件统一呈现；调用方不得手拼标签、冒号、列表符号、颜色或项间距。两种帮助不以字符数作为硬边界，长说明须换行并遵守共享浮层宽度上限。
- 图标表达用途，正文结构由内容决定：`?` 可承载短提示或结构化帮助；`i` 的统计详情采用键值结构，并不要求所有普通信息文字都表格化。无额外说明或明细为空时不生成入口。新增或修改的多入口区域应提供带对象名的可访问名称，按“对象名＋用途”命名，避免多个入口都只叫“说明”。
- `0`、`—`、未采集与未检查须保持各自业务语义；核心异常、必要状态和操作必须常驻。浮层只读，导航与执行使用外部具名操作，不能靠悬浮才能发现或执行。

- 原生 HTML `title` 不再用作提示文案或触发信号；`nativeTitle` 接口已移除。组件的 `title` 标题属性、标题插槽、路由/业务标题及 iframe 可访问名称保留，不按字符串批量删除。
- `AppHoverInfo` 与截断宿主复用 `tooltipTiming.ts` 的停留门槛；鼠标停止后才显示，持续移动重置等待，离开/点击/Escape 关闭，键盘聚焦立即显示，鼠标点击及其引起的焦点归还不锁定提示；输入来源由 `useTooltipInputModality` 在显式说明和截断宿主间共享，不接管控件焦点。富内容 popover 允许移入阅读；点击菜单及图表读数不等待这个门槛。窗口失焦、页面转入后台或窗口尺寸变化时统一清除已显示提示、待显示计时及触发区域瞬态状态；界面比例与切屏适配复用 `useDisplayScale` 已有的 resize 通知，显式提示和截断提示共用一份监听。尺寸变化后按最后一次鼠标位置重新核对真实命中：仍命中且页面可见时重新计算停留门槛，保留切屏分阶段通知期间已经建立的静止鼠标意图；移走、遮挡、移除或已不再截断的目标不恢复。原位置再次移动或重新 Tab 聚焦也可恢复，无需离开再进入、点击或刷新；窗口恢复焦点不能视为新的键盘阅读意图，不自动重弹，后续鼠标停留或 Tab 聚焦仍按原规则显示。页面不得新增私有计时器或第二套监听。
- `AppHoverInfo` 的 `reference` 只用于稳定的虚拟锚点；图标按钮保留真实 button 根节点及原有权限、点击和加载语义。监听随锚点更换与销毁清理，缓存页面停用时清理瞬态显示。提示文案为空或不适用时不生成空触发层。
- 禁用原因通过 `AppActionHint` 的外壳悬停或键盘阅读；禁用按钮仍不执行，外壳不代理点击。无权命令连同说明入口一起隐藏，权限过滤先于提示；加载状态不改成可执行状态。相同信息只出现一个提示，有显式说明的目标不再叠加截断气泡。
- 提示复用 `app-wrapping-popper` 的主题、排版和空间边界；共享 AppHoverInfo 允许在原方向空间不足时四向回退，并以双轴边界约束保持正文在视口内；简短说明与结构化帮助保留各自组件角色，不在消费页面私设颜色、字号或动效。
- `npm run check:tooltips` 按 Vue/TS AST 检查原生/透传 title 和旧自动接口，已接入生产构建；组件标题、插槽和 iframe 名称不误报。定向测试覆盖默认不显示、显式说明、真实截断、禁用原因、焦点/鼠标区分、点击关闭及监听清理；内置浏览器复核实际主题、位置和消失行为。

### 滚动条显隐

- 自建滚动区域统一使用 `AppScrollArea`；普通表格、宽表以及 Select、Dropdown、Cascader 等内部 `ElScrollbar` 统一由 `installScrollbarPolicy` 接管。导航与工作页签遵循同一规则，不保留始终隐藏的例外。禁止页面直接使用 `ElScrollbar`、原生 `overflow: auto/scroll`、私有滚动条样式或显隐参数。
- 横纵方向分别判断真实溢出；无溢出时不显示滑块或空轨道。悬停、所属区域内的键盘焦点、用户实际滚动和滑块拖动任一成立时显示；鼠标点击获得的普通焦点不锁定显示。滚轮、触摸移动、滚动按键或轨道操作提供滚动意图，实际滚动后才进入保持期；菜单切换、缓存激活、程序定位与尺寸收敛引起的位置变化不主动点亮滚动条。触摸不产生粘滞悬停，实际滚动后同样短暂显示。停止滚动后的保持时长和溢出容差唯一维护在 `components/scroll/scrollbarPolicy.ts`。
- 指针离开区域时，仍在拖动的滑块保持显示；释放、取消、窗口失焦或页面隐藏时清理瞬态状态。嵌套滚动按实际 viewport 分别记账，不把子区域滚动算到父区域；缓存页恢复后重新测量，不恢复旧的悬停或拖动状态。
- `LayoutHost` 操作区在正常空间保持自然高度；极低窗口中若操作区将挤掉主区，操作区通过 `AppScrollArea` 自身收缩内滚，给主区至少保留两行密度控件的可达窗口。主组件的 `minH` 不变，不足时继续走既有主内容区滚动兜底。
- 显隐仅控制滑块和轨道的透明度、可见性与命中，禁止改变内容宽高、列宽或滚动位置。应用内与受控浮层的轨道在公共策略接管前默认隐藏，避免初始化或缓存切换闪现。隐藏轨道不拦截点击；可见滑块和轨道继续复用组件库的拖动、点击与界面比例坐标换算。没有可聚焦子控件且发生溢出的 viewport 由公共层补齐键盘滚动入口，表单和导航不增加额外 Tab 停靠点。
- 视觉 token 唯一维护在 `styles/scrollbar.css`，颜色沿用现有主题中性色；减少动画偏好取消过渡，强制颜色模式在有溢出时保持显示。文本域等原生编辑控件保留浏览器滚动；图表画布内平移/缩放、浏览器自身界面不属于内容滚动条。
- `AppScrollArea` 的外壳只承担尺寸、表面和布局项职责；内容层通过 `--app-scroll-*` 布局变量或 `contentStyle` 承接 flex/grid、间距和内边距，禁止使用后代宽泛选择器影响嵌套实例。`as` 保留原生语义或既有四态/表单组件；不增加业务状态分支。位置恢复与测量通过组件暴露的 `viewport`、`scrollTo`、`setScrollTop`、`setScrollLeft` 和 `update` 操作真实滚动元素，不再读写外壳的 `scrollTop`。
- `npm run check:scrollbars` 是构建门禁，检查未接入的原生滚动区、私有显隐样式及消费方覆盖参数；行为、真实库组件和资源清理由定向 Vitest 覆盖。临时内置浏览器复核正文、表格、抽屉和导航的实际进出、滚动与拖动，不能只用样式文本断言替代交互验收。

### 金额展示与输入

- 金额格式化的唯一前端事实源是 `frontend/src/utils/money.ts`。本金、资金、现金、资产、成交金额、费用、盈亏、市值、净流入、价格，以及图表中的金额轴和金额 tooltip，必须消费 `formatMoney` 或该文件导出的缩放/输入 helper；页面和业务组件不得再定义私有 `money`、`wan`、金额 `toLocaleString` 或正则分组逻辑。
- 所有可见金额从个位起每三位使用英文逗号分组，例如 `1,000,000,000`。金额精度沿用业务口径：普通金额默认两位小数，明确的整数金额可用零位，成交价等价格按接口口径使用两位或四位；千分位规范不得擅自改变存储精度。
- 使用“万/亿”等缩放单位时必须明确展示单位，缩放后的数值部分仍使用三位分组；不得以缩写为由绕过格式化。正数是否显示 `+` 由涨跌、净流入等业务语义决定，负号保留在数值最前。
- 精确十进制字符串禁止先转成 JavaScript `number` 再格式化；使用 `formatMoney` 保留数据库定点精度。既有浮点业务字段可按既有精度归整后格式化。
- 金额输入控件展示千分位、业务状态和接口值不带分隔符：Element Plus 数字输入统一使用 `formatMoneyInput` / `parseMoneyInput`；精确定点字符串输入在非编辑态显示千分位，聚焦编辑时可以显示无分隔原值。粘贴带逗号金额必须能够正常解析。
- 百分比、数量、手数、代码和日期不是金额，不得为了套用本规范改变其业务单位；其中确需数值分组时使用相应数值工具，不冒充金额格式化。

### 日期时间展示

- 后端可以使用 ISO 8601 传输日期时间，但用户可见文本不得直接暴露 `T`、毫秒或时区后缀。秒级和分钟级展示统一消费 `frontend/src/utils/dateTime.ts` 的 `formatDateTimeSeconds` / `formatDateTimeMinutes`；页面不得通过 `slice`、`replace` 或私有 formatter 重复实现。
- 默认完整格式分别为 `YYYY-MM-DD HH:mm:ss` 和 `YYYY-MM-DD HH:mm`。仅时间模式可以在统一格式化后截取 `HH:mm`；空值文案由调用方按场景传入，不得把无值伪装成当前时间。

### 表格与列表

- 主数据表应作为 `growMain` 占据剩余空间，使用 `height="100%"` 让表体内部滚动；当一个标签页工作区承载多个互斥主表时，由 `tabs` 作为唯一 `growMain`，当前面板内的表体承接滚动。
- `list` 原型必须且只能有一个顶层 `growMain`；主列表不得使用 `embedded`。
- 长文档中后方仍有同级内容的局部表格不得独占富余高度；统一使用 `embedded`，由 `AppDataTable` 默认消费 `components/table/tableSizing.ts` 的 `LONG_DOCUMENT_TABLE_MAX_HEIGHT`，页面不重复传默认上限。显式 `height` 不叠加默认上限；显式 `max-height` 优先，确需完整展开时传 `:max-height="null"` 并说明原因。纵向混合工作台中，前置主业务表使用 `LEADING_WORKBENCH_TABLE_MAX_HEIGHT`，并通过 slot 的 `minH + idealH` 声明受控收缩范围；末尾表格可由 `section` 作为成长容器，在 `pageRegistry` 声明为唯一 `growMain`，内部表格继续作为嵌套 slot 登记。`VMixedGrow` 只让声明 `idealH` 的前置块收缩，未声明的固定块继续保持自然高度；页面不得复制 `clamp`、视口减法、私有行数换算或用 CSS 模拟成长关系。
- 表格内部列线与结果区外框分开：布局配置保留 `border` key，对外名称为“显示列分隔线”，默认关闭，仅控制列线，不控制卡片或工作区外围边界。`AppDataTable` 保留组件库固定列布局并移除其额外围框，外框与圆角由所属容器消费主题 token。
- 页面数据表格统一使用 `AppDataTable + AppTableColumn`。页面不得直接使用原生 `<table>`、`el-table`、`el-table-column`，也不得向列传 `width/min-width`。
- 列宽采用语义自适应契约：选择、展开、序号等结构列保持稳定窄宽；开关列显式使用 `switch`，固定 80px 以容纳标准开关、单元格留白及操作空间，不占富余宽度；普通名称使用 `name`，含前置选择/收藏等控件并展示主副信息的对象识别列使用 `entity`；其余列取“语义内容基础宽度”和“表头标签 + 同行元信息 + 排序/筛选控件 + 主内容前置控件”的较大值，并按 8px 网格取整。表格内编辑控件或控件组通过 `control-width="compact|short|medium|long|wide"` 声明容量，列宽额外计入单元格留白并按网格向上取整；评分指标、评分参数、权重分别使用 long、wide、medium。表格内多选下拉必须按 `filterSelectVisibleTagCount` 或 `filterSelectDisplayMode=count` 计入控件容量和单元格留白，禁止先压窄控件再裁掉标签、`+N` 或“已选 N”。中英文混排使用稳定字符权重估算，不做运行时 DOM/数据采样，避免数据变化触发列宽跳动；异常长表头受角色上限保护，真实截断时由全局省略提示展示原文（超长内容按统一上限截断）。容器有余量时由 Element Plus `fit` 按最小宽度权重分配并铺满，空间不足时保持最小可读宽度并由表体横向滚动。
- 横向滚动与单元格溢出是两套独立机制：前者只由所有列的语义最小宽度总和是否超过表格可视宽度决定；后者由 `AppDataTable` 递归比较单元格内文字、标签和嵌套结构的真实矩形是否越过该单元格边界。不得使用包含透明 padding / margin 的 `scrollWidth` 制造虚假省略号。省略号只有一种视觉规则：必须由实际承载文字的内容容器通过原生 `text-overflow: ellipsis` 绘制在自身末尾；表格只负责检测真实遮挡和触发统一悬浮，不得使用渐隐遮罩、伪元素或独立字符在单元格外层补画省略号。表格内标签、评分胶囊及其它有边界的复合内容必须在自身内部收缩，禁止切断背景、边框、文字或数字。全站省略原文统一由 `AppOverflowTooltipHost` 自动承接，只在真实截断时显示，并遵守统一的宽度与高度上限；页面不得传列级 `show-overflow-tooltip` 或自行维护截断 tooltip。操作列及动作组属于命令交互边界，不接入普通文本省略悬浮，也不得把隐藏测量副本纳入提示内容；结构列与操作列继续使用各自专用契约。
- 列表中的长文本摘要通过 `AppTableColumn` 的 `single-line` 显式限制为单行，由单元格原生绘制省略号；原文沿用统一悬浮提示，超出提示上限的长文由已有日志或详情入口继续承载，不让单条数据无限拉高行高。
- 换行与省略按阅读任务区分：表格/列表的名称、短标签和辅助摘要优先单行省略，完整原文通过真实截断提示或已有展开/详情恢复；报告正文、错误详情、处置说明及多行输入保留自然换行。关键状态与核心数值优先完整展示，空间不足时须有明确的完整值恢复入口；按钮与正在编辑的控件不得省略或裁切，操作区允许换行，表内编辑区按控件容量保留最小宽度并区内横向滚动。不得在数据层按字符数裁掉摘要原文来模拟视觉省略。
- 截断提示、显式操作说明与可访问名称的准入及交互统一遵循本节“提示、截断与可访问名称”；响应式收起的指标数值通过可见的 `HelpHint` 独立入口恢复，不把整块指标按钮变成隐形提示区。
- 列语义角色同时决定宽度和对齐：`structural/switch/rank/status/action/comparison-number` 的表头与单元格居中，`number` 右对齐，`code/name/entity/date/datetime/key/text/description` 左对齐；`number/comparison-number/rank` 使用等宽数字，表头默认与主值保持同一基准线。页面和业务组件不得传 `align/header-align` 或通过私有表格 CSS 覆盖；横向比较矩阵声明 `comparison-number`，其它差异新增稳定语义角色。空值、排序箭头、标签和加载状态不得改变该列基准线。
- 自适应列宽的角色、字符权重、控件预留、上限、对齐和数字排版唯一维护在 `components/table/adaptiveColumnWidth.ts`；页面只在动态标签无法推导时声明语义 `role`，不得复制数值或对齐 CSS。所有标准表头保持单行且不换行；日期、单位或短口径摘要使用 `header-meta` 在标签后同行弱化展示；主内容前存在紧凑控件时使用 `leading-controls` 让组件统一缩进表头并预留列宽。说明性长文本继续放 `HelpTip` / `HelpHint`，不得通过私有 header slot 拼接第二套样式。
- 表头保持稳定，分页、批量操作和关键筛选不被表体滚动带走。
- 不使用隔行变色作为默认识别手段；当前全局样式会取消 stripe 背景。
- 列宽按信息类型分配：编号、状态、日期、操作列稳定窄列；名称、标题、描述、备注更宽；数字列保持易比较。
- `data-table` / `wide-table` 的稳定字段只要支持排序，就必须同时支持列头直接排序和设置抽屉默认排序；分页表默认服务端分页与排序。只有具备明确规模上限、一次性返回完整结果的小集合才允许客户端分页与排序，且必须先对完整集合排序、再截取当前页，禁止只重排当前页。
- 多级排序统一按“全量一级、页内二级”解释：默认或用户选择的一级字段必须由接口对完整结果集排序；只在当前已加载页提供的其它候选字段属于二级排序，只能在一级值相同的分组内稳定排序，并在二级值相同时保留接口顺序。纯本地完整结果可在本地完成全部层级；禁止把打乱接口一级顺序的当前页排序展示成全量排序。存在业务分层的视图以分层键作为不可破坏的一级边界，例如连板天梯固定按连板高度分层，卡片自定义排序只作用于各层内部。
- `pageRegistry.componentMeta[slot].sortFields` 是可交互排序字段和默认排序候选的单一事实源；登记后该 slot 自动继承 `defaultSort`，页面表格必须把对应列接入 `sortable` / `@sort-change`。**反向契约**：页面列头可排序的字段必须登记进 `sortFields`，二者双向一致，由 `pageRegistry.spec.ts` 契约测试强制拦截漂移。
- 操作列、展开列、按钮列、开关列、多值标签组合列、长说明/详情文本列默认不排序；若业务需要排序，必须明确映射到稳定字段并登记到 `sortFields`。
- 操作列和列表项操作区优先单行可见；表格中 `label="操作"` 必须按动作密度显式声明 `action-compact`（单动作或仅“更多”入口，默认下限 96px）或 `action`（两个及以上候选动作，默认下限 144px），不得只靠标签推导；两档默认统一居中表头与单元格，宽度均可由当前已渲染行的最低可用组合向上扩展，但不参与表格富余空间分配。单动作最低完整显示该动作；多动作最低保留两个操作入口，可由两个直接动作或“首个直接动作 + 更多”构成，“更多”计作一个入口；除调用方明确把全部动作收进更多外，禁止退化为仅“更多”。行内按钮组优先使用 `AppRowActions`，普通操作使用常规正文色，禁用操作降为弱文本色并满足语义 token 规则定义的文字层级阈值；hover / focus-visible 只做轻量文字色反馈，不对整组做透明度显隐；操作过多时用轻量“更多”菜单、分组、详情入口或抽屉，不用多行按钮堆叠；超过最低组合后按操作列实际宽度尽量展示更多直接动作，放不下的按钮自动收进“更多”菜单，不硬截断；“更多”菜单不得引入重动画、布局跳动或遮挡表格内容，菜单命令仍消费 Element Plus 按钮的 disabled/loading 状态。业务事实字段不得使用含糊的“操作”标签冒充动作列，应改为“操作笔数”等准确名称并声明真实语义角色。
- 宽表通过表体横向滚动承载，不让整页横向滚动。
- `data-overview/assetTable` 保持单一 `wide-table` 主成长实例和内部双向滚动。其“全部 / DuckDB / PG / 规划中”场景只切换业务列，不创建并列表格：全部显示双库共同字段，DuckDB 承载数据源/业务日/鲜活度/质量，PG 承载归属/空间，规划中不展示物理统计。质量列中 `0` 表示已纳入质检且零问题，`—` 表示不适用或未纳入；字段展开区必须展示中文名/说明及其元数据来源。所有可显隐列登记在 `pageRegistry.componentMeta.assetTable.columns` 并消费既有 `hiddenColumns`；筛选只属于会话态。低高度由表体内滚承接，窄屏工具栏自然换行，字段展开区保持独立嵌入表并允许横向滚动。

#### 自定义顺序

- 用户调整条目先后次序统一使用 `AppReorderList` 的拖动把手与落点反馈，移除逐行上移/下移按钮；键盘通过空格拿起、方向键/Home/End 选择位置、空格或 Enter 确认，Esc 取消。表头按字段排序继续使用表格与 `AppSortControl`。
- 列表以稳定对象 key 标识新增、复制和已保存条目，禁止用列表下标承担身份；仅在所属完整集合或业务允许的组内重排，不能跨组改变业务类型。只读、归档、保存中禁止排序，单项不显示把手。
- 拖动预览不改写表单；松手提交当前列表的顺序，移出列表、指针取消、Esc、卸载或数据/权限变化均取消；长列表拖动接近滚动边缘时自动滚动。保存仍由所属业务流程负责，失败保留草稿，不暗示已保存。层级菜单使用 `AppReorderTree`，与列表共用 `AppDragHandle` 和 `useReorderInteraction`；只有允许的分组能接收子节点，禁止移入自己或后代。菜单保存互斥覆盖提交、重载和导航刷新；已就绪的鉴权快照用后台方式刷新导航，保留工作区，失败仍 fail-closed；排序失败读取服务端顺序；存在未保存属性或功能点编辑时锁定排序。只有受影响兄弟组重新赋顺序，其他菜单配置保持原值。

### 业务内容与技术详情

适用于标题、摘要、业务表格、状态、表单反馈与错误提示；审计、配置编辑/导入导出、指标开发和原始任务日志按下述技术查看边界承接。

- 业务内容必须先展示中文名称、当前结论和必要单位；对象、数组、条件树按领域转换为摘要、字段—值或列表，不直接输出 JSON、字典或隐式字符串。规则历史版本须保留参数、启停和条件关系等有效内容，不能靠删除内容实现简化。
- 已知枚举消费所属领域的名称映射；未知值显示“未识别类型/状态”等明确提示，不回显内部 key 充当业务名称，也不隐藏对应记录。展示转换不修改筛选键、定位标识或提交参数。空值、0、未记录、未采集、未检查分别表达，不显示 undefined、None、NaN 或对象占位。
- 失败反馈区分业务摘要、恢复动作与技术原因；接口软失败、任务失败和 HTTP 错误均适用。普通提示不承载 SQL、异常栈、原始对象和运行时英文错误；原始诊断保留在服务日志或具名技术详情，不得通过清空失败记录、伪装成功或统一成无数据来简化。
- 技术查看入口必须有明确用途，例如“原始配置”“原始诊断”或“任务日志”；普通业务区先提供可读摘要，必要原文再由展开/抽屉承接。审计上下文、配置路径、公式及证券专业标识可按任务保留；仅值本身使用代码字体。允许技术查看不等于允许整个页面默认展示代码结构。
- 普通错误消费 `utils/error.ts`；中文业务消息与未知枚举兜底消费 `utils/displayText.ts`，具体对象的转换与名称仍归所属领域。新旧诊断版本、未知类型、缺字段、零值、软失败和请求失败须有适用的定向验证；不得在共享展示外壳中猜测任意对象语义或逐页复制翻译规则。

### 统计摘要与下钻

本节适用于展示规模、覆盖、质量等信息的只读统计摘要；承担选择或编辑的卡片、图表行情读数遵循各自组件契约。具体页面的指标、口径与操作目的地由所属架构文档维护。

- 标题、主值与单位为第一层，至多一条核心状态为第二层；额外分项、日期与分母进入详情，说明入口按[提示契约](#提示截断与可访问名称)选择。数值按所属组件统一对齐并使用数据字阶、等宽数字，辅助状态使用 caption。不得用最长脚注决定整排高度，也不得以减少字阶替代信息分层。
- 只读统计卡外壳不承担隐形导航；有后续操作时使用具名入口，文字准确表达定位、查看或执行目的。没有业务动作时不强加按钮，同名入口不得随数据状态暗中切换目的；空态恢复动作须明确命名。
- 统计详情以 `AppDetailFields` 组织字段—值，口径备注与事实分开；不套用规则教学的问答结构。长内容按视口及界面比例约束，并由 `AppScrollArea` 内部滚动，末项和备注必须可达；不新增页面私有悬浮计时或监听。
- 日期、覆盖、鲜活度和质量状态分别表达，最大日期或零台账问题不能单独代表整体完整。指标的范围、统计单位和状态语义须可查；扫描台账与实时覆盖、估算与精确统计等不同口径不可混写为同一结果。
- 空间不足时按既有响应式策略重排或内部滚动，保留主值、必要状态及具名操作。收起的分项可由明确的详情入口恢复；沿用用户显示及列偏好，不通过断点改写配置。

### 四态反馈总则

页面和组件的数据反馈统一按 `ready / loading / empty / error` 四态处理，代码枚举以 `frontend/src/layout/schema.ts` 的 `COMPONENT_STATES` 为事实源。文档、`COMPONENT_CATALOG.defaultStates`、`LayoutComponentPreview` 和页面实现必须使用同一语义，不新增“暂无/失败/加载中”的私有视觉体系。

| 状态 | 中文口径 | 使用场景 | 组件和图标 | 文案模板 |
|---|---|---|---|---|
| `ready` | 价值态 / 有数据态 | 接口或本地计算已返回可行动内容 | 不额外加状态图标；价值由表格、KPI、图表、详情、状态 tag 自身承载 | 标题或摘要写清范围、日期、数量、来源，例如“2026-07-10 · 预设榜单 · 320 条” |
| `loading` | 加载态 | 首次加载、刷新、保存、运行、远程下拉 | 表格使用 `AppDataTable`；标准非表格异步区使用 `AppAsyncRegion`；只需单个阻断反馈时使用 `AppStateBlock loading`；按钮用 `:loading`；小型导航可用 Element Plus `Loading` 图标 | 页面级“正在加载{对象}…”，按钮级“{动作}中…”，下拉级“加载中…” |
| `empty` | 空态 | 请求成功但当前条件下没有可展示数据，或用户尚未完成前置选择 | 表格由 `AppDataTable` 承接；标准非表格区域由 `AppAsyncRegion` 承接；单个业务子状态用 `AppStateBlock empty`；底层 `el-empty.app-empty*` 不由页面重复拼装 | “暂无{对象}”“请选择{对象}”“运行后在这里展示{结果}”“当前条件无命中” |
| `error` | 异常态 / 无权态 | 主请求失败、局部依赖失败、403/权限失败、详情读取失败 | 标准非表格区域由 `AppAsyncRegion` 承接，单个阻断反馈用 `AppStateBlock error`；底层统一呈现警告结果。两变体二选一：**异常态**必须提供重试入口；**无权态**不提供重试（重试无意义），以「请联系系统管理员调整权限」说明不可重试原因（见 §312、§219；`AppStateBlock variant="permission"` 默认 `retry:false`） | 异常态“{对象}加载失败”+“请检查网络或稍后重试”；无权态“无权限{操作/查看对象}”+“请联系系统管理员调整权限” |

四态运行时入口按区域职责选择，不按页面偏好选择：

| 区域类型 | 必须优先使用 | 状态责任 | 不适用边界 |
|---|---|---|---|
| 标准数据表格 | `AppDataTable` | 组件根据 `loading + data.length` 分流首次骨架与已有表格遮罩，并承接分页和表格空态 | 不得再外套 `AppAsyncRegion` 或在页面重复写表格 loading/empty 分支 |
| 图表、摘要、树、详情、结果等标准非表格异步区 | `AppAsyncRegion` | 调用方提供 `loading + hasContent + error`，组件统一互斥渲染首次骨架、已有内容遮罩、空态和异常态 | 多个必需依赖需聚合、长任务存在额外业务状态、KeepAlive 仅做画布恢复等特殊生命周期可保留领域状态机，但必须复用 `AppStateBlock` / `AppStatusNotice` 的视觉语义并说明理由 |
| 整页首次初始化、单个阻断反馈或标准异步区内部的业务子状态 | `AppStateBlock` | 调用方明确声明单一 `loading / empty / error` 状态 | 不得用它在同一区域重新拼装一套“首次骨架 + 已有内容遮罩 + 错误 + 空态”标准分流 |
| 后台保鲜仍可安全使用缓存内容 | `AppStatusNotice` | 保持 `ready`，只说明降级原因和恢复动作 | 用户主动请求失败或内容已不可信时不得使用 |
| 按钮、远程下拉、小型导航、KeepAlive 画布恢复 | 组件自身 loading 能力 | 只反馈局部操作或生命周期，不改变所属数据区域顶层四态 | 不得代替主数据区域的首次加载、空态或异常态 |

`AppAsyncRegion` 不发请求、不缓存业务数据，也不自行判断内容归属。调用方的 `hasContent` 必须表示“当前区域此刻允许继续展示的可信内容”，不能机械等同于任意旧对象、任意非空数组或组件是否挂载：同一上下文刷新可保留当前内容；主数据范围切换必须先清空；同一列表内用户主动换行可显式保留最后一次成功图表到新响应原子替换；自动选首项、跨上下文恢复和最终空结果不得冒充已有内容。标准区域禁止继续手写与 `AppAsyncRegion` 等价的 `AppStateBlock + v-loading + v-if/else` 分流。

状态互斥与降级规则：

- 每个独立数据区域同一时间只能有一个顶层状态；`ready / loading / empty / error` 不得在同一区域并排或叠加渲染。刷新按钮的 loading、`v-loading` 遮罩等属于当前请求的操作反馈，不扩展顶层状态。
- 状态作用域按“最小可独立恢复的数据区域”确定。多个相邻面板因同一个请求、同一空集合或同一必需依赖失败时，在最近公共父级聚合为一个主状态；主从工作区不得在列表和详情两侧重复大图标、标题和主动作。次级区域确需保留上下文时只显示无图标短文案，不再生成第二个主状态。
- 同一工作区存在多个必需依赖失败时，优先聚合失败对象和一个恢复动作；可选依赖失败只贴近对应控件显示紧凑提示。不得让多个局部实体主按钮与页面主任务竞争。
- 首次进入或当前区域没有可复用旧内容时显示稳定骨架，不在空白内容上只放转圈遮罩，也不和 `empty` 同时出现；已有数据刷新过程中可以暂时保留旧 `ready` 内容并覆盖 `v-loading`，避免闪回空态，但请求失败后必须由 `error` 接管受影响区域并隐藏旧内容，不能继续显示“异常态 + 旧 ready 内容”。表格由 `AppDataTable`、标准非表格区域由 `AppAsyncRegion` 统一执行该分流，消费页不得重复实现。
- 全市场、自选、分组等主数据范围切换视为进入新上下文：必须先撤下上一范围的当前观察与图表内容，列表进入完整骨架加载态，分析区进入未选择空态或新对象首次加载骨架；即使新旧范围包含同一对象，也不得把上一范围图表作为可复用内容覆盖刷新遮罩。同一范围内的搜索、筛选、排序和分页仍属于已有内容刷新，请求期间列表保留现有数据并使用 `v-loading`，图表保持当前对象；新列表返回后，当前对象仍在结果中则保持不变，否则自动选择首个可用对象并以首次加载骨架加载对应图表；没有可用对象时必须清除旧观察与旧图并稳定展示空态。重复点击当前已激活对象保持幂等，不重新请求或重建图表。
- 同一列表上下文内仅点击另一行切换观察对象时，图表属于已有内容刷新：保留最后一次成功图表并使用 `v-loading` 遮罩，新对象成功返回后原子替换；不得先卸载画布再闪回横线骨架。该暂存只允许跨一次行选择请求，列表范围切换、列表最终为空或观察对象被清除时必须同步清空。
- `error` 不只依赖全局 toast；主内容、侧栏列表、详情面板、表格局部依赖失败时，失败区域必须留下页内错误态和“重试”或明确原因。
- 自动轮询、后台保鲜、偏好同步和参考选项同步失败，若当前缓存内容仍有明确来源且可安全继续使用，可以保持 `ready` 并使用 `AppStatusNotice` 说明降级内容与恢复动作；此时不得同时渲染整区 `AppStateBlock error`。用户主动刷新、筛选、分页、排序或切换主结果口径失败不属于该例外，必须由 `error` 接管受影响的主结果区域。
- 自动轮询必须有页面可见的等待说明和固定硬截止时间；服务端任务实例、请求 ID 或重试批次变化不得自动延长同一用户操作的截止时间。服务端返回失败、未就绪或中断终态后必须停止轮询并展示具体原因与可执行恢复动作，禁止失败任务被查询接口反复重建后让页面永久停留在 loading。
- 失败态操作必须真实对应恢复能力：有权限重新执行时使用“重新计算/重新执行”并进入该动作的确认与提交链路；只能重新读取服务端状态时使用“刷新状态”。禁止按钮写“重试”但实际只重复读取同一失败结果。
- 无权限是 `error` 的语义变体，运行时使用 `AppStateBlock state="error" variant="permission"`，不得扩展为第五种顶层状态。
- `empty` 表示“成功返回但无数据”，不能混用来表达接口失败、无权限或加载中。
- `ready` 必须呈现业务价值：至少有主体数据、摘要指标、当前过滤条件或来源说明之一；不要用大段说明文字替代真实数据展示。
- 四态切换不得改变外层 slot 的稳定尺寸；布局系统组件种类的 `loading-state`、`empty-state`、`error-state`、`skeleton` 只作为系统组件和预览语义，业务页面运行时优先复用真实组件和 Element Plus 状态能力。
- `AppStateBlock` 默认尺寸填充父区域并居中；局部反馈按空间使用 `compact`、`tiny` 或无图标的 `inline`，不将局部状态撑成整页。

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
- 编辑/保存型表单必须在数据回填完成或弹层打开后，以实际提交负载记录已保存基线；仅当当前提交负载与基线存在实质差异时启用保存按钮，提交函数还必须二次拒绝无变更请求。保存成功后更新基线，失败时保留当前编辑值和脏状态；创建型保存弹层以打开后的初始表单为基线。独立发布、启停、重置密码等本身会改变业务状态的命令不套用“表单未变更”判断；“保存并发布”“保存并启用”等包含保存语义的组合命令仍必须遵守变更基线。
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

### 动效与状态过渡

- 全站动效时长与缓动统一由 `styles/global.css` 的 `--app-motion-content`（180ms）、`--app-motion-page`（220ms）、`--app-motion-collapse`（200ms）、`--app-motion-distance`（4px）与 `--app-motion-ease` 管理；时长固定使用 ms，不作为页面配置或视觉预设字段。
- 工作区页面切换由 `WorkspaceRouteView` 消费 `directives/reveal.ts` 的 `vReveal`，仅在路径变化时对真实页面根节点短淡入并从下方 4px 归位；不增加布局外壳、不等待旧页离场、不改变 KeepAlive 身份、滚动位置或图表恢复逻辑。同路径 query 变化不重复播放。
- `AppAsyncRegion` 与 `AppDataTable` 共用 `vReveal`，从无内容进入有效内容时原位短淡入（初始透明度 0.35，避免整块突然消失），共享加载遮罩按相同时长淡出；同一区域已有内容刷新、轮询和数值更新不重播。错误和上下文切换立即撤下旧内容，禁止为离场动画延迟清除、双份叠放旧新数据或人为等待骨架播放完毕。
- `WorkspaceTabs` 的摘要行与页签同处横向栏，栏高直接切换到最终尺寸，禁止对高度做连续动画以免正文图表和滚动区逐帧重算；页签透明度和箭头旋转复用折叠时长与缓动，提供轻量收展反馈；页签沿用 `v-show` 保留实例，收起意图生效时立即设置 `inert` 和 `aria-hidden`，避免离场动画期间仍可聚焦或点击。快速反向切换交由 CSS/Vue Transition 接续，减少动态效果时即时完成，不增加计时器。
- `SettingsGroup`、`AppSummaryDisclosureCard` 复用 `ElCollapseTransition` 与 `app-motion-collapse`，正文折叠和箭头使用同一时长。保留原来的 v-show/v-if 生命周期，不因动效重置编辑值或改变懒挂载行为。
- `PageSegmented` 的常规分段保持选中底色渐变，tabs 外观通过单一下划线跟随受控选中值平移，复用内容时长与缓动；指示器不参与布局、不拦截点击，选项重排跟随真实选中值，无有效选中项时隐藏；tabs 消费点调整间距时使用 `--app-segment-gap`，使网格与指示器位置共用同一值，禁止页面新增私有切换动画。
<a id="菜单与交互卡片"></a>

- **菜单与交互卡片的反馈入口**：统一由 `styles/global.css` 的 `.app-interaction-target`、`.app-interaction-nav` / `.app-interaction-card` 和 `.app-interaction-content` 承载；侧栏组件库生成的下级分组标题使用同一共享选择器。颜色来源沿用§2，交互样式不得硬编码第二套明暗色值或依赖组件库默认悬停色。
- **普通、悬停与按下**：保留原尺寸、圆角、文字与语义底色；仅精细指针且支持悬停时，内容及卡片完整表面上移 `--app-interaction-lift`（2px），增强中性阴影和卡片边界。位移、颜色、边框和阴影过渡共用 `--app-motion-content`（180ms）与 `--app-motion-ease`，宿主颜色过渡统一消费`--app-interaction-color-transition`，包括承载卡片/指标的组件库按钮，按下保持悬停高度，仅收敛中性投影，松开不再次上浮；指针移出时由普通态平滑归位一次，移出后不保留按下投影，避免快速点击触发多次反向位移。选中变化只更新既有定位标记，不额外启动位移动画；不缩放、弹跳或循环。投影分别使用明暗主题下的 `--app-interaction-shadow` / 紧凑导航档 `--app-interaction-nav-shadow`，不混入强调色。
- **选中、焦点与不可操作状态**：悬停不改变真实选择；选中来源只消费现有路由或受控值，移开后归位并保留定位标记，悬停已选中项仍可浮起。键盘焦点使用2px主色内侧框，不依赖位移；委托卡片由宿主显示焦点，内部主选择按钮撤下组件库的重复焦点框，独立链接/帮助按钮仍显示自身焦点；禁用、加载及其后代不浮起、不新增悬停阴影，原有选中和语义反馈保留。无悬停设备取消位移与悬停投影，系统减少动态效果时同时取消过渡，保留即时颜色、边界和焦点反馈。
- **唯一表面与稳定命中**：宿主占位、点击区域、缩进和滚动位置固定，视觉层无指针事件。卡片宿主只保留透明边框占位，由唯一伪元素绘制背景、边框、内侧定位线及投影，并与内容同步上移，禁止固定宿主再画第二套轮廓。承载浮起卡片的滚动区必须为首尾卡片预留真实绘制空间，不能用 `z-index` 绕过滚动裁切。页面直属滚动区和弹窗正文统一在四向借用既有外部间距，并以 `--app-scroll-paint-gutter` 同量内距还原内容坐标；其他独立列表复用 `.app-scroll-paint-space`。普通边框同样受此保护，不以是否存在悬浮卡片作为启用条件。`AppScrollArea` 的实例默认变量通过低优先级 `:where()` 重置，不能因样式加载顺序压过调用方的内距与布局。响应式断点通过 `AppScrollArea.getContentWidth()` 使用扣除内距后的内容宽度；嵌套分栏工作区额外预留 `--app-border-raster-inset` 的细边绘制余量。`LayoutHost` 页面裁切边界同步扩展同量安全区，不改变原内容宽度、断点和弹层定位边界。导航投影不重复绘制边框；一级顶栏的紧凑背景面与焦点面也由伪元素承接，当前位置下划线固定在顶栏底部。

| 交互角色及使用位置 | 悬停 / 键盘焦点背景 | 选中或当前态 | 反馈边界 |
|---|---|---|---|
| 侧栏可点击入口、可折叠下级分组（`SideMenu` / `SideMenuItem`） | `--chrome-bg-soft-hover`，禁止使用基础表面 `--chrome-bg-soft` 代替 | 叶子使用`--chrome-nav-leaf-active-bg`及主色文字，不叠加常驻左边线，悬停/焦点改用`--chrome-nav-leaf-active-hover-bg`；父分组只增强中性文字 | 只移动图标/文字；分区标题及其蓝色圆点保持静态 |
| 双顶栏一级（`TopNavigation`） | 32px高的中性悬停/焦点面，使用`--chrome-bg-soft-hover`；宿主保持透明 | 保留原有主色图标框、加粗文字及顶栏底部下划线，不套二级选中框 | 点击区保持原位，紧凑面居中；下划线不随内容移动 |
| 双顶栏二级、工作标签（`TopNavigation` / `WorkspaceTabs`） | 普通项使用`--chrome-bg-soft-hover`，当前项保持中性选中底色 | 复用`.app-nav-context-entry`的高度与圆角；二级导航保留轻主色边框和底线，工作页签由连续底托承接并使用强中性边框、主色上沿与图标定位 | 移动标记内容；标签关闭按钮固定，键盘事件独立 |
| 顶栏下拉菜单（`TopNavigation`） | `--chrome-bg-soft-hover`，不得回落为组件库默认蓝色悬停/焦点底 | 当前叶子保留`--chrome-nav-leaf-active-bg`及主色文字 | 只移动内容；普通项悬停不改变真实路由 |
| 可点击卡片：天梯、指标模板、外观预设/导航选项、交易纪律规则选择（`LimitLadderCard`、`ConfigView`、`App`、`RuleMasterList`） | 保留自身基础或告警语义底色，仅增强边界、投影与浮起，不统一刷成菜单灰底；数据概览统计与问题卡为只读外壳，使用具名链接 | 具备选择语义的卡片使用`.app-interaction-card.is-selected`：主色边框、3px内侧线及`--app-interaction-selected-background`的6%浅底；悬停不加深选中底色 | 表面与标记内容同步浮起；金融涨跌和告警文字颜色保持原职责 |
| 连续行情对比指标（`MarketCompareMetricStrip`，消费于`StockAnalysisPanel` / `SectorsView`） | 普通项使用`--chrome-bg-soft-hover`；选中项保持`--app-interaction-selected-background` | 6%浅底与铺满单元格宽度的底线，不使用独立卡片外框、外投影或左侧线 | 只移动内容，保持连续分段栏结构 |

- **背景消费方式**：导航共用`--app-interaction-nav-hover-background` / `--app-interaction-nav-hover-color`，当前态只通过角色变量提供差异，统一规则覆盖组件库hover/focus默认色。卡片通过`--app-interaction-card-background` / `--app-interaction-card-border` / `--app-interaction-card-hover-border`保留各自语义；选中浅底与连续指标共用`--app-interaction-selected-background`，不复制局部透明度配方。
- **点击职责**：天梯卡片通过`.app-interaction-delegated`仅响应`.app-interaction-trigger`主选择区；底部板块链接与帮助入口独立，不触发卡片选择或浮起。其他卡片的内部链接、帮助按钮继续保留原点击边界，不因视觉层扩大父级点击行为。
- **排除范围**：侧栏分区标题、纯展示卡片、普通数据表格/列表行、图表/画布、命令按钮和紧凑筛选标签均不接入浮起机制。页面切换、异步内容、折叠、`PageSegmented`、弹窗/抽屉继续遵循各自既有动效规则，不套用卡片浮起；此处不表示全站所有历史动画均已迁移。
- **新增接入与验收**：仅同角色可操作入口复用以上class和变量，登记组件维护清单；不得给所有`.el-card`、按钮或菜单标题添加笼统悬停规则。定向测试覆盖选择与嵌套点击边界、禁用和共享角色消费；内置浏览器复核明暗主题、普通/悬停/按下/选中/焦点状态及滚动边界，未能模拟的输入媒体偏好需注明静态契约验证范围。
- “减少动态效果”来自操作系统辅助功能，由浏览器映射为 `prefers-reduced-motion`，不是应用新增设置；只降低运动呈现，不关闭加载状态、禁用状态或交互反馈。
- 动效只增强反馈，缺少 Web Animations API 时直接显示内容。系统 `prefers-reduced-motion: reduce` 下不播放上述淡入、位移、折叠和选中指示过渡，停止共享骨架动画；偏好在淡入中变化时立即取消动画，恢复正常可见内容。
- 不给行情数值、大表格行、K线或画布尺寸添加逐项进场、缩放或位移动画。不设置全局 `transition: all`；不使用常驻 `will-change`，动画结束、快速切换和卸载时释放资源。
- 此入口覆盖工作区页面、标准异步区域、分段控件、工作区栏与上述两类内容折叠；抽屉、弹窗继续消费组件库原生动效，其他历史局部动效尚不自动统一；菜单与交互卡片按本节单独列出的角色接入。

### 卡片、面板与分区

- `AppSummaryDisclosureCard`：规则、操作事实等“列表摘要 + 展开编辑”场景使用默认 `card`；只读检查清单使用 `variant="compact"` 的紧凑行，标题与附加摘要分列单行省略，保留完整原文并接入全局真实截断提示；状态通过 `leading` 插槽注入，无明细时传 `collapsible=false` 渲染静态摘要且不提供无效按钮；业务状态和命令通过插槽注入，组件不持有启停、删除或校验等领域逻辑；展开编辑区保持基础表面并用边框与主色边线表达层级，不使用常驻填充色形成嵌套色块；整块摘要使用带完整 `aria-expanded`、`aria-controls` 和可访问名称的专用原生 disclosure button，不得在消费页复制卡片结构。

- 卡片只用于承载独立数据块、表格容器、设置组、弹层内容，不把页面 section 都做成浮动卡片。
- 同角色普通与可浮起卡片的静止边框统一消费主题边框色，不叠加白色内阴影提亮顶部；悬停时才按交互规范增强边框与投影。
- 普通卡片圆角统一消费 `--layout-card-radius`，默认预设为 10px；设置抽屉和用户中心等浮层卡片可使用 12-16px。
- 普通内容卡片内距消费页面密度（紧凑 12px / 标准 16px / 宽松 24px）。独立主列表统一使用 `AppTableCard` 承接结果区外框：内容体无内距，表头与容器边缘、标题分隔线相接；标题与工具栏放在 header 插槽并保留内距，加载、空态、错误重试和分页必须位于同一外壳内，状态反馈和分页由组件保留空间。已有工作区卡片、`AppWorkspacePane` 或主从面板承接外围边界时，不重复套表格卡片；抽屉、展开行和局部明细表默认沿用所属容器。禁止使用页面私有表格外框或 `AppDataTable.framed`。混合说明、表单或图表的内容卡片不整体清零，禁止为贴边改写表格单元格内距。

### 弹窗与抽屉

- `AssetSearchDrawer`：公开资产页面统一消费，禁止私建同类选择器或搜索弹窗。资产浏览统一使用 `PageDrawer` 的 `xl` 语义宽度；从下拉选择器打开抽屉前必须先收起下拉浮层，禁止两个操作层重叠。无浏览权限时隐藏入口并显示明确无权态，不伪装成空态；加载查看默认不改变当前选择，需要外部展示时使用只读快照，只有“加载即展示结果”的场景才启用 `selectLoaded`。移除临时预览不等于删除资产，消费页必须同步清理对应请求和外部状态。mine-only 候选不显示“我的”，外部只读项保留来源；列表失败发 `loadFailed`，消费页结束等待并提供错误反馈和重试。mine ref 才进入选择器，系统或公开 ref 使用外部只读展示，不可解析时明示失效并阻止执行。具体 props、emits 和状态机以组件类型、实现及 `AssetProfileSelect.spec.ts` 为准。

- 弹窗/抽屉必须放在 `#overlays` 插槽。
- 破坏性确认使用 `ElMessageBox`；确认文案必须写清动作与对象，不用表单弹窗模拟二次确认。
- 短表单、单一信息组编辑和轻量查看统一使用 `AppDialog`，业务页面和业务组件禁止直接使用 `el-dialog`。语义宽度固定为 `compact=420px`、`narrow=440px`、`medium=480px`、`large=520px`、`xlarge=560px`、`max=640px`；仅图表、宽表等完整横向工作区可用 `workspace=min(92cqw, 1200px)`，普通表单不得借此拉宽。
- 完整对象详情、分段较多的编辑、历史版本和审计上下文统一使用 `AppDetailDrawer`；它负责标题、副标题、头部动作、四态、正文和 footer 的一致结构。业务详情按 `AppDetailSection` 分区，规则型键值展示使用 `AppDetailFields + AppDetailField`，键值网格支持 1–3 列并在窄容器自动单列，空值统一为 `—`，长值可跨列、代码值可等宽；不得复制私有详情网格或 `el-descriptions`。
- 数据结构体检及同类只读检查报告的展开布局统一为“检查摘要 → 数量/基准日 → 明细表 → 处理说明”。摘要复用 `AppSummaryDisclosureCard variant="compact"`，通过项静态行与可展开项保持同一对齐；明细复用 `AppDataTable embedded + AppTableColumn` 的语义列与 `small` 密度，每个对象占一行、字段名仅在表头出现，板块处置明细与 SQL 样例不得混用逐条字段卡、编号清单或私有表格。共同基准日只在表格上方展示一次，不同日期保留日期列；显示全量计数及实际样例数量，不能将样例数量当作异常总数。表格由 `embedded` 默认复用 `LONG_DOCUMENT_TABLE_MAX_HEIGHT` 限高，宽列在表内横向滚动，报告正文由共享抽屉滚动；处理说明位于明细之后。列出版本等长值时保留完整值的共享溢出查看能力，不靠缩小字号压缩。只有能精确对应台账的对象才提供定位链接。
- `AppDetailDrawer` 基于 `PageDrawer`。页面直接使用 `PageDrawer` 只限实时日志、资产搜索、页面设置以及主从工作区窄屏回退等具有专用交互模型的底层场景；普通详情不得绕过 `AppDetailDrawer`。
- 页面触发的抽屉遮罩和高度限制在当前 `LayoutHost` 内容区；只有应用顶栏触发的用户中心、外观等全局抽屉可以使用视口级浮层。
- Element Plus teleport 生成的浮层 DOM 必须使用唯一全局类或 `:global` 定位内部样式，不要依赖 scoped 深层样式碰运气。
- 复杂图表联动、宽表分析或跨模块工作流优先现有工作区、全屏抽屉或独立页面，不把完整工作台塞进普通弹窗。
- 可编辑字段只要提交、发布或后端校验不允许为空，对应 `el-form-item` 就必须显示必填标记，并与提交校验保持一致；条件必填项只在条件分支生效时标记，已有默认值不能作为省略标记的理由。只读展示、没有“空值”状态的开关和允许留空的字段不标记，禁止用红色星号表达推荐填写。
- 同一操作组内的同类任务必须采用一致的弹窗触发模型、对齐方式、footer 顺序和提交文案；只要同组任务需要在执行前展示参数，就统一使用参数弹窗，不得混用直接提交、`ElMessageBox` 和表单弹窗。
- 异步任务参数弹窗提交期间，主按钮必须有 loading 并阻止重复提交；提交失败时保留弹窗与已填内容，只有成功后才关闭。
- 抽屉正文可以内滚，但外层页面不能跟随滚动；footer 或关键操作应保持稳定位置。

弹窗文案容量规则（解决窄弹窗内占位/说明文字被截断）：

- 弹窗宽度只使用 `AppDialog` 语义档位，窄档位只放短字段；宽度不足时优先压缩文案、调整字段布局或改用 `AppDetailDrawer`，不靠继续加宽弹窗绕过。
- 控件内直接可见的提示文案（`placeholder`、单选/复选后缀）控制在 15 字以内；更完整的说明移出控件，按内容结构使用 `HelpHint` / `HelpTip`，常显字段说明及表单底部补充说明统一按下文「表单辅助说明」消费 `AppFormHelp`。tooltip 与 popover 的选型遵循[提示契约](#提示截断与可访问名称)，不受该可见文案字数边界约束。
- `AppSelect` / `AppFilterSelect` 等选择控件的占位只写「动作 + 对象」（如「输入代码或名称搜索」）；「可多选」「留空=默认值」等可操作语义放到字段辅助说明行，不拼进 `placeholder`，占位文案在输入框内不换行、不省略。
- 单选项文案过长时拆为「主文案（行内）+ 补充说明（辅助行）」，不让单选标签撑满或截断。
- 验收自检：弹窗内最宽控件的可用宽度 = 弹窗宽度 − 左右内边距（约 48px）− `label-width`；文案超宽就压缩文案或改布局，不能靠改 `width` 硬撑。
- 同页长说明分散到各字段且不重复；新写弹窗时优先复用字段内短占位 + 行内辅助说明的结构，不复制 `IngestView` 中已修正的长占位写法。

### 表单辅助说明

- 全站创建、编辑、任务参数及自定义字段区中的常显辅助说明统一使用 `AppFormHelp`，不局限于弹窗或数据管理页面。说明用于解释输入含义、允许范围、默认值、只读原因或操作后果；表单值、来源时间、选项描述、校验错误和运行状态不属于这一角色，沿用各自的值展示、选择器、表单校验及状态组件。设置抽屉继续使用 `PageSettingItem` 的共享帮助入口，浮层说明继续使用 `HelpHint` / `HelpTip`。
- 单行与多行使用同一规则，不根据字数或实际行数切换标记。组件自动生成一个中性色 `*`，调用方只传正文，不得手写星号、空格缩进或用换行决定是否显示标记。该星号不是字段必填标记，不参与可访问文本。
- 标记独立占列，正文占剩余宽度；自动换行后的每一行都与正文首字对齐，不回到星号位置，也不继承父容器的居中排版。字号/行高使用 caption 的 12px/18px，颜色使用辅助文字 token；确需提醒操作后果时声明 `tone="warning"`，仍保持同一排版。校验失败不得改成带星号的普通说明。
- 字段说明放在相应 `el-form-item` 控件下方，与控件列左边界对齐；多个字段共用的前置说明放在该组之前、由无标签的 `el-form-item` 保持控件列对齐。自定义字段区将说明放在对应控件容器下方；表单整体补充说明放在表单尾部。组件自身使用共享间距 token，调用方不得按 `label-width` 写死缩进或添加私有字号、标记、续行样式。
- 本规范由 `AppFormHelp`、组件测试和 `formHelpContract.spec.ts` 共同承接；共享入口改动需复核横向标签表单、顶部标签表单及窄视口长说明，并同步真实组件登记与响应式维护矩阵，不新增布局 kind 或用户配置字段。

### 设置抽屉

- 字段块由 `PageSettingItem` 承载，默认堆叠，开关或短数值可用行内布局；单块纯文本说明传 `hint`，由组件收成 `HelpHint`，结构化说明使用 `HelpTip` / `HelpTipItem`。主内容区配置分组由 `ConfigPanelSection` 承载，一级说明在组头，二级说明随内容收展；页面不复制字段布局。

- 页面设置抽屉三段**固定顺序**：`布局` → `组件设置` → `业务选项`；每段**仅在该页有对应内容时渲染**。`布局` 恒在，`组件设置` 仅当 registry 声明了可配置组件字段，`业务选项` 仅当页面提供 `#business` 插槽；不得为了形式完整强插空段。
- 抽屉三条配置通道按**属性所有者**划分，而不是按控件文案、出现页面或存储位置猜测：**布局段**收页面结构属性，凡是控制完整 slot / 模块是否存在、顺序、尺寸或密度的能力均登记为布局旋钮（例如 `slots.<slotId>.visible`），不得复制为组件内部 `config.visible`；**组件设置段**收当前页面已登记组件实例内部、可随该类组件复用的展示与交互默认能力——列显隐、默认排序、每页条数、组件内部区域高度、默认 tab、主从区宽度、分区内部字段集合、KPI 组内部指标项、日志详情自动滚动、快捷范围、多图组合与内部比例、默认数据粒度、组件内操作模式、联动工作台的默认模式与显示内容；字段能力由组件种类共享，页面专属取值按 `pageKey + slotId` 隔离，跨页面共用值则由字段声明的专用全局偏好承接，存储位置不改变组件归属。**业务选项段**只收由页面业务流程拥有的默认或偏好；页面主区对默认值的会话级覆盖不得登记为第二套持久化字段。判断顺序固定为：先判断是否改变完整 slot 的页面结构，是则归布局；否则再做替换检验——更换承载该能力的 Vue 组件后语义仍属于当前页面业务的，归业务选项，能力随组件实例一起成立或消失的归组件设置。不得仅因同一页面消费、字段名含“模式”或当前使用 `user_preference`，就把组件字段复制进 `usePageSettings`。
- `布局` 和 `组件设置` 由元数据自动渲染；`业务选项` 由页面声明。布局旋钮必须按 `EditableKnob.group` 进入二级章节，基础密度归“基础布局”，完整模块显隐归“模块显示”，不得随字段增长继续在一级平铺。组件配置不得通过业务插槽再次渲染或移动到业务段，避免同一字段出现双入口、双持久化和职责漂移。
- 设置项必须有默认值、来源展示、合法值域和重置路径；页面设置抽屉 footer 的「恢复默认」必须同时重置页面业务偏好、页面布局/组件用户层，以及抽屉自身尺寸和当前折叠态偏好。
- 「组件设置」段与系统管理→布局配置→**页面布局**编辑器的「组件特性」**共用唯一渲染器** `components/ComponentAutoSettings.vue`（抽屉=user 层、页面布局编辑器=page 层，经 `layer`/`slotIds`/`allowedLayersOf`/`collapsibleSlot`/`clearable` 适配），不得另写第二套组件特性表单。
- 配置面板的“默认折叠分区”按 `componentMeta.collapseSections.parentKey` 展示组/子分区层级；父组独立一行，只有同一父组下的同级候选可以并排并自然换行。整份候选清单及有子项的父组复用 `SettingsGroup` 折叠，无子项的候选不显示箭头；父组通过标题插槽保留复选框，复选框点击和键盘操作不得触发收展。清单展开态沿用抽屉折叠偏好，和业务默认折叠 key 列表分开管理。父子默认值独立选择，不做级联勾选；继续保存稳定 key 列表，切换当前页签的候选范围时保留隐藏项选值。
- 折叠记忆统一由 `useDrawerPreferences` 承接：三个一级分组跨页面共用；内部各级按 `pageKey + 稳定节点标识` 隔离，刷新、关闭后重开及缓存淘汰后均恢复。布局分组使用 `EditableKnob.groupKey`（存量缺省回退首字段路径），组件组使用 `slotId`，字段子组再加字段 key，业务分区必须声明同页唯一的 `PageSettingSection.sectionKey`；禁止用展示标题、数组位置或业务对象 ID 作为记忆键。记忆由 `PageSettingsDrawer` 提供上下文、`SettingsGroup` 统一读写，不逐页维护监听器，也不写进页面布局或业务默认值。批量操作与单节点操作同源；恢复默认同时清除全局一级状态及当前页面全部内部节点（含隐藏节点），其他页面内部记忆保留。按租户/用户隔离本地回退与待同步意图，串行保存，旧响应和快速刷新不得覆盖用户操作。其他容器的分组仍遵循各自调用方生命周期。
- 折叠规则统一：每个 slot 为可折叠组（`SettingsGroup` level 2；编辑器聚焦单 slot 时仅作标题锚点不折叠）；多行清单类特性（列显隐、默认折叠候选）为可折叠子组（level 3）；单字段为叶子不折叠。抽屉根按钮只控制一级组；任一 `SettingsGroup` 存在直接子分组时，必须由共享折叠树自动提供本层“一键收起/展开下级”，不得由页面手工维护子节点清单。父级操作不改写更深层状态；在已收起组操作下级控制按钮时先展开该组，让结果可见。所有可折叠节点统一使用箭头，二级及更深标题固定为 14px，并以缩进和结构线表达深度；事项统一由 `PageSettingItem` 或 `PageToggleRow` 承载。
- 设置抽屉中将页面当前会话值保存为默认或尺寸档案的操作，统一复用 `PageSettingsApplyButton`，视觉角色按按钮矩阵的语义轻量角色接入（`primary + plain`），整行宽度；不得在字段组件内复制颜色、宽度、边距或保存状态样式。当前页面值与已保存载荷无实质差异时禁用，提交函数二次拒绝无变化请求；按钮 `loading` 必须覆盖真实持久化周期并阻止重复提交，在请求的成功或失败分支统一释放；保存失败统一通过 `ElMessage.error` 明确提示并保留当前值供重试。普通编辑与恢复默认保持中性，危险操作才使用 `danger`。采用入口紧跟对应字段，不额外展示工作区像素、匹配阈值或档案清单等实现细节。
- **页面可改动属性单向默认机制**：抽屉/组件配置层只提供**默认值**，页面主区可直接交互改动的属性必须用独立会话 ref 承载；重复的默认值投影统一复用 `composables/useDefaultedSessionValue.ts`，组件配置分页统一经 `composables/useComponentPageSizeSession.ts` 完成默认值解析、会话投影、归页和重载，**页面改动只进会话态、绝不写回默认值**——刷新/重进页面后重新应用抽屉默认。这样「默认」才有意义：用户临时改动不污染长期偏好。禁止可写 computed 或主区 `v-model` 直写持久层；设置抽屉内的默认值编辑，以及带有明确“设为默认”语义的显式操作，才是默认值持久化入口。初始化优先级固定为：先完成页面业务偏好与远端布局默认值水合，再应用 URL query、返回列表态等显式会话恢复，最后才接受用户交互；迟到的默认值不得清除已经恢复的显式会话覆盖。URL query/分享链接恢复只写会话 ref，不触碰默认。**会话态清单**（本就该会话级、也不进抽屉）：纯查询条件（关键字/日期口径/方案选择）、业务资产选择、运行参数（如回测日期、所选方案和当次执行参数）。
- **新增属性登记判断（开发闭环必经步骤）**：新增页面、改造页面或给页面/组件新增任何可交互属性后，必须逐一回答三个问题再收尾——①该属性是否需要跨会话记住（默认值/偏好）？②需要时登记到哪条链路（业务偏好进 `usePageSettings` defaults + `#business` 插槽；组件展示字段按 §7.3 进 `COMPONENT_FIELD_DEFS`/后端规则，页面 slot 自动继承，仅候选或实例例外进 `componentMeta`）？③需要默认值时页面是否已按上条单向机制消费（读默认初始化会话 ref、不写回）？三问任一答「是」却未落地，即视为本次改动未完成。反向同样成立：不再需要或语义失效的已登记项必须及时下线，不得在抽屉里堆积死项。

## 5. Layout Principles

所有业务页面走可配置布局系统：页面声明 `PageLayout`，通过 `<LayoutHost>` 渲染，不手写 `.v-page` / `.v-grow` / 视口高度。配置合并顺序固定为：

`default < page < user`

| 层 | 职责 | 维护入口 |
|---|---|---|
| `default` | 页面原型、slot、组件代码默认值 | `frontend/src/layout/pageRegistry.ts`、组件代码 |
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

列表页的搜索/筛选交互行统一用卡片边框承载：`<el-card shadow="never" class="filter-card">` 包裹 `AppControlRow` 或 `AppAdvancedSearch`，`filter-card` 使用全局样式（`margin-bottom: 0`，卡片体内边距 `var(--app-density-card-padding)`）。禁止搜索行裸 div 无边框散落在页面。工具栏/操作按钮行不强制套卡。

### 5.1.2 页面间距承载

页面标题行到主内容区的间距由布局系统统一承载，页面禁止叠加私有间距：

- 操作区内块间距 = `.lh-action` 的 `gap: var(--app-density-section-gap)`，标准档 12px。
- 页面级间距 = `.v-page` 的 `gap: var(--layout-page-gap)`，该变量是 `--app-density-page-gap` 的兼容别名，标准档 12px；视觉预设不得覆盖。
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

### 5.5 共享工作区与尺寸档案

- `AppWorkspacePane`：个股查询、每日榜单、连板天梯、板块行情通过 `MarketMasterDetailWorkspace` 共同消费，个股详情与板块详情直接用于各自两栏；栏级标题统一高度、边框和间距，次要文字色的小号辅助行承载稳定的业务类型，当前日期或结果批次作为主标题展示；主次栏头统一消费 `--el-bg-color` 内容面，不提供主色背景变体，禁止由页面复制背景样式；不与图表内部 `StockChartPanelHeader` 合并；图表范围、分栏收展等栏级操作通过 `actions` 插槽承载；紧凑抽屉已有标题时可隐藏重复栏头。

- 通用左右分栏由 `AppSplitWorkspace` 承接；行情列表与分析区由 `MarketMasterDetailWorkspace` 组合。两栏各自内滚，列表不足时区内横向滚动；工作区布局宽度不超过 `720px` 时回退列表单区，由共享全屏抽屉展示分析区，抽屉填充与基础内距也归共享组件。
- 独占页面主内容区时使用 `fill`；作为长文档末段时使用 `adaptive`，余量足够时填满剩余空间，不足时守住常规 `480px` / 紧凑单区 `400px` 下限并由外层滚动。`RankedStockWorkbench` 默认 `adaptive`，仅独占主区时显式改为 `fill`；尺寸常量统一来自 `marketWorkspaceSizing`，页面不复制高度公式或让结果行数撑高工作区。
- 列表宽度默认 `45%`、允许 `30%–70%`，只有列表至少 `360px`、分析区至少 `240px` 的安全边界冲突时才偏离比例；不设列表固定像素上限。实际栏宽、上报比例与保存样本必须一致。
- 拖动/键盘只改会话值；采用当前比例时同时保存默认值和 `{width, ratio}` 档案，直接编辑占比也同步当前有效宽度档案。控件回显默认值或匹配档案经安全边界调整后的基线，拖动样本不提前覆盖它；无有效样本时回退默认值。当前宽度位于档案 `±15%` 内时取相对差最小项，`5%` 内更新原项，无匹配时回退默认；双击恢复当前匹配或默认比例，旧 `masterWidth` 仅兼容读取。
- 股票多图纵向比例按 `pageKey + slotId + 图表组合` 隔离，主从分栏中使用外层工作区 CSS 宽高作为档案尺寸；右栏自身尺寸只用于重绘与面板最低比例，左右分栏变化不能切换纵向档案。独立图表才使用自身 CSS 宽高，禁止使用物理屏幕尺寸。宽高均在 `±15%` 内时取综合距离最近项，`5%` 内覆盖原档案；无匹配时使用组合默认比例，不匹配旧右栏基准档案。
- 多图比例控件回显经最低高度调整后的配置基线；拖动只更新待采用值，显式采用才保存 `{width, height, ratios}`。直接编辑一个比例时其余可见面板平分剩余比例，合计 100%，并同步默认值和当前有效尺寸档案；尚无有效宽高时禁用采用入口。匹配算法、容差与数量上限复用公共尺寸档案能力，消费页只转发尺寸事件。
- 固定行情区通过 `chart.minHeight` 配置高度；随视口填充的个股/板块详情与主从工作台不使用固定高度字段，应显式启用可用高度适配和共享紧凑下限。其它图表以可见面板最小高度之和加分隔线作为硬下限。复权、查询范围等业务口径不并入 `chart.stockChart`，会话与默认值的通用规则见[设置抽屉](#设置抽屉)。

## 6. Depth & Elevation

层级主要通过背景、边框、轻阴影和密度表达，不使用强装饰和多层浮动卡片。

| 层级 | 表达方式 | 使用场景 |
|---|---|---|
| 页面底 | `--el-bg-color-page` | 工作区背景 |
| 基础表面 | `--el-bg-color` / `--chrome-bg-soft` | 卡片、表格、普通输入框；抽屉及其一级设置组通过 `--page-settings-bg` / `--page-settings-section-bg` 映射到同一 `surfaceBg` |
| 分区表面 | `--app-section-bg` | KPI、指标标签格、查询摘要、主内容区普通配置标题等内部信息区 |
| 浮层 | `--el-bg-color-overlay`、遮罩、边框 | dialog、drawer、popover |
| 强浮层 | `box-shadow: 0 10px 30px ...` | 页面设置抽屉、用户中心 |

规则：

- 普通卡片和控件圆角分别消费 `--layout-card-radius` / `--layout-control-radius`，默认预设分别为 10px / 6px；抽屉卡片可到 16px。
- 卡片主体、抽屉及抽屉一级设置组使用内容面；主内容区普通配置标题等内部信息区可使用分区色，保留共享组件已有的透明混合。`ConfigPanelSection` 的组头与 `SettingsGroup` 的一级卡片按各自职责消费，不将“配置分组”笼统视为同一种背景；更深层分组不强制增加底色，可用标题、缩进和分隔线区分。
- 业务页面不通过多层阴影表达层级，优先用边框、间距、标题和背景差异。
- 弹窗遮罩保持轻压暗，不能让背景表格干扰当前任务。
- 高对比预设必须提高边框和文字对比，而不是仅加深背景。
- 共享边框角色由 `themeSurfaces.ts::themeBorderVariables()` 提供，包含常规、分隔、强边框、选中及语义状态边框；`useLayoutPreset.ts` 统一同步组件库边框。背景仍按本节原有层级和 §2 维护。

## 7. Do's and Don'ts

### 7.1 必须遵守

- 所有 registry 业务页面必须走 `<LayoutHost>`。
- 新页面必须使用脚手架或 `pageRegistry.ts` 中的 `PageLayout` 单一事实源。
- 主数据区优先占据可用空间，表格表体内滚，分页和关键操作稳定展示。
- 所有滚动祖先保持 `min-height: 0`。
- 页面和主要组件必须声明 `ready / loading / empty / error` 四态处理；空态、错误态和加载态不得用彼此替代。
- 列表页分页/排序默认走服务端；具备明确规模上限且一次性完整加载的小集合可采用客户端分页，但必须先全量排序再切页；筛选变更自动触发；多选跨分页/搜索累积。
- 标准命令、纯图标操作、列表筛选、关键字搜索和日期选择必须复用 §4 登记的统一控件入口；具体 props、状态、事件和降级行为以“真实复用组件清单”、组件类型与测试为准，页面不得私建平行实现。
- 页面主体字体、字号、行高、字重和间距必须优先消费 `global.css` 的 `--app-font-*`、`--app-line-height-*`、`--app-space-*` token 或 `.app-*` 语义类；新增 px 值必须属于文档允许的局部特例。
- 说明性文字必须使用 §3 定义的统一说明入口，不在页面堆放长文或复制私有提示结构；具体承载方式以真实复用组件清单为准。
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
- 禁止绕过 §3、§4 与真实复用组件清单登记的统一控件、图标和说明入口，创建页面私有的平行实现；具体组件选择、可访问性、状态与结构约束以对应章节、组件类型和测试为准。
- 禁止使用 Unicode / emoji 冒充交互图标，禁止通过永久渐变、内阴影或大胶囊等装饰制造无业务语义的常驻层级。
- 禁止新增未登记的普通文字字号、游离字体族和随机间距；禁止把登录页、品牌字标、图表 tooltip 的特殊排版复制到业务页面。

### 7.3 组件特性配置治理

组件配置路径固定为：

`slots.<slotId>.config.<field>`

字段事实源为 `COMPONENT_FIELD_DEFS`。它描述组件 kind 真实支持的属性；页面只要登记该 kind 的 slot，就按 `default < page < user` 自动继承适用字段，禁止再维护逐页字段白名单。新增字段必须同时满足：

- 字段在 `COMPONENT_FIELD_DEFS` 中声明 label、control、layers、默认值和值域。
- `componentSchemas.ts` 接受该字段。
- 后端 `layout_config.py` 同步字段规则和归属校验；同名字段在不同组件种类中值域不同时，静态值域必须按 `(component kind, field)` 维护，不得只按字段名合并。
- 字段必须能由 `ComponentAutoSettings` 的通用控件安全渲染，或登记到专用动态候选渲染器；自动继承但没有安全控件的字段由组件配置契约测试直接拒绝。
- 适用性为 `always` 的字段自动进入每个同 kind slot；候选型字段由 `componentMeta.columns/sortFields/tabs/collapseSections` 有值时自动启用；结构型字段由 slot `config` 声明，例如 `pagination: true` 启用 `pageSize`。
- 实例明确不适用时必须在 `componentMeta.fieldApplicability[field]` 设置 `enabled: false` 并填写原因；不得以“没登记”隐式漏掉字段。
- 页面通过 `componentMeta` 提供安全枚举（列、可交互排序字段、tabs 等）。
- `componentMeta.columns` 只声明列显隐候选，不负责生成业务表格列；每个候选 key 必须在消费页面进入真实显隐判断并控制对应列或列内业务片段。该正向消费关系由 `pageRegistry.spec.ts` 契约测试强制，禁止“设置里可勾选、页面没有可渲染节点”的假配置。
- 页面实际读取并应用字段值。
- 复合业务组件若封装了多个可配置系统组件实例或承接页面业务口径，必须暴露并由消费页显式填写 `registryPageKey`（或等价的机器可读页面标识），并登记到 `layout/compositeComponentContracts.ts`；该契约声明必需子 slot、字段和运行时绑定。影响结果或展示口径的页面偏好统一登记到 `layout/pageBusinessPreferenceContracts.ts`，通用测试从每个直接或间接消费点反查默认值、抽屉控件与动态 prop 传递；中间组件的业务口径 prop 必须为必填且原样透传，禁止内部写死。只校验“已登记字段是否被消费”不够，因为它无法发现整个 slot 或业务偏好从未声明。
- 配置中心和设置抽屉共用 `ComponentAutoSettings`，且同时受字段代码最大层级与管理员当前开放策略限制。
- 普通页面从 `/layout/effective/{pageKey}` 一次获取 page/user 层和字段开放策略，前端结合本地 default 做三层合并；历史上已存但现策略禁止或实例不适用的值必须丢弃。
- `useRemoteLayoutConfig` 返回的 `componentAllowedLayers` 必须传入 `PageSettingsDrawer`；页面脚手架和 `pageRegistry.spec.ts` 同时守卫该接线，禁止只在配置中心消费管理员策略。
- 测试覆盖自动继承、实例适用性、代码默认/页面/用户合并、策略收紧、越权、类型和值域。

当前受控字段摘要：

下表只记录字段和开放层级；消费页面、slot、候选列、排序字段和 tab 项不在 DESIGN 手写维护，统一以 `COMPONENT_FIELD_DEFS`、slot `config` 和 `componentMeta` 为准。`pageRegistry.spec.ts` 校验每个适用字段都被页面真实消费，且明确例外都有原因。

| 组件 | 字段 | 层级 | 归属事实源 |
|---|---|---|---|
| `filter-bar` | `commonFields` | page/user | 候选为 `componentMeta.searchFields`，默认组合在 slot.config；不足三个有效候选时运行时不提供编辑入口 |
| `data-table` | `border` | page | 全部 `data-table` slot 自动继承；页面需实际消费 `tableBorder(slotId)` |
| `data-table` | `pageSize` | page/user | slot `config.pagination=true` 时自动启用 |
| `data-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `data-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `wide-table` | `border` | page | 全部 `wide-table` slot 自动继承；页面需实际消费 `tableBorder(slotId)` |
| `wide-table` | `pageSize` | page/user | slot `config.pagination=true` 时自动启用 |
| `wide-table` | `defaultSort` | page/user | 候选排序字段以 `componentMeta.sortFields` 为准 |
| `wide-table` | `hiddenColumns` | page/user | 候选列以 `componentMeta.columns` 为准 |
| `section` | `visibleIndicatorFields` | page/user | 仅由指标快照分区明确开放，候选字段由受控组件定义提供 |
| `chart` | `minHeight` | page/user | 图表 slot 以 `config.minHeight` 明确开放；自适应高度的工作台通过 `fieldApplicability.minHeight` 明确关闭并说明原因 |
| `chart` | `klineRangePreferences` | user（全局偏好持久化） | 含 `config.stockChart` 的 K 线工作区自动启用；组件设置统一编辑跨页面共享的 K 线快捷范围与默认范围 |
| `chart` | `stockAnalysis` | page/user | 联动股票走势工作台以 `config.stockAnalysis` 明确开放；默认模式、显示状态、对比周期、指数和指标统一由组件设置生成并单向投影到会话态 |
| `chart` | `sectorAnalysis` | page/user | 联动板块走势工作台以 `config.sectorAnalysis` 明确开放；使用独立板块指标模型，默认模式、显示状态、对比指数、指标和周期由组件设置生成并单向投影到会话态 |
| `tabs` | `defaultActive` | page/user | 仅在页面登记 tabs slot 且 `componentMeta.tabs` 提供候选时渲染 |
| `settings-drawer` | `size` | page/user（全局偏好持久化） | `supportsPageSettings !== false` 的 registry 页面共享 `settings` overlay slot；具体 slotId 不作为存储判定条件 |
| `settings-drawer` | `bodyScroll` | page | `supportsPageSettings !== false` 的 registry 页面共享 `settings` overlay slot |
| `config-panel` | `collapsibleSections` | preset/page | `config-system.configPanel` |
| `config-panel` | `defaultCollapsed`、`showGroupDescription`、`showSectionDescription` | page/user | `config-system.configPanel`、`trade-discipline.stockConditions`（仅默认折叠适用）；分区候选以 `componentMeta.collapseSections` 为准 |

`usePageSettings` 只保留页面业务偏好，不承载通用组件展示能力。
`settings-drawer.size` 与 `chart.klineRangePreferences` 的字段元数据将 `userPersistence` 标为 `global-preference`，分别由对应专用全局偏好承接。后端布局写接口按 `(component kind, field)` 反向拒绝它们进入 `layout_user_config`，不绑定具体 pageKey 或 slotId。`settings-drawer.bodyScroll` 只能由 page 层控制。折叠能力固定开启，不开放 `collapsibleSections` 或 `defaultCollapsed` 配置；实际交互状态以内部 `collapsedSections`（全局一级）和 `collapsedGroups[pageKey]`（页面内节点关闭清单）用户偏好保存，旧 `defaultCollapsed` 偏好仅兼容读取，新写入不再产生旧字段。其他未声明 `userPersistence` 的 user 字段默认写页面布局用户层。
页面可改动的组件字段，组件配置层只提供默认值，页面读默认初始化会话态、改动不回写，规则见「设置抽屉」节「页面可改动属性单向默认机制」。

### 7.4 页面 / 组件 / 布局变更维护闭环

具体维护矩阵、计划块和验收命令统一维护在 `agent-works/configurable-layout-system/page-template.md`。本节只保留长期规则：

- 页面、布局原型、系统组件种类、组件字段、真实复用组件、按钮图标体系或业务偏好发生变化时，必须同步对应代码事实源、页面消费事实源、文档入口和测试。
- 非公开 View 路由、`pageRegistry` 和页面登记 marker 必须以 `pageKey` 双向一致；registry 页面必须真实渲染 `LayoutHost`、通过 `getPageLayout` 消费布局，并按四态入口矩阵实际渲染 `AppDataTable`、`AppAsyncRegion` 或 `AppStateBlock` 中至少一种标准运行时状态入口，禁止把直接使用 `AppStateBlock` 固化为所有页面的唯一接入方式。
- 已有稳定真实实现的系统组件种类必须由消费页面实际导入并渲染对应复用入口；当前强映射包括 `data-table` / `wide-table` → `AppDataTable + AppTableColumn`、`settings-drawer` → `PageSettingsDrawer`、`config-panel` → `ConfigPanelSection`（系统字段表单由 `ConfigGroupForm` 承载；交易纪律由 `StockRuleChecklistEditor` / `StockRuleConditionChecklist` 承载）。`toolbar`、`section`、`tabs` 等组合型种类不要求虚构一对一空壳组件。
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
- `pageRegistry.responsiveProfile` 是页面类型的目标响应式画像，用于说明设计意图，不等同于已完成浏览器验收；实际列数和重排由 `layout.responsive` 决定，运行时滚动由 `LayoutHost` 决定，最终可用性以关键视口浏览器实测为准，Playwright 仅在满足 E2E 准入时使用。页面布局工作台必须显示为“目标响应式策略”，不得把画像名称当成已验证结论。
- 页面布局工作台的结构预览只负责表达页面区域、组件位置和当前选择，配置统一在右侧检查器完成；预览宽度不属于配置。三档宽度列数完全一致时隐藏切换控件并直接说明结果，只有列数确实变化时才显示包含宽度和列数的选择项。响应策略、重排边界和档位结果各保留一处，禁止重复堆叠摘要；配置依据与诊断默认折叠，不与主要编辑项争夺层级。
- 响应式配置必须有 `minWidth=0` 的基础断点。
- 单个大表、大图、大列表不靠多列重排解决高度问题，优先内部滚动。
- 主从布局两侧都是表格、图表等主内容区时，默认分栏必须按容器比例连续计算并设置双侧最小可用宽度与配置比例上限，禁止用单侧固定像素上限让跨屏占比失衡；导航树、索引栏等语义窄栏可以固定宽度，但必须具备窄屏折叠、转单列或滚动兜底。
- 多组件平级块只有在都允许重排、无强阅读顺序且最小宽度满足时才进入 `columns`。
- `workbench` 类页面采用固定分析块 + 主成长区，放不下时由主区域兜底滚动。
- 抽屉宽度使用 `PageDrawer` 的受控档位：`xs=280px`、`sm=320px`、`md=360px`、`lg=440px`、`xl=560px`、`xxl=clamp(640px, 60%, 820px)`、`wide=clamp(560px, 46%, 760px)`、`full=100%`。`xs` 用于只含少量短选项的局部工具，`wide` 用于需要横向阅读且应随内容区增长的场景，`xl/xxl` 用于复杂详情，`full` 只用于窄屏承载与桌面同等复杂的工作台。所有档位只铺满 `LayoutHost` 页面区域，不覆盖应用顶栏和导航；业务页面不得私传 px 或百分比，页面设置抽屉只开放 `sm/md/lg`。
- 弹窗和抽屉允许 `max-height` 作为视口安全上限，但不能用视口高度驱动页面主体布局。

### 8.1 信息优先级与降级契约

新增页面和影响布局的改造必须在开发计划中逐区声明核心内容、辅助内容、触发条件、降级行为、恢复入口与滚动归属，按 `page-template.md`「响应式设计」执行；不得仅填写 `responsiveProfile` 或“自适应”作为完成结论。规则适用于手写页面和脚手架页面。

| 内容层级 | 空间不足时的要求 |
|---|---|
| 完成主流程必需的操作、当前对象、关键业务值、错误与恢复入口 | 必须保持可达；允许换行、区内滚动或转入有明确入口的工作台抽屉，不得直接隐藏 |
| 热点、指标摘要、次要筛选、辅助分析区 | 优先减少常显数量、折叠或转详情；折叠必须有具名且可键盘操作的展开入口，生效筛选需仍可识别 |
| 辅助说明、重复控件标签、补充描述 | 可以截断、隐藏或放入帮助/详情；隐藏后控件仍须具备可访问名称，不得丢失唯一业务信息 |

降级改变展示方式，不改变查询口径、筛选值、当前选择或输入草稿；不得为适配而重挂载有状态控件或额外发起查询。空间恢复时自动恢复合适的布局；用户主动展开的辅助区域不因一次尺寸变化被强制重置，必要时通过受控内部滚动承接。禁止通过无限缩小字号、裁切主内容或整页横向滚动掩盖布局问题。核心表格列优先排序、次要说明省略或进详情，超出容量由表格内部横向滚动承接；不自动修改用户保存的列显隐偏好。

### 8.2 已有组件的降级规则

完整触发清单统一维护在 [响应式组件触发清单](agent-works/configurable-layout-system/responsive-components.md)，逐项覆盖所有 Vue 文件（包括无自身断点、自然换行、内部滚动、委托共享组件及页面私有片段）。组件阈值、降级方式、恢复入口和直接消费方以该清单及真实代码为准，页面不复制断点。

尺寸均为缩放后的布局 CSS 像素；应用画布、局部工作区和控件自身容器的尺寸不可混用。页面当前验收矩阵、实测范围与覆盖缺口见 [响应式页面检查](agent-works/configurable-layout-system/responsive-pages.md)；仅更新受影响行，不追加历史流水账，登记完整性不能代替实测。

### 8.3 响应式交付门禁

- 页面开发必须复用 `LayoutHost`、登记 `responsiveProfile` 和有 `minWidth=0` 基础断点的 `layout.responsive`；登记完整性与布局合法性由现有 registry/validator 测试约束。
- `scaffold-page` 自动生成独立的 `responsive-review-pending` 标记；接入业务组件后仍须按模板完成响应式设计与关键视口实测，留下具体结论后替换标记。`layout-contract.spec.ts` 拒绝带标记的页面交付。手写页面同样执行模板，不得跳过复核。
- `typography-spacing-system.spec.ts` 扫描所有 Vue/CSS 的尺寸媒体查询（包含范围语法），`layout-contract.spec.ts` 检查主体高度、布局入口和统一分页。机器测试不能证明内容优先级合理或真实渲染不溢出。
- 新增/删除 Vue 文件、改变响应式查询或降级语义必须更新完整组件清单；`responsive-inventory.spec.ts` 检查文件、页面记录覆盖及 CSS 查询双向一致。JS 阈值、业务优先级、恢复与状态保留由人工和定向验证承担。
- 视口复核按模板进行，交付分别列出定向测试、浏览器实测及未验证项。普通临时复核使用内置浏览器，Playwright 仅按 E2E 准入规则执行，不要求每个新页面新增 E2E。

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
| `screen` | `ScreenView`（策略筛选） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / main:`wide-table` / main:`chart` |
| `stocks` | `StocksView`（个股查询） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`wide-table` / nested:`wide-table` / nested:`chart` / footer |
| `data-quality` | `QualityView`（数据质量） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `data-schedule` | `ScheduleView`（任务调度） | `list` | `density` | action:`toolbar` / main:`data-table(growMain)` / overlay:`detail` |
| `data-ingest` | `IngestView`（数据采集） | `workbench` | `density` | action:`toolbar` / main:`section` / main:`tabs(growMain)` / nested:`data-table` / nested:`data-table` / overlay:`form` / overlay:`form` / overlay:`detail` |
| `data-overview` | `OverviewView`（数据概览） | `workbench` | `density` | action:`toolbar` / main:`kpi-grid` / main:`stat-strip` / main:`tabs` / nested:`wide-table` / nested:`data-table`  / nested:`filter-bar` |
| `backtest` | `BacktestView`（策略回测） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`chart` |
| `training` | `TrainingView`（盘感训练） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / nested:`chart` |
| `trade-discipline` | `TradeDisciplineView`（交易纪律） | `workbench` | `density` | action:`toolbar` / main:`tabs(growMain)` / nested:`section` / nested:`section` / nested:`config-panel` / nested:`data-table` / overlay:`detail`  / nested:`filter-bar` |
| `stock-detail` | `StockDetailView`（个股详情） | `master-detail` | `density`、模块显隐 | action:`toolbar` / main:`master-detail` / nested:`chart` / nested:`section` / nested:`section` / nested:`section` / nested:`section` / nested:`section` |
| `config-score` | `ConfigView`（评分规则） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`data-table` / main:`master-detail` / nested:`wide-table` / nested:`chart` |
| `config-trade` | `ConfigView`（买卖指标） | `workbench` | `density` | action:`toolbar` / main:`section` |
| `config-tech` | `ConfigView`（技术指标） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`filter-bar` / nested:`data-table` / overlay:`form` |
| `config-system` | `ConfigView`（系统设置） | `workbench` | `density` | action:`toolbar` / main:`section` / nested:`tabs` / nested:`config-panel` / nested:`data-table` |
| `user-manage` | `UserManageView`（用户管理） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `role-manage` | `RoleManageView`（角色管理） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` |
| `menu-manage` | `MenuResourceView`（菜单与功能） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`wide-table` |
| `tenant-manage` | `TenantManageView`（租户管理） | `list` | `density` | action:`filter-bar` / main:`data-table` |
| `layout-presets` | `LayoutPresetsView`（视觉预设） | `list` | 暂无 | action:`toolbar` / main:`data-table(growMain)` |
| `layout-pages` | `LayoutPagesView`（页面布局） | `workbench` | 暂无 | action:`toolbar` / main:`tabs(growMain)` |
| `layout-components` | `LayoutComponentsView`（系统组件） | `detail` | 暂无 | action:`toolbar` / main:`section` |
| `audit-log` | `AuditLogView`（审计日志） | `list` | `density` | action:`toolbar` / main:`kpi-grid` / main:`filter-bar` / main:`wide-table` / overlay:`detail` |
| `data-dictionary` | `DataDictionaryView`（数据字典） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`simple-list` / nested:`data-table` / overlay:`form` / overlay:`form` / overlay:`dialog` |
| `sectors` | `SectorsView`（板块行情） | `master-detail` | `density` | action:`filter-bar` / main:`master-detail` / nested:`wide-table` / nested:`chart` |
| `sectors-detail` | `SectorDetailView`（板块详情） | `master-detail` | `density` | action:`toolbar` / main:`master-detail` / nested:`section` / nested:`chart` / nested:`data-table` |
<!-- page-registry:end -->

除 `supportsPageSettings=false` 的视觉预设、页面布局、系统组件三个平台管理页外，registry 页面必须有 `settings-drawer` overlay slot。三个管理页只管理系统配置，不开放或持久化个人页面设置。组件字段、slot 结构、候选项和明确例外的事实源在 `COMPONENT_FIELD_DEFS`、slot `config` 和 `componentMeta`，不要在本表重复维护。

## 10. Scope & Exceptions

- 本项目桌面工作台优先；响应式规则覆盖低高度和常见桌面宽度，移动端不是当前验收重点。
- 当前没有独立品牌设计稿；视觉方向以本文件的金融科技研究终端规则和现有品牌组件为准。
- 品牌字标、登录主视觉、图表 tooltip、代码值和极窄 badge 允许局部排版特例；新增业务页面不得复制这些特例作为普通排版。
- 页面登记区块通过 `<!-- page-registry:start/end -->` marker 被 `pageRegistry.spec.ts` 和 `scaffold-page` 读取；marker 是机器契约，不要移除。
