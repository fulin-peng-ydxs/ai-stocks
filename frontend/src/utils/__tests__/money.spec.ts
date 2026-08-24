import { describe, expect, it } from 'vitest'
import {
  formatCompactMoneyYuan,
  formatMoney,
  formatMoneyInput,
  parseMoneyInput,
} from '@/utils/money'

describe('money formatter', () => {
  it('精确格式化大额字符串且不经过浮点数', () => {
    expect(formatMoney('999999999999999999.99')).toBe('999,999,999,999,999,999.99')
    expect(formatMoney('-1000000.5', { digits: 2 })).toBe('-1,000,000.50')
  })

  it('按调用方精度格式化 number，并统一处理符号与空值', () => {
    expect(formatMoney(1234567.8, { digits: 0 })).toBe('1,234,568')
    expect(formatMoney(1234567.8, { digits: 2, forceSign: true })).toBe('+1,234,567.80')
    expect(formatMoney(Number.NaN)).toBe('—')
  })

  it('输入格式化只添加分隔符，解析时移除分隔符', () => {
    expect(formatMoneyInput('1000000.25')).toBe('1,000,000.25')
    expect(formatMoneyInput('-1000000.')).toBe('-1,000,000.')
    expect(parseMoneyInput('1,000,000.25')).toBe('1000000.25')
  })

  it('万元和亿元缩放后仍对数值部分使用三位分隔', () => {
    expect(formatCompactMoneyYuan(1_234_567_890_000, { digits: 2 }))
      .toBe('12,345.68 亿')
    expect(formatCompactMoneyYuan(12_345_000, { digits: 1 })).toBe('1,234.5 万')
  })
})
