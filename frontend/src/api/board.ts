// 榜单/评分 API（对应 backend/api/board.py）
import http, { type AppRequestConfig } from './client'
import type { ScoreProfileBrowseResult, ScoreProfileSummary, ScoreRunRow } from './scoreProfile'

export interface SubScores {
  position: number
  trend: number
  volume: number
  turnover: number
  rs: number
  fund_flow: number
}

// 按需计算某交易日的每日榜单 Top N（回测"查看买入当日榜单"用）
export type BoardRow = ScoreRunRow
export function computeBoard(
  date: string,
  top = 50,
  scoreProfileRefOrId?: string,
  config?: AppRequestConfig,
): Promise<{ date: string; top: number; include_st: boolean; profile_version?: number; list: BoardRow[] }> {
  // 评分方案引用：与回测所选评分方案一致才能让名次对上 entry_rank。
  return http.get('/board/compute', {
    ...config,
    params: { date, top, ...(scoreProfileRefOrId ? { score_profile_id: scoreProfileRefOrId } : {}) },
  })
}

// ── 可见方案榜单（board:view）──
// source=mine：下拉只加载自己的评分方案（纯 owner，R3/C2）；
// source=preset|tenant|public：搜索弹窗浏览（分页 + q，R5/R14）；
// 不传维持 list_visible 兼容（自己 + 租户公开 + 全体公开 + 系统内置混合）。
export function listBoardProfiles(source?: 'mine'): Promise<ScoreProfileSummary[]> {
  return http.get('/board/profiles', { params: source ? { source } : undefined })
}

// 搜索弹窗三来源浏览（R5/R14）：preset 严格公开 / tenant / public，关键字 + 分页
export function browseBoardProfiles(params: {
  source: 'preset' | 'tenant' | 'public'
  q?: string
  page?: number
  pageSize?: number
}): Promise<ScoreProfileBrowseResult> {
  return http.get('/board/profiles', {
    params: {
      source: params.source,
      q: params.q || undefined,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 20,
    },
  })
}
export function runBoardProfile(body: {
  profile_ref?: string
  profile_id?: string
  run_date?: string
  page?: number
  page_size?: number
  listed_boards?: string[]
  keyword?: string
  related_board_keyword?: string
  export_all?: boolean
  force?: boolean
}, config?: AppRequestConfig): Promise<{
  run_date: string
  page: number
  page_size: number
  total: number
  count: number
  profile_ref?: string
  profile_version?: number
  profile_name?: string
  include_st?: boolean
  business_code?: 'READY' | 'ST_STATUS_NOT_READY'
  st_status_error?: string
  cache_status?: 'cached' | 'materialized'
  list: ScoreRunRow[]
}> {
  return http.post('/board/run', body, config)
}

// 评分维度元信息；热力颜色由 SubScoreBars 的共享语义色板计算。
export const SCORE_DIMS: { key: keyof SubScores; label: string; short: string; max: number }[] = [
  { key: 'position', label: '位置', short: '位', max: 30 },
  { key: 'trend', label: '趋势', short: '趋', max: 20 },
  { key: 'volume', label: '成交量', short: '量', max: 20 },
  { key: 'turnover', label: '换手', short: '换', max: 10 },
  { key: 'rs', label: 'RS', short: 'RS', max: 10 },
]

// 分项分满分合计（=各维度权重和），分段条按此为满格
export const SCORE_DIMS_TOTAL = SCORE_DIMS.reduce((s, d) => s + d.max, 0)
