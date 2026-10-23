import { chartCssVariable, type EChartsTheme } from '@/components/chartTheme'
import { formatMarketPercent } from '@/utils/marketValue'
import { marketAxisLabelColor, marketAxisPointerLabel } from '@/components/chartAxisLabel'

interface NamedSeries {
  name: string
  data?: readonly unknown[] | null
  [key: string]: unknown
}

interface MarketCompareLineOptionInput {
  theme: EChartsTheme
  colors: string[]
  dates: string[]
  series: NamedSeries[]
  tooltipFormatter: (params: unknown) => string
  scrollLegend?: boolean
  /** 百分比 0 对应的主观察对象具体值；左轴据此反算价格/指数点位。 */
  concreteValueBase?: number | null
}

function percentExtent(series: NamedSeries[]): { min: number; max: number } {
  const values = series.flatMap((item) => (item.data ?? []).flatMap((datum) => {
    const candidate = typeof datum === 'object' && datum != null && 'value' in datum
      ? (datum as { value?: unknown }).value
      : datum
    const value = Number(candidate)
    return candidate != null && Number.isFinite(value) ? [value] : []
  }))
  if (!values.length) return { min: -1, max: 1 }
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)
  const padding = rawMin === rawMax
    ? Math.max(Math.abs(rawMin) * 0.08, 1)
    : Math.max((rawMax - rawMin) * 0.08, 0.25)
  return {
    min: Number((rawMin - padding).toFixed(4)),
    max: Number((rawMax + padding).toFixed(4)),
  }
}

function concreteValueFormatter(base: number | null | undefined) {
  return (percentage: number) => {
    if (base == null || !Number.isFinite(base) || base <= 0) return '--'
    return (base * (1 + percentage / 100)).toFixed(2)
  }
}

/** 股票与板块走势统一消费同一序列色顺序，避免相同对象跨页面变色。 */
export function marketCompareLineColors(theme: EChartsTheme): string[] {
  return [
    theme.focus,
    theme.accent,
    chartCssVariable('--el-color-success', theme.focus),
    chartCssVariable('--el-color-danger', theme.accent),
    chartCssVariable('--el-color-info', theme.label),
    chartCssVariable('--shell-accent', theme.focus),
  ]
}

/** Canvas tooltip 的动态文本必须转义，调用方只负责拼装领域字段。 */
export function escapeChartHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

/** 涨跌色属于金融语义，与折线序列身份色分开。 */
export function marketCompareChangeColors(theme: EChartsTheme) {
  return {
    up: chartCssVariable('--market-up-color', '#f66055'),
    down: chartCssVariable('--market-down-color', '#1ec96e'),
    neutral: theme.text,
  }
}

/** 两类价格走势共享坐标轴、缩放、图例和 tooltip 外壳，领域组件只提供序列与内容。 */
export function buildMarketCompareLineOption(input: MarketCompareLineOptionInput) {
  const {
    theme,
    colors,
    dates,
    series,
    tooltipFormatter,
    scrollLegend = false,
    concreteValueBase,
  } = input
  const extent = percentExtent(series)
  const axisColors = { ...theme, ...marketCompareChangeColors(theme) }
  const labelColor = marketAxisLabelColor(axisColors)
  return {
    animation: false,
    backgroundColor: theme.background,
    color: colors,
    grid: { left: 56, right: 56, top: 40, bottom: 58 },
    legend: {
      data: series.map((item) => item.name),
      top: 4,
      ...(scrollLegend ? { type: 'scroll' as const } : {}),
      textStyle: { color: theme.label, fontSize: theme.typography.compact },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: theme.text, fontSize: theme.typography.body },
      axisPointer: { type: 'cross', label: { backgroundColor: theme.axis } },
      formatter: tooltipFormatter,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.label, fontSize: theme.typography.axis },
    },
    yAxis: [
      {
        type: 'value',
        position: 'left',
        scale: true,
        ...extent,
        axisLine: { show: false },
        axisLabel: {
          show: concreteValueBase != null && Number.isFinite(concreteValueBase) && concreteValueBase > 0,
          color: labelColor,
          fontSize: theme.typography.axis,
          formatter: concreteValueFormatter(concreteValueBase),
        },
        axisPointer: {
          label: marketAxisPointerLabel(axisColors, concreteValueFormatter(concreteValueBase),
            concreteValueBase != null && Number.isFinite(concreteValueBase) && concreteValueBase > 0
              ? 0 : null),
        },
        splitLine: { lineStyle: { color: theme.split } },
      },
      {
        type: 'value',
        position: 'right',
        scale: true,
        ...extent,
        axisLine: { show: false },
        axisLabel: { color: labelColor, fontSize: theme.typography.axis, formatter: formatMarketPercent },
        axisPointer: { label: marketAxisPointerLabel(axisColors, formatMarketPercent) },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      {
        type: 'slider',
        bottom: 6,
        height: 18,
        start: 0,
        end: 100,
        borderColor: theme.axis,
        fillerColor: theme.area,
        textStyle: { color: theme.label },
      },
    ],
    series,
  }
}
