import { describe, expect, it } from 'vitest'
import { ALL_DAYS } from '@/composables/useKlinePrefs'
import {
  alignPriceComparison,
  PRICE_COMPARE_METRIC_ORDER,
  priceCompareLookback,
  priceCompareSetLookback,
  priceReturn,
  type PriceCompareSeries,
} from '@/utils/marketCompare'

function series(code: string, points: Array<[string, number]>): PriceCompareSeries {
  return {
    code,
    name: code,
    bars: points.map(([date, close]) => ({ date, close })),
  }
}

const calendar = (count: number) => Array.from({ length: count }, (_, index) => ({
  date: `2026-01-${String(index + 1).padStart(2, '0')}`,
  close: 100 + index,
}))

describe('marketCompare', () => {
  it('N 日收益严格使用 N+1 个市场收盘点，历史不足不缩短代算', () => {
    const dates = calendar(6)
    const stock = series('A', dates.map((bar, index) => [bar.date, 10 + index] as [string, number]))

    expect(priceReturn(stock, 5, dates)).toBe(50)
    expect(priceReturn(stock, 5, dates.slice(1))).toBeNull()
    expect(priceCompareLookback('roll_5d', 20)).toBe(61)
    expect(priceCompareLookback('roll_60d', 20)).toBe(61)
    expect(priceCompareSetLookback(['cum', 'roll_30d', 'roll_60d'], 120)).toBe(121)
  })

  it('按市场日历前向延续停牌收盘（纯对比下各序列从自身首个有效值起算）', () => {
    const dates = calendar(3)
    const first = series('A', [[dates[0]!.date, 10], [dates[2]!.date, 12]])
    const second = series('B', [[dates[0]!.date, 20], [dates[1]!.date, 18], [dates[2]!.date, 22]])
    const result = alignPriceComparison([first, second], 2, null, dates)

    expect(result.dates).toEqual(dates.map((bar) => bar.date))
    expect(result.closesByCode.A).toEqual([10, 10, 12])
    expect(result.valuesByCode.A).toEqual([0, 0, 20])
    expect(result.valuesByCode.B).toEqual([0, -10, 10])
  })

  it('纯对比（不对比指数）中个别序列上市前空档只留空，不否决整体且各自从自身起点起算', () => {
    const dates = calendar(3)
    const oldStock = series('A', dates.map((bar, index) => [bar.date, 10 + index] as [string, number]))
    const newStock = series('B', [[dates[1]!.date, 20], [dates[2]!.date, 22]])

    const fixed = alignPriceComparison([oldStock, newStock], 2, null, dates)
    expect(fixed.dates).toEqual(dates.map((bar) => bar.date))
    expect(fixed.valuesByCode.A).toEqual([0, 10, 20])
    expect(fixed.valuesByCode.B).toEqual([null, 0, 10])

    const all = alignPriceComparison([oldStock, newStock], ALL_DAYS, null, dates)
    expect(all.dates).toEqual(dates.map((bar) => bar.date))
    expect(all.valuesByCode.B).toEqual([null, 0, 10])
  })

  it('对比指数时个别序列上市较晚只缩短基准期，不否决整体且统一从共同基期起算', () => {
    const dates = calendar(3)
    const oldStock = series('A', dates.map((bar, index) => [bar.date, 10 + index] as [string, number]))
    const newStock = series('B', [[dates[1]!.date, 20], [dates[2]!.date, 22]])
    const benchmark = series('IDX', dates.map((bar, index) => [bar.date, 100 + index] as [string, number]))

    const result = alignPriceComparison([oldStock, newStock], 2, benchmark, dates)
    expect(result.dates).toEqual([dates[1]!.date, dates[2]!.date])
    expect(result.valuesByCode.A).toEqual([0, 9.09])     // 老股从共同基期(次新股上市日)起算
    expect(result.valuesByCode.B).toEqual([0, 10])
    expect(result.valuesByCode.IDX).toEqual([0, 0.99])
  })

  it('空的显式市场日历不会退回股票日期，且股票页指标包含 30/60 日', () => {
    const stock = series('A', [['2026-01-01', 10], ['2026-01-02', 11]])

    expect(priceReturn(stock, 1, [])).toBeNull()
    expect(alignPriceComparison([stock], 1, null, []).dates).toEqual([])
    expect(PRICE_COMPARE_METRIC_ORDER).toEqual([
      'cum', 'roll_5d', 'roll_10d', 'roll_20d', 'roll_30d', 'roll_60d',
    ])
  })
})
