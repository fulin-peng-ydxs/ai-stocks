<script setup lang="ts">
// 成长曲线：历次训练评分 + 收益率。盘感训练历史成长回溯用。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useTheme } from '@/composables/useTheme'
import type { GrowthPoint } from '@/api/training'

const props = defineProps<{ data: GrowthPoint[] }>()
const el = ref<HTMLDivElement | null>(null)
const { isDark } = useTheme()
let chart: echarts.ECharts | null = null

const T = computed(() =>
  isDark.value
    ? { bg: '#0b0e16', axis: '#2b3550', split: '#161c28', label: '#8b94a7',
        tipBg: 'rgba(13,17,26,0.92)', tipBorder: '#2b3550', tipText: '#c9d1d9' }
    : { bg: '#ffffff', axis: '#dcdfe6', split: '#ebeef5', label: '#909399',
        tipBg: 'rgba(255,255,255,0.96)', tipBorder: '#dcdfe6', tipText: '#303133' },
)

function render() {
  if (!chart) return
  const t = T.value
  const labels = props.data.map((_, i) => `#${i + 1}`)
  const scores = props.data.map((p) => p.score)
  const rets = props.data.map((p) => (p.total_return == null ? null : +(p.total_return * 100).toFixed(2)))
  chart.setOption({
    animation: false,
    backgroundColor: t.bg,
    grid: { left: 40, right: 50, top: 30, bottom: 24 },
    legend: {
      data: ['评分', '收益%'],
      top: 4,
      textStyle: { color: t.label },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tipBg, borderColor: t.tipBorder, borderWidth: 1,
      textStyle: { color: t.tipText, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: t.axis } },
    },
    xAxis: {
      type: 'category', data: labels,
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { color: t.label, fontSize: 11 },
    },
    yAxis: [
      { type: 'value', min: 0, max: 100,
        axisLine: { show: false },
        axisLabel: { color: t.label, fontSize: 11 },
        splitLine: { lineStyle: { color: t.split } } },
      { type: 'value', position: 'right',
        axisLine: { show: false },
        axisLabel: { color: t.label, fontSize: 11, formatter: '{value}%' },
        splitLine: { show: false } },
    ],
    series: [
      { name: '评分', type: 'line', data: scores, smooth: true, connectNulls: true,
        showSymbol: true, symbolSize: 5,
        lineStyle: { color: '#409eff', width: 2 }, itemStyle: { color: '#409eff' },
        areaStyle: { color: 'rgba(64,158,255,0.08)' } },
      { name: '收益%', type: 'line', yAxisIndex: 1, data: rets, smooth: true, connectNulls: true,
        showSymbol: true, symbolSize: 5,
        lineStyle: { color: '#e6a23c', width: 2 }, itemStyle: { color: '#e6a23c' } },
    ],
  })
}

function resize() { chart?.resize() }
onMounted(() => { if (el.value) { chart = echarts.init(el.value); render(); window.addEventListener('resize', resize) } })
watch(() => props.data, render, { deep: true })
watch(isDark, render)
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose(); chart = null })
</script>

<template>
  <div ref="el" class="growth-chart" />
</template>

<style scoped>
.growth-chart { width: 100%; height: 200px; }
</style>
