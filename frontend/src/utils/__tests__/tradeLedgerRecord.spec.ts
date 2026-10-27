import { describe, expect, it } from 'vitest'
import type { LedgerEvent, LedgerSnapshot } from '@/api/tradeLedger'
import { ledgerOperationsForRule, ledgerRuleRecords } from '../tradeLedgerRecord'

function snapshot(): LedgerSnapshot {
  return { trade_date: '2026-10-26', events: [], positions: [], opening_positions: [], omissions: [],
    rules: ['trend', 'dividend'].map(rule_id => ({ rule_id, name: rule_id, version_no: 1,
      capital: '100000', stock_rules: [], action_rules: [] })),
    evaluations: [], assessment: null, complete: false, peak_positions: 0,
    buy_amount: '0', sell_amount: '0', fee: '0', net_outflow: '0', cash: null,
    realized_pnl: null, review_note: null }
}
const trade: LedgerEvent = { event_id: 'one-real-trade', kind: 'trade', rule_id: 'trend',
  stock_code: '600000.SH', stock_name_snapshot: '浦发银行', side: 'buy', stock_rule_id: 's',
  action_rule_id: 'a', price: '10', quantity: '100', amount: '1000', fee: '5',
  operated_at: '2026-10-26T10:00:00', note: null, display_order: 1 }

describe('交易日记录的规则归集', () => {
  it('没有成交也完整保留两套规则，漏买漏卖只进入所属规则', () => {
    const value = snapshot()
    value.omissions = [{ kind: 'missed_buy', stock_code: '600356.SH', rule_id: 'dividend' }]
    const groups = ledgerRuleRecords(value)
    expect(groups.map(group => group.ruleId)).toEqual(['trend', 'dividend'])
    expect(groups[0]!.omissions).toEqual([])
    expect(groups[1]!.omissions).toEqual(value.omissions)
    expect(groups.every(group => group.trades.length === 0)).toBe(true)
  })
  it('区分尚未确认与确认后数据待核对，不在展示层制造履约结论', () => {
    const value = snapshot()
    value.confirmed_rule_ids = ['trend']
    value.evaluations = [{ rule_id: 'trend', rule_name: 'trend', confirmed: true,
      assessment: null, complete: false, issues: [], warnings: ['成本未完整录入'] }]
    const groups = ledgerRuleRecords(value)
    expect(groups.map(group => [group.confirmed, group.assessment])).toEqual([[true, null], [false, null]])
    expect(groups[0]!.warnings).toEqual(['成本未完整录入'])
  })
  it('同一成交在两套规则显示各自依据，不重复记账、不修改快照', () => {
    const value = snapshot()
    value.events = [{ ...trade, primary_issues: [], primary_warnings: [], issues: ['dividend：买卖规则不符'],
      rule_checks: [{ rule_id: 'dividend', stock_rule_id: 'ds', action_rule_id: 'da', action_matches: false,
        issues: ['买卖规则不符'], warnings: [] }] }]
    const original = structuredClone(value)
    const groups = ledgerRuleRecords(value)
    expect(groups[0]!.trades[0]!.issues).toEqual([])
    expect(groups[1]!.trades[0]).toMatchObject({ event_id: trade.event_id, linked: true,
      stock_rule_id: 'ds', issues: ['买卖规则不符'] })
    expect(value).toEqual(original)
    expect(value.events).toHaveLength(1)
  })
  it('计划外成交保留独立分组，资金变动不会变成规则成交', () => {
    const value = snapshot()
    value.events = [{ ...trade, rule_id: null }, { ...trade, event_id: 'cash', kind: 'cash' }]
    const groups = ledgerRuleRecords(value)
    expect(groups.at(-1)).toMatchObject({ ruleId: '', name: '未按任何已设规则操作' })
    expect(groups.at(-1)!.trades).toHaveLength(1)
    expect(ledgerOperationsForRule(value.events, 'trend')).toEqual([])
  })
})
