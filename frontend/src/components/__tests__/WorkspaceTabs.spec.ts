// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearAuth } from '@/api/authToken'
import { resetWorkspaceTabPreferencesForTests, useWorkspaceTabPreferences } from '@/composables/useWorkspaceTabPreferences'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import WorkspaceRouteView from '@/components/WorkspaceRouteView.vue'
import MenuIcon from '@/components/MenuIcon.vue'
import { registerUnsavedHandler, resetUnsavedChangesGuard } from '@/composables/useUnsavedChangesGuard'
import { navigateWorkspaceMenu, resetWorkspaceTabs } from '@/composables/useWorkspaceTabs'
import { useAuthStore } from '@/stores/auth'

async function mountTabs(expanded = true) {
  resetWorkspaceTabs()
  if (expanded) useWorkspaceTabPreferences().setCollapsed(false)
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.menusStatus = 'ready'
  auth.menus = [{ index: 'market', title: '市场研究', children: [
    { index: '/board', title: '每日榜单', icon: 'DataBoard' },
    { index: '/screen', title: '策略筛选', icon: 'Filter' },
  ] }]
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/board', component: { template: '<div />' }, meta: { title: '每日榜单' } },
      { path: '/screen', component: { template: '<div />' }, meta: { title: '策略筛选' } },
    ],
  })
  await router.push('/board')
  await router.isReady()
  const host = defineComponent({
    components: { WorkspaceTabs, WorkspaceRouteView },
    template: '<WorkspaceTabs/><WorkspaceRouteView/>',
  })
  const wrapper = mount(host, { attachTo: document.body, global: { plugins: [pinia, router, ElementPlus] } })
  return { wrapper, router }
}

describe('侧栏工作标签页', () => {
  beforeEach(() => { clearAuth(); localStorage.clear(); resetWorkspaceTabPreferencesForTests() })
  afterEach(() => { vi.unstubAllGlobals(); resetUnsavedChangesGuard(); document.body.innerHTML = '' })

  it('记录访问页面，关闭当前页后切回相邻标签', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()

    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    expect(wrapper.get('.workspace-tabs-label').text()).toBe('工作区')
    expect(wrapper.get('.workspace-tabs-count').text()).toBe('2')
    expect(wrapper.get('.workspace-tabs-divider').attributes('aria-hidden')).toBe('true')
    expect(wrapper.get('[role="tablist"]').find('.workspace-tabs-heading').exists()).toBe(false)
    await wrapper.get('.workspace-tab.is-active .workspace-tab-close').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/board')
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(1)
    expect(wrapper.get('.workspace-tabs-count').text()).toBe('1')
    await wrapper.get('.workspace-tab-close').trigger('click')
    await flushPromises()
    expect(wrapper.find('.workspace-tabs').exists()).toBe(false)
    expect(wrapper.get('[aria-label="空工作区"]').text()).toContain('工作区已清空')
    wrapper.unmount()
  })

  it('方向键/Home/End 只移动焦点，Enter 激活；组合键和关闭按钮不冒泡导航', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()
    const tabs = wrapper.findAll('[role="tab"]')
    ;(tabs[1].element as HTMLElement).focus()
    await tabs[1].trigger('keydown', { key: 'ArrowLeft' })
    expect(document.activeElement).toBe(tabs[0].element)
    expect(router.currentRoute.value.path).toBe('/screen')
    expect(tabs[0].attributes('tabindex')).toBe('0')
    await tabs[0].trigger('keydown', { key: 'End' })
    expect(document.activeElement).toBe(tabs[1].element)
    await tabs[1].trigger('keydown', { key: 'Home', ctrlKey: true })
    expect(document.activeElement).toBe(tabs[1].element)
    await tabs[1].trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(tabs[0].element)
    await tabs[0].trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/board')
    await tabs[1].get('.workspace-tab-close').trigger('keydown', { key: 'Enter' })
    expect(router.currentRoute.value.path).toBe('/board')
    wrapper.unmount()
  })

  it('默认收起；展开与再次收起不销毁页签', async () => {
    const { wrapper } = await mountTabs(false)
    expect(wrapper.get('.workspace-tabs').classes()).toContain('is-collapsed')
    const tab = wrapper.get('.workspace-tab').element
    await wrapper.get('[aria-label="展开工作区"]').trigger('click')
    expect(wrapper.get('.workspace-tabs-rail').isVisible()).toBe(true)
    await wrapper.get('[aria-label="收起工作区"]').trigger('click')
    expect(wrapper.get('.workspace-tabs-rail').isVisible()).toBe(false)
    expect(wrapper.get('.workspace-tab').element).toBe(tab)
    wrapper.unmount()
  })

  it('折叠时可一键清空，整栏隐藏并交接焦点，同一菜单可重开且仍然折叠', async () => {
    const { wrapper, router } = await mountTabs(false)
    await router.push('/screen')
    await flushPromises()
    const clear = wrapper.get('[aria-label="清空页签"]')
    expect(clear.isVisible()).toBe(true)
    await clear.trigger('click')
    await flushPromises()
    expect(wrapper.find('.workspace-tabs').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.get('[aria-label="空工作区"]').element)
    await navigateWorkspaceMenu(router, '/screen', useAuthStore().menus)
    await flushPromises()
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(1)
    expect(wrapper.get('.workspace-tabs').classes()).toContain('is-collapsed')
    wrapper.unmount()
  })

  it('清空确认中禁用重复清空和单页关闭，取消后保留全部页面并恢复按钮', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()
    let finish!: (allowed: boolean) => void
    const requestLeave = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve }))
    const unregister = registerUnsavedHandler('/screen', { isDirty: () => true, requestLeave })
    const clear = wrapper.get('[aria-label="清空页签"]')
    await clear.trigger('click')
    await flushPromises()
    await clear.trigger('click')
    await wrapper.get('.workspace-tab-close').trigger('click')
    expect(requestLeave).toHaveBeenCalledOnce()
    expect(clear.attributes('aria-busy')).toBe('true')
    expect(wrapper.findAll('.workspace-tab-close').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    finish(false)
    await flushPromises()
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    expect(router.currentRoute.value.path).toBe('/screen')
    expect(clear.attributes('disabled')).toBeUndefined()
    unregister()
    wrapper.unmount()
  })

  it('标签图标消费最新授权菜单，缺失时使用统一文档图标', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()
    const icons = () => wrapper.findAllComponents(MenuIcon).map(icon => icon.props('name'))
    expect(icons()).toEqual(['DataBoard', 'Filter'])
    const auth = useAuthStore()
    auth.menus = [{ index: '/board', title: '每日榜单', icon: 'TrendCharts' }]
    await flushPromises()
    expect(icons()).toEqual(['TrendCharts', 'Document'])
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    wrapper.unmount()
  })
  it('容器缩窄只补滚被裁掉的距离，可见时不动，销毁时解除尺寸监听', async () => {
    let resize: (() => void) | undefined
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe() {}
      disconnect = disconnect
    })
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()
    const rail = wrapper.get('.workspace-tabs-rail').element as HTMLElement
    const current = wrapper.get('.workspace-tab.is-active').element as HTMLElement
    Object.defineProperty(rail, 'clientWidth', { configurable: true, value: 100 })
    Object.defineProperty(current, 'offsetLeft', { configurable: true, value: 180 })
    Object.defineProperty(current, 'offsetWidth', { configurable: true, value: 80 })
    rail.scrollLeft = 20
    resize!()
    expect(rail.scrollLeft).toBe(160)
    resize!()
    expect(rail.scrollLeft).toBe(160)
    Object.defineProperty(current, 'offsetLeft', { configurable: true, value: 60 })
    resize!()
    expect(rail.scrollLeft).toBe(60)
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalledOnce()
  })
  it('关闭聚焦的非当前标签后不切页，并恢复当前标签焦点', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()
    const close = wrapper.get('.workspace-tab:not(.is-active) .workspace-tab-close')
    ;(close.element as HTMLButtonElement).focus()
    await close.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/screen')
    expect(document.activeElement).toBe(wrapper.get('.workspace-tab.is-active').element)
    wrapper.unmount()
  })

  it('关闭确认期间防止重复请求，取消后标签和缓存入口保留', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()
    let resolve: (allowed: boolean) => void = () => {}
    const requestLeave = vi.fn(() => new Promise<boolean>(done => { resolve = done }))
    const unregister = registerUnsavedHandler('/screen', { isDirty: () => true, requestLeave })
    const close = wrapper.get('.workspace-tab.is-active .workspace-tab-close')
    await close.trigger('click')
    await close.trigger('click')
    expect(requestLeave).toHaveBeenCalledTimes(1)
    resolve(false)
    await flushPromises()
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    expect(router.currentRoute.value.path).toBe('/screen')
    expect(close.attributes('disabled')).toBeUndefined()
    unregister()
    wrapper.unmount()
  })

})
