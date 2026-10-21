import type { EChartsOption } from 'echarts'
import type { IntradayPoint } from '@/api/stocks'
import { formatMarketPercent } from '@/utils/marketValue'
import {
  STOCK_QUOTE_TOOLTIP_CSS,
  stockQuoteSummaryHtml,
  stockQuoteSummaryWidths,
  type StockQuoteSummaryModel,
} from './stockQuoteSummary'
import {
  buildStockVolumeBarSeries,
  formatAmount,
  formatChartNumber,
  formatVolumeLots,
  type StockChartTheme,
} from './chartUtils'

export interface IntradayOptionInput {
  points: IntradayPoint[]
  preClose: number | null
  theme: StockChartTheme
  chartHeight?: number
  zoomStart?: number
  zoomEnd?: number
}

interface IntradayPanelLayout {
  priceTop: number
  priceHeight: number
  dividerTop: number
  volumeHeaderTop: number
  volumeTop: number
  volumeBottom: number
}

/**
 * 为共享 DOM 面板标题栏预留空间，并按实际画布高度压缩空隙。
 * 单实例布局保证价格、量能仍共享十字光标和缩放窗口。
 */
export function intradayPanelLayout(chartHeight = 560): IntradayPanelLayout {
  const height = Math.max(340, chartHeight)
  const panelHeaderHeight = 32
  const pricePlotInset = 8
  const volumePlotInset = 12
  const priceTop = panelHeaderHeight + pricePlotInset
  const volumeBottom = 48
  const plotHeight = Math.max(
    180,
    height - priceTop - volumeBottom - panelHeaderHeight - pricePlotInset - volumePlotInset,
  )
  const priceHeight = Math.round(plotHeight * 0.66)
  const dividerTop = priceTop + priceHeight
  const volumeHeaderTop = dividerTop + pricePlotInset
  return {
    priceTop,
    priceHeight,
    dividerTop,
    volumeHeaderTop,
    volumeTop: volumeHeaderTop + panelHeaderHeight + volumePlotInset,
    volumeBottom,
  }
}

function symmetricPriceExtent(
  points: IntradayPoint[],
  preClose: number | null,
): { min?: number; max?: number; interval?: number } {
  if (preClose == null || !Number.isFinite(preClose) || preClose <= 0) return {}
  const prices = points.flatMap((point) => [point.close, point.average_price])
    .filter((value): value is number => value != null && Number.isFinite(value))
  const distance = Math.max(
    preClose * 0.005,
    ...prices.map((value) => Math.abs(value - preClose)),
  )
  const deviationRate = distance / preClose
  const reachesPriceLimit = [0.05, 0.1, 0.2, 0.3]
    .some((limit) => Math.abs(deviationRate - limit) <= 0.0025)
  const padded = distance * (reachesPriceLimit ? 1 : 1.08)
  return {
    min: Number((preClose - padded).toFixed(4)),
    max: Number((preClose + padded).toFixed(4)),
    // 四等分保证昨收价落在中央刻度，零轴左侧始终显示对应具体股价。
    interval: Number((padded / 2).toFixed(6)),
  }
}

/** 分钟明细复用日 K 的行情网格；价格与涨跌幅按昨收判色，折线身份色独立。 */
export function buildIntradayQuoteSummary(
  point: IntradayPoint,
  preClose: number | null,
  theme: StockChartTheme,
): StockQuoteSummaryModel {
  const pct = preClose != null && Number.isFinite(preClose) && preClose > 0
    ? ((point.close / preClose) - 1) * 100
    : null
  const tone = pct == null || pct === 0 ? 'neutral' : pct > 0 ? 'up' : 'down'
  return {
    time: point.time,
    hero: { label: '', value: formatChartNumber(point.close, 2), tone },
    rowsPerColumn: 2,
    metrics: [
      { label: '均价', value: formatChartNumber(point.average_price, 2), color: theme.series.kline.ma5 },
      {
        label: '涨跌幅',
        value: pct == null ? '--' : `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`,
        tone,
      },
      { label: '成交量', value: formatVolumeLots(point.volume) },
      { label: '成交额', value: formatAmount(point.amount) },
    ],
  }
}

export function buildIntradayOption(input: IntradayOptionInput): EChartsOption {
  const {
    points,
    preClose,
    theme,
    chartHeight = 560,
    zoomStart = 0,
    zoomEnd = 100,
  } = input
  const times = points.map((point) => point.time)
  const closes = points.map((point) => point.close)
  const averages = points.map((point) => point.average_price)
  const priceExtent = symmetricPriceExtent(points, preClose)
  const panelLayout = intradayPanelLayout(chartHeight)
  const middayIndex = times.indexOf('11:30')
  const lastTimeIndex = times.length - 1

  const summaries = points.map((point) => buildIntradayQuoteSummary(point, preClose, theme))
  const quoteWidths = stockQuoteSummaryWidths(summaries)

  return {
    animation: false,
    backgroundColor: theme.background,
    axisPointer: { link: [{ xAxisIndex: [0, 1] }], label: { backgroundColor: theme.muted } },
    tooltip: {
      trigger: 'axis',
      confine: true,
      appendTo: 'body',
      transitionDuration: 0,
      extraCssText: STOCK_QUOTE_TOOLTIP_CSS,
      axisPointer: { type: 'cross' },
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
      formatter: (params: unknown) => {
        const items = Array.isArray(params) ? params as Array<{ dataIndex?: number }> : []
        const index = items.find((item) => typeof item.dataIndex === 'number')?.dataIndex
        if (index == null || !points[index]) return ''
        return stockQuoteSummaryHtml(summaries[index]!, {
          ...theme, border: theme.tooltipBorder,
        }, quoteWidths)
      },
    },
    grid: [
      {
        left: 64,
        right: 64,
        top: panelLayout.priceTop,
        height: panelLayout.priceHeight,
      },
      {
        left: 64,
        right: 64,
        top: panelLayout.volumeTop,
        bottom: panelLayout.volumeBottom,
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: zoomStart,
        end: zoomEnd,
        filterMode: 'none',
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        start: zoomStart,
        end: zoomEnd,
        filterMode: 'none',
        bottom: 4,
        height: 14,
        borderColor: theme.axis,
        fillerColor: theme.area,
        textStyle: { color: theme.label },
        showDetail: false,
      },
    ],
    xAxis: [
      {
        type: 'category',
        gridIndex: 0,
        data: times,
        boundaryGap: false,
        axisLine: { show: false },
        axisLabel: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: times,
        boundaryGap: true,
        axisLine: { show: false },
        axisLabel: {
          color: theme.label,
          interval: (index: number) => {
            return index === 0 || index === middayIndex || index === lastTimeIndex
          },
          formatter: (_value: string, index: number) => {
            if (index === 0) return '09:30'
            if (index === middayIndex) return '11:30'
            if (index === lastTimeIndex) return '15:00'
            return ''
          },
        },
        axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        position: 'left',
        scale: true,
        splitNumber: 4,
        ...priceExtent,
        axisLabel: {
          color: theme.label,
          showMinLabel: false,
          showMaxLabel: false,
          formatter: (value: number) => value.toFixed(2),
        },
        axisPointer: {
          label: { formatter: ({ value }: { value: unknown }) => formatChartNumber(Number(value), 2) },
        },
        axisLine: { show: false },
        splitLine: {
          showMinLine: false,
          showMaxLine: false,
          lineStyle: { color: theme.split },
        },
      },
      {
        type: 'value',
        gridIndex: 0,
        position: 'right',
        scale: true,
        splitNumber: 4,
        ...priceExtent,
        axisLabel: {
          show: preClose != null && preClose > 0,
          showMinLabel: false,
          showMaxLabel: false,
          color: theme.label,
          formatter: (value: number) => {
            if (preClose == null || preClose <= 0) return '--'
            const percentage = ((value / preClose) - 1) * 100
            return formatMarketPercent(percentage)
          },
        },
        axisLine: { show: false },
        axisPointer: {
          label: {
            formatter: ({ value }: { value: unknown }) => preClose != null && preClose > 0
              ? formatMarketPercent(((Number(value) / preClose) - 1) * 100)
              : '--',
          },
        },
        splitLine: { show: false },
      },
      {
        type: 'value',
        gridIndex: 1,
        position: 'left',
        min: 0,
        splitNumber: 2,
        axisLabel: { color: theme.label, formatter: (value: number) => formatVolumeLots(value) },
        axisPointer: {
          label: { formatter: ({ value }: { value: unknown }) => formatVolumeLots(Number(value)) },
        },
        axisLine: { show: false },
        splitLine: {
          showMinLine: false,
          showMaxLine: false,
          lineStyle: { color: theme.split },
        },
      },
    ],
    series: [
      {
        name: '价格',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: closes,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: theme.text, width: 1.6 },
        // 默认 emptyCircle 内部固定白色；显式圆形保留空心轮廓，并让内部跟随背景。
        symbol: 'circle',
        itemStyle: { color: theme.background, borderColor: theme.text, borderWidth: 2 },
        emphasis: {
          itemStyle: { color: theme.background, borderColor: theme.text, borderWidth: 2 },
        },
        markLine: preClose == null ? undefined : {
          symbol: ['none', 'none'],
          silent: true,
          label: { show: true, position: 'insideEndTop', formatter: '0%', color: theme.label },
          lineStyle: { color: theme.muted, type: 'dashed', width: 1 },
          data: [{ yAxis: preClose }],
        },
      },
      {
        name: '均价',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: averages,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: theme.series.kline.ma5, width: 1.2 },
        itemStyle: { color: theme.series.kline.ma5 },
      },
      buildStockVolumeBarSeries({
        data: points,
        theme,
        directionReference: 'previous-close',
        initialReference: preClose,
        name: '成交量',
        xAxisIndex: 1,
        yAxisIndex: 2,
        barMaxWidth: 5,
      }),
    ],
  }
}
