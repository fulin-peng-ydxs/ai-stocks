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

// 归一化基准：first=区间首根收盘=0；mid=区间中点收盘=0（看前半/后半段分化）
export type CompareBasis = 'first' | 'mid'

const props = defineProps<{
  series: CompareSeries[]
  basis?: CompareBasis
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
  return Array.from(set).sort()
})

const midIndex = computed(() => Math.floor(dates.value.length / 2))

// 归一化：把每个板块的 close 序列映射到全量日期轴上，相对基准点收盘换算成累计涨跌幅（%）。
function normalizedData(s: CompareSeries): (number | null)[] {
  const byDate = new Map(s.bars.map((b) => [b.trade_date, b.close]))
  const aligned = dates.value.map((d) => byDate.get(d) ?? null)
  const baseIdx = props.basis === 'mid' ? midIndex.value : 0
  // 基准点本身可能缺数据，向后找最近的有效收盘做基点。
  let base: number | null = null
  for (let i = baseIdx; i < aligned.length; i += 1) {
    if (aligned[i] != null) { base = aligned[i]; break }
  }
  if (base == null || base === 0) return aligned.map(() => null)
  return aligned.map((c) => (c == null ? null : +(((c - base) / base) * 100).toFixed(2)))
}

function render() {
  if (!chart) return
  const t = theme.value
  const colors = lineColors.value
  const series = props.series.map((s, i) => ({
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
  chart.setOption({
    animation: false,
    backgroundColor: t.background,
    color: colors,
    grid: { left: 56, right: 24, top: 40, bottom: 58 },
    legend: {
      data: props.series.map((s) => s.name),
      top: 4, textStyle: { color: t.label, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBackground, borderColor: t.tooltipBorder, borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: t.axis } },
      valueFormatter: (v: number | null) => (v == null ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`),
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
      { type: 'inside' },
      {
        type: 'slider', bottom: 6, height: 18,
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
watch(() => props.basis, render)
watch(theme, render)
onBeforeUnmount(() => {
  detachResize()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="cmp-wrap" :class="{ 'cmp-wrap--fill': fill }">
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
