<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { Bar } from '@/api/stocks'
import AppStateBlock from '@/components/AppStateBlock.vue'
import { chartCssVariable, hasRenderableChartSize, useEChartsTheme } from '@/components/chartTheme'
import {
  alignPriceComparison,
  PRICE_COMPARE_METRIC_META,
  priceMetricWindow,
  type PriceCompareMetric,
  type PriceCompareSeries,
} from '@/utils/marketCompare'

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

const colors = computed(() => [
  theme.value.focus,
  theme.value.accent,
  chartCssVariable('--el-color-success', theme.value.focus),
  chartCssVariable('--el-color-danger', theme.value.accent),
  chartCssVariable('--el-color-info', theme.value.label),
  chartCssVariable('--shell-accent', theme.value.focus),
])

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

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function relativeSeries(item: StockCompareSeries): (number | null)[] {
  return comparison.value.valuesByCode[item.code] ?? []
}

function render(): void {
  if (!chart) return
  const currentTheme = theme.value
  const palette = colors.value
  const upColor = chartCssVariable('--market-up-color', '#f66055')
  const downColor = chartCssVariable('--market-down-color', '#1ec96e')
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
  chart.setOption({
    animation: false,
    backgroundColor: currentTheme.background,
    color: palette,
    grid: { left: 56, right: 24, top: 40, bottom: 58 },
    legend: {
      data: series.map((item) => item.name),
      top: 4,
      type: 'scroll',
      textStyle: { color: currentTheme.label, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: currentTheme.tooltipBackground,
      borderColor: currentTheme.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: currentTheme.text, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: currentTheme.axis } },
      formatter: (params: any) => {
        const rows = (Array.isArray(params) ? params : [params]).filter(Boolean)
        const date = String(rows[0]?.axisValueLabel ?? rows[0]?.name ?? '')
        const content = rows.map((row: any) => {
          const relative = Number(row.value)
          const valid = row.value != null && Number.isFinite(relative)
          const relativeText = valid ? `${relative > 0 ? '+' : ''}${relative.toFixed(2)}%` : '--'
          const color = !valid || relative === 0 ? currentTheme.text : relative > 0 ? upColor : downColor
          const isBenchmark = row.seriesName === benchmarkName
          const benchmarkValue = benchmarkData?.[Number(row.dataIndex)]
          const excess = valid && !isBenchmark && typeof benchmarkValue === 'number'
            ? +(relative - benchmarkValue).toFixed(2)
            : null
          const excessColor = excess == null || excess === 0 ? currentTheme.label : excess > 0 ? upColor : downColor
          return `<div style="display:flex;justify-content:space-between;gap:18px">`
            + `<span>${row.marker ?? ''}${escapeHtml(row.seriesName)}</span>`
            + `<span style="text-align:right"><strong style="color:${color}">${relativeText}</strong>`
            + (excess == null ? '' : `<small style="display:block;color:${excessColor}">超额 ${excess > 0 ? '+' : ''}${excess.toFixed(2)}%</small>`)
            + '</span>'
            + '</div>'
        }).join('')
        return `<div style="min-width:180px;line-height:1.7">`
          + `<div style="color:${currentTheme.label};margin-bottom:2px">${escapeHtml(date)} · ${metricLabel.value}</div>`
          + content
          + '</div>'
      },
    },
    xAxis: {
      type: 'category',
      data: dates.value,
      boundaryGap: false,
      axisLine: { lineStyle: { color: currentTheme.axis } },
      axisLabel: { color: currentTheme.label, fontSize: 10 },
    },
    yAxis: {
      scale: true,
      axisLine: { show: false },
      axisLabel: { color: currentTheme.label, fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: currentTheme.split } },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      {
        type: 'slider',
        bottom: 6,
        height: 18,
        start: 0,
        end: 100,
        borderColor: currentTheme.axis,
        fillerColor: currentTheme.area,
        textStyle: { color: currentTheme.label },
      },
    ],
    series,
  }, { notMerge: true })
}

function resize(): void {
  chart?.resize()
}

function ensureChart(): void {
  if (chart || !el.value || !hasCommonInterval.value || !hasRenderableChartSize(el.value)) return
  chart = echarts.init(el.value)
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
      resize()
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
      description="所选股票与指数没有共同有效基期，请调整对比队列、指数或周期。"
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
