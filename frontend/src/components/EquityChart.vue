<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EquityPoint } from '@/api/backtest'
import { useTheme } from '@/composables/useTheme'

const props = defineProps<{ points: EquityPoint[]; benchmarkCode: string }>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeListening = false
const { isDark } = useTheme()

const T = computed(() =>
  isDark.value
    ? { bg: '#0b0e16', axis: '#2b3550', split: '#161c28', label: '#8b94a7',
        tipBg: 'rgba(13,17,26,0.92)', tipBorder: '#2b3550', tipText: '#c9d1d9' }
    : { bg: '#ffffff', axis: '#dcdfe6', split: '#ebeef5', label: '#909399',
        tipBg: 'rgba(255,255,255,0.96)', tipBorder: '#dcdfe6', tipText: '#303133' },
)
const wrapBg = computed(() => T.value.bg)
const PORT = '#ef4d4d'
const BENCH = '#5b8ff9'
const DD = '#9aa5b1'

function render() {
  if (!chart) return
  const t = T.value
  const dates = props.points.map((p) => p.trade_date)
  const equity = props.points.map((p) => p.equity)
  const bench = props.points.map((p) => p.benchmark_equity)
  const dd = props.points.map((p) => +(p.drawdown * 100).toFixed(2))
  chart.setOption({
    animation: false,
    backgroundColor: t.bg,
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
      backgroundColor: t.tipBg, borderColor: t.tipBorder, borderWidth: 1,
      textStyle: { color: t.tipText, fontSize: 12 },
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
        lineStyle: { width: 2, color: PORT }, z: 3 },
      { name: `基准(${props.benchmarkCode})`, type: 'line', data: bench, showSymbol: false,
        lineStyle: { width: 1.5, color: BENCH } },
      { name: '回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: dd, showSymbol: false,
        areaStyle: { color: 'rgba(154,165,177,0.25)' }, lineStyle: { width: 1, color: DD } },
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
watch(isDark, render)
onBeforeUnmount(() => {
  detachResize()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="eq-wrap">
    <div ref="el" class="eq" />
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
</style>
