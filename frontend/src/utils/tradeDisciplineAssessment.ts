import type { CheckinAssessment, CheckinOperation, CheckinViolationItem } from '@/api/tradeDiscipline'

export const checkinAssessmentOptions: Array<{
  value: CheckinAssessment
  label: string
}> = [
  { value: 'complied', label: '已履约' },
  { value: 'partial', label: '部分履约' },
  { value: 'breached', label: '未履约' },
]

/** 表单和工作台帮助共用填写指引，说明整体自评与逐笔操作的关系。 */
export const checkinAssessmentGuides: Record<CheckinAssessment, { summary: string; details: string[] }> = {
  complied: {
    summary: '当日按本套规则执行；有交易就记录实际操作，没有交易可勾选“今日无操作”。',
    details: ['无需填写未履约事项、原因和详细说明；已确认选股条件不符或持仓超限时，不能选择已履约。'],
  },
  partial: {
    summary: '须同时有已履约操作和未履约依据；逐笔标记状态，并填写一个原因和详细说明。',
    details: [
      '至少一笔实际操作标记为已履约；全部操作未履约时请选择“未履约”。不能勾选“今日无操作”，已确认违规的操作不能标记已履约。',
      '未履约依据至少满足一项：有操作标记为未履约、勾选未履约事项，或当日实际持仓超限。只有原因和详细说明不能替代这些依据。',
      '例如一笔合规买入，加上勾选“应卖未卖”，即可记录部分履约；也可分别记录一笔已履约和一笔未履约操作。全部操作已履约且没有其他偏差时请选择“已履约”。',
    ],
  },
  breached: {
    summary: '填写一个未履约原因和详细说明；有交易就记录实际操作，无交易则勾选“今日无操作”并选择未履约事项。',
    details: [
      '未履约不等于没有交易。有买卖时仍需如实记录股票、方向和关联规则，不逐笔填写履约状态。',
      '例如应卖未卖且当天没有其他交易，勾选“今日无操作”和“应卖未卖”，再说明未卖原因。有实际操作时，“未履约事项”可选填。',
      '未履约事项可多选“应买未买、应卖未卖、买卖操作未履约”；原因只选或输入一个，详细说明必填。',
    ],
  },
}

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
  { value: 'other', label: '买卖操作未履约' },
]

export function checkinViolationItemsText(items?: CheckinViolationItem[] | null): string {
  if (items == null) return '未记录'
  return checkinViolationItemOptions.filter(option => items.includes(option.value))
    .map(option => option.label).join('、') || '未填写'
}

/** 与服务端一致：已履约操作 + 至少一种结构化未履约依据，不按交易笔数硬凑。 */
export function partialAssessmentIssue(
  operations: Pick<CheckinOperation, 'compliance_status'>[],
  violationItems: CheckinViolationItem[],
  hasKnownViolation: boolean,
): string | null {
  if (!operations.some(item => item.compliance_status === 'complied')) {
    return '部分履约须至少有一笔已履约操作；全部未履约请选择未履约'
  }
  if (!operations.some(item => item.compliance_status === 'breached')
    && !violationItems.length && !hasKnownViolation) {
    return '部分履约须同时记录未履约依据：未履约操作、未履约事项或实际持仓超限；均已履约请选择已履约'
  }
  return null
}
