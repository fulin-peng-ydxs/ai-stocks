// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import WorkspaceRouteView from '@/components/WorkspaceRouteView.vue'
import {
  removeWorkspaceTab,
  resetWorkspaceTabs,
  useWorkspaceTabs,
} from '@/composables/useWorkspaceTabs'
import { useAuthStore } from '@/stores/auth'

const DetailPage = defineComponent({
  name: 'DetailPage',
  setup() {
    const note = ref('')
    return { note }
  },
  template: '<input v-model="note" aria-label="研究笔记" />',
})

describe('工作区路由缓存', () => {
  beforeEach(resetWorkspaceTabs)

  it('同一页面组件的不同详情标签分别保留现场，关闭后重新进入会创建干净实例', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.menusStatus = 'ready'
    auth.menus = [{ index: 'market', title: '市场研究', children: [
      { index: '/detail', title: '个股详情' },
    ] }]
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/detail/:code', component: DetailPage, meta: { title: '个股详情' } },
      ],
    })
    await router.push('/detail/one')
    await router.isReady()
    const wrapper = mount(WorkspaceRouteView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    await wrapper.get('[aria-label="研究笔记"]').setValue('第一只股票的现场')

    await router.push('/detail/two')
    await flushPromises()
    await wrapper.get('[aria-label="研究笔记"]').setValue('第二只股票的现场')

    await router.push('/detail/one')
    await flushPromises()
    expect(wrapper.get('[aria-label="研究笔记"]').element).toHaveProperty(
      'value', '第一只股票的现场',
    )

    await router.push('/detail/two')
    await flushPromises()
    expect(removeWorkspaceTab('/detail/one', '/detail/two')).toBeUndefined()
    await nextTick()
    expect(useWorkspaceTabs().workspaceTabs.value.map((tab) => tab.key)).toEqual(['/detail/two'])

    await router.push('/detail/one')
    await flushPromises()
    expect(wrapper.get('[aria-label="研究笔记"]').element).toHaveProperty('value', '')
  })
})
