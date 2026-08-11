// 板块行情 API（对应 backend/api/sectors.py，板块概念需求 R7-R10/R13/R14）
import http from './client'

/** 列表可排序字段码（与 board_query.SORT_FIELDS 双向一致，前端中文标签仅 UI 映射）。 */
export type SectorSortField = 'pct_today' | 'pct_5d' | 'pct_10d' | 'pct_20d' | 'net_inflow' | 'up_count'
export type SortOrder = 'asc' | 'desc'
export type BoardType = 'concept' | 'industry'

/** 板块列表行（涨幅 pct_* 从 board_bar 实时计算；领涨股/净流入取资金流最新即时行）。 */
export interface SectorRow {
  board_code: string
  app_code: string | null
  name: string
  board_type: BoardType
  member_count: number | null
  has_members: boolean
  has_bar: boolean
  has_fund_flow: boolean
  pct_today: number | null
  pct_5d: number | null
  pct_10d: number | null
  pct_20d: number | null
  net_inflow: number | null
  leader_stock: string | null
  leader_pct: number | null
  up_count: number
  down_count: number
}

export interface SectorListParams {
  trade_date?: string
  board_type?: BoardType
  sort_by?: SectorSortField
  order?: SortOrder
  keyword?: string
  page?: number
  size?: number
}

export interface SectorList {
  list: SectorRow[]
  total: number
  /** 涨幅截面交易日（board_bar）。 */
  trade_date: string | null
  /** 资金流快照日（board_fund_flow 最新 snapshot_date）。 */
  fund_flow_date: string | null
  page: number
  size: number
}

/** 板块详情摘要（含能力字段 + 指定交易日截面）。 */
export interface SectorDetail extends SectorRow {
  trade_date: string | null
  fund_flow_date: string | null
}

export interface SectorBar {
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
}

export interface SectorBars {
  board_code: string
  start: string
  end: string
  list: SectorBar[]
}

export interface SectorMember {
  code: string
  name: string | null
  close: number | null
  pct_chg: number | null
  turnover_rate: number | null
}

export interface SectorMembers {
  list: SectorMember[]
  total: number
  trade_date: string | null
}

export function listSectors(params?: SectorListParams): Promise<SectorList> {
  return http.get('/sectors', { params })
}

export function getSector(code: string, tradeDate?: string): Promise<SectorDetail> {
  return http.get(`/sectors/${encodeURIComponent(code)}`, {
    params: tradeDate ? { trade_date: tradeDate } : undefined,
  })
}

export function getSectorBars(code: string, start: string, end: string): Promise<SectorBars> {
  return http.get(`/sectors/${encodeURIComponent(code)}/bars`, { params: { start, end } })
}

export function getSectorMembers(
  code: string,
  params?: { trade_date?: string; page?: number; size?: number },
): Promise<SectorMembers> {
  return http.get(`/sectors/${encodeURIComponent(code)}/members`, { params })
}
