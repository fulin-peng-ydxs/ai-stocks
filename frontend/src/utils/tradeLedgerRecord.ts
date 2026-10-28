import type { LedgerEvent, LedgerOmission, LedgerSnapshot } from '@/api/tradeLedger'
import type { CheckinAssessment } from '@/api/tradeDiscipline'

/** 主记账与附加核对各用自己的依据，不能把另一套规则的偏差归到当前规则。 */
export function ledgerOperationsForRule(events: LedgerEvent[], ruleId: string): LedgerEvent[] {
  return events.filter(event => event.kind === 'trade').flatMap(event => {
    if ((event.rule_id || '') === ruleId) return [{ ...event,
      issues: event.primary_issues ?? event.issues, warnings: event.primary_warnings ?? event.warnings,
      ...(!ruleId ? { stock_rule_id: 'unplanned', action_rule_id: event.side } : {}),
    }]
    const check = event.rule_checks?.find(item => item.rule_id === ruleId)
    return check ? [{ ...event, ...check, linked: true, client_key: `${event.event_id}:${ruleId}`,
      issues: check.issues ?? [], warnings: check.warnings ?? [],
    }] : []
  })
}

export interface LedgerRuleRecord {
  ruleId: string
  name: string
  restrictFinancialReportMonths?: boolean
  versionNo?: number
  confirmed: boolean
  assessment: CheckinAssessment | null
  issues: string[]
  warnings: string[]
  trades: LedgerEvent[]
  omissions: LedgerOmission[]
}

/** 按提交时的完整规则快照分组，只有遗漏、无操作及尚未确认的规则也必须可见。 */
export function ledgerRuleRecords(snapshot: LedgerSnapshot): LedgerRuleRecord[] {
  const evaluations = new Map(snapshot.evaluations.map(item => [item.rule_id, item]))
  const groups: LedgerRuleRecord[] = snapshot.rules.map(rule => {
    const result = evaluations.get(rule.rule_id)
    return { ruleId: rule.rule_id, name: rule.name, versionNo: rule.version_no,
      restrictFinancialReportMonths: rule.restrict_financial_report_months ?? false,
      confirmed: result?.confirmed ?? (snapshot.confirmed_rule_ids?.includes(rule.rule_id) ?? true),
      assessment: result?.assessment ?? null, issues: result?.issues ?? [], warnings: result?.warnings ?? [],
      trades: ledgerOperationsForRule(snapshot.events, rule.rule_id),
      omissions: snapshot.omissions.filter(item => item.rule_id === rule.rule_id),
    }
  })
  const unplanned = ledgerOperationsForRule(snapshot.events, '')
  if (unplanned.length) groups.push({ ruleId: '', name: '未按任何已设规则操作',
    confirmed: true, assessment: null, issues: [], warnings: [], trades: unplanned, omissions: [] })
  return groups
}
