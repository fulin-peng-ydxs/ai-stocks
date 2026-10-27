import http from './client'
import type { CheckinAssessment, CheckinOperation, RuleVersionDetail, StockOption } from './tradeDiscipline'

export interface LedgerPosition {
  market_value?: string | null
  quote_date?: string | null
  unrealized_pnl?: string | null
  stock_code: string
  stock_name: string
  quantity: string
  available_quantity: string
  cost: string | null
  rule_id: string | null
  stock_rule_id: string | null
}
export interface LedgerOpening {
  stock_code: string
  quantity: string | null
  cost?: string | null
  cost_price?: string | null
  rule_id?: string | null
  stock_rule_id?: string | null
}
export interface LedgerEvent extends CheckinOperation {
  cost_price?: string | null
  rule_checks?: LedgerRuleCheck[]
  event_id: string
  kind: 'trade' | 'position' | 'cash'
  rule_id: string | null
  direction?: 'in' | 'out'
  adjustment_type?: 'transfer' | 'bonus' | 'split' | 'correction' | 'deposit' | 'withdrawal' | 'dividend' | 'other'
  amount_mode?: 'auto' | 'manual'
  action_matches?: boolean
  issues?: string[]
  warnings?: string[]
  primary_issues?: string[]
  primary_warnings?: string[]
}
export interface LedgerRuleCheck {
  issues?: string[]
  warnings?: string[]
  rule_id: string
  stock_rule_id: string
  action_rule_id: string
  action_matches: boolean
  stock_matches?: boolean
  checklist_results?: CheckinOperation['checklist_results']
  loss_status?: CheckinOperation['loss_status']
  st_risk_status?: CheckinOperation['st_risk_status']
  selection_facts?: CheckinOperation['selection_facts']
}
export interface LedgerOmission {
  kind: 'missed_buy' | 'missed_sell'
  stock_code: string
  rule_id: string
  stock_name?: string
}
export interface LedgerSnapshot {
  confirmed_rule_ids?: string[]
  operation_count?: number
  trade_date: string
  revision_no?: number
  events: LedgerEvent[]
  positions: LedgerPosition[]
  opening_positions: LedgerPosition[]
  omissions: LedgerOmission[]
  rules: RuleVersionDetail[]
  assessment: CheckinAssessment | null
  complete: boolean
  peak_positions: number
  buy_amount: string
  sell_amount: string
  fee: string
  net_outflow: string
  cash: string | null
  realized_pnl: string | null
  review_note: string | null
  evaluations: { rule_id: string; rule_name: string; assessment: CheckinAssessment | null;
    complete: boolean; confirmed?: boolean; issues: string[]; warnings: string[] }[]
}
export interface LedgerContext {
  stock_options?: StockOption[]
  trade_date: string
  account_revision: number
  initialized_on: string | null
  can_edit: boolean
  latest_trade_date: string | null
  current_revision_no: number
  snapshot: LedgerSnapshot | null
  rules: RuleVersionDetail[]
  opening_positions: LedgerPosition[]
  opening_cash: string | null
  positions: LedgerPosition[]
  cash: string | null
}
export interface LedgerPayload {
  trade_date: string
  request_id: string
  expected_account_revision: number
  expected_revision: number
  events: ReturnType<typeof ledgerEventPayload>[]
  omissions: { kind: 'missed_buy' | 'missed_sell'; stock_code: string; rule_id: string }[]
  review_note: string | null
}

/** 只发送可填写事实，不能把服务端计算结果、名称和条件快照作为权威输入。 */
export function ledgerEventPayload(event: LedgerEvent) {
  return {
    event_id: event.event_id, kind: event.kind, rule_id: event.rule_id,
    stock_code: event.stock_code || null, side: event.side || null,
    direction: event.direction ?? null, adjustment_type: event.adjustment_type ?? null,
    stock_rule_id: event.rule_id ? event.stock_rule_id || null : null,
    action_rule_id: event.rule_id ? event.action_rule_id || null : null,
    price: event.price, cost_price: event.cost_price ?? null, quantity: event.quantity,
    // 修正数量时不能把旧快照的派生总成本作为新事实回传。
    amount: event.kind === 'position' && event.cost_price != null ? null : event.amount,
    amount_mode: event.amount_mode ?? 'auto', fee: event.fee,
    operated_at: event.operated_at, display_order: event.display_order, note: event.note,
    action_matches: event.action_matches ?? true,
    stock_matches: event.stock_matches ?? true,
    checklist_results: event.checklist_results ?? [],
    loss_status: event.loss_status ?? null, st_risk_status: event.st_risk_status ?? null,
    rule_checks: (event.rule_checks ?? []).map(check => ({
      rule_id: check.rule_id, stock_rule_id: check.stock_rule_id, action_rule_id: check.action_rule_id,
      action_matches: check.action_matches ?? true, checklist_results: check.checklist_results ?? [],
      stock_matches: check.stock_matches ?? true,
      loss_status: check.loss_status ?? null, st_risk_status: check.st_risk_status ?? null,
    })),
  }
}
export function getLedgerContext(tradeDate: string): Promise<LedgerContext> {
  return http.get('/trade-discipline/ledger', { params: { trade_date: tradeDate } })
}
export function initializeLedger(payload: {
  trade_date: string; expected_revision: number; positions: LedgerOpening[]; cash: string | null
}): Promise<LedgerContext> {
  return http.post('/trade-discipline/ledger/initialize', payload)
}
export function submitLedger(payload: LedgerPayload): Promise<LedgerSnapshot> {
  return http.post('/trade-discipline/ledger/days', payload)
}
export function previewLedger(payload: LedgerPayload): Promise<LedgerSnapshot> {
  return http.post('/trade-discipline/ledger/preview', payload)
}
export function withdrawLedger(tradeDate: string, accountRevision: number): Promise<LedgerContext> {
  return http.post('/trade-discipline/ledger/withdraw', {
    trade_date: tradeDate, expected_account_revision: accountRevision,
  })
}
export interface LedgerHistoryRow {
  stock_options?: StockOption[]
  trade_date: string
  current_revision_no: number
  withdrawn?: boolean
  snapshot: LedgerSnapshot
}
export function getLedgerHistory(page = 1, pageSize = 20, filters: {
  assessment?: string; stock_code?: string; rule_id?: string; date_from?: string; date_to?: string; sort_order?: 'asc' | 'desc'; include_withdrawn?: boolean
} = {}): Promise<{ total: number; list: LedgerHistoryRow[] }> {
  return http.get('/trade-discipline/ledger/history', { params: { page, page_size: pageSize, ...filters } })
}
export function getLedgerRevision(tradeDate: string, revision: number): Promise<LedgerHistoryRow & { revision_no: number }> {
  return http.get(`/trade-discipline/ledger/revisions/${tradeDate}/${revision}`)
}
