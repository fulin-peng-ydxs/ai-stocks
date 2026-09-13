// 角色管理 API（多租户 RBAC stage3·T12，R11）——对应后端 backend/api/roles.py。
// 角色为平台级全局表，管理入口仅 system（后端整段 require_system，assignable 除外）。
import http from './client'

export interface Role {
  id: string
  code: string
  name: string
  kind: string // system | tenant_admin | normal | custom
  is_builtin: boolean
  is_locked: boolean
  tenant_assignable: boolean
  description?: string | null
  member_count?: number
}

/** 角色当前授权：菜单 id 集 + 功能点 id 集（供权限树回显）。 */
export interface RoleGrants {
  menu_ids: string[]
  resource_ids: string[]
}

export function listRoles(): Promise<Role[]> {
  return http.get('/roles')
}

export function createRole(payload: {
  code: string
  name: string
  description?: string | null
  tenantAssignable?: boolean
}): Promise<Role> {
  return http.post('/roles', payload)
}

export function updateRole(roleId: string, payload: {
  name: string
  description?: string | null
  tenantAssignable: boolean
}): Promise<Role> {
  return http.put(`/roles/${encodeURIComponent(roleId)}`, payload)
}

export function deleteRole(roleId: string): Promise<null> {
  return http.delete(`/roles/${encodeURIComponent(roleId)}`)
}

export function getRoleGrants(roleId: string): Promise<RoleGrants> {
  return http.get(`/roles/${encodeURIComponent(roleId)}/perms`)
}

export function setRoleGrants(roleId: string, payload: { menuIds: string[]; resourceIds: string[] }): Promise<RoleGrants> {
  return http.put(`/roles/${encodeURIComponent(roleId)}/perms`, payload)
}
