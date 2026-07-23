import type { Bar, IndicatorRow } from '@/api/stocks'
import type { ChartType } from '@/composables/useStockChartPreferences'
import {
  formatAmount,
  formatChartNumber,
  formatVolume,
  movingAverage,
  type StockChartTheme,
} from './chartUtils'

export type WorkspacePanelKey = 'kline' | 'slot2' | 'slot3'
export type MacdPanelState = 'ready' | 'loading' | 'insufficient' | 'error'

export interface AlignedStockChartRow {
  bar: Bar
  indicator?: IndicatorRow
}

export interface SignalDatum {
  value: [number, number, number, 0 | 1]
  signalType: '金叉' | '死叉'
  tradeDate: string
  color: string
}

export const KLINE_MIN_HEIGHT = 250
export const AUXILIARY_MIN_HEIGHT = 126
export const WORKSPACE_MIN_HEIGHT = 650
export const SPLITTER_SIZE = 8
export const KEYBOARD_RATIO_STEP = 0.02

export function alignStockChartRows(
  bars: readonly Bar[],
  indicators: readonly IndicatorRow[],
): AlignedStockChartRow[] {
  const byDate = new Map(indicators.map((row) => [row.trade_date, row]))
  return bars.map((bar) => ({ bar, indicator: byDate.get(bar.date) }))
}

export function panelMinHeight(type: ChartType): number {
  return type === 'kline' ? KLINE_MIN_HEIGHT : AUXILIARY_MIN_HEIGHT
}

export function normalizeWorkspaceRatios(value: readonly number[], count: number): number[] {
  const fallback = count === 3 ? [0.6, 0.2, 0.2] : count === 2 ? [0.75, 0.25] : [1]
  if (
    value.length !== count
    || !value.every((item) => Number.isFinite(item) && item > 0)
  ) return fallback
  const total = value.reduce((sum, item) => sum + item, 0)
  if (!Number.isFinite(total) || total <= 0) return fallback
  return value.map((item) => item / total)
}

export function adjustAdjacentRatios(
  ratios: readonly number[],
  separatorIndex: number,
  delta: number,
  minRatios: readonly number[],
): number[] {
  const next = [...ratios]
  const firstIndex = separatorIndex
  const secondIndex = separatorIndex + 1
  if (
    firstIndex < 0
    || secondIndex >= next.length
    || minRatios.length !== next.length
  ) return next
  const pairTotal = next[firstIndex] + next[secondIndex]
  const first = Math.min(
    pairTotal - minRatios[secondIndex],
    Math.max(minRatios[firstIndex], next[firstIndex] + delta),
  )
  next[firstIndex] = first
  next[secondIndex] = pairTotal - first
  return normalizeWorkspaceRatios(next, next.length)
}

export function buildSignalData(
  rows: readonly AlignedStockChartRow[],
  theme: StockChartTheme,
): SignalDatum[] {
  let goldenLane = 0
  let deadLane = 0
  const signals: SignalDatum[] = []
  rows.forEach((row, index) => {
    const diff = row.indicator?.macd_diff
    if (diff == null || !Number.isFinite(diff)) return
    if (row.indicator?.macd_golden_cross === true) {
      signals.push({
        value: [index, diff, goldenLane++ % 3, 1],
        signalType: '金叉',
        tradeDate: row.bar.date,
        color: theme.up,
      })
    }
    if (row.indicator?.macd_dead_cross === true) {
      signals.push({
        value: [index, diff, deadLane++ % 3, 0],
        signalType: '死叉',
        tradeDate: row.bar.date,
        color: theme.down,
      })
    }
  })
  return signals
}

export function signalRenderGeometry(
  coord: [number, number],
  coordTop: number,
  coordBottom: number,
  lane: number,
  isGolden: boolean,
) {
  const x = coord[0]
  const anchorY = coord[1]
  const labelCenterY = isGolden
    ? coordTop + 17 + lane * 23
    : coordBottom - 17 - lane * 23
  const labelTop = labelCenterY - 9
  const lineStartY = isGolden ? labelTop + 18 : labelTop
  return { x, anchorY, labelCenterY, labelTop, lineStartY }
}

export function buildSignalSeries(
  rows: readonly AlignedStockChartRow[],
  theme: StockChartTheme,
) {
  return {
    name: 'MACD交叉信号',
    type: 'custom' as const,
    coordinateSystem: 'cartesian2d' as const,
    silent: false,
    clip: false,
    z: 8,
    data: buildSignalData(rows, theme),
    tooltip: {
      formatter: (params: { data?: SignalDatum }) => {
        const datum = params.data
        return datum ? `${datum.signalType}<br/>交易日：${datum.tradeDate}` : ''
      },
    },
    renderItem: (
      params: { coordSys: { y: number, height: number } },
      api: {
        value: (dimension: number) => number
        coord: (value: [number, number]) => [number, number]
        style: (style: Record<string, unknown>) => Record<string, unknown>
      },
    ) => {
      const isGolden = api.value(3) === 1
      const coord = api.coord([api.value(0), api.value(1)])
      const geometry = signalRenderGeometry(
        coord,
        params.coordSys.y,
        params.coordSys.y + params.coordSys.height,
        api.value(2),
        isGolden,
      )
      const color = isGolden ? theme.up : theme.down
      const label = isGolden ? '金叉' : '死叉'
      return {
        type: 'group',
        children: [
          {
            type: 'line',
            shape: {
              x1: geometry.x,
              x2: geometry.x,
              y1: geometry.lineStartY,
              y2: geometry.anchorY,
            },
            style: { stroke: color, lineWidth: 1.3 },
          },
          {
            type: 'circle',
            shape: { cx: geometry.x, cy: geometry.anchorY, r: 3 },
            style: { fill: color, stroke: theme.background, lineWidth: 1 },
          },
          {
            type: 'rect',
            shape: {
              x: geometry.x - 18,
              y: geometry.labelTop,
              width: 36,
              height: 18,
              r: 5,
            },
            style: { fill: color, opacity: 0.96 },
          },
          {
            type: 'text',
            style: api.style({
              x: geometry.x,
              y: geometry.labelCenterY,
              text: label,
              fill: '#ffffff',
              fontSize: 10,
              fontWeight: 700,
              align: 'center',
              verticalAlign: 'middle',
            }),
          },
        ],
      }
    },
  }
}

interface OptionContext {
  rows: readonly AlignedStockChartRow[]
  warmupBars: readonly Bar[]
  theme: StockChartTheme
  isBottom: boolean
  zoomStart: number
  zoomEnd: number
}

function commonAxes(context: OptionContext) {
  const dates = context.rows.map((row) => row.bar.date)
  return {
    grid: { left: 8, right: 64, top: 8, bottom: context.isBottom ? 34 : 8 },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: true,
      axisLine: { lineStyle: { color: context.theme.axis } },
      axisTick: { show: context.isBottom },
      axisLabel: {
        show: context.isBottom,
        color: context.theme.label,
        fontSize: 10,
      },
      splitLine: { show: false },
    },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        start: context.zoomStart,
        end: context.zoomEnd,
      },
      ...(context.isBottom
        ? [{
            type: 'slider',
            xAxisIndex: 0,
            bottom: 2,
            height: 16,
            start: context.zoomStart,
            end: context.zoomEnd,
            borderColor: context.theme.axis,
            fillerColor: 'rgba(64,158,255,0.18)',
            textStyle: { color: context.theme.label },
          }]
        : []),
    ],
  }
}

function commonOption(context: OptionContext) {
  const axes = commonAxes(context)
  return {
    animation: false,
    backgroundColor: context.theme.background,
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: context.theme.axis },
      lineStyle: { color: context.theme.label, type: 'dashed' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: context.theme.tooltipBackground,
      borderColor: context.theme.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: context.theme.text, fontSize: 12 },
    },
    ...axes,
  }
}

export function buildKlineOption(context: OptionContext) {
  const bars = context.rows.map((row) => row.bar)
  const allCloses = [...context.warmupBars, ...bars].map((bar) => bar.close)
  const base = commonOption(context)
  const maDefinitions = [
    { period: 5, color: context.theme.label },
    { period: 10, color: context.theme.diff },
    { period: 20, color: '#bd53c7' },
    { period: 30, color: '#16a8bd' },
    { period: 60, color: '#ff7a18' },
  ]
  return {
    ...base,
    tooltip: {
      ...base.tooltip,
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params]
        const index = (list[0] as { dataIndex?: unknown } | undefined)?.dataIndex
        if (typeof index !== 'number') return ''
        const row = context.rows[index]
        return row ? klineTooltip(row) : ''
      },
    },
    yAxis: {
      scale: true,
      position: 'right',
      axisLine: { show: false },
      axisLabel: { color: context.theme.label, fontSize: 10 },
      splitLine: { lineStyle: { color: context.theme.split } },
    },
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
        itemStyle: {
          color: context.theme.up,
          color0: context.theme.down,
          borderColor: context.theme.up,
          borderColor0: context.theme.down,
        },
      },
      ...maDefinitions.map(({ period, color }) => {
        const full = movingAverage(allCloses, period)
        return {
          name: `MA${period}`,
          type: 'line',
          data: full.slice(full.length - bars.length),
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1, color },
          z: 3,
        }
      }),
    ],
  }
}

export function buildVolumeOption(context: OptionContext) {
  const bars = context.rows.map((row) => row.bar)
  const allVolumes = [...context.warmupBars, ...bars].map((bar) => bar.volume)
  const volMa5 = movingAverage(allVolumes, 5).slice(-bars.length)
  const volMa10 = movingAverage(allVolumes, 10).slice(-bars.length)
  return {
    ...commonOption(context),
    yAxis: {
      scale: true,
      position: 'right',
      splitNumber: 2,
      axisLine: { show: false },
      axisLabel: {
        color: context.theme.label,
        fontSize: 10,
        formatter: (value: number) => formatVolume(value),
      },
      splitLine: { lineStyle: { color: context.theme.split } },
    },
    series: [
      {
        name: '量能',
        type: 'bar',
        data: bars.map((bar) => ({
          value: bar.volume,
          itemStyle: { color: bar.close >= bar.open ? context.theme.up : context.theme.down },
        })),
      },
      {
        name: 'VMA5',
        type: 'line',
        data: volMa5,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.4, color: context.theme.diff },
      },
      {
        name: 'VMA10',
        type: 'line',
        data: volMa10,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.4, color: '#16a8bd' },
      },
    ],
  }
}

export function buildMacdOption(context: OptionContext) {
  return {
    ...commonOption(context),
    yAxis: {
      scale: true,
      min: ({ min }: { min: number }) => Math.min(0, min),
      max: ({ max }: { max: number }) => Math.max(0, max),
      position: 'right',
      axisLine: { show: false },
      axisLabel: { color: context.theme.label, fontSize: 10 },
      splitLine: { lineStyle: { color: context.theme.split } },
    },
    series: [
      {
        name: 'MACD',
        type: 'bar',
        markLine: {
          silent: true,
          symbol: ['none', 'none'],
          label: { show: false },
          lineStyle: { color: context.theme.axis, width: 1 },
          data: [{ yAxis: 0 }],
        },
        data: context.rows.map((row) => {
          const value = row.indicator?.macd_hist ?? null
          return {
            value,
            itemStyle: {
              color: value != null && value >= 0 ? context.theme.up : context.theme.down,
            },
          }
        }),
      },
      {
        name: 'DIFF',
        type: 'line',
        data: context.rows.map((row) => row.indicator?.macd_diff ?? null),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.8, color: context.theme.diff },
      },
      {
        name: 'DEA',
        type: 'line',
        data: context.rows.map((row) => row.indicator?.macd_dea ?? null),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.8, color: context.theme.dea },
      },
      buildSignalSeries(context.rows, context.theme),
    ],
  }
}

export function panelTitle(type: ChartType, adjustLabel: string): string {
  if (type === 'kline') return `K线（日线·${adjustLabel}）`
  if (type === 'volume') return '量能'
  return 'MACD（12,26,9·前复权）'
}

export function klineMetrics(
  rows: readonly AlignedStockChartRow[],
  warmupBars: readonly Bar[],
  index: number,
) {
  const closes = [...warmupBars, ...rows.map((row) => row.bar)].map((bar) => bar.close)
  const offset = warmupBars.length + index
  return [5, 10, 20, 30, 60].map((period) => ({
    label: `MA${period}`,
    value: formatChartNumber(movingAverage(closes, period)[offset]),
  }))
}

export function volumeMetrics(
  rows: readonly AlignedStockChartRow[],
  warmupBars: readonly Bar[],
  index: number,
) {
  const volumes = [...warmupBars, ...rows.map((row) => row.bar)].map((bar) => bar.volume)
  const offset = warmupBars.length + index
  return [
    { label: '总量', value: formatVolume(rows[index]?.bar.volume) },
    { label: 'MA5', value: formatVolume(movingAverage(volumes, 5)[offset]) },
    { label: 'MA10', value: formatVolume(movingAverage(volumes, 10)[offset]) },
  ]
}

export function macdMetrics(rows: readonly AlignedStockChartRow[], index: number) {
  const indicator = rows[index]?.indicator
  return [
    { label: 'MACD', value: formatChartNumber(indicator?.macd_hist) },
    { label: 'DIFF', value: formatChartNumber(indicator?.macd_diff) },
    { label: 'DEA', value: formatChartNumber(indicator?.macd_dea) },
  ]
}

export function klineTooltip(row: AlignedStockChartRow): string {
  const bar = row.bar
  const pct = bar.pre_close ? ((bar.close - bar.pre_close) / bar.pre_close) * 100 : null
  const amplitude = bar.pre_close ? ((bar.high - bar.low) / bar.pre_close) * 100 : null
  return [
    `时间：${bar.date}`,
    `开盘：${formatChartNumber(bar.open)}`,
    `收盘：${formatChartNumber(bar.close)}`,
    `最高：${formatChartNumber(bar.high)}`,
    `最低：${formatChartNumber(bar.low)}`,
    `涨幅：${pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`}`,
    `振幅：${amplitude == null ? '--' : `${amplitude.toFixed(2)}%`}`,
    `成交量：${formatVolume(bar.volume)}`,
    `成交额：${formatAmount(bar.amount)}`,
    `换手率：${bar.turnover_rate == null ? '--' : `${bar.turnover_rate.toFixed(2)}%`}`,
  ].join('<br/>')
}
