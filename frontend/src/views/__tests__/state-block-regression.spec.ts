// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { computed, reactive, ref, type Component } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'

vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {},
    knobs: [],
    setKnob: vi.fn(),
    valueOf: vi.fn(),
    sourceOf: vi.fn(),
    isDirty: ref(false),
    resetAll: vi.fn(),
    componentValueOf: vi.fn((_slot: string, field: string) => {
      if (field === 'hiddenColumns') return []
      if (field === 'pageSize') return 50
      if (field === 'border') return false
      return ''
    }),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
    remoteHydrated: ref(true),
    whenRemoteHydrated: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: (_key: string, defaults: Record<string, unknown>) => ({
    settings: reactive(structuredClone(defaults)),
    isDirty: ref(false),
    reset: vi.fn(),
    hydrated: ref(true),
    whenHydrated: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/composables/useTradeDates', () => ({
  useTradeDates: () => ({
    dataMin: ref('2024-01-01'),
    dataMax: ref('2024-12-31'),
    ensureLoaded: vi.fn().mockResolvedValue(undefined),
    prevTradeDate: vi.fn((value: string) => value),
  }),
}))

vi.mock('@/composables/useKlinePrefs', () => ({
  useKlinePrefs: () => {
    const prefs = reactive({ defaultPeriod: 120 })
    return { validDefault: computed(() => prefs.defaultPeriod), prefs }
  },
}))

vi.mock('@/utils/csv', () => ({ downloadCsv: vi.fn() }))

vi.mock('@/api/scoreProfile', () => ({
  getIndicatorRegistry: vi.fn(),
  listScoreProfiles: vi.fn(),
}))
vi.mock('@/api/board', () => ({
  listBoardProfiles: vi.fn(),
  runBoardProfile: vi.fn(),
  computeBoard: vi.fn(),
}))
vi.mock('@/api/data', () => ({
  getDataStatus: vi.fn(),
  getUpdateLogs: vi.fn(),
  listTasks: vi.fn(),
  getOverview: vi.fn(),
  getCatalog: vi.fn(),
  getDimensions: vi.fn(),
  getStockQuality: vi.fn(),
  getDataQuality: vi.fn(),
  fixQualityIssue: vi.fn(),
  ignoreQualityIssue: vi.fn(),
  resetQualityIssue: vi.fn(),
  recoverQualityBatch: vi.fn(),
  markDelisted: vi.fn(),
  createTask: vi.fn(),
  getTask: vi.fn(),
  getTaskLogs: vi.fn(),
  resumeTask: vi.fn(),
  cancelTask: vi.fn(),
  TASK_LABEL: { update: '每日更新' },
  STATUS_LABEL: { running: '运行中', done: '已完成' },
  LAYER_DESC: {},
  ISSUE_TYPE_LABEL: { data_gap: '缺口' },
  SEVERITY_LABEL: { high: '高' },
  ISSUE_STATUS_LABEL: { open: '未处理', fixing: '修复中' },
  ISSUE_LAYER: { data_gap: 'L4' },
  LAYER_LABEL: { L4: '覆盖鲜活' },
  RECOVER_ACTION_LABEL: { data_gap: '恢复' },
}))
vi.mock('@/api/screening', () => ({
  copyProfile: vi.fn(),
  deleteProfile: vi.fn(),
  getProfile: vi.fn(),
  getProfileVersions: vi.fn(),
  listProfiles: vi.fn(),
  browseProfiles: vi.fn(),
  runScreen: vi.fn(),
  saveProfile: vi.fn(),
  setProfileVisibility: vi.fn(),
}))
vi.mock('@/api/backtest', () => ({
  runBacktest: vi.fn(),
  prepareBacktest: vi.fn(),
  listRuns: vi.fn(),
  getRun: vi.fn(),
  deleteRun: vi.fn(),
  runRobust: vi.fn(),
  setRunVisibility: vi.fn(),
}))
vi.mock('@/api/tradeProfile', () => ({ listTradeProfiles: vi.fn() }))
vi.mock('@/api/stocks', () => ({ getBars: vi.fn() }))
vi.mock('@/api/training', () => ({
  startSession: vi.fn(),
  getSession: vi.fn(),
  listSessions: vi.fn(),
  growth: vi.fn(),
  revealNext: vi.fn(),
  placeTrade: vi.fn(),
  cancelIntent: vi.fn(),
  settleRound: vi.fn(),
  saveReview: vi.fn(),
  deleteSession: vi.fn(),
}))

import * as scoreApi from '@/api/scoreProfile'
import * as boardApi from '@/api/board'
import * as dataApi from '@/api/data'
import * as screeningApi from '@/api/screening'
import * as backtestApi from '@/api/backtest'
import * as tradeApi from '@/api/tradeProfile'
import * as trainingApi from '@/api/training'
import BoardView from '@/views/BoardView.vue'
import OverviewView from '@/views/data/OverviewView.vue'
import IngestView from '@/views/data/IngestView.vue'
import QualityView from '@/views/data/QualityView.vue'
import ScreenView from '@/views/ScreenView.vue'
import BacktestView from '@/views/BacktestView.vue'
import TrainingView from '@/views/TrainingView.vue'
import AssetProfileSelect from '@/components/asset-search/AssetProfileSelect.vue'
import AssetSearchDrawer from '@/components/asset-search/AssetSearchDrawer.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/stocks/:code', component: { template: '<div />' } },
  ],
})

const stubs = {
  ElSelect: {
    props: ['modelValue', 'multiple'],
    emits: ['update:modelValue', 'change'],
    template: `
      <select
        :multiple="multiple"
        :value="modelValue"
        @change="$emit('update:modelValue', $event.target.value); $emit('change', $event.target.value)"
      >
        <slot />
      </select>
    `,
  },
  ElOption: {
    props: ['label', 'value'],
    template: '<option :value="value">{{ label || value }}<slot /></option>',
  },
  ElTable: {
    template: '<table><tbody><slot /></tbody><slot name="empty" /></table>',
  },
  ElTableColumn: true,
  LayoutHost: {
    template: `
      <div>
        <slot name="action"/>
        <slot name="summary"/>
        <slot name="quality"/>
        <slot name="filters"/>
        <slot name="workspace"/>
        <slot name="main"/>
        <slot name="footer"/>
        <slot name="overlays"/>
      </div>
    `,
  },
  AppDataTable: {
    props: ['loading', 'data'],
    emits: ['row-click'],
    template: `
      <div class="app-data-table" :data-loading="String(Boolean(loading))">
        <button
          v-if="data?.length"
          class="first-data-row"
          @click="$emit('row-click', data[0])"
        >
          打开首行
        </button>
        <slot/><slot name="empty"/>
      </div>
    `,
  },
  AppControlRow: { template: '<div><slot/></div>' },
  AppControlItem: { template: '<label><slot name="label"/><slot/></label>' },
  TradeDatePicker: { template: '<input />' },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  PageSettingSection: { template: '<section><slot/></section>' },
  PageSegmented: true,
  PageToggleRow: true,
  HelpTip: { template: '<span><slot/></span>' },
  AssetProfileLabel: { template: '<span>{{ name }}</span>', props: ['name'] },
  AssetVisibilityActions: true,
  AssetVisibilityTag: true,
  CandleChart: true,
  EquityChart: true,
  GrowthChart: true,
  KlineRangeSelect: true,
  KlineSettingSection: true,
  teleport: true,
}

async function mountView(component: Component) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'system'
  auth.permissions = ['screen:run', 'screen-profile:view', 'backtest:run', 'training:start']
  auth.menusStatus = 'ready'
  await router.push('/')
  await router.isReady()
  const wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [pinia, router, ElementPlus],
      stubs,
      directives: { permission: {} },
    },
  })
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [
      { key: 'bull_arrange', name_cn: '多头排列', dtype: 'bool', enabled: true, params: [] },
      { key: 'rs_pct', name_cn: '相对强度', dtype: 'number', enabled: true, params: [] },
    ],
  })
  ;(scoreApi.listScoreProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: 'score1', name: '评分方案', version: 1, source: 'mine' },
  ])
  ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: 'board1', name: '榜单方案', version: 1, source: 'preset' },
  ])
  ;(dataApi.getCatalog as ReturnType<typeof vi.fn>).mockResolvedValue({ tables: [] })
  ;(dataApi.getDimensions as ReturnType<typeof vi.fn>).mockResolvedValue({ dimensions: [] })
  ;(dataApi.getStockQuality as ReturnType<typeof vi.fn>).mockResolvedValue({ list: [], total: 0 })
  ;(dataApi.getDataStatus as ReturnType<typeof vi.fn>).mockResolvedValue({})
  ;(dataApi.getUpdateLogs as ReturnType<typeof vi.fn>).mockResolvedValue({ list: [], total: 0, tables: [] })
  ;(dataApi.listTasks as ReturnType<typeof vi.fn>).mockResolvedValue({ tasks: [], total: 0 })
  ;(screeningApi.listProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
  ;(backtestApi.prepareBacktest as ReturnType<typeof vi.fn>).mockResolvedValue({ duplicate: null })
  ;(backtestApi.listRuns as ReturnType<typeof vi.fn>).mockResolvedValue({ runs: [] })
  ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: 'trade1', name: '买卖方案', version: 1, source: 'mine' },
  ])
  ;(trainingApi.growth as ReturnType<typeof vi.fn>).mockResolvedValue([])
})

describe('代表性页面四态回归', () => {
  it('从每日榜单进入详情时同步榜单集合和返回地址', async () => {
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2026-07-25',
      top: 2,
      count: 2,
      list: [
        {
          rank: 1,
          code: '000001.SZ',
          name: '平安银行',
          total_score: 90,
          grade: '龙头候选',
          sub_scores: {},
        },
        {
          rank: 2,
          code: '600000.SH',
          name: '浦发银行',
          total_score: 80,
          grade: '观察',
          sub_scores: {},
        },
      ],
    })
    const push = vi.spyOn(router, 'push')
    const wrapper = await mountView(BoardView)

    expect(boardApi.runBoardProfile).toHaveBeenCalledWith(expect.objectContaining({
      profile_id: 'board1',
      run_date: '2024-12-31',
    }))
    expect(boardApi.runBoardProfile).toHaveBeenCalledTimes(1)

    await wrapper.get('.first-data-row').trigger('click')

    const stockSet = useStockSet()
    expect(stockSet.label).toBe('每日榜单')
    expect(stockSet.codes).toEqual(['000001.SZ', '600000.SH'])
    expect(stockSet.returnPath).toBe('/board')
    expect(push).toHaveBeenCalledWith('/stocks/000001.SZ')
    push.mockRestore()
  })

  it('榜单加载查看公开评分方案后直接选中并自动刷新', async () => {
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2024-12-31',
      top: 50,
      count: 0,
      list: [],
    })
    const wrapper = await mountView(BoardView)
    const select = wrapper.findComponent(AssetProfileSelect)
    expect(select.props('selectLoaded')).toBe(true)

    const publicProfile = {
      id: 'public-score',
      profile_ref: 'ref_public_score',
      name: '公开评分方案',
      version: 2,
      source: 'public',
      visibility: 'public',
      readonly: true,
      is_preset: false,
    }
    select.findComponent(AssetSearchDrawer).vm.$emit('load', publicProfile)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(select.props('modelValue')).toBe('ref_public_score')
    expect(boardApi.runBoardProfile).toHaveBeenLastCalledWith(expect.objectContaining({
      profile_ref: 'ref_public_score',
      run_date: '2024-12-31',
    }))
  })

  it('榜单加载失败显示错误态且不显示表格空态', async () => {
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('board failed'))
    const wrapper = await mountView(BoardView)
    expect(wrapper.text()).toContain('榜单加载失败')
    expect(wrapper.text()).toContain('board failed')
  })

  it('榜单方案列表加载失败结束首屏等待，重试成功后自动加载榜单', async () => {
    ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('profiles failed'))
      .mockResolvedValueOnce([{ id: 'board1', name: '榜单方案', version: 1, source: 'mine' }])
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2024-12-31', top: 50, count: 0, list: [],
    })

    const wrapper = await mountView(BoardView)
    expect(wrapper.text()).toContain('榜单加载失败')
    expect(wrapper.text()).toContain('profiles failed')

    await wrapper.findComponent(AssetProfileSelect).vm.reload()
    await flushPromises()
    expect(boardApi.runBoardProfile).toHaveBeenCalledWith(expect.objectContaining({ profile_id: 'board1' }))
    expect(wrapper.text()).not.toContain('profiles failed')
  })

  it('清空榜单方案会使在途请求失效，迟到响应不得重新写回结果', async () => {
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2024-12-31', top: 50, count: 0, list: [],
    })
    const wrapper = await mountView(BoardView)
    let resolveLate!: (value: unknown) => void
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((resolve) => { resolveLate = resolve }),
    )

    ;(wrapper.vm as unknown as { onProfileSelect: (key: string) => void }).onProfileSelect('board1')
    ;(wrapper.vm as unknown as { onProfileSelect: (key: string) => void }).onProfileSelect('')
    resolveLate({
      run_date: '2024-12-31', top: 50, count: 1,
      list: [{ rank: 1, code: '000001.SZ', name: '平安银行', total_score: 90, grade: '观察', sub_scores: {} }],
    })
    await flushPromises()

    expect((wrapper.vm as unknown as { profileRef: string }).profileRef).toBe('')
    expect((wrapper.vm as unknown as { rows: unknown[] }).rows).toEqual([])
  })

  it('数据概览加载失败显示错误态', async () => {
    ;(dataApi.getOverview as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('overview failed'))
    const wrapper = await mountView(OverviewView)
    expect(wrapper.text()).toContain('数据概览加载失败')
    expect(wrapper.text()).toContain('overview failed')
  })

  it('数据概览的逐股质量失败只落在局部错误态', async () => {
    ;(dataApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      latest_trade_date: '2026-07-16',
      codes: { active: 1, delisted: 0 },
      bar_rows: 1,
      quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
      gaps: { stocks_with_gap: 0, gap_days_total: 0 },
      last_scan_at: null,
    })
    ;(dataApi.getStockQuality as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('stock quality failed'))
    const wrapper = await mountView(OverviewView)
    const stockTab = wrapper.findAll('[role="tab"]')
      .find((tab) => tab.text().includes('逐股分层体检'))
    expect(stockTab).toBeTruthy()
    await stockTab!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('逐股质量加载失败')
    expect(wrapper.text()).toContain('stock quality failed')
    expect(wrapper.text()).not.toContain('数据概览加载失败')
  })

  it('数据质量加载失败显示错误态', async () => {
    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('quality failed'))
    const wrapper = await mountView(QualityView)
    expect(wrapper.text()).toContain('数据质量加载失败')
    expect(wrapper.text()).toContain('quality failed')
  })

  it('任务中心自动轮询静默刷新，不重复显示表格加载态', async () => {
    vi.useFakeTimers()
    let resolvePolling!: (value: unknown) => void
    const activeResult = {
      tasks: [{
        id: 'task-1',
        task_type: 'update',
        status: 'running',
        progress: 0.5,
        message: '执行中',
        params: {},
        created_at: '2026-07-20 10:00:00',
        updated_at: '2026-07-20 10:01:00',
      }],
      total: 1,
    }
    ;(dataApi.listTasks as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(activeResult)
      .mockImplementationOnce(() => new Promise((resolve) => { resolvePolling = resolve }))

    const wrapper = await mountView(IngestView)
    const taskTables = wrapper.findAll('.app-data-table')
    expect(taskTables[0].attributes('data-loading')).toBe('false')

    await vi.advanceTimersByTimeAsync(2_000)
    expect(dataApi.listTasks).toHaveBeenCalledTimes(2)
    expect(taskTables[0].attributes('data-loading')).toBe('false')

    resolvePolling(activeResult)
    await flushPromises()
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('任务中心按失败和中断状态使用不同恢复动作', async () => {
    const wrapper = await mountView(IngestView)
    const failedActions = (wrapper.vm as any).taskRowActions({
      id: 'failed-1', task_type: 'board', status: 'failed', params: {},
      capability: { can_resume: true, checkpoint: { phase: 'members' } },
    })
    const interruptedActions = (wrapper.vm as any).taskRowActions({
      id: 'interrupted-1', task_type: 'board', status: 'interrupted', params: {},
      capability: { can_resume: true },
    })

    expect(failedActions.find((action: any) => action.key === 'resume')?.label).toBe('重试未完成项')
    expect(interruptedActions.find((action: any) => action.key === 'resume')?.label).toBe('继续任务')
    wrapper.unmount()
  })

  it('筛选结果区初始显示引导空态', async () => {
    const wrapper = await mountView(ScreenView)
    expect(wrapper.text()).toContain('运行后在这里展示筛选结果')
    wrapper.unmount()
  })

  it('筛选运行失败落到结果区错误态', async () => {
    ;(screeningApi.runScreen as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('screen failed'))
    const wrapper = await mountView(ScreenView)
    const run = wrapper.findAll('button').find((button) => button.text().includes('运行筛选'))
    expect(run).toBeTruthy()
    await run!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('筛选运行失败')
    expect(wrapper.text()).toContain('screen failed')
  })

  it('筛选空结果再次运行时显示加载态', async () => {
    let resolveRerun: ((value: unknown) => void) | undefined
    ;(screeningApi.runScreen as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({
        run_date: '2026-08-01', count: 0, exclude_st: true, hits: [],
      })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRerun = resolve }))
    const wrapper = await mountView(ScreenView)
    const run = wrapper.findAll('button').find((button) => button.text().includes('运行筛选'))

    await run!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('当前条件暂无命中')

    await run!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('正在运行筛选')
    expect(wrapper.text()).not.toContain('当前条件暂无命中')

    resolveRerun?.({ run_date: '2026-08-01', count: 0, exclude_st: true, hits: [] })
    await flushPromises()
    wrapper.unmount()
  })

  it('筛选初始化失败显示配置错误态而不是空构建器', async () => {
    ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('registry failed'))
    const wrapper = await mountView(ScreenView)
    expect(wrapper.text()).toContain('筛选配置加载失败')
    expect(wrapper.text()).toContain('registry failed')
  })

  // 「加载查看」（R5/§7.0）：组件 emit loaded 后页面经 onScreenSelect 载入该公开方案详情进编辑器
  // 做只读展示（list 形态临时项高亮为选中态，与评分页同口径）。
  it('筛选页加载查看公开方案：按 profile_ref 页面级载入只读详情', async () => {
    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'pub1',
      profile_ref: 'ref_pub1',
      name: '公开筛选方案',
      version: 3,
      is_preset: false,
      visibility: 'public',
      readonly: true,
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    const wrapper = await mountView(ScreenView)
    const selector = wrapper.findComponent(AssetProfileSelect)
    expect(selector.exists()).toBe(true)
    selector.vm.$emit('loaded', {
      id: 'pub1',
      profile_ref: 'ref_pub1',
      name: '公开筛选方案',
      version: 3,
      source: 'public',
      readonly: true,
    })
    await flushPromises()
    // 直接调 getProfile(profile_ref) 页面级载入
    expect(screeningApi.getProfile).toHaveBeenCalledWith('ref_pub1')
    // 载入后 loadedProfile 只读 → 运行按 profile_ref 而非脏表达式
    const run = wrapper.findAll('button').find((button) => button.text().includes('运行筛选'))
    await run!.trigger('click')
    await flushPromises()
    expect(screeningApi.runScreen).toHaveBeenCalledWith(
      expect.objectContaining({ profile_id: 'ref_pub1' }),
    )
    expect(screeningApi.runScreen).not.toHaveBeenCalledWith(
      expect.objectContaining({ expression: expect.anything() }),
    )
  })

  it('筛选页只读公开态运行按所查看方案 profile_ref，不用当前脏表达式', async () => {
    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'pub2',
      profile_ref: 'ref_pub2',
      name: '另一公开方案',
      version: 1,
      is_preset: false,
      visibility: 'tenant',
      readonly: true,
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    const wrapper = await mountView(ScreenView)
    wrapper.findComponent(AssetProfileSelect).vm.$emit('loaded', {
      id: 'pub2',
      profile_ref: 'ref_pub2',
      name: '另一公开方案',
      version: 1,
      source: 'tenant',
      readonly: true,
    })
    await flushPromises()
    const run = wrapper.findAll('button').find((button) => button.text().includes('运行筛选'))
    await run!.trigger('click')
    await flushPromises()
    expect(screeningApi.runScreen).toHaveBeenCalledWith(
      expect.objectContaining({ profile_id: 'ref_pub2' }),
    )
  })

  it('筛选页移除本人名下系统内置预览后同步清空条件与结果，列表刷新失败也不残留参数', async () => {
    ;(screeningApi.listProfiles as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('刷新失败'))
    const summary = {
      id: 'pub-remove', profile_ref: 'ref_pub_remove', name: '待移除筛选方案', version: 1,
      is_preset: true, source: 'preset', readonly: false,
    }
    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...summary,
      is_preset: true, visibility: 'public',
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    const wrapper = await mountView(ScreenView)
    const selector = wrapper.findComponent(AssetProfileSelect)
    selector.vm.$emit('loaded', summary)
    await flushPromises()
    expect((wrapper.vm as any).rows).toHaveLength(1)

    selector.vm.$emit('tempRemoved', summary)
    await flushPromises()
    expect((wrapper.vm as any).curRef).toBe('')
    expect((wrapper.vm as any).loadedProfile).toBeNull()
    expect((wrapper.vm as any).rows).toEqual([])
    expect((wrapper.vm as any).complexAst).toBeNull()
    expect((wrapper.vm as any).result).toBeNull()
  })

  it('筛选方案切换成功后清除上一方案结果，详情失败则不提前清除', async () => {
    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'a', profile_ref: 'ref_a', name: '方案A', version: 1, is_preset: false,
      visibility: 'private', readonly: false,
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    ;(screeningApi.runScreen as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2026-08-01', count: 1, exclude_st: true,
      hits: [{ code: '000001.SZ', name: '旧结果股票', total_score: 90, grade: '观察', is_st: false }],
    })
    const wrapper = await mountView(ScreenView)
    const selector = wrapper.findComponent(AssetProfileSelect)
    selector.vm.$emit('loaded', { id: 'a', profile_ref: 'ref_a', name: '方案A', version: 1, readonly: false })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('运行筛选'))!.trigger('click')
    await flushPromises()
    expect((wrapper.vm as any).result?.hits).toHaveLength(1)

    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('切换失败'))
    selector.vm.$emit('loaded', { id: 'b', profile_ref: 'ref_b', name: '方案B', version: 1, readonly: true })
    await flushPromises()
    expect((wrapper.vm as any).result?.hits).toHaveLength(1)

    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'b', profile_ref: 'ref_b', name: '方案B', version: 1, is_preset: false,
      visibility: 'public', readonly: true,
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    selector.vm.$emit('loaded', { id: 'b', profile_ref: 'ref_b', name: '方案B', version: 1, readonly: true })
    await flushPromises()
    expect((wrapper.vm as any).result).toBeNull()
  })

  it('筛选页载入自己的可写方案显示删除按钮', async () => {
    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'mine1',
      name: '我的筛选方案',
      version: 2,
      is_preset: false,
      visibility: 'private',
      readonly: false,
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    const wrapper = await mountView(ScreenView)
    wrapper.findComponent(AssetProfileSelect).vm.$emit('loaded', {
      id: 'mine1',
      name: '我的筛选方案',
      version: 2,
      source: 'mine',
      readonly: false,
    })
    await flushPromises()
    // 限定编辑器头作用域：页面另有条件行的行内删除按钮，不能按全页文本匹配
    const edHead = wrapper.find('.ed-head')
    expect(edHead.findAll('button').find((b) => b.text().trim() === '删除')).toBeTruthy()
  })

  it('筛选页载入只读公开方案不显示删除按钮', async () => {
    ;(screeningApi.getProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'pub1',
      profile_ref: 'ref_pub1',
      name: '公开筛选方案',
      version: 3,
      is_preset: false,
      visibility: 'public',
      readonly: true,
      expression: { op: 'AND', children: [{ type: 'col', field: 'bull_arrange', cmp: '==', value: true }] },
    })
    const wrapper = await mountView(ScreenView)
    wrapper.findComponent(AssetProfileSelect).vm.$emit('loaded', {
      id: 'pub1',
      profile_ref: 'ref_pub1',
      name: '公开筛选方案',
      version: 3,
      source: 'public',
      readonly: true,
    })
    await flushPromises()
    // 只读公开态：编辑器头不应出现删除按钮（条件行的行内删除按钮属另一作用域，不参与断言）
    const edHead = wrapper.find('.ed-head')
    expect(edHead.findAll('button').find((b) => b.text().trim() === '删除')).toBeFalsy()
  })

  it('回测运行失败落到结果区错误态', async () => {
    localStorage.setItem('ai-stocks-backtest-params', JSON.stringify({
      kind: 'strategy',
      dateStart: '2024-01-01',
      dateEnd: '2024-12-31',
      scoreProfileId: 'score1',
      tradeProfileId: 'trade1',
    }))
    ;(backtestApi.runBacktest as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('backtest failed'))
    const wrapper = await mountView(BacktestView)
    const run = wrapper.findAll('button').find((button) => button.text().includes('运行回测'))
    expect(run).toBeTruthy()
    await run!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('回测运行失败')
    expect(wrapper.text()).toContain('backtest failed')
  })

  it('回测方案局部加载失败保留表单并提供页内重试态', async () => {
    ;(scoreApi.listScoreProfiles as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('score profiles failed'))
    const wrapper = await mountView(BacktestView)
    // T5：方案加载错误由 AssetProfileSelect 组件内联承接（AppStateBlock + 重试），不再有页面聚合错误块；
    // 局部失败不阻塞表单，运行入口仍可用。
    expect(wrapper.text()).toContain('评分方案加载失败')
    expect(wrapper.text()).toContain('score profiles failed')
    expect(wrapper.text()).toContain('运行回测')
  })

  it('训练历史加载失败显示错误态', async () => {
    ;(trainingApi.listSessions as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('history failed'))
    const wrapper = await mountView(TrainingView)
    expect(wrapper.text()).toContain('训练历史加载失败')
    expect(wrapper.text()).toContain('history failed')
  })
})
