/**
 * 可配置布局系统 — Schema 类型定义（M1）。
 *
 * 把布局规范的「页面原型 / 组件最低尺寸 / 滚动归属 / 重排多列」（原 ai-agent 规范稿，已代码化退场）
 * 抽象成机器可读的声明式描述符。每个页面用一份 PageLayout 声明其布局，
 * 由校验器（validator.ts）保证不越规、由渲染器（M2）产出页面外壳和条件成长/滚动区域。
 *
 * 三层配置模型（详见 agent-works/configurable-layout-system/plan.md）：
 *   L1 archetype（开发期选定、用户确认、运行期锁死）
 *   L2 布局参数（受限档位 + 白名单 editable + 取值域，越界即拒）
 *   L3 组件特性偏好（分页/排序/字段，复用 usePageSettings，本文件不涉及）
 */

/** 页面布局原型（规范 §4 A~G）。弹窗/抽屉(H) 是覆盖层、不作为页面级原型，单独处理。 */
export type Archetype =
  | 'list' //          A 列表页（最高频）：筛选+批量+表格+分页
  | 'master-detail' // B 主从页：左列表 | 右详情，两栏各自内滚
  | 'dashboard' //     C 仪表盘/概览：KPI 卡 + 图表网格，可重排多列
  | 'form' //          D 表单/编辑页：标题吸顶 + 字段区内滚 + 按钮吸底
  | 'detail' //        E 详情页：摘要/操作吸顶 + 分区内容内滚
  | 'workbench' //     F 分析工作台：参数区固定 + 混合成长区（固定分析块 + 主表）
  | 'wizard' //        G 向导页：步骤条吸顶 + 内容内滚 + 导航吸底

export const ARCHETYPES: readonly Archetype[] = [
  'list',
  'master-detail',
  'dashboard',
  'form',
  'detail',
  'workbench',
  'wizard',
] as const

/** 滚动归属（规范 §3/§6：每个可视区域有且仅有一个主滚动轴）。 */
export type ScrollOwnership =
  | 'none' //    不滚（固定区，或随父成长区滚）
  | 'body-y' //  自身纵向内滚（表体内滚 + 表头吸顶）
  | 'body-xy' // 纵向 + 横向内滚（宽表，优先冻结列）
  | 'region' //  作为成长区整体滚动（兜底阶梯第 3 级）

/**
 * 第一层外壳的区域角色（规范 §1：固定操作区 + 填满剩余的主内容区）。
 * `overlay` 为浮层区（drawer/dialog/设置抽屉等）：进入统一可寻址模型供配置/系统组件消费，
 * 但不参与 LayoutHost 的 action/main 主流渲染（由页面自行用 #overlays/#footer 渲染）。
 */
export type RegionRole = 'action' | 'main' | 'overlay'

/** 信息密度档位（L2 可调）。 */
export type Density = 'compact' | 'standard' | 'comfortable'

/** 当前内置预设只保留 balanced；运行时还允许加载预设管理中启用的自定义 key。 */
export type LayoutPresetKey = 'balanced'

export interface StyleTokenConfig {
  primary: string
  success: string
  warning: string
  danger: string
  pageBg: string
  surfaceBg: string
  surfaceHover: string
  border: string
  borderStrong: string
  text: string
  textStrong: string
  textMuted: string
  activeBg: string
  submenuBg: string
  cardRadius: number
  controlRadius: number
  shadow: string
  pageGap: number
  cardPadding: number
  tableCellPaddingY: number
}

export interface PresetComponentDefaults {
  density: Density
  tableSize: Density
  filterDefaultExpanded: boolean
  drawerSize: 'sm' | 'md' | 'lg'
}

export interface PresetResponsiveDefaults {
  pageGap: number
  reflowBreakpoint: number
}

/** 主题模式：与 useTheme 的 html.dark 同源。预设 token 按模式提供两套（M9）。 */
export type ThemeMode = 'light' | 'dark'

/** 预设双模式 token：白天/夜间各一套完整 StyleTokenConfig，applyPreset 按当前 isDark 取用。 */
export type PresetTokens = Record<ThemeMode, StyleTokenConfig>

export interface LayoutPreset {
  key: string
  name: string
  description: string
  tokens: PresetTokens
  componentDefaults: PresetComponentDefaults
  responsiveDefaults: PresetResponsiveDefaults
}

/** 常见业务组件种类（规范 §3 目录的键）。最低尺寸/滚动/可否成主/可否重排见 components.ts。 */
export type ComponentKind =
  | 'page-shell' //     页面外壳
  | 'section' //        内容分区
  | 'split-pane' //     分栏/分割面板
  | 'slot-group' //     组件分组
  | 'data-table' //     数据表格（分页列表）
  | 'wide-table' //     宽表格（列多，横向内滚 + 冻结列）
  | 'filter-bar' //     控件行（筛选、搜索、参数、操作）
  | 'search-box' //      关键词搜索
  | 'advanced-filter' // 高级筛选
  | 'toolbar' //        工具栏
  | 'batch-bar' //      批量操作栏
  | 'simple-list' //     简单列表
  | 'description-list' // 描述列表
  | 'tree-table' //      树表
  | 'pagination' //      分页器
  | 'column-settings' // 列设置
  | 'sort-control' //    排序控件
  | 'export-button' //   导出按钮
  | 'form' //           表单（创建/编辑）
  | 'form-section' //    表单分区
  | 'config-panel' //    配置面板
  | 'field-grid' //      字段网格
  | 'inline-editor' //   行内编辑
  | 'loading-state' //   加载态
  | 'empty-state' //     空态
  | 'error-state' //     错误态
  | 'skeleton' //        骨架屏
  | 'kpi-grid' //       KPI/指标卡片网格
  | 'metric-card' //     指标卡
  | 'stat-strip' //      指标条
  | 'chart' //          图表（折线等）
  | 'mini-chart' //     迷你图
  | 'chart-grid' //      图表网格
  | 'trend-panel' //     趋势面板
  | 'master-detail' //  主从（列表+详情）组合
  | 'tree-nav' //       树形导航/目录
  | 'tabs' //           标签页
  | 'collapse' //       折叠面板
  | 'steps' //          步骤向导
  | 'kanban' //         看板
  | 'detail-panel' //   详情面板
  | 'drawer' //         抽屉/弹窗
  | 'dialog' //         弹窗
  | 'settings-drawer' // 页面设置抽屉（受控 overlay，承载用户级偏好）
  | 'side-panel' //     侧边面板
  | 'detail' //         详情内容
  | 'timeline' //       时间线/Feed
  | 'anchor-nav' //     锚点导航
  | 'breadcrumb' //     面包屑

export type ComponentCategory =
  | 'structure'
  | 'query'
  | 'display'
  | 'table-addon'
  | 'form'
  | 'feedback'
  | 'analytics'
  | 'overlay'
  | 'complex'
  | 'navigation'

/** 页面和组件的数据反馈四态；预览、运行时状态组件与布局契约共同消费。 */
export const COMPONENT_STATES = ['ready', 'loading', 'empty', 'error'] as const
export type ComponentState = (typeof COMPONENT_STATES)[number]

export interface ComponentStateStrategy {
  /** 状态切换时是否保留稳定占位，避免布局跳变。 */
  reserveSpace: boolean
  /** 状态盒子最小高度；显式声明时用于校验稳定占位。 */
  minH?: number
}

export interface ComponentActionConfig {
  key: string
  label: string
  placement?: 'primary' | 'toolbar' | 'row' | 'footer'
  permission?: string
}

export interface ComponentDataBinding {
  source?: string
  valueKey?: string
  labelKey?: string
  rowKey?: string
}

export type ComponentInstanceConfig = Record<string, unknown>

/**
 * 组件槽：主内容区/操作区里的一个组件占位。
 * 尺寸缺省取组件目录默认；显式覆盖时校验器要求 ≥ 目录业务下限（不能把组件压到不可用）。
 */
export interface SlotSpec {
  id: string
  component: ComponentKind
  label?: string
  region: RegionRole
  visible?: boolean
  permission?: string
  styleTokens?: Record<string, string | number | boolean>
  /** 业务最低宽（px）。缺省取组件目录；显式值不得低于目录下限。 */
  minW?: number
  /** 业务最低高（px）。缺省取组件目录；显式值不得低于目录下限。 */
  minH?: number
  /** 理想宽高（仅渲染参考，不参与下限校验）。 */
  idealW?: number
  idealH?: number
  /** 滚动归属。缺省取组件目录默认。 */
  scroll?: ScrollOwnership
  /** 是否为吃富余空间的「主表/主图」（同一主内容区至多一个；组件须 canGrowMain）。 */
  growMain?: boolean
  /** 是否可参与多列重排；缺省取组件目录默认，仅允许收紧，不允许放松目录红线。 */
  reflowable?: boolean
  /** 常见状态的稳定占位策略。 */
  states?: Partial<Record<ComponentState, ComponentStateStrategy>>
  /** 数据绑定提示，供后续配置中心和脚手架使用。 */
  dataBinding?: ComponentDataBinding
  /** 操作声明，供后续权限和配置中心使用。 */
  actions?: ComponentActionConfig[]
  /** 组件专属受控配置，按 component 类型由 componentSchemas.ts 校验。 */
  config?: ComponentInstanceConfig
  /** 同区内排序（升序）。 */
  order?: number
  /**
   * 嵌套归属（P5）：声明本 slot 嵌套在另一个 slot（如 section/tabs 内承载的表/图）内部。
   * 仅用于使「非顶层组件」进入可寻址模型（寻址仍为 slots.<id>.config.<field>，复用现有合并/校验/后端归属）；
   * 带 parentId 的 slot 不参与 LayoutHost 的顶层 action/main 流式渲染，由父组件自行渲染。
   * 仅支持一层嵌套：parentId 必须指向一个不带 parentId 的顶层 slot。
   */
  parentId?: string
}

/** 单个响应式断点：视口宽 ≥ minWidth 时主内容区按 columns 列排布。 */
export interface ResponsiveBreakpoint {
  /** 触发该列数的最小视口宽度（px）；升序，首项应为 0 覆盖窄屏单列。 */
  minWidth: number
  /** 列数（≥1）。 */
  columns: number
}

/** 响应式重排方案（规范 §5：兜底阶梯第 2 级，拿宽度换高度）。 */
export interface ResponsivePlan {
  /** 是否允许重排多列。单个大表/有强阅读顺序 → 必须 false。 */
  allowReflow: boolean
  /** 断点表（升序）。如 [{0,1},{1024,2},{1440,3}]。 */
  breakpoints: ResponsiveBreakpoint[]
}

/**
 * 可编辑旋钮：Web 端自定义面板的白名单 + 取值域（L2 的「可改但不能乱改」）。
 * 对齐后端 app_config 的字段范式（type/min/max/options）。path 指向 PageLayout 内真实字段。
 */
export interface EditableKnob {
  /** 点分路径，定位 PageLayout 内字段：'density' | 'slots.<id>.minH' | ...。 */
  path: string
  label: string
  type: 'enum' | 'int' | 'number' | 'bool'
  options?: (string | number)[]
  /** enum 选项的中文展示名（按 String(value) 取），纯展示用，校验器忽略。 */
  optionLabels?: Record<string, string>
  min?: number
  max?: number
}

/** 一个页面的完整布局描述符。 */
export interface PageLayout {
  /** 页面唯一键（与 usePageSettings 的 pageKey 同源，便于偏好聚合）。 */
  pageKey: string
  archetype: Archetype
  /** 第一层是否拆「操作区」。无明确操作→内容上下级关系的平级面板页置 false（规范 §1 例外）。 */
  hasActionRegion: boolean
  slots: SlotSpec[]
  responsive: ResponsivePlan
  density: Density
  /** 允许 Web 端改动的旋钮白名单；为空表示该页不开放自定义。 */
  editable: EditableKnob[]
}
