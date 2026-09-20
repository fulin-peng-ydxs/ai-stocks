<script setup lang="ts">
import {
  computed,
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
  watch,
} from 'vue'
import * as echarts from 'echarts'
import type { Bar, IndicatorRow } from '@/api/stocks'
import AppStateBlock from '@/components/AppStateBlock.vue'
import { useStatusColorPalette } from '@/components/chartTheme'
import type { AuxiliaryChartType, ChartType } from '@/composables/useStockChartPreferences'
import { viewportDeltaToLayoutPixels } from '@/utils/displayScaleGeometry'
import StockChartPanelDivider from './StockChartPanelDivider.vue'
import StockChartPanelHeader from './StockChartPanelHeader.vue'
import type { StockChartLegendItem } from './StockChartLegend.vue'
import {
  KLINE_MA_DEFINITIONS,
  VOLUME_MA_DEFINITIONS,
  nextStockChartWorkspaceGroupId,
  stockChartAxisPointerIndex,
} from './chartUtils'
import { useStockChartTheme } from './useStockChartTheme'
import {
  AUXILIARY_MIN_HEIGHT,
  KEYBOARD_RATIO_STEP,
  KLINE_MIN_HEIGHT,
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

const props = withDefaults(defineProps<{
  bars: Bar[]
  warmupBars?: Bar[]
  indicators?: IndicatorRow[]
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
}>(), {
  warmupBars: () => [],
  indicators: () => [],
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
})

const emit = defineEmits<{
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
  retryMacd: []
  barClick: [tradeDate: string]
  activeBarChange: [bar: Bar | null]
  workspaceResize: [sample: StockChartWorkspaceSample | undefined]
}>()

defineSlots<{
  'header-actions'?: () => unknown
}>()

const groupId = nextStockChartWorkspaceGroupId()
const workspaceEl = ref<HTMLElement | null>(null)
const chartElements = new Map<WorkspacePanelKey, HTMLElement>()
const charts = new Map<WorkspacePanelKey, echarts.ECharts>()
const theme = useStockChartTheme()
const statusPalette = useStatusColorPalette()
const activeIndex = ref<number | null>(null)
const liveRatios = ref<number[]>([])
const zoomRange = ref<ZoomRange>(normalizeZoomRange(props.zoomStart, props.zoomEnd))
const workspaceHeight = ref(0)
let resizeObserver: ResizeObserver | null = null
let active = true
let bottomSliderVisible: boolean | undefined
let lastWorkspaceState = ''
let workspaceReportedAvailable = false

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
const rows = computed(() => alignStockChartRows(props.bars, props.indicators))
const ratios = computed(() => constrainWorkspaceRatios(
  liveRatios.value.length ? liveRatios.value : props.heightRatios,
  minimumRatios(),
))
const lastIndex = computed(() => Math.max(0, rows.value.length - 1))
const metricIndex = computed(() => activeIndex.value ?? lastIndex.value)

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
    return klineMetrics(rows.value, props.warmupBars, metricIndex.value)
  }
  if (type === 'volume') {
    return volumeMetrics(rows.value, props.warmupBars, metricIndex.value)
  }
  if (props.macdState !== 'ready') {
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
    warmupBars: props.warmupBars,
    theme: theme.value,
    isBottom,
    panelHeight,
    zoomStart: zoomRange.value.start,
    zoomEnd: zoomRange.value.end,
    markers: props.markers,
    buyMarkerColor: statusPalette.value.primary,
    sellMarkerColor: statusPalette.value.warning,
    clickableCandles: props.enableIntradayDrilldown,
    showKlineTooltip: props.showKlineTooltip,
    candlestickRect,
  }
  if (panel.type === 'kline') return buildKlineOption(context)
  if (panel.type === 'volume') return buildVolumeOption(context)
  return buildMacdOption(context)
}

function onChartClick(event: { seriesType?: string; dataIndex?: number }): void {
  if (!props.enableIntradayDrilldown || event.seriesType !== 'candlestick') return
  if (typeof event.dataIndex !== 'number') return
  const tradeDate = rows.value[event.dataIndex]?.bar.date
  if (tradeDate) emit('barClick', tradeDate)
}

function onAxisPointer(event: {
  axesInfo?: Array<{ value?: string | number }>
  seriesDataIndices?: Array<{ dataIndex?: number }>
}): void {
  const index = stockChartAxisPointerIndex(event, rows.value.map((row) => row.bar.date))
  if (index == null || index === activeIndex.value) return
  activeIndex.value = index
  emit('activeBarChange', rows.value[index]?.bar ?? null)
}

function clearActiveBar(): void {
  if (activeIndex.value == null) return
  activeIndex.value = null
  emit('activeBarChange', null)
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
  echarts.disconnect(groupId)
  if (!active || charts.size < 2) return
  charts.forEach((chart) => { chart.group = groupId })
  echarts.connect(groupId)
}

function hasRenderableSize(element: HTMLElement): boolean {
  return element.clientWidth > 0 && element.clientHeight > 0
}

function syncCharts(): void {
  if (!active) return
  const visibleKeys = new Set(panels.value.map((panel) => panel.key))
  charts.forEach((chart, key) => {
    if (visibleKeys.has(key) && chartElements.has(key)) return
    chart.dispose()
    charts.delete(key)
  })

  panels.value.forEach((panel, index) => {
    const element = chartElements.get(panel.key)
    if (!element) return
    let chart = charts.get(panel.key)
    if (!chart || chart.isDisposed()) {
      // KeepAlive 切换期间 DOM 可能已隐藏但 onDeactivated 尚未执行；禁止在 0×0 容器初始化，
      // 等 ResizeObserver 收到可见尺寸后再补建，避免 ECharts 告警和无效实例。
      if (!hasRenderableSize(element)) return
      chart = echarts.init(element)
      chart.on('updateAxisPointer', (event: unknown) => {
        onAxisPointer(event as Parameters<typeof onAxisPointer>[0])
      })
      chart.on('datazoom', (event: unknown) => {
        onDataZoom(panel.key, event as DataZoomEvent)
      })
      chart.on('globalout', clearActiveBar)
      if (panel.type === 'kline') chart.on('click', onChartClick)
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
      return
    }
    resizeCharts()
    const bottomPanel = panels.value.at(-1)
    const bottomElement = bottomPanel ? chartElements.get(bottomPanel.key) : undefined
    const nextSliderVisible = stockChartVisibleSlider(bottomElement?.clientHeight)
    if (!bottomPanel || nextSliderVisible === bottomSliderVisible) return
    const chart = charts.get(bottomPanel.key)
    if (!chart || chart.isDisposed()) return
    chart.setOption(chartOption(bottomPanel, true), true)
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
  committed: boolean
}

let drag: DragState | null = null

function applyRatioChange(separatorIndex: number, delta: number): number[] {
  const next = adjustAdjacentRatios(
    drag?.startRatios ?? ratios.value,
    separatorIndex,
    delta,
    minimumRatios(),
  )
  liveRatios.value = next
  emit('ratioDraft', [...next])
  void nextTick(resizeCharts)
  return next
}

function onPointerMove(event: PointerEvent): void {
  if (!drag || event.pointerId !== drag.pointerId) return
  const layoutDelta = viewportDeltaToLayoutPixels(
    event.clientY - drag.startY,
    workspaceEl.value,
    'y',
  )
  applyRatioChange(
    drag.separatorIndex,
    layoutDelta / availableHeight(),
  )
}

function finishDrag(event?: PointerEvent): void {
  if (!drag || (event && event.pointerId !== drag.pointerId)) return
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
}

function startDrag(event: PointerEvent, separatorIndex: number): void {
  if (drag) finishDrag()
  drag = {
    pointerId: event.pointerId,
    separatorIndex,
    startY: event.clientY,
    startRatios: [...ratios.value],
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
  return panel.type === 'macd' && props.macdState !== 'ready' ? props.macdState : null
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
watch(ratios, () => {
  void nextTick(onWorkspaceResize)
}, { deep: true })
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
  [panels, rows, () => props.warmupBars, () => props.macdState, () => props.markers, theme,
  ],
  async () => {
    clearActiveBar()
    if (!drag) liveRatios.value = []
    await nextTick()
    syncCharts()
  },
  { deep: true },
)

onMounted(async () => {
  await nextTick()
  syncCharts()
  observeResize()
})
onActivated(async () => {
  active = true
  await nextTick()
  syncCharts()
  observeResize()
})
onDeactivated(() => {
  active = false
  if (drag) finishDrag()
  reportWorkspaceUnavailable()
  stopObservingResize()
  disposeCharts()
})
onBeforeUnmount(() => {
  if (drag) finishDrag()
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
  >
    <template v-for="(panel, index) in panels" :key="panel.key">
      <article
        class="stock-chart-panel"
        :class="`stock-chart-panel--${panel.type}`"
        :style="panelStyle(panel, index)"
        :data-panel-key="panel.key"
      >
        <StockChartPanelHeader
          :title="panelTitle(panel.type, adjustLabel, macdAdjustLabel)"
          :items="panelLegendItems(panel.type)"
          :legend-label="`${panelTitle(panel.type, adjustLabel, macdAdjustLabel)}图例与当前值`"
        >
          <template #tail>
            <time v-if="panel.type === 'kline' && rows.length" class="stock-chart-panel__date">
              {{ rows[metricIndex]?.bar.date }}
            </time>
            <slot v-if="panel.type === 'kline'" name="header-actions" />
          </template>
        </StockChartPanelHeader>
        <div class="stock-chart-panel__body">
          <div
            :ref="(element) => setChartElement(panel.key, element)"
            class="stock-chart-panel__canvas"
            :aria-label="`${panelTitle(panel.type, adjustLabel, macdAdjustLabel)}图表`"
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
        :aria-label="`调整${panelTitle(panel.type, adjustLabel, macdAdjustLabel)}与下一幅图高度`"
        :aria-valuemin="separatorMin(index)"
        :aria-valuemax="separatorMax(index)"
        :aria-valuenow="separatorValue(index)"
        :data-separator-index="index"
        @pointerdown="startDrag($event, index)"
        @keydown="onSeparatorKeydown($event, index)"
      />
    </template>
  </section>
</template>

<style scoped>
.stock-chart-workspace {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.stock-chart-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--el-bg-color);
}

.stock-chart-panel__date {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
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
}

</style>

<style>
body.stock-chart-is-resizing {
  cursor: row-resize;
  user-select: none;
}
</style>
