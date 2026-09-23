import { describe, expect, it } from 'vitest'
import type { IntradayPoint } from '@/api/stocks'
import {
  buildIntradayOption,
  intradayPanelLayout,
} from '@/components/stock-chart/intradayOptions'
import type { StockChartTheme } from '@/components/stock-chart/chartUtils'

const theme: StockChartTheme = {
  background: '#bg',
  axis: '#axis',
  split: '#split',
  label: '#label',
  text: '#text',
  tooltipBackground: '#tooltip',
  tooltipBorder: '#border',
  focus: '#blue',
  accent: '#accent',
  muted: '#muted',
  area: '#area',
  up: '#red',
  down: '#green',
  volumeNeutral: '#neutral-volume',
  series: {
    kline: { ma5: '#orange', ma10: '#1', ma20: '#2', ma30: '#3', ma60: '#4' },
    volume: { ma5: '#5', ma10: '#6' },
    macd: { diff: '#7', dea: '#8' },
  },
}

const points: IntradayPoint[] = [
  { time: '09:31', open: 10, high: 10.2, low: 9.9, close: 10.1, volume: 10, amount: 10_100, average_price: 10.1 },
  { time: '11:30', open: 10.1, high: 10.2, low: 10, close: 10.15, volume: 15, amount: 15_225, average_price: 10.12 },
  { time: '13:01', open: 10.2, high: 10.2, low: 10, close: 10, volume: 20, amount: 20_000, average_price: 10.03 },
]

describe('buildIntradayOption', () => {
  it('固定为双绘图区、三序列、价格双轴与量能左轴，并复用股票主题色', () => {
    const option = buildIntradayOption({
      points,
      preClose: 9.8,
      theme,
      chartHeight: 560,
      zoomStart: 25,
      zoomEnd: 75,
    }) as any

    expect(option.grid).toHaveLength(2)
    expect(option.grid.every((grid: { left: number; right: number }) => (
      grid.left === 64 && grid.right === 64
    ))).toBe(true)
    expect(option.yAxis).toHaveLength(3)
    expect(option.yAxis.map((axis: { position: string }) => axis.position))
      .toEqual(['left', 'right', 'left'])
    expect(option.yAxis[1].axisLabel.formatter(9.8)).toBe('0.00%')
    expect(option.yAxis[0].axisLabel).toMatchObject({
      showMinLabel: false,
      showMaxLabel: false,
    })
    expect(option.yAxis[1].axisLabel).toMatchObject({
      showMinLabel: false,
      showMaxLabel: false,
    })
    expect(option.yAxis.every((axis: { axisLine: { show: boolean } }) => !axis.axisLine.show))
      .toBe(true)
    expect(option.xAxis.every((axis: { axisLine: { show: boolean } }) => !axis.axisLine.show))
      .toBe(true)
    expect(option.yAxis[0].splitLine.lineStyle).toEqual({ color: '#split' })
    expect(option.yAxis[2].splitLine.lineStyle).toEqual({ color: '#split' })
    expect(option.yAxis[0].splitLine).toMatchObject({ showMinLine: false, showMaxLine: false })
    expect(option.yAxis[2].splitLine).toMatchObject({ showMinLine: false, showMaxLine: false })
    expect(option.series.map((series: { name: string }) => series.name)).toEqual(['价格', '均价', '成交量'])
    expect(option.series[0].lineStyle.color).toBe('#blue')
    expect(option.series[0].markLine).toMatchObject({
      label: { formatter: '0%' },
      data: [{ yAxis: 9.8 }],
    })
    expect(option.series[1].lineStyle.color).toBe('#orange')
    expect(option.series[2].data.map((item: any) => item.itemStyle.color))
      .toEqual(['#red', '#red', '#green'])
    expect(option.yAxis[2].axisLabel.formatter(15_000)).toBe('1.50万手')
    expect(option.axisPointer.link).toEqual([{ xAxisIndex: [0, 1] }])
    expect(option.tooltip.showDelay).toBe(250)
    expect(option.legend).toBeUndefined()
    expect(option.title).toBeUndefined()
    expect(option.graphic).toBeUndefined()
    expect(option.xAxis[1].axisLabel.formatter('09:31', 0)).toBe('09:30')
    expect(option.xAxis[1].axisLabel.formatter('11:30', 1)).toBe('11:30')
    expect(option.xAxis[1].axisLabel.formatter('13:01', 2)).toBe('15:00')
    expect(option.dataZoom.map((zoom: { type: string }) => zoom.type)).toEqual(['inside', 'slider'])
    expect(option.dataZoom.every((zoom: { xAxisIndex: number[] }) => (
      zoom.xAxisIndex.join(',') === '0,1'
    ))).toBe(true)
    expect(option.dataZoom.every((zoom: { start: number; end: number }) => (
      zoom.start === 25 && zoom.end === 75
    ))).toBe(true)
    expect((option.yAxis[0].min + option.yAxis[0].max) / 2).toBeCloseTo(9.8)
  })

  it('分时量柱始终按上一分钟收盘判断，首点按昨收判断', () => {
    const fallbackPoints = points.map((point, index) => ({
      ...point,
      open: 0,
      close: index === 1 ? 10.05 : point.close,
    }))
    const option = buildIntradayOption({ points: fallbackPoints, preClose: 10, theme }) as any

    expect(option.series[2].data.map((item: any) => item.itemStyle.color))
      .toEqual(['#red', '#green', '#green'])
  })

  it('当前分钟与上一分钟收盘价相等时使用中性色量柱', () => {
    const flatPoints = [
      ...points,
      {
        ...points[2]!,
        time: '13:02',
        open: 9.95,
        volume: 12,
        amount: 12_000,
      },
    ]
    const option = buildIntradayOption({ points: flatPoints, preClose: 9.8, theme }) as any

    expect(option.series[2].data.at(-1).itemStyle.color).toBe('#neutral-volume')
    expect(option.series[2].emphasis).toEqual({ disabled: true })
  })

  it('按画布高度为共享标题栏预留固定空间，并保持紧凑双图间距', () => {
    const compact = intradayPanelLayout(340)
    const spacious = intradayPanelLayout(560)

    expect(compact.priceTop).toBe(40)
    expect(spacious.priceTop).toBe(40)
    expect(compact.volumeTop - compact.volumeHeaderTop).toBe(44)
    expect(spacious.volumeTop - spacious.volumeHeaderTop).toBe(44)
    expect(compact.volumeHeaderTop - (compact.priceTop + compact.priceHeight)).toBe(8)
    expect(spacious.volumeHeaderTop - (spacious.priceTop + spacious.priceHeight)).toBe(8)
    expect(compact.dividerTop).toBe(compact.priceTop + compact.priceHeight)
    expect(spacious.dividerTop).toBe(spacious.priceTop + spacious.priceHeight)
  })

  it('涨跌停边界不额外扩展纵轴，避免顶部留下无意义空段', () => {
    const limitPoints = points.map((point, index) => ({
      ...point,
      close: index === points.length - 1 ? 11 : point.close,
      average_price: index === points.length - 1 ? 10.5 : point.average_price,
    }))
    const option = buildIntradayOption({ points: limitPoints, preClose: 10, theme }) as any

    expect(option.yAxis[0].min).toBe(9)
    expect(option.yAxis[0].max).toBe(11)
    expect(option.yAxis[1].min).toBe(9)
    expect(option.yAxis[1].max).toBe(11)
  })

  it('悬浮提示包含相对昨收涨跌幅且午休不补点', () => {
    const option = buildIntradayOption({ points, preClose: 10, theme }) as any
    const html = option.tooltip.formatter([{ dataIndex: 0 }])

    expect(html).toContain('+1.00%')
    expect(html).toContain('成交量')
    expect(option.xAxis[0].data).toEqual(['09:31', '11:30', '13:01'])
  })
})
