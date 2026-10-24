import { describe, expect, it } from 'vitest'
import type { CheckinOperation, CheckinViolationItem } from '@/api/tradeDiscipline'
import { partialAssessmentIssue } from '../tradeDisciplineAssessment'

describe('部分履约须同时有正反两类依据', () => {
  it.each([
    { statuses: ['complied'], items: [], known: false, error: '未履约依据' },
    { statuses: ['complied', 'complied'], items: [], known: false, error: '未履约依据' },
    { statuses: ['breached'], items: [], known: false, error: '已履约操作' },
    { statuses: ['breached', 'breached'], items: ['missed_sell'], known: true, error: '已履约操作' },
    { statuses: ['complied', 'breached'], items: [], known: false, error: null },
    { statuses: ['complied'], items: ['missed_buy'], known: false, error: null },
    { statuses: ['complied'], items: ['missed_sell'], known: false, error: null },
    { statuses: ['complied'], items: ['other'], known: false, error: null },
    { statuses: ['complied'], items: [], known: true, error: null },
    { statuses: [], items: ['other'], known: true, error: '已履约操作' },
  ])('$statuses / $items / 已知违规$known', ({ statuses, items, known, error }) => {
    const operations = statuses.map(status => ({ compliance_status: status })) as Pick<CheckinOperation, 'compliance_status'>[]
    const result = partialAssessmentIssue(operations, items as CheckinViolationItem[], known)
    if (error) expect(result).toContain(error)
    else expect(result).toBeNull()
  })
})
