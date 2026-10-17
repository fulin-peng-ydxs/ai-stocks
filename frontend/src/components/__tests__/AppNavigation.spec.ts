// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '@/App.vue'
import { useAuthStore } from '@/stores/auth'
import { useAppNavigation } from '@/composables/useAppNavigation'
import { resetWorkspaceTabs } from '@/composables/useWorkspaceTabs'

afterEach(() => {
  useAppNavigation().navigationMode.value = 'sidebar-tabs'
  resetWorkspaceTabs()
})

async function mountShell() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.menusStatus = 'ready'
  auth.menus = [{ index: 'market', title: '市场研究', children: [
    { index: '/stocks', title: '个股行情' },
  ] }]
  let pageMounts = 0
  const page = defineComponent({
    name: 'TestResearchPage',
    setup() {
      pageMounts += 1
      return { note: ref('') }
    },
    template: '<input v-model="note" aria-label="研究笔记" />',
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/stocks', component: page, meta: { title: '个股行情' } },
    { path: '/stocks/:code', component: page, meta: { title: '个股详情' } },
  ] })
  await router.push('/stocks')
  const wrapper = mount(App, { global: {
    plugins: [pinia, router],
    renderStubDefaultSlot: true,
    stubs: {
      BrandMark: true, SideMenu: true, TopNavigation: true, WorkspaceTabs: true,
      AppIconButton: true, AppStatusDot: true, AppOverflowTooltipHost: true,
      PageSegmented: true, PageDrawer: true, SettingsGroup: true, TradeDisciplineQuickCard: true,
      ElAside: true, ElIcon: true, ElButton: true, ElPopover: true,
      ElHeader: true, ElMain: true, ElContainer: true, ElSlider: true,
    },
  } })
  await flushPromises()
  return { wrapper, router, auth, pageMounts: () => pageMounts }
}

describe('应用导航外壳', () => {
  it('品牌在独立侧栏，面包屑跟随详情路由且不重复菜单页标题', async () => {
    const { wrapper, router, auth } = await mountShell()
    expect(wrapper.find('.aside .aside-brand brand-mark-stub').exists()).toBe(true)
    expect(wrapper.find('.topbar .topbar-brand').exists()).toBe(false)
    expect(wrapper.findAll('.shell-breadcrumb li').map((item) => item.text()))
      .toEqual(['市场研究', '个股行情'])
    auth.menus[0].children![0].title = '自定义行情'
    await nextTick()
    expect(wrapper.findAll('.shell-breadcrumb li').map((item) => item.text()))
      .toEqual(['市场研究', '自定义行情'])
    await router.push('/stocks/600000.SH')
    await flushPromises()
    expect(wrapper.findAll('.shell-breadcrumb li').map((item) => item.text()))
      .toEqual(['市场研究', '自定义行情', '个股详情'])
    expect(wrapper.get('[aria-current="page"]').text()).toBe('个股详情')
    wrapper.unmount()
  })

  it('切换导航只移动品牌呈现，保留工作页面实例和输入现场', async () => {
    const { wrapper, pageMounts } = await mountShell()
    const input = wrapper.get('input')
    await input.setValue('保留研究现场')
    const originalMounts = pageMounts()
    const originalTabs = wrapper.get('workspace-tabs-stub').element
    useAppNavigation().navigationMode.value = 'dual-topbar'
    await nextTick()
    expect(wrapper.find('.aside').exists()).toBe(false)
    expect(wrapper.find('.topbar .topbar-brand brand-mark-stub').exists()).toBe(true)
    expect(wrapper.find('.shell-breadcrumb').exists()).toBe(false)
    expect(wrapper.get('workspace-tabs-stub').element).toBe(originalTabs)
    expect(wrapper.findAll('top-navigation-stub')).toHaveLength(2)
    expect(pageMounts()).toBe(originalMounts)
    expect(wrapper.get('input').element).toHaveProperty('value', '保留研究现场')
    useAppNavigation().navigationMode.value = 'sidebar-tabs'
    await nextTick()
    expect(wrapper.get('input').element).toBe(input.element)
    expect(wrapper.get('workspace-tabs-stub').element).toBe(originalTabs)
    wrapper.unmount()
  })

  it('权限加载和失败时不展示旧菜单层级，恢复后重新显示', async () => {
    const { wrapper, auth } = await mountShell()
    auth.menusStatus = 'loading'
    await nextTick()
    expect(wrapper.get('.shell-breadcrumb').text()).toBe('权限加载中…')
    auth.menusStatus = 'error'
    await nextTick()
    expect(wrapper.get('.shell-breadcrumb').text()).toBe('权限加载失败')
    auth.menusStatus = 'ready'
    await flushPromises()
    expect(wrapper.findAll('.shell-breadcrumb li')).toHaveLength(2)
    wrapper.unmount()
  })
})
