<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { IntradayPoint } from '@/api/stocks'
import { hasRenderableChartSize } from '@/components/chartTheme'
import { initVectorEChart } from '@/components/echartsRenderer'
import StockChartPanelDivider from './StockChartPanelDivider.vue'
import StockChartPanelHeader from './StockChartPanelHeader.vue'
import type { StockChartLegendItem } from './StockChartLegend.vue'
import {
  formatChartNumber,
  formatVolumeLots,
  stockChartAxisPointerIndex,
} from './chartUtils'
import { buildIntradayOption, intradayPanelLayout } from './intradayOptions'
import { useStockChartTheme } from './useStockChartTheme'

const props = defineProps<{
  points: IntradayPoint[]
  preClose: number | null
}>()

const chartEl = ref<HTMLElement | null>(null)
const volumeHeaderTop = ref(0)
const dividerTop = ref(0)
const theme = useStockChartTheme()
const activeIndex = ref<number | null>(null)
const metricPoint = computed(() => {
  const fallbackIndex = props.points.length - 1
  const index = activeIndex.value == null ? fallbackIndex : activeIndex.value
  return index >= 0 ? props.points[index] : undefined
})
const legendItems = computed<StockChartLegendItem[]>(() => [
  {
    key: 'price',
    label: '价格',
    value: formatChartNumber(metricPoint.value?.close),
    color: theme.value.focus,
    marker: 'line',
  },
  {
    key: 'average',
    label: '均价',
    value: formatChartNumber(metricPoint.value?.average_price),
    color: theme.value.series.kline.ma5,
    marker: 'line',
  },
])
const volumeTotal = computed(() => props.points.reduce((total, point) => {
  return Number.isFinite(point.volume) && point.volume > 0 ? total + point.volume : total
}, 0))
const volumeLegendItems = computed<StockChartLegendItem[]>(() => [
  {
    key: 'volume-total',
    label: '总量',
    value: formatVolumeLots(volumeTotal.value),
    color: theme.value.label,
    marker: 'bar',
  },
])
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let zoomStart = 0
let zoomEnd = 100

function onDataZoom(event: unknown): void {
  const typed = event as {
    start?: number
    end?: number
    batch?: Array<{ start?: number; end?: number }>
  }
  const payload = typed.batch?.[0] ?? typed
  if (typeof payload.start === 'number') zoomStart = payload.start
  if (typeof payload.end === 'number') zoomEnd = payload.end
}

function onAxisPointer(event: unknown): void {
  const index = stockChartAxisPointerIndex(
    event as Parameters<typeof stockChartAxisPointerIndex>[0],
    props.points.map((point) => point.time),
  )
  if (index != null) activeIndex.value = index
}

function render(): void {
  if (!chartEl.value || !hasRenderableChartSize(chartEl.value)) return
  const panelLayout = intradayPanelLayout(chartEl.value.clientHeight)
  volumeHeaderTop.value = panelLayout.volumeHeaderTop
  dividerTop.value = panelLayout.dividerTop
  if (!chart || chart.isDisposed()) {
    chart = initVectorEChart(chartEl.value)
    chart.on('datazoom', onDataZoom)
    chart.on('updateAxisPointer', onAxisPointer)
    chart.on('globalout', () => { activeIndex.value = null })
  }
  chart.setOption(buildIntradayOption({
    points: props.points,
    preClose: props.preClose,
    theme: theme.value,
    chartHeight: chartEl.value.clientHeight,
    zoomStart,
    zoomEnd,
  }), true)
  chart.resize()
}

watch([() => props.points, () => props.preClose, theme], async () => {
  activeIndex.value = null
  await nextTick()
  render()
}, { deep: true })

onMounted(async () => {
  window.addEventListener('resize', render)
  await nextTick()
  render()
  if (chartEl.value) {
    resizeObserver = new ResizeObserver(render)
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', render)
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="stock-intraday-chart app-stock-chart-frame" aria-label="价格、均价与分钟成交量分时图">
    <StockChartPanelHeader
      title="分时"
      class="stock-intraday-chart__header"
      :items="legendItems"
      legend-label="分时图图例"
    />
    <div ref="chartEl" class="stock-intraday-chart__canvas" />
    <StockChartPanelDivider
      class="stock-intraday-chart__divider"
      :style="{ top: `${dividerTop}px` }"
      aria-hidden="true"
    />
    <StockChartPanelHeader
      title="量能"
      class="stock-intraday-chart__header stock-intraday-chart__header--volume"
      :style="{ top: `${volumeHeaderTop}px` }"
      :items="volumeLegendItems"
      legend-label="分钟成交量汇总"
    />
  </div>
</template>

<style scoped>
.stock-intraday-chart {
  position: relative;
  width: 100%;
  height: min(64cqh, 560px);
  min-height: 380px;
}

.stock-intraday-chart__canvas {
  width: 100%;
  height: 100%;
}

/*
 * 分时量柱在缩放画布中可能落到半像素，SVG 默认抗锯齿会让同一填充色呈现深浅差。
 * 仅对有填充的柱形路径做设备像素对齐；价格、均价和网格等无填充线条保持平滑。
 */
.stock-intraday-chart__canvas :deep(path[fill]:not([fill='none'])) {
  shape-rendering: crispEdges;
}

.stock-intraday-chart__header {
  position: absolute;
  z-index: 2;
  top: 0;
  right: 0;
  left: 0;
  pointer-events: none;
}

.stock-intraday-chart__divider {
  position: absolute;
  right: 0;
  left: 0;
}

@container app-viewport (max-width: 960px) {
  .stock-intraday-chart {
    height: 58cqh;
    min-height: 340px;
  }
}
</style>
