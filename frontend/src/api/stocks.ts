// 个股查询 API（对应 backend/api/stocks.py）
import http from './client'
import type { AppRequestConfig } from './client'

export interface StockBasic {
  code: string
  name: string
  board: string
  industry: string | null
  list_date: string | null
  delist_date: string | null
  is_st: boolean
  close: number | null        // 指定交易日收盘价（元）
  pct_chg: number | null      // 指定交易日涨跌幅（%）
  groups: { id: string; name: string; color: string; is_default: boolean }[]
}

export interface StockListParams {
  q?: string
  board?: string
  exclude_st?: boolean
  trade_date?: string
  sort_by?: string
  sort_order?: string
  page?: number
  size?: number
}

export interface StockList {
  total: number
  page: number
  size: number
  trade_date: string
  list: StockBasic[]
}

export interface BoardMembershipItem {
  board_code: string
  name: string
  board_type: 'industry' | 'concept'
}

export interface StockBoardMembership {
  code: string
  membership_scope: 'cumulative'
  membership_updated_at: string | null
  industries: BoardMembershipItem[]
  concepts: BoardMembershipItem[]
}

export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  pre_close: number | null
  volume: number
  amount: number | null
  turnover_rate: number | null
  // 盘感训练 K 线由后端在 bars 内附带（12/26/9，严格后向），未暖机为 null
  macd_diff?: number | null
  macd_dea?: number | null
  macd_hist?: number | null
  macd_golden_cross?: boolean | null
  macd_dead_cross?: boolean | null
}

export interface Bars {
  code: string
  name: string | null
  adjust: string
  bars: Bar[]
}

export interface StockBenchmarkBars {
  index_code: string
  name: string
  end: string
  bars: Bar[]
}

export type NumericIndicatorField =
  | 'ma5' | 'ma10' | 'ma20' | 'ma60' | 'ma250'
  | 'macd_diff' | 'macd_dea' | 'macd_hist'
  | 'hhv60' | 'hhv120' | 'hhv240' | 'hhv480' | 'dist_to_high_2y'
  | 'vol_ma5' | 'vol_ma20' | 'rs_pct'

export type BooleanIndicatorField =
  | 'macd_golden_cross' | 'macd_dead_cross'
  | 'is_high_60' | 'is_high_120' | 'is_high_1y' | 'is_high_2y'
  | 'is_bull_arrange' | 'ma20_up' | 'ma60_up' | 'above_ma250'
  | 'is_vol_breakout' | 'is_platform_breakout' | 'is_turnover_healthy'

export type IndicatorField = NumericIndicatorField | BooleanIndicatorField

export type IndicatorRow = {
  trade_date: string
  code?: string
  param_hash?: string | null
} & Partial<Record<NumericIndicatorField, number | null>>
  & Partial<Record<BooleanIndicatorField, boolean | null>>

export interface Indicators {
  code: string
  indicators: IndicatorRow[]
}

export interface IndicatorParams {
  lookback?: number
  fields?: readonly IndicatorField[]
  end?: string
}

export function listStocks(params?: StockListParams): Promise<StockList> {
  return http.get('/stocks', { params })
}

export function getStockBoardMembership(code: string): Promise<StockBoardMembership> {
  return http.get(`/stocks/${encodeURIComponent(code)}/related-boards`)
}

export function getBars(
  code: string,
  params?: { adjust?: string; lookback?: number; end?: string },
  signal?: AbortSignal,
): Promise<Bars> {
  return http.get(`/stocks/${code}/bars`, { params, signal })
}

export function getStockBenchmarkBars(
  indexCode: string,
  params?: { lookback?: number; end?: string },
  signal?: AbortSignal,
): Promise<StockBenchmarkBars> {
  return http.get(`/stocks/benchmarks/${encodeURIComponent(indexCode)}/bars`, {
    params,
    signal,
    skipGlobalError: true,
  } as AppRequestConfig)
}

export function getIndicators(
  code: string,
  params?: IndicatorParams,
  signal?: AbortSignal,
): Promise<Indicators> {
  const query = params
    ? { ...params, fields: params.fields?.join(',') }
    : undefined
  return http.get(`/stocks/${code}/indicators`, {
    params: query,
    signal,
    skipGlobalError: true,
  } as AppRequestConfig)
}

export interface StockSignal {
  code: string
  date: string
  buy_point: string | null
  risk_flags: string[]
  buypoint_markers: { date: string; label: string }[]
}
export function getSignal(code: string, date?: string): Promise<StockSignal> {
  return http.get(`/stocks/${code}/signal`, { params: { date } })
}

// 个股 × 买卖指标方案：当日买/卖是否触发 + 各条件成立明细（v2.0 替代固定买点引擎）
export interface TradeCondStatus {
  label: string
  met: boolean
}
export interface TradeEval {
  code: string
  date: string
  profile_id: string
  name: string
  version: number | null
  buy_signal: boolean
  sell_signal: boolean
  buy: { op: string; conds: TradeCondStatus[] }
  sell: { op: string; conds: TradeCondStatus[] }
  backstop: { take_profit?: number | null; stop_loss?: number | null; max_hold_days?: number | null }
}
export function getTradeEval(code: string, profileId: string, date?: string, signal?: AbortSignal): Promise<TradeEval> {
  return http.get(`/stocks/${code}/trade-eval`, { params: { profile_id: profileId, date }, signal })
}
