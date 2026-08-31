import { describe, expect, it } from 'vitest'
import { formatMarketPercent, marketValueClass } from '@/utils/marketValue'

describe('marketValue', () => {
  it('统一涨跌百分比格式与语义颜色', () => {
    expect(formatMarketPercent(12.345)).toBe('+12.35%')
    expect(formatMarketPercent(-2.5)).toBe('-2.50%')
    expect(formatMarketPercent(null)).toBe('—')
    expect(marketValueClass(1)).toBe('up')
    expect(marketValueClass(-1)).toBe('down')
    expect(marketValueClass(0)).toBe('')
    expect(marketValueClass(Number.NaN)).toBe('muted')
  })
})
