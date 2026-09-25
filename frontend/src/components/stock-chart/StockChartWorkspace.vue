<script setup lang="ts">
import {
  computed,
  inject,
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  provide,
  ref,
  watch,
} from 'vue'
import * as echarts from 'echarts'
import { Operation } from '@element-plus/icons-vue'
import type { Bar, IndicatorRow } from '@/api/stocks'
import AppIconButton from '@/components/AppIconButton.vue'
import ChartOperationGroup from '@/components/ChartOperationGroup.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import AppStateBlock from '@/components/AppStateBlock.vue'
import { useStatusColorPalette } from '@/components/chartTheme'
import { initVectorEChart } from '@/components/echartsRenderer'
import type { StockAdjustMode } from '@/composables/useStockAnalysisSession'
import type { AuxiliaryChartType, ChartType } from '@/composables/useStockChartPreferences'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'
import { WORKSPACE_RESIZE_ACTIVE } from '@/layout/workspaceResizeContext'
import { elementVisualScale } from '@/utils/displayScaleGeometry'
import { createLatestAnimationFrame } from '@/utils/latestAnimationFrame'
import { formatMarketPercent, marketValueClass } from '@/utils/marketValue'
import StockChartPanelDivider from './StockChartPanelDivider.vue'
import StockChartPanelHeader from './StockChartPanelHeader.vue'
import StockChartLegend from './StockChartLegend.vue'
import type { StockChartLegendItem } from './StockChartLegend.vue'
import StockChartOperationsDrawer from './StockChartOperationsDrawer.vue'
import type { StockQuoteSupplement, StockQuoteTone } from './stockQuoteSummary'
import {
  KLINE_MA_DEFINITIONS,
  STOCK_CHART_GRID_SIDE,
  STOCK_CHART_GRID_TOP,
  VOLUME_MA_DEFINITIONS,
  nextStockChartWorkspaceGroupId,
  stockChartAxisPointerIndex,
} from './chartUtils'
import { useStockChartTheme } from './useStockChartTheme'
import {
  KLINE_PERIOD_OPTIONS,
  buildKlinePeriodSeries,
  tradingDaysBetween,
  type KlinePeriod,
  type PeriodBar,
} from './klinePeriod'
import {
  KEYBOARD_RATIO_STEP,
  SPLITTER_SIZE,
  WORKSPACE_MIN_HEIGHT,
  adjustAdjacentRatios,
  alignStockChartRows,
  buildKlineOption,
  buildMacdOption,
  buildVolumeOption,
  constrainWorkspaceRatios,
  klineMetrics,
  macdMetrics,
  normalizeWorkspaceRatios,
  panelMetricColor,
  panelMinHeight,
  panelTitle,
  stockChartWorkspaceMinHeight,
  stockChartVisibleSlider,
  volumeMetrics,
  type MacdPanelState,
  type TradeMarker,
  type WorkspacePanelKey,
  type StockChartWorkspaceSample,
} from './workspaceOptions'

interface PanelDescriptor {
  key: WorkspacePanelKey
  type: ChartType
}

interface Metric {
  label: string
  value: string
}

function metricMarker(type: ChartType, label: string): 'line' | 'bar' {
  return (type === 'macd' && label === 'MACD') || (type === 'volume' && label === '总量')
    ? 'bar'
    : 'line'
}

function panelLegendItems(type: ChartType): StockChartLegendItem[] {
  return panelMetrics(type).map((metric) => ({
    key: metric.label,
    label: metric.label,
    value: metric.value,
    color: metricColor(type, metric),
    marker: metricMarker(type, metric.label),
  }))
}

interface ZoomRange {
  start: number
  end: number
}

interface DataZoomEvent {
  start?: number
  end?: number
  batch?: Array<{ start?: number; end?: number }>
}

type MeasurementMode = 'latest' | 'range'

const MEASUREMENT_MODE_OPTIONS: Array<{ label: string; value: MeasurementMode }> = [
  { label: '截止', value: 'latest' },
  { label: '区间', value: 'range' },
]

const ADJUST_MODE_OPTIONS: Array<{ label: string; value: StockAdjustMode }> = [
  { label: '不复权', value: '' },
  { label: '前复权', value: 'qfq' },
  { label: '后复权', value: 'hfq' },
]

const props = withDefaults(defineProps<{
  bars: Bar[]
  warmupBars?: Bar[]
  indicators?: IndicatorRow[]
  /** 后端指标所属 K 线周期；切换请求完成前不把旧周期数值对齐到新周期。 */
  indicatorsPeriod?: KlinePeriod
  markers?: TradeMarker[]
  slot2?: AuxiliaryChartType
  slot3?: AuxiliaryChartType
  heightRatios?: number[]
  adjustLabel?: string
  /** MACD 可使用独立于 K 线行情的计算口径；未传时沿用行情口径。 */
  macdAdjustLabel?: string
  macdState?: MacdPanelState
  macdError?: string
  zoomStart?: number
  zoomEnd?: number
  minHeight?: number
  fitAvailableHeight?: boolean
  ariaLabel?: string
  enableIntradayDrilldown?: boolean
  showKlineTooltip?: boolean
  enableReturnMeasurement?: boolean
  returnMeasurementMode?: MeasurementMode
  enableKlinePeriodSwitch?: boolean
  klinePeriod?: KlinePeriod
  enableAdjustModeSwitch?: boolean
  adjustMode?: StockAdjustMode
}>(), {
  warmupBars: () => [],
  indicators: () => [],
  indicatorsPeriod: 'day',
  markers: () => [],
  slot2: 'volume',
  slot3: 'macd',
  heightRatios: () => [0.6, 0.2, 0.2],
  adjustLabel: '前复权',
  macdState: 'ready',
  macdError: '请检查网络或稍后重试',
  zoomStart: 0,
  zoomEnd: 100,
  fitAvailableHeight: false,
  ariaLabel: '行情多图联动工作区',
  enableIntradayDrilldown: false,
  showKlineTooltip: true,
  enableReturnMeasurement: false,
  returnMeasurementMode: 'latest',
  enableKlinePeriodSwitch: false,
  klinePeriod: 'day',
  enableAdjustModeSwitch: false,
  adjustMode: 'qfq',
})

const emit = defineEmits<{
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
  retryMacd: []
  barClick: [tradeDate: string]
  activeBarChange: [bar: Bar | null]
  measurementSummaryChange: [summary: StockQuoteSupplement | null]
  workspaceResize: [sample: StockChartWorkspaceSample | undefined]
  'update:returnMeasurementMode': [mode: MeasurementMode]
  'update:klinePeriod': [period: KlinePeriod]
  'update:adjustMode': [mode: StockAdjustMode]
}>()

defineSlots<{
  'header-actions'?: () => unknown
  'operation-actions'?: () => unknown
}>()

const groupId = nextStockChartWorkspaceGroupId()
const workspaceEl = ref<HTMLElement | null>(null)
provide(PAGE_OVERLAY_TARGET, workspaceEl)
const ancestorWorkspaceResizeActive = inject(WORKSPACE_RESIZE_ACTIVE, ref(false))
const chartElements = new Map<WorkspacePanelKey, HTMLElement>()
const charts = new Map<WorkspacePanelKey, echarts.ECharts>()
const theme = useStockChartTheme()
const statusPalette = useStatusColorPalette()
const activeIndex = ref<number | null>(null)
const klinePointerInside = ref(false)
const measurementMode = ref<MeasurementMode>(props.returnMeasurementMode)
const selectedPeriod = ref<KlinePeriod>(props.klinePeriod)
const selectedAdjustMode = ref<StockAdjustMode>(props.adjustMode)
const operationsDrawerOpen = ref(false)
const operationsTrigger = ref<HTMLElement | null>(null)
const rangeStartIndex = ref<number | null>(null)
const rangeEndIndex = ref<number | null>(null)
const liveRatios = ref<number[]>([])
const zoomRange = ref<ZoomRange>(normalizeZoomRange(props.zoomStart, props.zoomEnd))
const workspaceHeight = ref(0)
let resizeObserver: ResizeObserver | null = null
let active = true
let activationTimer: number | null = null
const ACTIVATION_RETRY_LIMIT = 12
const activationLoading = ref(false)
let bottomSliderVisible: boolean | undefined
let lastDisplayScale = 0
let lastWorkspaceState = ''
let workspaceReportedAvailable = false
let connectedChartSignature = ''
let deferredWorkspaceResize = false
let settledWorkspaceResizeScheduled = false
let dragChartResizeScheduled = false

const panels = computed<PanelDescriptor[]>(() => {
  const next: PanelDescriptor[] = [{ key: 'kline', type: 'kline' }]
  if (props.slot2 !== 'hidden') next.push({ key: 'slot2', type: props.slot2 })
  if (props.slot3 !== 'hidden') next.push({ key: 'slot3', type: props.slot3 })
  return next
})
const effectiveMinHeight = computed(() => {
  const panelFloor = stockChartWorkspaceMinHeight(
    panels.value.map((panel) => panel.type),
    props.fitAvailableHeight,
  )
  const requested = Number(props.minHeight)
  const fallback = props.fitAvailableHeight ? 0 : WORKSPACE_MIN_HEIGHT
  return Math.max(
    panelFloor,
    Number.isFinite(requested) && requested > 0 ? requested : fallback,
  )
})
const effectivePeriod = computed<KlinePeriod>(() => (
  props.enableKlinePeriodSwitch ? selectedPeriod.value : 'day'
))
const effectiveAdjustLabel = computed(() => {
  if (!props.enableAdjustModeSwitch) return props.adjustLabel
  if (selectedAdjustMode.value === 'hfq') return '后复权'
  if (selectedAdjustMode.value === 'qfq') return '前复权'
  return '不复权'
})
const effectiveIndicators = computed(() => (
  props.indicatorsPeriod === effectivePeriod.value ? props.indicators : []
))
const periodSeries = computed(() => buildKlinePeriodSeries(
  props.bars,
  props.warmupBars,
  effectiveIndicators.value,
  effectivePeriod.value,
))
const rows = computed(() => alignStockChartRows(
  periodSeries.value.bars,
  periodSeries.value.indicators,
))
const ratios = computed(() => constrainWorkspaceRatios(
  liveRatios.value.length ? liveRatios.value : props.heightRatios,
  minimumRatios(),
))
const lastIndex = computed(() => Math.max(0, rows.value.length - 1))
const metricIndex = computed(() => activeIndex.value ?? lastIndex.value)

const measurementIndices = computed<[number, number] | null>(() => {
  if (!props.enableReturnMeasurement || !rows.value.length) return null
  if (measurementMode.value === 'latest') {
    return activeIndex.value == null ? null : [activeIndex.value, lastIndex.value]
  }
  if (rangeStartIndex.value == null) return null
  const candidateEnd = rangeEndIndex.value ?? activeIndex.value
  if (candidateEnd == null) return null
  return rangeStartIndex.value <= candidateEnd
    ? [rangeStartIndex.value, candidateEnd]
    : [candidateEnd, rangeStartIndex.value]
})

const measurementChartRange = computed(() => {
  if (measurementMode.value !== 'range' || !measurementIndices.value) return null
  return {
    startIndex: measurementIndices.value[0],
    endIndex: measurementIndices.value[1],
  }
})

function measurementReturnFor(indices: [number, number] | null): number | null {
  if (!indices) return null
  const [startIndex, endIndex] = indices
  const startClose = rows.value[startIndex]?.bar.close
  const endClose = rows.value[endIndex]?.bar.close
  if (
    startClose == null
    || endClose == null
    || !Number.isFinite(startClose)
    || !Number.isFinite(endClose)
    || startClose <= 0
  ) return null
  return ((endClose / startClose) - 1) * 100
}

const measurementHintVisible = computed(() => (
  props.enableReturnMeasurement
  && rows.value.length > 0
  && klinePointerInside.value
  && measurementMode.value === 'range'
))
const chartOperationsVisible = computed(() => (
  (props.enableReturnMeasurement || props.enableAdjustModeSwitch)
  && rows.value.length > 0
))

const measurementHint = computed(() => {
  if (rangeStartIndex.value == null) {
    return { headline: '自选区间', note: '点击 K 线选择起点' }
  }
  if (rangeEndIndex.value == null) {
    const start = rows.value[rangeStartIndex.value]?.bar.date
    return {
      headline: start ? `${start}起` : '自选区间',
      note: '移动到终点后再次点击',
    }
  }
  const [startIndex, endIndex] = measurementIndices.value!
  const start = rows.value[startIndex]?.bar.date
  const end = rows.value[endIndex]?.bar.date
  return {
    headline: start && end ? `${start} → ${end}` : '自选区间',
    note: '点击 K 线重新选择起点',
  }
})

function measurementIndicesAt(index: number): [number, number] | null {
  if (measurementMode.value === 'latest') return [index, lastIndex.value]
  if (rangeStartIndex.value == null) return null
  const candidateEnd = rangeEndIndex.value ?? index
  return rangeStartIndex.value <= candidateEnd
    ? [rangeStartIndex.value, candidateEnd]
    : [candidateEnd, rangeStartIndex.value]
}

function measurementToneOf(value: number | null): StockQuoteTone {
  const tone = marketValueClass(value)
  return tone === 'up' || tone === 'down' ? tone : 'neutral'
}

function measurementSupplementAt(index: number): StockQuoteSupplement | null {
  if (!props.enableReturnMeasurement || !rows.value[index]) return null
  const indices = measurementIndicesAt(index)
  if (!indices) return null
  const [startIndex, endIndex] = indices
  const start = rows.value[startIndex]?.bar.date
  const end = rows.value[endIndex]?.bar.date
  if (!start || !end) return null
  const value = measurementReturnFor(indices)
  const days = tradingDaysBetween(periodSeries.value.bars, startIndex, endIndex)
  return measurementMode.value === 'latest'
    ? {
        label: `截止 ${end}`,
        value: formatMarketPercent(value),
        tone: measurementToneOf(value),
        details: [{ label: '交易日', value: `${days}个交易日` }],
      }
    : {
        label: '区间涨跌',
        value: formatMarketPercent(value),
        tone: measurementToneOf(value),
        details: [
          { label: '区间', value: `${start} → ${end}` },
          { label: '交易日', value: `${days}个交易日` },
        ],
      }
}

const activeMeasurementSupplement = computed(() => (
  klinePointerInside.value && activeIndex.value != null
    ? measurementSupplementAt(activeIndex.value)
    : null
))

function panelDisplayTitle(type: ChartType): string {
  return panelTitle(type, effectiveAdjustLabel.value, props.macdAdjustLabel)
}

function panelMetrics(type: ChartType): Metric[] {
  if (!rows.value.length) {
    if (type === 'kline') {
      return KLINE_MA_DEFINITIONS.map(({ label }) => ({ label, value: '--' }))
    }
    if (type === 'volume') {
      return [
        { label: '总量', value: '--' },
        ...VOLUME_MA_DEFINITIONS.map(({ label }) => ({ label, value: '--' })),
      ]
    }
    return ['MACD', 'DIFF', 'DEA'].map((label) => ({ label, value: '--' }))
  }
  if (type === 'kline') {
    return klineMetrics(rows.value, periodSeries.value.warmupBars, metricIndex.value)
  }
  if (type === 'volume') {
    return volumeMetrics(rows.value, periodSeries.value.warmupBars, metricIndex.value)
  }
  if (effectivePeriod.value === 'day' && props.macdState !== 'ready') {
    return ['MACD', 'DIFF', 'DEA'].map((label) => ({ label, value: '--' }))
  }
  return macdMetrics(rows.value, metricIndex.value)
}

function metricColor(type: ChartType, metric: Metric): string {
  const macdValue = rows.value[metricIndex.value]?.indicator?.macd_hist
  return panelMetricColor(theme.value, type, metric.label, macdValue)
}

function setChartElement(key: WorkspacePanelKey, element: unknown): void {
  const previous = chartElements.get(key)
  if (previous === element) return
  if (previous && previous !== element) resizeObserver?.unobserve(previous)
  const chart = charts.get(key)
  if (chart && !chart.isDisposed() && chart.getDom() !== element) {
    chart.dispose()
    charts.delete(key)
    if (connectedChartSignature) echarts.disconnect(groupId)
    connectedChartSignature = ''
  }
  if (element instanceof HTMLElement) {
    chartElements.set(key, element)
    resizeObserver?.observe(element)
  } else {
    chartElements.delete(key)
  }
}

function chartOption(panel: PanelDescriptor, isBottom: boolean) {
  const chart = charts.get(panel.key)
  const panelHeight = chartElements.get(panel.key)?.clientHeight
  if (isBottom) bottomSliderVisible = stockChartVisibleSlider(panelHeight)
  const candlestickRect = (params: unknown) => {
    if (!chart || chart.isDisposed()) return null
    const items = Array.isArray(params) ? params : [params]
    const item = items.find((entry) => (
      (entry as { seriesType?: string })?.seriesType === 'candlestick'
    )) as { dataIndex?: number } | undefined
    if (typeof item?.dataIndex !== 'number') return null
    const bar = rows.value[item.dataIndex]?.bar
    if (!bar) return null
    const highPoint = chart.convertToPixel(
      { xAxisIndex: 0, yAxisIndex: 0 },
      [item.dataIndex, bar.high],
    )
    const lowPoint = chart.convertToPixel(
      { xAxisIndex: 0, yAxisIndex: 0 },
      [item.dataIndex, bar.low],
    )
    if (!Array.isArray(highPoint) || !Array.isArray(lowPoint)) return null
    if (![highPoint[0], highPoint[1], lowPoint[1]].every(Number.isFinite)) return null
    return {
      x: Number(highPoint[0]) - 9,
      y: Math.min(Number(highPoint[1]), Number(lowPoint[1])),
      width: 18,
      height: Math.max(1, Math.abs(Number(lowPoint[1]) - Number(highPoint[1]))),
    }
  }
  const context = {
    rows: rows.value,
    warmupBars: periodSeries.value.warmupBars,
    theme: theme.value,
    isBottom,
    panelHeight,
    zoomStart: zoomRange.value.start,
    zoomEnd: zoomRange.value.end,
    markers: props.markers,
    buyMarkerColor: statusPalette.value.primary,
    sellMarkerColor: statusPalette.value.warning,
    clickableCandles: props.enableIntradayDrilldown && effectivePeriod.value === 'day',
    showKlineTooltip: props.showKlineTooltip,
    measurementRange: measurementChartRange.value,
    measurementSupplementAt,
    candlestickRect,
    displayScale: elementVisualScale(chartElements.get(panel.key), 'x'),
  }
  if (panel.type === 'kline') return buildKlineOption(context)
  if (panel.type === 'volume') return buildVolumeOption(context)
  return buildMacdOption(context)
}

function onChartClick(event: { seriesType?: string; dataIndex?: number }): void {
  // 自选区间由整个绘图区接管，避免细蜡烛或均线遮挡导致难以点中。
  if (props.enableReturnMeasurement && measurementMode.value === 'range') return
  if (
    !props.enableIntradayDrilldown
    || effectivePeriod.value !== 'day'
    || event.seriesType !== 'candlestick'
  ) return
  if (typeof event.dataIndex !== 'number') return
  const tradeDate = rows.value[event.dataIndex]?.bar.date
  if (tradeDate) emit('barClick', tradeDate)
}

function selectMeasurementIndex(index: number): void {
  if (rangeStartIndex.value == null || rangeEndIndex.value != null) {
    rangeStartIndex.value = index
    rangeEndIndex.value = null
  } else {
    const start = Math.min(rangeStartIndex.value, index)
    const end = Math.max(rangeStartIndex.value, index)
    rangeStartIndex.value = start
    rangeEndIndex.value = end
  }
  refreshKlineChart()
}

function onKlineCanvasClick(
  chart: echarts.ECharts,
  event: { offsetX?: number; offsetY?: number },
): void {
  if (
    !props.enableReturnMeasurement
    || measurementMode.value !== 'range'
    || activeIndex.value == null
    || typeof event.offsetX !== 'number'
    || typeof event.offsetY !== 'number'
    || !chart.containPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY])
  ) return
  selectMeasurementIndex(activeIndex.value)
}

function onAxisPointer(event: {
  axesInfo?: Array<{ value?: string | number }>
  seriesDataIndices?: Array<{ dataIndex?: number }>
}): void {
  const index = stockChartAxisPointerIndex(event, rows.value.map((row) => row.bar.date))
  if (index == null || index === activeIndex.value) return
  activeIndex.value = index
  const activeBar = rows.value[index]?.bar
  if (!activeBar) {
    emit('activeBarChange', null)
  } else if (effectivePeriod.value === 'day') {
    const {
      periodStartDate: _periodStartDate,
      periodEndDate: _periodEndDate,
      tradingDayCount: _tradingDayCount,
      ...dailyBar
    } = activeBar as PeriodBar
    emit('activeBarChange', dailyBar)
  } else {
    emit('activeBarChange', activeBar)
  }
  if (
    measurementMode.value === 'range'
    && rangeStartIndex.value != null
    && rangeEndIndex.value == null
  ) refreshKlineChart()
}

function clearActiveBar(): void {
  if (activeIndex.value == null) return
  activeIndex.value = null
  emit('activeBarChange', null)
  if (
    measurementMode.value === 'range'
    && rangeStartIndex.value != null
    && rangeEndIndex.value == null
  ) refreshKlineChart()
}

function refreshKlineChart(): void {
  const chart = charts.get('kline')
  if (!chart || chart.isDisposed()) return
  chart.setOption(chartOption({ key: 'kline', type: 'kline' }, panels.value.length === 1), true)
}

function setMeasurementMode(value: string | number | boolean): void {
  if (value !== 'latest' && value !== 'range') return
  measurementMode.value = value
  emit('update:returnMeasurementMode', value)
  rangeStartIndex.value = null
  rangeEndIndex.value = null
  refreshKlineChart()
}

function setKlinePeriod(value: string | number | boolean): void {
  if (value !== 'day' && value !== 'week' && value !== 'month' && value !== 'year') return
  if (value === selectedPeriod.value) return
  selectedPeriod.value = value
  emit('update:klinePeriod', value)
  activeIndex.value = null
  rangeStartIndex.value = null
  rangeEndIndex.value = null
  emit('activeBarChange', null)
  zoomRange.value = normalizeZoomRange(props.zoomStart, props.zoomEnd)
}

function setAdjustMode(value: string | number | boolean): void {
  if (value !== '' && value !== 'qfq' && value !== 'hfq') return
  if (value === selectedAdjustMode.value) return
  selectedAdjustMode.value = value
  emit('update:adjustMode', value)
}

function openOperationsDrawer(event: MouseEvent): void {
  operationsTrigger.value = event.currentTarget as HTMLElement | null
  operationsDrawerOpen.value = true
}

function restoreOperationsTriggerFocus(): void {
  operationsTrigger.value?.focus()
}

function enterKlinePanel(): void {
  if (props.enableReturnMeasurement) klinePointerInside.value = true
}

function leaveKlinePanel(): void {
  klinePointerInside.value = false
}

function normalizeZoomRange(start: number, end: number): ZoomRange {
  const safeStart = Number.isFinite(start) ? Math.min(100, Math.max(0, start)) : 0
  const safeEnd = Number.isFinite(end) ? Math.min(100, Math.max(0, end)) : 100
  return safeStart <= safeEnd
    ? { start: safeStart, end: safeEnd }
    : { start: safeEnd, end: safeStart }
}

function sameZoomRange(left: ZoomRange, right: ZoomRange): boolean {
  return left.start === right.start && left.end === right.end
}

function onDataZoom(sourceKey: WorkspacePanelKey, event: DataZoomEvent): void {
  const payload = event.batch?.[0] ?? event
  if (typeof payload.start !== 'number' || typeof payload.end !== 'number') return
  const next = normalizeZoomRange(payload.start, payload.end)
  if (sameZoomRange(zoomRange.value, next)) return

  zoomRange.value = next
  charts.forEach((chart, key) => {
    if (key === sourceKey || chart.isDisposed()) return
    // 独立 ECharts 实例的 connect 在部分运行时不会转发 dataZoom，显式广播保证三图同窗。
    chart.dispatchAction({
      type: 'dataZoom',
      start: next.start,
      end: next.end,
    })
  })
}

function connectCharts(): void {
  const signature = active && charts.size >= 2
    ? [...charts.keys()].sort().join('|')
    : ''
  if (signature === connectedChartSignature) return
  if (connectedChartSignature) echarts.disconnect(groupId)
  connectedChartSignature = signature
  if (!signature) return
  charts.forEach((chart) => { chart.group = groupId })
  echarts.connect(groupId)
}

function hasRenderableSize(element: HTMLElement): boolean {
  return element.clientWidth > 0 && element.clientHeight > 0
}

function hasReadyVisibleCharts(): boolean {
  return panels.value.every((panel) => {
    const element = chartElements.get(panel.key)
    const chart = charts.get(panel.key)
    return Boolean(
      element
      && hasRenderableSize(element)
      && chart
      && !chart.isDisposed()
      && chart.getDom() === element,
    )
  })
}

function syncCharts(): void {
  if (!active) return
  lastDisplayScale = elementVisualScale(workspaceEl.value, 'x')
  const visibleKeys = new Set(panels.value.map((panel) => panel.key))
  charts.forEach((chart, key) => {
    const element = chartElements.get(key)
    if (visibleKeys.has(key) && element && chart.getDom() === element) return
    chart.dispose()
    charts.delete(key)
    if (connectedChartSignature) echarts.disconnect(groupId)
    connectedChartSignature = ''
  })

  panels.value.forEach((panel, index) => {
    const element = chartElements.get(panel.key)
    if (!element) return
    let chart = charts.get(panel.key)
    if (!chart || chart.isDisposed()) {
      // KeepAlive 切换期间 DOM 可能已隐藏但 onDeactivated 尚未执行；禁止在 0×0 容器初始化，
      // 等 ResizeObserver 收到可见尺寸后再补建，避免 ECharts 告警和无效实例。
      if (!hasRenderableSize(element)) return
      chart = initVectorEChart(element)
      chart.on('updateAxisPointer', (event: unknown) => {
        onAxisPointer(event as Parameters<typeof onAxisPointer>[0])
      })
      chart.on('datazoom', (event: unknown) => {
        onDataZoom(panel.key, event as DataZoomEvent)
      })
      chart.on('globalout', clearActiveBar)
      if (panel.type === 'kline') {
        const klineChart = chart
        chart.on('click', onChartClick)
        chart.getZr().on('click', (event) => onKlineCanvasClick(klineChart, event))
      }
      charts.set(panel.key, chart)
    }
    chart.group = groupId
    chart.setOption(chartOption(panel, index === panels.value.length - 1), true)
  })
  connectCharts()
  resizeCharts()
}

function resizeCharts(): void {
  charts.forEach((chart) => {
    if (!chart.isDisposed()) chart.resize()
  })
}

function onWorkspaceResize(): void {
  if (!active) return
  const width = workspaceEl.value?.clientWidth ?? 0
  const height = workspaceEl.value?.clientHeight ?? 0
  workspaceHeight.value = height
  const effectiveRatios = ratios.value.map((value) => Number(value.toFixed(6)))
  const effectiveMinimumRatios = minimumRatios()
    .map((value) => Number(value.toFixed(6)))
  const signature = [
    width,
    height,
    effectiveRatios.join(':'),
    effectiveMinimumRatios.join(':'),
  ].join('|')
  if (width > 0 && height > 0 && signature !== lastWorkspaceState) {
    lastWorkspaceState = signature
    workspaceReportedAvailable = true
    emit('workspaceResize', {
      width,
      height,
      ratios: effectiveRatios,
      minimumRatios: effectiveMinimumRatios,
    })
  }
  if (drag || ancestorWorkspaceResizeActive.value) {
    deferredWorkspaceResize = true
    return
  }
  deferredWorkspaceResize = false
  // 高度变化会先更新面板最低比例；等待 DOM 完成重排后再让画布读取最终尺寸。
  void nextTick(() => {
    if (!active) return
    const hasPendingVisibleChart = panels.value.some((panel) => {
      const element = chartElements.get(panel.key)
      const chart = charts.get(panel.key)
      return Boolean(element && hasRenderableSize(element) && (!chart || chart.isDisposed()))
    })
    if (hasPendingVisibleChart) {
      syncCharts()
      if (hasReadyVisibleCharts()) activationLoading.value = false
      return
    }
    resizeCharts()
    if (hasReadyVisibleCharts()) activationLoading.value = false
    const nextDisplayScale = elementVisualScale(workspaceEl.value, 'x')
    if (drag) {
      // ResizeObserver 已处于布局完成后的读取阶段，可安全刷新跨屏缩放与可用高度基准。
      drag.visualScale = nextDisplayScale
      drag.availableHeight = availableHeight()
      drag.minimumRatios = minimumRatios()
    }
    if (Math.abs(nextDisplayScale - lastDisplayScale) > 0.001) {
      lastDisplayScale = nextDisplayScale
      panels.value.forEach((panel, index) => {
        const chart = charts.get(panel.key)
        if (!chart || chart.isDisposed()) return
        chart.setOption(chartOption(panel, index === panels.value.length - 1), true)
      })
    }
    const bottomPanel = panels.value.at(-1)
    const bottomElement = bottomPanel ? chartElements.get(bottomPanel.key) : undefined
    const nextSliderVisible = stockChartVisibleSlider(bottomElement?.clientHeight)
    if (!bottomPanel || nextSliderVisible === bottomSliderVisible) return
    const chart = charts.get(bottomPanel.key)
    if (!chart || chart.isDisposed()) return
    chart.setOption(chartOption(bottomPanel, true), true)
  })
}

function scheduleSettledWorkspaceResize(): void {
  deferredWorkspaceResize = true
  if (settledWorkspaceResizeScheduled) return
  settledWorkspaceResizeScheduled = true
  void nextTick(() => {
    settledWorkspaceResizeScheduled = false
    if (!active || drag || ancestorWorkspaceResizeActive.value || !deferredWorkspaceResize) return
    onWorkspaceResize()
  })
}

function reportWorkspaceUnavailable(): void {
  lastWorkspaceState = ''
  if (!workspaceReportedAvailable) return
  workspaceReportedAvailable = false
  emit('workspaceResize', undefined)
}

function disposeCharts(): void {
  echarts.disconnect(groupId)
  connectedChartSignature = ''
  charts.forEach((chart) => chart.dispose())
  charts.clear()
  bottomSliderVisible = undefined
}

function observeResize(): void {
  if (!workspaceEl.value || resizeObserver) return
  workspaceHeight.value = workspaceEl.value.clientHeight
  onWorkspaceResize()
  resizeObserver = new ResizeObserver(onWorkspaceResize)
  resizeObserver.observe(workspaceEl.value)
  chartElements.forEach((element) => resizeObserver?.observe(element))
}

function stopObservingResize(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
}

function cancelDeferredActivation(): void {
  if (activationTimer === null) return
  window.clearTimeout(activationTimer)
  activationTimer = null
}

function scheduleActivationRestore(attempt = 0): void {
  cancelDeferredActivation()
  activationTimer = window.setTimeout(() => {
    activationTimer = null
    if (!active) {
      activationLoading.value = false
      return
    }
    syncCharts()
    observeResize()
    if (hasReadyVisibleCharts()) {
      activationLoading.value = false
      return
    }
    // KeepAlive 恢复时父级工作区可能仍处于 0×0；跨短帧补试，避免完全依赖一次
    // ResizeObserver 通知。超过上限后继续保留加载态，由真实尺寸通知完成恢复。
    if (attempt < ACTIVATION_RETRY_LIMIT) scheduleActivationRestore(attempt + 1)
  }, attempt === 0 ? 0 : 16)
}

function availableHeight(): number {
  const height = workspaceHeight.value || workspaceEl.value?.clientHeight || effectiveMinHeight.value
  return Math.max(
    panels.value.reduce((total, panel) => total + panelMinimumHeight(panel.type), 0),
    height - (panels.value.length - 1) * SPLITTER_SIZE,
  )
}

function panelMinimumHeight(type: ChartType): number {
  return panelMinHeight(type, props.fitAvailableHeight)
}

function minimumRatios(): number[] {
  // 最低像素高度必须投影到当前真实空间；用声明下限会在成长型容器中把比例永久锁死。
  const available = availableHeight()
  return panels.value.map((panel) => panelMinimumHeight(panel.type) / available)
}

function panelStyle(panel: PanelDescriptor, index: number) {
  return {
    flexGrow: ratios.value[index],
    flexBasis: '0px',
    minHeight: `${panelMinimumHeight(panel.type)}px`,
  }
}

interface DragState {
  pointerId: number
  separatorIndex: number
  startY: number
  startRatios: number[]
  minimumRatios: number[]
  availableHeight: number
  visualScale: number
  committed: boolean
}

let drag: DragState | null = null

const ratioFrame = createLatestAnimationFrame<{ separatorIndex: number; delta: number }>(
  ({ separatorIndex, delta }) => { applyRatioChange(separatorIndex, delta) },
)

function scheduleDraggedChartsResize(): void {
  if (dragChartResizeScheduled) return
  dragChartResizeScheduled = true
  void nextTick(() => {
    dragChartResizeScheduled = false
    if (!active || !drag) return
    const adjacentPanels = panels.value.slice(drag.separatorIndex, drag.separatorIndex + 2)
    adjacentPanels.forEach((panel) => {
      const chart = charts.get(panel.key)
      if (!chart || chart.isDisposed()) return
      chart.resize()
    })
  })
}

function applyRatioChange(separatorIndex: number, delta: number): number[] {
  const next = adjustAdjacentRatios(
    drag?.startRatios ?? ratios.value,
    separatorIndex,
    delta,
    drag?.minimumRatios ?? minimumRatios(),
  )
  liveRatios.value = next
  emit('ratioDraft', [...next])
  if (drag) scheduleDraggedChartsResize()
  return next
}

function onPointerMove(event: PointerEvent): void {
  if (!drag || event.pointerId !== drag.pointerId) return
  const layoutDelta = (event.clientY - drag.startY) / drag.visualScale
  ratioFrame.schedule({
    separatorIndex: drag.separatorIndex,
    delta: layoutDelta / drag.availableHeight,
  })
}

function finishDrag(event?: PointerEvent): void {
  if (!drag || (event && event.pointerId !== drag.pointerId)) return
  ratioFrame.flush()
  const completed = drag
  drag = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', finishDrag)
  window.removeEventListener('pointercancel', finishDrag)
  document.body.classList.remove('stock-chart-is-resizing')
  if (!completed.committed) {
    completed.committed = true
    const next = normalizeWorkspaceRatios(liveRatios.value, panels.value.length)
    emit('ratioCommit', [...next])
  }
  scheduleSettledWorkspaceResize()
}

function startDrag(event: PointerEvent, separatorIndex: number): void {
  if (drag) finishDrag()
  const height = availableHeight()
  drag = {
    pointerId: event.pointerId,
    separatorIndex,
    startY: event.clientY,
    startRatios: [...ratios.value],
    minimumRatios: minimumRatios(),
    availableHeight: height,
    visualScale: elementVisualScale(workspaceEl.value, 'y'),
    committed: false,
  }
  liveRatios.value = [...ratios.value]
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  document.body.classList.add('stock-chart-is-resizing')
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', finishDrag)
  window.addEventListener('pointercancel', finishDrag)
}

function onSeparatorKeydown(event: KeyboardEvent, separatorIndex: number): void {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
  event.preventDefault()
  liveRatios.value = [...ratios.value]
  const delta = event.key === 'ArrowUp' ? -KEYBOARD_RATIO_STEP : KEYBOARD_RATIO_STEP
  const next = applyRatioChange(separatorIndex, delta)
  emit('ratioCommit', [...next])
}

function separatorValue(index: number): number {
  return Math.round(ratios.value.slice(0, index + 1).reduce((sum, value) => sum + value, 0) * 100)
}

function separatorMin(index: number): number {
  const value = minimumRatios().slice(0, index + 1).reduce((sum, ratio) => sum + ratio, 0)
  return Math.ceil(value * 100 - Number.EPSILON * 100)
}

function separatorMax(index: number): number {
  const value = 1 - minimumRatios()
    .slice(index + 1)
    .reduce((sum, ratio) => sum + ratio, 0)
  return Math.max(
    separatorMin(index),
    Math.floor(value * 100 + 1e-8),
  )
}

function panelState(panel: PanelDescriptor): MacdPanelState | null {
  return panel.type === 'macd'
    && effectivePeriod.value === 'day'
    && props.macdState !== 'ready'
    ? props.macdState
    : null
}

function stateCopy(state: MacdPanelState) {
  if (state === 'loading') {
    return { kind: 'loading' as const, title: 'MACD 数据加载中', description: 'K线与量能仍可查看' }
  }
  if (state === 'insufficient') {
    return {
      kind: 'empty' as const,
      title: '历史数据不足',
      description: '暂不能形成完整 MACD，不补零、不生成交叉信号',
    }
  }
  return {
    kind: 'error' as const,
    title: 'MACD 加载失败',
    description: props.macdError || 'K线与量能不受影响',
  }
}

watch(
  () => props.heightRatios,
  () => {
    if (!drag) liveRatios.value = []
  },
  { deep: true },
)
watch(
  () => props.returnMeasurementMode,
  (value) => {
    if (value === measurementMode.value) return
    measurementMode.value = value
    rangeStartIndex.value = null
    rangeEndIndex.value = null
    refreshKlineChart()
  },
)
watch(
  () => props.klinePeriod,
  (value) => {
    if (value === selectedPeriod.value) return
    selectedPeriod.value = value
  },
)
watch(
  () => props.adjustMode,
  (value) => {
    if (value === selectedAdjustMode.value) return
    selectedAdjustMode.value = value
  },
)
watch(
  activeMeasurementSupplement,
  (value) => emit('measurementSummaryChange', value),
  { deep: true, immediate: true },
)
watch(ratios, () => {
  // 拖动时真实尺寸变化由 ResizeObserver 统一上报并 resize，避免比例 watch 再做一轮。
  if (drag) return
  void nextTick(onWorkspaceResize)
}, { deep: true })
watch(ancestorWorkspaceResizeActive, (resizing) => {
  if (!resizing) scheduleSettledWorkspaceResize()
})
watch(
  [() => props.zoomStart, () => props.zoomEnd],
  ([start, end]) => {
    const next = normalizeZoomRange(start, end)
    if (sameZoomRange(zoomRange.value, next)) return
    zoomRange.value = next
    charts.forEach((chart) => {
      if (chart.isDisposed()) return
      chart.dispatchAction({ type: 'dataZoom', start: next.start, end: next.end })
    })
  },
)
watch(
  [panels, rows, () => periodSeries.value.warmupBars, () => props.macdState, () => props.markers, theme,
  ],
  async () => {
    clearActiveBar()
    if (!drag) liveRatios.value = []
    await nextTick()
    syncCharts()
  },
  { deep: true },
)
watch(
  () => props.bars,
  () => {
    rangeStartIndex.value = null
    rangeEndIndex.value = null
  },
  { deep: true },
)

onMounted(async () => {
  window.addEventListener('resize', onWorkspaceResize)
  await nextTick()
  syncCharts()
  observeResize()
})
onActivated(async () => {
  active = true
  if (hasReadyVisibleCharts()) {
    activationLoading.value = false
    observeResize()
    resizeCharts()
    return
  }
  activationLoading.value = true
  await nextTick()
  // KeepAlive 恢复时先让路由页面完成一次绘制，再重建 ECharts，避免图表初始化阻塞菜单反馈。
  scheduleActivationRestore()
})
onDeactivated(() => {
  active = false
  activationLoading.value = false
  cancelDeferredActivation()
  klinePointerInside.value = false
  if (drag) finishDrag()
  reportWorkspaceUnavailable()
  stopObservingResize()
  disposeCharts()
})
onBeforeUnmount(() => {
  active = false
  cancelDeferredActivation()
  window.removeEventListener('resize', onWorkspaceResize)
  if (drag) finishDrag()
  ratioFrame.cancel()
  reportWorkspaceUnavailable()
  stopObservingResize()
  disposeCharts()
  chartElements.clear()
})
</script>

<template>
  <section
    ref="workspaceEl"
    class="stock-chart-workspace app-stock-chart-frame"
    :style="{ minHeight: `${effectiveMinHeight}px` }"
    :data-min-height="effectiveMinHeight"
    :data-zoom-start="zoomRange.start"
    :data-zoom-end="zoomRange.end"
    :aria-label="ariaLabel"
    :aria-busy="activationLoading"
    v-loading="activationLoading"
  >
    <template v-for="(panel, index) in panels" :key="panel.key">
      <article
        class="stock-chart-panel"
        :class="`stock-chart-panel--${panel.type}`"
      :style="panelStyle(panel, index)"
      :data-panel-key="panel.key"
      @pointerleave="panel.type === 'kline' && leaveKlinePanel()"
      >
        <StockChartPanelHeader
          :title="panelDisplayTitle(panel.type)"
          :items="panel.type === 'kline' ? [] : panelLegendItems(panel.type)"
          :legend-label="`${panelDisplayTitle(panel.type)}图例与当前值`"
        >
          <PageSegmented
            v-if="panel.type === 'kline' && enableKlinePeriodSwitch"
            class="stock-chart-period-switch"
            :model-value="effectivePeriod"
            :options="KLINE_PERIOD_OPTIONS"
            size="small"
            tone="primary"
            variant="tabs"
            test-id="stock-chart-kline-period"
            aria-label="K线周期"
            @update:model-value="setKlinePeriod"
          />
          <template #tail>
            <div
              v-if="panel.type === 'kline'"
              class="stock-chart-panel__tail"
            >
              <time v-if="rows.length" class="stock-chart-panel__date">
                {{ rows[metricIndex]?.bar.date }}
              </time>
              <AppIconButton
                v-if="chartOperationsVisible"
                label="图表操作"
                :aria-expanded="operationsDrawerOpen"
                :aria-controls="`${groupId}-kline-operations`"
                data-testid="stock-chart-toggle-operations"
                size="xs"
                :native-title="false"
                @click="openOperationsDrawer"
              >
                <Operation />
              </AppIconButton>
              <slot name="header-actions" />
            </div>
          </template>
        </StockChartPanelHeader>
        <div
          v-if="panel.type === 'kline'"
          class="stock-chart-metric-rail"
        >
          <StockChartLegend
            :items="panelLegendItems('kline')"
            :aria-label="`${panelDisplayTitle('kline')}均线与当前值`"
          />
        </div>
        <div class="stock-chart-panel__body">
          <div
            v-if="panel.type === 'kline' && measurementHintVisible"
            class="stock-chart-measurement__hint"
            :style="{
              top: `${STOCK_CHART_GRID_TOP}px`,
              right: `${STOCK_CHART_GRID_SIDE}px`,
              maxWidth: `calc(100% - ${STOCK_CHART_GRID_SIDE * 2}px)`,
            }"
          >
            <span class="stock-chart-measurement__headline">
              {{ measurementHint.headline }}
            </span>
            <span
              v-if="measurementHint.note"
              class="stock-chart-measurement__separator"
              aria-hidden="true"
            >·</span>
            <span v-if="measurementHint.note" class="stock-chart-measurement__meta">
              {{ measurementHint.note }}
            </span>
          </div>
          <div
            :ref="(element) => setChartElement(panel.key, element)"
            class="stock-chart-panel__canvas"
            :aria-label="`${panelDisplayTitle(panel.type)}图表`"
            @pointerenter="panel.type === 'kline' && enterKlinePanel()"
          />
          <div
            v-if="panelState(panel)"
            class="stock-chart-panel__state"
            :data-state="panelState(panel)"
          >
            <AppStateBlock
              :state="stateCopy(panelState(panel)!).kind"
              :title="stateCopy(panelState(panel)!).title"
              :description="stateCopy(panelState(panel)!).description"
              size="inline"
              :retry="panelState(panel) === 'error'"
              retry-text="重试 MACD"
              @retry="emit('retryMacd')"
            />
          </div>
        </div>
      </article>

      <StockChartPanelDivider
        v-if="index < panels.length - 1"
        interactive
        role="separator"
        tabindex="0"
        aria-orientation="horizontal"
        :aria-label="`调整${panelDisplayTitle(panel.type)}与下一幅图高度`"
        :aria-valuemin="separatorMin(index)"
        :aria-valuemax="separatorMax(index)"
        :aria-valuenow="separatorValue(index)"
        :data-separator-index="index"
        @pointerdown="startDrag($event, index)"
        @keydown="onSeparatorKeydown($event, index)"
      />
    </template>

    <StockChartOperationsDrawer
      v-if="enableReturnMeasurement || enableAdjustModeSwitch"
      v-model="operationsDrawerOpen"
      :drawer-id="`${groupId}-kline-operations`"
      @closed="restoreOperationsTriggerFocus"
    >
      <slot name="operation-actions" />
      <ChartOperationGroup v-if="enableAdjustModeSwitch" label="复权口径">
        <PageSegmented
          :model-value="selectedAdjustMode"
          :options="ADJUST_MODE_OPTIONS"
          class="app-control-width-fill"
          size="small"
          test-id="stock-chart-adjust-mode"
          aria-label="K线复权口径"
          @update:model-value="setAdjustMode"
        />
      </ChartOperationGroup>
      <ChartOperationGroup v-if="enableReturnMeasurement" label="涨跌测算">
        <PageSegmented
          :model-value="measurementMode"
          :options="MEASUREMENT_MODE_OPTIONS"
          class="app-control-width-fill"
          size="small"
          test-id="stock-chart-measurement-mode"
          aria-label="区间涨跌测算模式"
          @update:model-value="setMeasurementMode"
        />
      </ChartOperationGroup>
    </StockChartOperationsDrawer>
  </section>
</template>

<style scoped>
.stock-chart-workspace {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.stock-chart-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--el-bg-color);
}

.stock-chart-panel__date {
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
}

.stock-chart-panel__tail {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
}

.stock-chart-period-switch {
  flex: 0 0 auto;
  width: auto;
  height: var(--app-control-height-xs);
  padding: 0;
  gap: var(--app-space-3);
}

.stock-chart-period-switch :deep(.seg-btn) {
  min-width: 32px;
  padding-inline: var(--app-space-1);
}

.stock-chart-metric-rail {
  box-sizing: border-box;
  height: 28px;
  min-height: 28px;
  padding: 4px var(--app-space-3);
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  font-variant-numeric: tabular-nums;
}

.stock-chart-metric-rail :deep(.stock-chart-legend) {
  width: 100%;
}

.stock-chart-measurement__hint {
  position: absolute;
  z-index: 2;
  padding: 3px 7px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--layout-control-radius);
  background: color-mix(in srgb, var(--el-bg-color) 92%, transparent);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
}

.stock-chart-measurement__headline,
.stock-chart-measurement__separator,
.stock-chart-measurement__meta {
  color: var(--el-text-color-secondary);
  font-weight: var(--app-font-weight-regular);
}

.stock-chart-panel__body {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
}

.stock-chart-panel__canvas {
  width: 100%;
  height: 100%;
}

.stock-chart-panel__state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  background: color-mix(in srgb, var(--el-bg-color) 94%, transparent);
}

@container app-viewport (max-width: 1180px) {
  .stock-chart-panel :deep(.stock-chart-legend__item:nth-child(n + 4)) {
    display: none;
  }

  .stock-chart-metric-rail :deep(.stock-chart-legend__item:nth-child(n + 4)) {
    display: inline-flex;
  }

  .stock-chart-metric-rail :deep(.stock-chart-legend) {
    gap: var(--app-space-2);
  }

  .stock-chart-period-switch :deep(.seg-btn) {
    min-width: 28px;
    padding-inline: var(--app-space-control-gap);
  }

  .stock-chart-period-switch {
    gap: var(--app-space-control-gap);
  }

}

@container app-viewport (max-width: 400px) {
  .stock-chart-metric-rail :deep(.stock-chart-legend__item:nth-child(n + 4)) {
    display: none;
  }
}

</style>

<style>
body.stock-chart-is-resizing {
  cursor: row-resize;
  user-select: none;
}
</style>
