// 评分规则方案 + 技术指标注册表 API（对应 backend/api/score_profiles.py、indicators.py）
import http from './client'

// ── 技术指标注册表 ──
export interface IndicatorParam {
  name: string
  label: string
  type: string
  default: number
  min: number | null
  max: number | null
}
export interface IndicatorDef {
  key: string
  name_cn: string
  dtype: 'number' | 'bool'
  category: string
  categories: string[]
  direction: string | null
  params: IndicatorParam[]
  desc: string
  enabled: boolean
  kind: 'builtin' | 'expr'
  expression: string | null
  is_builtin: boolean
}
export function getIndicatorRegistry(includeDisabled = true): Promise<{ count: number; items: IndicatorDef[] }> {
  return http.get('/indicators/registry', { params: { include_disabled: includeDisabled } })
}
export function saveIndicatorDef(body: {
  key: string
  name_cn: string
  dtype: 'number' | 'bool'
  expression: string
  params?: IndicatorParam[]
  category?: string
  direction?: string | null
  desc?: string
  categories?: string[]
}): Promise<{ key: string }> {
  return http.post('/indicators/def', body)
}
export function setIndicatorEnabled(key: string, enabled: boolean): Promise<unknown> {
  return http.patch(`/indicators/def/${key}/enabled`, { enabled })
}
export function setIndicatorCategories(key: string, categories: string[]): Promise<unknown> {
  return http.patch(`/indicators/def/${key}/categories`, { categories })
}
export function deleteIndicatorDef(key: string): Promise<{ msg: string }> {
  return http.delete(`/indicators/def/${key}`)
}

// ── 评分方案 ──
export type ScoringRule =
  | { type: 'bool' }
  | { type: 'band'; bands: [number, number, number][] }
  | { type: 'linear'; min: number; max: number }

export interface ScoreItem {
  indicator: string
  params?: Record<string, number>
  weight: number
  scoring: ScoringRule
}

export interface ScoreProfile {
  id: string
  name: string
  version: number
  is_preset: boolean
  items: ScoreItem[]
  grade_thresholds: Record<string, number>
}

export interface ScoreProfileSummary {
  id: string
  name: string
  version: number
  is_preset: boolean
}

export interface ScoreRunRow {
  rank: number
  code: string
  name: string | null
  total_score: number
  grade: string
  sub_scores: Record<string, number>
}

export function listScoreProfiles(): Promise<ScoreProfileSummary[]> {
  return http.get('/score-profiles')
}
export function getScoreProfile(pid: string): Promise<ScoreProfile> {
  return http.get(`/score-profiles/${pid}`)
}
export function saveScoreProfile(body: {
  id: string
  name: string
  items: ScoreItem[]
  grade_thresholds?: Record<string, number>
}): Promise<{ id: string; version: number }> {
  return http.post('/score-profiles', body)
}
export function deleteScoreProfile(pid: string): Promise<{ msg: string }> {
  return http.delete(`/score-profiles/${pid}`)
}
export function runScoreProfile(body: {
  profile_id?: string
  items?: ScoreItem[]
  grade_thresholds?: Record<string, number>
  run_date?: string
  top?: number
}): Promise<{ run_date: string; top: number; count: number; list: ScoreRunRow[] }> {
  return http.post('/score-profiles/run', body)
}
