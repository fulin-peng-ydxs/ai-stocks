// 用户管理 API（多租户 RBAC stage3·T11，R10）——对应后端 backend/api/users.py。
// 归属/角色一律取自后端上下文；tenantId 仅 system 生效（tenant_admin 忽略，防越权）。
import http from './client'

/** 用户管理列表/详情视图（无 password_hash）；roles 为角色码集，权限取并集。 */
export interface AdminUser {
  id: string
  tenant_id: string
  account: string
  email: string | null
  role_code: string
  roles: string[]
  status: string // active | disabled | locked
  perm_ver: number
  last_login_at: string | null
  created_at: string | null
}

export interface UserListResult {
  items: AdminUser[]
  total: number
}

/** 可分配角色（供用户下拉；按调用者身份分流，system 得含自建 custom、tenant_admin 仅系统预设）。 */
export interface AssignableRole {
  id: string
  code: string
  name: string
  kind: string
  is_builtin: boolean
  is_locked: boolean
  description?: string | null
}

export interface UserListQuery {
  tenant_id?: string
  role?: string
  status?: string
  q?: string
  page?: number
  size?: number
}

export function listUsers(query: UserListQuery = {}): Promise<UserListResult> {
  return http.get('/users', { params: query })
}

export function createUser(payload: {
  account: string
  password: string
  email?: string | null
  roleIds: string[]
  status?: string
  tenantId?: string | null // 仅 system 生效
}): Promise<AdminUser> {
  return http.post('/users', payload)
}

export function updateUser(userId: string, payload: {
  email?: string | null
  roleIds: string[]
  status: string
}): Promise<AdminUser> {
  return http.put(`/users/${encodeURIComponent(userId)}`, payload)
}

export function setUserStatus(userId: string, status: string): Promise<AdminUser> {
  return http.post(`/users/${encodeURIComponent(userId)}/status`, { status })
}

export function resetUserPassword(userId: string, password: string): Promise<null> {
  return http.post(`/users/${encodeURIComponent(userId)}/reset-password`, { password })
}

export function deleteUser(userId: string): Promise<null> {
  return http.delete(`/users/${encodeURIComponent(userId)}`)
}

/** 可分配角色下拉（挂后端 require_perm(user:list)，tenant_admin 亦可读，闭合分配链路）。 */
export function listAssignableRoles(): Promise<AssignableRole[]> {
  return http.get('/roles/assignable')
}
