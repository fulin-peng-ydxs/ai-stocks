import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import {
  clearOtherWorkspaceTabs,
  prepareWorkspaceTabVisit,
  removeWorkspaceTab,
  resolveWorkspaceMenuPath,
  resetWorkspaceTabs,
  trackWorkspaceRouteVisit,
  useWorkspaceTabs,
  visitWorkspaceTab,
} from '@/composables/useWorkspaceTabs'
import {
  registerUnsavedHandler,
  resetUnsavedChangesGuard,
} from '@/composables/useUnsavedChangesGuard'
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
  beforeEach(() => {
    resetWorkspaceTabs()
    resetUnsavedChangesGuard()
  })

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

  it('关闭当前标签后返回相邻页面，最后一个关闭后清空缓存身份', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    expect(await removeWorkspaceTab('/stocks', '/stocks')).toBe('/board')
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(1)
    expect(await removeWorkspaceTab('/board', '/board')).toBeUndefined()
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(0)
    expect(useWorkspaceTabs().workspaceCacheNames.value).toHaveLength(0)
  })

  it('最后一个脏标签也必须经过关闭确认', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    registerUnsavedHandler('/board', { isDirty: () => true, requestLeave: async () => false })
    await removeWorkspaceTab('/board', '/board')
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(1)
  })

  it('清除其他页签只释放对应缓存和菜单记忆，保留当前查询与缓存身份', async () => {
    const current = { ...route('/board', '每日榜单'), fullPath: '/board?restore=1' }
    visitWorkspaceTab({ ...route('/stocks', '个股查询'), fullPath: '/stocks?restore=1' }, menus)
    trackWorkspaceRouteVisit(current, menus)
    const activeTab = useWorkspaceTabs().workspaceTabs.value[1]
    expect(resolveWorkspaceMenuPath('/board')).toBe('/board?restore=1')
    const currentLeave = vi.fn(async () => false)
    registerUnsavedHandler('/board', { isDirty: () => true, requestLeave: currentLeave })
    expect(await clearOtherWorkspaceTabs(() => '/board')).toBe(true)
    expect(currentLeave).not.toHaveBeenCalled()
    expect(useWorkspaceTabs().workspaceCacheNames.value).toEqual([activeTab.cacheName])
    expect(resolveWorkspaceMenuPath('/board')).toBe('/board?restore=1')
    expect(resolveWorkspaceMenuPath('/stocks')).toBe('/stocks')
    expect(useWorkspaceTabs().workspaceTabs.value[0]).toBe(activeTab)
    trackWorkspaceRouteVisit(current, menus)
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(1)
  })

  it('非当前页逐页确认全部通过才清除，后续页面取消也保留之前的标签与缓存', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    visitWorkspaceTab(route('/sectors', '板块行情'), menus)
    const before = [...useWorkspaceTabs().workspaceCacheNames.value]
    const first = vi.fn(async () => true)
    const second = vi.fn(async () => false)
    registerUnsavedHandler('/board', { isDirty: () => true, requestLeave: first })
    registerUnsavedHandler('/stocks', { isDirty: () => true, requestLeave: second })
    expect(await clearOtherWorkspaceTabs(() => '/sectors')).toBe(false)
    expect(first).toHaveBeenCalledWith('tab-close')
    expect(second).toHaveBeenCalledWith('tab-close')
    expect(useWorkspaceTabs().workspaceCacheNames.value).toEqual(before)
    second.mockResolvedValue(true)
    expect(await clearOtherWorkspaceTabs(() => '/sectors')).toBe(true)
    expect(useWorkspaceTabs().workspaceTabs.value.map(tab => tab.key)).toEqual(['/sectors'])
  })

  it('确认期间新增页签时保留全部现场，不清除尚未确认的新页面', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/sectors', '板块行情'), menus)
    let finish!: (allowed: boolean) => void
    registerUnsavedHandler('/board', {
      isDirty: () => true,
      requestLeave: () => new Promise<boolean>(resolve => { finish = resolve }),
    })
    const pending = clearOtherWorkspaceTabs(() => '/sectors')
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    finish(true)
    expect(await pending).toBe(false)
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(3)
  })

  it('确认期间切换到已有页签时不关闭新当前页', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    let current = '/stocks'
    let finish!: (allowed: boolean) => void
    registerUnsavedHandler('/board', {
      isDirty: () => true,
      requestLeave: () => new Promise<boolean>(resolve => { finish = resolve }),
    })
    const pending = clearOtherWorkspaceTabs(() => current)
    current = '/board'
    finish(true)
    expect(await pending).toBe(false)
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(2)
  })

  it('只有当前页时不询问离开，找不到当前页时不清除工作区', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    const requestLeave = vi.fn(async () => true)
    registerUnsavedHandler('/board', { isDirty: () => true, requestLeave })
    expect(await clearOtherWorkspaceTabs(() => '/board')).toBe(true)
    expect(await clearOtherWorkspaceTabs(() => '/missing')).toBe(false)
    expect(requestLeave).not.toHaveBeenCalled()
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

  it('关闭脏标签先确认，拒绝时标签与缓存均保持不变', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    registerUnsavedHandler('/stocks', {
      isDirty: () => true,
      requestLeave: async () => false,
    })

    expect(await removeWorkspaceTab('/stocks', '/stocks')).toBeUndefined()
    expect(useWorkspaceTabs().workspaceTabs.value.map((tab) => tab.key)).toEqual([
      '/board', '/stocks',
    ])
  })

  it('关闭非当前脏标签被拒绝时不删除标签与 KeepAlive 身份', async () => {
    visitWorkspaceTab(route('/board', '每日榜单'), menus)
    visitWorkspaceTab(route('/stocks', '个股查询'), menus)
    const beforeCacheNames = [...useWorkspaceTabs().workspaceCacheNames.value]
    registerUnsavedHandler('/board', {
      isDirty: () => true,
      requestLeave: async () => false,
    })

    expect(await removeWorkspaceTab('/board', '/stocks')).toBeUndefined()
    expect(useWorkspaceTabs().workspaceTabs.value.map((tab) => tab.key)).toEqual([
      '/board', '/stocks',
    ])
    expect(useWorkspaceTabs().workspaceCacheNames.value).toEqual(beforeCacheNames)
  })

  it('容量满时优先淘汰干净标签；全部脏且拒绝时阻止新导航', async () => {
    for (let index = 1; index <= 12; index += 1) {
      visitWorkspaceTab(route(`/stocks/${index}`, `详情 ${index}`), menus)
    }
    for (let index = 1; index <= 12; index += 1) {
      registerUnsavedHandler(`/stocks/${index}`, {
        isDirty: () => true,
        requestLeave: async () => false,
      })
    }
    expect(await prepareWorkspaceTabVisit('/stocks/13', '/stocks/12')).toBe(false)
    expect(useWorkspaceTabs().workspaceTabs.value).toHaveLength(12)
    expect(useWorkspaceTabs().workspaceTabs.value[0].key).toBe('/stocks/1')
  })
})
