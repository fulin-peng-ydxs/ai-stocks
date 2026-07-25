import type { Bar } from '@/api/stocks'

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

export interface StockChartTheme {
  background: string
  axis: string
  split: string
  label: string
  text: string
  tooltipBackground: string
  tooltipBorder: string
  up: string
  down: string
  series: StockChartSeriesPalette
  focus: string
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

function cssVariable(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

/**
 * 盘感训练既有色板是股票指标序列的唯一身份色事实源。
 * 固定序列色不表达涨跌方向；蜡烛、柱体和信号方向仍使用 market token。
 */
export function trainingChartSeriesPalette(isDark: boolean): StockChartSeriesPalette {
  return {
    kline: {
      ma5: isDark ? '#dfe4ea' : '#606266',
      ma10: isDark ? '#f5a623' : '#9a5b00',
      ma20: isDark ? '#d63bd6' : '#9c2aa0',
      ma30: isDark ? '#16b8c4' : '#0b7580',
      ma60: isDark ? '#ff7a18' : '#b54708',
    },
    volume: {
      ma5: isDark ? '#f5a623' : '#9a5b00',
      ma10: isDark ? '#16b8c4' : '#0b7580',
    },
    macd: {
      diff: isDark ? '#f5a623' : '#9a5b00',
      dea: isDark ? '#16b8c4' : '#0b7580',
    },
  }
}

export function stockChartTheme(isDark: boolean): StockChartTheme {
  const primary = cssVariable('--el-color-primary', '#409eff')
  const up = cssVariable('--market-up-color', isDark ? '#ff6b6b' : '#ef4d4d')
  const down = cssVariable('--market-down-color', isDark ? '#45c486' : '#22b573')

  return {
    background: cssVariable('--el-bg-color', isDark ? '#0b0e16' : '#ffffff'),
    axis: cssVariable('--el-border-color', isDark ? '#2b3550' : '#dcdfe6'),
    split: cssVariable('--el-border-color-lighter', isDark ? '#161c28' : '#ebeef5'),
    label: cssVariable('--el-text-color-secondary', isDark ? '#8b94a7' : '#909399'),
    text: cssVariable('--el-text-color-primary', isDark ? '#c9d1d9' : '#303133'),
    tooltipBackground: cssVariable(
      '--el-bg-color-overlay',
      isDark ? 'rgba(13,17,26,0.96)' : 'rgba(255,255,255,0.96)',
    ),
    tooltipBorder: cssVariable('--el-border-color', isDark ? '#2b3550' : '#dcdfe6'),
    up,
    down,
    series: trainingChartSeriesPalette(isDark),
    focus: primary,
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
  if (yuan >= 1e8) return `${(yuan / 1e8).toFixed(2)}亿`
  if (yuan >= 1e4) return `${(yuan / 1e4).toFixed(0)}万`
  return yuan.toFixed(0)
}

export function formatVolume(shares: number | null | undefined): string {
  if (shares == null || !Number.isFinite(shares)) return '--'
  const lots = shares / 100
  if (lots >= 1e8) return `${(lots / 1e8).toFixed(2)}亿手`
  if (lots >= 1e4) return `${(lots / 1e4).toFixed(2)}万手`
  return `${lots.toFixed(0)}手`
}

export function formatChartNumber(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '--' : value.toFixed(digits)
}

type KlineTooltipPalette = Pick<StockChartTheme, 'text' | 'label' | 'up' | 'down'>

function tooltipRow(label: string, value: string, palette: KlineTooltipPalette, color?: string) {
  return `<div style="display:flex;justify-content:space-between;gap:18px">`
    + `<span style="color:${palette.label}">${label}</span>`
    + `<span style="color:${color ?? palette.text}">${value}</span>`
    + '</div>'
}

/** K线详情统一格式：固定字段、A股涨跌色和紧凑双列布局由新旧图表共同复用。 */
export function klineTooltipHtml(bar: Bar, palette: KlineTooltipPalette): string {
  const pct = bar.pre_close ? ((bar.close - bar.pre_close) / bar.pre_close) * 100 : null
  const amplitude = bar.pre_close ? ((bar.high - bar.low) / bar.pre_close) * 100 : null
  const directionColor = pct == null || pct === 0
    ? palette.text
    : pct > 0 ? palette.up : palette.down
  const pctText = pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`

  return '<div style="min-width:150px;line-height:1.6">'
    + tooltipRow('时间', bar.date, palette)
    + tooltipRow('开盘', formatChartNumber(bar.open), palette)
    + tooltipRow('收盘', formatChartNumber(bar.close), palette, directionColor)
    + tooltipRow('最高', formatChartNumber(bar.high), palette)
    + tooltipRow('最低', formatChartNumber(bar.low), palette)
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
