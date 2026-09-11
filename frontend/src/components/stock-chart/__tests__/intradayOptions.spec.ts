import { describe, expect, it } from 'vitest'
import type { IntradayPoint } from '@/api/stocks'
import { buildIntradayOption } from '@/components/stock-chart/intradayOptions'
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
  series: {
    kline: { ma5: '#orange', ma10: '#1', ma20: '#2', ma30: '#3', ma60: '#4' },
    volume: { ma5: '#5', ma10: '#6' },
    macd: { diff: '#7', dea: '#8' },
  },
}

const points: IntradayPoint[] = [
  { time: '09:31', open: 10, high: 10.2, low: 9.9, close: 10.1, volume: 1000, amount: 10_100, average_price: 10.1 },
  { time: '13:01', open: 10.2, high: 10.2, low: 10, close: 10, volume: 2000, amount: 20_000, average_price: 10.03 },
]

describe('buildIntradayOption', () => {
  it('固定为双绘图区、三序列、右轴，并复用股票主题色', () => {
    const option = buildIntradayOption({
      points,
      preClose: 9.8,
      theme,
      zoomStart: 25,
      zoomEnd: 75,
    }) as any

    expect(option.grid).toHaveLength(2)
    expect(option.yAxis).toHaveLength(2)
    expect(option.yAxis.every((axis: { position: string }) => axis.position === 'right')).toBe(true)
    expect(option.series.map((series: { name: string }) => series.name)).toEqual(['价格', '均价', '成交量'])
    expect(option.series[0].lineStyle.color).toBe('#blue')
    expect(option.series[0].markLine.data).toEqual([{ yAxis: 9.8 }])
    expect(option.series[1].lineStyle.color).toBe('#orange')
    expect(option.series[2].data.map((item: any) => item.itemStyle.color)).toEqual(['#red', '#green'])
    expect(option.axisPointer.link).toEqual([{ xAxisIndex: [0, 1] }])
    expect(option.legend.data).toEqual(['价格', '均价'])
    expect(option.xAxis[1].axisLabel.formatter('11:30')).toBe('11:30 / 13:01')
    expect(option.dataZoom.map((zoom: { type: string }) => zoom.type)).toEqual(['inside', 'slider'])
    expect(option.dataZoom.every((zoom: { xAxisIndex: number[] }) => (
      zoom.xAxisIndex.join(',') === '0,1'
    ))).toBe(true)
    expect(option.dataZoom.every((zoom: { start: number; end: number }) => (
      zoom.start === 25 && zoom.end === 75
    ))).toBe(true)
    expect((option.yAxis[0].min + option.yAxis[0].max) / 2).toBeCloseTo(9.8)
  })

  it('悬浮提示包含相对昨收涨跌幅且午休不补点', () => {
    const option = buildIntradayOption({ points, preClose: 10, theme }) as any
    const html = option.tooltip.formatter([{ dataIndex: 0 }])

    expect(html).toContain('+1.00%')
    expect(html).toContain('成交量')
    expect(option.xAxis[0].data).toEqual(['09:31', '13:01'])
  })
})
