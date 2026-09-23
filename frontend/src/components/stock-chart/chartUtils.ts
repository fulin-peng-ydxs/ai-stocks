import type { Bar } from '@/api/stocks'
import { formatMoney } from '@/utils/money'
import {
  chartCssVariable,
  echartsTheme,
  type EChartsTheme,
} from '@/components/chartTheme'
import {
  stockQuoteSummaryHtml,
  type StockQuoteSupplement,
  type StockQuoteTone,
} from './stockQuoteSummary'

export const STOCK_CHART_GRID_SIDE = 64
export const STOCK_CHART_GRID_TOP = 8
/** 光标短暂停留后再展示行情浮层，避免经过图表时遮挡内容。 */
export const STOCK_CHART_TOOLTIP_SHOW_DELAY_MS = 250

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
  volumeNeutral: string
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
    volumeNeutral: isDark ? '#ffffff' : base.label,
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

export function formatAmount(yuan: number | null | undefined, empty = '--'): string {
  if (yuan == null || !Number.isFinite(yuan)) return empty
  if (Math.abs(yuan) >= 1e8) return `${formatMoney(yuan / 1e8, { digits: 2, empty })}亿`
  if (Math.abs(yuan) >= 1e4) return `${formatMoney(yuan / 1e4, { digits: 0, empty })}万`
  return formatMoney(yuan, { digits: 0, empty })
}

export function formatVolume(shares: number | null | undefined): string {
  if (shares == null || !Number.isFinite(shares)) return '--'
  const lots = shares / 100
  if (lots >= 1e8) return `${(lots / 1e8).toFixed(2)}亿手`
  if (lots >= 1e4) return `${(lots / 1e4).toFixed(2)}万手`
  return `${lots.toFixed(0)}手`
}

/** 分钟行情统一以手传输，不再沿用日线“股转手”的格式化入口。 */
export function formatVolumeLots(lots: number | null | undefined): string {
  if (lots == null || !Number.isFinite(lots)) return '--'
  if (Math.abs(lots) >= 1e8) return `${(lots / 1e8).toFixed(2)}亿手`
  if (Math.abs(lots) >= 1e4) return `${(lots / 1e4).toFixed(2)}万手`
  return `${Number.isInteger(lots) ? lots.toFixed(0) : lots.toFixed(2)}手`
}

/** 股本数量按股展示，复用行情摘要的万/亿紧凑单位。 */
export function formatShares(shares: number | null | undefined, empty = '--'): string {
  if (shares == null || !Number.isFinite(shares)) return empty
  if (Math.abs(shares) >= 1e8) return `${formatMoney(shares / 1e8, { digits: 2, empty })}亿股`
  if (Math.abs(shares) >= 1e4) return `${formatMoney(shares / 1e4, { digits: 2, empty })}万股`
  return `${formatMoney(shares, { digits: 0, empty })}股`
}

/** 光标历史行情量比；只消费图表已加载数据，口径与详情最新行情接口一致。 */
export function stockVolumeRatioAt(bars: readonly Bar[], tradeDate: string): number | null {
  const index = bars.findIndex((bar) => bar.date === tradeDate)
  if (index < 0) return null
  const history = bars
    .slice(0, index)
    .map((bar) => bar.volume)
    .filter((volume) => Number.isFinite(volume) && volume > 0)
    .slice(-5)
  const current = bars[index]?.volume
  if (history.length !== 5 || current == null || !Number.isFinite(current)) return null
  const average = history.reduce((total, volume) => total + volume, 0) / history.length
  return average > 0 ? Math.round((current / average) * 100) / 100 : null
}

interface StockVolumeDatum {
  open: number | null
  close: number
  volume: number
}

interface StockVolumeBarSeriesInput {
  data: readonly StockVolumeDatum[]
  theme: Pick<StockChartTheme, 'up' | 'down' | 'label' | 'volumeNeutral'>
  directionReference?: 'open' | 'previous-close'
  initialReference?: number | null
  name?: string
  barWidth?: string
  barMaxWidth?: number
  xAxisIndex?: number
  yAxisIndex?: number
}

/** 日线与分时共用量柱外形；方向参考值由调用方按日线或分时口径显式声明。 */
export function buildStockVolumeBarSeries(input: StockVolumeBarSeriesInput) {
  return {
    name: input.name ?? '量能',
    type: 'bar' as const,
    ...(input.xAxisIndex == null ? {} : { xAxisIndex: input.xAxisIndex }),
    ...(input.yAxisIndex == null ? {} : { yAxisIndex: input.yAxisIndex }),
    ...(input.barWidth == null ? {} : { barWidth: input.barWidth }),
    ...(input.barMaxWidth == null ? {} : { barMaxWidth: input.barMaxWidth }),
    emphasis: { disabled: true },
    data: input.data.map((item, index) => {
      const previousClose = index > 0 ? input.data[index - 1]?.close : input.initialReference
      const reference = input.directionReference === 'previous-close'
        ? previousClose
        : item.open != null && item.open > 0 ? item.open : previousClose
      const color = reference == null
        ? input.theme.label
        : item.close === reference
          ? input.directionReference === 'previous-close' ? input.theme.volumeNeutral : input.theme.up
          : item.close > reference ? input.theme.up : input.theme.down
      return { value: item.volume, itemStyle: { color } }
    }),
  }
}

export function formatChartNumber(
  value: number | null | undefined,
  digits = 2,
  empty = '--',
): string {
  return formatMoney(value, { digits, empty })
}

/** 坐标轴统一精度，并把舍入后等于零的微小负值归一为正零。 */
export function formatChartAxisNumber(value: number, digits = 2): string {
  const zeroThreshold = 0.5 * 10 ** -digits
  return formatChartNumber(Math.abs(value) < zeroThreshold ? 0 : value, digits)
}

export interface StockChartAxisPointerEvent {
  axesInfo?: Array<{ value?: string | number }>
  seriesDataIndices?: Array<{ dataIndex?: number }>
}

/** 日线与分时共享光标索引解析，兼容 ECharts 返回序列索引、类目值或数值索引。 */
export function stockChartAxisPointerIndex(
  event: StockChartAxisPointerEvent,
  categories: readonly string[],
): number | null {
  if (!categories.length) return null
  const seriesIndex = event.seriesDataIndices?.[0]?.dataIndex
  if (typeof seriesIndex === 'number' && Number.isFinite(seriesIndex)) {
    return Math.max(0, Math.min(Math.round(seriesIndex), categories.length - 1))
  }
  const value = event.axesInfo?.[0]?.value
  if (typeof value === 'string') {
    const index = categories.indexOf(value)
    return index >= 0 ? index : null
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0, Math.min(Math.round(value), categories.length - 1))
  }
  return null
}

type KlineTooltipPalette = Pick<
  StockChartTheme,
  'text' | 'label' | 'up' | 'down' | 'tooltipBorder'
>

export interface TooltipPositionSize {
  contentSize: [number, number]
  viewSize: [number, number]
}

export interface TooltipTargetRect {
  x: number
  y: number
  width: number
  height: number
}

function tooltipTargetRect(value: unknown): TooltipTargetRect | null {
  const rect = value as Partial<TooltipTargetRect> | null
  if (!rect || ![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)) return null
  return rect as TooltipTargetRect
}

function overlapArea(
  left: number,
  top: number,
  width: number,
  height: number,
  rect: TooltipTargetRect | null,
): number {
  if (!rect) return 0
  const overlapWidth = Math.max(0, Math.min(left + width, rect.x + rect.width) - Math.max(left, rect.x))
  const overlapHeight = Math.max(0, Math.min(top + height, rect.y + rect.height) - Math.max(top, rect.y))
  return overlapWidth * overlapHeight
}

/** 保留光标避让，并在浮层覆盖当前蜡烛实体时选择重叠更少的一侧。 */
export function obstructionAwareTooltipPosition(
  point: number[],
  _params: unknown,
  _dom: HTMLElement,
  rectValue: unknown,
  size: TooltipPositionSize,
  displayScale = 1,
): [number, number] {
  const safeScale = Number.isFinite(displayScale) && displayScale > 0 ? displayScale : 1
  // Tooltip 挂到未缩放的 body 后，DOM 尺寸是视口像素；碰撞与停靠仍使用图表布局坐标。
  const contentWidth = Math.min(
    size.contentSize[0] / safeScale,
    Math.max(0, size.viewSize[0] - STOCK_CHART_GRID_SIDE * 2),
  )
  const contentHeight = size.contentSize[1] / safeScale
  const leftDock = Math.min(
    STOCK_CHART_GRID_SIDE,
    Math.max(0, size.viewSize[0] - contentWidth),
  )
  const rightDockLeft = Math.max(
    leftDock,
    size.viewSize[0] - STOCK_CHART_GRID_SIDE - contentWidth,
  )
  const overlapsLeftDock = point[0] >= leftDock && point[0] <= leftDock + contentWidth
  const targetRect = tooltipTargetRect(rectValue)
  const leftArea = overlapArea(
    leftDock, STOCK_CHART_GRID_TOP, contentWidth, contentHeight, targetRect,
  )
  const coversCandlestick = targetRect ? leftArea > 0 : false
  if (!overlapsLeftDock || !coversCandlestick) return [leftDock, STOCK_CHART_GRID_TOP]

  const rightArea = overlapArea(
    rightDockLeft, STOCK_CHART_GRID_TOP, contentWidth, contentHeight, targetRect,
  )
  return [rightArea <= leftArea ? rightDockLeft : leftDock, STOCK_CHART_GRID_TOP]
}

export function priceDirectionTone(
  value: number | null | undefined,
  reference: number | null | undefined,
): StockQuoteTone {
  if (value == null || reference == null || value === reference) return 'neutral'
  return value > reference ? 'up' : 'down'
}

/** K线详情统一格式：日期单独成行，行情字段按每列三项横向排布。 */
export function klineTooltipHtml(
  bar: Bar,
  palette: KlineTooltipPalette,
  supplement?: StockQuoteSupplement | null,
): string {
  const pct = bar.pre_close ? ((bar.close - bar.pre_close) / bar.pre_close) * 100 : null
  const amplitude = bar.pre_close ? ((bar.high - bar.low) / bar.pre_close) * 100 : null
  const pctText = pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`

  const tone: StockQuoteTone = pct == null || pct === 0 ? 'neutral' : pct > 0 ? 'up' : 'down'
  return stockQuoteSummaryHtml({
    time: bar.date,
    hero: { label: '', value: formatChartNumber(bar.close), tone },
    rowsPerColumn: 4,
    supplement,
    metrics: [
      { label: '开盘', value: formatChartNumber(bar.open), tone: priceDirectionTone(bar.open, bar.pre_close) },
      { label: '最高', value: formatChartNumber(bar.high), tone: priceDirectionTone(bar.high, bar.pre_close) },
      { label: '最低', value: formatChartNumber(bar.low), tone: priceDirectionTone(bar.low, bar.pre_close) },
      { label: '涨幅', value: pctText, tone },
      { label: '振幅', value: amplitude == null ? '--' : `${amplitude.toFixed(2)}%` },
      { label: '换手率', value: bar.turnover_rate == null ? '--' : `${bar.turnover_rate.toFixed(2)}%` },
      { label: '成交量', value: formatVolume(bar.volume) },
      { label: '成交额', value: formatAmount(bar.amount) },
    ],
  }, { ...palette, border: palette.tooltipBorder })
}
