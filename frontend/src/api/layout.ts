// 可配置布局系统 API（对应 backend/api/layout.py）
import http, { type AppRequestConfig } from './client'

export const LAYOUT_CONFIG_SCHEMA_VERSION = 1

export type LayoutOverlayValue = string | number | boolean | string[] | number[] | Record<string, unknown>
export type LayoutOverlayValues = Record<string, LayoutOverlayValue>

export interface LayoutOverride {
  schemaVersion: number
  values: LayoutOverlayValues
}

export interface LayoutPresetRecord {
  key: string
  name: string
  description: string
  config: LayoutOverride
  enabled: boolean
  is_builtin: boolean
  schemaVersion: number
  referencedPages?: string[]
  referenceCount?: number
  created_at?: string | null
  updated_at?: string | null
}

export interface LayoutPageConfig {
  pageKey: string
  presetKey: string | null
  config: LayoutOverride
  updated_at?: string | null
}

export interface LayoutUserConfig {
  userId: string
  pageKey: string
  config: LayoutOverride
  updated_at?: string | null
}

export interface EffectiveLayoutConfig {
  pageKey: string
  userId: string
  presetKey: string | null
  schemaVersion: number
  values: LayoutOverlayValues
  source: Record<string, 'preset' | 'page' | 'user'>
  layers: { layer: 'preset' | 'page' | 'user'; config: LayoutOverride }[]
}

export interface SavePresetPayload {
  key: string
  name: string
  description?: string
  config?: Partial<LayoutOverride> | LayoutOverlayValues
  enabled?: boolean
  is_builtin?: boolean
  schemaVersion?: number
}

export interface SavePageConfigPayload {
  presetKey?: string | null
  config?: { schemaVersion?: number; values?: Record<string, unknown> } | Record<string, unknown>
  schemaVersion?: number
  /** 含组件配置时必传：用于后端校验字段归属（slot 存在 + 字段属于该组件种类）。 */
  layout?: Record<string, unknown>
}

export interface SaveUserConfigPayload {
  userId?: string
  config?: { schemaVersion?: number; values?: Record<string, unknown> } | Record<string, unknown>
  schemaVersion?: number
  layout?: Record<string, unknown>
}

export interface ValidateLayoutPayload {
  config?: { schemaVersion?: number; values?: Record<string, unknown> } | Record<string, unknown>
  layout?: Record<string, unknown>
  schemaVersion?: number
}

export interface LayoutValidateResult {
  valid: boolean
  errors: string[]
}

export function listLayoutPresets(includeDisabled = false): Promise<{ schemaVersion: number; presets: LayoutPresetRecord[] }> {
  return http.get('/layout/presets', { params: { include_disabled: includeDisabled } })
}

export function saveLayoutPreset(payload: SavePresetPayload): Promise<LayoutPresetRecord> {
  return http.post('/layout/presets', payload)
}

export function deleteLayoutPreset(key: string): Promise<{ key: string }> {
  return http.delete(`/layout/presets/${encodeURIComponent(key)}`)
}

export function getLayoutPageConfig(pageKey: string): Promise<LayoutPageConfig> {
  return http.get(`/layout/pages/${encodeURIComponent(pageKey)}`)
}

export function saveLayoutPageConfig(pageKey: string, payload: SavePageConfigPayload): Promise<LayoutPageConfig> {
  return http.post(`/layout/pages/${encodeURIComponent(pageKey)}`, payload)
}

export function getLayoutUserConfig(pageKey: string, userId = 'local'): Promise<LayoutUserConfig> {
  return http.get(
    `/layout/users/${encodeURIComponent(pageKey)}`,
    { params: { userId }, skipGlobalError: true } as AppRequestConfig,
  )
}

export function saveLayoutUserConfig(pageKey: string, payload: SaveUserConfigPayload): Promise<LayoutUserConfig> {
  return http.post(
    `/layout/users/${encodeURIComponent(pageKey)}`,
    payload,
    { skipGlobalError: true } as AppRequestConfig,
  )
}

export function validateLayoutConfig(payload: ValidateLayoutPayload): Promise<LayoutValidateResult> {
  return http.post('/layout/validate', payload)
}

export function resetLayoutConfig(payload: {
  scope: 'page' | 'user'
  pageKey: string
  userId?: string
  path?: string
}): Promise<LayoutPageConfig | LayoutUserConfig> {
  return http.post('/layout/reset', payload)
}

export function getEffectiveLayoutConfig(pageKey: string, userId = 'local'): Promise<EffectiveLayoutConfig> {
  return http.get(`/layout/effective/${encodeURIComponent(pageKey)}`, { params: { userId } })
}

/** 组件字段开放策略（P10）：元配置，描述某 (组件, 字段) 当前开放到哪几层（preset/page/user）。 */
export type ComponentConfigLayer = 'preset' | 'page' | 'user'

export interface FieldPolicyRecord {
  componentKind: string
  field: string
  /** 代码声明的最大开放集（收放上界，不可越过）。 */
  maxLayers: ComponentConfigLayer[]
  /** 当前生效开放集（管理员覆盖优先，否则等于 maxLayers）。 */
  allowedLayers: ComponentConfigLayer[]
  /** 是否被管理员覆盖（false 表示回落代码最大集）。 */
  overridden: boolean
}

export function listFieldPolicies(): Promise<{ schemaVersion: number; policies: FieldPolicyRecord[] }> {
  return http.get('/layout/field-policies')
}

/** 设置开放策略；allowedLayers 为空数组表示重置回代码最大集。只能在 maxLayers 内收放。 */
export function saveFieldPolicy(payload: {
  componentKind: string
  field: string
  allowedLayers: ComponentConfigLayer[]
}): Promise<FieldPolicyRecord> {
  return http.post('/layout/field-policies', payload)
}
