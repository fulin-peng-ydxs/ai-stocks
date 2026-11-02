// 回测 API（对应 backend/api/backtest.py）
import http from './client'
import type {
  AssetBrowseParams,
  AssetBrowseResult,
  BacktestRunSummary,
} from '@/components/asset-search/types'

export interface BacktestMetrics {
  total_return: number
  annual_return: number
  max_drawdown: number
  max_dd_days: number
  annual_vol: number
  sharpe: number
  calmar: number
  sortino: number
  win_rate: number
  /** null 专指有盈利且无亏损（无限盈亏比），不是字段缺失；无盈利且无亏损为 0。 */
  profit_factor: number | null
  avg_hold_days: number
  n_trades: number
  benchmark_return: number
  excess_return: number
}

export interface EquityPoint {
  trade_date: string
  equity: number
  cash: number
  position_value: number
  n_positions: number
  drawdown: number
  benchmark_equity: number | null
}

export interface TradeRow {
  seq: number
  code: string
  entry_is_st?: boolean | null
  st_as_of_date?: string | null
  entry_date: string
  entry_price: number
  exit_date: string
  exit_price: number
  exit_reason: string
  exit_detail?: string | null  // 卖树部分命中时的命中指标标签（JSON 字符串数组）
  entry_score?: number | null  // 买入当日综合分（解释"无评级"档）
  shares: number
  return_pct: number
  pnl: number
  hold_days: number
  grade: string
  entry_rank: number | null
  entry_pick_rank: number | null
  entry_pool: number | null
}

// 分层命中率单元：{hit_rate, n, base_rate, excess, reliable}
export interface LayerCell {
  hit_rate: number | null
  n: number
  base_rate?: number | null
  excess?: number | null
  reliable?: boolean
}
export interface Layers {
  date_start: string
  date_end: string
  horizons: number[]
  thresholds: number[]
  min_samples: number
  total_signals: number
  base_rate: Record<string, LayerCell>
  by_grade: Record<string, Record<string, number | LayerCell>>
  grades_order: string[]
}

export interface StrategyResult {
  run_id: string
  metrics: BacktestMetrics
  layers: Layers
  trades: TradeRow[]
  equity: EquityPoint[]
  benchmark_code: string
  initial_capital: number
}

export interface RunSummary {
  id: string
  run_ref?: string
  asset_ref?: string
  kind: string
  profile_id: string | null
  profile_name: string | null
  profile_version?: number | null
  trade_profile_id?: string | null
  trade_profile_name?: string | null
  trade_profile_version?: number | null
  score_profile_id?: string | null
  score_profile_name?: string | null
  score_profile_version?: number | null
  date_start: string
  date_end: string
  status: string
  visibility?: 'private' | 'tenant' | 'public'
  source?: 'mine' | 'tenant' | 'public'
  readonly?: boolean
  owner_label?: string
  published_at?: string | null
  published_by?: string | null
  created_at: string
  total_return: number | null
  params?: string
}

export interface RunParams {
  kind: 'strategy' | 'score_check'
  date_start: string
  date_end: string
  profile_id?: string | null
  score_profile_id?: string | null
  trade_profile_id?: string | null
  top_n?: number
  initial_capital?: number
  sell_ma_period?: number
  take_profit?: number
  stop_loss?: number
  max_hold_days?: number
  rebalance_days?: number
  industry_max_pct?: number | null
  benchmark?: string
  horizons?: number[]
  thresholds?: number[]
  source_run_ref?: string | null
}

// 稳健性测试（即跑即看）
export interface RobustMetricsRow {
  value?: number
  total_return: number | null
  annual_return: number | null
  max_drawdown: number | null
  sharpe: number | null
  win_rate: number | null
  n_trades: number | null
  benchmark_return: number | null
  excess_return: number | null
}
export interface ParamSweepResult {
  param: string
  values: number[]
  rows: RobustMetricsRow[]
}
export interface InOutSampleResult {
  split: string
  in_sample: RobustMetricsRow & { range: [string, string] }
  out_sample: RobustMetricsRow & { range: [string, string] }
}
export function runRobust(body: {
  mode: 'param_sweep' | 'in_out_sample'
  params: Record<string, unknown>
  param?: string
  values?: number[]
  split_date?: string
}): Promise<ParamSweepResult | InOutSampleResult> {
  // 稳健性会跑多次回测，耗时更长，单独放宽超时
  return http.post('/backtest/robust', body, { timeout: 600000 })
}

// 运行回测（同步长任务：全市场逐日打分+事件驱动，全年约 45s，远超默认 30s 超时）
export function runBacktest(body: RunParams): Promise<StrategyResult | Layers> {
  return http.post('/backtest/run', body, { timeout: 300000 })
}

// 运行前查重：同条件（含方案版本）是否已有历史记录
export interface PrepareResult {
  signature: string
  versions: Record<string, number | null>
  duplicate: { run_id: string; kind: string; date_start: string; date_end: string; created_at: string } | null
}
export function prepareBacktest(body: RunParams): Promise<PrepareResult> {
  return http.post('/backtest/prepare', body)
}

// 交易日历（已有行情的真实交易日），供日历组件只放行交易日
export function getTradeDates(): Promise<{
  dates: string[]
  min: string | null
  max: string | null
  count: number
}> {
  return http.get('/data/trade-dates')
}

// 页头精确选择器只承载最近记录，避免不同签名长期积累后一次性 JOIN、传输和渲染全量历史。
export function listRuns(kind?: string, source?: string, limit = 100): Promise<{ runs: RunSummary[] }> {
  return http.get('/backtest/runs', {
    params: {
      ...(kind ? { kind } : {}),
      ...(source && source !== 'all' ? { source } : {}),
      limit,
    },
  })
}

// 搜索抽屉「浏览公开回测」分页浏览（T5）：走后端 page/page_size 契约，返回真 total。
// 后端返回 { runs, total, page, page_size }（http 拦截器已解包到 data），此处适配为抽屉统一 Result 形态。
export async function browseRuns(
  params: AssetBrowseParams & { kind?: string },
): Promise<AssetBrowseResult<BacktestRunSummary>> {
  const res = (await http.get('/backtest/runs', {
    params: {
      source: params.source,
      q: params.q || undefined,
      page: params.page,
      page_size: params.pageSize,
      ...(params.kind ? { kind: params.kind } : {}),
    },
  })) as { runs?: BacktestRunSummary[]; total?: number; page?: number; page_size?: number }
  return {
    items: res.runs ?? [],
    total: res.total ?? 0,
    page: res.page ?? params.page,
    page_size: res.page_size ?? params.pageSize,
    source: params.source,
  }
}

export function deleteRun(runId: string): Promise<{ deleted: string }> {
  return http.delete(`/backtest/runs/${runId}`)
}

export function setRunVisibility(
  runId: string,
  visibility: 'private' | 'tenant' | 'public',
): Promise<RunSummary> {
  return http.post(`/backtest/runs/${runId}/visibility`, { visibility })
}

export function getRun(runId: string): Promise<{
  run: RunSummary
  metrics: BacktestMetrics
  layers: Layers | null
  equity: EquityPoint[]
  trades: TradeRow[]
}> {
  return http.get(`/backtest/runs/${runId}`)
}
