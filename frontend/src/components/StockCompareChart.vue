<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { Bar } from '@/api/stocks'
import AppStateBlock from '@/components/AppStateBlock.vue'
import { hasRenderableChartSize, useEChartsTheme } from '@/components/chartTheme'
import { chartTooltipRowHtml } from '@/components/chartTooltipHtml'
import { initVectorEChart } from '@/components/echartsRenderer'
import { useDeferredWorkspaceResize } from '@/composables/useDeferredWorkspaceResize'
import {
  buildMarketCompareLineOption,
  escapeChartHtml,
  marketCompareChangeColors,
  marketCompareLineColors,
} from '@/components/marketCompareChart'
import {
  alignPriceComparison,
  PRICE_COMPARE_METRIC_META,
  priceMetricWindow,
  type PriceCompareMetric,
  type PriceCompareSeries,
} from '@/utils/marketCompare'
import { formatMarketPercent } from '@/utils/marketValue'

export interface StockCompareSeries {
  code: string
  name: string
  bars: Bar[]
}

const props = defineProps<{
  series: StockCompareSeries[]
  benchmark?: StockCompareSeries | null
  calendar?: Bar[]
  activeCode?: string
  fill?: boolean
  metric: PriceCompareMetric
  rangeDays: number
}>()

const el = ref<HTMLDivElement | null>(null)
const theme = useEChartsTheme()
const wrapBg = computed(() => theme.value.background)
let chart: echarts.ECharts | null = null
let resizeListening = false
let resizeObserver: ResizeObserver | null = null

const colors = computed(() => marketCompareLineColors(theme.value))

function toPriceSeries(item: StockCompareSeries): PriceCompareSeries {
  return {
    code: item.code,
    name: item.name,
    bars: item.bars.map((bar) => ({ date: bar.date, close: bar.close })),
  }
}

const comparison = computed(() => {
  const series = props.series.map(toPriceSeries)
  const benchmark = props.benchmark ? toPriceSeries(props.benchmark) : null
  return alignPriceComparison(
    series,
    priceMetricWindow(props.metric, props.rangeDays),
    benchmark,
    props.calendar?.map((bar) => ({ date: bar.date, close: bar.close })) ?? benchmark?.bars,
  )
})
const dates = computed(() => comparison.value.dates)
const hasCommonInterval = computed(() => dates.value.length >= 2)
const metricLabel = computed(() => PRICE_COMPARE_METRIC_META[props.metric].label)
const concreteValueBase = computed(() => {
  const referenceCode = props.activeCode && comparison.value.closesByCode[props.activeCode]
    ? props.activeCode
    : props.series[0]?.code
  return referenceCode
    ? comparison.value.closesByCode[referenceCode]?.find((value) => value != null) ?? null
    : null
})

function relativeSeries(item: StockCompareSeries): (number | null)[] {
  return comparison.value.valuesByCode[item.code] ?? []
}

function render(): void {
  if (!chart) return
  const currentTheme = theme.value
  const palette = colors.value
  const changeColors = marketCompareChangeColors(currentTheme)
  const stockSeries = props.series.map((item, index) => {
    const active = item.code === props.activeCode
    return {
      name: `${item.name || item.code} · ${item.code}`,
      type: 'line' as const,
      data: relativeSeries(item),
      showSymbol: false,
      connectNulls: false,
      smooth: false,
      lineStyle: { width: active ? 2.8 : 1.8, color: palette[index % palette.length] },
      itemStyle: { color: palette[index % palette.length] },
      emphasis: { focus: 'series' as const, lineStyle: { width: 3.2 } },
      z: active ? 3 : 2,
    }
  })
  const benchmarkName = props.benchmark ? `基准 · ${props.benchmark.name}` : ''
  const benchmarkData = props.benchmark ? relativeSeries(props.benchmark) : null
  const series = [
    ...stockSeries,
    ...(props.benchmark ? [{
      name: benchmarkName,
      type: 'line' as const,
      data: benchmarkData,
      showSymbol: false,
      connectNulls: false,
      smooth: false,
      lineStyle: { width: 1.5, type: 'dashed' as const, color: currentTheme.label },
      itemStyle: { color: currentTheme.label },
      emphasis: { focus: 'series' as const },
      z: 1,
    }] : []),
  ]
  chart.setOption(buildMarketCompareLineOption({
    theme: currentTheme,
    colors: palette,
    dates: dates.value,
    series,
    scrollLegend: true,
    concreteValueBase: concreteValueBase.value,
    tooltipFormatter: (params: unknown) => {
      const rows = (Array.isArray(params) ? params : [params]).filter(Boolean) as any[]
      const date = String(rows[0]?.axisValueLabel ?? rows[0]?.name ?? '')
      const content = rows.map((row: any) => {
        const relative = Number(row.value)
        const valid = row.value != null && Number.isFinite(relative)
        const relativeText = valid ? formatMarketPercent(relative) : '--'
        const color = !valid || relative === 0
          ? changeColors.neutral
          : relative > 0 ? changeColors.up : changeColors.down
        const isBenchmark = row.seriesName === benchmarkName
        const benchmarkValue = benchmarkData?.[Number(row.dataIndex)]
        const excess = valid && !isBenchmark && typeof benchmarkValue === 'number'
          ? +(relative - benchmarkValue).toFixed(2)
          : null
        const excessColor = excess == null || excess === 0
          ? currentTheme.label
          : excess > 0 ? changeColors.up : changeColors.down
        return chartTooltipRowHtml(
          `<span>${row.marker ?? ''}${escapeChartHtml(row.seriesName)}</span>`,
          `<span style="text-align:right"><strong style="color:${color}">${relativeText}</strong>`
            + (excess == null ? '' : `<small style="display:block;color:${excessColor}">超额 ${formatMarketPercent(excess)}</small>`)
            + '</span>',
        )
      }).join('')
      return `<div style="min-width:180px;line-height:var(--app-line-height-longform)">`
        + `<div style="color:${currentTheme.label};margin-bottom:2px">${escapeChartHtml(date)} · ${metricLabel.value}</div>`
        + content
        + '</div>'
    },
  }), { notMerge: true })
}

function resize(): void {
  chart?.resize()
}

const requestWorkspaceResize = useDeferredWorkspaceResize(resize)

function ensureChart(): void {
  if (chart || !el.value || !hasCommonInterval.value || !hasRenderableChartSize(el.value)) return
  chart = initVectorEChart(el.value)
  render()
}

function attachResize(): void {
  if (resizeListening) return
  window.addEventListener('resize', resize)
  resizeListening = true
}

function detachResize(): void {
  if (!resizeListening) return
  window.removeEventListener('resize', resize)
  resizeListening = false
}

onMounted(() => {
  if (el.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      ensureChart()
      requestWorkspaceResize()
    })
    resizeObserver.observe(el.value)
  }
  ensureChart()
  attachResize()
})
onActivated(async () => { attachResize(); await nextTick(); ensureChart(); resize() })
onDeactivated(detachResize)
watch(() => props.series, render, { deep: true })
watch(() => props.benchmark, render, { deep: true })
watch(() => props.calendar, render, { deep: true })
watch(() => props.activeCode, render)
watch(() => props.metric, render)
watch(() => props.rangeDays, render)
watch(theme, render)
watch(hasCommonInterval, async () => {
  await nextTick()
  ensureChart()
  resize()
})
onBeforeUnmount(() => {
  detachResize()
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div
    class="stock-compare-wrap"
    :class="{ 'stock-compare-wrap--fill': fill }"
    :data-point-count="dates.length"
    :data-benchmark-code="benchmark?.code ?? ''"
  >
    <AppStateBlock
      v-if="series.length && !hasCommonInterval"
      class="stock-compare-empty"
      state="empty"
      title="无共同交易区间"
      :description="benchmark
        ? '所选股票与指数没有共同有效基期，请调整对比队列、指数或周期。'
        : '所选股票在所选区间没有可用行情。'"
    />
    <div ref="el" v-show="hasCommonInterval" class="stock-compare-chart" />
  </div>
</template>

<style scoped>
.stock-compare-wrap {
  padding: 4px;
  border-radius: 6px;
  background: v-bind(wrapBg);
}
.stock-compare-wrap--fill,
.stock-compare-wrap--fill .stock-compare-chart {
  height: 100%;
}
.stock-compare-chart {
  width: 100%;
  height: 440px;
}
.stock-compare-empty {
  height: 100%;
}
</style>
