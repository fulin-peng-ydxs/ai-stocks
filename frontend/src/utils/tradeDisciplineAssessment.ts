import type { CheckinAssessment, CheckinViolationItem } from '@/api/tradeDiscipline'

export const checkinAssessmentOptions: Array<{
  value: CheckinAssessment
  label: string
}> = [
  { value: 'complied', label: '已履约' },
  { value: 'partial', label: '部分履约' },
  { value: 'breached', label: '未履约' },
]

const assessmentLabels: Record<CheckinAssessment, string> = {
  complied: '已履约',
  partial: '部分履约',
  breached: '未履约',
}

export function checkinAssessmentLabel(assessment: CheckinAssessment): string {
  return assessmentLabels[assessment]
}

export function checkinAssessmentTagType(
  assessment: CheckinAssessment,
): 'success' | 'warning' | 'danger' {
  if (assessment === 'complied') return 'success'
  return assessment === 'partial' ? 'warning' : 'danger'
}

export function hasCheckinViolation(assessment: CheckinAssessment): boolean {
  return assessment !== 'complied'
}

// 今日表单和历史详情共用事项名称；空值保留旧快照未采集的含义。
export const checkinViolationItemOptions: Array<{ value: CheckinViolationItem; label: string }> = [
  { value: 'missed_buy', label: '应买未买' },
  { value: 'missed_sell', label: '应卖未卖' },
  { value: 'other', label: '其他规则未履约' },
]

export function checkinViolationItemsText(items?: CheckinViolationItem[] | null): string {
  if (items == null) return '未记录'
  return checkinViolationItemOptions.filter(option => items.includes(option.value))
    .map(option => option.label).join('、') || '未填写'
}
