// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessage, ElTooltip } from 'element-plus'
import { computed, reactive, ref, type Component } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useStockSet } from '@/stores/stockSet'

const layoutMockState = vi.hoisted(() => ({
  hiddenColumnsBySlot: {} as Record<string, string[]>,
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
    componentValueOf: vi.fn((slot: string, field: string) => {
      if (field === 'hiddenColumns') return layoutMockState.hiddenColumnsBySlot[slot] ?? []
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
  ALL_DAYS: 99999,
  useKlinePrefs: () => {
    const prefs = reactive({ defaultPeriod: 120 })
    return { validDefault: computed(() => prefs.defaultPeriod), prefs }
  },
}))

vi.mock('@/utils/csv', () => ({ downloadCsv: vi.fn() }))

vi.mock('@/api/scoreProfile', () => ({
  getIndicatorRegistry: vi.fn(),
  listScoreProfiles: vi.fn(),
  browseScoreProfiles: vi.fn(),
  copyScoreProfile: vi.fn(),
}))
vi.mock('@/api/userPreferences', () => ({
  listUserPreferences: vi.fn().mockResolvedValue({ items: [] }),
  putUserPreference: vi.fn().mockResolvedValue(undefined),
  deleteUserPreference: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/api/stockGroup', () => ({
  listGroups: vi.fn().mockResolvedValue([]),
  addMembers: vi.fn(),
  createGroup: vi.fn(),
  removeMembers: vi.fn(),
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
  restoreQualityMonitoring: vi.fn(),
  resetQualityIssue: vi.fn(),
  recoverQualityBatch: vi.fn(),
  ignoreQualityBatch: vi.fn(),
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
  BOARD_ISSUE_ITEMS: [],
}))
vi.mock('@/api/screening', () => ({
  copyProfile: vi.fn(),
  deleteProfile: vi.fn(),
  getProfile: vi.fn(),
  getProfileVersions: vi.fn(),
  listProfiles: vi.fn(),
  browseProfiles: vi.fn(),
  runScreen: vi.fn(),
  rankScreen: vi.fn(),
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
import * as csvUtils from '@/utils/csv'
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
  StockChartWorkspace: true,
  EquityChart: true,
  GrowthChart: true,
  KlineRangeSelect: true,
  KlineSettingSection: true,
  StockAnalysisPanel: true,
  teleport: true,
}

async function mountView(
  component: Component,
  authOptions: { role?: string; permissions?: string[] } = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = authOptions.role ?? 'system'
  auth.permissions = authOptions.permissions
    ?? ['screen:run', 'screen-profile:view', 'backtest:run', 'training:start']
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
  layoutMockState.hiddenColumnsBySlot = {}
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
  ;(dataApi.getCatalog as ReturnType<typeof vi.fn>).mockResolvedValue({ summary: {}, tables: [] })
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
  it('榜单与筛选使用相同的评分方案选择器宽度档位', async () => {
    const board = await mountView(BoardView)
    const screen = await mountView(ScreenView)
    const boardSelector = board.findAllComponents(AssetProfileSelect)
      .find((item) => item.props('testId') === 'board-profile-select')!
    const screenSelector = screen.findAllComponents(AssetProfileSelect)
      .find((item) => item.props('testId') === 'screen-score-profile-select')!

    expect(boardSelector.classes()).toContain('app-control-width-wide')
    expect(screenSelector.classes()).toContain('app-control-width-wide')
    board.unmount()
    screen.unmount()
  })

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

    expect(wrapper.find('[data-testid="board-recompute-current"]').exists()).toBe(true)
    expect(boardApi.runBoardProfile).toHaveBeenCalledWith(expect.objectContaining({
      profile_id: 'board1',
      run_date: '2024-12-31',
    }))
    expect(boardApi.runBoardProfile).toHaveBeenCalledTimes(1)

    // 分析区展开时行点击只切换走势，不改变路由。
    await wrapper.get('.first-data-row').trigger('click')
    expect(push).not.toHaveBeenCalledWith('/stocks/000001.SZ')

    // 收起后行点击仍只切换分析；完整详情必须走分析区的次级入口。
    await wrapper.get('[data-testid="market-hide-analysis"]').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.get('.first-data-row').trigger('click')
    expect(push).not.toHaveBeenCalledWith('/stocks/000001.SZ')
    ;(wrapper.vm as unknown as { openActiveAnalysisDetail: () => void }).openActiveAnalysisDetail()
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

  it('本人评分方案可按所选日期重算当日榜单', async () => {
    ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'board1', name: '我的榜单方案', version: 1,
        source: 'mine', visibility: 'private', readonly: false,
      },
    ])
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2024-12-31', top: 50, count: 0, list: [],
    })

    const wrapper = await mountView(BoardView, {
      role: 'normal',
      permissions: ['board:view', 'board:compute'],
    })
    const recompute = wrapper.get('[data-testid="board-recompute-current"]')
    await recompute.trigger('click')
    await flushPromises()

    expect(boardApi.runBoardProfile).toHaveBeenCalledTimes(2)
    expect(boardApi.runBoardProfile).toHaveBeenLastCalledWith(expect.objectContaining({
      profile_id: 'board1',
      run_date: '2024-12-31',
      force: true,
    }))
  })

  it('他人公开评分方案和无计算权限的本人方案都不显示重算入口', async () => {
    ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'public-score', profile_ref: 'ref_public_score', name: '公开评分方案', version: 2,
        source: 'public', visibility: 'public', readonly: true,
      },
    ])
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2024-12-31', top: 50, count: 0, list: [],
    })

    const publicWrapper = await mountView(BoardView, {
      role: 'normal',
      permissions: ['board:view', 'board:compute'],
    })
    expect(publicWrapper.find('[data-testid="board-recompute-current"]').exists()).toBe(false)
    publicWrapper.unmount()

    ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'board1', name: '我的榜单方案', version: 1,
        source: 'mine', visibility: 'private', readonly: false,
      },
    ])
    const noPermissionWrapper = await mountView(BoardView, {
      role: 'normal',
      permissions: ['board:view'],
    })
    expect(noPermissionWrapper.find('[data-testid="board-recompute-current"]').exists()).toBe(false)
  })

  it('榜单加载失败显示错误态且不显示表格空态', async () => {
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('board failed'))
    const wrapper = await mountView(BoardView)
    expect(wrapper.text()).toContain('榜单加载失败')
    expect(wrapper.text()).toContain('board failed')
  })

  it('ST 批次未发布时榜单显示明确错误态而不是空榜', async () => {
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2024-12-31',
      top: 50,
      count: 0,
      business_code: 'ST_STATUS_NOT_READY',
      st_status_error: 'ST 点时事实批次状态为 refreshing',
      list: [],
    })
    const wrapper = await mountView(BoardView)
    expect(wrapper.text()).toContain('榜单加载失败')
    expect(wrapper.text()).toContain('ST 点时事实批次状态为 refreshing')
    expect(wrapper.text()).not.toContain('当前条件暂无榜单数据')
  })

  it('默认榜单遇服务瞬时故障时保留默认偏好', async () => {
    localStorage.setItem('ai-stocks-board-default-profile', JSON.stringify({
      profile_ref: 'ref_default_score',
      id: 'default-score',
      name: '默认评分方案',
      version: 3,
      is_preset: false,
      source: 'public',
      owner_label: '其他用户',
      readonly: true,
    }))
    ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: { msg: '服务暂时不可用，请稍后重试' } },
    })

    const wrapper = await mountView(BoardView)

    expect(boardApi.runBoardProfile).toHaveBeenCalledWith(expect.objectContaining({
      profile_ref: 'ref_default_score',
    }))
    expect((wrapper.vm as unknown as { profileRef: string }).profileRef).toBe('ref_default_score')
    expect(wrapper.text()).toContain('服务暂时不可用，请稍后重试')
    expect(JSON.parse(localStorage.getItem('ai-stocks-default-score-profile') || '{}'))
      .toMatchObject({ profile_ref: 'ref_default_score', id: 'default-score' })

    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      apiCode: 404,
      uiMessage: '方案不存在',
    })
    ;(wrapper.vm as unknown as { load: () => Promise<void> }).load()
    await flushPromises()

    expect((wrapper.vm as unknown as { profileRef: string }).profileRef).toBe('')
    expect(JSON.parse(localStorage.getItem('ai-stocks-default-score-profile') || '{}'))
      .toMatchObject({ profile_ref: '', id: '' })
  })

  it('默认榜单被删除或取消可见时才清除默认偏好', async () => {
    localStorage.setItem('ai-stocks-board-default-profile', JSON.stringify({
      profile_ref: 'ref_missing_score',
      id: 'missing-score',
      name: '已失效评分方案',
      version: 1,
      is_preset: false,
      source: 'public',
      owner_label: '其他用户',
      readonly: true,
    }))
    ;(boardApi.listBoardProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(boardApi.runBoardProfile as ReturnType<typeof vi.fn>).mockRejectedValue({
      apiCode: 404,
      uiMessage: '方案不存在',
    })

    const wrapper = await mountView(BoardView)
    await flushPromises()

    expect((wrapper.vm as unknown as { profileRef: string }).profileRef).toBe('')
    expect(JSON.parse(localStorage.getItem('ai-stocks-default-score-profile') || '{}'))
      .toMatchObject({ profile_ref: '', id: '' })
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

  it('数据资产按双库和规划场景切换列集合且互不串用', async () => {
    ;(dataApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      latest_trade_date: '2026-09-08', codes: { active: 1, delisted: 0 }, bar_rows: 1,
      quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
      gaps: { stocks_with_gap: 0, gap_days_total: 0 }, last_scan_at: null,
    })
    ;(dataApi.getCatalog as ReturnType<typeof vi.fn>).mockResolvedValue({
      summary: {
        duckdb: { active_tables: 28, legacy_tables: 28, unregistered_tables: 0, database_size_bytes: 1 },
        postgres: { active_tables: 60, legacy_tables: 0, unregistered_tables: 0, database_size_bytes: 2 },
      },
      tables: [
        {
          key: 'duckdb:main:daily_bar', database: 'duckdb', schema: 'main', table: 'daily_bar',
          name_cn: '日线行情', category: '行情参考', purpose: '行情', lifecycle: 'active',
          source_of_truth: 'duckdb', metadata_complete: true, ownership_scope: 'market_global',
          data_source: 'AKShare', row_count: 10, rows: 10, row_count_mode: 'estimated',
          storage_bytes: null, latest_time: '2026-09-08', fresh: true, open_issues: 0,
          fields: [], relations: [], measured_at: null,
        },
        {
          key: 'postgres:public:audit_log', database: 'postgres', schema: 'public', table: 'audit_log',
          name_cn: '审计日志', category: '审计与协调', purpose: '审计', lifecycle: 'active',
          source_of_truth: 'postgres', metadata_complete: true, ownership_scope: 'platform_global',
          data_source: '业务服务', row_count: 20, rows: 20, row_count_mode: 'estimated',
          storage_bytes: 2048, latest_time: null, fresh: null, open_issues: 0,
          fields: [], relations: [], measured_at: null,
        },
      ],
    })
    ;(dataApi.getDimensions as ReturnType<typeof vi.fn>).mockResolvedValue({
      dimensions: [
        { dimension: 'shareholders', name_cn: '股东数据', status: 'planned', source: '公开接口', tables: [], descr: '股东人数' },
        { dimension: 'chip_peak', name_cn: '筹码分布', status: 'planned', source: '公开接口', tables: [], descr: '筹码峰' },
      ],
    })

    const wrapper = await mountView(OverviewView)
    const toolbarHtml = wrapper.get('[data-testid="overview-assets-toolbar"]').html()
    const toolbarControlOrder = [
      'overview-asset-mode',
      'overview-asset-category',
      'overview-asset-legacy',
      'overview-asset-search',
      'overview-asset-reset-filters',
    ].map((testId) => toolbarHtml.indexOf(testId))
    expect(toolbarControlOrder.every((position) => position >= 0)).toBe(true)
    expect(toolbarControlOrder).toEqual([...toolbarControlOrder].sort((a, b) => a - b))
    expect(wrapper.get('[data-testid="overview-asset-reset-filters"]').attributes('disabled'))
      .toBeDefined()

    const labels = () => wrapper.findAllComponents({ name: 'AppTableColumn' })
      .map((column) => column.props('label')).filter(Boolean)
    expect(labels()).toContain('数据库')
    expect(labels()).not.toContain('归属范围')

    ;(wrapper.vm as any).assetMode = 'duckdb'
    await wrapper.vm.$nextTick()
    expect(labels()).toContain('最新业务日')
    expect(labels()).toContain('质量问题')
    expect(labels()).not.toContain('表及索引空间')

    ;(wrapper.vm as any).assetMode = 'postgres'
    await wrapper.vm.$nextTick()
    expect(labels()).toContain('归属范围')
    expect(labels()).toContain('表及索引空间')
    expect(labels()).not.toContain('鲜活度')

    expect((wrapper.vm as any).formatQualityIssues({ open_issues: null })).toBe('—')
    expect((wrapper.vm as any).formatQualityIssues({ open_issues: 0 })).toBe('0')
    expect((wrapper.vm as any).fieldMetadataSource({
      name_source: 'glossary', description_source: 'generated',
    })).toBe('中文名：公共词典；说明：命名规则生成')

    ;(wrapper.vm as any).assetMode = 'planned'
    await wrapper.vm.$nextTick()
    expect((wrapper.vm as any).displayedAssets.map((item: any) => item.name_cn))
      .toEqual(['股东数据', '筹码分布'])
    expect(labels()).not.toContain('物理表')

    await wrapper.get('[data-testid="overview-asset-reset-filters"]').trigger('click')
    await wrapper.vm.$nextTick()
    expect((wrapper.vm as any).assetMode).toBe('all')
    expect((wrapper.vm as any).assetCategory).toBe('')
    expect((wrapper.vm as any).assetKeyword).toBe('')
    expect((wrapper.vm as any).showLegacyAssets).toBe(false)
  })

  it('数据资产旧表默认隐藏，开启后允许同名双库表并存并支持筛选', async () => {
    ;(dataApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      latest_trade_date: null, codes: { active: 0, delisted: 0 }, bar_rows: 0,
      quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
      gaps: { stocks_with_gap: 0, gap_days_total: 0 }, last_scan_at: null,
    })
    const current = {
      key: 'postgres:public:task_log', database: 'postgres', schema: 'public', table: 'task_log',
      name_cn: '任务日志', category: '任务与调度', purpose: '运行日志', lifecycle: 'active',
      source_of_truth: 'postgres', metadata_complete: true, ownership_scope: 'runtime_global',
      data_source: '业务服务', row_count: 9, rows: 9, row_count_mode: 'estimated',
      storage_bytes: 1024, latest_time: null, fresh: null, open_issues: 0,
      fields: [], relations: [], measured_at: null,
    }
    const legacy = {
      ...current, key: 'duckdb:main:task_log', database: 'duckdb', schema: 'main',
      lifecycle: 'legacy_readonly', source_of_truth: 'postgres', storage_bytes: null,
    }
    ;(dataApi.getCatalog as ReturnType<typeof vi.fn>).mockImplementation(
      ({ include_legacy }: { include_legacy?: boolean } = {}) => Promise.resolve({
        summary: {
          duckdb: { active_tables: 28, legacy_tables: 28, unregistered_tables: 0, database_size_bytes: 1 },
          postgres: { active_tables: 60, legacy_tables: 0, unregistered_tables: 0, database_size_bytes: 2 },
        },
        tables: include_legacy ? [current, legacy] : [current],
      }),
    )

    const wrapper = await mountView(OverviewView)
    expect((wrapper.vm as any).displayedAssets).toHaveLength(1)
    expect((wrapper.vm as any).displayedAssets[0].lifecycle).toBe('active')
    await (wrapper.vm as any).toggleLegacyAssets(true)
    await flushPromises()
    expect(dataApi.getCatalog).toHaveBeenLastCalledWith({ database: 'all', include_legacy: true })
    expect((wrapper.vm as any).displayedAssets.map((item: any) => item.key)).toEqual([
      'postgres:public:task_log', 'duckdb:main:task_log',
    ])

    ;(wrapper.vm as any).assetKeyword = '不存在'
    await wrapper.vm.$nextTick()
    expect((wrapper.vm as any).displayedAssets).toHaveLength(0)
    ;(wrapper.vm as any).assetKeyword = ''
    ;(wrapper.vm as any).assetCategory = '任务与调度'
    await wrapper.vm.$nextTick()
    expect((wrapper.vm as any).displayedAssets).toHaveLength(2)
  })

  it('单表精确统计只刷新当前行，失败时保留原估算值', async () => {
    ;(dataApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      latest_trade_date: null, codes: { active: 0, delisted: 0 }, bar_rows: 0,
      quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
      gaps: { stocks_with_gap: 0, gap_days_total: 0 }, last_scan_at: null,
    })
    const estimated = {
      key: 'duckdb:main:daily_bar', database: 'duckdb', schema: 'main', table: 'daily_bar',
      name_cn: '日线行情', category: '行情参考', purpose: '行情', lifecycle: 'active',
      source_of_truth: 'duckdb', metadata_complete: true, ownership_scope: 'market_global',
      data_source: 'AKShare', row_count: 10, rows: 10, row_count_mode: 'estimated',
      storage_bytes: null, latest_time: null, fresh: false, open_issues: 0,
      fields: [], relations: [], measured_at: null,
    }
    ;(dataApi.getCatalog as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ summary: {}, tables: [estimated] })
      .mockResolvedValueOnce({
        summary: {}, tables: [{ ...estimated, row_count: 12, rows: 12, row_count_mode: 'exact', measured_at: '2026-09-09T01:02:03Z' }],
      })
      .mockRejectedValueOnce(new Error('count failed'))

    const wrapper = await mountView(OverviewView)
    expect((wrapper.vm as any).formatRowCount((wrapper.vm as any).tables[0])).toBe('约 10')
    await (wrapper.vm as any).loadExactCount(estimated)
    await flushPromises()
    expect((wrapper.vm as any).formatRowCount((wrapper.vm as any).tables[0])).toBe('12')
    await (wrapper.vm as any).loadExactCount({ ...estimated, row_count: 12, row_count_mode: 'exact' })
    await flushPromises()
    expect((wrapper.vm as any).tables[0].row_count).toBe(12)
    expect((wrapper.vm as any).exactErrors[estimated.key]).toContain('count failed')
  })

  it('板块日期追平但覆盖率不足时不显示整体同步', async () => {
    ;(dataApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      latest_trade_date: '2026-08-26',
      codes: { active: 1, delisted: 0 },
      bar_rows: 1,
      board: {
        board_dict: 100, board_member: 1, board_bar: 1, board_fund_flow: 1,
        concept_count: 60, industry_count: 40,
        member_target: 100, member_ready: 100,
        bar_target: 100, bar_ready: 1,
        fund_target: 100, fund_ready: 100,
        latest_bar_date: '2026-08-26', latest_fund_date: '2026-08-26',
        open_issues: 0, issues_by_type: {}, last_update: null,
      },
      quality: { score: 100, open: 0, by_severity: {}, by_layer: [] },
      gaps: { stocks_with_gap: 0, gap_days_total: 0 },
      last_scan_at: null,
    })

    const wrapper = await mountView(OverviewView)
    const boardTab = wrapper.findAll('[role="tab"]')
      .find((tab) => tab.text().includes('板块数据'))
    expect(boardTab).toBeTruthy()
    await boardTab!.trigger('click')
    await wrapper.vm.$nextTick()

    const freshness = wrapper.findAll('.fresh-cell')
    const bar = freshness.find((cell) => cell.text().includes('板块指数'))
    const fund = freshness.find((cell) => cell.text().includes('资金流快照'))
    expect(bar?.text()).toContain('2026-08-26')
    expect(bar?.text()).toContain('未齐')
    expect(bar?.classes()).toContain('stale')
    expect(fund?.text()).toContain('同步')
    expect(fund?.classes()).not.toContain('stale')
  })

  it('数据质量加载失败显示错误态', async () => {
    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('quality failed'))
    const wrapper = await mountView(QualityView)
    expect(wrapper.text()).toContain('数据质量加载失败')
    expect(wrapper.text()).toContain('quality failed')
  })

  it('数据质量已有列表刷新失败后由错误态接管，不继续展示旧表格', async () => {
    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockResolvedValue({
      list: [{
        id: 1,
        severity: 'high',
        code: '600000.SH',
        name: '浦发银行',
        trade_date: '2026-08-20',
        issue_type: 'data_gap',
        detail: '缺少行情',
        status: 'open',
        detected_at: '2026-08-20 12:00:00',
      }],
      total: 1,
      summary: [],
    })
    const wrapper = await mountView(QualityView)
    expect(wrapper.find('.app-data-table').exists()).toBe(true)

    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('refresh failed'))
    const search = wrapper.find('input[placeholder="股票/板块代码或名称"]')
    await search.setValue('600000')
    await search.trigger('keyup', { key: 'Enter' })
    await flushPromises()

    expect(wrapper.text()).toContain('数据质量刷新失败')
    expect(wrapper.text()).toContain('refresh failed')
    expect(wrapper.find('.app-data-table').exists()).toBe(false)
  })

  it('数据质量批量标记正常复用范围弹窗并提交整体忽略', async () => {
    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockResolvedValue({
      list: [], total: 0, summary: [],
    })
    ;(dataApi.ignoreQualityBatch as ReturnType<typeof vi.fn>).mockResolvedValue({
      count: 2, status: 'ignored', ignore_scope: 'object',
    })
    const wrapper = await mountView(QualityView)
    const search = wrapper.find('input[placeholder="股票/板块代码或名称"]')
    await search.setValue('309121')
    const batchButton = wrapper.findAll('button')
      .find((button) => button.text().includes('一键标记正常'))!
    await batchButton.trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain('仅忽略本次（推荐）')
    expect(document.body.textContent).toContain('整体忽略')
    const objectOption = Array.from(document.querySelectorAll<HTMLElement>('.el-radio'))
      .find((item) => item.textContent?.includes('整体忽略'))!
    objectOption.click()
    await wrapper.vm.$nextTick()
    document.querySelector<HTMLButtonElement>('[data-testid="quality-ignore-confirm"]')!.click()
    await flushPromises()

    expect(dataApi.ignoreQualityBatch).toHaveBeenCalledWith({ code: '309121' }, 'object')
  })

  it('结构体检将行情目标日缺口展示为提醒而非失败', async () => {
    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockResolvedValue({
      list: [], total: 0, summary: [],
    })
    ;(dataApi.createTask as ReturnType<typeof vi.fn>).mockResolvedValue({ task_id: 'task-checkup-1' })
    ;(dataApi.getTask as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'task-checkup-1', task_type: 'checkup', status: 'done', progress: 1,
      message: '体检通过：1 项提醒', params: {}, created_at: '', updated_at: '',
      result: {
        checkup: {
          passed: 1, warning_count: 1, warnings: ['个股行情覆盖至结果日期'],
          total: 2, all_ok: true, fails: [],
          groups: [{
            group: 'G. 个股走势关联板块',
            checks: [
              {
                name: '个股行情覆盖至结果日期', ok: true, status: 'warn',
                detail: '目标日未覆盖 17 条', help: '该日期差异本身不否定结果。',
              },
              {
                name: '基准目标日行情完整', ok: true, status: 'pass',
                detail: '目标日未覆盖 0 条',
              },
            ],
          }],
        },
      },
    })

    const wrapper = await mountView(QualityView)
    const checkupButton = wrapper.findAll('button')
      .find((button) => button.text().includes('结构体检'))!
    await checkupButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('体检通过，1 项提醒')
    expect(wrapper.text()).toContain('WARN')
    const warningRow = wrapper.get('.checkup-row.warn')
    expect(warningRow.text()).toContain('目标日未覆盖 17 条')
    expect(warningRow.findComponent(ElTooltip).props('content')).toBe('该日期差异本身不否定结果。')
    expect(wrapper.text()).not.toContain('1 项未通过')
  })

  it('立即质检轮询超时后自动重试，运行中防重复提交并按失败终态提示', async () => {
    vi.useFakeTimers()
    const warning = vi.spyOn(ElMessage, 'warning')
    const error = vi.spyOn(ElMessage, 'error')
    const success = vi.spyOn(ElMessage, 'success')
    ;(dataApi.getDataQuality as ReturnType<typeof vi.fn>).mockResolvedValue({
      list: [], total: 0, summary: [],
    })
    ;(dataApi.createTask as ReturnType<typeof vi.fn>).mockResolvedValue({ task_id: 'task-verify-1' })
    ;(dataApi.getTask as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce({
        isAxiosError: true,
        code: 'ECONNABORTED',
        message: 'timeout of 30000ms exceeded',
      })
      .mockResolvedValueOnce({
        id: 'task-verify-1', task_type: 'verify', status: 'failed', progress: 1,
        message: '质检扫描失败', params: {}, created_at: '', updated_at: '',
      })

    const wrapper = await mountView(QualityView)
    const verifyButton = wrapper.findAll('button').find((button) => button.text().includes('立即质检'))!
    await verifyButton.trigger('click')
    await verifyButton.trigger('click')
    await flushPromises()

    expect(dataApi.createTask).toHaveBeenCalledTimes(1)
    expect(dataApi.getTask).toHaveBeenNthCalledWith(1, 'task-verify-1', { silent: true })
    expect(verifyButton.attributes('disabled')).toBeDefined()
    expect(warning).toHaveBeenCalledWith('状态查询暂时超时，后台任务仍在运行，正在自动重试')

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(dataApi.getTask).toHaveBeenCalledTimes(2)
    expect(error).toHaveBeenCalledWith('质检扫描失败')
    expect(success).not.toHaveBeenCalledWith('质检扫描失败')
    expect(verifyButton.attributes('disabled')).toBeUndefined()

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('任务中心自动轮询静默失败时保留 ready 列表，不切换整区错误态', async () => {
    vi.useFakeTimers()
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
      .mockRejectedValueOnce(new Error('poll failed'))

    const wrapper = await mountView(IngestView)
    const taskTables = wrapper.findAll('.app-data-table')
    expect(taskTables[0].attributes('data-loading')).toBe('false')

    await vi.advanceTimersByTimeAsync(2_000)
    await flushPromises()
    expect(dataApi.listTasks).toHaveBeenCalledTimes(2)
    expect(taskTables[0].attributes('data-loading')).toBe('false')
    expect(wrapper.text()).not.toContain('任务中心刷新失败')
    expect(wrapper.findAll('.app-data-table').length).toBeGreaterThan(0)

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

  it('筛选 CSV 只按可见列导出走势板块名称，不泄露相关度内部字段', async () => {
    layoutMockState.hiddenColumnsBySlot.result = ['relatedConcept']
    ;(screeningApi.runScreen as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_date: '2026-08-28',
      count: 1,
      exclude_st: true,
      hits: [{
        code: '000001.SZ',
        name: '平安银行',
        total_score: 90,
        grade: '观察',
        is_st: false,
        related_boards: {
          as_of_date: '2026-08-28',
          benchmark: { code: '399001.SZ', name: '深证成指', fallback: false },
          industry: {
            board_code: '881001', name: '银行', score: 0.82,
            corr_20: 0.86, corr_60: 0.76, sample_20: 20, sample_60: 58,
            confidence: 'high',
          },
          concept: {
            board_code: '885001', name: '中特估', score: 0.55,
            corr_20: 0.6, corr_60: 0.48, sample_20: 19, sample_60: 50,
            confidence: 'medium',
          },
        },
      }],
    })
    const wrapper = await mountView(ScreenView)
    await wrapper.findAll('button').find((button) => button.text().includes('运行筛选'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('导出 CSV'))!.trigger('click')

    expect(csvUtils.downloadCsv).toHaveBeenCalledWith(
      '筛选结果_2026-08-28.csv',
      ['全市场排名', '代码', '名称', '行业走势', '综合分', '评级', '是否ST', '评分状态'],
      [['', '000001.SZ', '平安银行', '银行', 90, '观察', '', undefined]],
    )
    const serialized = JSON.stringify((csvUtils.downloadCsv as ReturnType<typeof vi.fn>).mock.calls[0])
    expect(serialized).not.toContain('中特估')
    expect(serialized).not.toContain('corr_20')
    expect(serialized).not.toContain('0.82')
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
    ;(backtestApi.runBacktest as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('backtest failed'))
    const wrapper = await mountView(BacktestView)
    const selectors = wrapper.findAllComponents(AssetProfileSelect)
    selectors.find((select) => select.props('testId') === 'backtest-score-select')!
      .vm.$emit('update:modelValue', 'score1')
    selectors.find((select) => select.props('testId') === 'backtest-trade-select')!
      .vm.$emit('update:modelValue', 'trade1')
    await flushPromises()
    const run = wrapper.findAll('button').find((button) => button.text().includes('运行回测'))
    expect(run).toBeTruthy()
    await run!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('回测运行失败')
    expect(wrapper.text()).toContain('backtest failed')
  })

  it('回测方案首次加载失败由字段错误态接管，不与空选择框并存', async () => {
    ;(scoreApi.listScoreProfiles as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('score profiles failed'))
    const wrapper = await mountView(BacktestView)
    const scoreSelector = wrapper.findAllComponents(AssetProfileSelect)
      .find((select) => select.props('testId') === 'backtest-score-select')!
    expect(wrapper.text()).toContain('评分方案加载失败')
    expect(wrapper.text()).toContain('score profiles failed')
    expect(scoreSelector.find('[data-testid="backtest-score-select-select"]').exists()).toBe(false)
    expect(scoreSelector.find('.app-state-block__inline-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('运行回测')
  })

  it('训练历史加载失败显示错误态', async () => {
    ;(trainingApi.listSessions as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('history failed'))
    const wrapper = await mountView(TrainingView)
    expect(wrapper.text()).toContain('训练历史加载失败')
    expect(wrapper.text()).toContain('history failed')
  })
})
