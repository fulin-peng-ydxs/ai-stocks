<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EquityPoint } from '@/api/backtest'
import type { BenchmarkEquity } from '@/utils/benchmarkEquity'
import { chartCssVariable, useEChartsTheme } from '@/components/chartTheme'
import { chartTooltipRowHtml } from '@/components/chartTooltipHtml'
import { initVectorEChart } from '@/components/echartsRenderer'
import { formatMoney } from '@/utils/money'
import { formatMarketPercent } from '@/utils/marketValue'

// showBenchmark：缺省 true（默认展示基准）；父页显式传 false（回测选「不对比指数」）时整条基准线隐藏。
// extraBenchmark 由父页按各自 trade_date 归一成资金净值曲线（与 points 同长同序）；有值渲染指数虚线，
// 无值（训练结算的「满仓持有」）渲染 points 自带基准实线。
// 注意：Vue boolean prop 缺省即 false，必须用 withDefaults 给 true 默认，否则未传时基准线被隐藏。
const props = withDefaults(defineProps<{
  points: EquityPoint[]
  benchmarkCode: string
  fill?: boolean
  extraBenchmark?: BenchmarkEquity | null
  showBenchmark?: boolean
}>(), {
  fill: false,
  extraBenchmark: null,
  showBenchmark: true,
})
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeListening = false
const theme = useEChartsTheme()
const wrapBg = computed(() => theme.value.background)

function render() {
  if (!chart) return
  const t = theme.value
  const upColor = chartCssVariable('--market-up-color', '#f66055')
  const downColor = chartCssVariable('--market-down-color', '#1ec96e')
  // 回撤语义=风险/亏损深度，用 danger 红（非 A 股涨跌绿）；面积用 light-9 浅红避免刺眼，与基准灰、组合蓝色相错开。
  const ddColor = chartCssVariable('--el-color-danger', '#f04438')
  const ddAreaColor = chartCssVariable('--el-color-danger-light-9', ddColor)
  const dates = props.points.map((p) => p.trade_date)
  const equity = props.points.map((p) => p.equity)
  const dd = props.points.map((p) => +(p.drawdown * 100).toFixed(2))
  // 父页显式关掉对比（showBenchmark=false）时整条基准线隐藏；否则：
  // 有 extraBenchmark 渲染该指数虚线，无则渲染 points 自带基准实线（训练结算「满仓持有」场景）。
  const showBenchmark = props.showBenchmark
  const hasExtra = !!props.extraBenchmark
  // 基准净值允许 null（无收盘日断点），用 echarts 的 (number | null)[] 数据标注避免 TS 收窄报错。
  const bench: (number | null)[] = hasExtra ? props.extraBenchmark!.equity : props.points.map((p) => p.benchmark_equity)
  const benchName = hasExtra ? `基准 · ${props.extraBenchmark!.name}` : `基准(${props.benchmarkCode})`
  // 基准线灰（t.label），与板块行情对比图基准一致；color/itemStyle 同值保证图例/悬浮圆点与线色一致。
  const benchColor = t.label
  // 首日净值（组合/基准同初值），悬浮换算涨跌幅与组合超额用。
  const firstEquity = equity.find((v) => Number.isFinite(v) && v !== 0) ?? 0
  const firstBench = bench.find((v) => Number.isFinite(v) && v !== 0) ?? 0
  const series: echarts.LineSeriesOption[] = [
    { name: '组合净值', type: 'line', data: equity, showSymbol: false,
      color: t.focus, lineStyle: { width: 2, color: t.focus }, z: 3 },
    { name: '回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: dd, showSymbol: false,
      color: ddColor, itemStyle: { color: ddColor },
      areaStyle: { color: ddAreaColor }, lineStyle: { width: 1, color: ddColor } },
  ]
  if (showBenchmark) {
    series.splice(1, 0, {
      name: benchName, type: 'line', data: bench, showSymbol: false,
      color: benchColor, itemStyle: { color: benchColor },
      lineStyle: { width: 1.5, color: benchColor, type: hasExtra ? 'dashed' : 'solid' },
    })
  }
  chart.setOption({
    animation: false,
    backgroundColor: t.background,
    grid: [
      { left: 64, right: 20, top: 30, height: '58%' },
      { left: 64, right: 20, top: '74%', height: '17%' },
    ],
    legend: {
      data: showBenchmark ? ['组合净值', benchName] : ['组合净值'],
      top: 4, textStyle: { color: t.label },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBackground, borderColor: t.tooltipBorder, borderWidth: 1,
      textStyle: { color: t.text, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: t.axis } },
      // 净值图悬浮：组合/基准按「相对首日涨跌幅 %」展示，并在基准可见时给组合一行「超额」（组合涨跌幅−基准涨跌幅），
      // 与板块行情对比图悬浮口径一致；回撤子图仍按 % 原值展示。
      formatter: (params: unknown) => {
        const rows = (Array.isArray(params) ? params : [params]).filter(Boolean) as {
          axisValueLabel?: string; name?: string; seriesName?: string
          value?: unknown; dataIndex?: number; marker?: string
        }[]
        const date = rows[0]?.axisValueLabel ?? rows[0]?.name ?? ''
        const idx = rows[0]?.dataIndex ?? 0
        const retOf = (v: unknown, first: number) =>
          Number.isFinite(v) && first ? ((v as number) / first - 1) * 100 : null
        const fmtRet = (r: number | null) => r == null ? '--' : formatMarketPercent(r)
        const colorOf = (r: number | null) => (r == null || r === 0 ? t.text : r > 0 ? upColor : downColor)
        // 超额=组合相对首日涨跌幅 − 基准相对首日涨跌幅（仅组合行、且基准可见时显示）
        const portfolioRet = retOf(equity[idx], firstEquity)
        const benchRet = retOf(bench[idx], firstBench)
        const excess = showBenchmark && portfolioRet != null && benchRet != null
          ? +(portfolioRet - benchRet).toFixed(2) : null
        const content = rows.map((item) => {
          const isDd = item.seriesName === '回撤'
          const r = isDd ? null : (item.seriesName === '组合净值' ? portfolioRet : benchRet)
          const val = isDd ? Number(item.value) : r
          const valText = isDd ? (Number.isFinite(val) ? formatMarketPercent(val as number) : '--') : fmtRet(r)
          const excessHtml = !isDd && item.seriesName === '组合净值' && excess != null
            ? `<small style="display:block;color:${colorOf(excess)}">超额 ${formatMarketPercent(excess)}</small>` : ''
          return chartTooltipRowHtml(
            `<span>${item.marker ?? ''}${item.seriesName ?? ''}</span>`,
            `<span style="text-align:right"><strong style="color:${colorOf(isDd ? val : r)}">${valText}</strong>${excessHtml}</span>`,
          )
        }).join('')
        return `<div style="min-width:150px;line-height:1.7">`
          + `<div style="color:${t.label};margin-bottom:2px">${date}</div>${content}</div>`
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: dates, axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { color: t.label, fontSize: 10 } },
      { type: 'category', gridIndex: 1, data: dates, axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { scale: true, axisLine: { show: false }, axisLabel: {
        color: t.label,
        fontSize: 10,
        formatter: (value: number) => formatMoney(value, { digits: 0, empty: '--' }),
      },
        splitLine: { lineStyle: { color: t.split } } },
      { gridIndex: 1, axisLine: { show: false }, splitNumber: 2,
        axisLabel: { color: t.label, fontSize: 10, formatter: formatMarketPercent },
        splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    series,
  }, { notMerge: true }) // 整图重建：切「不对比」时基准线 series 彻底移除，不被合并模式残留
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
    chart = initVectorEChart(el.value)
    render()
    attachResize()
  }
})
onActivated(() => { attachResize(); resize() })
onDeactivated(detachResize)
watch(() => props.points, render, { deep: true })
watch(() => props.extraBenchmark, render, { deep: true })
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
