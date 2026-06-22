/**
 * 布局原型预设注册表（规范 §4 A~G）。
 *
 * 开发期按业务从这里选一个原型作为页面布局的起点（用户确认后落为该页默认 PageLayout）。
 * 每个预设都是「开箱即合规」的：直接交给 validator.validateLayout 不应产生 error。
 * 预设是默认值，具体页面可在此基础上覆盖 slots/editable，但仍须过校验器。
 */
import type { Archetype, PageLayout } from './schema'

/** 标准重排断点：窄屏单列 → 1024 两列 → 1440 三列（规范 §5 推荐）。 */
const REFLOW_BREAKPOINTS = [
  { minWidth: 0, columns: 1 },
  { minWidth: 1024, columns: 2 },
  { minWidth: 1440, columns: 3 },
]

/** 不重排：恒单列（单个大表/有强阅读顺序）。 */
const SINGLE_COLUMN = [{ minWidth: 0, columns: 1 }]

const DENSITY_KNOB = {
  path: 'density',
  label: '信息密度',
  type: 'enum' as const,
  options: ['compact', 'standard', 'comfortable'],
}

type PresetBuilder = (pageKey: string) => PageLayout

/** A 列表页：筛选/批量（操作区）+ 表格（主内容区，主表内滚）+ 分页。 */
const list: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'list',
  hasActionRegion: true,
  slots: [
    { id: 'filter', component: 'filter-bar', region: 'action', order: 1 },
    { id: 'batch', component: 'batch-bar', region: 'action', order: 2 },
    { id: 'table', component: 'data-table', region: 'main', growMain: true, order: 1 },
  ],
  responsive: { allowReflow: false, breakpoints: SINGLE_COLUMN },
  density: 'standard',
  editable: [
    DENSITY_KNOB,
    { path: 'slots.table.minH', label: '表格最低高(px)', type: 'int', min: 300, max: 800 },
  ],
})

/** B 主从页：工具栏 + 左列表 | 右详情（两栏各自内滚；窄屏退化由渲染器处理）。 */
const masterDetail: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'master-detail',
  hasActionRegion: true,
  slots: [
    { id: 'toolbar', component: 'filter-bar', region: 'action', order: 1 },
    { id: 'list', component: 'data-table', region: 'main', order: 1, idealW: 280 },
    // 右详情在主从页是「内滚的栏」，覆盖目录默认的整区滚动为表体内滚
    { id: 'detail', component: 'detail', region: 'main', order: 2, scroll: 'body-y', idealW: 420 },
  ],
  responsive: { allowReflow: false, breakpoints: SINGLE_COLUMN },
  density: 'standard',
  editable: [DENSITY_KNOB],
})

/** C 仪表盘/概览：KPI 卡 + 图表网格，平级块、允许重排多列。 */
const dashboard: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'dashboard',
  hasActionRegion: false,
  slots: [
    { id: 'kpi', component: 'kpi-grid', region: 'main', order: 1 },
    { id: 'chartA', component: 'chart', region: 'main', order: 2 },
    { id: 'chartB', component: 'chart', region: 'main', order: 3 },
  ],
  responsive: { allowReflow: true, breakpoints: REFLOW_BREAKPOINTS },
  density: 'standard',
  editable: [DENSITY_KNOB],
})

/** D 表单/编辑页：字段区内滚填满，标题吸顶/按钮吸底由渲染器处理。 */
const form: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'form',
  hasActionRegion: false,
  slots: [{ id: 'form', component: 'form', region: 'main', order: 1 }],
  responsive: { allowReflow: false, breakpoints: SINGLE_COLUMN },
  density: 'standard',
  editable: [DENSITY_KNOB],
})

/** E 详情页：分区内容整体内滚。 */
const detail: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'detail',
  hasActionRegion: false,
  slots: [{ id: 'detail', component: 'detail', region: 'main', order: 1 }],
  responsive: { allowReflow: false, breakpoints: SINGLE_COLUMN },
  density: 'standard',
  editable: [DENSITY_KNOB],
})

/** F 分析工作台：参数区（操作区）+ 混合成长区（固定分析块 KPI/图 + 主表 grow）。 */
const workbench: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'workbench',
  hasActionRegion: true,
  slots: [
    { id: 'params', component: 'filter-bar', region: 'action', order: 1 },
    { id: 'perf', component: 'kpi-grid', region: 'main', order: 1 },
    { id: 'chart', component: 'chart', region: 'main', order: 2 },
    { id: 'table', component: 'data-table', region: 'main', growMain: true, order: 3 },
  ],
  responsive: { allowReflow: false, breakpoints: SINGLE_COLUMN },
  density: 'standard',
  editable: [
    DENSITY_KNOB,
    { path: 'slots.table.minH', label: '主表最低高(px)', type: 'int', min: 300, max: 800 },
  ],
})

/** G 向导页：步骤条吸顶 + 内容内滚 + 导航吸底（由 steps 组件封装）。 */
const wizard: PresetBuilder = (pageKey) => ({
  pageKey,
  archetype: 'wizard',
  hasActionRegion: false,
  slots: [{ id: 'steps', component: 'steps', region: 'main', order: 1 }],
  responsive: { allowReflow: false, breakpoints: SINGLE_COLUMN },
  density: 'standard',
  editable: [DENSITY_KNOB],
})

export const ARCHETYPE_PRESETS: Record<Archetype, PresetBuilder> = {
  list,
  'master-detail': masterDetail,
  dashboard,
  form,
  detail,
  workbench,
  wizard,
}

/** 按原型创建一份默认 PageLayout（深拷贝，调用方可安全改写）。 */
export function createLayout(archetype: Archetype, pageKey: string): PageLayout {
  return ARCHETYPE_PRESETS[archetype](pageKey)
}
