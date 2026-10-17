// @vitest-environment jsdom
// SideMenu 后端菜单消费 + fail-closed DOM 测试（T15 / Codex 整改 P2#6）：
// ready 按 menus 渲染；loading 显加载中；error 显错误+重试且**不露任何菜单项**（无静态全量兜底）。
import { afterEach, describe, it, expect, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'
import SideMenu from '@/components/SideMenu.vue'
import { useAuthStore } from '@/stores/auth'
import type { MenuTreeNode } from '@/utils/permission'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/board', component: { template: '<div/>' } },
    { path: '/screen', component: { template: '<div/>' } },
    { path: '/training', component: { template: '<div/>' } },
    { path: '/system/users', component: { template: '<div/>' } },
    { path: '/system/users/:id', component: { template: '<div/>' } },
    { path: '/system/audit', component: { template: '<div/>' } },
  ],
})

const MENUS: MenuTreeNode[] = [
  { index: 'quotes', title: '最新行情', icon: 'TrendCharts', children: [
    { index: '/board', title: '每日榜单' },
  ] },
  { index: '/screen', title: '策略筛选', icon: 'Filter' },
]

const wrappers: VueWrapper[] = []
const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (originalScrollIntoView) {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView)
  } else {
    delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView
  }
})

async function mountMenu(status: string, menus: MenuTreeNode[], path = '/board') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.menusStatus = status as never
  auth.menus = menus
  await router.push(path)
  await router.isReady()
  const w = mount(SideMenu, { global: { plugins: [pinia, router, ElementPlus] } })
  wrappers.push(w)
  await w.vm.$nextTick()
  return w
}

const SYSTEM: MenuTreeNode = {
  index: 'system', title: '系统管理', children: [
    { index: 'permission', title: '权限管理', children: [
      { index: '/system/users', title: '用户管理' },
    ] },
    { index: 'config', title: '配置管理', children: [
      { index: '/system/audit', title: '审计日志' },
    ] },
  ],
}

function opened(w: VueWrapper) {
  return w.findAll('.el-sub-menu.is-opened > .el-sub-menu__title').map((item) => item.text())
}
function group(w: VueWrapper, title: string) {
  return w.findAll('.el-sub-menu__title').find((item) => item.text() === title)!
}

describe('SideMenu 分区导航与 fail-closed', () => {
  it('分区标题与当前路由联动，详情继承，直达页面不误亮其他分区', async () => {
    const w = await mountMenu('ready', [...MENUS, SYSTEM])
    const currentHeading = () => w.findAll('.section-heading[aria-current="location"]')
      .map((heading) => heading.text())
    expect(currentHeading()).toEqual(['最新行情'])
    await router.push('/system/users/123')
    await flushPromises()
    expect(currentHeading()).toEqual(['系统管理'])
    expect(w.findAll('.menu-section.is-current-section')).toHaveLength(1)
    expect(group(w, '权限管理').element.parentElement?.classList.contains('is-active')).toBe(true)
    expect(w.get('.el-menu-item.is-active').text()).toBe('用户管理')
    await group(w, '权限管理').trigger('click')
    await group(w, '配置管理').trigger('click')
    expect(currentHeading()).toEqual(['系统管理'])
    expect(group(w, '配置管理').element.parentElement?.classList.contains('is-active')).toBe(false)
    await router.push('/screen')
    await flushPromises()
    expect(currentHeading()).toEqual([])
    expect(w.get('.el-menu-item.is-active').text()).toBe('策略筛选')
  })

  it('一级仅作非交互标题，二级提升为主入口，连续直达项合段且保留顺序', async () => {
    const menus = [...MENUS, { index: '/training', title: '盘感训练' }, SYSTEM]
    const original = JSON.stringify(menus)
    const w = await mountMenu('ready', menus)
    const sections = w.findAll('.menu-section')
    expect(sections).toHaveLength(3)
    expect(sections.map((section) => section.classes().includes('is-untitled')))
      .toEqual([false, true, false])
    expect(w.findAll('.section-heading').map((item) => item.text())).toEqual(['最新行情', '系统管理'])
    const heading = w.get('.section-heading')
    expect(heading.find('button, [tabindex], .el-sub-menu__icon-arrow').exists()).toBe(false)
    await heading.trigger('click')
    expect(router.currentRoute.value.path).toBe('/board')
    expect(w.get('.el-menu-item.is-active').classes()).toContain('is-root-menu-node')
    expect(w.findAll('.el-menu-item').map((item) => item.text()))
      .toEqual(['每日榜单', '策略筛选', '盘感训练', '用户管理', '审计日志'])
    expect(JSON.stringify(menus)).toBe(original)
  })

  it('手动可展开多组，切页收起非当前组，详情补开当前链，同页查询不重置', async () => {
    const w = await mountMenu('ready', [...MENUS, SYSTEM], '/system/users')
    expect(opened(w)).toEqual(['权限管理'])
    await group(w, '配置管理').trigger('click')
    expect(opened(w)).toEqual(['权限管理', '配置管理'])
    await router.push('/system/audit')
    await flushPromises()
    expect(opened(w)).toEqual(['配置管理'])
    await router.push('/screen')
    await flushPromises()
    expect(opened(w)).toEqual([])
    await router.push('/system/users/123')
    await flushPromises()
    expect(opened(w)).toEqual(['权限管理'])
    expect(w.get('.el-menu-item.is-active').text()).toBe('用户管理')
    await group(w, '权限管理').trigger('click')
    await group(w, '配置管理').trigger('click')
    await router.push('/system/users/123?date=2026-10-15')
    await flushPromises()
    expect(opened(w)).toEqual(['配置管理'])
  })

  it('异步授权就绪后展开完整下级链，授权移除后不残留菜单', async () => {
    const w = await mountMenu('loading', [], '/system/users')
    const auth = useAuthStore()
    auth.menus = [SYSTEM]
    auth.menusStatus = 'ready'
    await flushPromises()
    expect(opened(w)).toEqual(['权限管理'])
    expect(w.get('.el-menu-item.is-active').text()).toBe('用户管理')
    auth.menus = MENUS
    await flushPromises()
    expect(w.text()).not.toContain('系统管理')
    expect(w.text()).not.toContain('用户管理')
    expect(w.find('.is-current-section').exists()).toBe(false)
    auth.menus = []
    await flushPromises()
    expect(w.text()).toContain('暂无可用菜单')
    expect(w.find('.el-menu').exists()).toBe(false)
  })

  it('三级起缩进，深层递归与长名称、空图标占位仍可用', async () => {
    const title = '页面布局与研究工作区的完整配置名称'
    const w = await mountMenu('ready', [{ index: 'system', title: '系统管理', children: [
      { index: 'config', title: '页面配置', children: [
        { index: 'nested', title: '嵌套分组', children: [
          { index: '/system/users', title, icon: 'Setting' },
        ] },
      ] },
    ] }], '/system/users')
    expect(opened(w)).toEqual(['页面配置', '嵌套分组'])
    expect(w.get('.is-root-menu-node').attributes('style')).toContain('--side-menu-depth: 0')
    expect(w.findAll('.el-sub-menu')[1].attributes('style')).toContain('--side-menu-depth: 1')
    const leaf = w.get('.el-menu-item.is-active')
    expect(leaf.attributes('style')).toContain('--side-menu-depth: 2')
    expect(leaf.get('.menu-text').text()).toBe(title)
    const rootIcon = w.get('.is-root-menu-node > .el-sub-menu__title .menu-icon')
    expect(rootIcon.attributes('aria-hidden')).toBe('true')
    expect(rootIcon.find('svg').exists()).toBe(false)
  })

  it('点击下级分组不导航，点击叶子仍导航', async () => {
    const w = await mountMenu('ready', [...MENUS, SYSTEM], '/system/users')
    await group(w, '权限管理').trigger('click')
    expect(opened(w)).toEqual([])
    expect(router.currentRoute.value.path).toBe('/system/users')
    await group(w, '权限管理').trigger('click')
    expect(opened(w)).toEqual(['权限管理'])
    await w.findAll('.el-menu-item').find((item) => item.text() === '策略筛选')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/screen')
  })

  it('跨页返回每日榜单后叶子和分区仍保持当前状态，悬停其他入口不改选择', async () => {
    const w = await mountMenu('ready', MENUS, '/screen')
    const board = w.findAll('.el-menu-item').find((item) => item.text() === '每日榜单')!
    const screen = w.findAll('.el-menu-item').find((item) => item.text() === '策略筛选')!
    await board.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/board')
    expect(board.classes()).toContain('is-active')
    expect(w.get('.section-heading[aria-current="location"]').text()).toBe('最新行情')
    await screen.trigger('mouseenter')
    expect(board.classes()).toContain('is-active')
    await screen.trigger('click')
    await flushPromises()
    await board.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/board')
    expect(w.get('.el-menu-item.is-active').text()).toBe('每日榜单')
  })

  it('仅页面路径或授权变化时滚动露出当前项，不因查询变化抢滚动', async () => {
    const targets: HTMLElement[] = []
    const scroll = vi.fn(function (this: HTMLElement) { targets.push(this) })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true, writable: true, value: scroll,
    })
    const w = await mountMenu('ready', [...MENUS, SYSTEM])
    await flushPromises()
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' })
    expect(targets.at(-1)).toBe(w.get('.section-heading').element)
    scroll.mockClear()
    await router.push('/board?date=2026-10-15')
    await flushPromises()
    expect(scroll).not.toHaveBeenCalled()
    await router.push('/system/users')
    await flushPromises()
    expect(scroll).toHaveBeenCalled()
    expect(w.get('.el-menu-item.is-active').text()).toBe('用户管理')
  })

  it('空授权显空态，不伪装成失败或回退静态菜单', async () => {
    const w = await mountMenu('ready', [])
    expect(w.get('[role="status"]').text()).toBe('暂无可用菜单')
    expect(w.text()).not.toContain('失败')
    expect(w.find('.el-menu').exists()).toBe(false)
  })

  it('失败态不泄露旧授权菜单，重试复用 auth 入口', async () => {
    const w = await mountMenu('error', MENUS)
    const retry = vi.spyOn(useAuthStore(), 'retryMe').mockResolvedValue(undefined)
    expect(w.get('[role="alert"]').text()).toContain('菜单加载失败')
    expect(w.text()).not.toContain('每日榜单')
    expect(w.findAll('.el-menu-item')).toHaveLength(0)
    await w.get('button').trigger('click')
    expect(retry).toHaveBeenCalledOnce()
  })

  it.each(['idle', 'loading'])('%s 不渲染旧菜单，显示加载中', async (status) => {
    const w = await mountMenu(status, MENUS)
    expect(w.get('[role="status"]').text()).toContain('菜单加载中')
    expect(w.findAll('.el-menu-item')).toHaveLength(0)
    expect(w.text()).not.toContain('每日榜单')
  })
})
