import { describe, expect, it } from 'vitest'
import type { Bar } from '@/api/stocks'
import {
  aggregateKlineBars,
  buildKlinePeriodSeries,
  klinePeriodKey,
  tradingDaysBetween,
} from '../klinePeriod'

function bar(date: string, close: number, overrides: Partial<Bar> = {}): Bar {
  return {
    date,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    pre_close: close - 0.5,
    volume: close * 100,
    amount: close * 1_000,
    turnover_rate: close / 100,
    ...overrides,
  }
}

describe('klinePeriod', () => {
  it('按 ISO 自然周处理跨年边界', () => {
    expect(klinePeriodKey('2025-12-29', 'week')).toBe('2026-W01')
    expect(klinePeriodKey('2026-01-02', 'week')).toBe('2026-W01')
    expect(klinePeriodKey('2026-01-05', 'week')).toBe('2026-W02')
  })

  it('按自然月和自然年切分跨界数据', () => {
    const source = [
      bar('2025-12-31', 10),
      bar('2026-01-02', 11),
      bar('2026-01-30', 12),
      bar('2026-02-02', 13),
    ]
    expect(aggregateKlineBars(source, 'month').map((item) => item.date))
      .toEqual(['2025-12-31', '2026-01-30', '2026-02-02'])
    expect(aggregateKlineBars(source, 'year').map((item) => item.date))
      .toEqual(['2025-12-31', '2026-02-02'])
  })

  it('聚合 OHLCV、可空累计字段并保留未完成周期', () => {
    const rows = aggregateKlineBars([
      bar('2026-09-14', 10, { open: 9, high: 12, low: 8, pre_close: 8.8, amount: null }),
      bar('2026-09-15', 11, { open: 10, high: 13, low: 9, amount: 2_000 }),
      bar('2026-09-18', 12, { open: 11, high: 14, low: 10, amount: 3_000 }),
      bar('2026-09-21', 13, { open: 12, high: 15, low: 11, amount: null, turnover_rate: null }),
    ], 'week')

    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({
      date: '2026-09-18',
      periodStartDate: '2026-09-14',
      periodEndDate: '2026-09-18',
      tradingDayCount: 3,
      open: 9,
      high: 14,
      low: 8,
      close: 12,
      pre_close: 8.8,
      amount: 5_000,
    })
    expect(rows[0]!.volume).toBe(3_300)
    expect(rows[0]!.turnover_rate).toBeCloseTo(0.33)
    expect(rows[1]).toMatchObject({ date: '2026-09-21', tradingDayCount: 1, amount: null })

    const missing = aggregateKlineBars([
      bar('2026-09-21', 13, { volume: null as unknown as number }),
      bar('2026-09-22', 14, { volume: Number.NaN }),
    ], 'week')
    expect(missing[0]!.volume).toBeNull()
  })

  it('严格保留可见范围首柱并移除同周期暖机重复柱', () => {
    const series = buildKlinePeriodSeries(
      [bar('2026-09-16', 12), bar('2026-09-17', 13), bar('2026-09-18', 14)],
      [bar('2026-09-14', 10), bar('2026-09-15', 11)],
      [],
      'week',
    )
    expect(series.warmupBars).toHaveLength(0)
    expect(series.bars).toHaveLength(1)
    expect(series.bars[0]).toMatchObject({
      periodStartDate: '2026-09-16',
      periodEndDate: '2026-09-18',
      tradingDayCount: 3,
    })
  })

  it('周期图表直接消费后端对应周期指标，不在前端重算', () => {
    const indicators = [{ trade_date: '2026-09-18', macd_hist: 0.25 }]
    const series = buildKlinePeriodSeries(
      [bar('2026-09-14', 10), bar('2026-09-18', 12)],
      [],
      indicators,
      'week',
    )

    expect(series.indicators).toEqual(indicators)
  })

  it('按聚合柱包含的实际交易日计算收盘间隔', () => {
    const bars = aggregateKlineBars([
      bar('2026-09-14', 10), bar('2026-09-15', 11), bar('2026-09-18', 12),
      bar('2026-09-21', 13), bar('2026-09-22', 14),
      bar('2026-09-28', 15),
    ], 'week')
    expect(tradingDaysBetween(bars, 0, 2)).toBe(3)
  })
})
