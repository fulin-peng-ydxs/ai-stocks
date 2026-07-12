// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import WorkspaceTabs from '@/components/WorkspaceTabs.vue'
import WorkspaceRouteView from '@/components/WorkspaceRouteView.vue'
import { resetWorkspaceTabs } from '@/composables/useWorkspaceTabs'
import { useAuthStore } from '@/stores/auth'

describe('侧栏工作标签页', () => {
  it('记录访问页面，关闭当前页后切回相邻标签', async () => {
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
    await router.push('/screen')
    await flushPromises()

    expect(wrapper.findAll('.workspace-tab')).toHaveLength(2)
    await wrapper.find('.workspace-tab.is-active .workspace-tab-close').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/board')
    expect(wrapper.findAll('.workspace-tab')).toHaveLength(1)
  })
})
