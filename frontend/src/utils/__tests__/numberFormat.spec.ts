import { describe, expect, it } from 'vitest'
import { decimalText, displayDirection, formatCompactNumber, formatCompactQuantity, formatNumber, progressPercent } from '@/utils/numberFormat'
import { formatMoney, formatCompactMoneyYuan } from '@/utils/money'
import { formatMarketPercent, formatPercent, formatPercentPoints, formatReturn, marketValueClass } from '@/utils/marketValue'
import { formatTradePrice } from '@/utils/tradeNumeric'

describe('数值显示标准', () => {
  it.each([
    ['1.005', '1.01'], ['-1.005', '-1.01'], [1.005, '1.01'], [-1.005, '-1.01'],
    ['9.995', '10.00'], ['-9.995', '-10.00'], [12, '12.00'], ['-0.0049', '0.00'],
    ['0.005', '0.01'], ['-0.005', '-0.01'], [1e-7, '0.00'], [1e21, '1000000000000000000000.00'],
  ])('十进制舍入 %s → %s', (value, expected) => {
    expect(formatNumber(value)).toBe(expected)
  })
  it('不同业务类型补零、去尾零与参数原精度', () => {
    expect(formatNumber(85, 'score')).toBe('85.0')
    expect(formatNumber(0.8, 'coefficient')).toBe('0.8000')
    expect(formatNumber('0.85605', 'coefficient')).toBe('0.8561')
    expect(formatNumber(18.5, 'ratio')).toBe('18.50')
    expect(formatNumber(1234, 'count')).toBe('1,234')
    expect(formatNumber('1200.0000', 'quantity')).toBe('1,200')
    expect(formatNumber('12.5000', 'quantity')).toBe('12.5')
    expect(formatNumber('0.0003', 'parameter')).toBe('0.0003')
    expect(formatNumber(1.2, 'seconds')).toBe('1.2')
    expect(formatNumber(350, 'milliseconds')).toBe('350')
    expect(formatTradePrice('12.3')).toBe('12.3000')
  })
  it.each([null, undefined, '', ' ', 'null', 'NaN', 'Infinity', NaN, Infinity, -Infinity])('空值和非法值 %s 不伪造为零', value => {
    expect(formatNumber(value)).toBe('—')
    expect(formatMoney(value)).toBe('—')
    expect(formatMarketPercent(value)).toBe('—')
    expect(formatCompactNumber(value, '元')).toBe('—')
  })
  it('精确大额、科学记数与缩放不经过浮点数', () => {
    expect(formatMoney('999999999999999999.995')).toBe('1,000,000,000,000,000,000.00')
    expect(formatMoney('9007199254740992.005')).toBe('9,007,199,254,740,992.01')
    expect(decimalText('9007199254740992005e-3')).toBe('9007199254740992.005')
    expect(formatCompactMoneyYuan('99999999.999')).toBe('1.00 亿元')
    expect(formatCompactMoneyYuan('-99999999.999')).toBe('-1.00 亿元')
    expect(formatCompactMoneyYuan('9999.999')).toBe('1.00 万元')
    expect(formatCompactMoneyYuan(125000000)).toBe('1.25 亿元')
    expect(formatCompactQuantity('1250.0000', '手')).toBe('1,250 手')
    expect(formatCompactQuantity('12500', '手')).toBe('1.25 万手')
  })
  it('比例与百分数口径显式换算，百分点不混成收益率', () => {
    expect(formatPercent('0.1234', { input: 'ratio' })).toBe('12.34%')
    expect(formatPercent('12.34', { input: 'percent' })).toBe('12.34%')
    expect(formatReturn('0.032')).toBe('+3.20%')
    expect(formatPercent('0.65', { input: 'ratio' })).toBe('65.00%')
    expect(formatPercentPoints('0.023', 'ratio')).toBe('+2.30 个百分点')
    expect(formatPercentPoints(2.3)).toBe('+2.30 个百分点')
  })
  it('舍入后零无符号且不使用涨跌色', () => {
    for (const value of [-0, 0, 0.00001, -0.00001]) {
      expect(formatMoney(value, { forceSign: true })).toBe('0.00')
      expect(formatMarketPercent(value)).toBe('0.00%')
      expect(marketValueClass(value)).toBe('')
    }
    expect(marketValueClass(0.0001, { input: 'ratio' })).toBe('up')
    expect(marketValueClass('-0.00005', { input: 'ratio' })).toBe('down')
    expect(displayDirection('not a number')).toBeNull()
  })
  it('完成性指标直到真实完成才能显示100%', () => {
    expect(formatPercent('0.999999', { input: 'ratio', completion: true })).toBe('>99.99%')
    expect(formatPercent('99.999', { input: 'percent', completion: true })).toBe('>99.99%')
    expect(formatPercent(1, { input: 'ratio', completion: true })).toBe('100.00%')
    expect(formatPercent('0.999999', { input: 'ratio' })).toBe('100.00%')
    expect(progressPercent(0.999999)).toBe(99.99)
    expect(progressPercent(1)).toBe(100)
  })
})

it('极小值原始精度可用于详情，不改变固定精度主值', async () => {
  const { tinyValueHint } = await import('@/utils/numberFormat')
  const { formatMarketPercentDetail } = await import('@/utils/marketValue')
  expect(tinyValueHint('-0.00001', '%')).toBe('原始值 -0.00001%')
  expect(tinyValueHint(0, '%')).toBeUndefined()
  expect(tinyValueHint(1.23, '%')).toBeUndefined()
  expect(formatMarketPercentDetail(-0.00001)).toBe('0.00%（原始值 -0.00001%）')
})
