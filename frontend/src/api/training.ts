// 盘感训练 API（agent-works/market-sense-training/）
import http, { type AppRequestConfig } from './client'
import type { Bar } from './stocks'

export interface TrainTradeMarker {
  date: string
  rel_day: number
  kind: 'buy' | 'sell'
  label: string
}

export interface TrainTrade {
  seq: number
  side: 'buy' | 'sell'
  rel_day: number
  price: number
  hands: number
  shares: number
  fee: number
  pnl: number | null
  return_pct: number | null
  reason: string
  auto_close: boolean
  decide_date?: string | null
  fill_date?: string | null
}

// 进行中的当前回合（盲测脱敏：无真实 code/name/日期）
export interface RunningRound {
  seq: number
  cursor_idx: number
  window_days: number
  status: string
  is_last_day: boolean
  cash: number
  pos_shares: number
  pos_hands: number
  pos_avg_price: number
  cur_close: number
  pos_value: number
  equity: number
  unrealized_pnl: number
  realized_pnl: number
  pending: { side: 'buy' | 'sell'; hands: number; reason: string } | null
  bars: Bar[]
  markers: TrainTradeMarker[]
  trades: TrainTrade[]
  lot_size: number
  // 板块（主板/创业板/科创板）为宽泛分类，与选股过滤同口径，盲测阶段同样返回。
  board: string | null
}

export interface RunningView {
  id: string
  status: 'running' | 'completed' | 'aborted'
  mode: 'single' | 'multi'
  n_rounds: number
  window_days: number
  initial_capital: number
  fee_enabled: boolean
  cur_round: number
  round: RunningRound
  fill_msg?: string | null
}

// 结算后回合（揭晓真实身份）
export interface DetailRound {
  seq: number
  status: string
  code: string | null
  name: string | null
  board: string | null
  start_date: string | null
  end_date: string | null
  window_days: number
  cursor_idx: number
  round_return: number | null
  benchmark_return: number | null
  final_equity: number | null
  max_drawdown: number
  bars: Bar[]
  markers: TrainTradeMarker[]
  trades: TrainTrade[]
  equity_curve: number[]
}

export interface DetailView {
  id: string
  status: 'running' | 'completed' | 'aborted'
  mode: 'single' | 'multi'
  n_rounds: number
  window_days: number
  initial_capital: number
  fee_enabled: boolean
  total_return: number | null
  score: number | null
  grade: string | null
  win_rate: number | null
  max_drawdown: number | null
  n_trades: number | null
  review_note: string
  created_at: string
  completed_at: string | null
  lot_size: number
  rounds: DetailRound[]
}

export interface StartParams {
  mode: 'single' | 'multi'
  range_start?: string | null
  range_end?: string | null
  n_rounds?: number
  window_days?: number
  initial_capital?: number
  fee_enabled?: boolean
  filters?: Record<string, unknown> | null
}

export interface SessionRow {
  id: string
  mode: 'single' | 'multi'
  n_rounds: number
  window_days: number
  status: string
  total_return: number | null
  score: number | null
  grade: string | null
  win_rate: number | null
  max_drawdown: number | null
  n_trades: number | null
  created_at: string
  completed_at: string | null
}

export interface SessionPage {
  total: number
  page: number
  size: number
  list: SessionRow[]
}

export interface GrowthPoint {
  id: string
  score: number | null
  total_return: number | null
  win_rate: number | null
  grade: string | null
  completed_at: string | null
}

export function startSession(body: StartParams, config?: AppRequestConfig): Promise<RunningView> {
  return http.post('/training/sessions', body, config)
}

export function getSession(sid: string): Promise<RunningView & DetailView> {
  return http.get(`/training/sessions/${sid}`)
}

export function listSessions(params?: {
  page?: number; size?: number; status?: string; sort_by?: string; sort_order?: string
}): Promise<SessionPage> {
  return http.get('/training/sessions', { params })
}

export function growth(): Promise<GrowthPoint[]> {
  return http.get('/training/growth')
}

export function revealNext(sid: string, cursor_idx: number | null, config?: AppRequestConfig): Promise<RunningView> {
  return http.post(`/training/sessions/${sid}/reveal`, { cursor_idx }, config)
}

export function placeTrade(
  sid: string, side: 'buy' | 'sell', hands: number, reason = '', config?: AppRequestConfig,
): Promise<RunningView> {
  return http.post(`/training/sessions/${sid}/trade`, { side, hands, reason }, config)
}

export function cancelIntent(sid: string, config?: AppRequestConfig): Promise<RunningView> {
  return http.post(`/training/sessions/${sid}/cancel`, {}, config)
}

export function settleRound(sid: string, config?: AppRequestConfig): Promise<RunningView & DetailView> {
  return http.post(`/training/sessions/${sid}/settle-round`, {}, config)
}

export function saveReview(sid: string, note: string): Promise<unknown> {
  return http.patch(`/training/sessions/${sid}/review`, { note })
}

export function deleteSession(sid: string): Promise<unknown> {
  return http.delete(`/training/sessions/${sid}`)
}
