import { describe, expect, it } from 'vitest'
import type { CheckinOperation } from '@/api/tradeDiscipline'
import { missingOperationFinancialField, operationFinancialFields } from '../tradeDisciplineOperations'

const complete = { price: '10', quantity: '100', amount: '1000', fee: '0' } as CheckinOperation

describe('成交明细必填', () => {
  it.each(operationFinancialFields)('$label识别未填写，不把0识别为空', ({ key }) => {
    for (const value of [null, undefined, '']) {
      expect(missingOperationFinancialField({ ...complete, [key]: value })?.key).toBe(key)
    }
    expect(missingOperationFinancialField({ ...complete, [key]: '0' })).toBeUndefined()
  })
  it('完整成交明细不要求选填的操作时间或说明', () => {
    expect(missingOperationFinancialField(complete)).toBeUndefined()
  })
})
