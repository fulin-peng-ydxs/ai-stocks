import { chartCssVariable, type EChartsTheme } from '@/components/chartTheme'

interface NamedSeries {
  name: string
  [key: string]: unknown
}

interface MarketCompareLineOptionInput {
  theme: EChartsTheme
  colors: string[]
  dates: string[]
  series: NamedSeries[]
  tooltipFormatter: (params: unknown) => string
  scrollLegend?: boolean
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
  const { theme, colors, dates, series, tooltipFormatter, scrollLegend = false } = input
  return {
    animation: false,
    backgroundColor: theme.background,
    color: colors,
    grid: { left: 56, right: 24, top: 40, bottom: 58 },
    legend: {
      data: series.map((item) => item.name),
      top: 4,
      ...(scrollLegend ? { type: 'scroll' as const } : {}),
      textStyle: { color: theme.label, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: theme.text, fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: theme.axis } },
      formatter: tooltipFormatter,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.label, fontSize: 10 },
    },
    yAxis: {
      scale: true,
      axisLine: { show: false },
      axisLabel: { color: theme.label, fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: theme.split } },
    },
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
