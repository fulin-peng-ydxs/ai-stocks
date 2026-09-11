<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { IntradayPoint } from '@/api/stocks'
import { hasRenderableChartSize } from '@/components/chartTheme'
import StockChartPanelHeader from './StockChartPanelHeader.vue'
import { buildIntradayOption, intradayPanelLayout } from './intradayOptions'
import { useStockChartTheme } from './useStockChartTheme'

const props = defineProps<{
  points: IntradayPoint[]
  preClose: number | null
}>()

const chartEl = ref<HTMLElement | null>(null)
const volumeHeaderTop = ref(0)
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
  const panelLayout = intradayPanelLayout(chartEl.value.clientHeight)
  volumeHeaderTop.value = panelLayout.volumeHeaderTop
  if (!chart || chart.isDisposed()) {
    chart = echarts.init(chartEl.value)
    chart.on('datazoom', onDataZoom)
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
  <div class="stock-intraday-chart" aria-label="价格、均价与分钟成交量分时图">
    <StockChartPanelHeader title="分时" class="stock-intraday-chart__header">
      <div class="stock-intraday-chart__legend" aria-label="分时图图例">
        <span>
          <i :style="{ backgroundColor: theme.focus }" aria-hidden="true" />
          价格
        </span>
        <span>
          <i :style="{ backgroundColor: theme.series.kline.ma5 }" aria-hidden="true" />
          均价
        </span>
      </div>
    </StockChartPanelHeader>
    <div ref="chartEl" class="stock-intraday-chart__canvas" />
    <StockChartPanelHeader
      title="量能"
      class="stock-intraday-chart__header stock-intraday-chart__header--volume"
      :style="{ top: `${volumeHeaderTop}px` }"
    />
  </div>
</template>

<style scoped>
.stock-intraday-chart {
  position: relative;
  width: 100%;
  height: min(64vh, 560px);
  min-height: 380px;
}

.stock-intraday-chart__canvas {
  width: 100%;
  height: 100%;
}

.stock-intraday-chart__header {
  position: absolute;
  z-index: 2;
  top: 0;
  right: 0;
  left: 0;
  pointer-events: none;
}

.stock-intraday-chart__legend {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
  color: var(--el-text-color-secondary);
  font-size: var(--app-font-size-micro);
}

.stock-intraday-chart__legend span {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-control-gap);
}

.stock-intraday-chart__legend i {
  width: 14px;
  height: 2px;
  border-radius: 1px;
}

@media (max-width: 960px) {
  .stock-intraday-chart {
    height: 58vh;
    min-height: 340px;
  }
}
</style>
