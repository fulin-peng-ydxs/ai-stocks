// @vitest-environment jsdom
// T5：BacktestView 三方案选择器统一接入 AssetProfileSelect（select 形态）+ 历史区「浏览公开回测」抽屉。
// 列表由组件 ready 事件提供（组件为唯一事实源，P2-1），本 spec 用 emit 驱动；不真实打开抽屉，
// 编辑器/历史区 el-select 在 jsdom 下会触发递归更新循环（真实浏览器正常，已复验），故全局 stub。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { defineComponent, h, nextTick, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const pageSettingsState = vi.hoisted(() => ({ current: null as any }))

vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: (_key: string, defaults: Record<string, unknown>) => {
    pageSettingsState.current ??= reactive(structuredClone(defaults))
    return {
      settings: pageSettingsState.current,
      isDirty: ref(false),
      reset: vi.fn(),
    }
  },
}))

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

vi.mock('@/api/backtest', () => ({
  runBacktest: vi.fn(),
  prepareBacktest: vi.fn(async () => ({ duplicate: null })),
  listRuns: vi.fn(async () => ({ runs: [] })),
  getRun: vi.fn(),
  deleteRun: vi.fn(),
  runRobust: vi.fn(),
  setRunVisibility: vi.fn(),
  browseRuns: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'public' })),
}))

vi.mock('@/api/screening', () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(async () => null),
  browseProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyProfile: vi.fn(),
}))

vi.mock('@/api/scoreProfile', () => ({
  listScoreProfiles: vi.fn(),
  browseScoreProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyScoreProfile: vi.fn(),
}))

vi.mock('@/api/tradeProfile', () => ({
  listTradeProfiles: vi.fn(),
  browseTradeProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyTradeProfile: vi.fn(),
}))

import * as backtestApi from '@/api/backtest'
import * as screeningApi from '@/api/screening'
import * as scoreApi from '@/api/scoreProfile'
import * as tradeApi from '@/api/tradeProfile'
import BacktestView from '@/views/BacktestView.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AssetSearchDrawer from '@/components/asset-search/AssetSearchDrawer.vue'

const ElSelectStub = defineComponent({
  name: 'ElSelect',
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  setup(props, { slots }) {
    return () => h('div', { 'data-model-value': String(props.modelValue ?? '') }, slots.default?.())
  },
})
const ElOptionStub = defineComponent({
  name: 'ElOption',
  props: ['label', 'value'],
  setup(props, { slots }) {
    return () => h('span', { 'data-value': String(props.value ?? '') }, slots.default?.() ?? String(props.label ?? ''))
  },
})

// 共享组件浅 stub：声明 props+emits、渲染占位 div（带 testid），不渲染内部 el-select/teleport。
// 断言走 findComponent(...).props() + vm.$emit 驱动；避免布尔 stub(true) 在 emit 时
// 触发 Vue 内部 emitsOptions 读取空值的 unhandled rejection 噪音。
function assetCompStub(name: string, testId: string) {
  return defineComponent({
    name,
    props: ['modelValue', 'assetLabel', 'kind', 'fetchMine', 'browse', 'copyItem', 'copyPermission', 'viewPermission', 'rerunItem', 'rerunPermission', 'canBrowse', 'placeholder', 'labelMine', 'testId'],
    emits: ['update:modelValue', 'ready', 'loaded', 'copiedItem', 'copied', 'load', 'rerunDone'],
    setup() {
      return () => h('div', { 'data-testid': testId })
    },
  })
}
const AssetProfileSelectStub = assetCompStub('AssetProfileSelect', 'asset-profile-select-stub')
const AssetSearchDrawerStub = assetCompStub('AssetSearchDrawer', 'asset-search-drawer-stub')

const stubs = {
  LayoutHost: { template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>' },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  TradeDatePicker: true,
  PageSegmented: true,
  PageSettingSection: { template: '<section><slot/></section>' },
  PageToggleRow: true,
  HelpTip: { template: '<span><slot/></span>' },
  EquityChart: true,
  CandleChart: true,
  ElSelect: ElSelectStub,
  ElOption: ElOptionStub,
  AssetProfileSelect: AssetProfileSelectStub,
  AssetSearchDrawer: AssetSearchDrawerStub,
}

const ALL_PERMS = [
  'backtest:view', 'backtest:run', 'backtest:delete',
  'screen-profile:view', 'score-profile:view', 'trade-profile:view',
]

function mineScoreList() {
  return [{ id: 's1', profile_ref: 'avr_score_1', name: '默认趋势分', version: 2, is_preset: false } as any]
}
function mineScreenList() {
  return [{ id: 'p1', profile_ref: 'avr_screen_1', name: '趋势筛选', version: 1, is_preset: false } as any]
}
function mineTradeList() {
  return [{ id: 't1', profile_ref: 'avr_trade_1', name: '趋势买卖', version: 4, is_preset: false } as any]
}

async function mountView(permissions = ALL_PERMS): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = permissions
  auth.menusStatus = 'ready'
  auth.tenant = { id: 'tenant-a' }
  const wrapper = mount(BacktestView, {
    attachTo: document.body,
    global: { plugins: [pinia, ElementPlus], stubs, directives: { permission: {} } },
  })
  await flushPromises()
  await nextTick()
  return wrapper
}

// 组件 stub 不自行 emit ready，显式触发模拟装载「我的」列表（组件为唯一事实源，P2-1）
function findSelect(wrapper: VueWrapper, testId: string) {
  return wrapper.findAllComponents(AssetProfileSelect).find((c) => c.props('testId') === testId)
}
async function emitAllReady(wrapper: VueWrapper) {
  await findSelect(wrapper, 'backtest-score-select')!.vm.$emit('ready', mineScoreList())
  await findSelect(wrapper, 'backtest-screen-select')!.vm.$emit('ready', mineScreenList())
  await findSelect(wrapper, 'backtest-trade-select')!.vm.$emit('ready', mineTradeList())
  await flushPromises()
}
function runDrawer(wrapper: VueWrapper) {
  return wrapper.findAllComponents(AssetSearchDrawer).find((c) => c.props('kind') === 'backtest')
}

beforeEach(() => {
  vi.clearAllMocks()
  pageSettingsState.current = null
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(backtestApi.listRuns).mockResolvedValue({ runs: [] })
})

describe('BacktestView 三方案选择器（T5）', () => {
  it('评分/选股/买卖统一走 AssetProfileSelect，fetchMine/browse/copy 为函数、权限码正确', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    const screen = findSelect(wrapper, 'backtest-screen-select')!
    const trade = findSelect(wrapper, 'backtest-trade-select')!
    expect(score.exists() && screen.exists() && trade.exists()).toBe(true)

    expect(score.props('assetLabel')).toBe('评分方案')
    expect(screen.props('assetLabel')).toBe('选股方案')
    expect(trade.props('assetLabel')).toBe('买卖方案')

    for (const sel of [score, screen, trade]) {
      expect(typeof sel.props('fetchMine')).toBe('function')
      expect(typeof sel.props('browse')).toBe('function')
      expect(typeof sel.props('copyItem')).toBe('function')
    }
    expect(score.props('copyPermission')).toBe('score-profile:save')
    expect(score.props('viewPermission')).toBe('score-profile:view')
    expect(screen.props('copyPermission')).toBe('screen-profile:save')
    expect(screen.props('viewPermission')).toBe('screen-profile:view')
    expect(trade.props('copyPermission')).toBe('trade-profile:save')
    expect(trade.props('viewPermission')).toBe('trade-profile:view')
  })

  it('fetchMine 以 source=mine 调对应 list（组件真实挂载时触发，此处直接调回调验证口径）', async () => {
    const wrapper = await mountView()
    await findSelect(wrapper, 'backtest-score-select')!.props('fetchMine')()
    expect(scoreApi.listScoreProfiles).toHaveBeenCalledWith('mine')
    await findSelect(wrapper, 'backtest-screen-select')!.props('fetchMine')()
    expect(screeningApi.listProfiles).toHaveBeenCalledWith('mine')
    await findSelect(wrapper, 'backtest-trade-select')!.props('fetchMine')()
    expect(tradeApi.listTradeProfiles).toHaveBeenCalledWith('mine')
  })

  it('「加载查看」只并入候选、不选中、不运行（决策1）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.props('modelValue')).toBe('')
    vi.mocked(backtestApi.runBacktest).mockClear()

    // 加载查看公开评分方案 → 并入候选，但不改选中、不发回测
    score.vm.$emit('loaded', {
      id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true,
    })
    await flushPromises()
    expect(score.props('modelValue')).toBe('')  // 未自动选中
    expect(backtestApi.runBacktest).not.toHaveBeenCalled()
  })
})

describe('BacktestView 历史区「浏览公开回测」（T5）', () => {
  it('存在 kind=backtest 抽屉，rerunPermission=backtest:run、canBrowse 依 backtest:view', async () => {
    const wrapper = await mountView()
    const drawer = runDrawer(wrapper)!
    expect(drawer.exists()).toBe(true)
    expect(drawer.props('assetLabel')).toBe('回测')
    expect(drawer.props('rerunPermission')).toBe('backtest:run')
    expect(drawer.props('canBrowse')).toBe(true)
    expect(typeof drawer.props('rerunItem')).toBe('function')
    // 触发按钮存在
    expect(wrapper.find('[data-testid="backtest-browse-open"]').exists()).toBe(true)
  })

  it('「加载查看」公开回测 → 调 getRun 载入结果（不重跑）', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockResolvedValue({
      run: {
        id: 'r1', run_ref: 'run_ref_1', kind: 'strategy',
        date_start: '2024-01-01', date_end: '2024-06-30', created_at: '2024-07-01 10:00:00',
        params: JSON.stringify({ date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'avr_score_1', profile_id: 'avr_screen_1', trade_profile_id: 'avr_trade_1', top_n: 10, initial_capital: 1000000 }),
      },
      metrics: {}, layers: {}, trades: [], equity: [],
    } as any)
    vi.mocked(backtestApi.runBacktest).mockClear()

    const drawer = runDrawer(wrapper)!
    drawer.vm.$emit('load', { id: 'r1', run_ref: 'run_ref_1', kind: 'strategy' })
    await flushPromises()
    expect(backtestApi.getRun).toHaveBeenCalledWith('run_ref_1')
    expect(backtestApi.runBacktest).not.toHaveBeenCalled()
  })

  it('「复用参数重跑」→ getRun + runBacktest，body 含 source_run_ref，成功后刷新历史（决策2，不弹确认）', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockResolvedValue({
      run: {
        id: 'r9', run_ref: 'run_ref_9', kind: 'strategy',
        date_start: '2024-01-01', date_end: '2024-06-30',
        params: JSON.stringify({ date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'avr_score_1', profile_id: 'avr_screen_1', trade_profile_id: 'avr_trade_1', top_n: 5, initial_capital: 500000 }),
      },
      metrics: {}, layers: {}, trades: [], equity: [],
    } as any)
    vi.mocked(backtestApi.runBacktest).mockResolvedValue({ run_id: 'new_run' } as any)
    vi.mocked(backtestApi.listRuns).mockResolvedValue({ runs: [{ id: 'new_run', run_ref: 'run_ref_new', kind: 'strategy' } as any] })

    const drawer = runDrawer(wrapper)!
    const rerun = drawer.props('rerunItem') as (i: unknown) => Promise<unknown>
    await rerun({ id: 'r9', run_ref: 'run_ref_9', kind: 'strategy' })

    expect(backtestApi.getRun).toHaveBeenCalledWith('run_ref_9')
    expect(backtestApi.runBacktest).toHaveBeenCalledTimes(1)
    const body = vi.mocked(backtestApi.runBacktest).mock.calls[0][0] as any
    expect(body.source_run_ref).toBe('run_ref_9')
    expect(body.kind).toBe('strategy')
    expect(body.top_n).toBe(5)
    expect(body.score_profile_id).toBe('avr_score_1')

    // rerunDone → 刷新历史
    drawer.vm.$emit('rerunDone', { id: 'new_run', run_ref: 'run_ref_new' })
    await flushPromises()
    expect(backtestApi.listRuns).toHaveBeenCalled()
  })

  it('复用重跑不写回表单、不改当前选中（决策2，与 reuseCurrentRunParams 语义不同）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.props('modelValue')).toBe('')
    vi.mocked(backtestApi.getRun).mockResolvedValue({
      run: {
        id: 'r9', run_ref: 'run_ref_9', kind: 'strategy', date_start: '2024-01-01', date_end: '2024-06-30',
        params: JSON.stringify({ date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'avr_score_1', trade_profile_id: 'avr_trade_1', top_n: 5 }),
      },
      metrics: {}, layers: {}, trades: [], equity: [],
    } as any)
    vi.mocked(backtestApi.runBacktest).mockResolvedValue({ run_id: 'new_run' } as any)

    const drawer = runDrawer(wrapper)!
    const rerun = drawer.props('rerunItem') as (i: unknown) => Promise<unknown>
    await rerun({ id: 'r9', run_ref: 'run_ref_9', kind: 'strategy' })
    await flushPromises()
    // 表单选中未被改写（重跑不复用到表单）
    expect(score.props('modelValue')).toBe('')
  })

  it('无 backtest:view 时抽屉 canBrowse=false 且不渲染触发按钮', async () => {
    const wrapper = await mountView(ALL_PERMS.filter((p) => p !== 'backtest:view'))
    const drawer = runDrawer(wrapper)!
    expect(drawer.props('canBrowse')).toBe(false)
    expect(wrapper.find('[data-testid="backtest-browse-open"]').exists()).toBe(false)
  })
})
