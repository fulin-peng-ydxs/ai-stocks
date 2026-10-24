import type { CheckinOperation } from '@/api/tradeDiscipline'

/** 成交明细的必填字段与精度，表单提交和折叠操作卡共同消费。 */
export const operationFinancialFields = [
  { key: 'price', label: '成交价', scale: 4 },
  { key: 'quantity', label: '数量', scale: 4 },
  { key: 'amount', label: '成交金额', scale: 2 },
  { key: 'fee', label: '费用', scale: 2 },
] as const

export function missingOperationFinancialField(operation: CheckinOperation) {
  return operationFinancialFields.find(({ key }) => operation[key] == null || operation[key] === '')
}
