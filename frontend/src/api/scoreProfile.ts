// 评分规则方案 + 技术指标注册表 API（对应 backend/api/score_profiles.py、indicators.py）
import http from './client'
import type { StockRelatedBoards } from '@/types/relatedBoards'

// ── 技术指标注册表 ──
export interface IndicatorParam {
  name: string
  label: string
  type: string
  default: number
  min: number | null
  max: number | null
  unit?: string
  description?: string
}
export type IndicatorLayer = 'field' | 'metric' | 'signal' | 'preset'
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
  layer?: IndicatorLayer
  parent_key?: string | null
  preset_params?: Record<string, number | string>
}
export interface IndicatorTemplate {
  key: string
  name: string
  dtype: 'number' | 'bool'
  expression: string
  params: IndicatorParam[]
}
export function getIndicatorRegistry(includeDisabled = true): Promise<{ count: number; items: IndicatorDef[]; templates: IndicatorTemplate[] }> {
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
export function updateIndicatorDef(key: string, body: Parameters<typeof saveIndicatorDef>[0]): Promise<{ key: string }> {
  return http.patch(`/indicators/def/${key}`, body)
}
export interface IndicatorReferenceSummary {
  key: string
  count: number
  backtest_count: number
  items: { kind: 'screen' | 'score' | 'trade'; id: string; name: string; version: number; historical: boolean }[]
}
export function getIndicatorReferences(key: string): Promise<IndicatorReferenceSummary> {
  return http.get(`/indicators/def/${key}/references`)
}
export interface IndicatorPreviewResult {
  status: 'ok' | 'history_insufficient' | 'missing_field' | 'empty_result' | 'expression_error'
  reason: string
  code: string
  trade_date: string
  rendered_expression: string
  effective_params: Record<string, number>
  value: number | boolean | null
}
export function previewIndicatorDef(body: {
  dtype: 'number' | 'bool'; expression: string; params: IndicatorParam[]
  values: Record<string, number>; code: string; trade_date?: string
}): Promise<IndicatorPreviewResult> {
  return http.post('/indicators/def/preview', body)
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
  affected_run_count?: number
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
  affected_run_count?: number
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
  board: string | null
  total_score: number
  grade: string
  sub_scores: Record<string, number>
  groups?: { id: string; name: string; color: string; is_default: boolean }[]
  related_boards?: StockRelatedBoards | null
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
  body?: { name?: string; version?: number },
): Promise<{ id: string; profile_ref?: string; name: string; version: number; source_version?: number }> {
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
