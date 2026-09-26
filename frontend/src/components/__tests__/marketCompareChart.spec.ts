import { describe, expect, it } from 'vitest'
import type { EChartsTheme } from '@/components/chartTheme'
import {
  buildMarketCompareLineOption,
  escapeChartHtml,
  marketCompareChangeColors,
  marketCompareLineColors,
} from '@/components/marketCompareChart'

const theme: EChartsTheme = {
  background: '#fff',
  axis: '#ddd',
  split: '#eee',
  label: '#777',
  text: '#111',
  tooltipBackground: '#fff',
  tooltipBorder: '#ccc',
  focus: '#1677ff',
  accent: '#f58a07',
  muted: '#999',
  area: '#eef5ff',
}

describe('marketCompareChart', () => {
  it('股票与板块折线共用稳定的图例、坐标轴和缩放骨架', () => {
    const formatter = () => 'tooltip'
    const option = buildMarketCompareLineOption({
      theme,
      colors: ['#1677ff'],
      dates: ['2026-09-01', '2026-09-02'],
      series: [{ name: '示例', type: 'line', data: [0, 1] }],
      tooltipFormatter: formatter,
      scrollLegend: true,
      concreteValueBase: 10,
    })

    expect(option.legend).toMatchObject({ data: ['示例'], type: 'scroll' })
    expect(option.xAxis).toMatchObject({ data: ['2026-09-01', '2026-09-02'] })
    expect(option.yAxis).toHaveLength(2)
    expect(option.yAxis.map((axis) => axis.position)).toEqual(['left', 'right'])
    const concreteFormatter = option.yAxis[0].axisLabel.formatter
    expect(typeof concreteFormatter).toBe('function')
    if (typeof concreteFormatter === 'function') {
      expect(concreteFormatter(0)).toBe('10.00')
      expect(concreteFormatter(5)).toBe('10.50')
    }
    const percentFormatter = option.yAxis[1].axisLabel.formatter
    expect(typeof percentFormatter).toBe('function')
    if (typeof percentFormatter === 'function') {
      expect(percentFormatter(12.3456)).toBe('+12.35%')
      expect(percentFormatter(-2.3456)).toBe('-2.35%')
      expect(percentFormatter(0)).toBe('0.00%')
    }
    expect(option.yAxis[0].min).toBe(option.yAxis[1].min)
    expect(option.yAxis[0].max).toBe(option.yAxis[1].max)
    expect(option.dataZoom).toHaveLength(2)
    expect(option.tooltip.formatter).toBe(formatter)
  })

  it('统一序列色、金融涨跌色和 tooltip 转义', () => {
    expect(marketCompareLineColors(theme).slice(0, 2)).toEqual([theme.focus, theme.accent])
    expect(marketCompareChangeColors(theme)).toMatchObject({ neutral: theme.text })
    expect(escapeChartHtml('<板块 & "股票">')).toBe('&lt;板块 &amp; &quot;股票&quot;&gt;')
  })
})
