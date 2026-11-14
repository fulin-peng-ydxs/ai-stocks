// 买卖指标方案 API（对应 backend/api/trade_profiles.py）
import http, { type AppRequestConfig } from './client'

export interface TradeCond {
  indicator: string
  enabled?: boolean
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
  affected_run_count?: number
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
  updated_at?: string | null
  affected_run_count?: number
}

// browse 分页结果（后端 repo.browse：items/total/page/page_size/source）
export interface TradeProfileBrowseResult {
  items: TradeProfileSummary[]
  total: number
  page: number
  page_size: number
  source: string
}

// source=mine：下拉只加载自己的资产（纯 owner，R3/C2）；不传维持 list_visible 兼容
export function listTradeProfiles(source?: 'mine'): Promise<TradeProfileSummary[]> {
  return http.get('/trade-profiles', { params: source ? { source } : undefined })
}

// 搜索弹窗三来源浏览（R5/R14）：preset 严格公开 / tenant / public，关键字 + 分页
export function browseTradeProfiles(params: {
  source: 'preset' | 'tenant' | 'public'
  q?: string
  page?: number
  pageSize?: number
}): Promise<TradeProfileBrowseResult> {
  return http.get('/trade-profiles', {
    params: {
      source: params.source,
      q: params.q || undefined,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 20,
    },
  })
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
// C8：前端不再传 id，后端生成唯一 id、名称默认「原名 副本」，返回新标识供刷新选中
export function copyTradeProfile(
  pid: string,
  body?: { name?: string; version?: number },
): Promise<{ id: string; profile_ref?: string; name: string; version: number; source_version?: number }> {
  return http.post(`/trade-profiles/${pid}/copy`, body ?? {})
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
}, config?: AppRequestConfig): Promise<{ run_date: string; hit: number; list: { code: string; name: string | null }[] }> {
  return http.post('/trade-profiles/preview', body, config)
}
