// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import TopNavigation from '@/components/TopNavigation.vue'
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
})
