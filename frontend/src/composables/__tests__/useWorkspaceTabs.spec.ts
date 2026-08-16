import { beforeEach, describe, expect, it } from 'vitest'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import {
  removeWorkspaceTab,
  resolveWorkspaceMenuPath,
  resetWorkspaceTabs,
  useWorkspaceTabs,
  visitWorkspaceTab,
} from '@/composables/useWorkspaceTabs'
import type { MenuTreeNode } from '@/utils/permission'

const menus: MenuTreeNode[] = [
  { index: 'market', title: '市场研究', children: [
    { index: '/board', title: '每日榜单' },
    { index: '/stocks', title: '个股查询' },
    { index: '/sectors', title: '板块行情' },
  ] },
]

function route(path: string, title: string, code?: string): RouteLocationNormalizedLoaded {
  return {
    path,
    fullPath: path,
    params: code ? { code } : {},
    meta: { title },
  } as unknown as RouteLocationNormalizedLoaded
}

describe('工作标签页状态', () => {
  beforeEach(resetWorkspaceTabs)

  it('同一路径更新既有标签，详情页带证券代码', () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/stocks/600000.SH', '个股详情', '600000.SH'), menus)
    expect(useWorkspaceTabs().workspaceTabs.value.map((tab) => tab.title)).toEqual([
      '每日榜单', '个股详情 · 600000.SH',
    ])
  })

  it('菜单再进入不记详情子路由：点菜单回主页，详情现场只由工作标签恢复', () => {
    visitWorkspaceTab(route('/sectors/881121', '板块详情', '881121'), menus)
    // 详情子路由不覆盖菜单记忆——点「板块行情」菜单回主页而非上次详情
    expect(resolveWorkspaceMenuPath('/sectors')).toBe('/sectors')

    // 主页访问（含查询态）会被记忆
    visitWorkspaceTab(route('/sectors', '板块行情'), menus)
    expect(resolveWorkspaceMenuPath('/sectors')).toBe('/sectors')

    // 先看主页再进详情，菜单记忆仍是主页
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    visitWorkspaceTab(route('/stocks/600000.SH', '个股详情', '600000.SH'), menus)
    expect(resolveWorkspaceMenuPath('/stocks')).toBe('/stocks')
  })

  it('关闭当前标签后返回相邻页面，唯一标签不可关闭', () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    expect(removeWorkspaceTab('/board', '/board')).toBeUndefined()
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    expect(removeWorkspaceTab('/stocks', '/stocks')).toBe('/board')
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(1)
  })

  it('标签和缓存身份都限制为 12 个，超限时同步淘汰最旧项', () => {
    for (let index = 1; index <= 13; index += 1) {
      visitWorkspaceTab(route(`/stocks/${index}`, `详情 ${index}`), menus)
    }
    const { workspaceTabs, workspaceCacheNames } = useWorkspaceTabs()
    expect(workspaceTabs.value).toHaveLength(12)
    expect(workspaceTabs.value[0].key).toBe('/stocks/2')
    expect(new Set(workspaceCacheNames.value).size).toBe(12)
  })
})
