// @vitest-environment jsdom
// SideMenu 后端菜单消费 + fail-closed DOM 测试（T15 / Codex 整改 P2#6）：
// ready 按 menus 渲染；loading 显加载中；error 显错误+重试且**不露任何菜单项**（无静态全量兜底）。
import { afterEach, describe, it, expect } from 'vitest'
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
    { path: '/system/users', component: { template: '<div/>' } },
  ],
})

const MENUS: MenuTreeNode[] = [
  { index: 'quotes', title: '最新行情', icon: 'TrendCharts', children: [
    { index: '/board', title: '每日榜单' },
  ] },
  { index: '/screen', title: '策略筛选', icon: 'Filter' },
]

const wrappers: VueWrapper[] = []
afterEach(() => { wrappers.splice(0).forEach((wrapper) => wrapper.unmount()) })

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

describe('SideMenu fail-closed', () => {
  it('三级菜单沿授权层级展开，长名称保留完整文本，无图标项保留对齐位', async () => {
    const title = '页面布局与研究工作区的完整配置名称'
    const w = await mountMenu('ready', [{ index: 'system', title: '系统管理', children: [
      { index: 'config', title: '页面配置', children: [
        { index: '/system/users', title, icon: 'Setting' },
      ] },
    ] }], '/system/users')
    expect(w.findAll('.el-sub-menu.is-opened')).toHaveLength(2)
    expect(w.get('.is-root-menu-node').attributes('style')).toContain('--side-menu-depth: 0')
    const branch = w.findAll('.el-sub-menu')[1]
    expect(branch.attributes('style')).toContain('--side-menu-depth: 1')
    const leaf = w.get('.el-menu-item.is-active')
    expect(leaf.attributes('style')).toContain('--side-menu-depth: 2')
    expect(leaf.get('.menu-text').text()).toBe(title)
    const rootIcon = w.get('.is-root-menu-node > .el-sub-menu__title .menu-icon')
    expect(rootIcon.attributes('aria-hidden')).toBe('true')
    expect(rootIcon.find('svg').exists()).toBe(false)
  })

  it('点击叶子仍导航，分组折叠展开不改变当前页面', async () => {
    const w = await mountMenu('ready', MENUS)
    const group = w.get('.el-sub-menu__title')
    await group.trigger('click')
    expect(w.get('.el-sub-menu').classes()).not.toContain('is-opened')
    expect(router.currentRoute.value.path).toBe('/board')
    await group.trigger('click')
    expect(w.get('.el-sub-menu').classes()).toContain('is-opened')
    await w.findAll('.el-menu-item').find((item) => item.text() === '策略筛选')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/screen')
  })

  it('ready：按后端 menus 渲染菜单项', async () => {
    const w = await mountMenu('ready', MENUS)
    expect(w.text()).toContain('最新行情')
    expect(w.text()).toContain('每日榜单')
    expect(w.text()).toContain('策略筛选')
    expect(w.findAll('.el-menu-item').length).toBeGreaterThan(0)
  })

  it('error：显错误+重试，且不渲染任何菜单项（不露静态全量菜单）', async () => {
    const w = await mountMenu('error', [])
    expect(w.text()).toContain('菜单加载失败')
    expect(w.text()).toContain('重试')
    expect(w.findAll('.el-menu-item').length).toBe(0)
    // 关键：即便曾有静态菜单，这里也不应出现业务菜单文案
    expect(w.text()).not.toContain('策略筛选')
  })

  it('loading：显加载中，不渲染菜单项', async () => {
    const w = await mountMenu('loading', [])
    expect(w.text()).toContain('菜单加载中')
    expect(w.findAll('.el-menu-item').length).toBe(0)
  })
})
