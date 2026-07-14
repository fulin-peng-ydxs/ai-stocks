/**
 * 组件预览原型映射（P6 / M8-D）。
 *
 * 「系统组件」库需要给每个组件一块可视化预览。已登记组件（COMPONENT_CATALOG，当前 48 种）不逐一定制，而是归并到少量**视觉原型**
 * （代表性 mock），由 LayoutComponentPreview.vue 按原型 + 状态（默认/loading/empty/error）渲染占位示意。
 * 这是组件目录的展示层，不是新的运行时配置层（边界见 plan.md §6.3.1）。
 *
 * Record<ComponentKind, PreviewArchetype> 由 TS 强制完整：新增组件种类必须在此登记预览原型。
 */
import type { ComponentKind } from './schema'

export type PreviewArchetype =
  | 'table' //     表格：表头 + 数据行
  | 'list' //      列表/Feed/看板/折叠：条目流
  | 'tree' //      树：层级缩进节点
  | 'controls' //  操作类：输入/按钮/分页/步骤/面包屑
  | 'chart' //     图表：折线/柱状示意
  | 'kpi' //       指标卡/指标条
  | 'form' //      表单：标签 + 字段
  | 'feedback' //  反馈态：loading/empty/error/skeleton 本身
  | 'overlay' //   浮层：抽屉/弹窗/侧栏/详情面板（header+body+footer）
  | 'tabs' //      标签页：tab 条 + 内容
  | 'detail' //    详情/描述：键值行
  | 'master' //    主从：左列表 + 右详情
  | 'structure' // 结构容器：外壳/分区/分栏/分组

export const PREVIEW_ARCHETYPE: Record<ComponentKind, PreviewArchetype> = {
  'page-shell': 'structure',
  section: 'structure',
  'split-pane': 'structure',
  'slot-group': 'structure',

  'filter-bar': 'controls',
  'search-box': 'controls',
  'advanced-filter': 'controls',
  toolbar: 'controls',
  'batch-bar': 'controls',

  'data-table': 'table',
  'wide-table': 'table',
  'simple-list': 'list',
  'description-list': 'detail',
  'tree-table': 'tree',

  pagination: 'controls',
  'column-settings': 'controls',
  'sort-control': 'controls',
  'export-button': 'controls',

  form: 'form',
  'form-section': 'form',
  'config-panel': 'form',
  'field-grid': 'form',
  'inline-editor': 'form',

  'loading-state': 'feedback',
  'empty-state': 'feedback',
  'error-state': 'feedback',
  skeleton: 'feedback',

  'kpi-grid': 'kpi',
  'metric-card': 'kpi',
  'stat-strip': 'kpi',
  chart: 'chart',
  'mini-chart': 'chart',
  'chart-grid': 'chart',
  'trend-panel': 'chart',

  'detail-panel': 'overlay',
  detail: 'detail',
  drawer: 'overlay',
  dialog: 'overlay',
  'settings-drawer': 'overlay',
  'side-panel': 'overlay',

  'master-detail': 'master',
  tabs: 'tabs',
  collapse: 'list',
  steps: 'controls',
  kanban: 'list',
  timeline: 'list',

  'tree-nav': 'tree',
  'anchor-nav': 'list',
  breadcrumb: 'controls',
}

/** 取组件预览原型；未登记回落 structure（理论上不会发生，TS 已强制完整）。 */
export function previewArchetypeOf(kind: ComponentKind): PreviewArchetype {
  return PREVIEW_ARCHETYPE[kind] ?? 'structure'
}

/** feedback 类组件的「默认态」本身就是一种状态，预览据此选择默认渲染。 */
export const FEEDBACK_DEFAULT_STATE: Partial<Record<ComponentKind, 'loading' | 'empty' | 'error'>> = {
  'loading-state': 'loading',
  'empty-state': 'empty',
  'error-state': 'error',
  skeleton: 'loading',
}
