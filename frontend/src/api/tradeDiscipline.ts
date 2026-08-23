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
  capital: string
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
  max_capital: string | null
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
  capital: string | null
  source_version_no: number | null
  stock_rules: DraftStockRule[]
  action_rules: DraftActionRule[]
}

export interface RuleVersionDetail {
  rule_id: string
  version_no: number
  name: string
  capital: string
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
  capital: string | null
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
  sort_by?: 'trade_date'
  sort_order?: 'asc' | 'desc'
}

export interface StockOption {
  code: string
  name: string
  board: string | null
  industry: string | null
}

export interface StockOptionPage {
  q: string
  limit: number
  list: StockOption[]
}

export interface ViolationReason {
  code: string | null
  id: string | null
  name: string
  builtin: boolean
}

export interface CheckinOperation {
  client_key?: string
  id?: string | null
  stock_code: string
  stock_name_snapshot: string
  side: ActionType
  stock_rule_id: string
  action_rule_id: string
  price: string | null
  quantity: string | null
  amount: string | null
  fee: string | null
  operated_at: string | null
  note: string | null
  display_order: number
  stock_rule_name?: string | null
  action_rule_name?: string | null
  action_subtype?: ActionSubtype | null
  financial_complete?: boolean
}

export interface TradeDisciplineCheckin {
  checkin_id: string
  revision_no: number
  current_revision_no: number
  rule_id: string
  rule_name: string
  version_no: number
  trade_date: string
  checkin_status: 'submitted' | 'amended'
  assessment: CheckinAssessment
  no_operation: boolean
  reason_code: string | null
  reason_id: string | null
  reason_name_snapshot: string | null
  violation_detail: string | null
  review_note: string | null
  operations: CheckinOperation[]
  financial_complete: boolean
  revision_kind?: 'initial' | 'amendment'
  submitted_at?: string
  amended_at?: string | null
  created_at?: string
  rule_version?: RuleVersionDetail
}

export interface CheckinContext {
  trade_date: string
  version: RuleVersionDetail
  checkin: TradeDisciplineCheckin | null
}

export interface CheckinContentPayload {
  assessment: CheckinAssessment
  no_operation: boolean
  reason_code: string | null
  reason_id: string | null
  reason_text: string | null
  violation_detail: string | null
  review_note: string | null
  operations: CheckinOperation[]
}

export interface SubmitCheckinPayload extends CheckinContentPayload {
  rule_id: string
  trade_date: string
}

export interface CheckinSummaryRule {
  rule_id: string
  rule_name: string
  version_no: number
  effective_from_trade_date: string
  checkin_id: string | null
  current_revision_no: number | null
  status: 'submitted' | 'amended' | null
  assessment: CheckinAssessment | null
  no_operation: boolean | null
}

export interface CheckinSummary {
  trade_date: string
  total: number
  completed: number
  pending: number
  rules: CheckinSummaryRule[]
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

export function getTradeDisciplineCheckinRevision(
  checkinId: string,
  revisionNo: number,
): Promise<TradeDisciplineCheckin> {
  return http.get(`/trade-discipline/checkins/${checkinId}/revisions/${revisionNo}`)
}

export function getTradeDisciplineCheckinContext(
  ruleId: string,
  tradeDate: string,
): Promise<CheckinContext> {
  return http.get('/trade-discipline/checkins/current', {
    params: { rule_id: ruleId, trade_date: tradeDate },
  })
}

export function getTradeDisciplineSummary(tradeDate: string): Promise<CheckinSummary> {
  return http.get('/trade-discipline/summary', { params: { trade_date: tradeDate } })
}

export function submitTradeDisciplineCheckin(
  payload: SubmitCheckinPayload,
): Promise<TradeDisciplineCheckin> {
  return http.post('/trade-discipline/checkins', payload)
}

export function quickNoOperationTradeDisciplineCheckin(
  ruleId: string,
  tradeDate: string,
): Promise<TradeDisciplineCheckin & { idempotent: boolean }> {
  return http.post('/trade-discipline/checkins/quick-no-operation', {
    rule_id: ruleId,
    trade_date: tradeDate,
  })
}

export function amendTradeDisciplineCheckin(
  checkinId: string,
  payload: CheckinContentPayload & { expected_revision: number },
): Promise<TradeDisciplineCheckin> {
  return http.post(`/trade-discipline/checkins/${checkinId}/amendments`, payload)
}

export function listTradeDisciplineReasons(): Promise<ViolationReason[]> {
  return http.get('/trade-discipline/reasons')
}

export function deleteTradeDisciplineReason(reasonId: string): Promise<{ reason_id: string }> {
  return http.delete(`/trade-discipline/reasons/${reasonId}`)
}

export function searchTradeDisciplineStocks(
  q: string,
  limit = 20,
  signal?: AbortSignal,
): Promise<StockOptionPage> {
  return http.get('/trade-discipline/stock-options', { params: { q, limit }, signal })
}
