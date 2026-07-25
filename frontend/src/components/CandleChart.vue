<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { Bar } from '@/api/stocks'
import { useTheme } from '@/composables/useTheme'
import {
  formatVolume,
  klineTooltipHtml,
  movingAverage,
  stockChartTheme,
} from '@/components/stock-chart/chartUtils'

// 交易标记：在 K 线上标出买卖点（date=交易日, kind=买/卖, label=多行说明文本）
export interface TradeMarker {
  date: string
  kind: 'buy' | 'sell'
  label: string
}

const props = defineProps<{
  bars: Bar[]           // 展示用 bar，直接渲染到 ECharts（由父组件按范围切好）
  warmupBars?: Bar[]    // 热身用历史 bar，仅参与 MA 计算，不渲染到图表
  markers?: TradeMarker[]
  zoomStart?: number
  zoomEnd?: number
}>()
const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeListening = false
const { isDark } = useTheme()

// 买卖标记色（刻意避开蜡烛红绿，免混淆）：买=蓝、卖=橙
const BUY_COLOR = '#3b82f6'
const SELL_COLOR = '#f5a623'

// 兼容图表保留既有均线色；MA60 复用工作区的主题黄色，避免同一指标跨页面漂移。
const MA_DEFS = computed(() => [
  { n: 5, color: isDark.value ? '#dfe4ea' : '#606266' },
  { n: 10, color: '#f5a623' },
  { n: 20, color: '#d63bd6' },
  { n: 30, color: '#16b8c4' },
  { n: 60, color: stockChartTheme(isDark.value).series.kline.ma60 },
])
// 主题色板
const T = computed(() => {
  const theme = stockChartTheme(isDark.value)
  return {
    bg: theme.background,
    axis: theme.axis,
    split: theme.split,
    label: theme.label,
    mark: theme.text,
    tipBg: theme.tooltipBackground,
    tipBorder: theme.tooltipBorder,
    tipText: theme.text,
    tipKey: theme.label,
    zoom: theme.axis,
    up: theme.up,
    down: theme.down,
  }
})
const wrapBg = computed(() => T.value.bg)
const legLabelColor = computed(() => T.value.label)
const legValColor = computed(() => T.value.tipText)

// 跟随光标的索引（驱动顶部 MA 数值条），null=取最后一根
const hoverIdx = ref<number | null>(null)
const lastIdx = computed(() => props.bars.length - 1)
const activeIdx = computed(() => hoverIdx.value ?? lastIdx.value)

// warmupBars 在前，bars 在后拼接，计算完整 MA 后只取尾部 bars.length 个值用于展示
const allCloses = computed(() => [...(props.warmupBars ?? []), ...props.bars].map((b) => b.close))
const maSeries = computed(() =>
  MA_DEFS.value.map((d) => {
    const full = movingAverage(allCloses.value, d.n)
    return { ...d, data: full.slice(full.length - props.bars.length) }
  }),
)

// 顶部 MA 数值条（随光标更新）
const maLabels = computed(() =>
  maSeries.value.map((m) => ({
    n: m.n,
    color: m.color,
    val: m.data[activeIdx.value] != null ? m.data[activeIdx.value]!.toFixed(2) : '--',
  })),
)

// 量能均线（VMA5/VMA10）颜色 + 随光标更新的数值（供 HTML 图例叠加层）
const VMA5_COLOR = '#f5a623'
const VMA10_COLOR = '#16b8c4'
const allVolumes = computed(() => [...(props.warmupBars ?? []), ...props.bars].map((b) => b.volume))
const volMa5Arr = computed(() => { const f = movingAverage(allVolumes.value, 5); return f.slice(f.length - props.bars.length) })
const volMa10Arr = computed(() => { const f = movingAverage(allVolumes.value, 10); return f.slice(f.length - props.bars.length) })
const volLabels = computed(() => {
  const i = activeIdx.value
  const b = props.bars[i]
  const f = (v: number | null) => (v != null ? formatVolume(v) : '--')
  return {
    total: b ? formatVolume(b.volume) : '--',
    ma5: f(volMa5Arr.value[i] ?? null),
    ma10: f(volMa10Arr.value[i] ?? null),
  }
})

function render() {
  if (!chart) return
  const zStart = props.zoomStart ?? 0
  const zEnd = props.zoomEnd ?? 100
  const bars = props.bars
  const dates = bars.map((b) => b.date)
  const kline = bars.map((b) => [b.open, b.close, b.low, b.high]) // ECharts: 开收低高
  const vols = bars.map((b) => ({
    value: b.volume,
    itemStyle: { color: b.close >= b.open ? T.value.up : T.value.down },
  }))
  const volMa5 = volMa5Arr.value
  const volMa10 = volMa10Arr.value

  const maLineSeries = maSeries.value.map((m) => ({
    name: `MA${m.n}`,
    type: 'line' as const,
    data: m.data,
    smooth: false,
    showSymbol: false,
    lineStyle: { width: 1, color: m.color },
    z: 3,
  }))

  // 买卖点标记：买=蓝色▲(置于最低价下方)，卖=橙色▼(置于最高价上方)，带多行说明
  const idxByDate = new Map(bars.map((b, i) => [b.date, i]))
  const tradeMarks = (props.markers ?? [])
    .map((m) => {
      const i = idxByDate.get(m.date)
      if (i == null) return null
      const b = bars[i]
      const isBuy = m.kind === 'buy'
      const color = isBuy ? BUY_COLOR : SELL_COLOR
      return {
        coord: [i, isBuy ? b.low * 0.985 : b.high * 1.015],
        symbol: 'triangle', symbolRotate: isBuy ? 0 : 180, symbolSize: 12,
        itemStyle: { color, borderColor: '#fff', borderWidth: 1 },
        label: {
          show: true, position: isBuy ? 'bottom' : 'top', color, fontSize: 10,
          fontWeight: 600, lineHeight: 13, formatter: m.label,
        },
      }
    })
    .filter(Boolean)

  const t = T.value
  chart.setOption({
    animation: false,
    backgroundColor: t.bg,
    grid: [
      { left: 8, right: 64, top: 16, height: '62%' },
      { left: 8, right: 64, top: '74%', height: '17%' },
    ],
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: t.axis },
      lineStyle: { color: t.label, type: 'dashed' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      // 钉在左上角的详细数据框
      position: () => [10, 6],
      backgroundColor: t.tipBg,
      borderColor: t.tipBorder,
      borderWidth: 1,
      textStyle: { color: t.tipText, fontSize: 12 },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params : [params]
        const idx = p[0]?.dataIndex
        if (idx == null) return ''
        hoverIdx.value = idx
        return klineTooltipHtml(bars[idx], {
          text: t.tipText,
          label: t.tipKey,
          up: t.up,
          down: t.down,
        })
      },
    },
    xAxis: [
      {
        type: 'category', data: dates, boundaryGap: true,
        axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { color: t.label, fontSize: 10 },
        splitLine: { show: false },
      },
      {
        type: 'category', gridIndex: 1, data: dates,
        axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { show: false }, axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true, position: 'right',
        axisLine: { show: false },
        axisLabel: { color: t.label, fontSize: 10 },
        splitLine: { lineStyle: { color: t.split } },
      },
      {
        gridIndex: 1, scale: true, position: 'right', splitNumber: 2,
        axisLine: { show: false },
        axisLabel: { color: t.label, fontSize: 10, formatter: (v: number) => formatVolume(v) },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: zStart, end: zEnd },
      {
        type: 'slider', xAxisIndex: [0, 1], bottom: 2, height: 16, start: zStart, end: zEnd,
        borderColor: t.zoom, fillerColor: 'rgba(64,158,255,0.18)',
        textStyle: { color: t.label },
      },
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: kline,
        itemStyle: {
          color: t.up,
          color0: t.down,
          borderColor: t.up,
          borderColor0: t.down,
        },
        markPoint: {
          symbolSize: 0,
          data: [
            ...(bars.length
              ? [{
                  name: '最新', coord: [bars.length - 1, bars[bars.length - 1].close],
                  value: bars[bars.length - 1].close, symbol: 'rect', symbolSize: 0,
                  label: { show: true, position: 'right', color: t.mark, fontSize: 11,
                           formatter: (pm: any) => '← ' + Number(pm.value).toFixed(2) },
                }]
              : []),
            ...tradeMarks,
          ],
        },
      },
      ...maLineSeries,
      { name: '量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, z: 1 },
      {
        name: 'VMA5', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: volMa5,
        showSymbol: false, lineStyle: { width: 1.4, color: VMA5_COLOR },
      },
      {
        name: 'VMA10', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: volMa10,
        showSymbol: false, lineStyle: { width: 1.4, color: VMA10_COLOR },
      },
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
    chart.on('globalout', () => { hoverIdx.value = null })
    attachResize()
  }
})
onActivated(() => { attachResize(); resize() })
onDeactivated(detachResize)
watch(() => props.bars, () => { hoverIdx.value = null; render() }, { deep: true })
watch(() => props.warmupBars, () => render(), { deep: true })
watch(() => props.markers, () => render(), { deep: true })
watch(() => [props.zoomStart, props.zoomEnd], () => render())
watch(isDark, () => render()) // 主题切换重渲染
onBeforeUnmount(() => {
  detachResize()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="candle-wrap">
    <!-- 顶部 MA 数值条（随光标更新） -->
    <div class="ma-bar">
      <span v-for="m in maLabels" :key="m.n" :style="{ color: m.color }">
        MA{{ m.n }}:{{ m.val }}
      </span>
    </div>
    <div class="chart-area">
      <div ref="el" class="candle" />
      <!-- 量能均线图例（HTML 叠加层，内联色，夜间可靠；随光标更新） -->
      <div class="vol-legend">
        <span :style="{ color: legLabelColor }">量能</span>
        <span :style="{ color: legValColor }">总量 {{ volLabels.total }}</span>
        <span :style="{ color: VMA5_COLOR }">MA5 {{ volLabels.ma5 }}</span>
        <span :style="{ color: VMA10_COLOR }">MA10 {{ volLabels.ma10 }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.candle-wrap {
  background: v-bind(wrapBg);
  border-radius: 6px;
  padding: 6px 8px 2px;
}
.ma-bar {
  display: flex;
  gap: var(--app-space-4);
  font-size: var(--app-font-size-caption);
  font-weight: var(--app-font-weight-section);
  padding: 2px 4px 4px;
  font-variant-numeric: tabular-nums;
}
.chart-area {
  position: relative;
}
.candle {
  width: 100%;
  height: 480px;
}
.vol-legend {
  position: absolute;
  top: 350px; /* 量能区 grid top 74% × 480 ≈ 355，置于其上方 */
  left: 12px;
  display: flex;
  gap: var(--app-space-3);
  font-size: var(--app-font-size-micro);
  font-weight: var(--app-font-weight-section);
  font-variant-numeric: tabular-nums;
  pointer-events: none;
  z-index: 5;
}
</style>
