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
  profile_ref?: string
  id: string
  name: string
  version: number
  is_preset: boolean
  visibility?: 'private' | 'tenant' | 'public'
  source?: 'mine' | 'tenant' | 'public' | 'preset'
  readonly?: boolean
  owner_label?: string
  items: ScoreItem[]
  grade_thresholds: Record<string, number>
}

export interface ScoreProfileSummary {
  profile_ref?: string
  asset_ref?: string
  id: string
  name: string
  version: number
  is_preset: boolean
  visibility?: 'private' | 'tenant' | 'public'
  source?: 'mine' | 'tenant' | 'public' | 'preset'
  readonly?: boolean
  owner_label?: string
  updated_at?: string | null
}

// browse 分页结果（后端 repo.browse：items/total/page/page_size/source）
export interface ScoreProfileBrowseResult {
  items: ScoreProfileSummary[]
  total: number
  page: number
  page_size: number
  source: string
}

export interface ScoreRunRow {
  rank: number
  code: string
  name: string | null
  total_score: number
  grade: string
  sub_scores: Record<string, number>
}

// source=mine：下拉只加载自己的资产（纯 owner，R3/C2）；不传维持 list_visible 兼容
export function listScoreProfiles(source?: 'mine'): Promise<ScoreProfileSummary[]> {
  return http.get('/score-profiles', { params: source ? { source } : undefined })
}

// 搜索弹窗三来源浏览（R5/R14）：preset 严格公开 / tenant / public，关键字 + 分页
export function browseScoreProfiles(params: {
  source: 'preset' | 'tenant' | 'public'
  q?: string
  page?: number
  pageSize?: number
}): Promise<ScoreProfileBrowseResult> {
  return http.get('/score-profiles', {
    params: {
      source: params.source,
      q: params.q || undefined,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 20,
    },
  })
}
export function getScoreProfile(pid: string): Promise<ScoreProfile> {
  return http.get(`/score-profiles/${pid}`)
}
export function saveScoreProfile(body: {
  id?: string | null
  name: string
  items: ScoreItem[]
  grade_thresholds?: Record<string, number>
}): Promise<{ id: string; version: number }> {
  return http.post('/score-profiles', body)
}
export function deleteScoreProfile(pid: string): Promise<{ msg: string }> {
  return http.delete(`/score-profiles/${pid}`)
}
export function setScoreProfileVisibility(
  pid: string,
  visibility: 'private' | 'tenant' | 'public',
): Promise<ScoreProfile> {
  return http.post(`/score-profiles/${pid}/visibility`, { visibility })
}
// C8：前端不再传 id，后端生成唯一 id、名称默认「原名 副本」，返回新标识供刷新选中
export function copyScoreProfile(
  pid: string,
  body?: { name?: string },
): Promise<{ id: string; profile_ref?: string; name: string; version: number }> {
  return http.post(`/score-profiles/${pid}/copy`, body ?? {})
}

// 方案历史版本（回看/载入）
export interface ScoreProfileVersion {
  version: number
  name: string
  items: ScoreItem[]
  grade_thresholds: Record<string, number>
  saved_at: string
}
export function getScoreProfileVersions(pid: string): Promise<{ id: string; profile_ref?: string; versions: ScoreProfileVersion[] }> {
  return http.get(`/score-profiles/${pid}/versions`)
}
export function runScoreProfile(body: {
  profile_id?: string
  items?: ScoreItem[]
  grade_thresholds?: Record<string, number>
  run_date?: string
  top?: number
}): Promise<{ run_date: string; top: number; count: number; cache_status?: string; list: ScoreRunRow[] }> {
  return http.post('/score-profiles/run', body)
}
