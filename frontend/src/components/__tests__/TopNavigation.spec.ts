// @vitest-environment jsdom
import { defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import TopNavigation from '@/components/TopNavigation.vue'
import {
  initDisplayScale,
  resetDisplayScaleForTests,
  setCustomDisplayScalePercent,
} from '@/composables/useDisplayScale'
import { useAuthStore } from '@/stores/auth'
import type { MenuTreeNode } from '@/utils/permission'

const menus: MenuTreeNode[] = [
  { index: 'market', title: '市场研究', icon: 'TrendCharts', children: [{ index: '/board', title: '每日榜单', icon: 'DataBoard' }] },
  { index: 'system', title: '系统管理', icon: 'Setting', children: [
    { index: 'permission', title: '权限管理', icon: 'Lock', children: [{ index: '/system/users', title: '用户管理', icon: 'User' }] },
    { index: '/system/audit', title: '审计日志', icon: 'Document' },
  ] },
]

describe('双层顶栏导航', () => {
  beforeEach(() => {
    resetDisplayScaleForTests()
    Object.defineProperty(window.screen, 'availWidth', { configurable: true, value: 1920 })
    Object.defineProperty(window.screen, 'availHeight', { configurable: true, value: 1080 })
    Object.defineProperty(window.screen, 'availLeft', { configurable: true, value: 0 })
    Object.defineProperty(window.screen, 'availTop', { configurable: true, value: 0 })
  })
  afterEach(() => { resetDisplayScaleForTests(); vi.useRealTimers() })

  it('一级切换后进入首个授权页，并展示对应二级菜单', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.menusStatus = 'ready'
    auth.menus = menus
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/board', component: { template: '<div />' } },
        { path: '/system/users', component: { template: '<div />' } },
        { path: '/system/audit', component: { template: '<div />' } },
      ],
    })
    await router.push('/board')
    await router.isReady()
    const host = defineComponent({
      components: { TopNavigation },
      template: '<TopNavigation level="primary"/><TopNavigation level="secondary"/>',
    })
    const wrapper = mount(host, { global: { plugins: [pinia, router, ElementPlus] } })
    await wrapper.findAll('.primary-entry').find((entry) => entry.text() === '系统管理')!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/system/users')
    expect(wrapper.text()).toContain('权限管理')
    expect(wrapper.text()).toContain('审计日志')
    expect(wrapper.findAll('.primary-entry-icon')).toHaveLength(2)
    expect(wrapper.findAll('.secondary-entry-icon')).toHaveLength(2)
  })

  it('当前标签页调整显示比例后保持导航 DOM 稳定', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.menusStatus = 'ready'
    auth.menus = menus
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/board', component: { template: '<div />' } }],
    })
    await router.push('/board')
    await router.isReady()
    const wrapper = mount(TopNavigation, {
      props: { level: 'secondary' },
      global: { plugins: [pinia, router, ElementPlus] },
    })
    const originalNavigation = wrapper.get('nav').element

    setCustomDisplayScalePercent(73)
    await nextTick()

    expect(wrapper.get('nav').attributes('data-display-scale')).toBe('73')
    expect(wrapper.get('nav').element).toBe(originalNavigation)
    wrapper.unmount()
  })

  it('跨到同尺寸屏幕且比例不变时更新几何修订但不重挂导航', async () => {
    vi.useFakeTimers()
    initDisplayScale()
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.menusStatus = 'ready'
    auth.menus = menus
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/board', component: { template: '<div />' } }],
    })
    await router.push('/board')
    await router.isReady()
    const wrapper = mount(TopNavigation, {
      props: { level: 'secondary' },
      global: { plugins: [pinia, router, ElementPlus] },
    })
    const originalNavigation = wrapper.get('nav').element
    const originalScale = wrapper.get('nav').attributes('data-display-scale')

    Object.defineProperty(window.screen, 'availLeft', { configurable: true, value: 1920 })
    window.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(130)
    await nextTick()

    expect(wrapper.get('nav').attributes('data-display-scale')).toBe(originalScale)
    expect(wrapper.get('nav').attributes('data-display-geometry-revision')).toBe('1')
    expect(wrapper.get('nav').element).toBe(originalNavigation)

    const firstRefreshedNavigation = wrapper.get('nav').element
    vi.advanceTimersByTime(420)
    await nextTick()

    expect(wrapper.get('nav').attributes('data-display-geometry-revision')).toBe('2')
    expect(wrapper.get('nav').element).toBe(firstRefreshedNavigation)
    wrapper.unmount()
  })
})
