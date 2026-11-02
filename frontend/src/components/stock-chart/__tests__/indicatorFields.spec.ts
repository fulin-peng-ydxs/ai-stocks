import { describe, expect, it } from 'vitest'
import { formatIndicatorValue } from '../indicatorFields'

describe('指标输出展示契约', () => {
  it('均线与价格固定两位，布尔值和缺失值有独立语义', () => {
    expect(formatIndicatorValue(8.2585, 'ma20')).toBe('8.26')
    expect(formatIndicatorValue(1000, 'ma60')).toBe('1,000.00')
    expect(formatIndicatorValue(0.258953, 'dist_to_high_2y')).toBe('0.26')
    expect(formatIndicatorValue(false, 'is_bull_arrange')).toBe('否')
    expect(formatIndicatorValue(null, 'ma20')).toBe('—')
    expect(formatIndicatorValue(NaN, 'ma20')).toBe('—')
  })
})
