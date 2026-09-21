<script setup lang="ts">
// 板块对比图：多板块同图对比。趋势类指标（累计/单日/N 日滚动涨跌幅）以折线叠加，各板块指数
// 量级差异大（几百~几千点），统一换算成涨跌幅（%）后同图比较；截面类指标（最新资金净流入、
// 所选行情日累计成员涨跌）改用柱状对比。趋势线统一按市场交易日对齐、停牌日前向延续，并从共同有效
// 基期归零；固定 N 日必须具备 N+1 个收盘点，禁止用缩短区间代算。
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { SectorBar } from '@/api/sectors'
import AppStateBlock from '@/components/AppStateBlock.vue'
import { chartCssVariable, hasRenderableChartSize, useEChartsTheme } from '@/components/chartTheme'
import { initVectorEChart } from '@/components/echartsRenderer'
import {
  buildMarketCompareLineOption,
  escapeChartHtml,
  marketCompareChangeColors,
  marketCompareLineColors,
} from '@/components/marketCompareChart'
import {
  COMPARE_METRIC_META,
  metricKind,
  type CompareMetric,
} from '@/utils/sectorCompare'
import {
  alignPriceComparison,
  isPriceCompareMetric,
  priceMetricWindow,
  type PriceCompareSeries,
} from '@/utils/marketCompare'
import { formatMoney } from '@/utils/money'

// 单个板块的序列：code/name 标识 + 该板块的日线 bars（升序）
export interface CompareSeries {
  code: string
  name: string
  bars: SectorBar[]
}

// 截面柱状数据。second 仅 breadth（累计成员下跌家数）使用。
export interface CrossSectionDatum {
  name: string
  value: number | null
  second?: number | null
}

const props = defineProps<{
  series: CompareSeries[]
  benchmark?: CompareSeries | null
  fill?: boolean
  metric: CompareMetric
  rangeDays: number
  crossSection?: CrossSectionDatum[]
}>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeListening = false
let resizeObserver: ResizeObserver | null = null
const theme = useEChartsTheme()
const wrapBg = computed(() => theme.value.background)

const meta = computed(() => COMPARE_METRIC_META[props.metric])
const isBar = computed(() => metricKind(props.metric, props.rangeDays) === 'bar')

// 对比线只消费当前主题的语义 token，避免固定色板在自定义预设或夜间模式下失真。
const lineColors = computed(() => marketCompareLineColors(theme.value))

function toPriceSeries(series: CompareSeries): PriceCompareSeries {
  return {
    code: series.code,
    name: series.name,
    bars: series.bars.map((bar) => ({ date: bar.trade_date, close: bar.close })),
  }
}

const lineComparison = computed(() => {
  if (!isPriceCompareMetric(props.metric)) {
    return { dates: [], valuesByCode: {}, closesByCode: {} }
  }
  const series = props.series.map(toPriceSeries)
  const benchmark = props.benchmark ? toPriceSeries(props.benchmark) : null
  return alignPriceComparison(
    series,
    priceMetricWindow(props.metric, props.rangeDays),
    benchmark,
    benchmark?.bars,
  )
})
const dates = computed(() => lineComparison.value.dates)
const hasComparableLine = computed(() => isBar.value || dates.value.length >= 2)

function alignedMetric(series: CompareSeries): (number | null)[] {
  return lineComparison.value.valuesByCode[series.code] ?? []
}

function renderLine() {
  if (!chart) return
  const t = theme.value
  const colors = lineColors.value
  const changeColors = marketCompareChangeColors(t)
  const benchmarkData = props.benchmark ? alignedMetric(props.benchmark) : null
  const sectorSeries = props.series.map((s, i) => ({
    name: s.name,
    type: 'line' as const,
    data: alignedMetric(s),
    showSymbol: false,
    connectNulls: false,
    smooth: false,
    lineStyle: { width: 2, color: colors[i % colors.length] },
    itemStyle: { color: colors[i % colors.length] },
    emphasis: { focus: 'series' as const },
  }))
  const benchmarkName = props.benchmark ? `基准 · ${props.benchmark.name}` : ''
  const series = [
    ...sectorSeries,
    ...(props.benchmark ? [{
      name: benchmarkName,
      type: 'line' as const,
      data: benchmarkData,
      showSymbol: false,
      connectNulls: false,
      smooth: false,
      lineStyle: { width: 1.5, type: 'dashed' as const, color: t.label },
      itemStyle: { color: t.label },
      emphasis: { focus: 'series' as const },
      z: 1,
    }] : []),
  ]
  chart.setOption(buildMarketCompareLineOption({
    theme: t,
    colors,
    dates: dates.value,
    series,
    tooltipFormatter: (params: unknown) => {
      const rows = (Array.isArray(params) ? params : [params]).filter(Boolean) as any[]
      const date = escapeChartHtml(rows[0]?.axisValueLabel ?? rows[0]?.name ?? '')
      const content = rows.map((item: any) => {
        const value = typeof item.value === 'number' ? item.value : Number(item.value)
        const valid = item.value != null && Number.isFinite(value)
        const color = !valid || value === 0
          ? changeColors.neutral
          : value > 0 ? changeColors.up : changeColors.down
        const valueText = valid ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '--'
        const isBenchmark = item.seriesName === benchmarkName
        const benchmarkValue = benchmarkData?.[Number(item.dataIndex)]
        const excess = valid && !isBenchmark && typeof benchmarkValue === 'number'
          ? +(value - benchmarkValue).toFixed(2)
          : null
        const excessColor = excess == null || excess === 0
          ? t.label
          : excess > 0 ? changeColors.up : changeColors.down
        return `<div style="display:flex;justify-content:space-between;gap:18px">`
          + `<span>${item.marker ?? ''}${escapeChartHtml(item.seriesName)}</span>`
          + `<span style="text-align:right"><strong style="color:${color}">${valueText}</strong>`
          + (excess == null ? '' : `<small style="display:block;color:${excessColor}">超额 ${excess > 0 ? '+' : ''}${excess.toFixed(2)}%</small>`)
          + '</span>'
          + '</div>'
      }).join('')
      return `<div style="min-width:150px;line-height:1.7">`
        + `<div style="color:${t.label};margin-bottom:2px">${date} · ${meta.value.label}</div>`
        + content
        + '</div>'
    },
  }), { notMerge: true })
}

function renderBar() {
  if (!chart) return
  const t = theme.value
  const upColor = chartCssVariable('--market-up-color', '#f66055')
  const downColor = chartCssVariable('--market-down-color', '#1ec96e')
  const data = props.crossSection ?? []
  const names = data.map((d) => d.name)
  const unit = meta.value.unit
  const isBreadth = props.metric === 'breadth'
  const series = isBreadth
    ? [
        {
          name: '上涨家数', type: 'bar' as const,
          data: data.map((d) => d.value),
          barMaxWidth: 28, itemStyle: { color: upColor },
        },
        {
          name: '下跌家数', type: 'bar' as const,
          data: data.map((d) => d.second == null ? null : -d.second),
          barMaxWidth: 28, itemStyle: { color: downColor },
        },
      ]
    : [{
        name: meta.value.label, type: 'bar' as const,
          data: data.map((d) => ({
            value: d.value,
            itemStyle: { color: d.value == null ? t.label : d.value > 0 ? upColor : downColor },
          })),
        barMaxWidth: 28,
      }]
  chart.setOption({
    animation: false,
    backgroundColor: t.background,
    grid: { left: 64, right: 24, top: 40, bottom: 40 },
    legend: {
      data: series.map((item) => item.name),
      top: 4, textStyle: { color: t.label, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBackground, borderColor: t.tooltipBorder, borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const rows = (Array.isArray(params) ? params : [params]).filter(Boolean)
        const name = escapeChartHtml(rows[0]?.axisValueLabel ?? rows[0]?.name ?? '')
        const content = rows.map((item: any) => {
          const value = typeof item.value === 'number' ? item.value : Number(item.value)
          const valid = item.value != null && Number.isFinite(value)
          const color = !valid || value === 0 ? t.text : value > 0 ? upColor : downColor
          const valueText = valid
            ? (props.metric === 'inflow'
              ? `${formatMoney(value, { forceSign: true })}${unit}`
              : `${value > 0 ? '+' : ''}${value.toFixed(2)}${unit}`)
            : '--'
          return `<div style="display:flex;justify-content:space-between;gap:18px">`
            + `<span>${item.marker ?? ''}${escapeChartHtml(item.seriesName)}</span>`
            + `<span style="text-align:right"><strong style="color:${color}">${valueText}</strong></span>`
            + '</div>'
        }).join('')
        return `<div style="min-width:150px;line-height:1.7">`
          + `<div style="color:${t.label};margin-bottom:2px">${name}</div>`
          + content
          + '</div>'
      },
    },
    xAxis: {
      type: 'category', data: names,
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { color: t.label, fontSize: 10, interval: 0, rotate: names.length > 4 ? 20 : 0 },
    },
    yAxis: {
      scale: true,
      axisLine: { show: false },
      axisLabel: {
        color: t.label,
        fontSize: 10,
        formatter: props.metric === 'inflow'
          ? (value: number) => `${formatMoney(value)}${unit}`
          : `{value}${unit}`,
      },
      splitLine: { lineStyle: { color: t.split } },
    },
    series,
  }, { notMerge: true })
}

function render() {
  if (!chart) return
  if (isBar.value) renderBar()
  else renderLine()
}

function resize() {
  chart?.resize()
}
function ensureChart() {
  if (chart || !el.value || !hasComparableLine.value || !hasRenderableChartSize(el.value)) return
  chart = initVectorEChart(el.value)
  render()
}
function attachResize() {
  if (resizeListening) return
  window.addEventListener('resize', resize)
  resizeListening = true
}
function detachResize() {
  if (!resizeListening) return
  window.removeEventListener('resize', resize)
  resizeListening = false
}

onMounted(async () => {
  attachResize()
  if (el.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      ensureChart()
      resize()
    })
    resizeObserver.observe(el.value)
  }
  await nextTick()
  ensureChart()
})
onActivated(async () => { attachResize(); await nextTick(); ensureChart(); resize() })
onDeactivated(detachResize)
watch(() => props.series, render, { deep: true })
watch(() => props.benchmark, render, { deep: true })
watch(() => props.metric, render)
watch(() => props.rangeDays, render)
watch(() => props.crossSection, render, { deep: true })
watch(theme, render)
watch(hasComparableLine, async () => { await nextTick(); ensureChart(); resize() })
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
    class="cmp-wrap"
    :class="{ 'cmp-wrap--fill': fill }"
    :data-point-count="isBar ? (crossSection?.length ?? 0) : dates.length"
    :data-benchmark-code="isBar ? '' : (benchmark?.code ?? '')"
    :data-benchmark-point-count="isBar ? 0 : (benchmark?.bars.length ?? 0)"
  >
    <AppStateBlock
      v-if="!hasComparableLine"
      class="cmp-empty"
      state="empty"
      title="无共同交易区间"
      :description="benchmark
        ? '所选板块与指数没有足够的共同基期，请调整对比队列、指数或周期。'
        : '所选板块在所选区间没有可用行情。'"
    />
    <div ref="el" v-show="hasComparableLine" class="cmp" />
  </div>
</template>

<style scoped>
.cmp-wrap {
  background: v-bind(wrapBg);
  border-radius: 6px;
  padding: 4px;
}
.cmp-wrap--fill,
.cmp-wrap--fill .cmp {
  height: 100%;
}
.cmp {
  width: 100%;
  height: 440px;
}
.cmp-empty {
  height: 100%;
}
</style>
