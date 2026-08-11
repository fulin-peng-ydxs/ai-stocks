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
import AssetSearchDrawer from '@/components/asset-search/AssetSearchDrawer.vue'

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

// 找到真实 AssetProfileSelect 内部的 AssetSearchDrawer（组件无 test-id，按其所在选择器子树定位）。
function innerDrawer(select: VueWrapper) {
  return select.findComponent(AssetSearchDrawer)
}

// 驱动真实链路：抽屉 emit load → 组件 onDrawerLoad 设 tempItem + emit loaded → 页面记 tempSelected。
// 不复读组件 loaded（onDrawerLoad 内部已 emit），直接对抽屉发 load。
async function drawerLoad(select: VueWrapper, item: unknown) {
  innerDrawer(select).vm.$emit('load', item)
  await nextTick()
  await flushPromises()
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

describe('BacktestView + 真实 AssetProfileSelect（递归契约 + 完整 onDrawerLoad 链路）', () => {
  it('抽屉 load → 真实 onDrawerLoad 设 tempItem、selectedItem 不锁 temp、无递归，名称经选择器外 chip 展示', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.exists()).toBe(true)
    // 真实组件 onMounted 已 fetchMine 并 emit ready（listScoreProfiles('mine')）
    await flushPromises()
    expect(score.props('modelValue')).toBe('')

    // 完整链路：真实抽屉 load → 组件 onDrawerLoad 设内部 tempItem + emit loaded → 页面记 tempSelected
    const pub = { id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true }
    await drawerLoad(score, pub)

    // 回测使用 external 模式：组件内部不残留临时 option，快照只由页面 chip 承接。
    expect((score.vm as any).tempItem).toBeNull()
    // 递归契约：选择器 modelValue 不被设为临时项；selectedItem 解析不到（modelValue 为空），不锁 tempItem
    expect(score.props('modelValue')).toBe('')
    expect((score.vm as any).selectedItem ?? null).toBeNull()
    // 名称经页面选择器外 chip 渲染（非 opaque ref）
    const chip = wrapper.find('[data-testid="backtest-score-select-temp"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('公开评分')
    expect(chip.text()).not.toContain('avr_score_pub')
    // 无递归超限：组件仍正常渲染（若有 Maximum recursive updates，挂载/更新会抛错使断言失败）
    expect(wrapper.find('[data-testid="backtest-score-select"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('已选 mine → 抽屉 load 公开 → 运行用公开快照；改选真实 mine → chip 清、selectedItem 指向 mine、无递归', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    await flushPromises()
    // 用户先选真实 mine 项
    score.vm.$emit('update:modelValue', 'avr_score_1')
    await nextTick()
    await flushPromises()
    expect(score.props('modelValue')).toBe('avr_score_1')

    // 对公开方案点「加载查看」（完整 onDrawerLoad 链路）
    await drawerLoad(score, { id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true })
    expect((score.vm as any).tempItem).toBeNull()
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(true)
    // 快照优先：已有 mine 选择时运行仍用公开快照（三次复审 P1）
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_pub')

    // 用户重选同一真实 mine 项：页面 @update:model-value 无条件清 tempSelected（值不变 watch 不触发的边界）。
    score.vm.$emit('update:modelValue', 'avr_score_1')
    await nextTick()
    await flushPromises()
    expect(score.props('modelValue')).toBe('avr_score_1')
    // 组件 tempItem 自管：重选同值时组件 watch 不触发、tempItem 残留——但运行取页面 tempSelected 快照，
    // 组件残留不影响口径、也不破递归（selectedItem 仍解析到持久 mine 项，非 tempItem）。
    expect((score.vm as any).selectedItem?.name).toBe('默认趋势分')
    // 页面 chip 已清、buildBody 恢复用 mine（核心断言：口径与展示都回到 mine）
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_1')
    wrapper.unmount()
  })

  it('复制成功但 mine 刷新失败：不写无法解析的裸 ref，用复制响应构造临时 summary 显示名称（P1-3）', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    await flushPromises()
    // 让后续 fetchMine（复制后的 reload）失败——真实组件 reload 保留旧列表并返回 null
    vi.mocked(scoreApi.listScoreProfiles).mockRejectedValueOnce(new Error('网络瞬时失败'))
    // 抽屉 emit copied → 组件 onDrawerCopied：reload 失败 → 用复制响应构造临时 mine summary 置顶
    innerDrawer(score).vm.$emit('copied', { id: 's-copy', profile_ref: 'avr_score_copy', name: '公开评分 副本', version: 1 })
    await nextTick()
    await flushPromises()
    // 选中项有 summary 可解析：selectedItem 显示名称（非 opaque ref），不写无法解析的裸 ref
    expect(score.props('modelValue')).toBe('avr_score_copy')
    expect((score.vm as any).selectedItem?.name).toBe('公开评分 副本')
    expect((score.vm as any).selectedItem?.name).not.toContain('avr_score_copy')
    wrapper.unmount()
  })

  it('复制刷新成功但新记录暂未出现在列表：同样构造可解析 summary（P2-2 统一兜底）', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    await flushPromises()
    // reload 成功但返回列表不含新复制项（后端延迟可见）——仍须兜底，不写裸 ref
    vi.mocked(scoreApi.listScoreProfiles).mockResolvedValueOnce([
      { id: 's1', profile_ref: 'avr_score_1', name: '默认趋势分', version: 2, is_preset: false } as any,
    ])
    innerDrawer(score).vm.$emit('copied', { id: 's-copy', profile_ref: 'avr_score_copy', name: '公开评分 副本', version: 1 })
    await nextTick()
    await flushPromises()
    expect(score.props('modelValue')).toBe('avr_score_copy')
    expect((score.vm as any).selectedItem?.name).toBe('公开评分 副本')
    expect((score.vm as any).selectedItem?.name).not.toContain('avr_score_copy')
    wrapper.unmount()
  })

  it('复制响应 name 为空串时兜底中文名而非 opaque ref（P2-2 防退化）', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    await flushPromises()
    vi.mocked(scoreApi.listScoreProfiles).mockRejectedValueOnce(new Error('网络瞬时失败'))
    // name 为空串（异常后端）→ 组件用「评分方案 副本」中文兜底名，不退化成 profile_ref/id
    innerDrawer(score).vm.$emit('copied', { id: 's-copy', profile_ref: 'avr_score_copy', name: '', version: 1 })
    await nextTick()
    await flushPromises()
    const name = (score.vm as any).selectedItem?.name
    expect(name).toBe('评分方案 副本')
    expect(name).not.toContain('avr_score_copy')
    expect(name).not.toBe('s-copy')
    wrapper.unmount()
  })
})
