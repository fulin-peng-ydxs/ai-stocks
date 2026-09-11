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
import StockChartPanelHeader from './StockChartPanelHeader.vue'
import type { StockChartLegendItem } from './StockChartLegend.vue'
import {
  KLINE_MA_DEFINITIONS,
  VOLUME_MA_DEFINITIONS,
  nextStockChartWorkspaceGroupId,
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
  volumeMetrics,
  type MacdPanelState,
  type TradeMarker,
  type WorkspacePanelKey,
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
  macdState?: MacdPanelState
  macdError?: string
  zoomStart?: number
  zoomEnd?: number
  minHeight?: number
  ariaLabel?: string
  enableIntradayDrilldown?: boolean
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
  minHeight: WORKSPACE_MIN_HEIGHT,
  ariaLabel: '行情多图联动工作区',
  enableIntradayDrilldown: false,
})

const emit = defineEmits<{
  ratioDraft: [ratios: number[]]
  ratioCommit: [ratios: number[]]
  retryMacd: []
  barClick: [tradeDate: string]
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
let resizeObserver: ResizeObserver | null = null
let active = true

const panels = computed<PanelDescriptor[]>(() => {
  const next: PanelDescriptor[] = [{ key: 'kline', type: 'kline' }]
  if (props.slot2 !== 'hidden') next.push({ key: 'slot2', type: props.slot2 })
  if (props.slot3 !== 'hidden') next.push({ key: 'slot3', type: props.slot3 })
  return next
})
const effectiveMinHeight = computed(() => {
  const panelFloor = stockChartWorkspaceMinHeight(panels.value.map((panel) => panel.type))
  const requested = Number(props.minHeight)
  return Math.max(panelFloor, Number.isFinite(requested) && requested > 0 ? requested : 0)
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
  if (element instanceof HTMLElement) chartElements.set(key, element)
  else chartElements.delete(key)
}

function chartOption(panel: PanelDescriptor, isBottom: boolean) {
  const context = {
    rows: rows.value,
    warmupBars: props.warmupBars,
    theme: theme.value,
    isBottom,
    zoomStart: zoomRange.value.start,
    zoomEnd: zoomRange.value.end,
    markers: props.markers,
    buyMarkerColor: statusPalette.value.primary,
    sellMarkerColor: statusPalette.value.warning,
    clickableCandles: props.enableIntradayDrilldown,
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
  const seriesIndex = event.seriesDataIndices?.[0]?.dataIndex
  if (typeof seriesIndex === 'number') {
    activeIndex.value = seriesIndex
    return
  }
  const value = event.axesInfo?.[0]?.value
  if (typeof value === 'string') {
    const index = rows.value.findIndex((row) => row.bar.date === value)
    if (index >= 0) activeIndex.value = index
  } else if (typeof value === 'number') {
    activeIndex.value = Math.max(0, Math.min(Math.round(value), lastIndex.value))
  }
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
      chart.on('globalout', () => { activeIndex.value = null })
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
  const hasPendingVisibleChart = panels.value.some((panel) => {
    const element = chartElements.get(panel.key)
    const chart = charts.get(panel.key)
    return Boolean(element && hasRenderableSize(element) && (!chart || chart.isDisposed()))
  })
  if (hasPendingVisibleChart) syncCharts()
  else resizeCharts()
}

function disposeCharts(): void {
  echarts.disconnect(groupId)
  charts.forEach((chart) => chart.dispose())
  charts.clear()
}

function observeResize(): void {
  if (!workspaceEl.value || resizeObserver) return
  resizeObserver = new ResizeObserver(onWorkspaceResize)
  resizeObserver.observe(workspaceEl.value)
}

function stopObservingResize(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
}

function availableHeight(): number {
  const height = workspaceEl.value?.getBoundingClientRect().height || effectiveMinHeight.value
  return Math.max(
    panels.value.reduce((total, panel) => total + panelMinHeight(panel.type), 0),
    height - (panels.value.length - 1) * SPLITTER_SIZE,
  )
}

function minimumRatios(): number[] {
  // 以工作区允许的最小高度计算约束，确保历史保存占比在紧凑模式下也不会挤掉量能。
  const available = effectiveMinHeight.value
    - Math.max(0, panels.value.length - 1) * SPLITTER_SIZE
  return panels.value.map((panel) => panelMinHeight(panel.type) / available)
}

function panelStyle(panel: PanelDescriptor, index: number) {
  return {
    flexGrow: ratios.value[index],
    flexBasis: '0px',
    minHeight: `${panelMinHeight(panel.type)}px`,
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
  applyRatioChange(
    drag.separatorIndex,
    (event.clientY - drag.startY) / availableHeight(),
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
  return Math.ceil(minimumRatios().slice(0, index + 1).reduce((sum, value) => sum + value, 0) * 100)
}

function separatorMax(index: number): number {
  return Math.floor(
    (1 - minimumRatios().slice(index + 1).reduce((sum, value) => sum + value, 0)) * 100,
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
    activeIndex.value = null
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
  stopObservingResize()
  disposeCharts()
})
onBeforeUnmount(() => {
  if (drag) finishDrag()
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
          :title="panelTitle(panel.type, adjustLabel)"
          :items="panelLegendItems(panel.type)"
          :legend-label="`${panelTitle(panel.type, adjustLabel)}图例与当前值`"
        >
          <template #tail>
            <time v-if="panel.type === 'kline' && rows.length" class="stock-chart-panel__date">
              {{ rows[metricIndex]?.bar.date }}
            </time>
          </template>
        </StockChartPanelHeader>
        <div class="stock-chart-panel__body">
          <div
            :ref="(element) => setChartElement(panel.key, element)"
            class="stock-chart-panel__canvas"
            :aria-label="`${panelTitle(panel.type, adjustLabel)}图表`"
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

      <div
        v-if="index < panels.length - 1"
        class="stock-chart-splitter"
        role="separator"
        tabindex="0"
        aria-orientation="horizontal"
        :aria-label="`调整${panelTitle(panel.type, adjustLabel)}与下一幅图高度`"
        :aria-valuemin="separatorMin(index)"
        :aria-valuemax="separatorMax(index)"
        :aria-valuenow="separatorValue(index)"
        :data-separator-index="index"
        @pointerdown="startDrag($event, index)"
        @keydown="onSeparatorKeydown($event, index)"
      >
        <span aria-hidden="true" />
      </div>
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

.stock-chart-splitter {
  position: relative;
  z-index: 2;
  flex: 0 0 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  touch-action: none;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
  outline: none;
}

.stock-chart-splitter > span {
  width: 42px;
  height: 2px;
  border-radius: 1px;
  background: var(--el-border-color);
}

.stock-chart-splitter:hover,
.stock-chart-splitter:focus-visible {
  background: var(--el-color-primary-light-9);
}

.stock-chart-splitter:focus-visible {
  box-shadow: inset 0 0 0 2px var(--el-color-primary);
}

.stock-chart-splitter:hover > span,
.stock-chart-splitter:focus-visible > span {
  background: var(--el-color-primary);
}

@media (max-width: 1180px) {
  .stock-chart-panel :deep(.stock-chart-legend__item:nth-child(n + 4)) {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .stock-chart-splitter,
  .stock-chart-splitter > span {
    transition: none;
  }
}
</style>

<style>
body.stock-chart-is-resizing {
  cursor: row-resize;
  user-select: none;
}
</style>
