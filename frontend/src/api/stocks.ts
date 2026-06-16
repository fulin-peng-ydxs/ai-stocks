// 个股查询 API（对应 backend/api/stocks.py）
import http from './client'

export interface StockBasic {
  code: string
  name: string
  board: string
  industry: string | null
  list_date: string | null
  delist_date: string | null
  is_st: boolean
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
}

export interface Bars {
  code: string
  name: string | null
  adjust: string
  bars: Bar[]
}

export interface Indicators {
  code: string
  indicators: Record<string, unknown>[]
}

export function listStocks(params?: StockListParams): Promise<StockList> {
  return http.get('/stocks', { params })
}

export function getBars(
  code: string,
  params?: { adjust?: string; lookback?: number; end?: string },
  signal?: AbortSignal,
): Promise<Bars> {
  return http.get(`/stocks/${code}/bars`, { params, signal })
}

export function getIndicators(
  code: string,
  params?: { lookback?: number },
  signal?: AbortSignal,
): Promise<Indicators> {
  return http.get(`/stocks/${code}/indicators`, { params, signal })
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
