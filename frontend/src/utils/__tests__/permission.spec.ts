import { describe, it, expect } from 'vitest'
import {
  collectMenuPaths, firstMenuPath, isRouteAllowed, hasPermission, type MenuTreeNode,
} from '@/utils/permission'

// 模拟 /me 下发的菜单树：分组 index=code、叶子 index=route_path。
const MENUS: MenuTreeNode[] = [
  { index: 'quotes', title: '最新行情', children: [
    { index: '/stocks', title: '个股行情' },
    { index: '/board', title: '每日榜单' },
  ] },
  { index: '/screen', title: '策略筛选' },
  { index: 'system', title: '系统管理', children: [
    { index: 'permission', title: '权限管理', children: [
      { index: '/system/users', title: '用户管理' },
    ] },
  ] },
]

describe('collectMenuPaths', () => {
  it('仅收集叶子路由路径，跳过分组 code', () => {
    expect(collectMenuPaths(MENUS)).toEqual(['/stocks', '/board', '/screen', '/system/users'])
  })
  it('空菜单返回空数组', () => {
    expect(collectMenuPaths([])).toEqual([])
  })
})

describe('firstMenuPath', () => {
  it('返回首个叶子路径', () => {
    expect(firstMenuPath(MENUS)).toBe('/stocks')
  })
  it('空菜单返回空串', () => {
    expect(firstMenuPath([])).toBe('')
  })
})

describe('isRouteAllowed', () => {
  const allowed = ['/stocks', '/board', '/system/users']
  it('system 恒过（即便 allowed 为空）', () => {
    expect(isRouteAllowed('/anything', [], true)).toBe(true)
  })
  it('精确命中授权叶子', () => {
    expect(isRouteAllowed('/board', allowed, false)).toBe(true)
  })
  it('子路由按前缀命中（/stocks/600000 → /stocks）', () => {
    expect(isRouteAllowed('/stocks/600000.SH', allowed, false)).toBe(true)
  })
  it('未授权路由拒绝', () => {
    expect(isRouteAllowed('/system/tenants', allowed, false)).toBe(false)
  })
  it('前缀不完整不误判（/stocksXYZ 不命中 /stocks）', () => {
    expect(isRouteAllowed('/stocksXYZ', allowed, false)).toBe(false)
  })
  it('allowed 为空（未加载/失败）非 system 一律拒绝（fail-closed）', () => {
    expect(isRouteAllowed('/board', [], false)).toBe(false)
  })
})

describe('hasPermission', () => {
  it('system 恒过', () => {
    expect(hasPermission('system', [], 'user:create')).toBe(true)
  })
  it('permissions 含指定码放行', () => {
    expect(hasPermission('normal', ['user:list', 'user:create'], 'user:create')).toBe(true)
  })
  it('缺码拒绝', () => {
    expect(hasPermission('normal', ['user:list'], 'user:create')).toBe(false)
  })
  it('多码取并（含其一即可）', () => {
    expect(hasPermission('normal', ['role:list'], ['user:create', 'role:list'])).toBe(true)
  })
  it('多码全缺拒绝', () => {
    expect(hasPermission('normal', ['x'], ['user:create', 'role:list'])).toBe(false)
  })
})
