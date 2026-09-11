import type { Bar } from '@/api/stocks'
import { formatMoney } from '@/utils/money'
import {
  chartCssVariable,
  echartsTheme,
  type EChartsTheme,
} from '@/components/chartTheme'

export interface StockChartSeriesPalette {
  kline: {
    ma5: string
    ma10: string
    ma20: string
    ma30: string
    ma60: string
  }
  volume: {
    ma5: string
    ma10: string
  }
  macd: {
    diff: string
    dea: string
  }
}

export interface StockChartTheme extends EChartsTheme {
  up: string
  down: string
  series: StockChartSeriesPalette
}

export type KlineMaPaletteKey = keyof StockChartSeriesPalette['kline']
export type VolumeMaPaletteKey = keyof StockChartSeriesPalette['volume']

export interface KlineMaDefinition {
  period: number
  label: string
  paletteKey: KlineMaPaletteKey
}

export interface VolumeMaDefinition {
  period: number
  label: string
  seriesName: string
  paletteKey: VolumeMaPaletteKey
}

/** 股票 K 线均线的周期、标题和色板键统一事实源。 */
export const KLINE_MA_DEFINITIONS = [
  { period: 5, label: 'MA5', paletteKey: 'ma5' },
  { period: 10, label: 'MA10', paletteKey: 'ma10' },
  { period: 20, label: 'MA20', paletteKey: 'ma20' },
  { period: 30, label: 'MA30', paletteKey: 'ma30' },
  { period: 60, label: 'MA60', paletteKey: 'ma60' },
] as const satisfies readonly KlineMaDefinition[]

/** 股票量能均线的周期、标题、ECharts 名称和色板键统一事实源。 */
export const VOLUME_MA_DEFINITIONS = [
  { period: 5, label: 'MA5', seriesName: 'VMA5', paletteKey: 'ma5' },
  { period: 10, label: 'MA10', seriesName: 'VMA10', paletteKey: 'ma10' },
] as const satisfies readonly VolumeMaDefinition[]

let workspaceGroupSequence = 0

/** 模块级递增，确保同一页面并存的多个工作区不会误连到同一 ECharts group。 */
export function nextStockChartWorkspaceGroupId(): string {
  workspaceGroupSequence += 1
  return `stock-chart-workspace-${workspaceGroupSequence}`
}

/**
 * 盘感训练既有色板是股票指标序列的唯一身份色事实源。
 * 固定序列色不表达涨跌方向；蜡烛、柱体和信号方向仍使用 market token。
 */
export function trainingChartSeriesPalette(isDark: boolean): StockChartSeriesPalette {
  return {
    kline: {
      ma5: '#e28a35',
      ma10: '#418af5',
      ma20: isDark ? '#c53c92' : '#9f3793',
      ma30: '#56c3df',
      ma60: '#e56023',
    },
    volume: {
      ma5: '#e28a35',
      ma10: '#418af5',
    },
    macd: {
      diff: '#e28a35',
      dea: '#418af5',
    },
  }
}

export function stockChartTheme(isDark: boolean): StockChartTheme {
  const base = echartsTheme(isDark)
  const up = chartCssVariable('--market-up-color', isDark ? '#ff7a72' : '#f66055')
  const down = chartCssVariable('--market-down-color', isDark ? '#3fdd90' : '#1ec96e')

  return {
    ...base,
    up,
    down,
    series: trainingChartSeriesPalette(isDark),
  }
}

/** 后向移动平均；暖机不足返回 null，不读取当日之后的数据。 */
export function movingAverage(values: number[], period: number): (number | null)[] {
  return values.map((_, index) => {
    if (index + 1 < period) return null
    let total = 0
    for (let cursor = index + 1 - period; cursor <= index; cursor += 1) {
      total += values[cursor]
    }
    return +(total / period).toFixed(2)
  })
}

export function formatAmount(yuan: number | null | undefined): string {
  if (yuan == null || !Number.isFinite(yuan)) return '--'
  if (Math.abs(yuan) >= 1e8) return `${formatMoney(yuan / 1e8, { digits: 2, empty: '--' })}亿`
  if (Math.abs(yuan) >= 1e4) return `${formatMoney(yuan / 1e4, { digits: 0, empty: '--' })}万`
  return formatMoney(yuan, { digits: 0, empty: '--' })
}

export function formatVolume(shares: number | null | undefined): string {
  if (shares == null || !Number.isFinite(shares)) return '--'
  const lots = shares / 100
  if (lots >= 1e8) return `${(lots / 1e8).toFixed(2)}亿手`
  if (lots >= 1e4) return `${(lots / 1e4).toFixed(2)}万手`
  return `${lots.toFixed(0)}手`
}

export function formatChartNumber(value: number | null | undefined, digits = 2): string {
  return formatMoney(value, { digits, empty: '--' })
}

/** 坐标轴统一精度，并把舍入后等于零的微小负值归一为正零。 */
export function formatChartAxisNumber(value: number, digits = 2): string {
  const zeroThreshold = 0.5 * 10 ** -digits
  return formatChartNumber(Math.abs(value) < zeroThreshold ? 0 : value, digits)
}

type KlineTooltipPalette = Pick<StockChartTheme, 'text' | 'label' | 'up' | 'down'>

function tooltipRow(label: string, value: string, palette: KlineTooltipPalette, color?: string) {
  return `<div style="display:flex;justify-content:space-between;gap:18px">`
    + `<span style="color:${palette.label}">${label}</span>`
    + `<span style="color:${color ?? palette.text}">${value}</span>`
    + '</div>'
}

interface TooltipPositionSize {
  contentSize: [number, number]
  viewSize: [number, number]
}

/** 行情浮层固定靠光标反侧展示，避免覆盖正在查看的蜡烛。 */
export function oppositeSideTooltipPosition(
  point: number[],
  _params: unknown,
  _dom: HTMLElement,
  _rect: unknown,
  size: TooltipPositionSize,
): [number, number] {
  const horizontalInset = 8
  const contentWidth = Math.min(
    size.contentSize[0],
    Math.max(0, size.viewSize[0] - horizontalInset * 2),
  )
  const left = point[0] <= size.viewSize[0] / 2
    ? size.viewSize[0] - contentWidth - horizontalInset
    : horizontalInset
  return [Math.max(horizontalInset, left), 6]
}

function priceDirectionColor(
  value: number | null | undefined,
  reference: number | null | undefined,
  palette: KlineTooltipPalette,
): string {
  if (value == null || reference == null || value === reference) return palette.text
  return value > reference ? palette.up : palette.down
}

/** K线详情统一格式：固定字段、A股涨跌色和紧凑双列布局由新旧图表共同复用。 */
export function klineTooltipHtml(bar: Bar, palette: KlineTooltipPalette): string {
  const pct = bar.pre_close ? ((bar.close - bar.pre_close) / bar.pre_close) * 100 : null
  const amplitude = bar.pre_close ? ((bar.high - bar.low) / bar.pre_close) * 100 : null
  const directionColor = pct == null || pct === 0
    ? palette.text
    : pct > 0 ? palette.up : palette.down
  const pctText = pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`

  return '<div style="width:156px;box-sizing:border-box;line-height:1.6">'
    + tooltipRow('时间', bar.date, palette)
    + tooltipRow(
      '开盘', formatChartNumber(bar.open), palette,
      priceDirectionColor(bar.open, bar.pre_close, palette),
    )
    + tooltipRow('收盘', formatChartNumber(bar.close), palette, directionColor)
    + tooltipRow(
      '最高', formatChartNumber(bar.high), palette,
      priceDirectionColor(bar.high, bar.pre_close, palette),
    )
    + tooltipRow(
      '最低', formatChartNumber(bar.low), palette,
      priceDirectionColor(bar.low, bar.pre_close, palette),
    )
    + tooltipRow('涨幅', pctText, palette, directionColor)
    + tooltipRow(
      '振幅',
      amplitude == null ? '--' : `${amplitude.toFixed(2)}%`,
      palette,
    )
    + tooltipRow('成交量', formatVolume(bar.volume), palette)
    + tooltipRow('成交额', formatAmount(bar.amount), palette)
    + tooltipRow(
      '换手率',
      bar.turnover_rate == null ? '--' : `${bar.turnover_rate.toFixed(2)}%`,
      palette,
    )
    + '</div>'
}
