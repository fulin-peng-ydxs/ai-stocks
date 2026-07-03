// @vitest-environment jsdom
// SideMenu 后端菜单消费 + fail-closed DOM 测试（T15 / Codex 整改 P2#6）：
// ready 按 menus 渲染；loading 显加载中；error 显错误+重试且**不露任何菜单项**（无静态全量兜底）。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
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
  ],
})

const MENUS: MenuTreeNode[] = [
  { index: 'quotes', title: '最新行情', icon: 'TrendCharts', children: [
    { index: '/board', title: '每日榜单' },
  ] },
  { index: '/screen', title: '策略筛选', icon: 'Filter' },
]

async function mountMenu(status: string, menus: MenuTreeNode[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.menusStatus = status as never
  auth.menus = menus
  await router.push('/board')
  await router.isReady()
  const w = mount(SideMenu, { global: { plugins: [pinia, router, ElementPlus] } })
  await w.vm.$nextTick()
  return w
}

describe('SideMenu fail-closed', () => {
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
