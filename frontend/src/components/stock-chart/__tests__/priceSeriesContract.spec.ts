import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { movingAverage } from '../chartUtils'

// 两种语言共享期望样例，防止图表显示计算与后端 MA 各自漂移。
const cases = JSON.parse(readFileSync(new URL(
  '../../../../../backend/tests/fixtures/price_series_contract.json', import.meta.url,
), 'utf8')) as Array<{ values: Array<number | null>; period: number; expected: Array<number | null> }>

describe('图表与后端价格计算契约', () => {
  it.each(cases)('满窗且保留精度：$values', ({ values, period, expected }) => {
    const actual = movingAverage(values.map((v) => v ?? Number.NaN), period)
    expected.forEach((value, index) => {
      if (value == null) expect(actual[index]).toBeNull()
      else expect(actual[index]).toBeCloseTo(value, 12)
    })
  })

  it('无穷值窗口缺数，离开窗口后恢复', () => {
    expect(movingAverage([1, Infinity, 3, 4, 5], 2)).toEqual([null, null, null, 3.5, 4.5])
  })
})
