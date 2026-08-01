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
import AssetProfileLabel from '@/components/AssetProfileLabel.vue'
import type { Layers } from '@/api/backtest'

// 合法 Layers fixture（P1-3）：layers 不可为 {}——渲染访问 grades_order/by_grade/base_rate，
// mock 成 {} 会抛「grades_order is not iterable」unhandled error（组件崩溃后断言仍通过的假绿根因）。
function validLayers(): Layers {
  return {
    date_start: '2024-01-01', date_end: '2024-06-30',
    horizons: [10, 20], thresholds: [0.1, 0.2],
    min_samples: 1, total_signals: 0,
    base_rate: {}, by_grade: {}, grades_order: [],
  }
}

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
const AssetSearchDrawerStub = assetCompStub('AssetSearchDrawer', 'asset-search-drawer-stub')

// 选择器 stub（方案b）：只声明 props/emits、渲染占位 div。临时项名称改由页面级 chip 渲染（选择器外），
// 不再由 stub 承接；页面 chip 用 AssetProfileLabel 真实渲染，jsdom 可直接断言其文本（名称非 opaque ref）。
const AssetProfileSelectStub = defineComponent({
  name: 'AssetProfileSelect',
  props: ['modelValue', 'assetLabel', 'kind', 'fetchMine', 'browse', 'copyItem', 'copyPermission', 'viewPermission', 'rerunItem', 'rerunPermission', 'canBrowse', 'placeholder', 'labelMine', 'testId'],
  emits: ['update:modelValue', 'ready', 'loaded', 'copiedItem', 'copied', 'load', 'rerunDone'],
  setup() {
    return () => h('div', { 'data-testid': 'asset-profile-select-stub' })
  },
})

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
  // 占位替代布尔 stub(true)：布尔 stub 在 el-option v-for 等结构下会触发 emitsOptions 空引用
  AssetVisibilityActions: { template: '<div />' },
  AssetVisibilityTag: { template: '<div />' },
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

// getRun 返回的合法结构（layers 用 validLayers，避免 grades_order 崩溃假绿）
function getRunDetail(params: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    run: {
      id: 'r1', run_ref: 'run_ref_1', kind: 'strategy',
      date_start: '2024-01-01', date_end: '2024-06-30', created_at: '2024-07-01 10:00:00',
      params: JSON.stringify(params), ...extra,
    },
    metrics: {}, layers: validLayers(), trades: [], equity: [],
  } as any
}

// 触发「加载查看」：直接 emit loaded（方案b 下页面记 tempSelected 快照、渲染选择器外 chip）。
async function emitLoaded(wrapper: VueWrapper, testId: string, item: unknown) {
  const sel = findSelect(wrapper, testId)!
  sel.vm.$emit('loaded', item)
  await nextTick()
  await flushPromises()
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
    wrapper.unmount()
  })

  it('fetchMine 以 source=mine 调对应 list（组件真实挂载时触发，此处直接调回调验证口径）', async () => {
    const wrapper = await mountView()
    await findSelect(wrapper, 'backtest-score-select')!.props('fetchMine')()
    expect(scoreApi.listScoreProfiles).toHaveBeenCalledWith('mine')
    await findSelect(wrapper, 'backtest-screen-select')!.props('fetchMine')()
    expect(screeningApi.listProfiles).toHaveBeenCalledWith('mine')
    await findSelect(wrapper, 'backtest-trade-select')!.props('fetchMine')()
    expect(tradeApi.listTradeProfiles).toHaveBeenCalledWith('mine')
    wrapper.unmount()
  })

  it('「加载查看」选择器外 chip 显示名称（非 opaque ref）、不改选择器选中、不运行、不持久化（方案b）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.props('modelValue')).toBe('')
    vi.mocked(backtestApi.runBacktest).mockClear()

    await emitLoaded(wrapper, 'backtest-score-select', {
      id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true,
    })
    // 不破组件递归契约：选择器 modelValue 不被设为临时项
    expect(score.props('modelValue')).toBe('')
    expect(backtestApi.runBacktest).not.toHaveBeenCalled()
    // 名称经选择器外 chip 渲染（AssetProfileLabel），非 opaque ref
    const chip = wrapper.find('[data-testid="backtest-score-select-temp"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('公开评分')
    expect(chip.text()).not.toContain('avr_score_pub')
    // 临时项不入持久偏好
    expect(localStorage.getItem('ai-stocks-backtest-params') ?? '').not.toContain('avr_score_pub')
    wrapper.unmount()
  })

  it('临时项作为运行口径：选择器为空时 buildBody 按 tempSelected 快照取 ref（P1-3 方案b 运行路径）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    await emitLoaded(wrapper, 'backtest-trade-select', {
      id: 'pub-t', profile_ref: 'avr_trade_pub', name: '公开买卖', version: 2, source: 'public', readonly: true,
    })
    // 选择器为空、临时项在 → 卖出规则行用临时项名称（tradeProfileName 回退 tempSelected）
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
    expect((wrapper.vm as any).tradeProfileName('avr_trade_pub')).toBe('公开买卖')
    // buildBody 在选择器为空时按 tempSelected 快照取 ref（运行可使用临时方案）
    const body = (wrapper.vm as any).buildBody()
    expect(body.trade_profile_id).toBe('avr_trade_pub')
    wrapper.unmount()
  })

  it('临时→mine 切换即丢弃临时项：chip 消失、保存偏好写的是 mine 选择（P1-2 路径1）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    await emitLoaded(wrapper, 'backtest-score-select', {
      id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true,
    })
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(true)
    // 用户改选自己的方案（mine 列表 avr_score_1）
    const score = findSelect(wrapper, 'backtest-score-select')!
    score.vm.$emit('update:modelValue', 'avr_score_1')
    await flushPromises()
    // 临时项被清除（chip 消失）
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    // 保存偏好写的是有效 mine 选择，不被误剔除为空（rememberedParams 经 watcher 持久化到 localStorage）
    ;(wrapper.vm as any).saveParams()
    expect((wrapper.vm as any).rememberedParams.scoreProfileId).toBe('avr_score_1')
    wrapper.unmount()
  })

  it('复制为我的→不标临时、保存偏好可恢复（P1-2 路径2：copiedItem 不复用 onXLoaded）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    const score = findSelect(wrapper, 'backtest-score-select')!
    // 模拟组件复制成功：ready 重喂含新 mine 项 + copiedItem 回写 + update:modelValue 选中新项
    const copied = { id: 's-copy', profile_ref: 'avr_score_copy', name: '评分副本', version: 1, is_preset: false, source: 'mine' } as any
    score.vm.$emit('ready', [...mineScoreList(), copied])
    score.vm.$emit('copiedItem', copied)
    score.vm.$emit('update:modelValue', 'avr_score_copy')
    await flushPromises()
    // 复制结果不标临时：无 chip
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    // 保存偏好写的是新 mine 选择（不被当临时剔除），刷新可恢复
    ;(wrapper.vm as any).saveParams()
    expect((wrapper.vm as any).rememberedParams.scoreProfileId).toBe('avr_score_copy')
    wrapper.unmount()
  })

  it('旧 public/preset ref：ready 后偏好 hydration 再 restore，最终清空不回弹（P1-1 时序屏障）', async () => {
    localStorage.setItem('ai-stocks-backtest-params', JSON.stringify({
      kind: 'strategy', dateStart: '2024-01-01', dateEnd: '2024-12-31',
      profileId: '', scoreProfileId: 'avr_score_old', tradeProfileId: 'avr_trade_old',
      topN: 10, initCap: 1000000, industryOn: false, industryPct: 20,
    }))
    const wrapper = await mountView()
    await emitAllReady(wrapper) // 列表 ready（reconcile 清掉非 mine 残留）
    expect(findSelect(wrapper, 'backtest-score-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
    // 模拟偏好稍后 hydration：再次触发 restore + reconcile（rememberedParamsHydrated watcher 路径）
    pageSettingsState.current = null // 强制重置；restoreParams 从 localStorage 再读旧 ref
    ;(wrapper.vm as any).restoreParams()
    ;(wrapper.vm as any).reconcileProfileRefs()
    await flushPromises()
    // 旧 ref 最终为空、不回弹（readyFlags 屏障 + reconcile 兜底）
    expect(findSelect(wrapper, 'backtest-score-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
    wrapper.unmount()
  })

  it('旧 public/preset ref 恢复后 ready 清空并提示重新选择（R3 下拉仅 mine）', async () => {
    localStorage.setItem('ai-stocks-backtest-params', JSON.stringify({
      kind: 'strategy', dateStart: '2024-01-01', dateEnd: '2024-12-31',
      profileId: '', scoreProfileId: 'avr_score_old', tradeProfileId: 'avr_trade_old',
      topN: 10, initCap: 1000000, industryOn: false, industryPct: 20,
    }))
    const wrapper = await mountView()
    await emitAllReady(wrapper) // ready 列表落地后清掉非 mine 残留
    expect(findSelect(wrapper, 'backtest-score-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
    wrapper.unmount()
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
    wrapper.unmount()
  })

  it('「加载查看」公开回测 → 调 getRun 载入结果（不重跑），readonly 行注入使删除不可见（P1-4）', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail(
      { date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'avr_score_1', profile_id: 'avr_screen_1', trade_profile_id: 'avr_trade_1', top_n: 10, initial_capital: 1000000 },
    ))
    vi.mocked(backtestApi.runBacktest).mockClear()

    const drawer = runDrawer(wrapper)!
    drawer.vm.$emit('load', { id: 'r1', run_ref: 'run_ref_1', kind: 'strategy', readonly: true, source: 'public' })
    await flushPromises()
    expect(backtestApi.getRun).toHaveBeenCalledWith('run_ref_1')
    expect(backtestApi.runBacktest).not.toHaveBeenCalled()
    // 公开只读行 → 删除按钮不可见（readonly fail-closed，非默认可写）
    expect(wrapper.findAll('button').some((b) => b.text() === '删除')).toBe(false)
    wrapper.unmount()
  })

  it('「复用参数重跑」完整复制回测参数（撮合/基准/阈值，P1-1）+ source_run_ref', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail({
      date_start: '2024-01-01', date_end: '2024-06-30',
      score_profile_id: 'avr_score_1', profile_id: 'avr_screen_1', trade_profile_id: 'avr_trade_1',
      top_n: 5, initial_capital: 500000, industry_max_pct: 0.2,
      sell_ma_period: 30, take_profit: 0.25, stop_loss: 0.08, max_hold_days: 40, rebalance_days: 5,
      benchmark: '000300.SH', horizons: [5, 15], thresholds: [0.05, 0.15],
    }, { id: 'r9', run_ref: 'run_ref_9' }))
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
    // 基础字段
    expect(body.score_profile_id).toBe('avr_score_1')
    expect(body.profile_id).toBe('avr_screen_1')
    expect(body.trade_profile_id).toBe('avr_trade_1')
    expect(body.horizons).toEqual([5, 15])          // 沿用历史分层阈值，不被常量覆盖
    expect(body.thresholds).toEqual([0.05, 0.15])
    expect(body.benchmark).toBe('000300.SH')
    // 撮合参数（缺一即改变撮合与收益，P1-1 核心）
    expect(body.top_n).toBe(5)
    expect(body.initial_capital).toBe(500000)
    expect(body.industry_max_pct).toBe(0.2)
    expect(body.sell_ma_period).toBe(30)
    expect(body.take_profit).toBe(0.25)
    expect(body.stop_loss).toBe(0.08)
    expect(body.max_hold_days).toBe(40)
    expect(body.rebalance_days).toBe(5)
    wrapper.unmount()
  })

  it('rerunDone 携带新 run 返回值，按 run_id 精确选中并切到我的（P2-5）', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.listRuns).mockResolvedValue({
      runs: [
        { id: 'older', run_ref: 'run_ref_older', kind: 'strategy' } as any,
        { id: 'new_run', run_ref: 'run_ref_new', kind: 'strategy' } as any,
      ],
    })
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail({ date_start: '2024-01-01', date_end: '2024-06-30' }))

    const drawer = runDrawer(wrapper)!
    // 真实组件会 emit('rerunDone', result, item)；此处直接驱动父级回调验证按 run_id 选中
    drawer.vm.$emit('rerunDone', { run_id: 'new_run' }, { id: 'r9', run_ref: 'run_ref_9', kind: 'strategy' })
    await flushPromises()
    expect(backtestApi.listRuns).toHaveBeenCalled()
    // 选中的必须是返回值指定的新 run（new_run 不在列表首行，证明非盲选 [0]）
    expect(backtestApi.getRun).toHaveBeenCalledWith('run_ref_new')
    wrapper.unmount()
  })

  it('复用重跑不写回表单、不改当前选中（决策2，与 reuseCurrentRunParams 语义不同）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.props('modelValue')).toBe('')
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail(
      { date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'avr_score_1', trade_profile_id: 'avr_trade_1', top_n: 5 },
    ))
    vi.mocked(backtestApi.runBacktest).mockResolvedValue({ run_id: 'new_run' } as any)

    const drawer = runDrawer(wrapper)!
    const rerun = drawer.props('rerunItem') as (i: unknown) => Promise<unknown>
    await rerun({ id: 'r9', run_ref: 'run_ref_9', kind: 'strategy' })
    await flushPromises()
    // 表单选中未被改写（重跑不复用到表单）
    expect(score.props('modelValue')).toBe('')
    wrapper.unmount()
  })

  it('无 backtest:view 时抽屉 canBrowse=false 且不渲染触发按钮', async () => {
    const wrapper = await mountView(ALL_PERMS.filter((p) => p !== 'backtest:view'))
    const drawer = runDrawer(wrapper)!
    expect(drawer.props('canBrowse')).toBe(false)
    expect(wrapper.find('[data-testid="backtest-browse-open"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
