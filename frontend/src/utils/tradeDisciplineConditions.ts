import type { CheckinOperation, ConditionFact, DraftStockRule } from '@/api/tradeDiscipline'
import { decimalToMinorUnits } from './fixedDecimal'
import { formatMoney } from './money'

export const conditionFilterOptions = [
  { label: '不限', value: 'any' }, { label: '排除', value: 'exclude' }, { label: '仅限', value: 'only' },
]
export const conditionFactOptions = [
  { label: '是', value: 'yes' }, { label: '否', value: 'no' }, { label: '未知', value: 'unknown' },
]
export const stockConditionFields = [
  { key: 'st_filter', label: '是否ST' },
  { key: 'loss_filter', label: '是否亏损' },
  { key: 'st_risk_filter', label: '是否存在ST风险' },
] as const
export const manualConditionFields = [
  { key: 'loss_status', filter: 'loss_filter', label: '是否亏损' },
  { key: 'st_risk_status', filter: 'st_risk_filter', label: '是否存在ST风险' },
] as const

export function conditionFactLabel(value?: ConditionFact | null): string {
  return conditionFactOptions.find((item) => item.value === value)?.label ?? '未记录'
}

/** 配置、打卡及历史共享条件摘要，不把未配置条件说成已核验。 */
export function stockConditionSummary(rule?: DraftStockRule): string {
  if (!rule) return ''
  const parts: string[] = []
  if (rule.price_min || rule.price_max) {
    const low = rule.price_min ? formatMoney(rule.price_min, { digits: 4 }) : ''
    const high = rule.price_max ? formatMoney(rule.price_max, { digits: 4 }) : ''
    parts.push(`股价 ${low && high ? `${low}～${high}` : low ? `≥${low}` : `≤${high}`} 元`)
  }
  for (const [key, label] of [['st_filter', 'ST'], ['loss_filter', '亏损'], ['st_risk_filter', 'ST风险']] as const) {
    const mode = rule[key] ?? 'any'
    if (mode !== 'any') parts.push(`${mode === 'exclude' ? '排除' : '仅限'}${label}`)
  }
  return parts.length ? parts.join(' · ') : '股价与状态不限'
}

export function stockConditionWarnings(rule: DraftStockRule | undefined, operation: CheckinOperation): string[] {
  if (!rule || operation.side !== 'buy') return []
  const warnings: string[] = []
  const price = decimalToMinorUnits(operation.price, 4)
  const low = decimalToMinorUnits(rule.price_min, 4)
  const high = decimalToMinorUnits(rule.price_max, 4)
  if (low !== null || high !== null) {
    if (price === null) warnings.push('成交价未记录，无法核对股价条件')
    else if ((low !== null && price < low) || (high !== null && price > high)) warnings.push('成交价不符合股价条件')
  }
  const st = operation.is_st === true ? 'yes' : operation.is_st === false ? 'no' : 'unknown'
  for (const [filter, fact, label] of [
    [rule.st_filter, st, 'ST状态'],
    [rule.loss_filter, operation.loss_status, '亏损状态'],
    [rule.st_risk_filter, operation.st_risk_status, 'ST风险'],
  ] as const) {
    if (!filter || filter === 'any') continue
    if (!fact || fact === 'unknown') warnings.push(`${label}未知，无法核对`)
    else if ((fact === 'yes') !== (filter === 'only')) warnings.push(`${label}不符合选股条件`)
  }
  return warnings
}

export function holdingCountWarning(limit?: number | null, actual?: number | null): string {
  if (limit == null) return ''
  if (actual == null) return '尚未记录当日最大同时持仓数'
  return actual > limit ? `当日最大同时持仓 ${actual} 只，超过本套规则上限 ${limit} 只；请核对履约自评` : ''
}
