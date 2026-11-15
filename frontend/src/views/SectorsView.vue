<script setup lang="ts">
import { formatNumber } from '@/utils/numberFormat'
import AppSelect from '@/components/AppSelect.vue'
import { useMenuPageTitle } from '@/composables/useMenuPageTitle'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createLatestRequestGuard } from '@/utils/latestRequestGuard'
import { Star, StarFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import AppControlRow from '@/components/AppControlRow.vue'
import AppSearchInput from '@/components/AppSearchInput.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppRowActions from '@/components/AppRowActions.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import ComparePinButton from '@/components/ComparePinButton.vue'
import AppAsyncRegion from '@/components/AppAsyncRegion.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import CompareQueueRail from '@/components/CompareQueueRail.vue'
import type { CompareQueueItem } from '@/components/CompareQueueRail.vue'
import HelpTip from '@/components/HelpTip.vue'
import HelpTipItem from '@/components/HelpTipItem.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import MarketCompareMetricStrip from '@/components/MarketCompareMetricStrip.vue'
import type { MarketMetricStripItem } from '@/components/MarketCompareMetricStrip.vue'
import MarketBenchmarkSelect from '@/components/MarketBenchmarkSelect.vue'
import MarketAnalysisHeader from '@/components/MarketAnalysisHeader.vue'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import { useMarketMasterRatioRuntime } from '@/composables/useMarketMasterRatioRuntime'
import SectorCompareChart from '@/components/SectorCompareChart.vue'
import type { CrossSectionDatum } from '@/components/SectorCompareChart.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { normalizePageSize, PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import {
  activateCompareCode,
  emptyCompareQueue,
  removeCompareCode,
  toggleComparePin,
  type CompareQueueState,
} from '@/utils/compareQueue'
import { normalizeMarketBenchmarkCode } from '@/utils/marketBenchmarks'
import {
  addSectorWatchlist,
  getSectorBenchmarkBars,
  getSectorBars,
  listSectorWatchlist,
  listSectors,
  listWatchlistSectors,
  removeSectorWatchlist,
  type BoardType,
  type SectorBar,
  type SectorRow,
  type SectorSortField,
} from '@/api/sectors'
import type { Bar, IndicatorRow, KlinePeriod } from '@/api/stocks'
import {
  COMPARE_METRIC_META,
  COMPARE_METRIC_ORDER,
  COMPARE_RANGE_OPTIONS,
  boardRangeQueryStart,
  formatSectorInflow,
  formatSectorPercent,
  metricKind,
  metricSeries,
  metricWindow,
  sectorValueClass,
  toBoardChartBars,
  type CompareMetric,
} from '@/utils/sectorCompare'
import {
  ALL_DAYS,
  trimAlignedKlineRange,
  useKlinePrefs,
} from '@/composables/useKlinePrefs'
import { usePageSettings } from '@/composables/usePageSettings'
import { useComponentPageSizeSession } from '@/composables/useComponentPageSizeSession'
import { useDefaultedSessionValue } from '@/composables/useDefaultedSessionValue'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  composeComponentRuntimeValueOf,
  useStockChartComponentConfig,
} from '@/composables/useStockChartComponentConfig'
import { useLegacyStockChartPreferenceMigration } from '@/composables/useLegacyStockChartPreferenceMigration'
import { normalizeSectorAnalysisPreferences } from '@/composables/useSectorAnalysisPreferences'
import { useTableSort } from '@/composables/useTableSort'
import { useTradeDates } from '@/composables/useTradeDates'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { useSectorsSessionStore } from '@/stores/sectorsSession'
import type { AppRequestConfig } from '@/api/client'
import { getErrorMessage, getErrorStatus } from '@/utils/error'
import { hasPermission } from '@/utils/permission'
import { sectorDetailLocation } from '@/utils/sectorNavigation'

const pageErrorRequest: AppRequestConfig = { skipGlobalError: true }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sectorsSession = useSectorsSessionStore()
const { dataMax, ensureLoaded } = useTradeDates()
const settingsOpen = ref(false)

const sectorsDefaults = {
  defaultType: '' as BoardType | '',
  defaultScope: 'all' as 'all' | 'watchlist',
}
const {
  settings,
  isDirty,
  reset,
  save: savePageSettings,
  whenHydrated,
  legacySnapshot,
} = usePageSettings('sectors', sectorsDefaults, { deferUnknownFieldCleanup: true })

const sectorsLayout = getPageLayout('sectors')
const {
  effective,
  knobs: layoutKnobs,
  setKnob,
  valueOf,
  sourceOf,
  layerValuesOf,
  isDirty: layoutDirty,
  resetAll: resetLayout,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
  remoteHydrated,
  whenRemoteHydrated,
  saveRemoteUserConfig,
  remoteSaveError,
} = useRemoteLayoutConfig(sectorsLayout)
const drawerConfig = {
  knobs: layoutKnobs,
  valueOf,
  sourceOf,
  layerValuesOf,
  setKnob,
  componentValueOf,
  setComponentKnob,
  componentSourceOf,
  componentLayerValuesOf,
  componentAllowedLayers,
  save: saveRemoteUserConfig,
}
const {
  setCurrentMasterRatioSample,
  componentRuntimeValueOf: masterRuntimeValueOf,
} = useMarketMasterRatioRuntime()
const marketWorkspaceRef = ref<{ openCompactAnalysis: () => boolean } | null>(null)
const chartPreferences = useStockChartComponentConfig({
  componentValueOf,
  setComponentKnob,
  hydrated: remoteHydrated,
})
const componentRuntimeValueOf = composeComponentRuntimeValueOf(
  masterRuntimeValueOf,
  chartPreferences.componentRuntimeValueOf,
)
useLegacyStockChartPreferenceMigration({
  pageKey: 'sectors', analysisType: 'sector', componentSourceOf, setComponentKnob,
  whenRemoteHydrated, whenPageSettingsHydrated: whenHydrated, legacySnapshot,
  saveRemoteUserConfig, remoteSaveFailed: () => remoteSaveError.value, savePageSettings,
})

const DEFAULT_SORT = 'pct_today:desc'
const SORTABLE_FIELDS = [
  'pct_today', 'pct_5d', 'pct_10d', 'pct_20d',
  'net_inflow', 'net_inflow_3d', 'net_inflow_5d', 'net_inflow_10d', 'net_inflow_20d',
  'up_count',
] as const
const {
  sortBy,
  sortOrder,
  elementDefaultSort,
  onSortChange: onTableSortChange,
} = useTableSort<SectorSortField>({
  slotId: 'table',
  defaultSort: DEFAULT_SORT,
  componentValueOf,
  allowedFields: SORTABLE_FIELDS,
})

const TYPE_OPTIONS: { label: string; value: BoardType | '' }[] = [
  { label: '全部板块', value: '' },
  { label: '概念', value: 'concept' },
  { label: '行业', value: 'industry' },
]
const CHART_MODE_OPTIONS = [
  { label: '走势对比', value: 'compare' },
  { label: 'K 线', value: 'kline' },
]
const LIST_SCOPE_OPTIONS = [
  { label: '全市场', value: 'all' },
  { label: '自选', value: 'watchlist' },
]

const hiddenColumns = computed<string[]>(() =>
  (componentValueOf('table', 'hiddenColumns') as string[]) ?? [],
)
function colVisible(key: string): boolean {
  return !hiddenColumns.value.includes(key)
}
function tableBorder(slotId: string): boolean {
  return componentValueOf(slotId, 'border') === true
}

const loading = ref(false)
const loadError = ref('')
const forbidden = ref(false)
const tradeDate = ref<string | null>('')
const marketDate = ref<string | null>(null)
// 首屏先等待持久化默认值水合，再按一次性 restore 标记恢复当前 Tab 现场；期间禁止 watcher 抢跑。
let restoring = true
const pageInitialized = ref(false)
// 五个筛选/图表口径均为单向：抽屉默认值 → 会话 ref；主区改动只进会话态，不写回默认。
// 详情返回现场由当前 Tab 的 sectorsSession 恢复，不再把普通页面状态写入 URL。
const configuredBoardType = computed<BoardType | ''>(() => (
  settings.defaultType === 'concept' || settings.defaultType === 'industry' ? settings.defaultType : ''
))
const boardType = useDefaultedSessionValue(configuredBoardType, {
  shouldSync: () => !restoring,
  onSynced: () => { search() },
})
// listScope 单向：会话 ref 初始化自默认；无自选权限的守卫在使用处（列表查询/展示），初始化不读 canViewWatchlist 避免 TDZ。
const configuredListScope = computed<'all' | 'watchlist'>(() => (
  settings.defaultScope === 'watchlist' ? 'watchlist' : 'all'
))
const listScope = useDefaultedSessionValue(configuredListScope, {
  shouldSync: () => !restoring && (
    configuredListScope.value !== 'watchlist' || canViewWatchlist.value
  ),
  onSynced: () => { changeListScope() },
})
const keyword = ref('')
const page = ref(1)
const {
  defaultPageSize: configuredPageSize,
  pageSize: size,
  changePageSize,
} = useComponentPageSizeSession({
  resolveDefault: () => componentValueOf('table', 'pageSize'),
  shouldSync: () => !restoring,
  resetPage: () => {
    page.value = 1
  },
  reload: load,
})
const total = ref(0)
const rows = ref<SectorRow[]>([])
const boardLookup = ref<Record<string, SectorRow>>({})
const watchlistCodes = ref<Set<string>>(new Set())
const watchlistBusyCodes = ref<Set<string>>(new Set())
const canViewWatchlist = computed(() =>
  hasPermission(auth.role, auth.permissions, 'sector-watchlist:view'),
)
const canUpdateWatchlist = computed(() =>
  hasPermission(auth.role, auth.permissions, 'sector-watchlist:update'),
)


// 行点击只切换主观察对象；勾选“对比”会把板块固定在图中，跨分页仍保留。
// 队列顺序稳定（进入先后），激活只移动高亮不重排，由共享 compareQueue 状态机维护。
const COMPARE_MAX = 6
const activeCode = ref('')
const pinnedCodes = ref<string[]>([])
const queueCodes = ref<string[]>([])

function currentQueue(): CompareQueueState {
  return { queueCodes: queueCodes.value, pinnedCodes: pinnedCodes.value, activeCode: activeCode.value }
}
function applyQueue(next: CompareQueueState): void {
  queueCodes.value = [...next.queueCodes]
  pinnedCodes.value = [...next.pinnedCodes]
  activeCode.value = next.activeCode
  persistListReturnState()
}

/** 退出当前板块结果上下文，避免范围切换或空结果继续展示旧图。 */
function clearChartContext(): void {
  chartRequestVersion += 1
  chartLoading.value = false
  chartError.value = ''
  benchmarkError.value = ''
  compareBars.value = {}
  compareWarmupBars.value = {}
  compareIndicators.value = {}
  loadedChartActiveCode.value = ''
  loadedChartCodes.value = []
  preserveChartOnNextLoad.value = false
  retainSelectionChart.value = false
  cumBars.value = {}
  benchmarkSeries.value = null
  applyQueue(emptyCompareQueue())
}

/** 切换板块主范围时撤下旧列表，交由 AppDataTable 统一呈现首次加载骨架。 */
function clearListContext(): void {
  rows.value = []
  total.value = 0
  boardLookup.value = {}
  clearChartContext()
}
const { validDefault: klineDefaultRange } = useKlinePrefs()
const sectorAnalysis = computed(() => normalizeSectorAnalysisPreferences(
  chartPreferences.sectorAnalysis.value,
))
// K 线范围单向：全局偏好默认范围 → 会话 ref；主区切换不写回全局默认。
const rangeDays = useDefaultedSessionValue(klineDefaultRange)
const configuredChartMode = computed<'compare' | 'kline'>(() => (
  sectorAnalysis.value.defaultChartMode
))
const configuredBenchmarkCode = computed(() => (
  normalizeMarketBenchmarkCode(sectorAnalysis.value.benchmarkCode)
))
const configuredCompareMetric = computed(() => sanitizeCompareMetric(
  sectorAnalysis.value.defaultCompareMetric,
))
const configuredCompareWindow = computed(() => (
  COMPARE_RANGE_OPTIONS.some((option) => option.value === sectorAnalysis.value.compareWindow)
    ? sectorAnalysis.value.compareWindow
    : 250
))
const chartMode = useDefaultedSessionValue(configuredChartMode)
const benchmarkCode = useDefaultedSessionValue(configuredBenchmarkCode)
const compareMetric = useDefaultedSessionValue(configuredCompareMetric)
// 累计涨跌周期单向：抽屉默认值 → 会话 ref（白名单钳制到 COMPARE_RANGE_OPTIONS）；主区改动不写回。
const compareWindow = useDefaultedSessionValue(configuredCompareWindow)
const chartLoading = ref(false)
const chartError = ref('')
const benchmarkError = ref('')
const compareBars = ref<Record<string, SectorBar[]>>({})
const compareWarmupBars = ref<Record<string, SectorBar[]>>({})
const compareIndicators = ref<Record<string, IndicatorRow[]>>({})
const compareIndicatorPeriod = ref<KlinePeriod>('day')
// 累计涨跌窗口的独立缓存：头部「累计涨跌」槽与其它固定指标（5/10/20日）的图表数据同用一个
// compareBars 会导致切固定指标时覆盖掉累计窗口数据、数值漂移，故单独缓存，仅在累计被选中时刷新。
const cumBars = ref<Record<string, SectorBar[]>>({})
const benchmarkSeries = ref<{ code: string; name: string; bars: SectorBar[] } | null>(null)
const loadedChartActiveCode = ref('')
const loadedChartCodes = ref<string[]>([])
const preserveChartOnNextLoad = ref(false)
const retainSelectionChart = ref(false)
let chartRequestVersion = 0

const activeRow = computed(() => boardLookup.value[activeCode.value] ?? null)
const chartCodes = computed(() => {
  if (!activeCode.value) return []
  if (chartMode.value === 'kline') return [activeCode.value]
  return queueCodes.value
})
const compareRows = computed(() =>
  chartCodes.value
    .map((code) => boardLookup.value[code])
    .filter((row): row is SectorRow => Boolean(row)),
)
// 行选择属于同一列表上下文内的内容刷新：请求期间继续渲染最后一次成功图表，
// 由 AppAsyncRegion 叠加 v-loading；范围切换会通过 clearChartContext 清空快照。
const isSelectionRefresh = computed(() => Boolean(
  chartLoading.value
  && retainSelectionChart.value
  && activeCode.value
  && loadedChartActiveCode.value
  && loadedChartActiveCode.value !== activeCode.value,
))
const renderedChartCodes = computed(() => (
  isSelectionRefresh.value && loadedChartCodes.value.length
    ? loadedChartCodes.value
    : chartCodes.value
))
const renderedCompareRows = computed(() =>
  renderedChartCodes.value
    .map((code) => boardLookup.value[code])
    .filter((row): row is SectorRow => Boolean(row)),
)
const compareQueueItems = computed<CompareQueueItem[]>(() =>
  compareRows.value.map((row) => ({
    key: row.board_code,
    label: row.name,
    active: row.board_code === activeCode.value,
  })),
)
function activateCompared(code: string): void {
  const row = boardLookup.value[code]
  if (row) selectRow(row)
}
const compareSeries = computed(() =>
  renderedCompareRows.value
    .filter((row) => compareBars.value[row.board_code]?.length)
    .map((row) => ({
      code: row.board_code,
      name: row.name,
      bars: compareBars.value[row.board_code]!,
    })),
)
const klineBars = computed<Bar[]>(() =>
  toBoardChartBars(compareBars.value[
    isSelectionRefresh.value ? loadedChartActiveCode.value : activeCode.value
  ] ?? []),
)
const klineWarmupBars = computed<Bar[]>(() =>
  toBoardChartBars(compareWarmupBars.value[
    isSelectionRefresh.value ? loadedChartActiveCode.value : activeCode.value
  ] ?? []),
)
const klineIndicators = computed(() => compareIndicators.value[
  isSelectionRefresh.value ? loadedChartActiveCode.value : activeCode.value
] ?? [])
const compareMetricKind = computed(() => metricKind(compareMetric.value, compareWindow.value))
// 头部槽位只展示用户配置的指标，顺序固定为指标池顺序（过滤掉历史遗留的失效指标，如 speed）。
// 配置为空时回退全量，避免头部无槽可切。
const visibleCompareMetrics = computed<CompareMetric[]>(() => {
  const configured = sectorAnalysis.value.compareMetrics
  const list = COMPARE_METRIC_ORDER.filter((m) => configured.includes(m))
  return list.length ? list : [...COMPARE_METRIC_ORDER]
})
// 请求区间窗口：趋势指标窗口跟随周期（cum=compareWindow、固定滚动=自身窗口）。
const effectiveRange = computed<number>(() =>
  chartMode.value === 'compare' ? metricWindow(compareMetric.value, compareWindow.value) : rangeDays.value,
)
const requestedPointCount = computed(() => (
  chartMode.value === 'compare' && effectiveRange.value !== ALL_DAYS
    ? effectiveRange.value + 1
    : effectiveRange.value
))
// 截面数据：即时净流入与累计成员涨跌都匹配所选行情日；单日累计退化为「今日涨幅」柱状。
const crossSection = computed<CrossSectionDatum[]>(() => {
  if (compareMetric.value === 'inflow') {
    return compareRows.value.map((row) => ({
      name: row.name,
      value: row.net_inflow,
    }))
  }
  if (compareMetric.value === 'breadth') {
    return compareRows.value.map((row) => ({
      name: row.name,
      value: row.up_count,
      second: row.down_count,
    }))
  }
  if (compareMetric.value === 'cum' && compareWindow.value === 1) {
    return compareRows.value.map((row) => ({
      name: row.name,
      value: row.pct_today,
    }))
  }
  return []
})
const hasCrossSectionData = computed(() => crossSection.value.some((item) => (
  item.value != null || item.second != null
)))
const hasChartContent = computed(() => {
  if (chartMode.value === 'kline') return klineBars.value.length > 0
  return compareMetricKind.value === 'line'
    ? compareSeries.value.length > 0
    : hasCrossSectionData.value
})
const chartEmptyTitle = computed(() => {
  if (!activeCode.value) return '选择一个板块'
  if (chartMode.value === 'kline') return '暂无 K 线数据'
  return compareMetricKind.value === 'line' ? '暂无指数走势' : '暂无对比数据'
})
const chartEmptyDescription = computed(() => {
  if (!activeCode.value) return '点击左侧排行中的任意一行即可查看走势'
  if (chartMode.value === 'compare' && compareMetricKind.value === 'bar') {
    return '对比队列暂无该指标快照'
  }
  return '可切换其他板块，或先运行板块指数采集'
})
function chartEnd(): string {
  return tradeDate.value || marketDate.value || dataMax.value || ''
}
async function loadChart(): Promise<void> {
  const preservePreviousChart = preserveChartOnNextLoad.value
  preserveChartOnNextLoad.value = false
  retainSelectionChart.value = Boolean(
    preservePreviousChart
    && loadedChartActiveCode.value
    && loadedChartActiveCode.value !== activeCode.value,
  )
  if (!analysisPanelVisible.value) {
    chartLoading.value = false
    retainSelectionChart.value = false
    return
  }
  const codes = chartCodes.value
  if (!codes.length) {
    compareBars.value = {}
    compareWarmupBars.value = {}
    benchmarkSeries.value = null
    chartError.value = ''
    benchmarkError.value = ''
    retainSelectionChart.value = false
    return
  }
  // 柱状模式（截面指标 / 单日累计）无时间轴，直接消费列表行快照，无需请求 bars。
  if (chartMode.value === 'compare' && compareMetricKind.value === 'bar') {
    chartRequestVersion += 1
    chartLoading.value = false
    chartError.value = ''
    benchmarkError.value = ''
    benchmarkSeries.value = null
    retainSelectionChart.value = false
    return
  }
  const end = chartEnd()
  const start = boardRangeQueryStart(end, requestedPointCount.value)
  if (!start || !end) {
    retainSelectionChart.value = false
    return
  }

  const requestVersion = ++chartRequestVersion
  const requestedPeriod = chartPreferences.klinePeriod.value
  chartLoading.value = true
  chartError.value = ''
  benchmarkError.value = ''
  try {
    // 截面指标（即时净流入/累计成员涨跌）与价格基准指数无同口径可比性，跳过基准请求。
    const needBenchmark = chartMode.value === 'compare'
      && compareMetricKind.value === 'line' && benchmarkCode.value
    const benchmarkPromise = needBenchmark
      ? getSectorBenchmarkBars(benchmarkCode.value, start, end)
          .catch((error) => {
            if (requestVersion === chartRequestVersion) {
              benchmarkError.value = getErrorMessage(error, '对比指数加载失败')
            }
            return null
          })
      : Promise.resolve(null)
    const [results, benchmark] = await Promise.all([Promise.all(
      codes.map(async (code) => {
        const result = await getSectorBars(
          code,
          start,
          end,
          chartMode.value === 'kline',
          requestedPeriod,
        )
        return [code, result] as const
      }),
    ), benchmarkPromise])
    if (requestVersion !== chartRequestVersion) return
    const rawSeries: Record<string, SectorBar[]> = Object.fromEntries(
      results.map(([code, result]) => [code, result.list]),
    )
    compareIndicators.value = Object.fromEntries(
      results.map(([code, result]) => [code, result.indicators ?? []]),
    )
    compareIndicatorPeriod.value = results[0]?.[1].period ?? requestedPeriod
    const benchmarkKey = benchmark ? `benchmark:${benchmark.index_code}` : ''
    if (benchmark) rawSeries[benchmarkKey] = benchmark.list
    const trimmed = trimAlignedKlineRange(rawSeries, requestedPointCount.value)
    compareBars.value = Object.fromEntries(codes.map((code) => [code, trimmed[code] ?? []]))
    compareWarmupBars.value = Object.fromEntries(codes.map((code) => {
      const visibleDates = new Set((trimmed[code] ?? []).map((row) => row.trade_date))
      return [code, (rawSeries[code] ?? []).filter((row) => !visibleDates.has(row.trade_date))]
    }))
    // 累计涨跌被选中时同步刷新其独立缓存，供头部槽在切换到其它指标后仍能取到正确窗口的数值。
    if (compareMetric.value === 'cum') {
      cumBars.value = { ...compareBars.value }
    }
    if (benchmark && !benchmark.list.length) {
      benchmarkError.value = `${benchmark.name}在当前区间暂无行情`
    }
    benchmarkSeries.value = benchmark?.list.length ? {
      code: benchmark.index_code,
      name: benchmark.name,
      bars: trimmed[benchmarkKey] ?? [],
    } : null
    loadedChartActiveCode.value = activeCode.value
    loadedChartCodes.value = [...codes]
  } catch (error) {
    if (requestVersion !== chartRequestVersion) return
    chartError.value = getErrorMessage(error, '板块走势加载失败')
  } finally {
    if (requestVersion === chartRequestVersion) {
      chartLoading.value = false
      retainSelectionChart.value = false
    }
  }
}

// 走势分析区显隐单向：抽屉默认值 → 会话 ref；主区「》」收起/展开只进会话态，不写回默认。
const analysisPanelVisible = useDefaultedSessionValue(computed(() => (
  sectorAnalysis.value.showAnalysisPanel
)))
// 抽屉默认和主区会话变化统一触发副作用。
watch(analysisPanelVisible, (visible) => {
  persistListReturnState()
  applyAnalysisPanelSideEffect(visible)
})
/** 收起分析区时保留观察对象与对比队列；再次展开后按当前筛选状态刷新走势。 */
function applyAnalysisPanelSideEffect(visible: boolean): void {
  if (visible) {
    void loadChart()
    return
  }
  chartRequestVersion += 1
  chartLoading.value = false
}

function persistListReturnState(): void {
  if (!pageInitialized.value || restoring) return
  sectorsSession.saveListReturnState({
    tradeDate: tradeDate.value,
    boardType: boardType.value,
    listScope: listScope.value,
    keyword: keyword.value.trim().slice(0, 50),
    sortBy: sortBy.value,
    sortOrder: sortOrder.value,
    page: page.value,
    size: size.value,
    chartMode: chartMode.value,
    benchmarkCode: benchmarkCode.value,
    compareMetric: compareMetric.value,
    compareWindow: compareWindow.value,
    rangeDays: rangeDays.value,
    analysisPanelVisible: analysisPanelVisible.value,
    activeCode: activeCode.value,
    pinnedCodes: pinnedCodes.value,
    queueCodes: queueCodes.value,
    queueRows: queueCodes.value
      .map((code) => boardLookup.value[code])
      .filter((row): row is SectorRow => Boolean(row)),
  })
}

async function cleanPageUrl(): Promise<void> {
  if (route.path === '/sectors' && route.fullPath !== '/sectors') {
    await router.replace('/sectors')
  }
}

function isPinned(code: string): boolean {
  return pinnedCodes.value.includes(code)
}
function togglePinned(row: SectorRow, checked: boolean): void {
  if (row.available === false) return
  boardLookup.value = { ...boardLookup.value, [row.board_code]: row }
  const result = toggleComparePin(currentQueue(), row.board_code, COMPARE_MAX)
  if (result.limitReached) {
    ElMessage.warning(`对比队列已满，最多 ${COMPARE_MAX} 个`)
    return
  }
  applyQueue(result.state)
  void loadChart()
}
function removeCompared(code: string): void {
  const fallback = rows.value.find((row) => row.available !== false)?.board_code || ''
  applyQueue(removeCompareCode(currentQueue(), code, fallback))
  void loadChart()
}
function selectRow(row: SectorRow): void {
  if (row.available === false) return
  marketWorkspaceRef.value?.openCompactAnalysis()
  boardLookup.value = { ...boardLookup.value, [row.board_code]: row }
  if (activeCode.value === row.board_code) return
  preserveChartOnNextLoad.value = hasChartContent.value
  applyQueue(activateCompareCode(currentQueue(), row.board_code, COMPARE_MAX))
  void loadChart()
}
function rowClassName({ row }: { row: SectorRow }): string {
  return [
    row.board_code === activeCode.value ? 'sector-row--active' : '',
    row.available === false ? 'sector-row--unavailable' : '',
  ].filter(Boolean).join(' ')
}

function isWatchlisted(code: string): boolean {
  return watchlistCodes.value.has(code)
}

function isWatchlistBusy(code: string): boolean {
  return watchlistBusyCodes.value.has(code)
}

async function loadWatchlist(): Promise<void> {
  if (!canViewWatchlist.value) return
  try {
    const data = await listSectorWatchlist(pageErrorRequest)
    watchlistCodes.value = new Set(data.list.map((row) => row.board_code))
  } catch (error) {
    ElMessage.error(getErrorMessage(error, '板块自选加载失败'))
  }
}

async function toggleWatchlist(row: SectorRow): Promise<void> {
  if (!canUpdateWatchlist.value || isWatchlistBusy(row.board_code)) return
  watchlistBusyCodes.value = new Set([...watchlistBusyCodes.value, row.board_code])
  const removing = isWatchlisted(row.board_code)
  try {
    if (removing) await removeSectorWatchlist(row.board_code, pageErrorRequest)
    else await addSectorWatchlist(row.board_code, pageErrorRequest)
    const next = new Set(watchlistCodes.value)
    if (removing) next.delete(row.board_code)
    else next.add(row.board_code)
    watchlistCodes.value = next
    ElMessage.success(removing ? `已移出自选：${row.name}` : `已加入自选：${row.name}`)
    if (removing && listScope.value === 'watchlist') await load()
  } catch (error) {
    ElMessage.error(getErrorMessage(error, removing ? '移出板块自选失败' : '加入板块自选失败'))
  } finally {
    const next = new Set(watchlistBusyCodes.value)
    next.delete(row.board_code)
    watchlistBusyCodes.value = next
  }
}

const sectorListRequest = createLatestRequestGuard()
async function load(options: { deferChart?: boolean } = {}): Promise<void> {
  const requestId = sectorListRequest.begin()
  persistListReturnState()
  loading.value = true
  loadError.value = ''
  forbidden.value = false
  try {
    const listApi = listScope.value === 'watchlist' ? listWatchlistSectors : listSectors
    const data = await listApi({
      trade_date: tradeDate.value || undefined,
      board_type: boardType.value || undefined,
      sort_by: sortBy.value,
      order: sortOrder.value,
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      size: size.value,
    })
    if (!sectorListRequest.isCurrent(requestId)) return
    rows.value = data.list
    total.value = data.total
    marketDate.value = data.trade_date
    boardLookup.value = {
      ...boardLookup.value,
      ...Object.fromEntries(data.list.map((row) => [row.board_code, row])),
    }

    const maxPage = Math.max(1, Math.ceil(data.total / size.value))
    if (page.value > maxPage) {
      page.value = maxPage
      return load(options)
    }

    // 首屏直接呈现可用走势，避免必须先理解控件才能看到内容。
    const availableRows = data.list.filter((row) => row.available !== false)
    if (!availableRows.length) {
      clearChartContext()
      return
    }
    const activeInCurrentList = availableRows.some((row) => row.board_code === activeCode.value)
    if (!activeInCurrentList && availableRows.length) {
      const first = availableRows[0]!.board_code
      if (!activeCode.value) {
        // 首次进入：以首个可用项重建空队列。
        applyQueue({ queueCodes: [first], pinnedCodes: [], activeCode: first })
      } else {
        // 翻页/筛选导致观察项离开当前列表：回退到首个可用项，队列顺序保持稳定。
        applyQueue(activateCompareCode(currentQueue(), first, COMPARE_MAX))
      }
      if (!options.deferChart) void loadChart()
    }
  } catch (error) {
    if (!sectorListRequest.isCurrent(requestId)) return
    if (getErrorStatus(error) === 403) forbidden.value = true
    loadError.value = getErrorMessage(error, '板块列表加载失败')
  } finally {
    if (sectorListRequest.isCurrent(requestId)) loading.value = false
  }
}

function search(): void {
  page.value = 1
  void load()
}
function changeListScope(): void {
  page.value = 1
  // 全市场 / 自选是主列表上下文切换：列表与图表都不得复用上一范围的内容。
  clearListContext()
  void load()
}
function onDateChange(): void {
  if (restoring) return
  search()
  void loadChart()
}

const defaultBoardType = computed<BoardType | ''>(() => (
  configuredBoardType.value
))
const hasQueryFilters = computed(() => (
  boardType.value !== defaultBoardType.value
  || tradeDate.value !== (dataMax.value || '')
  || keyword.value.trim() !== ''
))

async function resetQueryFilters(): Promise<void> {
  if (!hasQueryFilters.value) return
  restoring = true
  boardType.value = defaultBoardType.value
  tradeDate.value = dataMax.value || ''
  keyword.value = ''
  page.value = 1
  await nextTick()
  restoring = false
  await load({ deferChart: true })
  await loadChart()
}

async function refreshSectors(): Promise<void> {
  await Promise.all([load({ deferChart: true }), loadWatchlist()])
  await loadChart()
}

watch([sortBy, sortOrder], () => {
  if (restoring) return
  page.value = 1
  void load()
})
watch([rangeDays, chartMode, benchmarkCode, compareMetric, compareWindow], () => {
  if (restoring) return
  persistListReturnState()
  void loadChart()
})
watch(chartPreferences.klinePeriod, () => {
  if (restoring || chartMode.value !== 'kline') return
  void loadChart()
})
// 抽屉里把当前指标从展示列表移除时，回退到首个可见指标，保持图与头部一致。
watch(visibleCompareMetrics, (list) => {
  if (restoring) return
  if (list.length && !list.includes(compareMetric.value)) {
    compareMetric.value = list[0]!
  }
})

async function openDetail(): Promise<void> {
  if (!activeCode.value || activeRow.value?.available === false) return
  persistListReturnState()
  await router.push(sectorDetailLocation(activeCode.value))
}

const fmtPct = formatSectorPercent
const fmtInflow = formatSectorInflow
const pctClass = sectorValueClass

function resetSettings(): void {
  chartPreferences.cancelRatioDraft()
  reset()
  resetLayout()
}
// 头部槽快照与走势图严格同口径：趋势指标取当前板块已加载 bars 的最后一个指标值（= 图最右端点），
// 截面指标取列表行快照字段。返回 { text, cls } 避免 value/class 两处重复 switch。
function metricSlot(metric: CompareMetric): { text: string; cls: string } {
  if (!activeRow.value) return { text: '—', cls: 'muted' }
  const row = activeRow.value
  if (metric === 'breadth') return { text: `${row.up_count} / ${row.down_count}`, cls: '' }
  if (metric === 'inflow') return { text: fmtInflow(row.net_inflow), cls: pctClass(row.net_inflow) }
  // 单日累计：柱状口径与列表行今日涨幅一致。
  if (metric === 'cum' && compareWindow.value === 1) {
    return { text: fmtPct(row.pct_today), cls: pctClass(row.pct_today) }
  }
  // 固定滚动指标：直接用后端已算好的窗口涨幅字段（与列表行同口径）。
  if (metric === 'roll_5d') return { text: fmtPct(row.pct_5d), cls: pctClass(row.pct_5d) }
  if (metric === 'roll_10d') return { text: fmtPct(row.pct_10d), cls: pctClass(row.pct_10d) }
  if (metric === 'roll_20d') return { text: fmtPct(row.pct_20d), cls: pctClass(row.pct_20d) }
  // 累计涨跌：从独立缓存 cumBars 按当前周期窗口现算，避免被其它指标的数据覆盖导致数值漂移。
  const bars = cumBars.value[activeCode.value]
  if (!bars?.length) return { text: '—', cls: 'muted' }
  const vals = metricSeries(bars, 'cum')
  const last = vals[vals.length - 1] ?? null
  return { text: last == null ? '—' : fmtPct(last), cls: pctClass(last) }
}
function metricSlotLabel(metric: CompareMetric): string {
  const base = COMPARE_METRIC_META[metric].label
  if (metric === 'cum') {
    const opt = COMPARE_RANGE_OPTIONS.find((o) => o.value === compareWindow.value)
    return opt ? `${base} · ${opt.label}` : base
  }
  return base
}
const metricStripItems = computed<MarketMetricStripItem[]>(() => visibleCompareMetrics.value.map((metric) => {
  const slot = metricSlot(metric)
  if (metric === 'breadth') {
    const [up = '—', down = '—'] = slot.text.split(' / ')
    return {
      key: metric,
      label: metricSlotLabel(metric),
      value: slot.text,
      parts: [
        { text: up, tone: 'up' },
        { text: '/', tone: 'muted' },
        { text: down, tone: 'down' },
      ],
    }
  }
  return {
    key: metric,
    label: metricSlotLabel(metric),
    value: slot.text,
    tone: slot.cls === 'up' || slot.cls === 'down' || slot.cls === 'muted' ? slot.cls : 'neutral',
  }
}))
function sanitizeCompareMetric(value: unknown): CompareMetric {
  const v = String(value ?? '')
  return (COMPARE_METRIC_ORDER as string[]).includes(v) ? (v as CompareMetric) : 'cum'
}
// 切换指标：固定窗口指标（5/10/20日）不反向改动累计涨跌的周期窗口——累计窗口只由周期列表下拉决定。
function selectCompareMetric(value: string): void {
  if (!(COMPARE_METRIC_ORDER as string[]).includes(value)) return
  const metric = value as CompareMetric
  if (compareMetric.value === metric) return
  compareMetric.value = metric
}

watch(
  () => [route.path, route.query.restore] as const,
  ([path, restore]) => {
    if (!pageInitialized.value || path !== '/sectors' || restore !== '1') return
    // KeepAlive 返回时页面实例已保留现场，只消费持久化副本并清理一次性标记。
    sectorsSession.consumeListReturnState()
    void cleanPageUrl()
  },
)

onMounted(async () => {
  await Promise.all([whenHydrated(), whenRemoteHydrated()])
  size.value = configuredPageSize.value
  await ensureLoaded().catch(() => undefined)
  // 只有显式详情返回才恢复一次性现场；普通进入或刷新重新应用抽屉保存的默认值。
  const restored = route.query.restore === '1'
    ? sectorsSession.consumeListReturnState()
    : null
  restoring = true
  tradeDate.value = typeof restored?.tradeDate === 'string' ? restored.tradeDate : dataMax.value || ''
  boardType.value = restored && (
    restored.boardType === 'concept' || restored.boardType === 'industry' || restored.boardType === ''
  ) ? restored.boardType : configuredBoardType.value
  const defaultScope = configuredListScope.value === 'watchlist' && canViewWatchlist.value
    ? 'watchlist'
    : 'all'
  listScope.value = restored
    ? (restored.listScope === 'watchlist' && canViewWatchlist.value ? 'watchlist' : 'all')
    : defaultScope
  chartMode.value = restored?.chartMode === 'kline' ? 'kline' : configuredChartMode.value
  benchmarkCode.value = restored
    ? normalizeMarketBenchmarkCode(restored.benchmarkCode)
    : configuredBenchmarkCode.value
  compareMetric.value = sanitizeCompareMetric(
    restored?.compareMetric ?? sectorAnalysis.value.defaultCompareMetric,
  )
  compareWindow.value = COMPARE_RANGE_OPTIONS.some((option) => option.value === restored?.compareWindow)
    ? restored!.compareWindow
    : configuredCompareWindow.value
  rangeDays.value = restored && Number.isFinite(restored.rangeDays) && restored.rangeDays > 0
    ? restored.rangeDays
    : klineDefaultRange.value
  analysisPanelVisible.value = typeof restored?.analysisPanelVisible === 'boolean'
    ? restored.analysisPanelVisible
    : sectorAnalysis.value.showAnalysisPanel
  // 默认指标若被移出展示列表，回退到首个可见指标，避免图与头部高亮脱节。
  if (!visibleCompareMetrics.value.includes(compareMetric.value)) {
    compareMetric.value = visibleCompareMetrics.value[0] ?? 'cum'
  }
  keyword.value = typeof restored?.keyword === 'string' ? restored.keyword.slice(0, 50) : ''
  page.value = Number.isInteger(restored?.page) && Number(restored?.page) > 0
    ? Number(restored?.page)
    : 1
  size.value = restored ? normalizePageSize(restored.size, configuredPageSize.value) : configuredPageSize.value
  if (restored && (SORTABLE_FIELDS as readonly string[]).includes(restored.sortBy)) {
    onTableSortChange({
      prop: restored.sortBy,
      order: restored.sortOrder === 'asc' ? 'ascending' : 'descending',
    })
  }
  if (restored) {
    boardLookup.value = Object.fromEntries(
      (Array.isArray(restored.queueRows) ? restored.queueRows : [])
        .filter((row) => row && typeof row.board_code === 'string')
        .map((row) => [row.board_code, row]),
    )
    const queueCodes = Array.isArray(restored.queueCodes)
      ? restored.queueCodes.filter((value): value is string => typeof value === 'string').slice(0, COMPARE_MAX)
      : []
    const pinnedCodes = Array.isArray(restored.pinnedCodes)
      ? restored.pinnedCodes
          .filter((value): value is string => typeof value === 'string' && queueCodes.includes(value))
          .slice(0, COMPARE_MAX)
      : []
    applyQueue({
      activeCode: typeof restored.activeCode === 'string' ? restored.activeCode : '',
      pinnedCodes,
      queueCodes,
    })
  }
  restoring = false
  pageInitialized.value = true
  await cleanPageUrl()
  await loadWatchlist()
  void load()
})
const menuPageTitle = useMenuPageTitle()
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <h2 class="app-page-title page-title-row">
              {{ menuPageTitle }}
              <HelpTip title="板块行情怎么看？" :width="460" test-id="sectors-help-tip">
                <HelpTipItem question="涨幅口径是什么">
                  <ul>
                    <li>今日涨幅相对上一交易日收盘；5/10/20 日涨幅相对对应交易日前收盘，历史不足显示“—”。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="资金口径是什么">
                  <ul>
                    <li>即时及多日净流入来自与行情同日的资金流快照，单位为亿元；当日未匹配到数据时显示“—”，不回退到其他日期。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="排行如何操作">
                  <ul>
                    <li>点击列头切换排序；列显隐在页面设置中管理；点击板块行切换当前观察对象。</li>
                  </ul>
                </HelpTipItem>
                <HelpTipItem question="对比如何操作">
                  <ul>
                    <li>勾选板块加入走势对比，最多 {{ COMPARE_MAX }} 个；收起右侧分析区后可专注查看排行，再次展开会保留当前观察状态。</li>
                  </ul>
                </HelpTipItem>
              </HelpTip>
            </h2>
            <p class="page-subtitle">从强弱排行定位主线，点选板块后在同一视野比较走势。</p>
          </div>
          <AppControlRow class="page-head-actions">
            <el-button data-testid="sectors-refresh" :loading="loading || chartLoading" @click="refreshSectors">刷新</el-button>
            <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
          </AppControlRow>
        </div>

        <el-card shadow="never" class="filter-card">
          <AppControlRow class="filter-row">
            <PageSegmented
              v-if="canViewWatchlist"
              v-model="listScope"
              :options="LIST_SCOPE_OPTIONS"
              aria-label="板块范围"
              test-id="sectors-list-scope"
              tone="primary"
              @update:model-value="changeListScope"
            />
            <PageSegmented
              v-model="boardType"
              :options="TYPE_OPTIONS"
              aria-label="板块类型"
              test-id="sectors-type"
              @update:model-value="search"
            />
            <TradeDatePicker
              v-model="tradeDate"
              placeholder="交易日期"
              class="app-control-width-long"
              @update:model-value="onDateChange"
            />
            <AppSearchInput
              v-model="keyword"
              placeholder="搜索板块"
              class="app-control-width-long"
              maxlength="50"
              data-testid="sectors-keyword"
              @search="search"
            />
            <el-button data-testid="sectors-reset-filters" :disabled="!hasQueryFilters" @click="resetQueryFilters">重置筛选</el-button>
          </AppControlRow>
        </el-card>
      </div>
    </template>

    <template #main>
      <AppStateBlock
        v-if="forbidden"
        state="error"
        variant="permission"
        title="无权限查看板块行情"
        description="请联系系统管理员调整权限"
      />
      <AppStateBlock
        v-else-if="loadError"
        state="error"
        :title="rows.length ? '板块排行刷新失败' : '板块行情加载失败'"
        :description="loadError"
        retry
        @retry="load"
      />
      <MarketMasterDetailWorkspace
        v-else
        ref="marketWorkspaceRef"
        v-model:analysis-visible="analysisPanelVisible"
        eyebrow="强弱排行"
        :title="marketDate || tradeDate || '最新交易日'"
        :meta="`${formatNumber(total, 'count')} 个${listScope === 'watchlist' ? '自选' : '板块'}`"
        list-aria-label="板块强弱排行"
        :default-master-ratio="Number(componentValueOf('workspace', 'masterRatio') ?? 45)"
        :master-ratio-profiles="componentValueOf('workspace', 'masterRatioProfiles')"
        analysis-drawer-title="板块走势分析"
        @master-ratio-sample-change="setCurrentMasterRatioSample"
        test-id-prefix="sectors"
        data-testid="sectors-workspace"
      >
        <template #list>
          <AppDataTable
            data-testid="sectors-table"
            kind="wide-table"
            :data="rows"
            :loading="loading"
            row-key="board_code"
            :row-class-name="rowClassName"
            :border="tableBorder('table')"
            :default-sort="elementDefaultSort"
            clickable
            aria-label="板块强弱排行"
            :pagination="{ currentPage: page, pageSize: size, total, pageSizes: PAGE_SIZE_OPTIONS, small: true }"
            @row-click="selectRow"
            @sort-change="onTableSortChange"
            @page-change="(value: number) => { page = value; void load() }"
            @size-change="changePageSize"
          >
            <AppTableColumn v-if="!colVisible('name')" label="操作" role="action-compact">
              <template #default="{ row }">
                <AppRowActions :actions="[{ key: 'view', kind: 'navigation', label: '查看走势', disabled: row.available === false, onClick: () => selectRow(row) }]" />
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('name')"
              label="板块"
              prop="name"
              role="entity"
              :leading-controls="canUpdateWatchlist ? 2 : 1"
            >
              <template #default="{ row }">
                <div
                  class="sector-name-cell"
                  :data-testid="row?.board_code ? `sectors-row-${row.board_code}` : undefined"
                >
                  <AppIconButton
                    v-if="canUpdateWatchlist"
                    v-permission="'sector-watchlist:update'"
                    class="watchlist-button"
                    :class="{ 'watchlist-button--active': isWatchlisted(row.board_code) }"
                    :aria-pressed="isWatchlisted(row.board_code)"
                    :label="`${isWatchlisted(row.board_code) ? '移出' : '加入'}板块自选：${row.name}`"
                    :loading="isWatchlistBusy(row.board_code)"
                    :data-testid="`sectors-watchlist-${row.board_code}`"
                    size="xs"
                    @click.stop="toggleWatchlist(row)"
                  >
                    <el-icon><StarFilled v-if="isWatchlisted(row.board_code)" /><Star v-else /></el-icon>
                  </AppIconButton>
                  <ComparePinButton
                    :disabled="row.available === false"
                    :active="isPinned(row.board_code)"
                    :label="`${isPinned(row.board_code) ? '移出' : '加入'}走势对比：${row.name}`"
                    :test-id="row?.board_code ? `sectors-pin-${row.board_code}` : undefined"
                    @toggle="togglePinned(row, !isPinned(row.board_code))"
                  />
                  <div class="sector-name-copy">
                    <el-button data-button-kind="navigation"
                      link
                      type="primary"
                      class="sector-select app-table-field-link"
                      :disabled="row.available === false"
                      :data-testid="row?.board_code ? `sectors-name-${row.board_code}` : undefined"
                      @click.stop="selectRow(row)"
                    >
                      {{ row.name }}
                    </el-button>
                    <span v-if="row.available === false">{{ row.board_type === 'concept' ? '概念' : '行业' }} · 已失效</span>
                    <span v-else>{{ row.board_type === 'concept' ? '概念' : '行业' }} · 最近快照 {{ formatNumber(row.member_count, 'count') }}只</span>
                  </div>
                </div>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_today')"
              label="今日涨幅"
              prop="pct_today"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong class="app-data-text" :class="pctClass(row.pct_today)">{{ fmtPct(row.pct_today) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_5d')"
              label="5日涨幅"
              prop="pct_5d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.pct_5d)"
                  :data-testid="row?.board_code ? `sectors-pct-5d-${row.board_code}` : undefined"
                >{{ fmtPct(row.pct_5d) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_10d')"
              label="10日涨幅"
              prop="pct_10d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.pct_10d)"
                  :data-testid="row?.board_code ? `sectors-pct-10d-${row.board_code}` : undefined"
                >{{ fmtPct(row.pct_10d) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_20d')"
              label="20日涨幅"
              prop="pct_20d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.pct_20d)"
                  :data-testid="row?.board_code ? `sectors-pct-20d-${row.board_code}` : undefined"
                >{{ fmtPct(row.pct_20d) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow')"
              label="即时净流入"
              prop="net_inflow"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.net_inflow)"
                  :data-testid="row?.board_code ? `sectors-inflow-${row.board_code}` : undefined"
                >{{ fmtInflow(row.net_inflow) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_3d')"
              label="3日净流入"
              prop="net_inflow_3d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.net_inflow_3d)"
                >{{ fmtInflow(row.net_inflow_3d) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_5d')"
              label="5日净流入"
              prop="net_inflow_5d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.net_inflow_5d)"
                >{{ fmtInflow(row.net_inflow_5d) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_10d')"
              label="10日净流入"
              prop="net_inflow_10d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.net_inflow_10d)"
                >{{ fmtInflow(row.net_inflow_10d) }}</strong>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_20d')"
              label="20日净流入"
              prop="net_inflow_20d"
              sortable="custom"
              role="number"
            >
              <template #default="{ row }">
                <strong
                  class="app-data-text"
                  :class="pctClass(row.net_inflow_20d)"
                >{{ fmtInflow(row.net_inflow_20d) }}</strong>
              </template>
            </AppTableColumn>
            <template #empty>
              <span v-if="keyword.trim()">没有匹配板块，换个关键词试试</span>
              <span v-else-if="listScope === 'watchlist'">还没有自选板块，请在“全市场”中点击星标添加</span>
              <span v-else>暂无板块数据，请先运行板块采集</span>
            </template>
          </AppDataTable>
        </template>

        <template #analysis>
        <section
          class="chart-panel app-surface"
          aria-label="板块走势分析"
          data-testid="sectors-chart"
        >
          <MarketAnalysisHeader
            :title="activeRow?.name || '等待选择板块'"
            :code="activeRow?.board_code"
            :detail-visible="!!activeRow"
            :detail-disabled="activeRow?.available === false"
            title-test-id="sectors-chart-title"
            detail-test-id="sectors-open-detail"
            data-testid="sectors-chart-header"
            @open-detail="openDetail"
          >
            <template #description>
              <span>
                {{ chartMode === 'compare' ? `与 ${Math.max(0, chartCodes.length - 1)} 个板块对比区间强弱` : '查看板块指数开高低收与量能' }}
                <template v-if="activeRow?.leader_stock">
                  · 领涨 {{ activeRow.leader_stock }}
                  <strong :class="pctClass(activeRow.leader_pct)">{{ fmtPct(activeRow.leader_pct) }}</strong>
                </template>
              </span>
            </template>
            <template #controls>
              <div v-if="chartMode === 'compare' && compareMetricKind === 'line'" class="benchmark-control">
                <span class="market-analysis-control-label">对比指数</span>
                <MarketBenchmarkSelect
                  v-model="benchmarkCode"
                  test-id="sectors-benchmark"
                />
              </div>
              <KlineRangeSelect v-if="chartMode === 'kline'" v-model="rangeDays" test-id="sectors-range" />
              <AppSelect
                v-else-if="chartMode === 'compare' && compareMetric === 'cum'"
                v-model="compareWindow"
                data-testid="sectors-compare-range"
                width="compact"
              >
                <el-option v-for="o in COMPARE_RANGE_OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
              </AppSelect>
              <PageSegmented
                v-model="chartMode"
                :options="CHART_MODE_OPTIONS"
                aria-label="图表模式"
                test-id="sectors-chart-mode"
                tone="primary"
              />
            </template>
          </MarketAnalysisHeader>

          <MarketCompareMetricStrip
            v-if="activeRow"
            :items="metricStripItems"
            :active-key="compareMetric"
            ariaLabel="板块对比指标"
            test-id-prefix="sectors-metric"
            @select="selectCompareMetric"
          />

          <CompareQueueRail
            v-if="chartMode === 'compare' && chartCodes.length"
            :items="compareQueueItems"
            aria-label="当前对比板块"
            :hint="`勾选左侧板块加入，最多 ${COMPARE_MAX} 个`"
            :max="COMPARE_MAX"
            test-id-prefix="sectors"
            @activate="activateCompared"
            @remove="removeCompared"
          />

          <AppAsyncRegion
            class="chart-stage"
            :loading="chartLoading"
            :has-content="hasChartContent"
            :error="chartError"
            loading-title="正在加载板块走势…"
            error-title="板块走势加载失败"
            :empty-title="chartEmptyTitle"
            :empty-description="chartEmptyDescription"
            retry
            @retry="loadChart"
          >
            <SectorCompareChart
              v-if="chartMode === 'compare'"
              data-testid="sectors-compare-chart"
              :series="compareSeries"
              :benchmark="benchmarkSeries"
              :metric="compareMetric"
              :range-days="compareWindow"
              :cross-section="crossSection"
              fill
            />
            <StockChartWorkspace
              v-else
              embedded
              class="sector-kline-workspace"
              :bars="klineBars"
              :warmup-bars="klineWarmupBars"
              :indicators="klineIndicators"
              :indicators-period="compareIndicatorPeriod"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              adjust-label="原始连续指数"
              :min-height="384"
              :zoom-start="0"
              :zoom-end="100"
              aria-label="板块指数多图联动工作区"
              enable-return-measurement
              enable-kline-period-switch
              v-model:return-measurement-mode="chartPreferences.returnMeasurementMode.value"
              v-model:kline-period="chartPreferences.klinePeriod.value"
              @ratio-draft="chartPreferences.handleRatioDraft"
              @ratio-commit="chartPreferences.handleRatioCommit"
              @workspace-resize="chartPreferences.handleWorkspaceResize"
            />
          </AppAsyncRegion>

          <footer v-if="chartMode === 'compare'" class="chart-footer">
            <span v-if="benchmarkError && compareMetricKind === 'line'" class="benchmark-warning">{{ benchmarkError }}，当前仅显示板块走势。</span>
            <span v-else-if="compareMetricKind === 'bar' && (compareMetric === 'inflow' || compareMetric === 'breadth')" class="compare-explanation">
              净流入使用独立最新快照；成员涨跌按所选行情日计算。两者均为截面值，故以柱状对比，不叠加市场指数。
            </span>
            <span v-else-if="compareMetricKind === 'bar'" class="compare-explanation">
              单日涨幅为截面快照，故以柱状对比。
            </span>
            <span v-else-if="!benchmarkCode" class="compare-explanation">
              {{ metricSlotLabel(compareMetric) }}；当前未选择市场指数，只比较板块之间的相对强弱。
            </span>
            <span v-else class="compare-explanation">
              {{ metricSlotLabel(compareMetric) }}；虚线为{{ benchmarkSeries?.name || '所选指数' }}，悬浮可查看板块相对指数的超额涨跌。
            </span>
          </footer>
        </section>
        </template>
      </MarketMasterDetailWorkspace>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="板块行情"
        :dirty="isDirty || layoutDirty"
        page-key="sectors"
        :config="drawerConfig"
        :business-visible="true"
        :component-runtime-value-of="componentRuntimeValueOf"
        @reset="resetSettings"
      >
        <template #business>
          <PageSettingSection section-key="default-query" title="默认查询">
            <PageSettingItem v-if="canViewWatchlist" label="默认板块范围">
              <PageSegmented
                v-model="settings.defaultScope"
                :options="LIST_SCOPE_OPTIONS"
                aria-label="默认板块范围"
                test-id="sectors-default-scope"
              />
            </PageSettingItem>
            <PageSettingItem label="默认类型">
              <PageSegmented
                v-model="settings.defaultType"
                :options="TYPE_OPTIONS"
                aria-label="默认类型"
                test-id="sectors-default-type"
              />
            </PageSettingItem>
          </PageSettingSection>
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-title-row {
  display: flex;
  align-items: center;
}
.panel-eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.filter-row {
  flex-wrap: wrap;
}
.chart-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.chart-panel {
  display: flex;
  flex-direction: column;
}
:deep(.el-table__row.sector-row--active > td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, var(--el-bg-color));
}
:deep(.el-table__row.sector-row--active > td:first-child) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.sector-name-cell {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}
:deep(.el-table__row.sector-row--unavailable > td.el-table__cell) {
  background: var(--el-fill-color-extra-light);
  color: var(--el-text-color-placeholder);
}
.sector-name-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: var(--app-line-height-table);
}
.sector-select {
  overflow: hidden;
  padding: 0;
  height: auto;
  min-height: 0;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sector-name-copy > span {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chart-panel {
  position: relative;
}
.chart-panel :deep(.market-analysis-header__description strong) {
  font-variant-numeric: tabular-nums;
}
.benchmark-control {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  white-space: nowrap;
}
.chart-stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.chart-stage :deep(.cmp-wrap),
.chart-stage :deep(.cmp),
.sector-kline-workspace {
  height: 100%;
}
.chart-footer {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-height: 44px;
  padding: var(--app-space-2) var(--app-space-3);
  border-top: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
}
.compare-explanation {
  color: var(--el-text-color-secondary);
}
.benchmark-warning {
  color: var(--el-color-warning);
}
@container app-viewport (max-width: 1180px) {
  .page-subtitle {
    display: none;
  }
}
@container app-viewport (max-height: 700px) {
  .chart-footer {
    min-height: 36px;
    padding-block: var(--app-space-1);
  }
}
</style>
