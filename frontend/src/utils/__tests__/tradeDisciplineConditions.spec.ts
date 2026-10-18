import { describe, expect, it } from 'vitest'
import type { CheckinOperation, DraftStockRule } from '@/api/tradeDiscipline'
import { holdingCountWarning, manualConditionDefaults, stockConditionSummary, stockConditionWarnings, stockConditionViolations } from '../tradeDisciplineConditions'

const rule: DraftStockRule = {
  detail_id: 's', name: '选股', max_capital: '100', content: '趋势', display_order: 1, enabled: true,
  price_min: '5.1234', price_max: '10', st_filter: 'exclude', loss_filter: 'exclude', st_risk_filter: 'only',
}
const operation: CheckinOperation = {
  stock_code: '600000.SH', stock_name_snapshot: '股票', side: 'buy', stock_rule_id: 's', action_rule_id: 'a',
  price: '5.1234', quantity: null, amount: null, fee: null, operated_at: null, note: null, display_order: 1,
  is_st: false, loss_status: 'no', st_risk_status: 'yes',
}

describe('交易纪律选股条件', () => {
  it('人工事实按买入规则预填，不限、缺失规则与卖出不预填', () => {
    expect(manualConditionDefaults(rule, 'buy')).toEqual({ loss_status: 'no', st_risk_status: 'yes' })
    expect(manualConditionDefaults({ ...rule, loss_filter: 'any', st_risk_filter: undefined }, 'buy'))
      .toEqual({ loss_status: null, st_risk_status: null })
    expect(manualConditionDefaults(undefined, 'buy')).toEqual({ loss_status: null, st_risk_status: null })
    expect(manualConditionDefaults(rule, 'sell')).toEqual({ loss_status: null, st_risk_status: null })
  })
  it('保留价格四位精度，摘要只列出已配置的限制', () => {
    expect(stockConditionSummary(rule)).toBe('股价 5.1234～10.0000 元 · 排除ST · 排除亏损 · 仅限ST风险')
    expect(stockConditionSummary({ ...rule, price_min: null, price_max: null, st_filter: 'any', loss_filter: 'any', st_risk_filter: 'any' })).toBe('股价与状态不限')
  })
  it('包含上下边界，同股卖出不触发选股差异', () => {
    expect(stockConditionWarnings(rule, operation)).toEqual([])
    expect(stockConditionWarnings(rule, { ...operation, price: '10' })).toEqual([])
    expect(stockConditionWarnings(rule, { ...operation, price: '5.1233' })).toEqual(['成交价不符合股价条件'])
    expect(stockConditionWarnings(rule, { ...operation, side: 'sell', price: null, is_st: true })).toEqual([])
  })
  it('区分未知、未填与明确不符合，不修改事实或自评', () => {
    expect(stockConditionWarnings(rule, { ...operation, price: null, is_st: null, loss_status: 'unknown', st_risk_status: 'no' })).toEqual([
      '成交价未记录，无法核对股价条件', 'ST状态未知，无法核对', '亏损状态未知，无法核对', 'ST风险不符合选股条件',
    ])
    expect(operation.loss_status).toBe('no')
  })
  it('仅已确认违反条件进入违规集合，未知与卖出保持可自评', () => {
    expect(stockConditionViolations(rule, { ...operation, is_st: true })).toEqual(['ST状态不符合选股条件'])
    expect(stockConditionViolations(rule, { ...operation, price: null, is_st: null, loss_status: 'unknown', st_risk_status: 'unknown' })).toEqual([])
    expect(stockConditionViolations(rule, { ...operation, side: 'sell', is_st: true })).toEqual([])
    expect(stockConditionViolations({ ...rule, st_filter: 'any' }, { ...operation, is_st: true })).toEqual([])
  })
  it('峰值0有效，等于上限符合，缺失与超限分别提示', () => {
    expect(holdingCountWarning(null, null)).toBe('')
    expect(holdingCountWarning(2, 0)).toBe('')
    expect(holdingCountWarning(2, 2)).toBe('')
    expect(holdingCountWarning(2, null)).toContain('尚未记录')
    expect(holdingCountWarning(2, 3)).toContain('超过本套规则上限 2 只')
  })
})
