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
 * 布局配置平台页（视觉预设/页面布局/系统组件）也纳入注册表，保证「页面布局」工作台能查看和配置这些系统页面。
 */
import type { Archetype, EditableKnob, PageLayout, SlotSpec } from './schema'
import { cloneLayout } from './path'
import { CONFIG_SYSTEM_COLLAPSE_SECTIONS, CONFIG_SYSTEM_GROUP_TABS } from './configPanel'
import {
  getApplicableComponentFieldDefs,
  type ComponentConfigLayer,
  type ComponentSlotConfigMeta,
} from './componentConfig'
import { createDefaultStockChartPreferences } from '@/composables/useStockChartPreferences'

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
   * 页面类型的目标响应式画像，用于表达设计意图和配置中心摘要。
   * 实际列数/重排由 layout.responsive 决定，滚动由 LayoutHost 决定，
   * 浏览器可用性以关键视口 E2E 为准；配置中心不得把本字段展示成已验证结论。
   */
  responsiveProfile: ResponsiveProfile
  /**
   * 是否开放页面级个人设置入口。默认 true；平台布局管理页只管理系统配置，
   * 不消费 page/user 覆盖时必须显式为 false，避免登记 settings-drawer 假能力。
   */
  supportsPageSettings?: boolean
  /** 是否开放组件特性配置层；字段由 slot.component 自动继承，不再逐页面登记。 */
  supportsComponentConfig: boolean
  /**
   * 组件配置自动渲染元数据（slotId -> 列/可交互排序字段），驱动设置抽屉「组件设置」段自动生成
   * （列显隐开关、默认排序下拉），并作为页面列头排序能力的事实源。
   * 登记 sortFields 的 slot 必须消费 defaultSort，页面表格也必须接入列头排序；
   * sortFields 须与页面侧可排序列白名单（useTableSort 的 allowedFields 等）双向一致，
   * 反向漂移由 pageRegistry.spec.ts 契约测试拦截。
   */
  componentMeta?: Record<string, SlotConfigMeta>
}

/** 某 slot 的组件配置自动渲染元数据。 */
export interface SlotConfigMeta extends ComponentSlotConfigMeta {
  /** 可显隐的列（驱动 hiddenColumns 开关组；key 为列标识、label 为中文名）。 */
  columns?: { key: string; label: string }[]
  /** 可交互排序字段，同时作为 defaultSort 下拉候选；key 可与列 key 不同，如 pct_chg。 */
  sortFields?: { key: string; label: string }[]
  /**
   * defaultSort 是否含方向（升/降）。
   * true（默认）：值形如 `field:order`，渲染字段选择 + 方向选择（如 StocksView）。
   * false：值就是 sortFields 的 key（排序模式枚举，无方向，如 BoardView 的 score/rank）。
   */
  sortHasDirection?: boolean
  /** 可选的 Tab 项（驱动 tabs.defaultActive 选择；key 为 tab name、label 为中文名）。 */
  tabs?: { key: string; label: string }[]
  /** 可折叠分区项（驱动 config-panel/defaultCollapsed 选择；key 为折叠节点 key、label 为中文名）。 */
  collapseSections?: { key: string; label: string }[]
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
    pageKey: 'limit-ladder',
    label: '连板天梯',
    path: '/limit-ladder',
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: true },
          masterRatioProfiles: { enabled: true },
        },
      },
    },
    layout: {
      pageKey: 'limit-ladder',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', minH: 360, label: '连板天梯研究工作台', order: 1 },
        { id: 'ladder', component: 'section', region: 'main', parentId: 'workspace', label: '天梯分层', order: 1 },
        { id: 'analysis', component: 'chart', region: 'main', parentId: 'workspace', label: '股票走势分析', order: 2, config: { stockChart: createDefaultStockChartPreferences() } },
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'board',
    label: '每日榜单',
    path: '/board',
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: true },
          masterRatioProfiles: { enabled: true },
        },
      },
      table: {
        columns: [
          { key: 'code', label: '代码列' },
          { key: 'name', label: '名称列' },
          { key: 'board', label: '板块' },
          { key: 'score', label: '综合分' },
          { key: 'grade', label: '评级' },
          { key: 'subScores', label: '分项达标分' },
          { key: 'relatedIndustry', label: '行业走势' },
          { key: 'relatedConcept', label: '概念走势' },
        ],
        sortFields: [
          { key: 'score', label: '综合分' },
          { key: 'rank', label: '排名' },
          { key: 'code', label: '代码' },
        ],
        sortHasDirection: false,
      },
      chart: {
        fieldApplicability: {
          minHeight: { enabled: false, reason: '主从工作台图表随剩余空间成长，不使用固定区域高度' },
        },
      },
    },
    layout: {
      pageKey: 'board',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', minH: 360, label: '榜单股票行情工作台', order: 1 },
        { id: 'table', component: 'wide-table', region: 'main', parentId: 'workspace', label: '榜单列表', order: 1, config: { pagination: false, defaultSort: 'score' } },
        { id: 'chart', component: 'chart', region: 'main', parentId: 'workspace', label: '股票走势分析', order: 2, config: { stockChart: createDefaultStockChartPreferences() } },
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
    componentMeta: {
      result: {
        columns: [
          { key: 'code', label: '代码列' },
          { key: 'name', label: '名称列' },
          { key: 'score', label: '综合分' },
          { key: 'grade', label: '评级' },
          { key: 'st', label: 'ST 标记' },
          { key: 'relatedIndustry', label: '行业走势' },
          { key: 'relatedConcept', label: '概念走势' },
        ],
        sortFields: [
          { key: 'score', label: '综合分' },
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
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
        { id: 'result', component: 'data-table', region: 'main', growMain: true, label: '结果列表', order: 1, config: { pagination: false, defaultSort: 'score' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'stocks',
    label: '个股查询',
    path: '/stocks',
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    // table=列表视图主表；groupTable=分组视图表，两者按组件种类自动继承字段并单独寻址。
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: true },
          masterRatioProfiles: { enabled: true },
        },
      },
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
          { key: 'relatedIndustry', label: '行业走势' },
          { key: 'relatedConcept', label: '概念走势' },
        ],
        sortFields: [
          { key: 'pct_chg', label: '涨跌幅' },
          { key: 'close', label: '股价' },
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
          { key: 'relatedIndustry', label: '行业走势' },
          { key: 'relatedConcept', label: '概念走势' },
        ],
        sortFields: [
          { key: 'add_date', label: '加入日期' },
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
          { key: 'price', label: '股价' },
          { key: 'pct_chg', label: '涨跌幅' },
          { key: 'ret', label: '截止涨幅' },
          { key: 'last_date', label: '截至日期' },
        ],
      },
      chart: {
        fieldApplicability: {
          minHeight: { enabled: false, reason: '查询工作台图表随主从区域成长，不使用固定区域高度' },
        },
      },
    },
    layout: {
      pageKey: 'stocks',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'filter', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', minH: 360, label: '个股行情分析工作台', order: 1 },
        { id: 'table', component: 'wide-table', region: 'main', parentId: 'workspace', label: '普通查询列表', order: 1, config: { pagination: true, defaultSort: 'pct_chg:asc' } },
        // 分组视图表：与 table 互斥渲染（按 defaultView 模式），建模为 table 的可寻址子槽，承载独立列集，不进主流渲染。
        { id: 'groupTable', component: 'wide-table', region: 'main', parentId: 'workspace', label: '分组视图', order: 2, config: { pagination: true, defaultSort: 'add_date:asc' } },
        { id: 'chart', component: 'chart', region: 'main', parentId: 'workspace', label: '股票走势分析', order: 3, config: { stockChart: createDefaultStockChartPreferences() } },
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
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '问题列表', order: 1, config: { pagination: true, defaultSort: 'time:desc' } },
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
    // 逐笔表的列显隐/排序由 data-table 组件字段自动继承，消除 usePageSettings 双入口。
    supportsComponentConfig: true,
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
          { key: 'exit', label: '卖出日' },
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
        { id: 'trades', component: 'data-table', region: 'main', parentId: 'body', label: '逐笔成交', order: 2, config: { pagination: false, defaultSort: 'entry' } },
        { id: 'chart', component: 'chart', region: 'main', parentId: 'body', label: '交易回放图表', order: 3, config: { stockChart: createDefaultStockChartPreferences() } },
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
    // 训练参数保留为业务态；训练历史表的排序/每页条数与图表区域高度进入组件配置层。
    supportsComponentConfig: true,
    componentMeta: {
      history: {
        sortFields: [
          { key: 'created_at', label: '开始时间' },
          { key: 'completed_at', label: '结束时间' },
          { key: 'score', label: '评分' },
          { key: 'total_return', label: '收益' },
          { key: 'win_rate', label: '胜率' },
        ],
      },
    },
    layout: {
      pageKey: 'training',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        // body 槽统一走成长区（grow 策略）：各阶段收尾块（config 历史表 / running 成交明细 / result 复盘卡）
        // 吃满剩余高度，余量不足时主内容区滚动兜底（见 TrainingView）。
        { id: 'body', component: 'section', region: 'main', order: 1 },
        { id: 'history', component: 'data-table', region: 'main', parentId: 'body', label: '训练历史', order: 2, config: { pagination: true, defaultSort: 'created_at:desc' } },
        // 训练台/结算的 K 线工作区：进入统一可寻址模型（slots.chart.config.*），承载「图表区域高度」等组件特性。
        { id: 'chart', component: 'chart', region: 'main', parentId: 'body', label: '训练图表', order: 3, config: { minHeight: 650, stockChart: createDefaultStockChartPreferences() } },
        // 设置抽屉：overlay 区，进入统一可寻址模型，不参与主流渲染（由页面自行渲染抽屉）。
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'trade-discipline',
    label: '交易纪律',
    path: '/trade-discipline',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      history: {
        sortFields: [{ key: 'trade_date', label: '交易日' }],
        columns: [
          { key: 'trade_date', label: '交易日' },
          { key: 'rule_name', label: '规则' },
          { key: 'assessment', label: '履约结果' },
          { key: 'operation_count', label: '操作数' },
          { key: 'reason_name_snapshot', label: '违规摘要' },
          { key: 'current_revision_no', label: '修订' },
          { key: 'updated_at', label: '最后更新' },
        ],
      },
    },
    layout: {
      pageKey: 'trade-discipline',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'workspaceTabs', component: 'tabs', region: 'main', growMain: true, label: '交易纪律业务页签', order: 1 },
        { id: 'checkinPanel', component: 'section', region: 'main', parentId: 'workspaceTabs', label: '今日打卡', order: 1 },
        { id: 'rulesPanel', component: 'section', region: 'main', parentId: 'workspaceTabs', label: '规则管理', order: 2 },
        { id: 'history', component: 'data-table', region: 'main', parentId: 'workspaceTabs', label: '历史记录', order: 3, config: { pagination: true, defaultSort: 'trade_date:desc', pageSize: 20 } },
        { id: 'historyDetail', component: 'detail', region: 'overlay', label: '履约修订详情抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  configEntry('config-score', '评分规则', '/system/config/score'),
  configEntry('config-trade', '买卖指标', '/system/config/trade'),
  {
    pageKey: 'config-tech',
    label: '技术指标',
    path: '/system/config/tech',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      techTable: {
        sortFields: [
          { key: 'catOrder', label: '分类' },
          { key: 'name_cn', label: '名称' },
          { key: 'typeLabel', label: '类型' },
          { key: 'srcLabel', label: '来源' },
          { key: 'hasParams', label: '有无参数' },
        ],
      },
    },
    layout: {
      pageKey: 'config-tech',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', label: '技术指标', order: 1 },
        { id: 'techFilters', component: 'filter-bar', region: 'main', parentId: 'body', label: '技术指标筛选', order: 1 },
        { id: 'techTable', component: 'data-table', region: 'main', parentId: 'body', label: '技术指标表', order: 2, config: { pagination: false, defaultSort: 'catOrder:asc' } },
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'config-system',
    label: '系统设置',
    path: '/system/config/system',
    archetype: 'workbench',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      configPanel: {
        collapseSections: CONFIG_SYSTEM_COLLAPSE_SECTIONS,
      },
      sysTabs: {
        tabs: CONFIG_SYSTEM_GROUP_TABS.map((tab) => ({ key: tab.key, label: tab.label })),
      },
    },
    layout: {
      pageKey: 'config-system',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', label: '系统设置', order: 1 },
        { id: 'configPanel', component: 'config-panel', region: 'main', parentId: 'body', label: '系统设置面板', order: 2 },
        // 系统设置分组页签（访问安全/数据治理/研究运行）：defaultActive 进组件配置层，页面 el-tabs 联动。
        { id: 'sysTabs', component: 'tabs', region: 'main', parentId: 'body', label: '系统设置分组页签', order: 3, config: { defaultActive: 'access' } },
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'user-manage',
    label: '用户管理',
    path: '/system/users',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    componentMeta: {
      table: {
        columns: [
          { key: 'email', label: '邮箱列' },
          { key: 'roles', label: '角色列' },
          { key: 'tenant', label: '租户列' },
          { key: 'status', label: '状态列' },
          { key: 'lastLogin', label: '最后登录列' },
          { key: 'created', label: '创建时间列' },
        ],
        sortFields: [
          { key: 'created', label: '创建时间' },
          { key: 'lastLogin', label: '最后登录' },
          { key: 'account', label: '账号' },
          { key: 'tenant', label: '租户' },
        ],
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
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '用户列表', order: 1, config: { pagination: true, defaultSort: 'created:desc' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'role-manage',
    label: '角色管理',
    path: '/system/roles',
    archetype: 'master-detail',
    responsiveProfile: 'single-column',
    supportsComponentConfig: false,
    componentMeta: {
      content: {
        fieldApplicability: {
          masterRatio: { enabled: false, reason: '角色权限页使用独立树表布局，尚未接入行情主从工作台' },
          masterRatioProfiles: { enabled: false, reason: '角色权限页使用独立树表布局，尚未接入行情主从工作台' },
        },
      },
    },
    layout: {
      pageKey: 'role-manage',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'master-detail', region: 'main', minH: 360, label: '角色权限工作台', order: 1 },
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
        { id: 'table', component: 'data-table', region: 'main', growMain: true, label: '租户列表', order: 1, config: { pagination: true, defaultSort: 'created:desc' } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    // 菜单与功能管理（P6·R12+R13）：master-detail（左菜单树 draggable + 右属性表单 + 功能子表）。
    pageKey: 'menu-manage',
    label: '菜单与功能',
    path: '/system/menus',
    archetype: 'master-detail',
    responsiveProfile: 'single-column',
    supportsComponentConfig: true,
    componentMeta: {
      content: {
        fieldApplicability: {
          masterRatio: { enabled: false, reason: '菜单编辑页的左树右表单由业务页自主编排，不消费行情主从工作台' },
          masterRatioProfiles: { enabled: false, reason: '菜单编辑页的左树右表单由业务页自主编排，不消费行情主从工作台' },
        },
      },
      resourceTable: {
        columns: [
          { key: 'code', label: '功能码' },
          { key: 'name', label: '名称' },
          { key: 'type', label: '类型' },
          { key: 'apiPath', label: '绑定接口' },
        ],
      },
    },
    layout: {
      pageKey: 'menu-manage',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'head', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'master-detail', region: 'main', minH: 360, label: '菜单与功能工作台', order: 1 },
        { id: 'resourceTable', component: 'wide-table', region: 'main', parentId: 'content', label: '功能点表', order: 2, config: { pagination: false } },
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
        sortFields: [
          { key: 'event_time', label: '时间' },
          { key: 'event_category', label: '事件类型' },
          { key: 'result', label: '结果' },
          { key: 'status', label: '状态' },
          { key: 'duration_ms', label: '耗时' },
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
        { id: 'auditTable', component: 'wide-table', region: 'main', growMain: true, label: '审计日志表', order: 3, config: { pagination: true, defaultSort: 'event_time:desc', pageSize: 50 } },
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
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: false, reason: '数据字典页的左导航右表格由业务页自主编排，不消费行情主从工作台' },
          masterRatioProfiles: { enabled: false, reason: '数据字典页的左导航右表格由业务页自主编排，不消费行情主从工作台' },
        },
      },
      itemTable: {
        columns: [
          { key: 'code', label: 'code 列' },
          { key: 'label', label: '名称列' },
          { key: 'color', label: '颜色列' },
          { key: 'sort', label: '排序列' },
          { key: 'enabled', label: '启用列' },
          { key: 'remark', label: '备注列' },
          { key: 'updated_at', label: '更新时间列' },
        ],
        sortFields: [
          { key: 'sort', label: '排序' },
          { key: 'code', label: 'code' },
          { key: 'label', label: '名称' },
          { key: 'enabled', label: '启用' },
          { key: 'updated_at', label: '更新时间' },
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
        { id: 'itemTable', component: 'data-table', region: 'main', parentId: 'workspace', label: '字典项表', order: 2, config: { pagination: true, defaultSort: 'sort:asc', pageSize: 50, hiddenColumns: ['remark', 'updated_at'] } },
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
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: true },
          masterRatioProfiles: { enabled: true },
        },
      },
      chart: {
        fieldApplicability: {
          minHeight: { enabled: false, reason: '详情图表随双栏工作区可用高度成长，不使用固定区域高度' },
        },
      },
    },
    layout: {
      pageKey: 'stock-detail',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'quoteSummary', component: 'section', region: 'main', label: '个股行情摘要', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', minH: 360, label: '个股详情双栏工作台', order: 2, config: { masterRatio: 65, masterRatioProfiles: { profiles: [] } } },
        { id: 'chart', component: 'chart', region: 'main', parentId: 'workspace', label: '个股行情', order: 1, config: { stockChart: createDefaultStockChartPreferences() } },
        { id: 'relatedBoards', component: 'section', region: 'main', parentId: 'workspace', label: '所属板块', order: 2 },
        { id: 'indicatorSnapshot', component: 'section', region: 'main', parentId: 'workspace', label: '最新指标快照', order: 3 },
        { id: 'tradeEvaluation', component: 'section', region: 'main', parentId: 'workspace', label: '买卖信号评估', order: 4 },
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '设置抽屉', order: 1 },
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
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        tabs: [
          { key: 'tasks', label: '任务中心' },
          { key: 'logs', label: '采集日志' },
        ],
      },
      taskTable: {
        sortFields: [
          { key: 'time', label: '截止时间' },
          { key: 'type', label: '任务类型' },
          { key: 'status', label: '任务状态' },
        ],
      },
      logTable: {
        sortFields: [
          { key: 'time', label: '时间' },
          { key: 'table', label: '目标表' },
          { key: 'status', label: '结果' },
        ],
      },
    },
    layout: {
      pageKey: 'data-ingest',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
        { id: 'workspace', component: 'tabs', region: 'main', growMain: true, label: '采集任务工作区', order: 2, config: { defaultActive: 'tasks' } },
        { id: 'taskTable', component: 'data-table', region: 'main', parentId: 'workspace', label: '任务中心', order: 3, config: { pagination: true, defaultSort: 'time:desc' } },
        { id: 'logTable', component: 'data-table', region: 'main', parentId: 'workspace', label: '采集日志', order: 4, config: { pagination: true, defaultSort: 'time:desc' } },
        { id: 'ingestExecutionDialog', component: 'form', region: 'overlay', label: '采集执行弹窗', order: 1 },
        { id: 'resultMaintenanceDialog', component: 'form', region: 'overlay', label: '结果维护执行弹窗', order: 2 },
        { id: 'taskLogDrawer', component: 'detail', region: 'overlay', label: '任务日志抽屉', order: 3 },
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
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        tabs: [
          { key: 'assets', label: '数据资产' },
          { key: 'stocks', label: '逐股分层体检' },
          { key: 'board', label: '板块数据' },
        ],
      },
      assetTable: {
        columns: [
          { key: 'database', label: '数据库' },
          { key: 'name', label: '中文名' },
          { key: 'table', label: '物理表' },
          { key: 'category', label: '业务分类' },
          { key: 'lifecycle', label: '生命周期' },
          { key: 'rowCount', label: '行数' },
          { key: 'dataSource', label: '数据源' },
          { key: 'latestTime', label: '最新业务日' },
          { key: 'freshness', label: '鲜活度' },
          { key: 'qualityIssues', label: '质量问题' },
          { key: 'ownershipScope', label: '归属范围' },
          { key: 'storageBytes', label: '表及索引空间' },
        ],
      },
    },
    layout: {
      pageKey: 'data-overview',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'summary', component: 'kpi-grid', region: 'main', label: '核心指标', order: 1 },
        { id: 'quality', component: 'stat-strip', region: 'main', label: '四层质量摘要', order: 2 },
        { id: 'workspace', component: 'tabs', region: 'main', growMain: true, label: '数据治理工作区', order: 3, config: { defaultActive: 'assets' } },
        { id: 'assetTable', component: 'wide-table', region: 'main', parentId: 'workspace', label: '数据资产表', order: 4, config: { pagination: false, hiddenColumns: [] } },
        { id: 'stockTable', component: 'data-table', region: 'main', parentId: 'workspace', label: '逐股分层体检表', order: 5, config: { pagination: true } },
        { id: 'settings', component: 'settings-drawer', region: 'overlay', label: '页面设置', order: 6 },
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
    supportsComponentConfig: true,
    componentMeta: {
      jobTable: {
        columns: [
          { key: 'name', label: '名称' },
          { key: 'taskType', label: '任务类型' },
          { key: 'freq', label: '触发规则' },
          { key: 'tradingDay', label: '仅交易日' },
          { key: 'enabled', label: '启用' },
          { key: 'nextRun', label: '下次触发' },
          { key: 'lastRun', label: '最近触发' },
          { key: 'retry', label: '自身重试' },
        ],
        sortFields: [
          { key: 'name', label: '名称' },
          { key: 'freq', label: '触发规则' },
        ],
      },
      sourceTable: {
        columns: [
          { key: 'source', label: '数据源' },
          { key: 'role', label: '角色' },
          { key: 'status', label: '状态' },
          { key: 'lastSuccess', label: '最近成功' },
          { key: 'timeout', label: '超时' },
        ],
      },
    },
    layout: {
      pageKey: 'data-schedule',
      archetype: 'detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'body', component: 'section', region: 'main', order: 1 },
        { id: 'jobTable', component: 'data-table', region: 'main', parentId: 'body', label: '定时任务', order: 2, config: { pagination: false, defaultSort: 'name:asc' } },
        { id: 'sourceTable', component: 'data-table', region: 'main', parentId: 'body', label: '数据源健康', order: 3, config: { pagination: false } },
        { id: 'triggerEvents', component: 'detail', region: 'overlay', label: '触发记录抽屉', order: 4 },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'layout-presets',
    label: '视觉预设',
    path: '/system/layout/presets',
    archetype: 'list',
    responsiveProfile: 'single-column',
    supportsPageSettings: false,
    supportsComponentConfig: false,
    layout: {
      pageKey: 'layout-presets',
      archetype: 'list',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'table', component: 'data-table', region: 'main', growMain: true, minH: 360, label: '预设列表', order: 1, config: { pagination: false } },
      ],
      editable: [],
    },
  },
  {
    pageKey: 'layout-pages',
    label: '页面布局',
    path: '/system/layout/pages',
    archetype: 'workbench',
    responsiveProfile: 'single-column',
    supportsPageSettings: false,
    supportsComponentConfig: false,
    layout: {
      pageKey: 'layout-pages',
      archetype: 'workbench',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'content', component: 'tabs', region: 'main', growMain: true, minH: 360, label: '页面布局工作台', order: 1 },
      ],
      editable: [],
    },
  },
  {
    pageKey: 'layout-components',
    label: '系统组件',
    path: '/system/layout/components',
    archetype: 'detail',
    responsiveProfile: 'single-column',
    supportsPageSettings: false,
    supportsComponentConfig: false,
    layout: {
      pageKey: 'layout-components',
      archetype: 'detail',
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
  {
    pageKey: 'sectors',
    label: '板块行情',
    path: '/sectors',
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: true },
          masterRatioProfiles: { enabled: true },
        },
      },
      table: {
        columns: [
          { key: 'name', label: '板块名称' },
          { key: 'pct_today', label: '今日涨幅' },
          { key: 'pct_5d', label: '5日涨幅' },
          { key: 'pct_10d', label: '10日涨幅' },
          { key: 'pct_20d', label: '20日涨幅' },
          { key: 'net_inflow', label: '即时净流入' },
          { key: 'net_inflow_3d', label: '3日净流入' },
          { key: 'net_inflow_5d', label: '5日净流入' },
          { key: 'net_inflow_10d', label: '10日净流入' },
          { key: 'net_inflow_20d', label: '20日净流入' },
        ],
        sortFields: [
          { key: 'pct_today', label: '今日涨幅' },
          { key: 'pct_5d', label: '5日涨幅' },
          { key: 'pct_10d', label: '10日涨幅' },
          { key: 'pct_20d', label: '20日涨幅' },
          { key: 'net_inflow', label: '即时净流入' },
          { key: 'net_inflow_3d', label: '3日净流入' },
          { key: 'net_inflow_5d', label: '5日净流入' },
          { key: 'net_inflow_10d', label: '10日净流入' },
          { key: 'net_inflow_20d', label: '20日净流入' },
          { key: 'up_count', label: '上涨家数' },
        ],
      },
      chart: {
        fieldApplicability: {
          minHeight: { enabled: false, reason: '板块主从工作台图表随剩余空间成长，不使用固定区域高度' },
        },
      },
    },
    layout: {
      pageKey: 'sectors',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'filter', component: 'filter-bar', region: 'action', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', minH: 360, label: '板块强弱分析工作台', order: 1 },
        {
          id: 'table',
          component: 'wide-table',
          region: 'main',
          parentId: 'workspace',
          label: '板块强弱排行',
          order: 1,
          config: {
            pagination: true,
            defaultSort: 'pct_today:desc',
            pageSize: 20,
            hiddenColumns: ['pct_20d', 'net_inflow_3d', 'net_inflow_5d', 'net_inflow_10d', 'net_inflow_20d'],
          },
        },
        { id: 'chart', component: 'chart', region: 'main', parentId: 'workspace', label: '板块走势分析', order: 2, config: { stockChart: createDefaultStockChartPreferences() } },
      ],
      editable: [densityKnob()],
    },
  },
  {
    pageKey: 'sectors-detail',
    label: '板块详情',
    path: '/sectors/:code',
    archetype: 'master-detail',
    responsiveProfile: 'mixed-panel',
    supportsComponentConfig: true,
    componentMeta: {
      workspace: {
        fieldApplicability: {
          masterRatio: { enabled: true },
          masterRatioProfiles: { enabled: true },
        },
      },
      chart: {
        fieldApplicability: {
          minHeight: { enabled: false, reason: '详情图表随双栏工作区可用高度成长，不使用固定区域高度' },
        },
      },
      memberTable: {
        columns: [
          { key: 'code', label: '代码' },
          { key: 'name', label: '名称' },
          { key: 'price', label: '现价' },
          { key: 'pct', label: '涨跌幅' },
          { key: 'turnover', label: '换手率' },
        ],
        sortFields: [
          { key: 'pct', label: '涨跌幅' },
          { key: 'price', label: '现价' },
          { key: 'code', label: '代码' },
        ],
      },
    },
    layout: {
      pageKey: 'sectors-detail',
      archetype: 'master-detail',
      hasActionRegion: true,
      density: 'standard',
      responsive: singleColumn(),
      slots: [
        { id: 'toolbar', component: 'toolbar', region: 'action', order: 1 },
        { id: 'workspace', component: 'master-detail', region: 'main', minH: 360, label: '板块详情双栏工作台', order: 1, config: { masterRatio: 65, masterRatioProfiles: { profiles: [] } } },
        { id: 'summary', component: 'section', region: 'main', parentId: 'workspace', label: '板块行情摘要', order: 1 },
        { id: 'chart', component: 'chart', region: 'main', parentId: 'workspace', label: '板块走势', order: 1, config: { stockChart: createDefaultStockChartPreferences() } },
        { id: 'memberTable', component: 'data-table', region: 'main', parentId: 'workspace', label: '成分股', order: 2, config: { pagination: true, defaultSort: 'pct:desc', pageSize: 20 } },
      ],
      editable: [densityKnob()],
    },
  },
]

/** 合并组件实例元数据与可从 slot.config 稳定推导的适用性。 */
export function componentMetaForSlot(entry: PageRegistryEntry, slot: SlotSpec): SlotConfigMeta {
  const declared = entry.componentMeta?.[slot.id] ?? {}
  const fieldApplicability = { ...(declared.fieldApplicability ?? {}) }
  if (slot.component === 'data-table' || slot.component === 'wide-table') {
    const pagination = slot.config?.pagination
    fieldApplicability.pageSize = pagination === true
      ? { enabled: true }
      : { enabled: false, reason: '该组件实例不承载分页，分页大小不适用' }
  }
  if (slot.component === 'chart' && !fieldApplicability.minHeight) {
    fieldApplicability.minHeight = typeof slot.config?.minHeight === 'number'
      ? { enabled: true }
      : { enabled: false, reason: '该图表实例未声明固定区域高度' }
  }
  if (slot.component === 'chart' && !fieldApplicability.stockChart) {
    fieldApplicability.stockChart = slot.config?.stockChart
      ? { enabled: true }
      : { enabled: false, reason: '该图表实例不是股票 K 线多图工作区' }
  }
  return { ...declared, fieldApplicability }
}

/** 页面 slot 自动继承的组件字段；页面和抽屉不得维护第二套字段白名单。 */
export function applicableComponentFields(
  entry: PageRegistryEntry,
  slotId: string,
  layer?: ComponentConfigLayer,
) {
  const slot = entry.layout.slots.find((candidate) => candidate.id === slotId)
  if (!slot) return []
  return getApplicableComponentFieldDefs(slot.component, componentMetaForSlot(entry, slot), layer)
}

// overlay 纳管：开放个人设置的业务页面统一补登 settings-drawer；平台布局管理页
// 显式 supportsPageSettings=false，只管理系统配置，不声明 page/user 设置能力。
for (const entry of REGISTRY) {
  if (entry.supportsPageSettings === false) continue
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
