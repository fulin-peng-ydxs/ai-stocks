// 租户 API（多租户 RBAC stage3）——对应后端 backend/api/tenants.py（整 router 挂 require_system）。
// T11 用户管理页消费 listTenants（system 的租户筛选/新建归属下拉）；
// T14 租户管理页在此扩展 新建/编辑（含指定管理员）/启停/删除 写接口。
import http from './client'

export interface Tenant {
  id: string
  name: string
  status: string // active | disabled
  admin_user_id?: string | null
  admin_account?: string | null
  user_count?: number
  created_at?: string | null
}

export interface TenantListResult {
  items: Tenant[]
  total: number
}

export function listTenants(query: {
  q?: string
  status?: string
  page?: number
  size?: number
} = {}): Promise<TenantListResult> {
  return http.get('/tenants', { params: query })
}

// ── 写接口（T14）──
export function createTenant(body: { name: string; status?: string }): Promise<Tenant> {
  return http.post('/tenants', body)
}

/** 编辑：租户名 + 指定管理员（adminUserId 须属该租户，后端校验）。 */
export function updateTenant(id: string, body: { name: string; adminUserId?: string | null }): Promise<Tenant> {
  return http.put(`/tenants/${id}`, body)
}

/** 启停：停用即时踢下线该租户全部用户（后端 bump perm_ver + 每请求校验租户 status）。 */
export function setTenantStatus(id: string, status: string): Promise<Tenant> {
  return http.post(`/tenants/${id}/status`, { status })
}

export function deleteTenant(id: string): Promise<void> {
  return http.delete(`/tenants/${id}`)
}
