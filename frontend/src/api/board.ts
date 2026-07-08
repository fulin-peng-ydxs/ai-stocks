// 榜单/评分 API（对应 backend/api/board.py）
import http from './client'
import type { ScoreProfileSummary, ScoreRunRow } from './scoreProfile'

export interface SubScores {
  position: number
  trend: number
  volume: number
  turnover: number
  rs: number
  fund_flow: number
}

export interface ScoreRow {
  trade_date: string
  code: string
  name: string | null
  total_score: number
  rank: number
  grade: string
  sub_scores: SubScores | null
  buy_point: string | null
  risk_flags: string[] | null
}

export interface ScoresTop {
  trade_date: string
  top: number
  list: ScoreRow[]
}

export interface ScoresPage {
  trade_date: string
  total: number
  page: number
  size: number
  list: ScoreRow[]
}

export function getScoresTop(params?: {
  date?: string
  model_id?: string
  top?: number
}): Promise<ScoresTop> {
  return http.get('/scores/top', { params })
}

export function getScores(params?: {
  date?: string
  model_id?: string
  page?: number
  size?: number
}): Promise<ScoresPage> {
  return http.get('/scores', { params })
}

// 按需计算某交易日的每日榜单 Top N（回测"查看买入当日榜单"用）
export interface BoardRow {
  rank: number
  code: string
  name: string | null
  total_score: number
  grade: string
}
export function computeBoard(
  date: string,
  top = 50,
  scoreProfileRefOrId?: string,
): Promise<{ date: string; top: number; list: BoardRow[] }> {
  // 评分方案引用：与回测所选评分方案一致才能让名次对上 entry_rank。
  return http.get('/board/compute', {
    params: { date, top, ...(scoreProfileRefOrId ? { score_profile_id: scoreProfileRefOrId } : {}) },
  })
}

// ── 可见方案榜单（board:view）──
// 方案来自“自己的 + 同租户公开 + 全体公开 + 平台系统内置方案”，榜单快照写入方案 owner 的共享缓存槽。
export function listBoardProfiles(): Promise<ScoreProfileSummary[]> {
  return http.get('/board/profiles')
}
export function runBoardProfile(body: {
  profile_ref?: string
  profile_id?: string
  run_date?: string
  top?: number
  force?: boolean
}): Promise<{
  run_date: string
  top: number
  count: number
  profile_ref?: string
  profile_version?: number
  cache_status?: 'cached' | 'materialized'
  list: ScoreRunRow[]
}> {
  return http.post('/board/run', body)
}

// 评分维度展示配置：key 对应 sub_scores 字段，max=该维度满分（=权重），color=分段条颜色
// 颜色取中等饱和度，浅色/暗色背景都不刺眼
export const SCORE_DIMS: { key: keyof SubScores; label: string; short: string; max: number; color: string }[] = [
  { key: 'position', label: '位置', short: '位', max: 30, color: '#5b8ff9' },
  { key: 'trend', label: '趋势', short: '趋', max: 20, color: '#61c08f' },
  { key: 'volume', label: '成交量', short: '量', max: 20, color: '#9270ca' },
  { key: 'turnover', label: '换手', short: '换', max: 10, color: '#e8a33d' },
  { key: 'rs', label: 'RS', short: 'RS', max: 10, color: '#d97c7c' },
]

// 分项分满分合计（=各维度权重和），分段条按此为满格
export const SCORE_DIMS_TOTAL = SCORE_DIMS.reduce((s, d) => s + d.max, 0)
