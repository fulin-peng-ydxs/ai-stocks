// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick, reactive, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import type { Bar, IndicatorRow } from '@/api/stocks'
import { useAuthStore } from '@/stores/auth'

const pageSettingsState = vi.hoisted(() => ({ current: null as any }))

vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {},
    knobs: [],
    setKnob: vi.fn(),
    valueOf: vi.fn(),
    sourceOf: vi.fn(),
    isDirty: ref(false),
    resetAll: vi.fn(),
    componentValueOf: vi.fn(),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
  }),
}))

vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: (_key: string, defaults: Record<string, unknown>) => {
    pageSettingsState.current ??= reactive(structuredClone(defaults))
    return {
      settings: pageSettingsState.current,
      isDirty: ref(false),
      reset: vi.fn(),
      hydrated: ref(true),
    }
  },
}))

vi.mock('@/composables/useKlinePrefs', () => ({
  useKlinePrefs: () => ({ validDefault: ref(120) }),
}))

vi.mock('@/api/stocks', () => ({
  getBars: vi.fn(),
  getIndicators: vi.fn(),
  getTradeEval: vi.fn(),
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
import * as tradeProfileApi from '@/api/tradeProfile'
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
    'adjustLabel',
    'macdState',
    'macdError',
  ],
  emits: ['retryMacd'],
  setup(props, { emit }) {
    return () => h('section', {
      'data-testid': 'stock-chart-workspace',
      'data-macd-state': props.macdState,
      'data-adjust-label': props.adjustLabel,
    }, [
      h('span', { 'data-testid': 'workspace-close' },
        String((props.bars as Bar[] | undefined)?.at(-1)?.close ?? '')),
      h('span', { 'data-testid': 'workspace-macd-error' }, String(props.macdError || '')),
      h('button', {
        'data-testid': 'retry-macd',
        onClick: () => emit('retryMacd'),
      }, '重试 MACD'),
    ])
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
  props: ['modelValue'],
  emits: ['update:modelValue'],
  setup(_props, { emit }) {
    return () => h('button', {
      'data-testid': 'range-250',
      onClick: () => emit('update:modelValue', 250),
    }, '250日')
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

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/stocks/:code', component: StockDetailView },
    { path: '/stocks', component: { template: '<div />' } },
  ],
})

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = ['stocks:view']
  auth.menusStatus = 'ready'
  await router.push('/stocks/600000.SH')
  await router.isReady()

  const wrapper = shallowMount(StockDetailView, {
    global: {
      plugins: [pinia, router, ElementPlus],
      directives: {
        permission: {},
      },
      stubs: {
        LayoutHost: {
          template: '<main><slot name="action"/><slot name="main"/><slot name="overlays"/></main>',
        },
        StockChartWorkspace: StockChartWorkspaceStub,
        AppStateBlock: AppStateBlockStub,
        KlineRangeSelect: KlineRangeSelectStub,
        PageSettingsDrawer: true,
        PageSettingsTrigger: true,
        PageSettingSection: { template: '<section><slot/></section>' },
        PageSegmented: true,
        PageToggleRow: true,
        KlineSettingSection: true,
        ElCard: { template: '<section><slot name="header"/><slot/></section>' },
        ElDescriptions: { template: '<dl><slot/></dl>' },
        ElDescriptionsItem: {
          props: ['label'],
          template: '<div><dt>{{ label }}</dt><dd><slot/></dd></div>',
        },
      },
    },
  })
  await flushPromises()
  await nextTick()
  return wrapper
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
  vi.mocked(stocksApi.getTradeEval).mockResolvedValue({
    code: '600000.SH',
    date: '2026-07-23',
    profile_id: 'trade-1',
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
  vi.mocked(tradeProfileApi.listTradeProfiles).mockResolvedValue([
    {
      id: 'trade-1',
      name: '默认买卖',
      version: 1,
      is_preset: true,
    } as any,
  ])
}

describe('StockDetailView 三图数据协调', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pageSettingsState.current = null
    localStorage.clear()
    setDefaultApiResponses()
  })

  it('初次并行加载行情、全量指标序列和报价，并把默认三图接入页面', async () => {
    const wrapper = await mountView()
    const workspace = wrapper.findComponent(StockChartWorkspaceStub)

    expect(stocksApi.getBars).toHaveBeenCalledWith(
      '600000.SH',
      { adjust: 'qfq', lookback: 1250 },
      expect.any(AbortSignal),
    )
    expect(stocksApi.getBars).toHaveBeenCalledWith(
      '600000.SH',
      { adjust: '', lookback: 1 },
      expect.any(AbortSignal),
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
    expect(wrapper.text()).toContain('12.34')
  })

  it('复权只刷新行情；范围同时刷新行情和指标，不重复请求报价或买卖评估', async () => {
    const wrapper = await mountView()
    const initialBars = vi.mocked(stocksApi.getBars).mock.calls.length
    const initialIndicators = vi.mocked(stocksApi.getIndicators).mock.calls.length
    const initialTrade = vi.mocked(stocksApi.getTradeEval).mock.calls.length

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
    const quoteCalls = vi.mocked(stocksApi.getBars).mock.calls.filter(
      ([, params]) => params?.lookback === 1,
    )
    expect(quoteCalls).toHaveLength(1)

    const barsAfterRange = vi.mocked(stocksApi.getBars).mock.calls.length
    const indicatorsAfterRange = vi.mocked(stocksApi.getIndicators).mock.calls.length
    pageSettingsState.current.charts.slot3 = 'hidden'
    await nextTick()
    await flushPromises()

    expect(stocksApi.getBars).toHaveBeenCalledTimes(barsAfterRange)
    expect(stocksApi.getIndicators).toHaveBeenCalledTimes(indicatorsAfterRange)
    expect(wrapper.findComponent(StockChartWorkspaceStub).props('slot3')).toBe('hidden')
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
      { id: 'trade-1', name: '方案一', version: 1, is_preset: true } as any,
      { id: 'trade-2', name: '方案二', version: 1, is_preset: true } as any,
    ])
    const oldTrade = deferred<Awaited<ReturnType<typeof stocksApi.getTradeEval>>>()
    vi.mocked(stocksApi.getTradeEval)
      .mockImplementationOnce(() => oldTrade.promise)
      .mockResolvedValueOnce({
        code: '600000.SH',
        date: '2026-07-23',
        profile_id: 'trade-2',
        name: '方案二',
        version: 2,
        buy_signal: false,
        sell_signal: false,
        buy: { op: 'AND', conds: [] },
        sell: { op: 'AND', conds: [] },
        backstop: {},
      })

    const wrapper = await mountView()
    const tradeSelect = wrapper.findAllComponents({ name: 'ElSelect' }).find(
      (component) => component.props('modelValue') === 'trade-1',
    )
    expect(tradeSelect).toBeTruthy()

    tradeSelect!.vm.$emit('update:modelValue', 'trade-2')
    tradeSelect!.vm.$emit('change', 'trade-2')
    await nextTick()
    await flushPromises()

    const tradeCalls = vi.mocked(stocksApi.getTradeEval).mock.calls
    expect(tradeCalls[0][3]?.aborted).toBe(true)
    expect(tradeCalls[1][1]).toBe('trade-2')
    expect(wrapper.text()).toContain('v2')

    oldTrade.resolve({
      code: '600000.SH',
      date: '2026-07-22',
      profile_id: 'trade-1',
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
