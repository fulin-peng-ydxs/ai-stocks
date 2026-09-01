// 菜单 / 功能点 API（多租户 RBAC stage3）——对应后端 backend/api/menus.py + resources.py（均 require_system）。
// T12 角色管理页消费只读 listMenus + listResources（构建授权树）；
// T13 菜单与功能管理页在此扩展 菜单/功能点的 CRUD、排序 写接口。
import http from './client'

/** 菜单树节点（嵌套 children）。icon 存 Element Plus 图标名；type=group/leaf；visible=login/system。 */
export interface MenuNode {
  id: string
  parent_id: string | null
  code: string
  title: string
  type: string // group | leaf
  route_path: string | null
  icon: string | null
  sort: number
  visible: string // login | system
  is_builtin: boolean
  children: MenuNode[]
}

/** 功能点（按钮/接口）。type=button/api。 */
export interface Resource {
  id: string
  menu_id: string
  code: string
  name: string
  type: string // button | api
  api_method: string | null
  api_path: string | null
  sort: number
  is_builtin: boolean
  role_count?: number
  baseline_locked?: boolean // 登录基线共享读码：角色页恒勾选+置灰不可反选（stage4·R21）
  system_locked?: boolean // 普通业务菜单下仍仅系统管理员可用：角色页显示但置灰不可授
}

export function listMenus(): Promise<MenuNode[]> {
  return http.get('/menus')
}

export function listResources(menuId?: string): Promise<Resource[]> {
  return http.get('/resources', { params: menuId ? { menu_id: menuId } : {} })
}

// ── 菜单写接口（T13）──
// 注：内置菜单 seed id=code 含斜杠（如 /screen、/system/users），后端用 `{menu_id:path}` 转换器捕获。
// **必须 encodeURIComponent(id)**：直接插值 `/menus/${'/board'}` 会得双斜杠 `/menus//board`，
// 浏览器/fetch 规范化后丢掉前导斜杠 → 后端收 `board` 匹配不到（实测「菜单不存在」）；
// 编码为 `%2Fboard` 后 :path 解码回 `/board` 才命中（实测通过）。对 uuid 自定义 id 编码为恒等，两者皆安全。
export interface MenuWrite {
  parentId?: string | null
  code?: string // 仅创建需要；创建后不可改
  title: string
  type: string // group | leaf
  routePath?: string | null
  icon?: string | null
  visible: string // login | system
  sort?: number | null
}

export function createMenu(body: MenuWrite): Promise<MenuNode> {
  return http.post('/menus', body)
}

export function updateMenu(id: string, body: MenuWrite): Promise<MenuNode> {
  return http.put(`/menus/${encodeURIComponent(id)}`, body)
}

export function deleteMenu(id: string): Promise<void> {
  return http.delete(`/menus/${encodeURIComponent(id)}`)
}

/** 批量排序/移动：items=[{id, sort, parentId?}]；纯排序不失效权限，含移动的节点后端会 bump。 */
export function reorderMenus(items: Array<{ id: string; sort: number; parentId: string | null }>): Promise<unknown> {
  return http.post('/menus/reorder', { items })
}

// ── 功能点写接口（T13）──
export interface ResourceWrite {
  menuId: string
  code: string
  name: string
  type: string // button | api
  apiMethod?: string | null
  apiPath?: string | null
  sort?: number | null
}

export function createResource(body: ResourceWrite): Promise<Resource> {
  return http.post('/resources', body)
}

export function updateResource(id: string, body: ResourceWrite): Promise<Resource> {
  return http.put(`/resources/${id}`, body)
}

export function deleteResource(id: string): Promise<void> {
  return http.delete(`/resources/${id}`)
}
