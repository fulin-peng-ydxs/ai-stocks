import type { EChartsOption } from 'echarts'
import type { IntradayPoint } from '@/api/stocks'
import { formatAmount, formatChartNumber, formatVolume, type StockChartTheme } from './chartUtils'

export interface IntradayOptionInput {
  points: IntradayPoint[]
  preClose: number | null
  theme: StockChartTheme
  zoomStart?: number
  zoomEnd?: number
}

function symmetricPriceExtent(
  points: IntradayPoint[],
  preClose: number | null,
): { min?: number; max?: number } {
  if (preClose == null || !Number.isFinite(preClose) || preClose <= 0) return {}
  const prices = points.flatMap((point) => [point.close, point.average_price])
    .filter((value): value is number => value != null && Number.isFinite(value))
  const distance = Math.max(
    preClose * 0.005,
    ...prices.map((value) => Math.abs(value - preClose)),
  )
  const padded = distance * 1.08
  return {
    min: Number((preClose - padded).toFixed(4)),
    max: Number((preClose + padded).toFixed(4)),
  }
}

function tooltipRow(label: string, value: string, color: string, labelColor: string): string {
  return '<div style="display:flex;justify-content:space-between;gap:18px">'
    + `<span style="color:${labelColor}">${label}</span>`
    + `<span style="color:${color}">${value}</span>`
    + '</div>'
}

export function buildIntradayOption(input: IntradayOptionInput): EChartsOption {
  const { points, preClose, theme, zoomStart = 0, zoomEnd = 100 } = input
  const times = points.map((point) => point.time)
  const closes = points.map((point) => point.close)
  const averages = points.map((point) => point.average_price)
  const volumes = points.map((point) => ({
    value: point.volume,
    itemStyle: { color: point.close >= point.open ? theme.up : theme.down },
  }))
  const priceExtent = symmetricPriceExtent(points, preClose)

  return {
    animation: false,
    backgroundColor: theme.background,
    axisPointer: { link: [{ xAxisIndex: [0, 1] }], label: { backgroundColor: theme.muted } },
    legend: {
      data: ['价格', '均价'],
      left: 16,
      top: 0,
      textStyle: { color: theme.label },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      axisPointer: { type: 'cross' },
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.text },
      formatter: (params: unknown) => {
        const items = Array.isArray(params) ? params as Array<{ dataIndex?: number }> : []
        const index = items.find((item) => typeof item.dataIndex === 'number')?.dataIndex
        if (index == null || !points[index]) return ''
        const point = points[index]
        const pct = preClose ? ((point.close / preClose) - 1) * 100 : null
        const direction = pct == null || pct === 0 ? theme.text : pct > 0 ? theme.up : theme.down
        return '<div style="min-width:150px;line-height:1.6">'
          + tooltipRow('时间', point.time, theme.text, theme.label)
          + tooltipRow('价格', formatChartNumber(point.close, 2), direction, theme.label)
          + tooltipRow(
            '涨跌幅',
            pct == null ? '--' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`,
            direction,
            theme.label,
          )
          + tooltipRow('均价', formatChartNumber(point.average_price, 2), theme.series.kline.ma5, theme.label)
          + tooltipRow('成交量', formatVolume(point.volume), theme.text, theme.label)
          + tooltipRow('成交额', formatAmount(point.amount), theme.text, theme.label)
          + '</div>'
      },
    },
    grid: [
      { left: 16, right: 70, top: 28, height: '54%' },
      { left: 16, right: 70, top: '69%', bottom: 48 },
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
        axisLine: { lineStyle: { color: theme.axis } },
        axisLabel: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: times,
        boundaryGap: true,
        axisLine: { lineStyle: { color: theme.axis } },
        axisLabel: {
          color: theme.label,
          interval: (index: number) => {
            const time = times[index]
            return time === '09:31' || time === '11:30' || time === '15:00'
          },
          formatter: (value: string) => value === '11:30' ? '11:30 / 13:01' : value,
        },
        axisTick: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        position: 'right',
        scale: true,
        ...priceExtent,
        axisLabel: { color: theme.label, formatter: (value: number) => value.toFixed(2) },
        axisLine: { show: true, lineStyle: { color: theme.axis } },
        splitLine: { lineStyle: { color: theme.split, type: 'dashed' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        position: 'right',
        min: 0,
        axisLabel: { color: theme.label, formatter: (value: number) => formatVolume(value) },
        axisLine: { show: true, lineStyle: { color: theme.axis } },
        splitLine: { show: false },
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
        lineStyle: { color: theme.focus, width: 1.6 },
        itemStyle: { color: theme.focus },
        markLine: preClose == null ? undefined : {
          symbol: ['none', 'none'],
          silent: true,
          label: { show: true, position: 'insideEndTop', formatter: '昨收', color: theme.label },
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
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        barMaxWidth: 5,
      },
    ],
  }
}
