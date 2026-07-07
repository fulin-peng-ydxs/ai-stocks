// 买卖指标方案 API（对应 backend/api/trade_profiles.py）
import http from './client'

export interface TradeCond {
  indicator: string
  params?: Record<string, number>
  cmp: string // == != > >= < <= between
  value: number | boolean | [number, number]
}
export interface CondTree {
  op: 'AND' | 'OR'
  children: TradeCond[]
}
export interface Backstop {
  take_profit?: number | null
  stop_loss?: number | null
  max_hold_days?: number | null
}
export interface TradeProfile {
  id: string
  profile_ref?: string
  asset_ref?: string
  name: string
  version: number
  is_preset: boolean
  visibility?: 'private' | 'tenant' | 'public'
  source?: 'mine' | 'tenant' | 'public' | 'preset'
  readonly?: boolean
  owner_label?: string
  buy_tree: CondTree
  sell_tree: CondTree | Record<string, never>
  backstop: Backstop
}
export interface TradeProfileSummary {
  id: string
  profile_ref?: string
  asset_ref?: string
  name: string
  version: number
  is_preset: boolean
  visibility?: 'private' | 'tenant' | 'public'
  source?: 'mine' | 'tenant' | 'public' | 'preset'
  readonly?: boolean
  owner_label?: string
}

export function listTradeProfiles(): Promise<TradeProfileSummary[]> {
  return http.get('/trade-profiles')
}
export function getTradeProfile(pid: string): Promise<TradeProfile> {
  return http.get(`/trade-profiles/${pid}`)
}
export function saveTradeProfile(body: {
  id?: string | null
  name: string
  buy_tree: CondTree
  sell_tree?: CondTree | null
  backstop?: Backstop | null
}): Promise<{ id: string; version: number }> {
  return http.post('/trade-profiles', body)
}
export function deleteTradeProfile(pid: string): Promise<{ msg: string }> {
  return http.delete(`/trade-profiles/${pid}`)
}
export function setTradeProfileVisibility(
  pid: string,
  visibility: 'private' | 'tenant' | 'public',
): Promise<TradeProfile> {
  return http.post(`/trade-profiles/${pid}/visibility`, { visibility })
}
export function copyTradeProfile(pid: string, body: { id: string; name?: string }): Promise<{ id: string; version: number }> {
  return http.post(`/trade-profiles/${pid}/copy`, body)
}

// 方案历史版本（回看/载入）
export interface TradeProfileVersion {
  version: number
  name: string
  buy_tree: CondTree
  sell_tree: CondTree | Record<string, never>
  backstop: Backstop
  saved_at: string
}
export function getTradeProfileVersions(pid: string): Promise<{ id: string; profile_ref?: string; versions: TradeProfileVersion[] }> {
  return http.get(`/trade-profiles/${pid}/versions`)
}
export function previewConditions(body: {
  tree: CondTree
  run_date?: string
  top?: number
}): Promise<{ run_date: string; hit: number; list: { code: string; name: string | null }[] }> {
  return http.post('/trade-profiles/preview', body)
}
