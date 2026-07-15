import http, { type AppRequestConfig } from './client'

export interface UserPreferenceRecord<T = unknown> {
  scope: string
  pageKey: string
  prefKey: string
  value: T
  schemaVersion: number
  updated_at?: string | null
}

export interface SaveUserPreferencePayload<T = unknown> {
  scope: string
  pageKey?: string
  prefKey: string
  value: T
  schemaVersion?: number
}

export function listUserPreferences(params: {
  scope?: string
  pageKey?: string
  prefKey?: string
} = {}): Promise<{ items: UserPreferenceRecord[] }> {
  return http.get('/user-preferences', { params, skipGlobalError: true } as AppRequestConfig)
}

export function saveUserPreference<T = unknown>(
  payload: SaveUserPreferencePayload<T>,
): Promise<UserPreferenceRecord<T>> {
  return http.post('/user-preferences', payload, { skipGlobalError: true } as AppRequestConfig)
}

export function saveUserPreferencesBulk(
  items: SaveUserPreferencePayload[],
  options: { migrationSource?: string } = {},
): Promise<{ items: UserPreferenceRecord[] }> {
  return http.post(
    '/user-preferences/bulk',
    { items, migrationSource: options.migrationSource },
    { skipGlobalError: true } as AppRequestConfig,
  )
}
