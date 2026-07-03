// 权限/菜单消费的纯逻辑（多租户 RBAC stage3·T15）——无 DOM 依赖，供 v-permission 指令、
// SideMenu、路由守卫、auth store 共用，并可在 node 环境单测。
// 事实源：/me 下发的 menus（按「角色授权 ∩ 可见性」双过滤的嵌套树）+ permissions（扁平功能码）。

/** /me 菜单节点：叶子 index=route_path（'/' 开头）、分组 index=code；icon 为 Element Plus 图标名。 */
export interface MenuTreeNode {
  index: string
  title: string
  icon?: string | null
  children?: MenuTreeNode[]
}

/** 递归收集所有叶子（可导航）路由路径——即 index 以 '/' 开头且无子节点。 */
export function collectMenuPaths(menus: MenuTreeNode[]): string[] {
  const out: string[] = []
  const walk = (nodes: MenuTreeNode[]) => {
    for (const n of nodes) {
      if (n.children?.length) walk(n.children)
      else if (n.index.startsWith('/')) out.push(n.index)
    }
  }
  walk(menus)
  return out
}

/** 首个可导航叶子路径（守卫无权时的安全落点）；无则空串。 */
export function firstMenuPath(menus: MenuTreeNode[]): string {
  return collectMenuPaths(menus)[0] ?? ''
}

/**
 * 路由是否放行：system 恒过；否则命中某授权叶子（精确或作为其子路由前缀，如
 * /stocks/600000 命中 /stocks）即放行。allowed 为空（未加载/加载失败）返回 false（fail-closed）。
 */
export function isRouteAllowed(path: string, allowed: string[], isSystem: boolean): boolean {
  if (isSystem) return true
  return allowed.some((a) => path === a || path.startsWith(a + '/'))
}

/** 按钮级判定：system 恒过；否则 permissions 含指定码之一（codes 支持单码或多码取并）。 */
export function hasPermission(role: string, permissions: string[], codes: string | string[]): boolean {
  if (role === 'system') return true
  const list = Array.isArray(codes) ? codes : [codes]
  return list.some((c) => permissions.includes(c))
}

/** 未授权时的安全首页（所有登录用户可达的落点，避免 fail-open 到被请求的未授权页）。 */
export const SAFE_HOME = '/board'

/**
 * 已登录、非公开路由的菜单授权决策（守卫核心；纯函数，可单测）。
 * - system 或命中授权叶子 → 放行(true)。
 * - 否则**fail-closed**：漏斗到安全落点（首个授权菜单，无则 SAFE_HOME）；已在落点则放行，避免死循环。
 * 关键：菜单未加载/加载失败（menuRoutePaths 为空）时，非 system **绝不**放行到被请求的未授权页——
 * 要么重定向到 SAFE_HOME，要么（当请求的就是 SAFE_HOME）落到首页壳（SideMenu 显错误/空态+重试）。
 */
export function resolveMenuGuard(
  path: string,
  opts: { isSystem: boolean; menuRoutePaths: string[]; firstMenuPath: string; safeHome?: string },
): true | { path: string } {
  if (isRouteAllowed(path, opts.menuRoutePaths, opts.isSystem)) return true
  const landing = opts.firstMenuPath || opts.safeHome || SAFE_HOME
  return path === landing ? true : { path: landing }
}
