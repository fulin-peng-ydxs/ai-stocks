<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EquityPoint } from '@/api/backtest'
import { useEChartsTheme } from '@/components/chartTheme'

const props = defineProps<{ points: EquityPoint[]; benchmarkCode: string; fill?: boolean }>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeListening = false
const theme = useEChartsTheme()
const wrapBg = computed(() => theme.value.background)

function render() {
  if (!chart) return
  const t = theme.value
  const dates = props.points.map((p) => p.trade_date)
  const equity = props.points.map((p) => p.equity)
  const bench = props.points.map((p) => p.benchmark_equity)
  const dd = props.points.map((p) => +(p.drawdown * 100).toFixed(2))
  chart.setOption({
    animation: false,
    backgroundColor: t.background,
    grid: [
      { left: 64, right: 20, top: 30, height: '58%' },
      { left: 64, right: 20, top: '74%', height: '17%' },
    ],
    legend: {
      data: ['组合净值', `基准(${props.benchmarkCode})`],
      top: 4, textStyle: { color: t.label },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBackground, borderColor: t.tooltipBorder, borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: t.axis } },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: dates, axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { color: t.label, fontSize: 10 } },
      { type: 'category', gridIndex: 1, data: dates, axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { scale: true, axisLine: { show: false }, axisLabel: { color: t.label, fontSize: 10 },
        splitLine: { lineStyle: { color: t.split } } },
      { gridIndex: 1, axisLine: { show: false }, splitNumber: 2,
        axisLabel: { color: t.label, fontSize: 10, formatter: '{value}%' },
        splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series: [
      { name: '组合净值', type: 'line', data: equity, showSymbol: false,
        lineStyle: { width: 2, color: t.focus }, z: 3 },
      { name: `基准(${props.benchmarkCode})`, type: 'line', data: bench, showSymbol: false,
        lineStyle: { width: 1.5, color: t.accent } },
      { name: '回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: dd, showSymbol: false,
        areaStyle: { color: t.area }, lineStyle: { width: 1, color: t.muted } },
    ],
  })
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
watch(() => props.points, render, { deep: true })
watch(theme, render)
onBeforeUnmount(() => {
  detachResize()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="eq-wrap" :class="{ 'eq-wrap--fill': fill }">
    <div ref="el" class="eq" :class="{ 'eq--fill': fill }" />
  </div>
</template>

<style scoped>
.eq-wrap {
  background: v-bind(wrapBg);
  border-radius: 6px;
  padding: 4px;
}
.eq {
  width: 100%;
  height: 420px;
}
/* 撑满容器模式：结算详情页等高列内图表随容器高度填满（无固定高度则退化 420px）。 */
.eq-wrap--fill {
  height: 100%;
  box-sizing: border-box;
}
.eq--fill {
  height: 100%;
}
</style>
