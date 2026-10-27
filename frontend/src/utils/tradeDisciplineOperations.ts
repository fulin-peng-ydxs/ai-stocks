import type { CheckinOperation } from '@/api/tradeDiscipline'

/** 已保存的逐日核验快照优先，兼容新选股票的顶层字段；明确未知不能回退成已知。 */
export function operationSTStatus(operation: CheckinOperation) {
  const source = operation.selection_facts ?? operation
  return { is_st: source.is_st ?? null, st_as_of_date: source.st_as_of_date ?? null }
}

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
