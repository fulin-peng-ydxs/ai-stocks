import type { CheckinOperation, ChecklistCategory, ConditionFact, DraftStockRule, StockChecklistItem, StockChecklistResult } from '@/api/tradeDiscipline'
import { decimalToMinorUnits } from './fixedDecimal'
import { formatMoney } from './money'
import { operationSTStatus } from './tradeDisciplineOperations'

export const conditionFilterOptions = [
  { label: '不限', value: 'any' }, { label: '排除', value: 'exclude' }, { label: '仅限', value: 'only' },
]
export const conditionFactOptions = [
  { label: '是', value: 'yes' }, { label: '否', value: 'no' },
]
export const checklistCategories: Array<{ value: ChecklistCategory; label: string }> = [
  { value: 'basic', label: '基本条件' }, { value: 'risk', label: '风险排除' },
  { value: 'technical', label: '技术形态' },
]
export type ConditionSection = ChecklistCategory | 'notes'
export type ConditionSectionsState = Partial<Record<ConditionSection, boolean>>
export function checklistCategory(category: StockChecklistItem['category']): ChecklistCategory {
  return category === 'other' ? 'technical' : category
}
export const checklistResultOptions = [
  { label: '符合', value: 'yes' }, { label: '不符合', value: 'no' },
]

export interface ChecklistCategoryOption { value: string; label: string; disabled?: boolean }

/** 字典项、固定字段分区及历史快照共同构成分组，停用/删除分类也不能吞掉旧条件。 */
export function conditionCategories(items: StockChecklistItem[], options: readonly ChecklistCategoryOption[] = checklistCategories, snapshot = false): ChecklistCategoryOption[] {
  const groups = new Map<string, ChecklistCategoryOption>(checklistCategories.map(item => [item.value, { ...item, disabled: true }]))
  for (const item of options) groups.set(item.value, { ...item })
  for (const item of items) {
    const value = checklistCategory(item.category)
    const existing = groups.get(value)
    if (!existing) groups.set(value, { value, label: item.category_label || value, disabled: true })
    else if (snapshot && item.category_label) groups.set(value, { ...existing, label: item.category_label })
  }
  return [...groups.values()]
}

/** 组内保留顺序，兼容未知/停用分类；不能按固定枚举筛选而丢弃检查项。 */
export function normalizeChecklist(items: StockChecklistItem[], options: readonly ChecklistCategoryOption[] = checklistCategories): StockChecklistItem[] {
  return conditionCategories(items, options).flatMap(({ value }) => items.filter(item => checklistCategory(item.category) === value))
    .map((item, index) => ({ ...item, category: checklistCategory(item.category), display_order: index + 1 }))
}

/** 收起时仍展示条件范围及核对进度；旧分类只在展示层归入技术形态。 */
export function conditionSectionSummary(rule: DraftStockRule | undefined, category: ChecklistCategory,
  checking = false, results?: StockChecklistResult[] | null, operation?: CheckinOperation): string {
  const items = (rule?.checklist_items ?? []).filter(item => checklistCategory(item.category) === category)
  const states: Array<ConditionFact | 'pending'> = items.map(item => results?.find(result => result.item_id === item.item_id)?.status ?? 'pending')
  let summary = !['basic', 'risk'].includes(category) ? '' : stockConditionSummary({
    ...rule, checklist_items: [],
    ...(category === 'basic' ? { st_filter: 'any', loss_filter: 'any', st_risk_filter: 'any' }
      : { price_min: null, price_max: null }),
  } as DraftStockRule)
  if (summary === '股价与状态不限') summary = category === 'basic' ? '股价不限' : '风险状态不限'
  if (operation && rule) {
    if (category === 'basic' && (rule.price_min || rule.price_max)) {
      const price = decimalToMinorUnits(operation.price, 4)
      const violated = stockConditionViolations({ ...rule, checklist_items: [], st_filter: 'any', loss_filter: 'any', st_risk_filter: 'any' }, operation).length > 0
      states.push(price === null ? 'unknown' : violated ? 'no' : 'yes')
    }
    if (category === 'risk') {
      for (const [filter, fact] of [
        [rule.st_filter, operation.is_st == null ? 'unknown' : operation.is_st ? 'yes' : 'no'],
        [rule.loss_filter, operation.loss_status], [rule.st_risk_filter, operation.st_risk_status],
      ] as const) {
        if (!filter || filter === 'any') continue
        states.push(fact == null ? 'pending' : fact === 'unknown' ? 'unknown' : (fact === 'yes') === (filter === 'only') ? 'yes' : 'no')
      }
    }
  }
  const parts = summary ? [summary] : []
  const count = checking ? states.length : items.length
  if (count || !['basic', 'risk'].includes(category)) parts.push(`${count} 项${checking ? '核对' : '人工检查'}`)
  if (checking) for (const [status, label] of [['pending', '待核对'], ['no', '不符合'], ['unknown', '未知']] as const) {
    const count = states.filter(value => value === status).length
    if (count) parts.push(`${label} ${count}`)
  }
  return parts.join(' · ')
}

export function checklistMissingItem(rule: DraftStockRule | undefined, operation: CheckinOperation): StockChecklistItem | undefined {
  if (operation.side !== 'buy') return undefined
  // 移除填报候选不改变历史快照的合法状态，修正其他字段时仍可保留旧未知值。
  return rule?.checklist_items?.find(item => !(operation.checklist_results ?? []).some(result =>
    result.item_id === item.item_id && ['yes', 'no', 'unknown'].includes(result.status)))
}

export function conditionViolationTarget(rule: DraftStockRule | undefined, operation: CheckinOperation): { section: ChecklistCategory; itemId?: string } | undefined {
  if (!rule || operation.side !== 'buy') return undefined
  const fixed = stockConditionViolations({ ...rule, checklist_items: [] }, operation)
  if (fixed.length) return { section: fixed[0] === '成交价不符合股价条件' ? 'basic' : 'risk' }
  const failed = rule.checklist_items?.find(item => operation.checklist_results?.some(result => result.item_id === item.item_id && result.status === 'no'))
  return failed ? { section: checklistCategory(failed.category), itemId: failed.item_id } : undefined
}

export function stockRuleHasContent(rule: DraftStockRule): boolean {
  return Boolean(rule.content?.trim() || rule.checklist_items?.length || rule.price_min || rule.price_max
    || stockConditionFields.some(field => rule[field.key] && rule[field.key] !== 'any'))
}

export function checklistMissing(rule: DraftStockRule | undefined, operation: CheckinOperation): boolean {
  return !!checklistMissingItem(rule, operation)
}
export const stockConditionFields = [
  { key: 'st_filter', label: '是否ST' },
  { key: 'loss_filter', label: '是否亏损' },
  { key: 'st_risk_filter', label: '是否存在ST风险' },
] as const
export const manualConditionFields = [
  { key: 'loss_status', filter: 'loss_filter', label: '是否亏损' },
  { key: 'st_risk_status', filter: 'st_risk_filter', label: '是否存在ST风险' },
] as const

/** 表单按规则预填人工事实，不推导财报或风险；ST仍以交易日权威数据为准。 */
export function manualConditionDefaults(
  rule: DraftStockRule | undefined,
  side: CheckinOperation['side'],
): Pick<CheckinOperation, 'loss_status' | 'st_risk_status'> {
  const defaults: Pick<CheckinOperation, 'loss_status' | 'st_risk_status'> = {
    loss_status: null, st_risk_status: null,
  }
  if (side === 'buy') {
    for (const field of manualConditionFields) {
      const filter = rule?.[field.filter]
      defaults[field.key] = filter === 'exclude' ? 'no' : filter === 'only' ? 'yes' : null
    }
  }
  return defaults
}

/** 新增或重新关联时预填符合；由操作编辑器写入表单，展示组件不补写历史。 */
export function checklistDefaults(
  rule: DraftStockRule | undefined,
  side: CheckinOperation['side'],
): StockChecklistResult[] | null {
  return side === 'buy' && rule?.checklist_items?.length
    ? rule.checklist_items.map(item => ({ item_id: item.item_id, status: 'yes' }))
    : null
}

export function checklistResultLabel(value?: ConditionFact | null): string {
  return value === 'unknown' ? '未知' : checklistResultOptions.find(item => item.value === value)?.label ?? '未记录'
}

export function conditionFactLabel(value?: ConditionFact | null): string {
  if (value === 'unknown') return '未知' // 历史快照仍需如实展示，填报候选不再提供未知。
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
  if (rule.checklist_items?.length) parts.push(`${rule.checklist_items.length} 项人工检查`)
  return parts.length ? parts.join(' · ') : '股价与状态不限'
}

export function stockConditionWarnings(rule: DraftStockRule | undefined, operation: CheckinOperation): string[] {
  return stockConditionIssues(rule, operation, true)
}

export function stockConditionViolations(rule: DraftStockRule | undefined, operation: CheckinOperation): string[] {
  return stockConditionIssues(rule, operation, false)
}

function stockConditionIssues(rule: DraftStockRule | undefined, operation: CheckinOperation, includeUnknown: boolean): string[] {
  if (!rule || operation.side !== 'buy') return []
  const warnings: string[] = []
  const price = decimalToMinorUnits(operation.price, 4)
  const low = decimalToMinorUnits(rule.price_min, 4)
  const high = decimalToMinorUnits(rule.price_max, 4)
  if (low !== null || high !== null) {
    if (price === null && includeUnknown) warnings.push('成交价未记录，无法核对股价条件')
    else if (price !== null && ((low !== null && price < low) || (high !== null && price > high))) warnings.push('成交价不符合股价条件')
  }
  const { is_st: isSt } = operationSTStatus(operation)
  const st = isSt === true ? 'yes' : isSt === false ? 'no' : 'unknown'
  for (const [filter, fact, label] of [
    [rule.st_filter, st, 'ST状态'],
    [rule.loss_filter, operation.loss_status, '亏损状态'],
    [rule.st_risk_filter, operation.st_risk_status, 'ST风险'],
  ] as const) {
    if (!filter || filter === 'any') continue
    if (!fact || fact === 'unknown') {
      if (includeUnknown) warnings.push(`${label}未知，无法核对`)
    }
    else if ((fact === 'yes') !== (filter === 'only')) warnings.push(`${label}不符合选股条件`)
  }
  for (const item of rule.checklist_items ?? []) {
    const status = operation.checklist_results?.find(result => result.item_id === item.item_id)?.status
    if (status === 'no') warnings.push(`选股条件“${item.text}”不符合`)
    else if (includeUnknown && status !== 'yes') warnings.push(`选股条件“${item.text}”${status === 'unknown' ? '未知' : '未记录'}，无法核对`)
  }
  return warnings
}

export function holdingCountWarning(limit?: number | null, actual?: number | null): string {
  if (limit == null) return ''
  if (actual == null) return '尚未记录当日最大同时持仓数'
  return actual > limit ? `当日最大同时持仓 ${actual} 只，超过本套规则上限 ${limit} 只；请核对履约自评` : ''
}
