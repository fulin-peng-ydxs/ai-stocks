import http from './client'

export type RuleManagementStatus = 'unpublished' | 'active' | 'archived'
export type RuleEffectiveStatus = 'unpublished' | 'active' | 'archived'
export type CheckinAssessment = 'complied' | 'breached'

export interface RuleLifecycleEvent {
  event_type: 'publish' | 'archive' | 'restore'
  event_seq: number
  version_no: number
  occurred_at: string
  activated_at: string
  effective_from_trade_date: string
}

export interface RuleLifecycleCommandResult {
  rule_id: string
  event_type: 'archive' | 'restore'
  event_seq: number
  version_no: number
  effective_from_trade_date: string
}

export interface RuleVersionSummary {
  version_no: number
  name: string
  capital: string | number
}

export interface TradeDisciplineRule {
  id: string
  name: string | null
  status: RuleManagementStatus
  latest_version_no: number | null
  draft_revision?: number | null
  proposed_name?: string | null
  source_version_no?: number | null
  management_status: RuleManagementStatus
  latest_management_event: RuleLifecycleEvent | null
  has_pending_management_action: boolean
  effective_status: RuleEffectiveStatus
  effective_event_seq: number | null
  effective_from_trade_date: string | null
  effective_version: RuleVersionSummary | null
  created_at?: string
  updated_at?: string
}

export interface DraftStockRule {
  detail_id: string | null
  name: string | null
  max_capital: string | number | null
  content: string | null
  display_order: number
  enabled: boolean
}

export type ActionType = 'buy' | 'sell'
export type ActionSubtype = 'open_position' | 'add_position' | 'liquidate' | 'do_t'

export interface DraftActionRule {
  detail_id: string | null
  name: string | null
  action_type: ActionType | null
  action_subtype: ActionSubtype | null
  content: string | null
  display_order: number
  enabled: boolean
}

export interface RuleDraft {
  rule_id: string
  draft_revision: number
  name: string | null
  proposed_name?: string | null
  capital: string | number | null
  source_version_no: number | null
  stock_rules: DraftStockRule[]
  action_rules: DraftActionRule[]
}

export interface RuleVersionDetail {
  rule_id: string
  version_no: number
  name: string
  capital: string | number
  stock_rules: DraftStockRule[]
  action_rules: DraftActionRule[]
}

export interface TradeDisciplineRuleDetail extends TradeDisciplineRule {
  draft: RuleDraft | null
  latest_version: RuleVersionDetail | null
  effective_version: RuleVersionDetail | null
}

export interface RuleDraftPayload {
  name: string | null
  capital: string | number | null
  stock_rules: DraftStockRule[]
  action_rules: DraftActionRule[]
}

export interface CheckinHistoryRow {
  id: string
  rule_id: string
  rule_name: string
  trade_date: string
  status: 'submitted' | 'amended'
  current_revision_no: number
  version_no: number
  assessment: CheckinAssessment
  no_operation: boolean
  reason_name_snapshot: string | null
  operation_count: number
  submitted_at: string
  amended_at: string | null
  updated_at: string
}

export interface CheckinHistoryPage {
  total: number
  page: number
  page_size: number
  list: CheckinHistoryRow[]
}

export interface CheckinHistoryQuery {
  page?: number
  page_size?: number
  date_from?: string
  date_to?: string
  rule_id?: string
  assessment?: CheckinAssessment
  no_operation?: boolean
  amended?: boolean
  stock?: string
  reason?: string
}

export interface StockOption {
  code: string
  name: string
  board: string | null
  industry: string | null
}

export function listTradeDisciplineRules(
  tradeDate?: string | null,
): Promise<TradeDisciplineRule[]> {
  return http.get('/trade-discipline/rules', {
    params: tradeDate ? { trade_date: tradeDate } : undefined,
  })
}

export function getTradeDisciplineRule(
  ruleId: string,
  tradeDate?: string | null,
): Promise<TradeDisciplineRuleDetail> {
  return http.get(`/trade-discipline/rules/${ruleId}`, {
    params: tradeDate ? { trade_date: tradeDate } : undefined,
  })
}

export function createTradeDisciplineRule(
  payload?: Partial<RuleDraftPayload>,
): Promise<{ id: string }> {
  return http.post('/trade-discipline/rules', payload ?? {})
}

export function openTradeDisciplineRuleDraft(ruleId: string): Promise<RuleDraft> {
  return http.post(`/trade-discipline/rules/${ruleId}/draft/open`)
}

export function saveTradeDisciplineRuleDraft(
  ruleId: string,
  payload: RuleDraftPayload & { expected_revision: number },
): Promise<RuleDraft> {
  return http.put(`/trade-discipline/rules/${ruleId}/draft`, payload)
}

export function discardTradeDisciplineRuleDraft(
  ruleId: string,
): Promise<unknown> {
  return http.delete(`/trade-discipline/rules/${ruleId}/draft`)
}

export function publishTradeDisciplineRule(
  ruleId: string,
  expectedRevision: number,
): Promise<{ changed: boolean; rule_id: string; version_no: number; effective_from_trade_date?: string }> {
  return http.post(`/trade-discipline/rules/${ruleId}/publish`, {
    expected_revision: expectedRevision,
  })
}

export function archiveTradeDisciplineRule(ruleId: string): Promise<RuleLifecycleCommandResult> {
  return http.post(`/trade-discipline/rules/${ruleId}/archive`)
}

export function restoreTradeDisciplineRule(ruleId: string): Promise<RuleLifecycleCommandResult> {
  return http.post(`/trade-discipline/rules/${ruleId}/restore`)
}

export function copyTradeDisciplineRule(
  ruleId: string,
  source: 'published' | 'draft',
): Promise<{ id: string }> {
  return http.post(`/trade-discipline/rules/${ruleId}/copy`, { source })
}

export function deleteTradeDisciplineRule(ruleId: string): Promise<{ rule_id: string }> {
  return http.delete(`/trade-discipline/rules/${ruleId}`)
}

export function listTradeDisciplineCheckins(
  params: CheckinHistoryQuery,
): Promise<CheckinHistoryPage> {
  return http.get('/trade-discipline/checkins', { params })
}

export function searchTradeDisciplineStocks(q: string, limit = 20): Promise<StockOption[]> {
  return http.get('/trade-discipline/stock-options', { params: { q, limit } })
}
