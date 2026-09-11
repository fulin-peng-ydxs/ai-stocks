import { describe, expect, it } from 'vitest'
import {
  formatSectorInflow,
  formatSectorPercent,
  metricKind,
  metricSeries,
  metricWindow,
  sectorValueClass,
  toBoardChartBars,
} from '@/utils/sectorCompare'
import type { SectorBar } from '@/api/sectors'

function bar(trade_date: string, close: number, pre_close?: number | null): SectorBar {
  return { trade_date, open: close, high: close, low: close, close, pre_close, volume: 1, amount: 1 }
}

describe('metricSeries（区间累计涨跌幅）', () => {
  it('累计涨跌以首个有效收盘为基准', () => {
    const bars = [bar('2026-08-04', 100), bar('2026-08-05', 105), bar('2026-08-06', 98)]
    expect(metricSeries(bars, 'cum')).toEqual([0, 5, -2])
  })

  it('累计涨跌跳过首个无效收盘，以首个有效值为基准', () => {
    const bars = [bar('2026-08-04', 0), bar('2026-08-05', 100), bar('2026-08-06', 110)]
    expect(metricSeries(bars, 'cum')).toEqual([null, 0, 10])
  })

  it('固定窗口指标（5日涨幅）与累计涨跌同为区间累计口径', () => {
    // roll_5d 现在也是「以该序列首有效收盘为基准」的区间累计，窗口由数据加载层决定
    const bars = [bar('2026-08-04', 100), bar('2026-08-05', 105), bar('2026-08-06', 98)]
    expect(metricSeries(bars, 'roll_5d')).toEqual([0, 5, -2])
  })

  it('截面指标返回全 null（由页面取快照，不在 bars 上计算）', () => {
    const bars = [bar('2026-08-04', 100), bar('2026-08-05', 105)]
    expect(metricSeries(bars, 'inflow')).toEqual([null, null])
    expect(metricSeries(bars, 'breadth')).toEqual([null, null])
  })
})

describe('metricWindow', () => {
  it('累计涨跌窗口跟随周期选择器', () => {
    expect(metricWindow('cum', 60)).toBe(60)
    expect(metricWindow('cum', 1)).toBe(1)
  })

  it('固定滚动指标窗口返回自身，不受周期影响', () => {
    expect(metricWindow('roll_5d', 250)).toBe(5)
    expect(metricWindow('roll_20d', 60)).toBe(20)
  })
})

describe('metricKind', () => {
  it('累计涨跌窗口=1（单日）退化为柱状，其余折线', () => {
    expect(metricKind('cum', 1)).toBe('bar')
    expect(metricKind('cum', 5)).toBe('line')
    expect(metricKind('cum', 250)).toBe('line')
  })

  it('截面指标恒为柱状', () => {
    expect(metricKind('inflow', 60)).toBe('bar')
    expect(metricKind('breadth', 60)).toBe('bar')
  })

  it('固定滚动指标恒为折线', () => {
    expect(metricKind('roll_5d', 5)).toBe('line')
    expect(metricKind('roll_20d', 250)).toBe('line')
  })
})

describe('板块图表适配与展示格式', () => {
  it('两页共享同一原始指数到工作区映射，首根优先使用接口返回的区间外前收', () => {
    const rows = [bar('2026-08-04', 100, 98), bar('2026-08-05', 105, 100)]
    expect(toBoardChartBars(rows)).toEqual([
      expect.objectContaining({ date: '2026-08-04', close: 100, pre_close: 98 }),
      expect.objectContaining({ date: '2026-08-05', close: 105, pre_close: 100 }),
    ])
  })

  it('兼容不带前收的轻量序列，后续点仍回落到前一收盘', () => {
    const rows = [bar('2026-08-04', 100), bar('2026-08-05', 105)]
    expect(toBoardChartBars(rows).map((item) => item.pre_close)).toEqual([null, 100])
  })

  it('百分比、资金流和涨跌样式统一处理空值、非有限值与正负号', () => {
    expect(formatSectorPercent(1.2)).toBe('+1.20%')
    expect(formatSectorPercent(Number.NaN)).toBe('—')
    expect(formatSectorInflow(-2.5)).toBe('-2.50 亿')
    expect(sectorValueClass(null)).toBe('muted')
    expect(sectorValueClass(0)).toBe('')
    expect(sectorValueClass(2)).toBe('up')
  })
})
