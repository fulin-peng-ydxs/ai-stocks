import type { CheckinAssessment } from '@/api/tradeDiscipline'

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
