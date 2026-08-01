// @vitest-environment jsdom
// T5 复审 P1-3：用**真实 AssetProfileSelect** 挂载 BacktestView，验证「加载查看」在选择器外展示、
// 组件不被设为临时项选中（不破 ElSelect 递归契约）。与 BacktestView.spec.ts 的区别：那里 stub 掉选择器
// 只能断言父页面数组/props，无法发现真实组件 option 所属关系；这里挂真实组件，断言组件内部不锁 tempItem。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { nextTick, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const pageSettingsState = vi.hoisted(() => ({ current: null as any }))

vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: (_key: string, defaults: Record<string, unknown>) => {
    pageSettingsState.current ??= reactive(structuredClone(defaults))
    return { settings: pageSettingsState.current, isDirty: ref(false), reset: vi.fn() }
  },
}))

vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {}, knobs: [], setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
    isDirty: ref(false), resetAll: vi.fn(), componentValueOf: vi.fn(), setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(), layerValuesOf: vi.fn(), componentLayerValuesOf: vi.fn(),
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
  listProfiles: vi.fn(async () => []),
  getProfile: vi.fn(async () => null),
  browseProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyProfile: vi.fn(),
}))
vi.mock('@/api/scoreProfile', () => ({
  listScoreProfiles: vi.fn(async () => []),
  browseScoreProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyScoreProfile: vi.fn(),
}))
vi.mock('@/api/tradeProfile', () => ({
  listTradeProfiles: vi.fn(async () => []),
  browseTradeProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyTradeProfile: vi.fn(),
}))

import * as scoreApi from '@/api/scoreProfile'
import BacktestView from '@/views/BacktestView.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'

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
  AssetVisibilityActions: { template: '<div />' },
  AssetVisibilityTag: { template: '<div />' },
  // 抽屉不真实打开（el-table 幻影行 + teleport），加载查看改由组件 loaded 事件驱动
  AssetSearchDrawer: { template: '<div />', props: ['modelValue'], emits: ['load', 'copied', 'rerunDone', 'update:modelValue'] },
  // 注意：**不 stub AssetProfileSelect**——本 spec 的目的就是挂真实选择器验证递归契约
}

const ALL_PERMS = ['backtest:view', 'backtest:run', 'backtest:delete', 'screen-profile:view', 'score-profile:view', 'trade-profile:view']

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

function findSelect(wrapper: VueWrapper, testId: string) {
  return wrapper.findAllComponents(AssetProfileSelect).find((c) => c.props('testId') === testId)
}

beforeEach(() => {
  vi.clearAllMocks()
  pageSettingsState.current = null
  localStorage.clear()
  document.body.innerHTML = ''
  vi.mocked(scoreApi.listScoreProfiles).mockResolvedValue([
    { id: 's1', profile_ref: 'avr_score_1', name: '默认趋势分', version: 2, is_preset: false } as any,
  ])
})

describe('BacktestView + 真实 AssetProfileSelect（P1-3 递归契约）', () => {
  it('「加载查看」后真实选择器 modelValue 不被设为临时项、无递归超限，名称经选择器外 chip 展示', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.exists()).toBe(true)
    // 真实组件 onMounted 已 fetchMine 并 emit ready（listScoreProfiles('mine')）
    await flushPromises()
    expect(score.props('modelValue')).toBe('')

    // 模拟抽屉「加载查看」emit loaded（真实组件 onDrawerLoad 设 tempItem + emit loaded，不设选中）
    const pub = { id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true }
    score.vm.$emit('loaded', pub)
    await nextTick()
    await flushPromises()

    // 递归契约：真实选择器的当前选中**不是**临时项（页面方案b 不把临时项设为选择器 modelValue）
    expect(score.props('modelValue')).toBe('')
    // 组件内部 selectedItem 解析不到（modelValue 为空），不会把 el-select 锁到 tempItem
    expect((score.vm as any).selectedItem ?? null).toBeNull()
    // 名称经页面选择器外 chip 渲染（非 opaque ref）
    const chip = wrapper.find('[data-testid="backtest-score-select-temp"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('公开评分')
    // 无递归超限：组件仍正常渲染（若有 Maximum recursive updates，挂载/更新会抛错使断言失败）
    expect(wrapper.find('[data-testid="backtest-score-select"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('临时项→改选真实 mine 项：选择器正常选中、临时 chip 清除、无递归', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    await flushPromises()
    // 加载查看公开项
    score.vm.$emit('loaded', { id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true })
    await flushPromises()
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(true)
    // 用户改选真实 mine 项（经组件 update:modelValue）
    score.vm.$emit('update:modelValue', 'avr_score_1')
    await nextTick()
    await flushPromises()
    // 选择器选中真实 mine 项；组件 selectedItem 解析到 mine 列表项（非临时）
    expect(score.props('modelValue')).toBe('avr_score_1')
    expect((score.vm as any).selectedItem?.name).toBe('默认趋势分')
    // 临时 chip 被清除
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
