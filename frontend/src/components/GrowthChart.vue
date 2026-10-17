<script setup lang="ts">
// 成长曲线：历次训练评分 + 收益率。盘感训练历史成长回溯用。
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useEChartsTheme } from '@/components/chartTheme'
import { initVectorEChart } from '@/components/echartsRenderer'
import type { GrowthPoint } from '@/api/training'
import { formatMarketPercent } from '@/utils/marketValue'

const props = defineProps<{ data: GrowthPoint[] }>()
const el = ref<HTMLDivElement | null>(null)
const theme = useEChartsTheme()
let chart: echarts.ECharts | null = null
let resizeListening = false

function render() {
  if (!chart) return
  const t = theme.value
  const labels = props.data.map((_, i) => `#${i + 1}`)
  const scores = props.data.map((p) => p.score)
  const rets = props.data.map((p) => (p.total_return == null ? null : +(p.total_return * 100).toFixed(2)))
  chart.setOption({
    animation: false,
    backgroundColor: t.background,
    grid: { left: 40, right: 50, top: 30, bottom: 24 },
    legend: {
      data: ['评分', '收益%'],
      top: 4,
      textStyle: { color: t.label },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBackground, borderColor: t.tooltipBorder, borderWidth: 1,
      textStyle: { color: t.text, fontSize: t.typography.body },
      axisPointer: { type: 'cross', label: { backgroundColor: t.axis } },
    },
    xAxis: {
      type: 'category', data: labels,
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { color: t.label, fontSize: t.typography.compact },
    },
    yAxis: [
      { type: 'value', min: 0, max: 100,
        axisLine: { show: false },
        axisLabel: { color: t.label, fontSize: t.typography.compact },
        splitLine: { lineStyle: { color: t.split } } },
      { type: 'value', position: 'right',
        axisLine: { show: false },
        axisLabel: { color: t.label, fontSize: t.typography.compact, formatter: formatMarketPercent },
        splitLine: { show: false } },
    ],
    series: [
      { name: '评分', type: 'line', data: scores, smooth: true, connectNulls: true,
        showSymbol: true, symbolSize: 5,
        lineStyle: { color: t.focus, width: 2 }, itemStyle: { color: t.focus },
        areaStyle: { color: t.area } },
      { name: '收益%', type: 'line', yAxisIndex: 1, data: rets, smooth: true, connectNulls: true,
        showSymbol: true, symbolSize: 5,
        lineStyle: { color: t.accent, width: 2 }, itemStyle: { color: t.accent } },
    ],
  })
}

function resize() { chart?.resize() }
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
onMounted(() => { if (el.value) { chart = initVectorEChart(el.value); render(); attachResize() } })
onActivated(() => { attachResize(); resize() })
onDeactivated(detachResize)
watch(() => props.data, render, { deep: true })
watch(theme, render)
onBeforeUnmount(() => { detachResize(); chart?.dispose(); chart = null })
</script>

<template>
  <div ref="el" class="growth-chart" />
</template>

<style scoped>
.growth-chart { width: 100%; height: 200px; }
</style>
