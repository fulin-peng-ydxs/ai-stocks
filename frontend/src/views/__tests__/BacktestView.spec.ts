// @vitest-environment jsdom
// T5：BacktestView 三方案选择器统一接入 AssetProfileSelect（select 形态）+ 历史区「浏览公开回测」抽屉。
// 列表由组件 ready 事件提供（组件为唯一事实源，P2-1），本 spec 用 emit 驱动；不真实打开抽屉，
// 编辑器/历史区 el-select 在 jsdom 下会触发递归更新循环（真实浏览器正常，已复验），故全局 stub。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessage } from 'element-plus'
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
  props: {
    modelValue: { default: '' },
    fitInputWidth: Boolean,
    placement: { type: String, default: '' },
  },
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
  AssetVisibilityTag: {
    props: ['source'],
    template: '<span v-if="source" class="asset-source-stub">{{ source }}</span>',
  },
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
    expect(score.props('placeholder')).toBe('请选择评分方案（必选）')
    expect(screen.props('placeholder')).toBe('不使用选股方案（默认）')
    expect(trade.props('placeholder')).toBe('请选择买卖方案（必选）')

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

  it('顶部历史只加载我的记录，不再渲染与公开浏览重复的来源下拉', async () => {
    const wrapper = await mountView()
    expect(backtestApi.listRuns).toHaveBeenCalledWith('strategy', 'mine')
    expect(wrapper.find('.history-source-select').exists()).toBe(false)
    expect(wrapper.text()).toContain('回测记录')
    expect(wrapper.find('[data-testid="backtest-browse-open"]').exists()).toBe(true)
    const historySelect = wrapper.findAllComponents(ElSelectStub)
      .find((select) => select.classes().includes('history-run-select'))
    expect(historySelect?.props('fitInputWidth')).toBe(true)
    expect(historySelect?.props('placement')).toBe('bottom-start')
    wrapper.unmount()
  })

  it('mine-only 回测记录下拉不重复显示“我的”来源标签', async () => {
    vi.mocked(backtestApi.listRuns).mockResolvedValue({
      runs: [{
        id: 'mine-run', run_ref: 'run_ref_mine', kind: 'strategy',
        date_start: '2024-01-01', date_end: '2024-12-31',
        score_profile_name: '我的评分', profile_name: '我的选股', trade_profile_name: '我的买卖',
        source: 'mine', readonly: false,
      } as any],
    })
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail(
      { date_start: '2024-01-01', date_end: '2024-12-31' },
      { id: 'mine-run', run_ref: 'run_ref_mine' },
    ))
    const wrapper = await mountView()

    expect(wrapper.find('.history-run-select').text()).toContain('我的评分-我的选股-我的买卖')
    expect(wrapper.find('.history-run-select').find('.asset-source-stub').exists()).toBe(false)
    wrapper.unmount()
  })

  it('公开回测加载查看使用独立只读快照，不混入我的记录下拉', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail(
      { date_start: '2024-01-01', date_end: '2024-06-30' },
      { id: 'public-run', run_ref: 'run_ref_public' },
    ))
    const item = {
      id: 'public-run', run_ref: 'run_ref_public', kind: 'strategy',
      date_start: '2024-01-01', date_end: '2024-06-30', created_at: '2024-07-01 10:00:00',
      score_profile_name: '公开评分', profile_name: '公开选股', trade_profile_name: '公开买卖',
      source: 'public', readonly: true,
    } as any

    runDrawer(wrapper)!.vm.$emit('load', item)
    await flushPromises()

    expect((wrapper.vm as any).runHistory).toEqual([])
    expect((wrapper.vm as any).selectedRun).toBe('')
    expect(wrapper.find('[data-testid="backtest-external-run"]').text()).toContain('公开评分-公开选股-公开买卖')
    expect(wrapper.find('[data-testid="backtest-external-run"] .asset-source-stub').text()).toBe('public')
    expect(backtestApi.getRun).toHaveBeenCalledWith('run_ref_public')
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

  it('临时项作为运行口径：buildBody 按 tempSelected 快照取 ref（方案b 运行路径）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    await emitLoaded(wrapper, 'backtest-trade-select', {
      id: 'pub-t', profile_ref: 'avr_trade_pub', name: '公开买卖', version: 2, source: 'public', readonly: true,
    })
    // buildBody 按 tempSelected 快照取 ref
    const body = (wrapper.vm as any).buildBody()
    expect(body.trade_profile_id).toBe('avr_trade_pub')
    expect(wrapper.find('.sell-row').text()).toContain('公开买卖')
    wrapper.unmount()
  })

  it('已有 mine 买卖方案时临时公开快照同时驱动运行参数和卖出规则名称', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    findSelect(wrapper, 'backtest-trade-select')!.vm.$emit('update:modelValue', 'avr_trade_1')
    await flushPromises()
    await emitLoaded(wrapper, 'backtest-trade-select', {
      id: 'pub-t', profile_ref: 'avr_trade_pub', name: '公开买卖', version: 2, source: 'public', readonly: true,
    })

    expect((wrapper.vm as any).buildBody().trade_profile_id).toBe('avr_trade_pub')
    expect(wrapper.find('.sell-row').text()).toContain('公开买卖')
    expect(wrapper.find('.sell-row').text()).not.toContain('趋势买卖')
    wrapper.unmount()
  })

  it('普通回测与稳健性测试共用同一临时快照 ref，不出现展示/运行口径分叉', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    await emitLoaded(wrapper, 'backtest-score-select', {
      id: 'pub-s', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true,
    })
    await emitLoaded(wrapper, 'backtest-screen-select', {
      id: 'pub-p', profile_ref: 'avr_screen_pub', name: '公开选股', version: 2, source: 'public', readonly: true,
    })
    await emitLoaded(wrapper, 'backtest-trade-select', {
      id: 'pub-t', profile_ref: 'avr_trade_pub', name: '公开买卖', version: 4, source: 'public', readonly: true,
    })
    vi.mocked(backtestApi.runRobust).mockResolvedValue({ rows: [] } as any)

    const normal = (wrapper.vm as any).buildBody()
    await (wrapper.vm as any).runRobustTest()

    expect(backtestApi.runRobust).toHaveBeenCalledTimes(1)
    const robust = vi.mocked(backtestApi.runRobust).mock.calls[0][0] as any
    expect(robust.params.profile_id).toBe(normal.profile_id)
    expect(robust.params.score_profile_id).toBe(normal.score_profile_id)
    expect(robust.params.trade_profile_id).toBe(normal.trade_profile_id)
    expect(robust.params).toMatchObject({
      profile_id: 'avr_screen_pub',
      score_profile_id: 'avr_score_pub',
      trade_profile_id: 'avr_trade_pub',
    })
    wrapper.unmount()
  })

  it('自动载入含系统方案的历史记录时显示中文名称，不把内部 id 写入 mine-only 选择器', async () => {
    vi.mocked(backtestApi.listRuns).mockResolvedValue({
      runs: [{
        id: 'r-system', run_ref: 'run_ref_system', kind: 'strategy',
        date_start: '2024-01-01', date_end: '2024-06-30', created_at: '2024-07-01 10:00:00',
        profile_name: '趋势龙头', profile_version: 1,
        score_profile_name: '默认趋势分', score_profile_version: 2,
        trade_profile_name: '趋势买卖', trade_profile_version: 3,
      } as any],
    })
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail({
      date_start: '2024-01-01', date_end: '2024-06-30',
      profile_id: 'preset_trend_leader', score_profile_id: 'default', trade_profile_id: 'default',
      top_n: 3, initial_capital: 1000000,
    }, { id: 'r-system', run_ref: 'run_ref_system' }))

    const wrapper = await mountView()
    await emitAllReady(wrapper)

    expect(findSelect(wrapper, 'backtest-score-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-screen-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').text()).toContain('默认趋势分')
    expect(wrapper.find('[data-testid="backtest-screen-select-temp"]').text()).toContain('趋势龙头')
    expect(wrapper.find('[data-testid="backtest-trade-select-temp"]').text()).toContain('趋势买卖')
    expect(wrapper.text()).not.toContain('preset_trend_leader')

    // 用户随后加载另一公开方案时，历史投影必须让位；列表再次 ready 也不能把旧历史快照覆盖回来。
    await emitLoaded(wrapper, 'backtest-score-select', {
      id: 'pub-new', profile_ref: 'avr_score_new', name: '新公开评分', version: 5, source: 'public', readonly: true,
    })
    findSelect(wrapper, 'backtest-score-select')!.vm.$emit('ready', mineScoreList())
    await flushPromises()
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').text()).toContain('新公开评分')
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').text()).not.toContain('默认趋势分')
    wrapper.unmount()
  })

  it('历史方案 ref 无名称且不在 mine 列表时显示失效态并阻止运行', async () => {
    vi.mocked(backtestApi.listRuns).mockResolvedValue({
      runs: [{
        id: 'r-stale', run_ref: 'run_ref_stale', kind: 'strategy',
        date_start: '2024-01-01', date_end: '2024-06-30', created_at: '2024-07-01 10:00:00',
      } as any],
    })
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail({
      date_start: '2024-01-01', date_end: '2024-06-30',
      profile_id: 'gone-screen', score_profile_id: 'gone-score', trade_profile_id: 'gone-trade',
    }, { id: 'r-stale', run_ref: 'run_ref_stale' }))

    const wrapper = await mountView()
    await emitAllReady(wrapper)

    expect(wrapper.text()).toContain('历史评分方案已不可用')
    expect(wrapper.text()).toContain('历史选股方案已不可用')
    expect(wrapper.text()).toContain('历史买卖方案已不可用')
    expect((wrapper.vm as any).validateRunSelection()).toBe(false)
    wrapper.unmount()
  })

  it('快照优先（三次复审 P1）：已选 mine → 加载公开 chip 后 buildBody 用公开快照、saveParams 仍保存 mine', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    // 用户先选自己的评分方案 mine-A
    const score = findSelect(wrapper, 'backtest-score-select')!
    score.vm.$emit('update:modelValue', 'avr_score_1')
    await flushPromises()
    // 再对公开方案 public-B 点「加载查看」
    await emitLoaded(wrapper, 'backtest-score-select', {
      id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true,
    })
    // 选择器仍是 mine-A（不动选择器与持久偏好），chip 同时显示 public-B 且标「本次运行：」
    expect(score.props('modelValue')).toBe('avr_score_1')
    const chip = wrapper.find('[data-testid="backtest-score-select-temp"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('本次运行')
    expect(chip.text()).toContain('公开评分')
    // buildBody 用公开快照（快照优先于 mine 选择器值），不是 mine-A
    const body = (wrapper.vm as any).buildBody()
    expect(body.score_profile_id).toBe('avr_score_pub')
    // 持久偏好仍是 mine-A，不被临时快照覆盖
    ;(wrapper.vm as any).saveParams()
    expect((wrapper.vm as any).rememberedParams.scoreProfileId).toBe('avr_score_1')
    wrapper.unmount()
  })

  it('清除 chip 后 buildBody 恢复使用 mine（快照优先的自然回退）', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    const score = findSelect(wrapper, 'backtest-score-select')!
    score.vm.$emit('update:modelValue', 'avr_score_1')
    await flushPromises()
    await emitLoaded(wrapper, 'backtest-score-select', {
      id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true,
    })
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_pub')
    // 用户点清除
    ;(wrapper.vm as any).clearTemp('score')
    await flushPromises()
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    // 恢复用 mine-A
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_1')
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
    // 改选 mine 后临时快照已清，buildBody 用新 mine（覆盖「改选另一个 mine → 用新 mine」）
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_1')
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
    // hydration 已写入页面内部状态、mine 列表尚未 ready 时，也不得把 opaque ref 暴露给 ElSelect。
    expect((wrapper.vm as any).scoreProfileId).toBe('avr_score_old')
    expect((wrapper.vm as any).tradeProfileId).toBe('avr_trade_old')
    expect(findSelect(wrapper, 'backtest-score-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
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
    const warning = vi.spyOn(ElMessage, 'warning')
    await emitAllReady(wrapper) // ready 列表落地后清掉非 mine 残留
    expect(findSelect(wrapper, 'backtest-score-select')!.props('modelValue')).toBe('')
    expect(findSelect(wrapper, 'backtest-trade-select')!.props('modelValue')).toBe('')
    const staleWarnings = warning.mock.calls.filter(([message]) => String(message).includes('方案已不可用'))
    expect(staleWarnings).toHaveLength(1)
    expect(String(staleWarnings[0][0])).toContain('评分/买卖')
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

  it('关闭公开回测恢复进入前的表单、结果与运行按钮状态', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    ;(wrapper.vm as any).dateStart = '2023-01-01'
    ;(wrapper.vm as any).scoreProfileId = 'avr_score_1'
    ;(wrapper.vm as any).dirty = false
    const previousResult = { run_id: 'mine-result', metrics: {}, layers: validLayers(), trades: [], equity: [] }
    ;(wrapper.vm as any).strat = previousResult

    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail({
      date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'public-score',
    }, { id: 'public-run', run_ref: 'run_ref_public' }))
    runDrawer(wrapper)!.vm.$emit('load', {
      id: 'public-run', run_ref: 'run_ref_public', kind: 'strategy',
      score_profile_name: '公开评分', readonly: true, source: 'public',
    })
    await flushPromises()
    expect((wrapper.vm as any).dateStart).toBe('2024-01-01')

    ;(wrapper.vm as any).clearExternalRun()
    await flushPromises()
    expect((wrapper.vm as any).externalRunSummary).toBeNull()
    expect((wrapper.vm as any).dateStart).toBe('2023-01-01')
    expect((wrapper.vm as any).scoreProfileId).toBe('avr_score_1')
    expect((wrapper.vm as any).strat).toStrictEqual(previousResult)
    expect((wrapper.vm as any).dirty).toBe(false)
    wrapper.unmount()
  })

  it('历史回测快速切换时只允许最后一次请求写入页面', async () => {
    const wrapper = await mountView()
    let resolveFirst!: (value: any) => void
    let resolveSecond!: (value: any) => void
    vi.mocked(backtestApi.getRun)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))

    void (wrapper.vm as any).loadRun('run-first')
    void (wrapper.vm as any).loadRun('run-second')
    resolveSecond(getRunDetail({ date_start: '2025-02-01', date_end: '2025-06-30' }, { run_ref: 'run-second' }))
    await flushPromises()
    resolveFirst(getRunDetail({ date_start: '2024-01-01', date_end: '2024-06-30' }, { run_ref: 'run-first' }))
    await flushPromises()

    expect((wrapper.vm as any).dateStart).toBe('2025-02-01')
    expect((wrapper.vm as any).strat?.run_id).toBe('run-second')
    wrapper.unmount()
  })

  it('关闭加载中的公开回测会使迟到响应失效', async () => {
    const wrapper = await mountView()
    let resolveRun!: (value: any) => void
    vi.mocked(backtestApi.getRun).mockImplementationOnce(
      () => new Promise((resolve) => { resolveRun = resolve }),
    )
    runDrawer(wrapper)!.vm.$emit('load', {
      id: 'public-run', run_ref: 'run_ref_public', kind: 'strategy', readonly: true, source: 'public',
    })
    ;(wrapper.vm as any).clearExternalRun()
    resolveRun(getRunDetail({ date_start: '2030-01-01', date_end: '2030-06-30' }))
    await flushPromises()

    expect((wrapper.vm as any).externalRunSummary).toBeNull()
    expect((wrapper.vm as any).dateStart).not.toBe('2030-01-01')
    expect((wrapper.vm as any).strat).toBeNull()
    wrapper.unmount()
  })

  it('评分验证通过页面复用参数后运行仍携带 source_run_ref', async () => {
    const wrapper = await mountView()
    await emitAllReady(wrapper)
    vi.mocked(backtestApi.getRun).mockResolvedValue(getRunDetail({
      date_start: '2024-01-01', date_end: '2024-06-30', score_profile_id: 'avr_score_1',
    }, { id: 'score-run', run_ref: 'score_run_ref', kind: 'score_check' }))
    runDrawer(wrapper)!.vm.$emit('load', {
      id: 'score-run', run_ref: 'score_run_ref', kind: 'score_check', readonly: true, source: 'public',
    })
    await flushPromises()

    await (wrapper.vm as any).reuseCurrentRunParams()
    expect((wrapper.vm as any).buildBody()).toMatchObject({
      kind: 'score_check', score_profile_id: 'avr_score_1', source_run_ref: 'score_run_ref',
    })
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

  it('rerunDone 携带新 run 返回值，单次刷新我的记录并按 run_id 精确选中（P2-5）', async () => {
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
    expect(backtestApi.listRuns).toHaveBeenLastCalledWith('strategy', 'mine')
    // 选中的必须是返回值指定的新 run（new_run 不在列表首行，证明非盲选 [0]）
    expect(backtestApi.getRun).toHaveBeenCalledWith('run_ref_new')
    wrapper.unmount()
  })

  it('rerunDone 刷新失败时不回退选择旧记录', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockClear()
    vi.mocked(backtestApi.listRuns).mockRejectedValueOnce(new Error('network'))
    const warning = vi.spyOn(ElMessage, 'warning')

    runDrawer(wrapper)!.vm.$emit('rerunDone', { run_id: 'new_run' }, { id: 'r9' })
    await flushPromises()

    expect(backtestApi.getRun).not.toHaveBeenCalled()
    expect((wrapper.vm as any).selectedRun).toBe('')
    expect(warning).toHaveBeenCalledWith('重跑已完成，但我的记录刷新失败，请稍后重试')
    wrapper.unmount()
  })

  it('rerunDone 刷新成功但目标记录未出现时不误选首行', async () => {
    const wrapper = await mountView()
    vi.mocked(backtestApi.getRun).mockClear()
    vi.mocked(backtestApi.listRuns).mockResolvedValueOnce({
      runs: [{ id: 'older', run_ref: 'run_ref_older', kind: 'strategy' } as any],
    })
    const warning = vi.spyOn(ElMessage, 'warning')

    runDrawer(wrapper)!.vm.$emit('rerunDone', { run_id: 'new_run' }, { id: 'r9' })
    await flushPromises()

    expect(backtestApi.getRun).not.toHaveBeenCalled()
    expect((wrapper.vm as any).selectedRun).toBe('')
    expect(warning).toHaveBeenCalledWith('重跑已完成，但新记录尚未出现在列表中，请稍后刷新')
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
