// 板块行情 API（对应 backend/api/sectors.py，板块概念需求 R7-R10/R13/R14）
import http from './client'
import type { AppRequestConfig } from './client'
import type { IndicatorRow } from './stocks'

/** 列表可排序字段码（与 board_query.SORT_FIELDS 双向一致，前端中文标签仅 UI 映射）。 */
export type SectorSortField =
  | 'pct_today' | 'pct_5d' | 'pct_10d' | 'pct_20d'
  | 'net_inflow' | 'net_inflow_3d' | 'net_inflow_5d' | 'net_inflow_10d' | 'net_inflow_20d'
  | 'up_count'
export type SortOrder = 'asc' | 'desc'
export type BoardType = 'concept' | 'industry'
export type SectorMemberSortField = 'pct' | 'code'

/** 板块列表行（涨幅 pct_* 从 board_bar 计算；各周期净流入严格匹配同一行情截面日）。 */
export interface SectorRow {
  board_code: string
  app_code: string | null
  name: string
  board_type: BoardType
  /** 最近一次完整成分快照返回数；不是历史累计关系数。 */
  member_count: number | null
  has_members: boolean
  has_bar: boolean
  has_fund_flow: boolean
  pct_today: number | null
  pct_5d: number | null
  pct_10d: number | null
  pct_20d: number | null
  net_inflow: number | null
  net_inflow_3d: number | null
  net_inflow_5d: number | null
  net_inflow_10d: number | null
  net_inflow_20d: number | null
  /** 历史累计成员中，行情截面日涨幅最高者。 */
  leader_stock: string | null
  leader_pct: number | null
  /** 历史累计成员在行情截面日的上涨/下跌家数。 */
  up_count: number
  down_count: number
  /** 自选视图中表示板块事实是否仍可用；普通行情列表缺省即为可用。 */
  available?: boolean
  added_at?: string | null
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
  /** 与行情截面同日的资金流快照日；当日无匹配数据时为 null。 */
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
  /** includeIndicators=true 时返回；缺省请求保持仅行情的轻量契约。 */
  indicators?: IndicatorRow[]
}

export interface SectorBenchmarkBars {
  index_code: string
  name: string
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

export interface SectorWatchlistEntry {
  board_code: string
  name: string
  board_type: BoardType
  added_at: string | null
}

export interface SectorWatchlist {
  list: SectorWatchlistEntry[]
  total: number
}

export function listSectorWatchlist(): Promise<SectorWatchlist> {
  return http.get('/sectors/watchlist')
}

export function listWatchlistSectors(params?: SectorListParams): Promise<SectorList> {
  return http.get('/sectors/watchlist/markets', { params })
}

export function addSectorWatchlist(boardCode: string): Promise<{ board_code: string; added: boolean }> {
  return http.post('/sectors/watchlist', { board_code: boardCode })
}

export function removeSectorWatchlist(boardCode: string): Promise<{ board_code: string; removed: boolean }> {
  return http.delete(`/sectors/watchlist/${encodeURIComponent(boardCode)}`)
}

export function getSector(code: string, tradeDate?: string): Promise<SectorDetail> {
  return http.get(`/sectors/${encodeURIComponent(code)}`, {
    params: tradeDate ? { trade_date: tradeDate } : undefined,
  })
}

export function getSectorBars(
  code: string,
  start: string,
  end: string,
  includeIndicators = false,
): Promise<SectorBars> {
  return http.get(`/sectors/${encodeURIComponent(code)}/bars`, {
    params: { start, end, include_indicators: includeIndicators },
  })
}

export function getSectorBenchmarkBars(
  indexCode: string,
  start: string,
  end: string,
): Promise<SectorBenchmarkBars> {
  // 基准指数是可选对比数据（指数区间无行情/接口异常时回退默认基准线），不弹全局 toast。
  return http.get(`/sectors/benchmarks/${encodeURIComponent(indexCode)}/bars`, {
    params: { start, end },
    skipGlobalError: true,
  } as AppRequestConfig)
}

export function getSectorMembers(
  code: string,
  params?: {
    trade_date?: string
    page?: number
    size?: number
    sort_by?: SectorMemberSortField
    order?: SortOrder
  },
): Promise<SectorMembers> {
  return http.get(`/sectors/${encodeURIComponent(code)}/members`, { params })
}
