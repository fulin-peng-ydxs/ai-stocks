import http, { type AppRequestConfig } from './client'
import { getAccessToken } from './authToken'
import type { RelatedBoardEmptyReason, RelatedBoardHistory } from '@/types/relatedBoards'

export const LIMIT_LADDER_WINDOWS = [10, 20, 31, 60] as const
export type LimitLadderWindow = typeof LIMIT_LADDER_WINDOWS[number]
export type LimitLadderBoard = 'main' | 'star' | 'gem'
export type LimitLadderHotspotType = 'industry' | 'concept'

export const LIMIT_LADDER_BOARD_OPTIONS: { value: LimitLadderBoard; label: string }[] = [
  { value: 'main', label: '主板' },
  { value: 'star', label: '科创板' },
  { value: 'gem', label: '创业板' },
]

export interface LimitLadderFilters {
  window: LimitLadderWindow
  boards: LimitLadderBoard[]
  ignoreSt: boolean
  oneWordOnly: boolean
  keyword: string
  hotspotType: LimitLadderHotspotType | null
  hotspotKey: string | null
}

export interface LimitLadderQueryParams {
  window: LimitLadderWindow
  boards?: string
  ignore_st: boolean
  one_word_only: boolean
  keyword?: string
  hotspot_type?: LimitLadderHotspotType
  hotspot_key?: string
}

export interface LimitLadderConcept {
  board_code: string
  board_name: string
}

export interface LimitLadderRelatedBoard extends LimitLadderConcept {
  as_of_date: string
  history?: RelatedBoardHistory
}

export interface LimitLadderStock {
  code: string
  name: string
  board: string
  price_limit_pct: number
  is_st: boolean
  st_as_of_date?: string | null
  st_quality: 'accurate' | 'approximate'
  st_source: string
  is_one_word: boolean
  consecutive_days: number
  amount: number
  industry_name: string
  industry_board_code: string | null
  source_version: string
  window_limit_up_days: number | null
  window_return_pct: number | null
  window_start_date: string | null
  actual_trade_days: number | null
  snapshot_concepts: LimitLadderConcept[]
  latest_related_industry: LimitLadderRelatedBoard | null
  latest_related_concept: LimitLadderRelatedBoard | null
  latest_related_industry_empty_reason?: RelatedBoardEmptyReason | null
  latest_related_concept_empty_reason?: RelatedBoardEmptyReason | null
}

export interface LimitLadderLayer {
  consecutive_days: number
  stock_count: number
  stocks: LimitLadderStock[]
}

export interface LimitLadderHotspot {
  group_key: string
  group_name: string
  stock_count: number
  historical_stock_count?: number
}

export interface LimitLadderResult {
  trade_date: string
  business_code: string
  snapshot_status: string
  stored_snapshot_status: string
  has_snapshot: boolean
  filters: Record<string, unknown>
  snapshot: ({
    snapshot_id: string
    trade_date: string
    computed_at: string
    stock_count: number
    has_approx_st: boolean
    coverage: Record<string, unknown>
  } & Record<string, unknown>) | null
  requested_window_start_date: string | null
  requested_window_trade_days: number
  dynamic_window_status: string
  related_board_status?: string
  related_concept_status?: string
  coverage?: Record<string, unknown>
  last_success_at?: string | null
  failure_summary?: string | null
  invalid_reason?: string | null
  task_error?: string | null
  st_status_error?: string | null
  task?: {
    command_id: string
    task_id?: string | null
    status: string
    source: string
    progress?: number | null
    message?: string | null
  } | null
  nearest_previous_trade_date?: string | null
  summary: {
    stock_count: number
    highest_board: number | null
    first_board_count: number
  }
  hotspots: Record<LimitLadderHotspotType, LimitLadderHotspot[]>
  layers: LimitLadderLayer[]
}

export interface LimitLadderTradeDates {
  dates: string[]
  latest_candidate_date: string | null
  latest_complete_date: string | null
  latest_candidate_coverage: Record<string, unknown> | null
  latest_candidate_ready: boolean
}

export interface LimitLadderRecomputeResult {
  command_id: string
  task_id: string | null
  status: string
  reused: boolean
}

export const DEFAULT_LIMIT_LADDER_FILTERS: LimitLadderFilters = {
  window: 31,
  boards: ['main', 'star', 'gem'],
  ignoreSt: true,
  oneWordOnly: false,
  keyword: '',
  hotspotType: null,
  hotspotKey: null,
}

const ALL_BOARDS = new Set<LimitLadderBoard>(DEFAULT_LIMIT_LADDER_FILTERS.boards)

export function normalizeLimitLadderFilters(
  input: Partial<LimitLadderFilters>,
): LimitLadderFilters {
  const window = LIMIT_LADDER_WINDOWS.includes(Number(input.window) as LimitLadderWindow)
    ? Number(input.window) as LimitLadderWindow
    : 31
  const boards = Array.from(new Set(
    (input.boards ?? DEFAULT_LIMIT_LADDER_FILTERS.boards)
      .filter((board): board is LimitLadderBoard => ALL_BOARDS.has(board as LimitLadderBoard)),
  ))
  const hotspotType = input.hotspotType === 'industry' || input.hotspotType === 'concept'
    ? input.hotspotType
    : null
  const hotspotKey = hotspotType && String(input.hotspotKey ?? '').trim()
    ? String(input.hotspotKey).trim()
    : null
  return {
    window,
    boards: boards.length ? boards : [...DEFAULT_LIMIT_LADDER_FILTERS.boards],
    ignoreSt: input.ignoreSt ?? true,
    oneWordOnly: input.oneWordOnly ?? false,
    keyword: String(input.keyword ?? '').trim(),
    hotspotType: hotspotKey ? hotspotType : null,
    hotspotKey,
  }
}

export function toLimitLadderQueryParams(filters: LimitLadderFilters): LimitLadderQueryParams {
  const normalized = normalizeLimitLadderFilters(filters)
  const boards = normalized.boards.length === ALL_BOARDS.size
    ? undefined
    : normalized.boards.join(',')
  return {
    window: normalized.window,
    boards,
    ignore_st: normalized.ignoreSt,
    one_word_only: normalized.oneWordOnly,
    keyword: normalized.keyword || undefined,
    hotspot_type: normalized.hotspotType ?? undefined,
    hotspot_key: normalized.hotspotKey ?? undefined,
  }
}

function firstQueryValue(value: unknown): string {
  return Array.isArray(value) ? String(value[0] ?? '') : String(value ?? '')
}

export function filtersFromRouteQuery(
  query: Record<string, unknown>,
  defaults: LimitLadderFilters = DEFAULT_LIMIT_LADDER_FILTERS,
): LimitLadderFilters {
  const boardsText = firstQueryValue(query.boards)
  const boards = boardsText
    ? boardsText.split(',').map((item) => item.trim()) as LimitLadderBoard[]
    : undefined
  return normalizeLimitLadderFilters({
    window: query.window === undefined
      ? defaults.window
      : Number(firstQueryValue(query.window)) as LimitLadderWindow,
    boards: query.boards === undefined ? defaults.boards : boards,
    ignoreSt: query.ignore_st === undefined
      ? defaults.ignoreSt
      : firstQueryValue(query.ignore_st) !== '0',
    oneWordOnly: firstQueryValue(query.one_word_only) === '1',
    keyword: firstQueryValue(query.keyword),
    hotspotType: firstQueryValue(query.hotspot_type) as LimitLadderHotspotType,
    hotspotKey: firstQueryValue(query.hotspot_key),
  })
}

export function filtersToRouteQuery(filters: LimitLadderFilters): Record<string, string> {
  const params = toLimitLadderQueryParams(filters)
  return {
    window: String(params.window),
    ...(params.boards ? { boards: params.boards } : {}),
    ...(params.ignore_st ? {} : { ignore_st: '0' }),
    ...(params.one_word_only ? { one_word_only: '1' } : {}),
    ...(params.keyword ? { keyword: params.keyword } : {}),
    ...(params.hotspot_type && params.hotspot_key
      ? { hotspot_type: params.hotspot_type, hotspot_key: params.hotspot_key }
      : {}),
  }
}

export function listLimitLadderTradeDates(): Promise<LimitLadderTradeDates> {
  return http.get('/limit-ladder/trade-dates')
}

export function getLimitLadder(
  tradeDate: string,
  filters: LimitLadderFilters,
): Promise<LimitLadderResult> {
  return http.get(`/limit-ladder/${encodeURIComponent(tradeDate)}`, {
    params: toLimitLadderQueryParams(filters),
  })
}

export function recomputeLimitLadder(tradeDate: string): Promise<LimitLadderRecomputeResult> {
  return http.post(
    `/limit-ladder/${encodeURIComponent(tradeDate)}/recompute`,
    undefined,
    { skipGlobalError: true } as AppRequestConfig,
  )
}

function exportFilename(disposition: string | null, tradeDate: string, window: number): string {
  const match = disposition?.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i)
  return match?.[1] ? decodeURIComponent(match[1]) : `limit-ladder-${tradeDate}-${window}d.csv`
}

export async function exportLimitLadder(
  tradeDate: string,
  filters: LimitLadderFilters,
): Promise<{ blob: Blob; filename: string }> {
  const params = new URLSearchParams()
  Object.entries(toLimitLadderQueryParams(filters)).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value))
  })
  const response = await fetch(
    `/api/limit-ladder/${encodeURIComponent(tradeDate)}/export?${params.toString()}`,
    { headers: { Authorization: `Bearer ${getAccessToken()}` } },
  )
  if (!response.ok) {
    let message = '导出失败，请稍后重试'
    try {
      const body = await response.json() as { msg?: string; detail?: string }
      message = body.msg || body.detail || message
    } catch {
      // 非 JSON 网关错误使用稳定中文兜底。
    }
    throw new Error(message)
  }
  return {
    blob: await response.blob(),
    filename: exportFilename(response.headers.get('content-disposition'), tradeDate, filters.window),
  }
}
