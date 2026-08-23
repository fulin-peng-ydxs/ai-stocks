import { describe, expect, it } from 'vitest'
import { decimalToMinorUnits, formatMinorUnits } from '@/utils/fixedDecimal'

describe('fixedDecimal', () => {
  it('用十进制定点单位精确处理常见浮点边界', () => {
    expect(decimalToMinorUnits(0.1)).toBe(10n)
    expect(decimalToMinorUnits(0.2)).toBe(20n)
    expect(decimalToMinorUnits('100000.09')).toBe(10000009n)
    expect(formatMinorUnits(30n)).toBe('0.30')
    expect(formatMinorUnits(-1n)).toBe('-0.01')
  })

  it('拒绝超过指定精度或非十进制普通写法的输入', () => {
    expect(decimalToMinorUnits('0.001')).toBeNull()
    expect(decimalToMinorUnits('not-a-number')).toBeNull()
    expect(decimalToMinorUnits(1e21)).toBeNull()
  })
})
