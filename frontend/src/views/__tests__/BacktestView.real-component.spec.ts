// @vitest-environment jsdom
// 用真实 AssetProfileSelect 挂载 BacktestView：会话候选保留在下拉中，当前运行快照在选择器外展示。
// 与 stub 选择器的 BacktestView.spec.ts 互补，验证真实 option、mine 选值及运行快照的衔接，
// 不依赖已移除的单项临时缓存字段，也不以缺失字段的空值兜底代替行为断言。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElOption, ElSelect } from 'element-plus'
import { nextTick, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const pageSettingsState = vi.hoisted(() => ({ current: null as any }))

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
  StockChartWorkspace: true,
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

// 驱动真实链路：抽屉 emit load → 组件保留会话候选并 emit loaded → 页面记运行快照。
// 不复读组件 loaded（onDrawerLoad 内部已 emit），直接对抽屉发 load。
async function drawerLoad(select: VueWrapper, item: unknown) {
  innerDrawer(select).vm.$emit('load', item)
  await nextTick()
  await flushPromises()
}

function findOption(select: VueWrapper, value: string) {
  const option = select.findAllComponents(ElOption).find((item) => item.props('value') === value)
  expect(option, `候选 ${value} 应存在于真实选择器中`).toBeDefined()
  return option!
}

// 从底层选择器的输入边界驱动共享组件及父页面，不绕过组件的 onSelect 分发逻辑。
// 同值事件用于验证回调契约；这里不模拟组件库的鼠标或键盘事件生成。
async function selectValue(select: VueWrapper, value: string) {
  select.getComponent(ElSelect).vm.$emit('update:modelValue', value)
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

describe('BacktestView + 真实 AssetProfileSelect（会话候选与运行快照）', () => {
  it('加载公开方案保留未选中候选，名称由外部快照展示，显式清除同步移除候选及运行参数', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    expect(score.exists()).toBe(true)
    // 真实组件 onMounted 已 fetchMine 并 emit ready（listScoreProfiles('mine')）
    await flushPromises()
    expect(score.props('modelValue')).toBe('')

    // 加载后候选保留，但不把公开 ref 写入 mine 选择器的选值。
    const pub = { id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true }
    await drawerLoad(score, pub)

    expect(score.props('loadedMode')).toBe('external')
    expect(score.props('modelValue')).toBe('')
    expect(score.getComponent(ElSelect).props('modelValue')).toBe('')
    const candidate = findOption(score, 'avr_score_pub')
    expect(candidate.text()).toContain('公开评分')
    expect(candidate.attributes('aria-selected')).toBe('false')
    expect(score.findAllComponents(ElOption).map((item) => item.props('value')))
      .toEqual(['avr_score_pub', 'avr_score_1'])
    expect(score.emitted('update:modelValue')).toBeUndefined()
    expect(score.emitted('ready')).toEqual([[[expect.objectContaining({ profile_ref: 'avr_score_1' })]]])
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_pub')
    // 名称经页面选择器外 chip 渲染（非 opaque ref）
    const chip = wrapper.find('[data-testid="backtest-score-select-temp"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('公开评分')
    expect(chip.text()).not.toContain('avr_score_pub')
    expect(wrapper.find('[data-testid="backtest-score-select"]').exists()).toBe(true)
    // 外部快照的清除操作也调用共享组件的按 key 清理入口，不留下可重载的已移除候选。
    await chip.get('button[aria-label="清除临时只读方案"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    expect(score.findAllComponents(ElOption).map((item) => item.props('value'))).toEqual(['avr_score_1'])
    expect((wrapper.vm as any).buildBody()).not.toHaveProperty('score_profile_id')
    wrapper.unmount()
  })

  it('公开快照优先于 mine 选值；收到同值 mine 选择事件清除快照，保留候选供再次加载', async () => {
    const wrapper = await mountView()
    const score = findSelect(wrapper, 'backtest-score-select')!
    await flushPromises()
    await selectValue(score, 'avr_score_1')
    expect(score.props('modelValue')).toBe('avr_score_1')

    // 对公开方案点「加载查看」（完整 onDrawerLoad 链路）
    await drawerLoad(score, { id: 'pub-x', profile_ref: 'avr_score_pub', name: '公开评分', version: 3, source: 'public', readonly: true })
    expect(score.getComponent(ElSelect).props('modelValue')).toBe('avr_score_1')
    expect(findOption(score, 'avr_score_pub').attributes('aria-selected')).toBe('false')
    expect(findOption(score, 'avr_score_1').attributes('aria-selected')).toBe('true')
    expect(score.get('.el-select__selected-item .asset-profile-label').text()).toContain('默认趋势分')
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(true)
    // 快照优先：已有 mine 选择时运行仍用公开快照（三次复审 P1）
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_pub')

    // 同值输入到达共享组件时，页面回调仍须清快照，不能只依赖值变化的 watch。
    await selectValue(score, 'avr_score_1')
    expect(score.props('modelValue')).toBe('avr_score_1')
    expect(score.get('.el-select__selected-item .asset-profile-label').text()).toContain('默认趋势分')
    // 页面 chip 已清、buildBody 恢复用 mine（核心断言：口径与展示都回到 mine）
    expect(wrapper.find('[data-testid="backtest-score-select-temp"]').exists()).toBe(false)
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_1')

    // 切换只释放运行快照，候选仍可再次加载；external 分发不向父级写入公开选值。
    expect(findOption(score, 'avr_score_pub').text()).toContain('公开评分')
    expect(score.emitted('update:modelValue')).toEqual([['avr_score_1'], ['avr_score_1']])
    await selectValue(score, 'avr_score_pub')
    expect(score.emitted('update:modelValue')).toEqual([['avr_score_1'], ['avr_score_1']])
    expect(score.getComponent(ElSelect).props('modelValue')).toBe('avr_score_1')
    expect(wrapper.get('[data-testid="backtest-score-select-temp"]').text()).toContain('公开评分')
    expect((wrapper.vm as any).buildBody().score_profile_id).toBe('avr_score_pub')
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
    // 真实选择器的选中标签必须能解析名称，不能显示 opaque ref。
    expect(score.props('modelValue')).toBe('avr_score_copy')
    const label = score.get('.el-select__selected-item .asset-profile-label').text()
    expect(label).toContain('公开评分 副本')
    expect(label).not.toContain('avr_score_copy')
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
    const label = score.get('.el-select__selected-item .asset-profile-label').text()
    expect(label).toContain('公开评分 副本')
    expect(label).not.toContain('avr_score_copy')
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
    const name = score.get('.el-select__selected-item .asset-profile-label__name').text()
    expect(name).toBe('评分方案 副本')
    expect(name).not.toContain('avr_score_copy')
    expect(name).not.toBe('s-copy')
    wrapper.unmount()
  })
})
