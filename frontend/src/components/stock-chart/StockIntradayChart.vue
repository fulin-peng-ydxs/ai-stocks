<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { IntradayPoint } from '@/api/stocks'
import { hasRenderableChartSize } from '@/components/chartTheme'
import { buildIntradayOption } from './intradayOptions'
import { useStockChartTheme } from './useStockChartTheme'

const props = defineProps<{
  points: IntradayPoint[]
  preClose: number | null
}>()

const chartEl = ref<HTMLElement | null>(null)
const theme = useStockChartTheme()
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

function render(): void {
  if (!chartEl.value || !hasRenderableChartSize(chartEl.value)) return
  if (!chart || chart.isDisposed()) {
    chart = echarts.init(chartEl.value)
    chart.on('datazoom', onDataZoom)
  }
  chart.setOption(buildIntradayOption({
    points: props.points,
    preClose: props.preClose,
    theme: theme.value,
    zoomStart,
    zoomEnd,
  }), true)
  chart.resize()
}

watch([() => props.points, () => props.preClose, theme], async () => {
  await nextTick()
  render()
}, { deep: true })

onMounted(async () => {
  await nextTick()
  render()
  if (chartEl.value) {
    resizeObserver = new ResizeObserver(render)
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="stock-intraday-chart" aria-label="价格、均价与分钟成交量分时图" />
</template>

<style scoped>
.stock-intraday-chart {
  width: 100%;
  height: min(64vh, 560px);
  min-height: 380px;
}

@media (max-width: 960px) {
  .stock-intraday-chart {
    height: 58vh;
    min-height: 340px;
  }
}
</style>
