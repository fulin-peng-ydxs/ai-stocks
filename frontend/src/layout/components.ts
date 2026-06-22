/**
 * 组件最低尺寸目录（规范 §3「常见业务组件：最低尺寸与自适应行为目录」的机器可读版）。
 *
 * 这是校验器判定「不能把组件压到不可用」的判据来源，也是渲染器取默认滚动/尺寸的依据。
 * 数值取自规范 §3（如数据表格 min-height≈300、图表折线≈260、迷你图≈120、主从左 280/右 420）。
 * 调整这些值即调整全站布局下限，属规范级变更，须同步规范文档。
 */
import type { ComponentKind, ScrollOwnership } from './schema'

export interface ComponentMeta {
  kind: ComponentKind
  label: string
  /** 业务最低宽（px）：低于它该组件被压到不可读/不可用。 */
  minW: number
  /** 业务最低高（px）。 */
  minH: number
  /** 默认滚动归属（slot 未显式声明时取此）。 */
  defaultScroll: ScrollOwnership
  /** 能否作为吃富余空间的「主表/主图」（规范 §1 放置规则 3）。 */
  canGrowMain: boolean
  /** 是否无强阅读顺序、可参与重排多列（规范 §5 条件 2/3）。单个大表/有序内容为 false。 */
  reflowable: boolean
}

/** ComponentKind → 元信息。新增组件种类须在此登记，否则校验器拒绝该 slot。 */
export const COMPONENT_CATALOG: Record<ComponentKind, ComponentMeta> = {
  'data-table': { kind: 'data-table', label: '数据表格', minW: 360, minH: 300, defaultScroll: 'body-y', canGrowMain: true, reflowable: false },
  'wide-table': { kind: 'wide-table', label: '宽表格', minW: 480, minH: 300, defaultScroll: 'body-xy', canGrowMain: true, reflowable: false },
  'filter-bar': { kind: 'filter-bar', label: '筛选栏', minW: 280, minH: 48, defaultScroll: 'none', canGrowMain: false, reflowable: false },
  'batch-bar': { kind: 'batch-bar', label: '批量操作栏', minW: 280, minH: 44, defaultScroll: 'none', canGrowMain: false, reflowable: false },
  form: { kind: 'form', label: '表单', minW: 360, minH: 240, defaultScroll: 'body-y', canGrowMain: false, reflowable: false },
  'kpi-grid': { kind: 'kpi-grid', label: 'KPI 卡片网格', minW: 200, minH: 88, defaultScroll: 'none', canGrowMain: false, reflowable: true },
  chart: { kind: 'chart', label: '图表', minW: 280, minH: 260, defaultScroll: 'none', canGrowMain: true, reflowable: true },
  'mini-chart': { kind: 'mini-chart', label: '迷你图', minW: 160, minH: 120, defaultScroll: 'none', canGrowMain: false, reflowable: true },
  'master-detail': { kind: 'master-detail', label: '主从组合', minW: 720, minH: 320, defaultScroll: 'none', canGrowMain: false, reflowable: false },
  'tree-nav': { kind: 'tree-nav', label: '树形导航', minW: 200, minH: 240, defaultScroll: 'body-y', canGrowMain: false, reflowable: false },
  tabs: { kind: 'tabs', label: '标签页', minW: 320, minH: 200, defaultScroll: 'none', canGrowMain: false, reflowable: false },
  collapse: { kind: 'collapse', label: '折叠面板', minW: 280, minH: 80, defaultScroll: 'none', canGrowMain: false, reflowable: false },
  steps: { kind: 'steps', label: '步骤向导', minW: 360, minH: 200, defaultScroll: 'none', canGrowMain: false, reflowable: false },
  kanban: { kind: 'kanban', label: '看板', minW: 280, minH: 320, defaultScroll: 'body-xy', canGrowMain: false, reflowable: false },
  drawer: { kind: 'drawer', label: '抽屉/弹窗', minW: 320, minH: 240, defaultScroll: 'body-y', canGrowMain: false, reflowable: false },
  detail: { kind: 'detail', label: '详情内容', minW: 360, minH: 300, defaultScroll: 'region', canGrowMain: false, reflowable: false },
  timeline: { kind: 'timeline', label: '时间线/Feed', minW: 280, minH: 240, defaultScroll: 'body-y', canGrowMain: false, reflowable: false },
}

/** 取组件元信息；未登记返回 undefined（校验器据此报错）。 */
export function getComponentMeta(kind: ComponentKind): ComponentMeta | undefined {
  return COMPONENT_CATALOG[kind]
}
