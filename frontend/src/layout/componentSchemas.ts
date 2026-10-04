import type { ComponentKind, ComponentInstanceConfig } from './schema'

export interface ComponentConfigIssue {
  code: string
  message: string
}

type ConfigValue = string | number | boolean | string[] | number[] | Record<string, unknown>
type ConfigShape = Record<string, 'string' | 'number' | 'int' | 'bool' | 'string[]' | 'number[]' | 'object' | string[]>

const rowClick = ['none', 'select', 'open-detail', 'navigate']
const resetMode = ['clear', 'defaults']
const size = ['sm', 'md', 'lg', 'xl', 'fullscreen']
const chartType = ['line', 'bar', 'area', 'pie', 'scatter', 'candlestick']

const tableShape: ConfigShape = {
  border: 'bool',
  pagination: 'bool',
  pageSize: 'int',
  defaultSort: 'string',
  columns: 'string[]',
  columnOrder: 'string[]',
  hiddenColumns: 'string[]',
  columnWidths: 'object',
  frozenColumns: 'int',
  selectable: 'bool',
  crossPageSelection: 'bool',
  serverSide: 'bool',
  rowClick,
}

const filterShape: ConfigShape = {
  fields: 'string[]',
  placeholder: 'string',
  defaultExpanded: 'bool',
  advanced: 'bool',
  autoQuery: 'bool',
  resetMode,
  remember: 'bool',
}

const controlRowShape: ConfigShape = {
  commonFields: 'string[]',
  controls: 'string[]',
  wrap: 'bool',
  fill: 'bool',
  labelControlMode: ['inline', 'stacked'],
  autoQuery: 'bool',
  resetMode,
  remember: 'bool',
}

const searchBoxShape: ConfigShape = {
  placeholder: 'string',
  autoQuery: 'bool',
  remember: 'bool',
}

const advancedFilterShape: ConfigShape = {
  fields: 'string[]',
  defaultExpanded: 'bool',
  resetMode,
  remember: 'bool',
}

const formShape: ConfigShape = {
  columns: 'int',
  labelWidth: ['auto', 'compact', 'standard', 'wide'],
  readonly: 'bool',
  stickyFooter: 'bool',
  scrollBody: 'bool',
  collapsible: 'bool',
}

const overlayShape: ConfigShape = {
  size,
  maxHeight: 'int',
  fixedHeader: 'bool',
  fixedFooter: 'bool',
  closeOnEsc: 'bool',
  bodyScroll: 'bool',
  collapsible: 'bool',
}

const chartShape: ConfigShape = {
  chartType,
  minHeight: 'int',
  stockChart: 'object',
  klineRangePreferences: 'object',
  stockAnalysis: 'object',
  sectorAnalysis: 'object',
  returnMeasurement: 'bool',
  multiPeriodKline: 'bool',
  klinePeriod: ['day', 'week', 'month', 'year'],
  returnMeasurementMode: ['latest', 'range'],
  aspectRatio: 'number',
  legend: 'bool',
  tooltip: 'bool',
  emptyState: 'string',
}

const feedbackShape: ConfigShape = {
  reserveSpace: 'bool',
  minH: 'int',
  rows: 'int',
  retryAction: 'string',
}

const COMPONENT_CONFIG_SHAPES: Partial<Record<ComponentKind, ConfigShape>> = {
  section: {
    title: 'string',
    collapsible: 'bool',
    visibleIndicatorFields: 'string[]',
  },
  'data-table': tableShape,
  'wide-table': tableShape,
  'tree-table': { ...tableShape, defaultExpandAll: 'bool', rowKey: 'string' },
  'simple-list': { rowClick },
  'description-list': { columns: 'int', labelWidth: formShape.labelWidth },

  'filter-bar': controlRowShape,
  'search-box': searchBoxShape,
  'advanced-filter': advancedFilterShape,
  toolbar: { actions: 'string[]', wrap: 'bool' },
  'batch-bar': { actions: 'string[]', selectionRequired: 'bool' },

  pagination: { pageSize: 'int', pageSizes: 'number[]', layout: 'string' },
  'column-settings': { hiddenColumns: 'string[]', columnOrder: 'string[]', columnWidths: 'object' },
  'sort-control': { defaultSort: 'string', options: 'string[]' },
  'export-button': { formats: 'string[]', permission: 'string' },

  form: formShape,
  'form-section': { ...formShape, title: 'string' },
  'config-panel': {
    collapsibleSections: 'bool',
    defaultCollapsed: 'string[]',
    showGroupDescription: 'bool',
    showSectionDescription: 'bool',
  },
  'field-grid': { columns: 'int', labelWidth: formShape.labelWidth },
  'inline-editor': { mode: ['cell', 'row', 'popover'], validation: 'object' },

  'loading-state': feedbackShape,
  'empty-state': feedbackShape,
  'error-state': feedbackShape,
  skeleton: feedbackShape,

  'kpi-grid': { columns: 'int', autoFit: 'bool', visibleItems: 'string[]' },
  'metric-card': { trend: 'bool', precision: 'int' },
  'stat-strip': { items: 'string[]', wrap: 'bool' },
  chart: chartShape,
  'mini-chart': chartShape,
  'chart-grid': { columns: 'int', minHeight: 'int', gap: 'int' },
  'trend-panel': { chartType, summaryPlacement: ['top', 'right', 'bottom'] },

  'detail-panel': overlayShape,
  detail: { sections: 'string[]', stickySummary: 'bool', bodyScroll: 'bool', autoScroll: 'bool' },
  drawer: overlayShape,
  dialog: overlayShape,
  'settings-drawer': { ...overlayShape, sections: 'string[]' },
  'side-panel': overlayShape,

  'master-detail': { masterWidth: 'int', masterRatio: 'int', masterRatioProfiles: 'object', detailMinWidth: 'int', collapseAt: 'int' },
  tabs: { stickyTabBar: 'bool', defaultActive: 'string', remember: 'bool', independentLayout: 'bool' },
  collapse: { accordion: 'bool', defaultActive: 'string[]' },
  steps: { active: 'int', direction: ['horizontal', 'vertical'], stickyNav: 'bool' },
  kanban: { columns: 'string[]', cardMinWidth: 'int', dragEnabled: 'bool' },
  timeline: { mode: ['left', 'right', 'alternate'], reverse: 'bool', groupByDate: 'bool' },

  'tree-nav': { defaultExpandAll: 'bool', showSearch: 'bool', remember: 'bool' },
  'anchor-nav': { sticky: 'bool', offset: 'int' },
  breadcrumb: { maxItems: 'int' },

  'page-shell': {},
  'split-pane': { direction: ['horizontal', 'vertical'], primarySize: 'int', resizable: 'bool' },
  'slot-group': { gap: 'int', columns: 'int' },
}

function typeOf(value: unknown): ConfigValue | undefined {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  if (Array.isArray(value) && value.every((v) => typeof v === 'string')) return value as string[]
  if (Array.isArray(value) && value.every((v) => typeof v === 'number')) return value as number[]
  if (value != null && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  return undefined
}

function matchesRule(value: unknown, rule: ConfigShape[string]): boolean {
  const typed = typeOf(value)
  if (typed === undefined) return false
  if (Array.isArray(rule)) return typeof value === 'string' && rule.includes(value)
  if (rule === 'int') return typeof value === 'number' && Number.isInteger(value)
  if (rule === 'number') return typeof value === 'number' && Number.isFinite(value)
  if (rule === 'bool') return typeof value === 'boolean'
  if (rule === 'string') return typeof value === 'string'
  if (rule === 'string[]') return Array.isArray(value) && value.every((v) => typeof v === 'string')
  if (rule === 'number[]') return Array.isArray(value) && value.every((v) => typeof v === 'number' && Number.isFinite(v))
  if (rule === 'object') return value != null && typeof value === 'object' && !Array.isArray(value)
  return false
}

function ruleLabel(rule: ConfigShape[string]): string {
  return Array.isArray(rule) ? rule.join(' | ') : rule
}

export function validateComponentConfig(kind: ComponentKind, config: ComponentInstanceConfig | undefined): ComponentConfigIssue[] {
  if (!config) return []
  const shape = COMPONENT_CONFIG_SHAPES[kind]
  if (!shape) return [{ code: 'component.config.schemaMissing', message: `${kind} 缺少组件配置 schema` }]

  const issues: ComponentConfigIssue[] = []
  for (const [key, value] of Object.entries(config)) {
    const rule = shape[key]
    if (!rule) {
      issues.push({ code: 'component.config.unknownKey', message: `${kind}.${key} 不是受控配置项` })
      continue
    }
    if (!matchesRule(value, rule)) {
      issues.push({ code: 'component.config.type', message: `${kind}.${key} 需为 ${ruleLabel(rule)}` })
    }
  }
  return issues
}
