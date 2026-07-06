// 审计日志 API（stage5·T7）：对应 backend/api/audit.py，只做类型封装和参数透传。
import http from './client'

export interface AuditLog {
  id: string
  event_category: string
  event_type: string
  action: string
  result: string
  status: string
  tenant_id?: string | null
  actor_user_id?: string | null
  actor_account?: string | null
  resource_code?: string | null
  resource_name?: string | null
  target_type?: string | null
  target_id?: string | null
  target_label?: string | null
  target_description?: string | null
  ip?: string | null
  method?: string | null
  path?: string | null
  duration_ms?: number | null
  error_summary?: string | null
  context?: Record<string, unknown> | null
  event_time: string
  created_at: string
}

export interface AuditQuery {
  page?: number
  page_size?: number
  start_time?: string | null
  end_time?: string | null
  event_category?: string | string[] | null
  event_type?: string | string[] | null
  result?: string | string[] | null
  status?: string | string[] | null
  resource_code?: string | null
  actor_keyword?: string | null
  target_keyword?: string | null
  tenant_id?: string | string[] | null
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export interface AuditListResult {
  list: AuditLog[]
  total: number
  page: number
  page_size: number
  size?: number
}

export interface AuditSummary {
  total: number
  success: number
  failed: number
  by_category: Record<string, number>
  by_type: Record<string, number>
  by_result: Record<string, number>
  by_status: Record<string, number>
}

function toAuditParams(query: AuditQuery): URLSearchParams {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, raw]) => {
    if (raw == null || raw === '') return
    if (Array.isArray(raw)) {
      raw.forEach((item) => {
        const value = String(item).trim()
        if (value) params.append(key, value)
      })
      return
    }
    params.append(key, String(raw))
  })
  return params
}

export function listAuditLogs(query: AuditQuery = {}): Promise<AuditListResult> {
  return http.get('/audit', { params: toAuditParams(query) })
}

export function getAuditSummary(query: Omit<AuditQuery, 'page' | 'page_size'> = {}): Promise<AuditSummary> {
  return http.get('/audit/summary', { params: toAuditParams(query) })
}

export function getAuditDetail(id: string): Promise<AuditLog> {
  return http.get(`/audit/${id}`)
}
