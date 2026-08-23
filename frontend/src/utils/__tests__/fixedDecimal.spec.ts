import { describe, expect, it } from 'vitest'
import {
  decimalToMinorUnits,
  formatDecimalString,
  formatMinorUnits,
  isFixedDecimalInput,
  multiplyToMinorUnits,
} from '@/utils/fixedDecimal'

describe('fixedDecimal', () => {
  it('用十进制定点单位精确处理常见及大额边界', () => {
    expect(decimalToMinorUnits('0.10')).toBe(10n)
    expect(decimalToMinorUnits('0.20')).toBe(20n)
    expect(decimalToMinorUnits('100000.09')).toBe(10000009n)
    expect(decimalToMinorUnits('9007199254740992.01')).toBe(900719925474099201n)
    expect(decimalToMinorUnits('999999999999999999.99')).toBe(99999999999999999999n)
    expect(decimalToMinorUnits('999999999999999999.98')).toBe(99999999999999999998n)
    expect(formatMinorUnits(30n)).toBe('0.30')
    expect(formatMinorUnits(-1n)).toBe('-0.01')
  })

  it('拒绝超过指定精度或非十进制普通写法的输入', () => {
    expect(decimalToMinorUnits('0.001')).toBeNull()
    expect(decimalToMinorUnits('not-a-number')).toBeNull()
  })

  it('按 NUMERIC(20,2) 的整数位和小数位限制受控输入', () => {
    expect(isFixedDecimalInput('9007199254740992.01')).toBe(true)
    expect(isFixedDecimalInput('999999999999999999.99')).toBe(true)
    expect(isFixedDecimalInput('9999999999999999999.99')).toBe(false)
    expect(isFixedDecimalInput('999999999999999999.999')).toBe(false)
  })

  it('精确计算价量乘积并格式化超出安全整数范围的快照', () => {
    expect(multiplyToMinorUnits('9007199254740992.0001', '1.0000')).toBe(900719925474099200n)
    expect(multiplyToMinorUnits('0.0100', '0.5000')).toBe(1n)
    expect(formatDecimalString('999999999999999999.99')).toBe('999,999,999,999,999,999.99')
    expect(formatDecimalString('9007199254740992.0001', 4)).toBe('9,007,199,254,740,992.0001')
  })
})
