// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { computed, defineComponent, h, KeepAlive, nextTick, reactive, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import type { Bar, IndicatorRow } from '@/api/stocks'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'
import StockChartSettingSection from '@/components/StockChartSettingSection.vue'
import {
  chartCompositionKey,
  normalizeStockChartPreferences,
  setAuxiliaryChartType,
  visibleChartTypes,
} from '@/composables/useStockChartPreferences'

const pageSettingsState = vi.hoisted(() => ({
  current: null as any,
  reset: vi.fn(),
}))
const resetLayout = vi.hoisted(() => vi.fn())
const componentConfigState = vi.hoisted(() => ({ current: null as any }))

function defaultChartConfig() {
  return {
    slot2: 'volume',
    slot3: 'macd',
    heightRatios: {
      kline: [1],
      'kline|volume': [0.75, 0.25],
      'kline|macd': [0.75, 0.25],
      'kline|volume|macd': [0.6, 0.2, 0.2],
      'kline|macd|volume': [0.6, 0.2, 0.2],
    },
  }
}

vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => {
    componentConfigState.current ??= reactive(defaultChartConfig())
    return ({
    effective: {},
    knobs: [],
    setKnob: vi.fn(),
    valueOf: vi.fn(),
    sourceOf: vi.fn(),
    isDirty: ref(false),
    resetAll: () => {
      resetLayout()
      Object.assign(componentConfigState.current, defaultChartConfig())
    },
    componentValueOf: vi.fn((_slotId: string, field: string) => (
      field === 'stockChart' ? componentConfigState.current : field === 'minHeight' ? 650 : undefined
    )),
    setComponentKnob: vi.fn((_slotId: string, field: string, value: unknown) => {
      if (field !== 'stockChart') return
      for (const key of Object.keys(componentConfigState.current)) delete componentConfigState.current[key]
      Object.assign(componentConfigState.current, structuredClone(value))
    }),
    componentSourceOf: vi.fn(() => 'default'),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
    remoteHydrated: ref(true),
    whenRemoteHydrated: async () => undefined,
    saveRemoteUserConfig: async () => undefined,
    remoteSaveError: ref(false),
  })
  },
}))

vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: (_key: string, defaults: Record<string, unknown>) => {
    pageSettingsState.current ??= reactive(structuredClone(defaults))
    pageSettingsState.reset = vi.fn(() => {
      for (const key of Object.keys(pageSettingsState.current)) {
        delete pageSettingsState.current[key]
      }
      Object.assign(pageSettingsState.current, structuredClone(defaults))
    })
    return {
      settings: pageSettingsState.current,
      isDirty: ref(false),
      reset: pageSettingsState.reset,
      hydrated: ref(true),
    }
  },
}))

// 每次调用返回独立 prefs：避免未卸载组件实例经共享单例串扰（真实单例行为对这些断言无意义）。
vi.mock('@/composables/useKlinePrefs', () => ({
  useKlinePrefs: () => {
    const prefs = reactive({ defaultPeriod: 120 })
    return { validDefault: computed(() => prefs.defaultPeriod), prefs }
  },
}))

vi.mock('@/api/stocks', () => ({
  getBars: vi.fn(),
  getIndicators: vi.fn(),
  getTradeEval: vi.fn(),
  getIntraday: vi.fn(),
  getStockBoardMembership: vi.fn(),
  getStockQuoteSummary: vi.fn(),
  listStocks: vi.fn(),
}))

vi.mock('@/api/stockGroup', () => ({
  addMembers: vi.fn(),
  getGroup: vi.fn(),
  listGroups: vi.fn(),
  removeMembers: vi.fn(),
}))

vi.mock('@/api/tradeProfile', () => ({
  listTradeProfiles: vi.fn(),
}))

import * as stocksApi from '@/api/stocks'
import * as stockGroupApi from '@/api/stockGroup'
import * as tradeProfileApi from '@/api/tradeProfile'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import StockGroupFavoriteButton from '@/components/StockGroupFavoriteButton.vue'
import StockDetailView from '@/views/StockDetailView.vue'

const StockChartWorkspaceStub = defineComponent({
  name: 'StockChartWorkspace',
  props: [
    'bars',
    'warmupBars',
    'indicators',
    'slot2',
    'slot3',
    'heightRatios',
    'minHeight',
    'fitAvailableHeight',
    'adjustLabel',
    'macdAdjustLabel',
    'macdState',
    'macdError',
    'enableIntradayDrilldown',
    'showKlineTooltip',
  ],
  emits: ['retryMacd', 'ratioDraft', 'ratioCommit', 'barClick', 'activeBarChange'],
  setup(props, { emit, slots }) {
    return () => h('section', {
      'data-testid': 'stock-chart-workspace',
      'data-min-height': props.minHeight,
      'data-macd-state': props.macdState,
      'data-adjust-label': props.adjustLabel,
      'data-macd-adjust-label': props.macdAdjustLabel,
      'data-show-kline-tooltip': String(props.showKlineTooltip),
    }, [
      h('span', { 'data-testid': 'workspace-close' },
        String((props.bars as Bar[] | undefined)?.at(-1)?.close ?? '')),
      h('span', { 'data-testid': 'workspace-macd-error' }, String(props.macdError || '')),
      slots['header-actions']?.(),
      h('button', {
        'data-testid': 'retry-macd',
        onClick: () => emit('retryMacd'),
      }, '重试 MACD'),
      h('button', {
        'data-testid': 'open-intraday',
        onClick: () => emit('barClick', '2026-08-07'),
      }, '打开分时'),
      h('button', {
        'data-testid': 'activate-kline-bar',
        onClick: () => emit('activeBarChange', bar('2026-07-22', 9.5)),
      }, '联动行情摘要'),
      h('button', {
        'data-testid': 'ratio-draft',
        onClick: () => emit('ratioDraft', [0.5, 0.3, 0.2]),
      }, '调整高度草稿'),
      h('button', {
        'data-testid': 'ratio-commit',
        onClick: () => emit('ratioCommit', [0.5, 0.3, 0.2]),
      }, '提交高度'),
    ])
  },
})

const AppSplitWorkspaceStub = defineComponent({
  name: 'AppSplitWorkspace',
  props: ['secondaryVisible', 'defaultPrimaryRatio', 'primaryRatioProfiles'],
  emits: ['update:secondaryVisible', 'primaryRatioChange', 'primaryRatioSampleChange'],
  setup(props, { expose, slots }) {
    expose({ openCompactSecondary: () => false, closeCompactSecondary: () => undefined })
    return () => h('section', { 'data-testid': 'stock-detail-workspace' }, [
      h('div', { 'data-testid': 'stock-detail-primary' }, slots.primary?.({ compact: false })),
      props.secondaryVisible
        ? h('div', { 'data-testid': 'stock-detail-secondary' }, slots.secondary?.())
        : null,
    ])
  },
})

const PageSettingsDrawerStub = defineComponent({
  name: 'PageSettingsDrawer',
  props: ['businessVisible', 'config', 'componentRuntimeValueOf'],
  emits: ['reset'],
  setup(_props, { emit, slots }) {
    return () => {
      const config = (_props as any).config
      const value = normalizeStockChartPreferences(config.componentValueOf('chart', 'stockChart'))
      const key = chartCompositionKey(value)
      const runtime = normalizeStockChartPreferences(
        (_props as any).componentRuntimeValueOf?.('chart', 'stockChart') ?? value,
      )
      return h('aside', { 'data-testid': 'page-settings-drawer' }, [
      h(StockChartSettingSection, {
        slot2: value.slot2,
        slot3: value.slot3,
        chartTypes: visibleChartTypes(value),
        defaultRatios: value.heightRatios[key],
        currentRatios: runtime.heightRatios[key],
        canApplyCurrentRatios: true,
        testIdPrefix: 'component-chart-stock-chart',
        onChange: (slot: 'slot2' | 'slot3', next: unknown) => config.setComponentKnob(
          'chart', 'stockChart', setAuxiliaryChartType(value, slot, next),
        ),
        onSaveDefaultRatios: (ratios: number[]) => config.setComponentKnob('chart', 'stockChart', {
          ...value,
          heightRatios: { ...value.heightRatios, [key]: ratios },
        }),
        onApplyCurrentRatios: () => config.setComponentKnob('chart', 'stockChart', runtime),
      }),
      slots.business?.(),
      h('button', {
        'data-testid': 'page-settings-reset',
        onClick: () => emit('reset'),
      }, '恢复默认'),
    ])
    }
  },
})

const PageSegmentedStub = defineComponent({
  name: 'PageSegmented',
  props: ['modelValue', 'options', 'testId'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('div', { 'data-testid': props.testId }, (
      props.options as Array<{ label: string; value: string | number | boolean }>
    ).map((option) => h('button', {
      'data-testid': props.testId ? `${props.testId}-${String(option.value)}` : undefined,
      'data-active': String(props.modelValue === option.value),
      onClick: () => emit('update:modelValue', option.value),
    }, option.label)))
  },
})

const PageToggleRowStub = defineComponent({
  name: 'PageToggleRow',
  props: ['modelValue', 'label', 'testId'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('button', {
      'data-testid': props.testId,
      'data-active': String(props.modelValue),
      onClick: () => emit('update:modelValue', !props.modelValue),
    }, String(props.label))
  },
})

const AppStateBlockStub = defineComponent({
  name: 'AppStateBlock',
  props: ['state', 'variant', 'title', 'description', 'retry'],
  emits: ['retry'],
  setup(props, { emit }) {
    return () => h('section', {
      'data-testid': 'state-block',
      'data-state': props.state,
      'data-variant': props.variant,
    }, [
      h('span', String(props.title || '')),
      h('span', String(props.description || '')),
      props.retry
        ? h('button', { onClick: () => emit('retry') }, '重试')
        : null,
    ])
  },
})

const KlineRangeSelectStub = defineComponent({
  name: 'KlineRangeSelect',
  props: ['modelValue', 'width'],
  emits: ['update:modelValue'],
  setup(_props, { emit }) {
    return () => h('button', {
      'data-testid': 'range-250',
      onClick: () => emit('update:modelValue', 250),
    }, '250日')
  },
})

const ElSelectStub = defineComponent({
  name: 'ElSelect',
  props: ['modelValue', 'placement', 'fallbackPlacements'],
  emits: ['update:modelValue', 'change', 'visible-change', 'end-reached'],
  setup(props, { slots }) {
    return () => h('div', {
      'data-model-value': String(props.modelValue ?? ''),
    }, slots.default?.())
  },
})

const AppWorkspacePaneStub = defineComponent({
  name: 'AppWorkspacePane',
  inheritAttrs: false,
  props: {
    title: { type: String, required: true },
    eyebrow: { type: String, default: '' },
    headerVisible: { type: Boolean, default: true },
    primary: { type: Boolean, default: false },
  },
  setup(props, { attrs, slots }) {
    return () => h('section', attrs, [
      props.headerVisible
        ? h('header', { class: 'app-workspace-pane__header' }, [
            props.eyebrow ? h('div', { class: 'app-workspace-pane__eyebrow' }, props.eyebrow) : null,
            h('h3', props.title),
            slots.actions?.(),
          ])
        : null,
      h('div', { class: 'app-workspace-pane__body' }, slots.default?.()),
    ])
  },
})

function bar(date: string, close: number): Bar {
  return {
    date,
    open: close - 0.1,
    high: close + 0.3,
    low: close - 0.2,
    close,
    pre_close: close - 0.1,
    volume: 100_000,
    amount: 1_000_000,
    turnover_rate: 1,
  }
}

function quote(close: number, name = '浦发银行'): Awaited<ReturnType<typeof stocksApi.getStockQuoteSummary>> {
  return {
    code: '600000.SH', name, board: '主板', industry: '银行', is_st: false,
    trade_date: '2026-07-23', open: close - 0.4, high: close + 0.3, low: close - 0.5,
    close, pre_close: close - 1, volume: 100_000, amount: 1_000_000,
    turnover_rate: 1, volume_ratio: 1.2, total_mv: 10_000_000_000,
    float_mv: 8_000_000_000, total_share: 1_000_000_000,
    float_share: 800_000_000, pe_ttm: null,
  }
}

function indicator(date: string, ma20 = 12.34): IndicatorRow {
  return {
    trade_date: date,
    ma20,
    ma60: 11.2,
    macd_diff: 0.2,
    macd_dea: 0.1,
    macd_hist: 0.2,
    macd_golden_cross: false,
    macd_dead_cross: false,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function httpError(status: number, msg: string) {
  return {
    response: {
      status,
      data: { msg },
    },
  }
}

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/stocks/:code', component: StockDetailView },
    { path: '/stocks', component: { template: '<div />' } },
  ],
})

function testGlobal(pinia: ReturnType<typeof createPinia>) {
  return {
    plugins: [pinia, router, ElementPlus],
    directives: {
      permission: {},
    },
    stubs: {
      LayoutHost: {
        template: '<main><slot name="action"/><slot name="main"/><slot name="overlays"/></main>',
      },
      AppSplitWorkspace: AppSplitWorkspaceStub,
      AppWorkspacePane: AppWorkspacePaneStub,
      StockChartWorkspace: StockChartWorkspaceStub,
      MarketDetailHero: {
        props: ['eyebrow', 'title', 'code', 'subtitle', 'asideAlign'],
        template: '<section :data-aside-align="asideAlign"><span>{{ title }}</span><span>{{ code }}</span><slot name="badges"/><slot name="actions"/><slot name="summary"/><slot name="meta"/><slot name="footer"/></section>',
      },
      StockQuoteSummary: {
        name: 'StockQuoteSummary',
        props: ['summary', 'columnGap'],
        template: '<div data-testid="stock-latest-quote">{{ summary.hero.value }}:{{ summary.hero.tone }} {{ summary.hero.details?.map((item) => item.value).join(" ") }} {{ summary.metrics.map((item) => `${item.label}:${item.value}:${item.tone || "neutral"}`).join(" ") }}</div>',
      },
      StockBoardMembershipPanel: {
        name: 'StockBoardMembershipPanel',
        props: ['membership'],
        template: '<section data-testid="stock-board-membership-panel" />',
      },
      StockIntradayDialog: {
        name: 'StockIntradayDialog',
        props: ['modelValue', 'code', 'name', 'tradeDate', 'requestKey'],
        emits: ['update:modelValue'],
        template: '<div data-testid="intraday-dialog" :data-open="modelValue" :data-date="tradeDate" />',
      },
      StockChartSettingSection: false,
      AppStateBlock: AppStateBlockStub,
      KlineRangeSelect: KlineRangeSelectStub,
      PageSettingsDrawer: PageSettingsDrawerStub,
      PageSettingsTrigger: true,
      PageSettingSection: { template: '<section><slot/></section>' },
      PageSettingItem: { template: '<div><slot/></div>' },
      PageSegmented: PageSegmentedStub,
      PageToggleRow: PageToggleRowStub,
      PageSettingsApplyButton: {
        props: ['testId', 'disabled'],
        emits: ['click'],
        template: '<button :data-testid="testId" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
      },
      KlineSettingSection: true,
      ElSelect: ElSelectStub,
      ElOption: {
        props: ['label', 'value'],
        template: '<span :data-value="String(value)"><slot>{{ label }}</slot></span>',
      },
      ElCard: { template: '<section><slot name="header"/><slot/></section>' },
      AppDetailFields: false,
      AppDetailField: false,
    },
  }
}

async function prepareAuth(permissions = [
  'stocks:view',
  'stocks:trade-eval',
  'trade-profile:view',
]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = permissions
  auth.menusStatus = 'ready'
  await router.push('/stocks/600000.SH')
  await router.isReady()
  return pinia
}

async function mountView(permissions?: string[]) {
  const pinia = await prepareAuth(permissions)
  const wrapper = shallowMount(StockDetailView, {
    global: testGlobal(pinia),
  })
  await flushPromises()
  await nextTick()
  return wrapper
}

async function mountKeepAliveView(options: {
  count?: number
  withPagedStockSet?: boolean
} = {}) {
  const pinia = await prepareAuth()
  if (options.withPagedStockSet) {
    useStockSet().setSet(
      'list',
      [
        { code: '600000.SH', name: '浦发银行' },
        { code: '000001.SZ', name: '平安银行' },
      ],
      '查询结果',
      '',
      {
        query: { kind: 'stocks', params: { q: '银行' } },
        total: 250,
        loadedPages: [1],
        pageSize: 100,
      },
    )
  }
  const actives = Array.from({ length: options.count ?? 1 }, () => ref(true))
  const Host = defineComponent({
    setup() {
      return () => h('div', actives.map((active, index) => h(KeepAlive, null, {
        default: () => (active.value
          ? h(StockDetailView, { key: `stock-detail-${index}` })
          : null),
      })))
    },
  })
  const wrapper = mount(Host, {
    global: testGlobal(pinia),
  })
  await nextTick()
  return { active: actives[0], actives, wrapper }
}

function setDefaultApiResponses() {
  vi.mocked(stocksApi.getBars).mockImplementation(async (_code, params) => ({
    code: '600000.SH',
    name: '浦发银行',
    adjust: params?.adjust || '',
    bars: params?.lookback === 1
      ? [bar('2026-07-23', 10.5)]
      : [bar('2026-07-22', 10), bar('2026-07-23', 10.5)],
  }))
  vi.mocked(stocksApi.getIndicators).mockResolvedValue({
    code: '600000.SH',
    indicators: [indicator('2026-07-22'), indicator('2026-07-23')],
  })
  vi.mocked(stocksApi.getStockQuoteSummary).mockResolvedValue(quote(10.5))
  vi.mocked(stocksApi.getStockBoardMembership).mockResolvedValue({
    code: '600000.SH',
    membership_scope: 'cumulative',
    membership_updated_at: '2026-07-23T18:00:00',
    trade_date: '2026-07-23',
    industries: [],
    concepts: [],
    related_boards: null,
  })
  vi.mocked(stocksApi.getTradeEval).mockResolvedValue({
    code: '600000.SH',
    date: '2026-07-23',
    profile_id: 'avr_trade_1',
    name: '默认买卖',
    version: 1,
    buy_signal: false,
    sell_signal: false,
    buy: { op: 'AND', conds: [] },
    sell: { op: 'AND', conds: [] },
    backstop: {},
  })
  vi.mocked(stocksApi.listStocks).mockResolvedValue({
    total: 0,
    page: 1,
    size: 1,
    trade_date: '2026-07-23',
    list: [],
  })
  vi.mocked(stockGroupApi.listGroups).mockResolvedValue([])
  vi.mocked(tradeProfileApi.listTradeProfiles).mockResolvedValue([
    {
      id: 'trade-1',
      profile_ref: 'avr_trade_1',
      name: '默认买卖',
      version: 1,
      is_preset: true,
    } as any,
  ])
}

// 列表改由共享选择器组件经 ready 事件提供（P2-1，组件为唯一事实源）。
// 本测试以 shallowMount 渲染，AssetProfileSelect 被自动 stub、不会自行 emit ready，
// 故显式触发 ready 模拟组件装载「我的」列表，驱动首项选中并评估。
const mineTradeList = [
  { id: 'trade-1', profile_ref: 'avr_trade_1', name: '默认买卖', version: 1, is_preset: true } as any,
]
async function emitTradeReady(wrapper: any, list = mineTradeList) {
  await wrapper.findComponent(AssetProfileSelect).vm.$emit('ready', list)
  await flushPromises()
}

describe('StockDetailView 三图数据协调', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pageSettingsState.current = null
    componentConfigState.current = null
    resetLayout.mockReset()
    localStorage.clear()
    setDefaultApiResponses()
  })

  it('买卖方案统一走共享选择器，仅加载「我的」（source=mine）', async () => {
    const wrapper = await mountView()
    const select = wrapper.findComponent(AssetProfileSelect)
    await emitTradeReady(wrapper)

    expect(select.exists()).toBe(true)
    expect(select.props('assetLabel')).toBe('买卖方案')
    expect(select.props('modelValue')).toBe('avr_trade_1')
    // 组件为列表唯一事实源（P2-1）：页面传入 fetchMine 回调、不再自行 fetch；
    // 该回调内部以 source=mine 调 listTradeProfiles（真实组件挂载时触发，本处 stub 不触发）。
    expect(typeof select.props('fetchMine')).toBe('function')
  })

  it('加载查看公开方案只选中不自动评估，点「评估」按钮才运行（R10）', async () => {
    const wrapper = await mountView()
    await emitTradeReady(wrapper)
    vi.mocked(stocksApi.getTradeEval).mockClear()

    const select = wrapper.findComponent(AssetProfileSelect)
    // 「加载查看」注入临时只读项：只选中+展示，不发评估请求
    select.vm.$emit('loaded', {
      id: 'pub-x', profile_ref: 'avr_pub_x', name: '趋势买卖', version: 3, is_preset: true, source: 'preset', readonly: true,
    })
    await flushPromises()
    expect(select.props('modelValue')).toBe('avr_pub_x')
    expect(stocksApi.getTradeEval).not.toHaveBeenCalled()

    // 用户点「评估」按钮才显式运行
    await wrapper.get('[data-testid="stock-trade-eval-run"]').trigger('click')
    await flushPromises()
    expect(stocksApi.getTradeEval).toHaveBeenCalledWith(
      '600000.SH', 'avr_pub_x', undefined, expect.any(AbortSignal),
    )
  })

  it('初次并行加载行情、全量指标序列和报价，并把默认三图接入页面', async () => {
    const wrapper = await mountView()
    await emitTradeReady(wrapper)
    const workspace = wrapper.findComponent(StockChartWorkspaceStub)

    expect(stocksApi.getBars).toHaveBeenCalledWith(
      '600000.SH',
      { adjust: 'qfq', lookback: 1250 },
      expect.any(AbortSignal),
    )
    expect(stocksApi.getStockQuoteSummary).toHaveBeenCalledWith(
      '600000.SH', expect.any(AbortSignal),
    )
    expect(stocksApi.getStockBoardMembership).toHaveBeenCalledWith(
      '600000.SH', '2026-07-23', expect.any(AbortSignal),
    )
    expect(stocksApi.getIndicators).toHaveBeenCalledWith(
      '600000.SH',
      {
        lookback: 1250,
        fields: expect.arrayContaining([
          'ma20',
          'ma60',
          'macd_diff',
          'macd_dea',
          'macd_hist',
          'macd_golden_cross',
          'macd_dead_cross',
        ]),
      },
      expect.any(AbortSignal),
    )
    expect(workspace.props('slot2')).toBe('volume')
    expect(workspace.props('slot3')).toBe('macd')
    expect(workspace.props('macdState')).toBe('ready')
    expect(workspace.props('adjustLabel')).toBe('前复权')
    expect(workspace.props('macdAdjustLabel')).toBe('前复权')
    expect(workspace.props('minHeight')).toBeUndefined()
    expect(workspace.props('fitAvailableHeight')).toBe('')
    expect(workspace.props('enableIntradayDrilldown')).toBe('')
    expect(workspace.props('showKlineTooltip')).toBe(false)
    expect(wrapper.find('[data-testid="stock-board-membership-panel"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="stock-detail-primary"]').findComponent(StockChartWorkspaceStub).exists())
      .toBe(true)
    expect(wrapper.get('[data-testid="stock-detail-secondary"]').find('[data-testid="stock-indicator-snapshot-card"]').exists())
      .toBe(true)
    expect(wrapper.text()).toContain('12.34')
    expect(stocksApi.getTradeEval).toHaveBeenCalledWith(
      '600000.SH',
      'avr_trade_1',
      undefined,
      expect.any(AbortSignal),
    )
  })

  it('点击个股详情日 K 后把交易日传入共享分时弹窗', async () => {
    const wrapper = await mountView()
    await emitTradeReady(wrapper)

    await wrapper.get('[data-testid="open-intraday"]').trigger('click')
    await flushPromises()

    const dialog = wrapper.get('[data-testid="intraday-dialog"]')
    expect(dialog.attributes('data-open')).toBe('true')
    expect(dialog.attributes('data-date')).toBe('2026-08-07')
  })

  it('行情摘要保持纯行情字段并随 K 线光标切换数值和涨跌颜色', async () => {
    vi.mocked(stocksApi.getStockBoardMembership).mockResolvedValueOnce({
      code: '600000.SH',
      membership_scope: 'cumulative',
      membership_updated_at: '2026-07-23T18:00:00',
      trade_date: '2026-07-23',
      industries: [
        { board_code: '881001', name: '银行', board_type: 'industry', pct_chg: 2 },
      ],
      concepts: [],
      related_boards: {
        as_of_date: '2026-07-23',
        benchmark: { code: '000001.SH', name: '上证指数', fallback: false },
        industry: {
          board_code: '881001', name: '银行', score: 0.8, corr_20: 0.8, corr_60: 0.8,
          sample_20: 20, sample_60: 60, confidence: 'high',
        },
        concept: null,
      },
    })
    const wrapper = await mountView()
    const hero = wrapper.find('[data-aside-align="start"]')

    expect(hero.exists()).toBe(true)
    expect(wrapper.get('[data-testid="stock-latest-quote"]').text()).toContain('10.50')
    expect(wrapper.get('[data-testid="stock-latest-quote"]').text()).not.toContain('所属行业')
    expect(wrapper.getComponent({ name: 'StockQuoteSummary' }).props('columnGap')).toBe('relaxed')

    await wrapper.get('[data-testid="activate-kline-bar"]').trigger('click')
    await nextTick()

    const summary = wrapper.get('[data-testid="stock-latest-quote"]').text()
    expect(summary).toContain('9.50:up')
    expect(summary).toContain('开盘:9.40:neutral')
    expect(wrapper.text()).not.toContain('行情 2026-07-22')
  })

  it('手动刷新保留当前股票和方案并同步行情、指标、报价与买卖评估', async () => {
    const wrapper = await mountView()
    await emitTradeReady(wrapper)
    vi.mocked(stocksApi.getBars).mockClear()
    vi.mocked(stocksApi.getIndicators).mockClear()
    vi.mocked(stocksApi.getStockQuoteSummary).mockClear()
    vi.mocked(stocksApi.getStockBoardMembership).mockClear()
    vi.mocked(stocksApi.getTradeEval).mockClear()

    const refresh = wrapper.get('[data-testid="stock-detail-refresh"]')
    await refresh.trigger('click')
    await flushPromises()

    expect(stocksApi.getBars).toHaveBeenCalledTimes(1)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(1)
    expect(stocksApi.getStockQuoteSummary).toHaveBeenCalledTimes(1)
    expect(stocksApi.getStockBoardMembership).toHaveBeenCalledTimes(1)
    expect(stocksApi.getTradeEval).toHaveBeenCalledWith(
      '600000.SH', 'avr_trade_1', undefined, expect.any(AbortSignal),
    )
    expect(router.currentRoute.value.params.code).toBe('600000.SH')
  })

  it('最小 stocks:view 权限不请求也不展示分组和买卖评估能力', async () => {
    const wrapper = await mountView(['stocks:view'])

    expect(tradeProfileApi.listTradeProfiles).not.toHaveBeenCalled()
    expect(stocksApi.getTradeEval).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="stock-group-select"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="stock-detail-favorite"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="stock-trade-eval-card"]').exists()).toBe(false)
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(true)
  })

  it('详情头部复用收藏心维护默认自选分组并同步所属分组状态', async () => {
    vi.mocked(stockGroupApi.listGroups).mockResolvedValue([{
      id: 'grp-default',
      name: '自选',
      group_date: null,
      description: '',
      color: '#409eff',
      is_default: true,
      member_count: 1,
      updated_at: '2026-07-23T18:00:00',
    }])
    vi.mocked(stocksApi.listStocks).mockResolvedValue({
      total: 1,
      page: 1,
      size: 1,
      trade_date: '2026-07-23',
      list: [{
        code: '600000.SH',
        name: '浦发银行',
        board: '主板',
        industry: '银行',
        list_date: '1999-11-10',
        delist_date: null,
        is_st: false,
        close: 10.5,
        pct_chg: 1.2,
        groups: [{ id: 'grp-default', name: '自选', color: '#409eff', is_default: true }],
      }],
    })

    const wrapper = await mountView([
      'stocks:view',
      'stock-group:view',
      'stock-group:member-update',
    ])
    const favorite = wrapper.getComponent(StockGroupFavoriteButton)

    expect(favorite.props('active')).toBe(true)
    favorite.vm.$emit('changed', false)
    await nextTick()

    expect(wrapper.getComponent(StockGroupFavoriteButton).props('active')).toBe(false)
  })

  it('所属分组下拉固定在触发器下方，不回退到页面上方', async () => {
    const wrapper = await mountView([
      'stocks:view',
      'stock-group:view',
      'stock-group:member-update',
    ])
    const select = wrapper.findAllComponents(ElSelectStub)
      .find((item) => item.attributes('data-testid') === 'stock-group-select')

    expect(select?.exists()).toBe(true)
    expect(select?.props('placement')).toBe('bottom-start')
    expect(select?.props('fallbackPlacements')).toEqual(['bottom-start', 'bottom-end'])
  })

  it('初次行情普通错误显示可重试错误态，重试成功后恢复工作区', async () => {
    let chartAttempts = 0
    vi.mocked(stocksApi.getBars).mockImplementation(async (_code, params) => {
      if (params?.lookback === 1) {
        return {
          code: '600000.SH',
          name: '浦发银行',
          adjust: '',
          bars: [bar('2026-07-23', 10.5)],
        }
      }
      chartAttempts += 1
      if (chartAttempts === 1) throw new Error('行情服务暂不可用')
      return {
        code: '600000.SH',
        name: '浦发银行',
        adjust: params?.adjust || '',
        bars: [bar('2026-07-23', 11)],
      }
    })

    const wrapper = await mountView()
    const state = wrapper.findComponent(AppStateBlockStub)
    expect(state.props('variant')).toBeUndefined()
    expect(state.props('retry')).toBe(true)
    expect(wrapper.text()).toContain('行情服务暂不可用')
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)

    await state.get('button').trigger('click')
    await flushPromises()

    expect(wrapper.findComponent(AppStateBlockStub).exists()).toBe(false)
    expect(wrapper.get('[data-testid="workspace-close"]').text()).toBe('11')
  })

  it('行情成功空数据进入 empty 状态且不渲染工作区', async () => {
    vi.mocked(stocksApi.getBars).mockImplementation(async (_code, params) => ({
      code: '600000.SH',
      name: '浦发银行',
      adjust: params?.adjust || '',
      bars: params?.lookback === 1 ? [bar('2026-07-23', 10.5)] : [],
    }))

    const wrapper = await mountView()
    const state = wrapper.findComponent(AppStateBlockStub)

    expect(state.props('state')).toBe('empty')
    expect(wrapper.text()).toContain('暂无个股行情')
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)
  })

  it('已有行情刷新失败后由错误态接管并隐藏旧图', async () => {
    const wrapper = await mountView()
    vi.mocked(stocksApi.getBars).mockRejectedValueOnce(new Error('范围刷新失败'))

    await wrapper.get('[data-testid="range-250"]').trigger('click')
    await flushPromises()

    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)
    expect(wrapper.text()).toContain('个股详情刷新失败')
    expect(wrapper.text()).toContain('范围刷新失败')
  })

  it('复权只刷新行情；范围同时刷新行情和指标，不重复请求报价或买卖评估', async () => {
    const wrapper = await mountView()
    const initialBars = vi.mocked(stocksApi.getBars).mock.calls.length
    const initialIndicators = vi.mocked(stocksApi.getIndicators).mock.calls.length
    const initialTrade = vi.mocked(stocksApi.getTradeEval).mock.calls.length
    const initialQuote = vi.mocked(stocksApi.getStockQuoteSummary).mock.calls.length

    pageSettingsState.current.adjustMode = 'hfq'
    await nextTick()
    await flushPromises()

    expect(stocksApi.getBars).toHaveBeenCalledTimes(initialBars + 1)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(initialIndicators)
    expect(stocksApi.getTradeEval).toHaveBeenCalledTimes(initialTrade)

    await wrapper.get('[data-testid="range-250"]').trigger('click')
    await flushPromises()

    expect(stocksApi.getBars).toHaveBeenCalledTimes(initialBars + 2)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(initialIndicators + 1)
    expect(stocksApi.getIndicators).toHaveBeenLastCalledWith(
      '600000.SH',
      expect.objectContaining({ lookback: 1250 }),
      expect.any(AbortSignal),
    )
    expect(stocksApi.getTradeEval).toHaveBeenCalledTimes(initialTrade)
    expect(stocksApi.getStockQuoteSummary).toHaveBeenCalledTimes(initialQuote)

    const barsAfterRange = vi.mocked(stocksApi.getBars).mock.calls.length
    const indicatorsAfterRange = vi.mocked(stocksApi.getIndicators).mock.calls.length
    componentConfigState.current.slot3 = 'hidden'
    await nextTick()
    await flushPromises()

    expect(stocksApi.getBars).toHaveBeenCalledTimes(barsAfterRange)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(indicatorsAfterRange)
    expect(wrapper.findComponent(StockChartWorkspaceStub).props('slot3')).toBe('hidden')
  })

  it('设置抽屉即时交换和隐藏辅助图，主区高度只改会话并可显式设为默认', async () => {
    const wrapper = await mountView()
    const initialBars = vi.mocked(stocksApi.getBars).mock.calls.length
    const initialIndicators = vi.mocked(stocksApi.getIndicators).mock.calls.length
    const workspace = wrapper.findComponent(StockChartWorkspaceStub)

    expect(wrapper.get('[data-testid="component-chart-stock-chart-slot1-kline"]').text())
      .toContain('固定，不可隐藏')

    await wrapper.get('[data-testid="component-chart-stock-chart-slot2-macd"]').trigger('click')
    await nextTick()
    expect(componentConfigState.current).toMatchObject({
      slot2: 'macd',
      slot3: 'volume',
    })
    expect(workspace.props('slot2')).toBe('macd')
    expect(workspace.props('slot3')).toBe('volume')

    await wrapper.get('[data-testid="component-chart-stock-chart-slot3-hidden"]').trigger('click')
    await nextTick()
    expect(workspace.props('slot3')).toBe('hidden')
    expect(stocksApi.getBars).toHaveBeenCalledTimes(initialBars)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(initialIndicators)

    const persistedBeforeDraft = JSON.parse(
      JSON.stringify(componentConfigState.current.heightRatios),
    )
    await wrapper.get('[data-testid="ratio-draft"]').trigger('click')
    await nextTick()
    expect(componentConfigState.current.heightRatios).toEqual(persistedBeforeDraft)

    await wrapper.get('[data-testid="ratio-commit"]').trigger('click')
    await nextTick()
    expect(componentConfigState.current.heightRatios['kline|macd'])
      .toEqual([0.75, 0.25])

    // 三图终态用于验证 commit 真正写入当前有序组合，而不是草稿或其他组合。
    await wrapper.get('[data-testid="component-chart-stock-chart-slot3-volume"]').trigger('click')
    await nextTick()
    await wrapper.get('[data-testid="ratio-commit"]').trigger('click')
    await nextTick()
    expect(workspace.props('heightRatios')).toEqual([0.5, 0.3, 0.2])
    expect(componentConfigState.current.heightRatios['kline|macd|volume'])
      .toEqual([0.6, 0.2, 0.2])

    await wrapper.get('[data-testid="component-chart-stock-chart-save-current-ratios"]').trigger('click')
    await nextTick()
    expect(componentConfigState.current.heightRatios['kline|macd|volume'])
      .toEqual([0.5, 0.3, 0.2])

    await wrapper.get('[data-testid="page-settings-reset"]').trigger('click')
    await nextTick()
    expect(pageSettingsState.reset).toHaveBeenCalledTimes(1)
    expect(resetLayout).toHaveBeenCalledTimes(1)
    expect(componentConfigState.current).toEqual({
      slot2: 'volume',
      slot3: 'macd',
      heightRatios: {
        kline: [1],
        'kline|volume': [0.75, 0.25],
        'kline|macd': [0.75, 0.25],
        'kline|volume|macd': [0.6, 0.2, 0.2],
        'kline|macd|volume': [0.6, 0.2, 0.2],
      },
      heightRatioProfiles: {
        kline: [],
        'kline|volume': [],
        'kline|macd': [],
        'kline|volume|macd': [],
        'kline|macd|volume': [],
      },
    })
  })

  it('最新指标快照作为独立辅助模块隐藏，保留指标请求和字段偏好并可恢复默认', async () => {
    const wrapper = await mountView()
    const barsCalls = vi.mocked(stocksApi.getBars).mock.calls.length
    const indicatorCalls = vi.mocked(stocksApi.getIndicators).mock.calls.length

    expect(wrapper.find('[data-testid="stock-indicator-snapshot-card"]').exists()).toBe(true)
    expect(wrapper.find('.stock-detail-main').exists()).toBe(true)
    expect(wrapper.find('.stock-detail-ready').exists()).toBe(true)
    expect(wrapper.get('[data-testid="stock-chart-workspace"]').classes())
      .toContain('detail-chart-workspace')

    await wrapper.get('[data-testid="stock-detail-toggle-indicator-snapshot"]').trigger('click')
    await nextTick()
    await flushPromises()

    expect(pageSettingsState.current.showIndicatorSnapshot).toBe(false)
    expect(wrapper.find('[data-testid="stock-indicator-snapshot-card"]').exists()).toBe(false)
    expect(pageSettingsState.current.indicators.ma20).toBe(true)
    expect(stocksApi.getBars).toHaveBeenCalledTimes(barsCalls)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(indicatorCalls)

    await wrapper.get('[data-testid="page-settings-reset"]').trigger('click')
    await nextTick()

    expect(pageSettingsState.current.showIndicatorSnapshot).toBe(true)
    expect(wrapper.find('[data-testid="stock-indicator-snapshot-card"]').exists()).toBe(true)
  })

  it('辅助卡全部隐藏时图表恢复单栏，重新启用后恢复右栏', async () => {
    const wrapper = await mountView()
    const split = wrapper.findComponent(AppSplitWorkspaceStub)

    expect(split.props('defaultPrimaryRatio')).toBe(65)
    expect(split.props('secondaryVisible')).toBe(true)
    await wrapper.get('[data-testid="stock-detail-toggle-indicator-snapshot"]').trigger('click')
    await wrapper.get('[data-testid="stock-detail-toggle-trade-card"]').trigger('click')
    await wrapper.get('[data-testid="stock-detail-toggle-related-boards"]').trigger('click')
    await nextTick()

    expect(split.props('secondaryVisible')).toBe(false)
    expect(wrapper.find('[data-testid="stock-detail-secondary"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="stock-detail-toggle-auxiliary"]').exists()).toBe(false)

    await wrapper.get('[data-testid="stock-detail-toggle-indicator-snapshot"]').trigger('click')
    await nextTick()
    expect(split.props('secondaryVisible')).toBe(true)
    expect(wrapper.find('[data-testid="stock-indicator-snapshot-card"]').exists()).toBe(true)
  })

  it('辅助栏收展入口沿用主从工作台双箭头语义', async () => {
    const wrapper = await mountView()
    const toggle = wrapper.get('[data-testid="stock-detail-toggle-auxiliary"]')

    expect(wrapper.get('[data-testid="stock-detail-primary"]')
      .find('[data-testid="stock-detail-toggle-auxiliary"]').exists()).toBe(true)
    expect(wrapper.find('.page-head-actions [data-testid="stock-detail-toggle-auxiliary"]').exists())
      .toBe(false)
    expect(toggle.attributes('label')).toBe('收起辅助信息，仅看图表')
    await toggle.trigger('click')
    await nextTick()

    expect(toggle.attributes('label')).toBe('显示辅助信息')
  })

  it('左右栏具有统一栏头，K 线范围置于行情栏操作区', async () => {
    const wrapper = await mountView()
    const primary = wrapper.get('[data-testid="stock-detail-primary"]')
    const pageActions = wrapper.get('.page-head-actions')
    const chartPanel = wrapper.get('[data-testid="stock-detail-chart-panel"]')
    const auxiliaryPanel = wrapper.get('[data-testid="stock-detail-auxiliary-panel"]')
    const panes = wrapper.findAllComponents(AppWorkspacePaneStub)

    expect(primary.findComponent(KlineRangeSelectStub).exists()).toBe(true)
    expect(pageActions.findComponent(KlineRangeSelectStub).exists()).toBe(false)
    expect(wrapper.findComponent(KlineRangeSelectStub).props('width')).toBe('112px')
    expect(chartPanel.get('.app-workspace-pane__header').text()).toContain('行情走势')
    expect(auxiliaryPanel.get('.app-workspace-pane__eyebrow').text()).toBe('分析概览')
    expect(auxiliaryPanel.get('.app-workspace-pane__header h3').text()).toBe('2026-07-23')
    expect(panes[0]?.props('primary')).toBe(true)
    expect(panes[1]?.props('primary')).toBe(false)
  })

  it('MACD 局部失败保留行情和快照，局部重试不刷新行情', async () => {
    const wrapper = await mountView()
    const oldSnapshot = wrapper.text()
    const barsCalls = vi.mocked(stocksApi.getBars).mock.calls.length
    vi.mocked(stocksApi.getIndicators).mockRejectedValueOnce(new Error('指标服务超时'))

    await wrapper.get('[data-testid="range-250"]').trigger('click')
    await flushPromises()

    const workspace = wrapper.findComponent(StockChartWorkspaceStub)
    expect(workspace.props('macdState')).toBe('error')
    expect(workspace.props('macdError')).toContain('指标服务超时')
    expect(workspace.props('bars')).toHaveLength(2)
    expect(wrapper.text()).toContain('12.34')
    expect(oldSnapshot).toContain('12.34')

    vi.mocked(stocksApi.getIndicators).mockResolvedValueOnce({
      code: '600000.SH',
      indicators: [indicator('2026-07-23', 13.21)],
    })
    await wrapper.get('[data-testid="retry-macd"]').trigger('click')
    await flushPromises()

    expect(stocksApi.getBars).toHaveBeenCalledTimes(barsCalls + 1)
    expect(workspace.props('macdState')).toBe('ready')
    expect(wrapper.text()).toContain('13.21')
  })

  it('快速切换范围时较慢旧响应不会覆盖最新行情和指标', async () => {
    const wrapper = await mountView()
    const oldBars = deferred<Awaited<ReturnType<typeof stocksApi.getBars>>>()
    const newBars = deferred<Awaited<ReturnType<typeof stocksApi.getBars>>>()
    const oldIndicators = deferred<Awaited<ReturnType<typeof stocksApi.getIndicators>>>()
    const newIndicators = deferred<Awaited<ReturnType<typeof stocksApi.getIndicators>>>()
    vi.mocked(stocksApi.getBars)
      .mockImplementationOnce(() => oldBars.promise)
      .mockImplementationOnce(() => newBars.promise)
    vi.mocked(stocksApi.getIndicators)
      .mockImplementationOnce(() => oldIndicators.promise)
      .mockImplementationOnce(() => newIndicators.promise)

    const range = wrapper.findComponent(KlineRangeSelectStub)
    range.vm.$emit('update:modelValue', 60)
    await nextTick()
    range.vm.$emit('update:modelValue', 250)
    await nextTick()

    const rangeBarCalls = vi.mocked(stocksApi.getBars).mock.calls.slice(-2)
    const rangeIndicatorCalls = vi.mocked(stocksApi.getIndicators).mock.calls.slice(-2)
    expect(rangeBarCalls[0][2]?.aborted).toBe(true)
    expect(rangeBarCalls[1][2]?.aborted).toBe(false)
    expect(rangeIndicatorCalls[0][2]?.aborted).toBe(true)
    expect(rangeIndicatorCalls[1][2]?.aborted).toBe(false)

    newBars.resolve({
      code: '600000.SH',
      name: '浦发银行',
      adjust: 'qfq',
      bars: [bar('2026-07-23', 20)],
    })
    newIndicators.resolve({
      code: '600000.SH',
      indicators: [indicator('2026-07-23', 20.2)],
    })
    await flushPromises()

    oldBars.resolve({
      code: '600000.SH',
      name: '旧响应',
      adjust: 'qfq',
      bars: [bar('2026-07-22', 5)],
    })
    oldIndicators.resolve({
      code: '600000.SH',
      indicators: [indicator('2026-07-22', 5.2)],
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="workspace-close"]').text()).toBe('20')
    expect(wrapper.text()).toContain('20.20')
    expect(wrapper.text()).not.toContain('5.20')
  })

  it('快速切换买卖方案时取消旧评估且旧响应不会覆盖新方案', async () => {
    vi.mocked(tradeProfileApi.listTradeProfiles).mockResolvedValue([
      {
        id: 'same-id',
        profile_ref: 'avr_trade_1',
        name: '方案一',
        version: 1,
        is_preset: true,
      } as any,
      {
        id: 'same-id',
        profile_ref: 'avr_trade_2',
        name: '方案二',
        version: 1,
        is_preset: true,
      } as any,
    ])
    const oldTrade = deferred<Awaited<ReturnType<typeof stocksApi.getTradeEval>>>()
    vi.mocked(stocksApi.getTradeEval)
      .mockImplementationOnce(() => oldTrade.promise)
      .mockResolvedValueOnce({
        code: '600000.SH',
        date: '2026-07-23',
        profile_id: 'avr_trade_2',
        name: '方案二',
        version: 2,
        buy_signal: false,
        sell_signal: false,
        buy: { op: 'AND', conds: [] },
        sell: { op: 'AND', conds: [] },
        backstop: {},
      })

    const wrapper = await mountView()
    const tradeSelect = wrapper.findComponent(AssetProfileSelect)
    // ready 装载列表 → 首项 avr_trade_1 自动选中并发起首次评估（oldTrade）
    await emitTradeReady(wrapper, [
      { id: 'same-id', profile_ref: 'avr_trade_1', name: '方案一', version: 1, is_preset: true } as any,
      { id: 'same-id', profile_ref: 'avr_trade_2', name: '方案二', version: 1, is_preset: true } as any,
    ])
    expect(tradeSelect.exists()).toBe(true)
    expect(tradeSelect.props('modelValue')).toBe('avr_trade_1')

    tradeSelect.vm.$emit('update:modelValue', 'avr_trade_2')
    await nextTick()
    await flushPromises()

    const tradeCalls = vi.mocked(stocksApi.getTradeEval).mock.calls
    expect(tradeCalls[0][3]?.aborted).toBe(true)
    expect(tradeCalls[1][1]).toBe('avr_trade_2')
    expect(wrapper.text()).toContain('v2')

    oldTrade.resolve({
      code: '600000.SH',
      date: '2026-07-22',
      profile_id: 'avr_trade_1',
      name: '方案一',
      version: 1,
      buy_signal: true,
      sell_signal: false,
      buy: { op: 'AND', conds: [] },
      sell: { op: 'AND', conds: [] },
      backstop: {},
    })
    await flushPromises()

    expect(wrapper.text()).toContain('v2')
    expect(wrapper.text()).not.toContain('v1')
  })

  it('行情 403 使用 permission 错误态且不伪装为空数据', async () => {
    vi.mocked(stocksApi.getBars).mockImplementation(async (_code, params) => {
      if (params?.lookback === 1) {
        return {
          code: '600000.SH',
          name: '浦发银行',
          adjust: '',
          bars: [bar('2026-07-23', 10.5)],
        }
      }
      throw {
        response: {
          status: 403,
          data: { msg: '无权限查看个股行情' },
        },
      }
    })

    const wrapper = await mountView()
    const state = wrapper.findComponent(AppStateBlockStub)

    expect(state.props('state')).toBe('error')
    expect(state.props('variant')).toBe('permission')
    expect(state.props('retry')).toBe(false)
    expect(wrapper.text()).toContain('无权限查看个股详情')
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)
  })

  it('行情 403 先返回时，稍后完成的方案列表不会再发起买卖评估', async () => {
    const profiles = deferred<Awaited<ReturnType<typeof tradeProfileApi.listTradeProfiles>>>()
    vi.mocked(tradeProfileApi.listTradeProfiles).mockImplementation(() => profiles.promise)
    vi.mocked(stocksApi.getBars).mockImplementation(async (_code, params) => {
      if (params?.lookback === 1) {
        return {
          code: '600000.SH',
          name: '浦发银行',
          adjust: '',
          bars: [bar('2026-07-23', 10.5)],
        }
      }
      throw httpError(403, '无权限查看个股行情')
    })

    const wrapper = await mountView()
    profiles.resolve([{
      id: 'trade-1',
      profile_ref: 'avr_trade_1',
      name: '默认买卖',
      version: 1,
      is_preset: true,
    }])
    await flushPromises()

    expect(wrapper.findComponent(AppStateBlockStub).props('variant')).toBe('permission')
    expect(stocksApi.getTradeEval).not.toHaveBeenCalled()
  })

  it('已有数据后收到 403 会清空详情，后续 pending 和再次 403 始终保持 fail-closed', async () => {
    const wrapper = await mountView()
    vi.mocked(stocksApi.getBars).mockRejectedValueOnce(
      httpError(403, '股票查看权限已撤销'),
    )

    await wrapper.get('[data-testid="range-250"]').trigger('click')
    await flushPromises()

    let state = wrapper.findComponent(AppStateBlockStub)
    expect(state.props('variant')).toBe('permission')
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)
    expect(wrapper.find('[data-testid="stock-latest-quote"]').exists()).toBe(false)

    const pending = deferred<Awaited<ReturnType<typeof stocksApi.getBars>>>()
    vi.mocked(stocksApi.getBars).mockImplementationOnce(() => pending.promise)
    pageSettingsState.current.adjustMode = 'hfq'
    await nextTick()

    state = wrapper.findComponent(AppStateBlockStub)
    expect(state.props('variant')).toBe('permission')
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)

    pending.reject(httpError(403, '仍无股票查看权限'))
    await flushPromises()

    state = wrapper.findComponent(AppStateBlockStub)
    expect(state.props('variant')).toBe('permission')
    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('10.50')
  })

  it('报价失败只清空报价，不影响行情、指标和工作区', async () => {
    vi.mocked(stocksApi.getStockQuoteSummary).mockRejectedValueOnce(new Error('报价服务超时'))

    const wrapper = await mountView()

    expect(wrapper.findComponent(StockChartWorkspaceStub).exists()).toBe(true)
    expect(wrapper.find('[data-testid="stock-latest-quote"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('12.34')
    expect(wrapper.findComponent(AppStateBlockStub).exists()).toBe(false)
  })

  it('KeepAlive 停用会取消五个在途通道，激活后恢复且旧报价不会覆盖新结果', async () => {
    const oldBars = deferred<Awaited<ReturnType<typeof stocksApi.getBars>>>()
    const newBars = deferred<Awaited<ReturnType<typeof stocksApi.getBars>>>()
    const oldQuote = deferred<Awaited<ReturnType<typeof stocksApi.getStockQuoteSummary>>>()
    const newQuote = deferred<Awaited<ReturnType<typeof stocksApi.getStockQuoteSummary>>>()
    const oldIndicators = deferred<Awaited<ReturnType<typeof stocksApi.getIndicators>>>()
    const newIndicators = deferred<Awaited<ReturnType<typeof stocksApi.getIndicators>>>()
    const oldTrade = deferred<Awaited<ReturnType<typeof stocksApi.getTradeEval>>>()
    const newTrade = deferred<Awaited<ReturnType<typeof stocksApi.getTradeEval>>>()
    let barsCalls = 0
    let quoteCalls = 0
    let indicatorCalls = 0
    let tradeCalls = 0

    vi.mocked(stocksApi.getBars).mockImplementation(() => {
      barsCalls += 1
      return barsCalls === 1 ? oldBars.promise : newBars.promise
    })
    vi.mocked(stocksApi.getStockQuoteSummary).mockImplementation(() => {
      quoteCalls += 1
      return quoteCalls === 1 ? oldQuote.promise : newQuote.promise
    })
    vi.mocked(stocksApi.getIndicators).mockImplementation(() => {
      indicatorCalls += 1
      return indicatorCalls === 1 ? oldIndicators.promise : newIndicators.promise
    })
    vi.mocked(stocksApi.getTradeEval).mockImplementation(() => {
      tradeCalls += 1
      return tradeCalls === 1 ? oldTrade.promise : newTrade.promise
    })

    const { active, wrapper } = await mountKeepAliveView()
    await flushPromises()
    // ready 装载列表 → 首项自动选中并发起评估（占第 1 次 trade 调用）
    await wrapper.findComponent(AssetProfileSelect).vm.$emit('ready', mineTradeList)
    await flushPromises()
    expect(barsCalls).toBe(1)
    expect(quoteCalls).toBe(1)
    expect(indicatorCalls).toBe(1)
    expect(tradeCalls).toBe(1)

    const firstBarsSignal = vi.mocked(stocksApi.getBars).mock.calls[0][2]
    const firstQuoteSignal = vi.mocked(stocksApi.getStockQuoteSummary).mock.calls[0][1]
    const firstIndicatorSignal = vi.mocked(stocksApi.getIndicators).mock.calls[0][2]
    const firstTradeSignal = vi.mocked(stocksApi.getTradeEval).mock.calls[0][3]

    active.value = false
    await nextTick()
    expect(firstBarsSignal?.aborted).toBe(true)
    expect(firstQuoteSignal?.aborted).toBe(true)
    expect(firstIndicatorSignal?.aborted).toBe(true)
    expect(firstTradeSignal?.aborted).toBe(true)

    active.value = true
    await nextTick()
    await flushPromises()
    expect(barsCalls).toBe(2)
    expect(quoteCalls).toBe(2)
    expect(indicatorCalls).toBe(2)
    expect(tradeCalls).toBe(2)

    newBars.resolve({
      code: '600000.SH',
      name: '浦发银行',
      adjust: 'qfq',
      bars: [bar('2026-07-23', 20)],
    })
    newQuote.resolve(quote(21))
    newIndicators.resolve({
      code: '600000.SH',
      indicators: [indicator('2026-07-23', 20.2)],
    })
    newTrade.resolve({
      code: '600000.SH',
      date: '2026-07-23',
      profile_id: 'avr_trade_1',
      name: '默认买卖',
      version: 2,
      buy_signal: false,
      sell_signal: false,
      buy: { op: 'AND', conds: [] },
      sell: { op: 'AND', conds: [] },
      backstop: {},
    })
    await flushPromises()

    const detail = wrapper.findComponent(StockDetailView)
    expect(detail.get('[data-testid="workspace-close"]').text()).toBe('20')
    expect(detail.get('[data-testid="stock-latest-quote"]').text()).toContain('21.00')

    oldBars.resolve({
      code: '600000.SH',
      name: '旧行情',
      adjust: 'qfq',
      bars: [bar('2026-07-22', 5)],
    })
    oldQuote.resolve(quote(5, '旧报价'))
    oldIndicators.resolve({
      code: '600000.SH',
      indicators: [indicator('2026-07-22', 5.2)],
    })
    oldTrade.resolve({
      code: '600000.SH',
      date: '2026-07-22',
      profile_id: 'avr_trade_1',
      name: '旧买卖',
      version: 1,
      buy_signal: true,
      sell_signal: false,
      buy: { op: 'AND', conds: [] },
      sell: { op: 'AND', conds: [] },
      backstop: {},
    })
    await flushPromises()

    expect(detail.get('[data-testid="workspace-close"]').text()).toBe('20')
    expect(detail.get('[data-testid="stock-latest-quote"]').text()).toContain('21.00')
    // 评估卡内显示新评估 v2，不被旧响应 v1 覆盖（选择器区另含方案列表版本，不在此断言范围）
    const tradeCard = detail.get('[data-testid="stock-trade-eval-card"]')
    expect(tradeCard.text()).toContain('v2')
    expect(tradeCard.text()).not.toContain('旧买卖')
  })

  it('两个 KeepAlive 个股实例分别消费自身下拉触底事件和分页状态', async () => {
    vi.mocked(stocksApi.listStocks).mockImplementation(async (params) => ({
      total: 250,
      page: params?.page ?? 1,
      size: params?.size ?? 100,
      trade_date: '2026-07-23',
      list: [{
        code: `PAGE-${params?.page ?? 1}`,
        name: `第${params?.page ?? 1}页`,
      } as any],
    }))

    const { actives, wrapper } = await mountKeepAliveView({
      count: 2,
      withPagedStockSet: true,
    })
    await flushPromises()
    const details = wrapper.findAllComponents(StockDetailView)
    expect(details).toHaveLength(2)
    const collectionSelects = details.map((detail) => (
      detail.findAllComponents(ElSelectStub).find(
        (component) => component.attributes('data-testid') === 'stock-set-select',
      )
    ))
    expect(collectionSelects.every(Boolean)).toBe(true)

    collectionSelects.forEach((select) => select!.vm.$emit('visible-change', true))
    await flushPromises()
    vi.mocked(stocksApi.listStocks).mockClear()

    collectionSelects[0]!.vm.$emit('end-reached', 'bottom')
    await flushPromises()
    expect(stocksApi.listStocks).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: '银行', page: 2, size: 100 }),
    )

    collectionSelects[1]!.vm.$emit('end-reached', 'bottom')
    await flushPromises()
    expect(vi.mocked(stocksApi.listStocks).mock.calls).toHaveLength(2)
    expect(stocksApi.listStocks).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: '银行', page: 2, size: 100 }),
    )

    actives[0].value = false
    await nextTick()
    collectionSelects[1]!.vm.$emit('end-reached', 'bottom')
    await flushPromises()
    expect(vi.mocked(stocksApi.listStocks).mock.calls).toHaveLength(3)
    expect(stocksApi.listStocks).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: '银行', page: 3, size: 100 }),
    )
    wrapper.unmount()
  })

  it('首次渲染集合下拉时保留当前股票的真实序号', async () => {
    const pinia = await prepareAuth()
    useStockSet().setSet(
      'list',
      [
        { code: '000001.SZ', name: '平安银行' },
        { code: '600000.SH', name: '浦发银行' },
      ],
      '查询结果',
    )
    const wrapper = shallowMount(StockDetailView, {
      global: testGlobal(pinia),
    })
    await flushPromises()

    const collectionSelect = wrapper.findAllComponents(ElSelectStub).find(
      (component) => component.attributes('data-testid') === 'stock-set-select',
    )
    expect(collectionSelect?.text()).toContain('2. 浦发银行 600000.SH')
    wrapper.unmount()
  })

  it('返回键：当前股票在集合内回来源页，不在集合（残留 returnPath）归位列表', async () => {
    // 场景1：从榜单进入（code 在集合中，returnPath=/board）→ 返回回榜单
    const pinia = await prepareAuth()
    useStockSet().setSet(
      'list',
      [{ code: '600000.SH', name: '浦发银行' }],
      '每日榜单',
      '',
      { returnPath: '/board' },
    )
    const pushSpy = vi.spyOn(router, 'push')
    const wrapper = shallowMount(StockDetailView, { global: testGlobal(pinia) })
    await flushPromises()
    wrapper.get('[data-testid="stock-detail-back"]').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/board')
    expect(wrapper.get('[data-testid="stock-detail-back"]').attributes('aria-label'))
      .toBe('返回每日榜单')
    wrapper.unmount()

    // 场景2：直接从菜单/链接进入（code 不在集合中）→ 残留 returnPath 不生效，归位列表
    useStockSet().setSet(
      'list',
      [{ code: '000001.SZ', name: '平安银行' }],
      '每日榜单',
      '',
      { returnPath: '/board' },
    )
    pushSpy.mockClear()
    const wrapper2 = shallowMount(StockDetailView, { global: testGlobal(pinia) })
    await flushPromises()
    wrapper2.get('[data-testid="stock-detail-back"]').trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/stocks?restore=1')
    expect(wrapper2.get('[data-testid="stock-detail-back"]').attributes('aria-label'))
      .toBe('返回个股查询')
    wrapper2.unmount()
  })

  it('指标历史不足时只让 MACD 面板进入 insufficient', async () => {
    vi.mocked(stocksApi.getIndicators).mockResolvedValue({
      code: '600000.SH',
      indicators: [{
        trade_date: '2026-07-23',
        macd_diff: null,
        macd_dea: null,
        macd_hist: null,
      }],
    })

    const wrapper = await mountView()
    const workspace = wrapper.findComponent(StockChartWorkspaceStub)

    expect(workspace.props('macdState')).toBe('insufficient')
    expect(workspace.props('bars')).toHaveLength(2)
    expect(wrapper.findComponent(AppStateBlockStub).exists()).toBe(false)
  })
})
