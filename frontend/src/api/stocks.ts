// 个股查询 API（对应 backend/api/stocks.py）
import http from './client'
import type { AppRequestConfig } from './client'
import type { StockRelatedBoards } from '@/types/relatedBoards'

export interface StockBasic {
  code: string
  name: string
  board: string
  industry: string | null
  list_date: string | null
  delist_date: string | null
  is_st: boolean
  st_as_of_date?: string | null
  close: number | null        // 指定交易日收盘价（元）
  pct_chg: number | null      // 指定交易日涨跌幅（%）
  groups: { id: string; name: string; color: string; is_default: boolean }[]
  related_boards?: StockRelatedBoards | null
}

export interface StockListParams {
  q?: string
  boards?: string
  statuses?: string
  /** 兼容旧调用；新页面分别使用 boards 和 statuses。 */
  board?: string
  membership_board_code?: string
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
  pct_chg: number | null
}

export interface StockBoardMembership {
  code: string
  membership_scope: 'cumulative'
  membership_updated_at: string | null
  trade_date: string | null
  industries: BoardMembershipItem[]
  concepts: BoardMembershipItem[]
  related_boards: StockRelatedBoards | null
}

export interface StockMembershipOption {
  board_code: string
  name: string
  board_type: 'industry' | 'concept'
}

export interface StockMembershipOptions {
  list: StockMembershipOption[]
}

export interface CapitalEvidence {
  source: string | null
  effective_date: string | null
  available_date: string | null
  basis: string | null
  retrospective: boolean
  mv_source: string | null
}

export interface Bar {
  capital_evidence?: { total: CapitalEvidence; float: CapitalEvidence }
  date: string
  open: number
  high: number
  low: number
  close: number
  pre_close: number | null
  volume: number
  amount: number | null
  turnover_rate: number | null
  /** 详情按需加载的当日原始市值（元）；不随价格复权，历史缺口为 null。 */
  total_mv?: number | null
  float_mv?: number | null
  total_share?: number | null
  float_share?: number | null
  // 盘感训练 K 线由后端在 bars 内附带（12/26/9，严格后向），未暖机为 null
  macd_diff?: number | null
  macd_dea?: number | null
  macd_hist?: number | null
  macd_golden_cross?: boolean | null
  macd_dead_cross?: boolean | null
}

export type KlinePeriod = 'day' | 'week' | 'month' | 'year'

export interface Bars {
  code: string
  name: string | null
  adjust: string
  bars: Bar[]
}

export interface IntradayPoint {
  time: string
  open: number | null
  high: number
  low: number
  close: number
  volume: number // 手；1 手 = 100 股，两个分钟源在后端适配层统一
  amount: number
  average_price: number | null
}

export interface StockIntraday {
  archived?: boolean
  archive_start?: string | null
  archive_end?: string | null
  code: string
  name: string | null
  trade_date: string
  frequency: '1m'
  status: 'ready' | 'partial' | 'out_of_range' | 'no_data'
  source: 'sina' | 'eastmoney' | 'ths' | null
  fetched_at: string | null
  /** 兼容旧接口，源端采集窗口统一由数据管理解释，查询固定返回 null。 */
  supported_start: string | null
  supported_end: string | null
  pre_close: number | null
  turnover_rate: number | null
  points: IntradayPoint[]
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
  period?: KlinePeriod
  adjust?: 'qfq'
  indicators: IndicatorRow[]
}

export interface IndicatorParams {
  lookback?: number
  fields?: readonly IndicatorField[]
  end?: string
  period?: KlinePeriod
}

export function listStocks(params?: StockListParams): Promise<StockList> {
  return http.get('/stocks', { params })
}

export function getStockMembershipOptions(): Promise<StockMembershipOptions> {
  return http.get('/stocks/membership-options')
}

export function getStockBoardMembership(
  code: string,
  businessDate?: string,
  signal?: AbortSignal,
): Promise<StockBoardMembership> {
  return http.get(`/stocks/${encodeURIComponent(code)}/related-boards`, {
    params: { business_date: businessDate },
    signal,
    skipGlobalError: true,
  } as AppRequestConfig)
}

export interface StockQuoteSummary {
  code: string
  name: string | null
  board: string | null
  industry: string | null
  is_st: boolean | null
  trade_date: string | null
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  pre_close: number | null
  volume: number | null
  amount: number | null
  turnover_rate: number | null
  volume_ratio: number | null
  total_mv: number | null
  float_mv: number | null
  total_share: number | null
  float_share: number | null
  pe_ttm: number | null
  capital_evidence?: { total: CapitalEvidence; float: CapitalEvidence }
}

export function getStockQuoteSummary(
  code: string,
  signal?: AbortSignal,
): Promise<StockQuoteSummary> {
  return http.get(`/stocks/${encodeURIComponent(code)}/quote-summary`, {
    signal,
    skipGlobalError: true,
  } as AppRequestConfig)
}

export function getBars(
  code: string,
  params?: { adjust?: string; lookback?: number; end?: string; include_market_values?: boolean; capital_basis?: 'point_in_time' | 'historical' },
  signal?: AbortSignal,
  config?: AppRequestConfig,
): Promise<Bars> {
  return http.get(`/stocks/${code}/bars`, { ...config, params, signal })
}

export function getIntraday(
  code: string,
  tradeDate: string,
  signal?: AbortSignal,
): Promise<StockIntraday> {
  return http.get(`/stocks/${encodeURIComponent(code)}/intraday`, {
    params: { trade_date: tradeDate },
    signal,
    skipGlobalError: true,
  } as AppRequestConfig)
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
