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

export function listTradeDisciplineCheckins(
  params: CheckinHistoryQuery,
): Promise<CheckinHistoryPage> {
  return http.get('/trade-discipline/checkins', { params })
}

export function searchTradeDisciplineStocks(q: string, limit = 20): Promise<StockOption[]> {
  return http.get('/trade-discipline/stock-options', { params: { q, limit } })
}
