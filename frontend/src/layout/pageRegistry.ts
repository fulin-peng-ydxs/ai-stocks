/**
 * 页面注册表（P0/P1）——可配置布局系统的单一事实源。
 *
 * 设计目标（plan.md §7.1）：把"哪些页面已纳入布局系统、各自原型/槽位/可编辑旋钮/响应式策略"
 * 集中到一处声明，替代两类历史散落：
 *   1. 每个 View 内联手写一份 PageLayout；
 *   2. LayoutConfigView 内手写一份 managedPages（且与真实页面声明漂移，见 P1 修正）。
 *
 * 各业务页面统一通过 getPageLayout(pageKey) 取布局；配置中心、报告页、导入校验
 * 统一通过 PAGE_REGISTRY / listManagedPages() 读取页面元信息，不再手写。
 *
 * 布局配置平台页（预设管理/页面布局/系统组件）也纳入注册表，保证「页面布局」工作台能查看和配置这些系统页面。
 */
import type { Archetype, EditableKnob, PageLayout } from './schema'
import { cloneLayout } from './path'

/** 页面响应式策略（plan.md §14.3）。受控命名，不等于自由编辑断点。 */
export type ResponsiveProfile =
  | 'single-column' //  始终单列，依赖内部滚动（列表/详情主区单组件）
  | 'safe-reflow' //    仅允许满足最小尺寸的平级块重排（仪表盘类）
  | 'mixed-panel' //    固定分析块 + 主 grow 区 + 整区滚动兜底（工作台类）

export interface PageRegistryEntry {
  /** 页面唯一键（与 usePageSettings / 后端 layout_page_config 同源）。 */
  pageKey: string
  /** 中文展示名（与路由菜单一致）。 */
  label: string
  /** 路由路径。 */
  path: string
  archetype: Archetype
  /** 该页面的代码默认布局（default 层，单一事实源）。 */
  layout: PageLayout
  /**
   * 声明的目标响应式策略，用于配置中心报告与 P5 自适应产品化。
   * 注意：当前仅为"声明值"，尚未由 layout.responsive 强制落地（各页实际 responsive 仍多为 single-column）；
   * 配置中心已将其标注为"声明，待 P5 落地"，避免高估当前自适应能力。
   */
  responsiveProfile: ResponsiveProfile
  /** 是否已接入组件特性配置层（顶层 slot 可承载受控字段）；决定配置中心是否显示组件配置区块。 */
  supportsComponentConfig: boolean
  /**
   * 该页实际消费的组件配置字段（slotId -> 字段 key 列表），单一事实源。
   * 配置中心只渲染此处登记的字段，避免暴露页面不读的配置项；新增字段必须同时在此登记。
   */
  consumedComponentFields?: Record<string, string[]>
  /**
   * 组件配置自动渲染元数据（slotId -> 列/可排序字段），驱动设置抽屉「组件设置」段自动生成
   * （列显隐开关、默认排序下拉），各页不再手写列开关。仅消费 hiddenColumns/defaultSort 的 slot 需登记。
   */
  componentMeta?: Record<string, SlotConfigMeta>
}

/** 某 slot 的组件配置自动渲染元数据。 */
export interface SlotConfigMeta {
  /** 可显隐的列（驱动 hiddenColumns 开关组；key 为列标识、label 为中文名）。 */
  columns?: { key: string; label: string }[]
  /** 可作为默认排序的字段（驱动 defaultSort 下拉；key 可与列 key 不同，如 pct_chg）。 */
  sortFields?: { key: string; label: string }[]
  /**
   * defaultSort 是否含方向（升/降）。
   * true（默认）：值形如 `field:order`，渲染字段选择 + 方向选择（如 StocksView）。
   * false：值就是 sortFields 的 key（排序模式枚举，无方向，如 BoardView 的 score/rank）。
   */
  sortHasDirection?: boolean
  /** 可选的 Tab 项（驱动 tabs.defaultActive 选择；key 为 tab name、label 为中文名）。 */
  tabs?: { key: string; label: string }[]
}

/** 信息密度旋钮——所有页面通用的 L2 可编辑项，统一文案与取值域。 */
function densityKnob(): EditableKnob {
  return {
    path: 'density',
    label: '信息密度',
    type: 'enum',
    options: ['compact', 'standard', 'comfortable'],
    optionLabels: { compact: '紧凑', standard: '标准', comfortable: '宽松' },
  }
}

/** 通用单列响应式方案（不重排，靠内部滚动）。 */
function singleColumn() {
  return { allowReflow: false, breakpoints: [{ minWidth: 0, columns: 1 }] }
}

function configEntry(pageKey: string, label: string, path: string): PageRegistryEntry {
  return {
    pageKey,
    label,
    path,
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: false,
    layout: {
      pageKey,
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', label, order: 1 },
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  }
}

const REGISTRY: PageRegistryEntry[] = [
  {
    pageKey: 'board',
    label: '每日榜单',
    path: '/board',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    consumedComponentFields: { table: ['defaultSort', 'hiddenColumns'] },
    componentMeta: {
      table: {
        columns: [
          { key: 'code', label: '代码列' },
          { key: 'name', label: '名称列' },
          { key: 'score', label: '综合分' },
          { key: 'grade', label: '评级' },
          { key: 'subScores', label: '分项达标分' },
        ],
        sortFields: [
          { key: 'score', label: '综合分' },
          { key: 'rank', label: '排名' },
        ],
        sortHasDirection: false,
      },
    },
    layout: {
      pageKey: 'board',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '榜单列表', order: 1, config: { defaultSort: 'score' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'screen',
    label: '策略筛选',
    path: '/screen',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    consumedComponentFields: { result: ['defaultSort', 'hiddenColumns'] },
    componentMeta: {
      result: {
        columns: [
          { key: 'code', label: '代码列' },
          { key: 'name', label: '名称列' },
          { key: 'score', label: '综合分' },
          { key: 'grade', label: '评级' },
          { key: 'st', label: 'ST 标记' },
        ],
        sortFields: [
          { key: 'score', label: '综合分' },
          { key: 'code', label: '代码' },
        ],
        sortHasDirection: false,
      },
    },
    layout: {
      pageKey: 'screen',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'builder', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'result', component: 'data-table', region: 'main', growMain: true, label: '结果列表', order: 1, config: { defaultSort: 'score' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'stocks',
    label: '个股查询',
    path: '/stocks',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    // table=列表视图主表；groupTable=分组视图表（另一套列集，P7 迁入组件配置层，单独可寻址）。
    consumedComponentFields: { table: ['defaultSort', 'pageSize', 'hiddenColumns'], groupTable: ['hiddenColumns'] },
    componentMeta: {
      table: {
        columns: [
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
          { key: 'price', label: '股价' },
          { key: 'pct', label: '涨跌幅' },
          { key: 'groups', label: '所属分组' },
          { key: 'industry', label: '行业' },
          { key: 'board', label: '板块' },
          { key: 'status', label: '状态' },
        ],
        sortFields: [
          { key: 'pct_chg', label: '涨跌幅' },
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
          { key: 'industry', label: '行业' },
        ],
      },
      groupTable: {
        columns: [
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
          { key: 'price', label: '股价' },
          { key: 'pct', label: '涨跌幅' },
          { key: 'addDate', label: '加入日期' },
          { key: 'ret', label: '截止涨幅' },
          { key: 'lastDate', label: '截至日期' },
        ],
      },
    },
    layout: {
      pageKey: 'stocks',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'filter', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '普通查询列表', order: 1, config: { defaultSort: 'pct_chg:asc' } },
        // 分组视图表：与 table 互斥渲染（按 defaultView 模式），建模为 table 的可寻址子槽，承载独立列集，不进主流渲染。
        { id: 'groupTable', component: 'data-table', region: 'main', parentId: 'table', label: '分组视图', order: 2 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'data-quality',
    label: '数据质量',
    path: '/data/quality',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    consumedComponentFields: { table: ['defaultSort', 'hiddenColumns'] },
    componentMeta: {
      table: {
        columns: [
          { key: 'severity', label: '严重度' },
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
          { key: 'date', label: '日期' },
          { key: 'layer', label: '层' },
          { key: 'type', label: '类型' },
          { key: 'detail', label: '详情' },
          { key: 'status', label: '状态' },
          { key: 'detectedAt', label: '检出时间' },
        ],
        sortFields: [
          { key: 'time', label: '检出时间' },
          { key: 'severity', label: '严重度' },
        ],
        sortHasDirection: false,
      },
    },
    layout: {
      pageKey: 'data-quality',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '问题列表', order: 1, config: { defaultSort: 'time' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'backtest',
    label: '回测',
    path: '/backtest',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    // 逐笔表嵌套在 section 主区内（P5 建模为 parentId=body 的可寻址 data-table slot）；
    // P7 已把页面逐笔表的列显隐/排序迁入组件配置层（trades slot），消除 usePageSettings 双入口。
    supportsComponentConfig: true,
    consumedComponentFields: { trades: ['defaultSort', 'hiddenColumns'] },
    componentMeta: {
      trades: {
        columns: [
          { key: 'ret', label: '收益' },
          { key: 'hold', label: '持有日' },
          { key: 'reason', label: '卖出原因' },
          { key: 'grade', label: '买入档' },
          { key: 'rank', label: '榜单排名' },
        ],
        sortFields: [
          { key: 'entry', label: '买入日' },
          { key: 'return', label: '收益率' },
          { key: 'hold', label: '持有日' },
        ],
        sortHasDirection: false,
      },
    },
    layout: {
      pageKey: 'backtest',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
        // 逐笔成交表：嵌套在 body 分区内，进入统一可寻址模型（slots.trades.config.*），P7 已接入页面消费（排序/列显隐）。
        { id: 'trades', component: 'data-table', region: 'main', parentId: 'body', label: '逐笔成交', order: 2, config: { defaultSort: 'entry' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'training',
    label: '盘感训练',
    path: '/training',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    // 训练参数全部为业务态（§13.3 保留）；唯一配置面是设置抽屉，P5 已建模为 overlay slot（可寻址、入系统组件消费视图），
    // 抽屉组件字段消费与 settings-drawer 专属种类属 P6/P7，故 supportsComponentConfig 仍为 false。
    supportsComponentConfig: false,
    layout: {
      pageKey: 'training',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
        // 设置抽屉：overlay 区，进入统一可寻址模型，不参与主流渲染（由页面自行渲染抽屉）。
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  configEntry('config-score', '评分规则', '/system/config/score'),
  configEntry('config-trade', '买卖指标', '/system/config/trade'),
  configEntry('config-tech', '技术指标', '/system/config/tech'),
  configEntry('config-system', '系统设置', '/system/config/system'),
  {
    pageKey: 'user-manage',
    label: '用户管理',
    path: '/system/users',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    consumedComponentFields: { table: ['defaultSort', 'hiddenColumns'] },
    componentMeta: {
      table: {
        columns: [
          { key: 'email', label: '邮箱列' },
          { key: 'roles', label: '角色列' },
          { key: 'tenant', label: '租户列' },
          { key: 'status', label: '状态列' },
          { key: 'lastLogin', label: '最后登录列' },
        ],
        sortFields: [
          { key: 'created', label: '创建时间' },
          { key: 'lastLogin', label: '最后登录' },
          { key: 'account', label: '账号' },
        ],
        sortHasDirection: false,
      },
    },
    layout: {
      pageKey: 'user-manage',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '用户列表', order: 1, config: { defaultSort: 'created' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'role-manage',
    label: '角色管理',
    path: '/system/roles',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'role-manage',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'section', region: 'main', minH: 360, label: '角色权限工作台', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    // 租户管理（P7·R14）：list（筛选工具栏 + 数据表 + 分页 + 编辑弹窗）。与 user-manage 同构。
    pageKey: 'tenant-manage',
    label: '租户管理',
    path: '/system/tenants',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    consumedComponentFields: { table: ['defaultSort', 'hiddenColumns'] },
    componentMeta: {
      table: {
        columns: [
          { key: 'id', label: '租户 ID 列' },
          { key: 'admin', label: '管理员列' },
          { key: 'userCount', label: '用户数列' },
          { key: 'created', label: '创建时间列' },
        ],
        sortFields: [
          { key: 'created', label: '创建时间' },
          { key: 'name', label: '租户名' },
          { key: 'userCount', label: '用户数' },
        ],
        sortHasDirection: false,
      },
    },
    layout: {
      pageKey: 'tenant-manage',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '租户列表', order: 1, config: { defaultSort: 'created' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    // 菜单与功能管理（P6·R12+R13）：master-detail（左菜单树 draggable + 右属性表单 + 功能子表）。
    // 与 role-manage 同构——section 承载工作台内部主从布局，无 growMain（section 不能吃富余空间）。
    pageKey: 'menu-manage',
    label: '菜单与功能',
    path: '/system/menus',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'menu-manage',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'section', region: 'main', minH: 360, label: '菜单与功能工作台', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'audit-log',
    label: '审计日志',
    path: '/system/audit',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    consumedComponentFields: { auditTable: ['pageSize', 'hiddenColumns'] },
    componentMeta: {
      auditTable: {
        columns: [
          { key: 'event_time', label: '时间列' },
          { key: 'actor', label: '处理人列' },
          { key: 'event_category', label: '事件类型列' },
          { key: 'resource_code', label: '资源码列' },
          { key: 'target', label: '目标对象列' },
          { key: 'result', label: '结果列' },
          { key: 'status', label: '状态列' },
          { key: 'ip', label: 'IP 列' },
          { key: 'duration_ms', label: '耗时列' },
          { key: 'error_summary', label: '错误摘要列' },
        ],
      },
    },
    layout: {
      pageKey: 'audit-log',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'summary', component: 'kpi-grid', region: 'main', order: 1 },
        { id: 'filters', component: 'filter-bar', region: 'main', order: 2 },
        { id: 'auditTable', component: 'wide-table', region: 'main', growMain: true, label: '审计日志表', order: 3, config: { pageSize: 50 } },
        { id: 'detailDrawer', component: 'detail', region: 'overlay', label: '审计详情抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'data-dictionary',
    label: '数据字典',
    path: '/system/dicts',
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    consumedComponentFields: { itemTable: ['pageSize', 'hiddenColumns'] },
    componentMeta: {
      itemTable: {
        columns: [
          { key: 'code', label: 'code 列' },
          { key: 'label', label: '名称列' },
          { key: 'sort', label: '排序列' },
          { key: 'enabled', label: '启用列' },
          { key: 'remark', label: '备注列' },
          { key: 'updated_at', label: '更新时间列' },
        ],
      },
    },
    layout: {
      pageKey: 'data-dictionary',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', label: '数据字典工作台', order: 1 },
        { id: 'typeList', component: 'simple-list', region: 'main', parentId: 'workspace', label: '字典类型列表', order: 1 },
        { id: 'itemTable', component: 'data-table', region: 'main', parentId: 'workspace', label: '字典项表', order: 2, config: { pageSize: 50, hiddenColumns: ['remark', 'updated_at'] } },
        { id: 'typeDialog', component: 'form', region: 'overlay', label: '字典类型弹窗', order: 1 },
        { id: 'itemDialog', component: 'form', region: 'overlay', label: '字典项弹窗', order: 2 },
        { id: 'deleteConfirm', component: 'dialog', region: 'overlay', label: '删除确认', order: 3 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'stock-detail',
    label: '个股详情',
    path: '/stocks/:code',
    archetype: 'detail',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'stock-detail',
      archetype: 'detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'detail', component: 'detail', region: 'main', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'data-ingest',
    label: '数据采集',
    path: '/data/ingest',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'data-ingest',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'data-overview',
    label: '数据概览',
    path: '/data/overview',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'data-overview',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'data-schedule',
    label: '任务调度',
    path: '/data/schedule',
    archetype: 'detail',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'data-schedule',
      archetype: 'detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'layout-presets',
    label: '预设管理',
    path: '/system/layout/presets',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'layout-presets',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'section', region: 'main', scroll: 'region', minH: 360, label: '预设管理内容', order: 1 },
      ],
      editable: [],
    },
  },
  {
    pageKey: 'layout-pages',
    label: '页面布局',
    path: '/system/layout/pages',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'layout-pages',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'section', region: 'main', minH: 360, label: '页面布局工作台', order: 1 },
      ],
      editable: [],
    },
  },
  {
    pageKey: 'layout-components',
    label: '系统组件',
    path: '/system/layout/components',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    layout: {
      pageKey: 'layout-components',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'section', region: 'main', scroll: 'region', minH: 360, label: '系统组件内容', order: 1 },
      ],
      editable: [],
    },
  },
]

// P13 overlay 纳管：所有业务页面都有「页面设置抽屉」（用户层入口）。统一补登一个 overlay
// settings-drawer slot（已显式声明者跳过，如 training），使「系统组件」页能正确显示 settings-drawer
// 的消费关系（消除"暂无页面消费"的假象）。overlay slot 不进主流渲染，由各页自渲染抽屉，纯纳管/可寻址用途。
for (const entry of REGISTRY) {
  if (!entry.layout.slots.some((s) => s.component === 'settings-drawer')) {
    const overlayCount = entry.layout.slots.filter((s) => s.region === 'overlay').length
    entry.layout.slots.push({
      id: 'settings',
      component: 'settings-drawer',
      region: 'overlay',
      label: '设置抽屉',
      order: overlayCount + 1,
    })
  }
  entry.supportsComponentConfig = true
  entry.consumedComponentFields = {
    ...(entry.consumedComponentFields ?? {}),
    settings: ['size', 'bodyScroll', 'collapsibleSections', 'defaultCollapsed'],
  }
}

/** 全部已纳管页面（按注册顺序）。 */
export const PAGE_REGISTRY: readonly PageRegistryEntry[] = REGISTRY

const REGISTRY_BY_KEY = new Map(REGISTRY.map((entry) => [entry.pageKey, entry]))

/** 取页面注册项；未登记返回 undefined。 */
export function getPageEntry(pageKey: string): PageRegistryEntry | undefined {
  return REGISTRY_BY_KEY.get(pageKey)
}

/**
 * 取页面代码默认布局（深拷贝，避免调用方意外改写注册表单一事实源）。
 * 业务页面应统一用本函数取布局，不再内联手写 PageLayout。
 */
export function getPageLayout(pageKey: string): PageLayout {
  const entry = REGISTRY_BY_KEY.get(pageKey)
  if (!entry) throw new Error(`页面未登记到 pageRegistry: ${pageKey}`)
  return cloneLayout(entry.layout)
}

/** 配置中心可纳管的页面列表（当前等于全部业务页面）。 */
export function listManagedPages(): readonly PageRegistryEntry[] {
  return REGISTRY
}

/** 组件被某页某 slot 消费的一条记录。 */
export interface ComponentUsage {
  pageKey: string
  label: string
  slotId: string
}

/**
 * 列出某组件种类在已登记页面中的消费关系（哪些页面、哪些 slot 在用它）。
 * 供「系统组件」工作区展示组件消费页面（plan.md §15.2 / requirement §5.7）。
 */
export function listComponentUsage(kind: string): ComponentUsage[] {
  const out: ComponentUsage[] = []
  for (const entry of REGISTRY) {
    for (const slot of entry.layout.slots) {
      if (slot.component === kind) out.push({ pageKey: entry.pageKey, label: entry.label, slotId: slot.id })
    }
  }
  return out
}
