<script setup lang="ts">
// 板块对比图：多板块归一化走势叠加。各板块指数量级差异大（几百~几千点），直接叠价格不可比，
// 统一换算成相对基准点的累计涨跌幅（%）后同图叠加，用于横向对比不同板块的强弱与走势分化。
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { SectorBar } from '@/api/sectors'
import { chartCssVariable, useEChartsTheme } from '@/components/chartTheme'

// 单个板块的序列：code/name 标识 + 该板块的日线 bars（升序）
export interface CompareSeries {
  code: string
  name: string
  bars: SectorBar[]
}

const props = defineProps<{
  series: CompareSeries[]
  benchmark?: CompareSeries | null
  fill?: boolean
}>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeListening = false
const theme = useEChartsTheme()
const wrapBg = computed(() => theme.value.background)

// 对比线只消费当前主题的语义 token，避免固定色板在自定义预设或夜间模式下失真。
const lineColors = computed(() => [
  theme.value.focus,
  theme.value.accent,
  chartCssVariable('--el-color-success', theme.value.focus),
  chartCssVariable('--el-color-danger', theme.value.accent),
  chartCssVariable('--el-color-info', theme.value.label),
  chartCssVariable('--shell-accent', theme.value.focus),
])

// 交易日并集（升序）：各板块可能有缺口，横轴取全量交易日，缺数据的点置 null 让折线断开。
const dates = computed<string[]>(() => {
  const set = new Set<string>()
  for (const s of props.series) for (const b of s.bars) set.add(b.trade_date)
  if (props.benchmark) for (const b of props.benchmark.bars) set.add(b.trade_date)
  return Array.from(set).sort()
})

// 归一化：把每条 close 序列映射到全量日期轴上，固定以区间首个有效收盘为 0%。
function normalizedData(s: CompareSeries): (number | null)[] {
  const byDate = new Map(s.bars.map((b) => [b.trade_date, b.close]))
  const aligned = dates.value.map((d) => byDate.get(d) ?? null)
  // 区间首日可能缺数据，向后找该序列首个有效收盘作为归一化起点。
  let base: number | null = null
  for (let i = 0; i < aligned.length; i += 1) {
    if (aligned[i] != null) { base = aligned[i]; break }
  }
  if (base == null || base === 0) return aligned.map(() => null)
  return aligned.map((c) => (c == null ? null : +(((c - base) / base) * 100).toFixed(2)))
}

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function render() {
  if (!chart) return
  const t = theme.value
  const colors = lineColors.value
  const upColor = chartCssVariable('--market-up-color', '#f66055')
  const downColor = chartCssVariable('--market-down-color', '#1ec96e')
  const benchmarkData = props.benchmark ? normalizedData(props.benchmark) : null
  const sectorSeries = props.series.map((s, i) => ({
    name: s.name,
    type: 'line' as const,
    data: normalizedData(s),
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
  chart.setOption({
    animation: false,
    backgroundColor: t.background,
    color: colors,
    grid: { left: 56, right: 24, top: 40, bottom: 58 },
    legend: {
      data: series.map((item) => item.name),
      top: 4, textStyle: { color: t.label, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBackground, borderColor: t.tooltipBorder, borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: t.axis } },
      formatter: (params: any) => {
        const rows = (Array.isArray(params) ? params : [params]).filter(Boolean)
        const date = escapeHtml(rows[0]?.axisValueLabel ?? rows[0]?.name ?? '')
        const content = rows.map((item: any) => {
          const value = typeof item.value === 'number' ? item.value : Number(item.value)
          const valid = Number.isFinite(value)
          const color = !valid || value === 0 ? t.text : value > 0 ? upColor : downColor
          const valueText = valid ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '--'
          const isBenchmark = item.seriesName === benchmarkName
          const benchmarkValue = benchmarkData?.[Number(item.dataIndex)]
          const excess = valid && !isBenchmark && typeof benchmarkValue === 'number'
            ? +(value - benchmarkValue).toFixed(2)
            : null
          const excessColor = excess == null || excess === 0 ? t.label : excess > 0 ? upColor : downColor
          return `<div style="display:flex;justify-content:space-between;gap:18px">`
            + `<span>${item.marker ?? ''}${escapeHtml(item.seriesName)}</span>`
            + `<span style="text-align:right"><strong style="color:${color}">${valueText}</strong>`
            + (excess == null ? '' : `<small style="display:block;color:${excessColor}">超额 ${excess > 0 ? '+' : ''}${excess.toFixed(2)}%</small>`)
            + '</span>'
            + '</div>'
        }).join('')
        return `<div style="min-width:150px;line-height:1.7">`
          + `<div style="color:${t.label};margin-bottom:2px">${date} · 区间涨跌</div>`
          + content
          + '</div>'
      },
    },
    xAxis: {
      type: 'category', data: dates.value, boundaryGap: false,
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { color: t.label, fontSize: 10 },
    },
    yAxis: {
      scale: true,
      axisLine: { show: false },
      axisLabel: { color: t.label, fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: t.split } },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      {
        type: 'slider', bottom: 6, height: 18,
        start: 0, end: 100,
        borderColor: t.axis, fillerColor: t.area,
        textStyle: { color: t.label },
      },
    ],
    series,
  }, { notMerge: true })
}

function resize() {
  chart?.resize()
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

onMounted(() => {
  if (el.value) {
    chart = echarts.init(el.value)
    render()
    attachResize()
  }
})
onActivated(() => { attachResize(); resize() })
onDeactivated(detachResize)
watch(() => props.series, render, { deep: true })
watch(() => props.benchmark, render, { deep: true })
watch(theme, render)
onBeforeUnmount(() => {
  detachResize()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div
    class="cmp-wrap"
    :class="{ 'cmp-wrap--fill': fill }"
    :data-point-count="dates.length"
    :data-benchmark-code="benchmark?.code ?? ''"
    :data-benchmark-point-count="benchmark?.bars.length ?? 0"
  >
    <div ref="el" class="cmp" />
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
</style>
