// 筛选方案 + 运行筛选 API（对应 backend/api/profiles.py）
import http from './client'

export interface Profile {
  id: string
  name: string
  expression: Record<string, unknown>
  params: Record<string, unknown> | null
  version: number
  is_preset: boolean
}

export interface ScreenHit {
  code: string
  name: string | null
  total_score: number | null
  grade: string
  is_st: boolean
}

export interface ScreenResult {
  run_date: string
  count: number
  exclude_st: boolean
  hits: ScreenHit[]
}

export function listProfiles(): Promise<Profile[]> {
  return http.get('/profiles')
}

// 列表只返回摘要；取完整方案（含 expression AST）用详情接口
export function getProfile(pid: string): Promise<Profile> {
  return http.get(`/profiles/${pid}`)
}

// 运行筛选：传 profile_id（已存方案）或 expression（临时 AST），可选 run_date
export function runScreen(body: {
  profile_id?: string
  expression?: Record<string, unknown>
  run_date?: string
  exclude_st?: boolean
}): Promise<ScreenResult> {
  return http.post('/screen/run', body)
}

// 保存/更新筛选方案（实质变更才 版本+1）
export function saveProfile(body: {
  id: string
  name: string
  expression: Record<string, unknown>
}): Promise<{ id: string; version: number }> {
  return http.post('/profiles', body)
}

// 方案历史版本（回看/恢复，T-M6-7）
export interface ProfileVersion {
  version: number
  name: string
  expression: Record<string, unknown>
  saved_at: string
}
export function getProfileVersions(pid: string): Promise<{ id: string; versions: ProfileVersion[] }> {
  return http.get(`/profiles/${pid}/versions`)
}
