// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import WorkspaceRouteView from '@/components/WorkspaceRouteView.vue'
import { resetWorkspaceTabs } from '@/composables/useWorkspaceTabs'
import { useAuthStore } from '@/stores/auth'

async function mountTabs() {
  resetWorkspaceTabs()
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.menusStatus = 'ready'
  auth.menus = [{ index: 'market', title: '市场研究', children: [
    { index: '/board', title: '每日榜单' },
    { index: '/screen', title: '策略筛选' },
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
  const wrapper = mount(host, { global: { plugins: [pinia, router, ElementPlus] } })
  return { wrapper, router }
}

describe('侧栏工作标签页', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('记录访问页面，关闭当前页后切回相邻标签', async () => {
    const { wrapper, router } = await mountTabs()
    await router.push('/screen')
    await flushPromises()

    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    await wrapper.find('.workspace-tab.is-active .workspace-tab-close').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/board')
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(1)
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
})
