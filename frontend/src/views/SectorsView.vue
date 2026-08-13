<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, type Sort } from 'element-plus'
import { ArrowRight, Close, DArrowLeft, DArrowRight, Star, StarFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import AppControlRow from '@/components/AppControlRow.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppIconButton from '@/components/AppIconButton.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import HelpTip from '@/components/HelpTip.vue'
import KlineSettingSection from '@/components/KlineSettingSection.vue'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingSection from '@/components/PageSettingSection.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import PageSettingsTrigger from '@/components/PageSettingsTrigger.vue'
import SectorCompareChart from '@/components/SectorCompareChart.vue'
import StockChartSettingSection from '@/components/StockChartSettingSection.vue'
import StockChartWorkspace from '@/components/stock-chart/StockChartWorkspace.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { PAGE_SIZE_OPTIONS } from '@/constants/pagination'
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
import type { Bar, IndicatorRow } from '@/api/stocks'
import {
  COMPARE_METRIC_META,
  COMPARE_METRIC_ORDER,
  COMPARE_RANGE_OPTIONS,
  metricKind,
  metricSeries,
  metricWindow,
  type CompareMetric,
} from '@/utils/sectorCompare'
import {
  klineRangeQueryStart,
  trimAlignedKlineRange,
  useKlinePrefs,
} from '@/composables/useKlinePrefs'
import { usePageSettings } from '@/composables/usePageSettings'
import { useRemoteLayoutConfig } from '@/composables/useRemoteLayoutConfig'
import {
  createDefaultStockChartPreferences,
  useStockChartPreferences,
  type AuxiliaryChartSlot,
} from '@/composables/useStockChartPreferences'
import { useTableSort } from '@/composables/useTableSort'
import { useTradeDates } from '@/composables/useTradeDates'
import { getPageLayout } from '@/layout'
import LayoutHost from '@/layout/components/LayoutHost.vue'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage, getErrorStatus } from '@/utils/error'
import { hasPermission } from '@/utils/permission'
import {
  resolveSectorListState,
  sanitizeSectorSourceQuery,
  toLocationQuery,
} from '@/utils/sectorNavigation'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { dataMin, dataMax, ensureLoaded } = useTradeDates()
const settingsOpen = ref(false)

const BENCHMARK_OPTIONS = [
  { label: '不对比指数', value: '' },
  { label: '中证 500', value: '000905.SH' },
  { label: '沪深 300', value: '000300.SH' },
]
const sectorsDefaults = {
  defaultType: '' as BoardType | '',
  defaultScope: 'all' as 'all' | 'watchlist',
  defaultChartMode: 'compare' as 'compare' | 'kline',
  benchmarkCode: '000905.SH',
  showAnalysisPanel: true,
  compareMetrics: COMPARE_METRIC_ORDER as CompareMetric[],
  defaultCompareMetric: 'cum' as CompareMetric,
  charts: createDefaultStockChartPreferences(),
}
const { settings, isDirty, reset, hydrated, whenHydrated } = usePageSettings('sectors', sectorsDefaults)
const chartSettings = computed({
  get: () => settings.charts,
  set: (value) => { settings.charts = value },
})
const chartPreferences = useStockChartPreferences(chartSettings, hydrated)

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
}

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
  setComponentKnob,
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

const defaultSize = computed<number>(() => {
  const value = componentValueOf('table', 'pageSize')
  return typeof value === 'number' ? value : 20
})
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
const boardType = ref<BoardType | ''>(settings.defaultType)
const listScope = ref<'all' | 'watchlist'>(settings.defaultScope)
const keyword = ref('')
const page = ref(1)
const size = ref(defaultSize.value)
const total = ref(0)
const rows = ref<SectorRow[]>([])
const fundFlowDate = ref<string | null>(null)
const boardLookup = ref<Record<string, SectorRow>>({})
const watchlistCodes = ref<Set<string>>(new Set())
const watchlistBusyCodes = ref<Set<string>>(new Set())
const canViewWatchlist = computed(() =>
  hasPermission(auth.role, auth.permissions, 'sector-watchlist:view'),
)
const canUpdateWatchlist = computed(() =>
  hasPermission(auth.role, auth.permissions, 'sector-watchlist:update'),
)

let restoring = false
let searchTimer: ReturnType<typeof setTimeout> | null = null

// 行点击只切换主观察对象；勾选“对比”会把板块固定在图中，跨分页仍保留。
const COMPARE_MAX = 6
const activeCode = ref('')
const pinnedCodes = ref<string[]>([])
const { validDefault: klineDefaultRange } = useKlinePrefs()
const rangeDays = ref<number>(klineDefaultRange.value)
const chartMode = ref<'compare' | 'kline'>(settings.defaultChartMode)
const benchmarkCode = ref(settings.benchmarkCode)
const compareMetric = ref<CompareMetric>(settings.defaultCompareMetric)
const compareWindow = ref<number>(250)
const chartLoading = ref(false)
const chartError = ref('')
const benchmarkError = ref('')
const compareBars = ref<Record<string, SectorBar[]>>({})
const compareIndicators = ref<Record<string, IndicatorRow[]>>({})
// 累计涨跌窗口的独立缓存：头部「累计涨跌」槽与其它固定指标（5/10/20日）的图表数据同用一个
// compareBars 会导致切固定指标时覆盖掉累计窗口数据、数值漂移，故单独缓存，仅在累计被选中时刷新。
const cumBars = ref<Record<string, SectorBar[]>>({})
const benchmarkSeries = ref<{ code: string; name: string; bars: SectorBar[] } | null>(null)
let chartRequestVersion = 0

const activeRow = computed(() => boardLookup.value[activeCode.value] ?? null)
const chartCodes = computed(() => {
  if (!activeCode.value) return []
  if (chartMode.value === 'kline') return [activeCode.value]
  return Array.from(new Set([activeCode.value, ...pinnedCodes.value])).slice(0, COMPARE_MAX)
})
const compareRows = computed(() =>
  chartCodes.value
    .map((code) => boardLookup.value[code])
    .filter((row): row is SectorRow => Boolean(row)),
)
const compareSeries = computed(() =>
  compareRows.value
    .filter((row) => compareBars.value[row.board_code]?.length)
    .map((row) => ({
      code: row.board_code,
      name: row.name,
      bars: compareBars.value[row.board_code]!,
    })),
)
const klineBars = computed<Bar[]>(() =>
  (compareBars.value[activeCode.value] ?? []).map((bar, index, source) => ({
    date: bar.trade_date,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    pre_close: index > 0 ? source[index - 1]!.close : null,
    volume: bar.volume,
    amount: bar.amount,
    turnover_rate: null,
  })),
)
const klineIndicators = computed(() => compareIndicators.value[activeCode.value] ?? [])
const compareMetricKind = computed(() => metricKind(compareMetric.value, compareWindow.value))
// 头部槽位只展示用户配置的指标，顺序固定为指标池顺序（过滤掉历史遗留的失效指标，如 speed）。
// 配置为空时回退全量，避免头部无槽可切。
const visibleCompareMetrics = computed<CompareMetric[]>(() => {
  const configured = settings.compareMetrics as CompareMetric[]
  const list = COMPARE_METRIC_ORDER.filter((m) => configured.includes(m))
  return list.length ? list : [...COMPARE_METRIC_ORDER]
})
const metricStripStyle = computed(() => ({
  gridTemplateColumns: `repeat(${visibleCompareMetrics.value.length}, minmax(72px, 1fr))`,
}))
// 请求区间窗口：趋势指标窗口跟随周期（cum=compareWindow、固定滚动=自身窗口）。
const effectiveRange = computed<number>(() =>
  chartMode.value === 'compare' ? metricWindow(compareMetric.value, compareWindow.value) : rangeDays.value,
)
// 截面数据：净流入/涨跌家数取列表行快照；单日累计退化为「今日涨幅」柱状。
const crossSection = computed(() => {
  if (compareMetric.value === 'inflow') {
    return compareRows.value.map((row) => ({
      name: row.name,
      value: row.net_inflow ?? 0,
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
      value: row.pct_today ?? 0,
    }))
  }
  return []
})
function chartEnd(): string {
  return tradeDate.value || marketDate.value || dataMax.value || ''
}
async function loadChart(): Promise<void> {
  if (!settings.showAnalysisPanel) {
    chartLoading.value = false
    return
  }
  const codes = chartCodes.value
  if (!codes.length) {
    compareBars.value = {}
    benchmarkSeries.value = null
    chartError.value = ''
    benchmarkError.value = ''
    return
  }
  // 柱状模式（截面指标 / 单日累计）无时间轴，直接消费列表行快照，无需请求 bars。
  if (chartMode.value === 'compare' && compareMetricKind.value === 'bar') {
    chartRequestVersion += 1
    chartLoading.value = false
    chartError.value = ''
    benchmarkError.value = ''
    benchmarkSeries.value = null
    return
  }
  const end = chartEnd()
  const start = klineRangeQueryStart(end, effectiveRange.value, dataMin.value || '2024-01-01')
  if (!start || !end) return

  const requestVersion = ++chartRequestVersion
  chartLoading.value = true
  chartError.value = ''
  benchmarkError.value = ''
  try {
    // 截面指标（净流入/涨跌家数）与价格基准指数无同口径可比性，跳过基准请求。
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
        const result = await getSectorBars(code, start, end, chartMode.value === 'kline')
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
    const benchmarkKey = benchmark ? `benchmark:${benchmark.index_code}` : ''
    if (benchmark) rawSeries[benchmarkKey] = benchmark.list
    const trimmed = trimAlignedKlineRange(rawSeries, effectiveRange.value)
    compareBars.value = Object.fromEntries(codes.map((code) => [code, trimmed[code] ?? []]))
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
  } catch (error) {
    if (requestVersion !== chartRequestVersion) return
    chartError.value = getErrorMessage(error, '板块走势加载失败')
  } finally {
    if (requestVersion === chartRequestVersion) chartLoading.value = false
  }
}

/** 收起分析区时保留观察对象与对比队列；再次展开后按当前筛选状态刷新走势。 */
function setAnalysisPanelVisible(visible: boolean): void {
  settings.showAnalysisPanel = visible
  if (visible) {
    void loadChart()
    return
  }
  chartRequestVersion += 1
  chartLoading.value = false
}

function isPinned(code: string): boolean {
  return pinnedCodes.value.includes(code)
}
function togglePinned(row: SectorRow, checked: boolean): void {
  if (row.available === false) return
  boardLookup.value = { ...boardLookup.value, [row.board_code]: row }
  if (checked) {
    if (!isPinned(row.board_code)) {
      const capacity = activeCode.value && !isPinned(activeCode.value) ? COMPARE_MAX - 1 : COMPARE_MAX
      pinnedCodes.value = [...pinnedCodes.value, row.board_code].slice(-capacity)
    }
  } else {
    pinnedCodes.value = pinnedCodes.value.filter((code) => code !== row.board_code)
  }
  void loadChart()
}
function removeCompared(code: string): void {
  if (code === activeCode.value) {
    const next = pinnedCodes.value.find((item) => item !== code)
      || rows.value.find((row) => row.available !== false)?.board_code
      || ''
    activeCode.value = next
  }
  pinnedCodes.value = pinnedCodes.value.filter((item) => item !== code)
  void loadChart()
}
function selectRow(row: SectorRow): void {
  if (row.available === false) return
  boardLookup.value = { ...boardLookup.value, [row.board_code]: row }
  if (activeCode.value === row.board_code) return
  activeCode.value = row.board_code
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
    const data = await listSectorWatchlist()
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
    if (removing) await removeSectorWatchlist(row.board_code)
    else await addSectorWatchlist(row.board_code)
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

async function load(): Promise<void> {
  syncSourceQuery()
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
    rows.value = data.list
    total.value = data.total
    marketDate.value = data.trade_date
    fundFlowDate.value = data.fund_flow_date
    boardLookup.value = {
      ...boardLookup.value,
      ...Object.fromEntries(data.list.map((row) => [row.board_code, row])),
    }

    const maxPage = Math.max(1, Math.ceil(data.total / size.value))
    if (page.value > maxPage) {
      page.value = maxPage
      return load()
    }

    // 首屏直接呈现可用走势，避免必须先理解控件才能看到内容。
    const availableRows = data.list.filter((row) => row.available !== false)
    const activeInCurrentList = availableRows.some((row) => row.board_code === activeCode.value)
    if (!activeInCurrentList && availableRows.length) {
      const initialSelection = !activeCode.value
      activeCode.value = availableRows[0]!.board_code
      if (initialSelection) pinnedCodes.value = []
      void loadChart()
    }
  } catch (error) {
    if (getErrorStatus(error) === 403) forbidden.value = true
    loadError.value = getErrorMessage(error, '板块列表加载失败')
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  void load()
}
function changeListScope(): void {
  page.value = 1
  void load()
}
function scheduleSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    search()
  }, 300)
}
function onDateChange(): void {
  if (restoring) return
  search()
  void loadChart()
}

watch([sortBy, sortOrder], () => {
  if (restoring) return
  page.value = 1
  void load()
})
watch(defaultSize, (value) => {
  if (restoring) return
  size.value = value
  page.value = 1
  void load()
})
watch([rangeDays, chartMode, benchmarkCode, compareMetric, compareWindow], () => {
  if (restoring) return
  void loadChart()
})
// 抽屉里把当前指标从展示列表移除时，回退到首个可见指标，保持图与头部一致。
watch(visibleCompareMetrics, (list) => {
  if (restoring) return
  if (list.length && !list.includes(compareMetric.value)) {
    compareMetric.value = list[0]!
  }
})

function sourceQuery() {
  return {
    ...(boardType.value ? { type: boardType.value } : {}),
    ...(sortBy.value !== 'pct_today' ? { sort: sortBy.value } : {}),
    ...(sortOrder.value !== 'desc' ? { order: sortOrder.value } : {}),
    ...(keyword.value.trim() ? { keyword: keyword.value.trim().slice(0, 50) } : {}),
    ...(page.value > 1 ? { page: String(page.value) } : {}),
    ...(listScope.value === 'watchlist' ? { scope: 'watchlist' as const } : {}),
    ...(tradeDate.value ? { date: tradeDate.value } : {}),
  }
}
function syncSourceQuery(): void {
  if (restoring) return
  void router.replace({ path: '/sectors', query: toLocationQuery(sourceQuery()) })
}
function openDetail(): void {
  if (!activeCode.value || activeRow.value?.available === false) return
  void router.push({
    path: `/sectors/${encodeURIComponent(activeCode.value)}`,
    query: toLocationQuery(sourceQuery()),
  })
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}
function fmtInflow(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}亿`
}
function pctClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'muted'
  return value > 0 ? 'up' : value < 0 ? 'down' : ''
}
function fmtFlowDate(value: string | null): string {
  return value ? value.slice(5) : '—'
}

function setAuxiliaryChart(slot: AuxiliaryChartSlot, value: string | number | boolean): void {
  chartPreferences.setSlotType(slot, value)
}

function handleRatioDraft(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
}

function handleRatioCommit(ratios: number[]): void {
  chartPreferences.updateRatioDraft(ratios)
  chartPreferences.commitRatioDraft()
}

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
function sanitizeCompareMetric(value: unknown): CompareMetric {
  const v = String(value ?? '')
  return (COMPARE_METRIC_ORDER as string[]).includes(v) ? (v as CompareMetric) : 'cum'
}
// 切换指标：固定窗口指标（5/10/20日）不反向改动累计涨跌的周期窗口——累计窗口只由周期列表下拉决定。
function selectCompareMetric(metric: CompareMetric): void {
  if (compareMetric.value === metric) return
  compareMetric.value = metric
}

onMounted(async () => {
  await whenHydrated()
  await ensureLoaded().catch(() => undefined)
  const resolved = resolveSectorListState(route.query, settings, canViewWatchlist.value)
  const query = resolved.query
  restoring = true
  if (!tradeDate.value) tradeDate.value = dataMax.value || ''
  boardType.value = resolved.boardType
  listScope.value = resolved.listScope
  chartMode.value = resolved.chartMode
  benchmarkCode.value = resolved.benchmarkCode
  compareMetric.value = sanitizeCompareMetric(settings.defaultCompareMetric)
  // 默认指标若被移出展示列表，回退到首个可见指标，避免图与头部高亮脱节。
  if (!visibleCompareMetrics.value.includes(compareMetric.value)) {
    compareMetric.value = visibleCompareMetrics.value[0] ?? 'cum'
  }
  if (query.date) tradeDate.value = query.date
  keyword.value = resolved.keyword
  page.value = resolved.page
  size.value = defaultSize.value
  if (query.sort) {
    onTableSortChange({
      prop: query.sort,
      order: (query.order ?? 'desc') === 'desc' ? 'descending' : 'ascending',
    })
  }
  restoring = false
  await loadWatchlist()
  void load()
})
</script>

<template>
  <LayoutHost :layout="effective">
    <template #action>
      <div class="lh-action">
        <div class="page-head">
          <div>
            <!-- <div class="page-kicker">MARKET SECTORS</div> -->
            <h2 class="app-page-title page-title-row">
              板块行情
              <HelpTip title="板块行情怎么看？" :width="460" test-id="sectors-help-tip">
                <p><b>涨幅口径</b>：今日涨幅相对上一交易日收盘；5/10/20日涨幅相对对应交易日前收盘，历史不足显示“—”。</p>
                <p><b>资金口径</b>：即时及多日净流入来自资金流快照，单位为亿元；资金快照日可能与行情交易日不同，以净流入表头日期为准。</p>
                <p><b>排行操作</b>：点击列头切换排序；列显隐在页面设置中管理；点击板块行切换当前观察对象。</p>
                <p><b>对比操作</b>：勾选板块加入走势对比，最多 {{ COMPARE_MAX }} 个；收起右侧分析区后可专注查看排行，再次展开会保留当前观察状态。</p>
              </HelpTip>
            </h2>
            <p class="page-subtitle">从强弱排行定位主线，点选板块后在同一视野比较走势。</p>
          </div>
          <PageSettingsTrigger :dirty="isDirty || layoutDirty" @click="settingsOpen = true" />
        </div>

        <el-card shadow="never" class="filter-card">
          <AppControlRow class="filter-row">
            <PageSegmented
              v-if="canViewWatchlist"
              v-model="listScope"
              :options="LIST_SCOPE_OPTIONS"
              aria-label="板块范围"
              test-id="sectors-list-scope"
              size="small"
              tone="primary"
              @update:model-value="changeListScope"
            />
            <PageSegmented
              v-model="boardType"
              :options="TYPE_OPTIONS"
              aria-label="板块类型"
              test-id="sectors-type"
              size="small"
              tone="primary"
              @update:model-value="search"
            />
            <TradeDatePicker
              v-model="tradeDate"
              placeholder="交易日期"
              class="date-picker"
              @update:model-value="onDateChange"
            />
            <el-input
              v-model="keyword"
              placeholder="搜索板块"
              class="keyword-input"
              clearable
              maxlength="50"
              data-testid="sectors-keyword"
              @input="scheduleSearch"
              @clear="search"
              @keyup.enter="search"
            />
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
        v-else-if="loadError && !rows.length"
        state="error"
        title="板块行情加载失败"
        :description="loadError"
        retry
        @retry="load"
      />
      <div
        v-else
        class="sector-workspace"
        :class="{ 'sector-workspace--list-only': !settings.showAnalysisPanel }"
        data-testid="sectors-workspace"
      >
        <section class="rank-panel" aria-label="板块强弱排行">
          <header class="panel-head rank-head">
            <div class="rank-head-primary">
              <div>
                <div class="panel-eyebrow">强弱排行</div>
                <h3 class="app-section-title">{{ marketDate || tradeDate || '最新交易日' }}</h3>
              </div>
            </div>
            <div class="rank-head-actions">
              <div class="rank-meta app-caption-text">
                <span>{{ total }} 个{{ listScope === 'watchlist' ? '自选' : '板块' }}</span>
                <span>{{ settings.showAnalysisPanel ? '点击行切换走势' : '点击行选择板块' }}</span>
              </div>
              <AppIconButton
                :label="settings.showAnalysisPanel ? '收起走势分析，仅看排行' : '显示走势分析'"
                :data-testid="settings.showAnalysisPanel ? 'sectors-hide-analysis' : 'sectors-show-analysis'"
                :native-title="false"
                @click="setAnalysisPanelVisible(!settings.showAnalysisPanel)"
              >
                <el-icon><DArrowRight v-if="settings.showAnalysisPanel" /><DArrowLeft v-else /></el-icon>
              </AppIconButton>
            </div>
          </header>

          <AppStateBlock
            v-if="loadError"
            state="error"
            size="compact"
            title="排行刷新失败"
            :description="loadError"
            retry
            @retry="load"
          />

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
            @size-change="(value: number) => { size = value; page = 1; void load() }"
          >
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
                    :label="`${isWatchlisted(row.board_code) ? '移出' : '加入'}板块自选：${row.name}`"
                    :loading="isWatchlistBusy(row.board_code)"
                    :data-testid="`sectors-watchlist-${row.board_code}`"
                    size="xs"
                    :native-title="false"
                    @click.stop="toggleWatchlist(row)"
                  >
                    <el-icon><StarFilled v-if="isWatchlisted(row.board_code)" /><Star v-else /></el-icon>
                  </AppIconButton>
                  <el-checkbox
                    :disabled="row.available === false"
                    :model-value="isPinned(row.board_code)"
                    :aria-label="`${isPinned(row.board_code) ? '移出' : '加入'}对比：${row.name}`"
                    :data-testid="row?.board_code ? `sectors-pin-${row.board_code}` : undefined"
                    @click.stop
                    @change="(checked: boolean) => togglePinned(row, checked)"
                  />
                  <div class="sector-name-copy">
                    <el-button
                      link
                      type="primary"
                      class="sector-select"
                      :disabled="row.available === false"
                      :data-testid="row?.board_code ? `sectors-name-${row.board_code}` : undefined"
                      @click.stop="selectRow(row)"
                    >
                      {{ row.name }}
                    </el-button>
                    <span v-if="row.available === false">{{ row.board_type === 'concept' ? '概念' : '行业' }} · 已失效</span>
                    <span v-else>{{ row.board_type === 'concept' ? '概念' : '行业' }} · {{ row.member_count ?? '—' }}只</span>
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
              align="right"
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
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.pct_5d)">{{ fmtPct(row.pct_5d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_10d')"
              label="10日涨幅"
              prop="pct_10d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.pct_10d)">{{ fmtPct(row.pct_10d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('pct_20d')"
              label="20日涨幅"
              prop="pct_20d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.pct_20d)">{{ fmtPct(row.pct_20d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow')"
              label="即时净流入"
              prop="net_inflow"
              sortable="custom"
              role="number"
              :header-meta="fmtFlowDate(fundFlowDate)"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.net_inflow)">{{ fmtInflow(row.net_inflow) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_3d')"
              label="3日净流入"
              prop="net_inflow_3d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.net_inflow_3d)">{{ fmtInflow(row.net_inflow_3d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_5d')"
              label="5日净流入"
              prop="net_inflow_5d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.net_inflow_5d)">{{ fmtInflow(row.net_inflow_5d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_10d')"
              label="10日净流入"
              prop="net_inflow_10d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.net_inflow_10d)">{{ fmtInflow(row.net_inflow_10d) }}</span>
              </template>
            </AppTableColumn>
            <AppTableColumn
              v-if="colVisible('net_inflow_20d')"
              label="20日净流入"
              prop="net_inflow_20d"
              sortable="custom"
              role="number"
              align="right"
            >
              <template #default="{ row }">
                <span class="app-data-text" :class="pctClass(row.net_inflow_20d)">{{ fmtInflow(row.net_inflow_20d) }}</span>
              </template>
            </AppTableColumn>
            <template #empty>
              <span v-if="keyword.trim()">没有匹配板块，换个关键词试试</span>
              <span v-else-if="listScope === 'watchlist'">还没有自选板块，请在“全市场”中点击星标添加</span>
              <span v-else>暂无板块数据，请先运行板块采集</span>
            </template>
          </AppDataTable>
        </section>

        <section
          v-if="settings.showAnalysisPanel"
          class="chart-panel"
          aria-label="板块走势分析"
          data-testid="sectors-chart"
        >
          <header class="panel-head chart-head">
            <div class="chart-identity">
              <div class="panel-eyebrow">当前观察</div>
              <div class="chart-title-line">
                <h3 class="chart-title" data-testid="sectors-chart-title">{{ activeRow?.name || '等待选择板块' }}</h3>
                <span v-if="activeRow" class="board-code">{{ activeRow.board_code }}</span>
                <el-button
                  v-if="activeRow"
                  link
                  type="primary"
                  class="detail-link"
                  :disabled="activeRow.available === false"
                  data-testid="sectors-open-detail"
                  @click="openDetail"
                >
                  查看详情
                  <el-icon class="el-icon--right"><ArrowRight /></el-icon>
                </el-button>
              </div>
              <p>
                {{ chartMode === 'compare' ? `与 ${Math.max(0, chartCodes.length - 1)} 个板块对比区间强弱` : '查看板块指数开高低收与量能' }}
                <template v-if="activeRow?.leader_stock">
                  · 领涨 {{ activeRow.leader_stock }}
                  <strong :class="pctClass(activeRow.leader_pct)">{{ fmtPct(activeRow.leader_pct) }}</strong>
                </template>
              </p>
            </div>
            <div class="chart-head-actions">
              <div v-if="chartMode === 'compare' && compareMetricKind === 'line'" class="benchmark-control">
                <span>对比指数</span>
                <AppFilterSelect
                  v-model="benchmarkCode"
                  :options="BENCHMARK_OPTIONS"
                  :multiple="false"
                  :clearable="false"
                  :filterable="false"
                  data-testid="sectors-benchmark"
                />
              </div>
              <KlineRangeSelect v-if="chartMode === 'kline'" v-model="rangeDays" width="112px" test-id="sectors-range" />
              <el-select
                v-else-if="chartMode === 'compare' && compareMetric === 'cum'"
                v-model="compareWindow"
                style="width: 96px"
                data-testid="sectors-compare-range"
              >
                <el-option v-for="o in COMPARE_RANGE_OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
              </el-select>
              <PageSegmented
                v-model="chartMode"
                :options="CHART_MODE_OPTIONS"
                aria-label="图表模式"
                test-id="sectors-chart-mode"
                size="small"
                tone="primary"
              />
            </div>
          </header>

          <div v-if="activeRow" class="market-strip" aria-label="板块对比指标" :style="metricStripStyle">
            <div
              v-for="(metric, index) in visibleCompareMetrics"
              :key="metric"
              class="market-metric"
              :class="{
                'market-metric--active': metric === compareMetric,
                'market-metric--lead': index === 0,
              }"
              role="button"
              tabindex="0"
              :aria-pressed="metric === compareMetric"
              :data-testid="`sectors-metric-${metric}`"
              @click="selectCompareMetric(metric)"
              @keydown.enter="selectCompareMetric(metric)"
            >
              <span>{{ metricSlotLabel(metric) }}</span>
              <strong :class="metricSlot(metric).cls">{{ metricSlot(metric).text }}</strong>
            </div>
          </div>

          <div
            v-if="chartMode === 'compare' && chartCodes.length"
            class="compare-rail"
            aria-label="当前对比板块"
            data-testid="sectors-compare-rail"
          >
            <span class="compare-label">对比队列</span>
            <div
              v-for="row in compareRows"
              :key="row.board_code"
              class="compare-chip"
              :class="{ active: row.board_code === activeCode }"
              :data-testid="`sectors-compare-${row.board_code}`"
              role="button"
              tabindex="0"
              @click="selectRow(row)"
              @keydown.enter="selectRow(row)"
            >
              <span>{{ row.name }}</span>
              <AppIconButton
                v-if="row.board_code !== activeCode || compareRows.length > 1"
                class="chip-remove"
                :label="`移除对比：${row.name}`"
                :data-testid="`sectors-remove-${row.board_code}`"
                size="xs"
                :native-title="false"
                @click.stop="removeCompared(row.board_code)"
              >
                <el-icon><Close /></el-icon>
              </AppIconButton>
            </div>
            <span v-if="chartCodes.length < COMPARE_MAX" class="compare-hint">勾选左侧板块加入，最多 {{ COMPARE_MAX }} 个</span>
          </div>

          <div class="chart-stage" v-loading="chartLoading">
            <AppStateBlock
              v-if="chartError"
              state="error"
              title="板块走势加载失败"
              :description="chartError"
              retry
              @retry="loadChart"
            />
            <AppStateBlock
              v-else-if="!activeCode"
              state="empty"
              title="选择一个板块"
              description="点击左侧排行中的任意一行即可查看走势"
            />
            <AppStateBlock
              v-else-if="!chartLoading && chartMode === 'compare' && compareMetricKind === 'line' && !compareSeries.length"
              state="empty"
              title="暂无指数走势"
              description="可切换其他板块，或先运行板块指数采集"
            />
            <AppStateBlock
              v-else-if="!chartLoading && chartMode === 'compare' && compareMetricKind === 'bar' && !crossSection.length"
              state="empty"
              title="暂无对比数据"
              description="对比队列暂无该指标快照"
            />
            <AppStateBlock
              v-else-if="!chartLoading && chartMode === 'kline' && !klineBars.length"
              state="empty"
              title="暂无 K 线数据"
              description="可切换其他板块，或先运行板块指数采集"
            />
            <SectorCompareChart
              v-else-if="chartMode === 'compare'"
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
              class="sector-kline-workspace"
              :bars="klineBars"
              :indicators="klineIndicators"
              :slot2="chartPreferences.preferences.value.slot2"
              :slot3="chartPreferences.preferences.value.slot3"
              :height-ratios="chartPreferences.currentRatios.value"
              adjust-label="板块指数"
              :min-height="384"
              :zoom-start="0"
              :zoom-end="100"
              aria-label="板块指数多图联动工作区"
              @ratio-draft="handleRatioDraft"
              @ratio-commit="handleRatioCommit"
            />
          </div>

          <footer v-if="chartMode === 'compare'" class="chart-footer">
            <span v-if="benchmarkError && compareMetricKind === 'line'" class="benchmark-warning">{{ benchmarkError }}，当前仅显示板块走势。</span>
            <span v-else-if="compareMetricKind === 'bar' && (compareMetric === 'inflow' || compareMetric === 'breadth')" class="compare-explanation">
              净流入与涨跌家数为最新截面快照，无法回溯，故以柱状对比，不叠加市场指数。
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
      </div>
    </template>

    <template #overlays>
      <PageSettingsDrawer
        v-model="settingsOpen"
        title="板块行情"
        :dirty="isDirty || layoutDirty"
        page-key="sectors"
        :config="drawerConfig"
        :business-visible="true"
        @reset="resetSettings"
      >
        <template #business>
          <StockChartSettingSection
            :slot2="chartPreferences.preferences.value.slot2"
            :slot3="chartPreferences.preferences.value.slot3"
            test-id-prefix="sectors-chart"
            @change="setAuxiliaryChart"
          />
          <PageSettingSection title="默认查询">
            <div v-if="canViewWatchlist" class="setting-item">
              <div class="setting-label">默认板块范围</div>
              <PageSegmented
                v-model="settings.defaultScope"
                :options="LIST_SCOPE_OPTIONS"
                aria-label="默认板块范围"
                test-id="sectors-default-scope"
              />
            </div>
            <div class="setting-item">
              <div class="setting-label">默认类型</div>
              <PageSegmented
                v-model="settings.defaultType"
                :options="TYPE_OPTIONS"
                aria-label="默认类型"
                test-id="sectors-default-type"
              />
            </div>
            <div class="setting-item">
              <div class="setting-label">默认图表模式</div>
              <PageSegmented
                v-model="settings.defaultChartMode"
                :options="CHART_MODE_OPTIONS"
                aria-label="默认图表模式"
                test-id="sectors-default-chart-mode"
              />
            </div>
            <div class="setting-item">
              <div class="setting-label">默认对比指数</div>
              <AppFilterSelect
                v-model="settings.benchmarkCode"
                :options="BENCHMARK_OPTIONS"
                :multiple="false"
                :clearable="false"
                :filterable="false"
              />
            </div>
          </PageSettingSection>
          <PageSettingSection title="对比指标" desc="配置头部对比指标槽展示哪些指标与默认选中口径。">
            <div class="setting-item">
              <div class="setting-label">展示指标</div>
              <el-checkbox-group v-model="settings.compareMetrics" class="compare-metric-checks">
                <el-checkbox
                  v-for="metric in COMPARE_METRIC_ORDER"
                  :key="metric"
                  :value="metric"
                >
                  {{ COMPARE_METRIC_META[metric].label }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
            <div class="setting-item">
              <div class="setting-label">默认对比指标</div>
              <el-select v-model="settings.defaultCompareMetric" style="width: 160px">
                <el-option
                  v-for="metric in COMPARE_METRIC_ORDER"
                  :key="metric"
                  :value="metric"
                  :label="COMPARE_METRIC_META[metric].label"
                />
              </el-select>
            </div>
          </PageSettingSection>
          <KlineSettingSection />
        </template>
      </PageSettingsDrawer>
    </template>
  </LayoutHost>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--app-space-3);
}
.page-title-row {
  display: flex;
  align-items: center;
}
.page-kicker,
.panel-eyebrow {
  color: var(--el-color-primary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
  font-weight: var(--app-font-weight-strong);
  letter-spacing: 0.14em;
}
.page-subtitle {
  margin: var(--app-space-1) 0 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.filter-card {
  margin-bottom: 0;
}
.filter-card :deep(.el-card__body) {
  padding: var(--app-space-3) var(--app-space-4);
}
.filter-row {
  flex-wrap: wrap;
}
.date-picker {
  width: 150px;
}
.keyword-input {
  width: 160px;
}
.sector-workspace {
  height: 100%;
  min-height: 0;
  min-width: 860px;
  display: grid;
  grid-template-columns: minmax(360px, 0.82fr) minmax(500px, 1.18fr);
  gap: var(--app-space-3);
  overflow-x: auto;
}
.sector-workspace--list-only {
  min-width: 640px;
  grid-template-columns: minmax(0, 1fr);
}
.rank-panel,
.chart-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-card-radius);
  background: var(--el-bg-color);
  box-shadow: inset 0 1px 0 color-mix(in srgb, white 18%, transparent);
}
.rank-panel,
.chart-panel {
  display: flex;
  flex-direction: column;
}
.panel-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  padding: var(--app-space-3) var(--app-space-4);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.rank-head {
  min-height: 64px;
  background: color-mix(in srgb, var(--el-color-primary-light-9) 42%, var(--el-bg-color));
}
.rank-head-primary {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}
.rank-head-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}
.rank-meta {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
}
.rank-panel :deep(.app-data-table) {
  flex: 1 1 auto;
  min-height: 0;
}
.rank-panel :deep(.el-table__row.sector-row--active > td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, var(--el-bg-color));
}
.rank-panel :deep(.el-table__row.sector-row--active > td:first-child) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.sector-name-cell {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
}
.watchlist-button {
  color: var(--el-text-color-placeholder);
}
.watchlist-button--active {
  color: var(--el-color-primary);
}
.rank-panel :deep(.el-table__row.sector-row--unavailable > td.el-table__cell) {
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
  font-weight: var(--app-font-weight-section);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sector-select:hover {
  color: var(--el-color-primary-dark-2);
}
.sector-select:focus-visible {
  border-radius: 2px;
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: 1px;
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
.chart-head {
  min-height: 72px;
}
.chart-identity {
  min-width: 0;
}
.chart-title-line {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}
.chart-title {
  overflow: hidden;
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: var(--app-font-size-title-md);
  line-height: var(--app-line-height-title-md);
  font-weight: var(--app-font-weight-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.board-code {
  color: var(--el-text-color-placeholder);
  font-family: var(--app-font-family-mono);
  font-size: var(--app-font-size-micro);
}
.detail-link {
  flex: 0 0 auto;
  height: auto;
  padding: 0;
  font-size: var(--app-font-size-caption);
}
.chart-identity p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  line-height: var(--app-line-height-caption);
}
.chart-identity p strong {
  font-variant-numeric: tabular-nums;
}
.chart-head-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--app-space-2);
}
.benchmark-control {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-caption);
  white-space: nowrap;
}
.benchmark-control :deep(.app-filter-select) {
  width: 124px;
}
.chart-head-actions :deep(.page-segmented) {
  white-space: nowrap;
}
.chart-head-actions :deep(.seg-btn) {
  min-width: 52px;
  font-variant-numeric: tabular-nums;
}
.market-strip {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: repeat(6, minmax(72px, 1fr));
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: color-mix(in srgb, var(--el-fill-color-light) 54%, var(--el-bg-color));
}.market-metric {
  min-width: 0;
  padding: var(--app-space-2) var(--app-space-3);
  border-right: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
  text-align: left;
}
.market-metric:last-child {
  border-right: 0;
}
.market-metric:hover,
.market-metric--active {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 70%, transparent);
}
.market-metric--active {
  box-shadow: inset 0 -2px 0 var(--el-color-primary);
}
.market-metric:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: -2px;
}
.market-metric span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  line-height: var(--app-line-height-micro);
}
.market-metric strong {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  font-size: var(--app-font-size-data);
  line-height: var(--app-line-height-data);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-metric strong i {
  font-style: normal;
}
.market-metric--lead {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 58%, transparent);
}
.market-metric--lead.market-metric--active {
  background: color-mix(in srgb, var(--el-color-primary-light-9) 70%, transparent);
}
.cum-base-row {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-height: 42px;
  padding: var(--app-space-2) var(--app-space-3);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.compare-rail {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-control-gap);
  min-height: 42px;
  padding: var(--app-space-2) var(--app-space-3);
  overflow-x: auto;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}
.compare-label,
.compare-hint {
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
}
.compare-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  height: var(--app-control-height-sm);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--el-border-color);
  border-radius: var(--layout-control-radius);
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  cursor: pointer;
  font: inherit;
  font-size: var(--app-font-size-caption);
}
.compare-chip:hover,
.compare-chip.active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.compare-chip:focus-visible {
  outline: 2px solid var(--el-color-primary-light-5);
  outline-offset: 1px;
}
.chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  --app-icon-button-size: 18px;
  --app-icon-button-glyph: 11px;
  border-radius: 50%;
  color: var(--el-text-color-secondary);
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
.setting-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}
.setting-label {
  color: var(--page-settings-text-subtle);
  font-size: var(--app-font-size-body);
}
.up {
  color: var(--market-up-color);
}
.down {
  color: var(--market-down-color);
}
.muted {
  color: var(--app-placeholder-text);
}
@media (max-width: 1180px) {
  .page-subtitle {
    display: none;
  }
  .chart-identity p {
    display: none;
  }
  .market-strip {
    grid-template-columns: repeat(3, minmax(84px, 1fr));
  }
}
@media (max-height: 700px) {
  .market-strip {
    display: none;
  }
  .chart-head {
    min-height: 60px;
  }
  .chart-footer {
    min-height: 36px;
    padding-block: var(--app-space-1);
  }
}
@media (prefers-reduced-motion: reduce) {
  .compare-chip {
    transition: none;
  }
}
</style>
