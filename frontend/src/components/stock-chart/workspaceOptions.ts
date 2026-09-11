import type { Bar, IndicatorRow } from '@/api/stocks'
import type { ChartType } from '@/composables/useStockChartPreferences'
import { formatMarketPercent } from '@/utils/marketValue'
import {
  buildStockVolumeBarSeries,
  formatChartAxisNumber,
  formatChartNumber,
  formatVolume,
  KLINE_MA_DEFINITIONS,
  klineTooltipHtml,
  movingAverage,
  obstructionAwareTooltipPosition,
  VOLUME_MA_DEFINITIONS,
  type StockChartTheme,
} from './chartUtils'

export type WorkspacePanelKey = 'kline' | 'slot2' | 'slot3'
export type MacdPanelState = 'ready' | 'loading' | 'insufficient' | 'error'

export interface AlignedStockChartRow {
  bar: Bar
  indicator?: IndicatorRow
}

/** 买卖点标注：date=交易日（与 bars.date 对齐），kind=买/卖，label=标注文字。 */
export interface TradeMarker {
  date: string
  kind: 'buy' | 'sell'
  label: string
}

export interface SignalDatum {
  value: [number, number, 0 | 1]
  signalType: '金叉' | '死叉'
  tradeDate: string
  color: string
}

export const KLINE_MIN_HEIGHT = 250
export const AUXILIARY_MIN_HEIGHT = 126
export const WORKSPACE_MIN_HEIGHT = 650
export const SPLITTER_SIZE = 8
export const KEYBOARD_RATIO_STEP = 0.02
export const KLINE_BAR_WIDTH = '72%'
export const VOLUME_BAR_WIDTH = '44%'
export const MACD_BAR_WIDTH = '24%'
export const BOTTOM_GRID_HEIGHT = 52

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

/** 股票多图工作区在当前图表组合下不可压缩的内容高度。 */
export function stockChartWorkspaceMinHeight(types: readonly ChartType[]): number {
  return types.reduce((total, type) => total + panelMinHeight(type), 0)
    + Math.max(0, types.length - 1) * SPLITTER_SIZE
}

export function panelMetricColor(
  theme: StockChartTheme,
  type: ChartType,
  label: string,
  macdValue?: number | null,
): string {
  if (type === 'macd' && label === 'MACD') {
    if (macdValue == null) return theme.label
    return macdValue < 0 ? theme.down : theme.up
  }
  if (type === 'kline') {
    const definition = KLINE_MA_DEFINITIONS.find((item) => item.label === label)
    if (definition) return theme.series.kline[definition.paletteKey]
  }
  if (type === 'volume') {
    const definition = VOLUME_MA_DEFINITIONS.find((item) => item.label === label)
    if (definition) return theme.series.volume[definition.paletteKey]
  }
  if (label === 'DIFF') return theme.series.macd.diff
  if (label === 'DEA') return theme.series.macd.dea
  return theme.label
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

export function constrainWorkspaceRatios(
  value: readonly number[],
  minRatios: readonly number[],
): number[] {
  const normalized = normalizeWorkspaceRatios(value, minRatios.length)
  const safeMinimums = minRatios.map((item) => (
    Number.isFinite(item) && item > 0 ? item : 0
  ))
  const minimumTotal = safeMinimums.reduce((sum, item) => sum + item, 0)
  if (minimumTotal >= 1) {
    return normalizeWorkspaceRatios(safeMinimums, safeMinimums.length)
  }

  const surplus = normalized.map((item, index) => Math.max(0, item - safeMinimums[index]!))
  const surplusTotal = surplus.reduce((sum, item) => sum + item, 0)
  const availableSurplus = 1 - minimumTotal
  if (surplusTotal <= 0) {
    const evenShare = availableSurplus / Math.max(1, normalized.length)
    return safeMinimums.map((item) => item + evenShare)
  }
  return safeMinimums.map(
    (item, index) => item + surplus[index]! / surplusTotal * availableSurplus,
  )
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
  const signals: SignalDatum[] = []
  rows.forEach((row, index) => {
    const diff = row.indicator?.macd_diff
    if (diff == null || !Number.isFinite(diff)) return
    if (row.indicator?.macd_golden_cross === true) {
      signals.push({
        value: [index, diff, 1],
        signalType: '金叉',
        tradeDate: row.bar.date,
        color: theme.up,
      })
    }
    if (row.indicator?.macd_dead_cross === true) {
      signals.push({
        value: [index, diff, 0],
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
  isGolden: boolean,
) {
  const x = coord[0]
  const anchorY = coord[1]
  const labelCenterY = anchorY + (isGolden ? -13 : 13)
  const labelTop = labelCenterY - 9
  const pointerBaseY = isGolden ? labelTop + 18 : labelTop
  const pointerPoints = isGolden
    ? [[x - 3, pointerBaseY], [x + 3, pointerBaseY], [x, anchorY]]
    : [[x, anchorY], [x - 3, pointerBaseY], [x + 3, pointerBaseY]]
  return { x, anchorY, labelCenterY, labelTop, pointerPoints }
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
      show: true,
      trigger: 'item' as const,
      confine: true,
      formatter: (params: { data?: SignalDatum }) => {
        const datum = params.data
        return datum ? `${datum.signalType}<br/>交易日：${datum.tradeDate}` : ''
      },
    },
    renderItem: (
      _params: { coordSys: { y: number, height: number } },
      api: {
        value: (dimension: number) => number
        coord: (value: [number, number]) => [number, number]
      },
    ) => {
      const isGolden = api.value(2) === 1
      const coord = api.coord([api.value(0), api.value(1)])
      const geometry = signalRenderGeometry(coord, isGolden)
      const color = isGolden ? theme.up : theme.down
      const label = isGolden ? '金叉' : '死叉'
      return {
        type: 'group',
        children: [
          {
            type: 'polygon',
            shape: { points: geometry.pointerPoints },
            style: { fill: color },
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
            style: {
              fill: theme.background,
              stroke: color,
              lineWidth: 1.5,
            },
          },
          {
            type: 'text',
            style: {
              x: geometry.x,
              y: geometry.labelCenterY,
              text: label,
              fill: theme.text,
              fontSize: 10,
              fontWeight: 700,
              align: 'center',
              verticalAlign: 'middle',
            },
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
  markers?: readonly TradeMarker[]
  buyMarkerColor?: string
  sellMarkerColor?: string
  clickableCandles?: boolean
}

/** 买卖点 markPoint：买=蓝▲置于最低价下方，卖=橙▼置于最高价上方（语义色由组件按主题传入）。 */
function buildTradeMarkPoints(context: OptionContext) {
  if (!context.markers?.length) return []
  const indexByDate = new Map(context.rows.map((row, index) => [row.bar.date, index]))
  return context.markers
    .map((marker) => {
      const index = indexByDate.get(marker.date)
      if (index == null) return null
      const bar = context.rows[index].bar
      const isBuy = marker.kind === 'buy'
      const color = isBuy ? context.buyMarkerColor : context.sellMarkerColor
      return {
        name: marker.label,
        kind: marker.kind,
        coord: [index, isBuy ? bar.low * 0.985 : bar.high * 1.015],
        symbol: 'triangle',
        symbolRotate: isBuy ? 0 : 180,
        symbolSize: 12,
        itemStyle: { color, borderColor: '#fff', borderWidth: 1 },
        label: {
          show: true,
          position: isBuy ? 'bottom' : 'top',
          color,
          fontSize: 10,
          fontWeight: 600,
          lineHeight: 13,
          formatter: marker.label,
        },
      }
    })
    .filter(Boolean)
}

function commonAxes(context: OptionContext, showPointerDate: boolean) {
  const dates = context.rows.map((row) => row.bar.date)
  return {
    grid: {
      left: 64,
      right: 64,
      top: 8,
      bottom: context.isBottom ? BOTTOM_GRID_HEIGHT : 8,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: true,
      axisLine: { lineStyle: { color: context.theme.axis } },
      axisTick: { show: context.isBottom },
      axisLabel: {
        show: context.isBottom,
        showMinLabel: true,
        showMaxLabel: true,
        alignMinLabel: 'left',
        alignMaxLabel: 'right',
        margin: 8,
        color: context.theme.label,
        fontSize: 10,
      },
      axisPointer: {
        label: { show: showPointerDate },
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
            bottom: 4,
            height: 14,
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

function commonOption(context: OptionContext, showPointerDate: boolean) {
  const axes = commonAxes(context, showPointerDate)
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
  const referencePrice = [...bars]
    .reverse()
    .find((bar) => bar.pre_close != null && Number.isFinite(bar.pre_close) && bar.pre_close > 0)
    ?.pre_close ?? null
  const base = commonOption(context, true)
  return {
    ...base,
    tooltip: {
      ...base.tooltip,
      className: 'stock-chart-kline-tooltip',
      confine: true,
      transitionDuration: 0,
      extraCssText: 'transition:opacity .14s ease,visibility .14s ease;',
      position: obstructionAwareTooltipPosition,
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params]
        const index = (list[0] as { dataIndex?: unknown } | undefined)?.dataIndex
        if (typeof index !== 'number') return ''
        const row = context.rows[index]
        return row ? klineTooltipHtml(row.bar, context.theme) : ''
      },
    },
    yAxis: [
      {
        scale: true,
        position: 'left',
        axisLine: { show: false },
        axisLabel: {
          color: context.theme.label,
          fontSize: 10,
          formatter: (value: number) => formatChartAxisNumber(value, 2),
        },
        splitLine: { lineStyle: { color: context.theme.split } },
      },
      {
        scale: true,
        position: 'right',
        axisLine: { show: false },
        axisLabel: {
          color: context.theme.label,
          fontSize: 10,
          formatter: (value: number) => {
            if (referencePrice == null) return '--'
            const percentage = ((value / referencePrice) - 1) * 100
            return formatMarketPercent(percentage)
          },
        },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        cursor: context.clickableCandles ? 'pointer' : 'default',
        barWidth: KLINE_BAR_WIDTH,
        barMaxWidth: 18,
        data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
        itemStyle: {
          color: context.theme.up,
          color0: context.theme.down,
          borderColor: context.theme.up,
          borderColor0: context.theme.down,
        },
        markPoint: {
          symbolSize: 0,
          data: buildTradeMarkPoints(context),
        },
      },
      ...KLINE_MA_DEFINITIONS.map((definition) => {
        const full = movingAverage(allCloses, definition.period)
        return {
          name: definition.label,
          type: 'line',
          data: full.slice(full.length - bars.length),
          showSymbol: false,
          connectNulls: false,
          lineStyle: {
            width: 1,
            color: context.theme.series.kline[definition.paletteKey],
          },
          z: 3,
        }
      }),
      {
        name: '__price_axis_sync__',
        type: 'candlestick',
        yAxisIndex: 1,
        data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
        silent: true,
        z: -10,
        tooltip: { show: false },
        itemStyle: { opacity: 0, borderWidth: 0 },
        emphasis: { disabled: true },
      },
    ],
  }
}

export function buildVolumeOption(context: OptionContext) {
  const bars = context.rows.map((row) => row.bar)
  const allVolumes = [...context.warmupBars, ...bars].map((bar) => bar.volume)
  const base = commonOption(context, false)
  return {
    ...base,
    tooltip: { ...base.tooltip, showContent: false },
    yAxis: {
      scale: true,
      position: 'left',
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
      buildStockVolumeBarSeries({
        data: bars,
        theme: context.theme,
        barWidth: VOLUME_BAR_WIDTH,
        barMaxWidth: 12,
      }),
      ...VOLUME_MA_DEFINITIONS.map((definition) => ({
        name: definition.seriesName,
        type: 'line',
        data: movingAverage(allVolumes, definition.period).slice(-bars.length),
        showSymbol: false,
        connectNulls: false,
        lineStyle: {
          width: 1.4,
          color: context.theme.series.volume[definition.paletteKey],
        },
      })),
    ],
  }
}

export function buildMacdOption(context: OptionContext) {
  const base = commonOption(context, false)
  return {
    ...base,
    tooltip: {
      ...base.tooltip,
      className: 'stock-chart-macd-signal-tooltip',
      showContent: true,
      // 普通柱线仍只驱动十字光标；信号系列以 item tooltip 覆盖并显示完整交易日。
      formatter: () => '',
    },
    yAxis: {
      scale: true,
      min: ({ min }: { min: number }) => Math.min(0, min),
      max: ({ max }: { max: number }) => Math.max(0, max),
      position: 'left',
      axisLine: { show: false },
      axisLabel: {
        color: context.theme.label,
        fontSize: 10,
        formatter: (value: number) => formatChartAxisNumber(value, 2),
      },
      splitLine: { lineStyle: { color: context.theme.split } },
    },
    series: [
      {
        name: 'MACD',
        type: 'bar',
        barWidth: MACD_BAR_WIDTH,
        barMaxWidth: 7,
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
        lineStyle: { width: 1.8, color: context.theme.series.macd.diff },
      },
      {
        name: 'DEA',
        type: 'line',
        data: context.rows.map((row) => row.indicator?.macd_dea ?? null),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.8, color: context.theme.series.macd.dea },
      },
      buildSignalSeries(context.rows, context.theme),
    ],
  }
}

export function panelTitle(type: ChartType, adjustLabel: string): string {
  if (type === 'kline') return `K线（日线·${adjustLabel}）`
  if (type === 'volume') return '量能'
  return `MACD（12,26,9·${adjustLabel}）`
}

export function klineMetrics(
  rows: readonly AlignedStockChartRow[],
  warmupBars: readonly Bar[],
  index: number,
) {
  const closes = [...warmupBars, ...rows.map((row) => row.bar)].map((bar) => bar.close)
  const offset = warmupBars.length + index
  return KLINE_MA_DEFINITIONS.map((definition) => ({
    label: definition.label,
    value: formatChartNumber(movingAverage(closes, definition.period)[offset]),
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
    ...VOLUME_MA_DEFINITIONS.map((definition) => ({
      label: definition.label,
      value: formatVolume(movingAverage(volumes, definition.period)[offset]),
    })),
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
