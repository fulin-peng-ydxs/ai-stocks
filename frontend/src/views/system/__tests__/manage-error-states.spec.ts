// @vitest-environment jsdom
// 管理页 error+retry 闭环回归测试（Codex 二轮复审整改沉淀，防回退）：
//  · 角色页 loadAll(): 角色列表加载失败也须进 loadError 错误态（曾漏——loadRoles 在 catch 外）。
//  · 菜单页 loadResources(): 功能点列表加载失败须显"功能点加载失败+重试"（曾漏——静默结束 loading）。
// 用 vi.mock 精确复现"其它接口成功、目标接口失败"的窄路径，并验重试可恢复。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'
import type { Component } from 'vue'
import { useAuthStore } from '@/stores/auth'

// api 全量 mock（顶层解构导入须提供所有具名函数）
vi.mock('@/api/role', () => ({
  listRoles: vi.fn(), createRole: vi.fn(), updateRole: vi.fn(),
  deleteRole: vi.fn(), getRoleGrants: vi.fn(), setRoleGrants: vi.fn(),
}))
vi.mock('@/api/menu', () => ({
  listMenus: vi.fn(), listResources: vi.fn(), createMenu: vi.fn(), updateMenu: vi.fn(),
  deleteMenu: vi.fn(), reorderMenus: vi.fn(), createResource: vi.fn(),
  updateResource: vi.fn(), deleteResource: vi.fn(),
}))
// 布局组合式 mock：其 onMounted 会发 /layout 网络请求，jsdom 无 server 会挂起；且与本测无关。
// 消费方（LayoutHost / PageSettingsDrawer / PageSettingsTrigger）均已 stub，返回惰性对象即可。
vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {}, knobs: [], setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
    isDirty: false, resetAll: vi.fn(), componentValueOf: vi.fn(), setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(), layerValuesOf: vi.fn(), componentLayerValuesOf: vi.fn(),
  }),
}))
vi.mock('@/composables/usePageSettings', () => ({ usePageSettings: () => ({ reset: vi.fn() }) }))

import * as roleApi from '@/api/role'
import * as menuApi from '@/api/menu'
import RoleManageView from '@/views/system/RoleManageView.vue'
import MenuResourceView from '@/views/system/MenuResourceView.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', component: { template: '<div/>' } }],
})

// LayoutHost 渲染各具名插槽，使 #main（含错误态/功能点表）可见；其余重型子组件渲染子插槽即可。
const stubs = {
  LayoutHost: { template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>' },
  PageSettingsDrawer: true, PageSettingsTrigger: true, HelpTip: { template: '<span><slot/></span>' },
  IconPicker: true, PermissionTree: true,
}

async function mountView(comp: Component) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'system'          // 超管，避免 v-permission 干扰错误态渲染
  auth.permissions = []
  await router.push('/')        // memory history 须先导航，否则 isReady 永不 resolve
  await router.isReady()
  const w = mount(comp, {
    global: { plugins: [pinia, router, ElementPlus], stubs, directives: { permission: {} } },
  })
  await flushPromises()
  await w.vm.$nextTick()
  return w
}

const MENU = { id: 'm1', code: 'm1', title: '策略筛选', type: 'leaf', route_path: '/screen', icon: null, visible: 'login', sort: 10, parent_id: null, is_builtin: false, children: [] }
const BUILTIN_RESOURCE = {
  id: 'resource-1',
  menu_id: 'builtin',
  code: 'menu:view',
  name: '查看菜单',
  type: 'api',
  api_method: 'GET',
  api_path: '/api/menus',
  is_builtin: true,
}

describe('角色页 loadAll error+retry 闭环', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('系统内置标签统一展示在角色名称后面', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(roleApi.listRoles as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'system-role',
        code: 'system',
        name: '系统管理员',
        description: null,
        kind: 'system',
        is_builtin: true,
        is_locked: true,
        member_count: 2,
      },
    ])
    ;(roleApi.getRoleGrants as ReturnType<typeof vi.fn>).mockResolvedValue({
      menu_ids: [],
      resource_ids: [],
    })

    const w = await mountView(RoleManageView)
    const normalizedText = (selector: string) =>
      w.get(selector).element.textContent?.replace(/\s+/g, '')

    expect(normalizedText('.role-name')).toBe('系统管理员系统内置')
    expect(normalizedText('.rname')).toBe('系统管理员系统内置')
  })

  it('菜单/资源成功但角色列表失败 → 进错误态（回归：loadRoles 曾在 catch 外）', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(roleApi.listRoles as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const w = await mountView(RoleManageView)
    expect(w.text()).toContain('权限树加载失败')
    expect(w.find('.rm-error').exists()).toBe(true)
  })

  it('重试后接口恢复 → 错误态消失', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(roleApi.listRoles as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom')).mockResolvedValue([])
    const w = await mountView(RoleManageView)
    expect(w.find('.rm-error').exists()).toBe(true)
    await w.find('.rm-error button').trigger('click')
    await flushPromises()
    expect(w.find('.rm-error').exists()).toBe(false)
  })
})

describe('菜单页 loadResources error+retry 闭环', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('系统内置标签统一展示在菜单名称和功能码后面', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([
      { ...MENU, id: 'builtin', title: '系统菜单', is_builtin: true },
    ])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockResolvedValue([BUILTIN_RESOURCE])

    const w = await mountView(MenuResourceView)
    const normalizedText = (selector: string) =>
      w.get(selector).element.textContent?.replace(/\s+/g, '')

    expect(normalizedText('.mname')).toBe('系统菜单系统内置')
    expect(normalizedText('.el-table__body .mr-code-cell')).toBe('menu:view系统内置')
  })

  it('快速切换菜单时忽略较早返回的功能点响应', async () => {
    let resolveInitial!: (value: unknown[]) => void
    const initialResources = new Promise<unknown[]>((resolve) => {
      resolveInitial = resolve
    })
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([
      { ...MENU, id: 'initial', title: '初始菜单' },
      { ...MENU, id: 'builtin', title: '系统菜单', is_builtin: true },
    ])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockImplementation((menuId: string) => (
      menuId === 'initial' ? initialResources : Promise.resolve([BUILTIN_RESOURCE])
    ))

    const w = await mountView(MenuResourceView)
    const targetNode = w.findAll('[role="treeitem"]').find((node) => node.text().includes('系统菜单'))
    expect(targetNode).toBeTruthy()
    await targetNode!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('menu:view')

    resolveInitial([])
    await flushPromises()
    expect(w.text()).toContain('menu:view')
    expect(w.text()).not.toContain('该菜单暂无功能点')
  })

  it('菜单树只标记自定义节点，不重复展示系统内置和系统管理员可见性', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([
      { ...MENU, id: 'builtin', title: '系统菜单', is_builtin: true, visible: 'system' },
      { ...MENU, id: 'custom', title: '自定义菜单' },
    ])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockResolvedValue([])
    const w = await mountView(MenuResourceView)
    const menuTree = w.find('.mr-left')
    expect(menuTree.text()).toContain('自定义')
    expect(menuTree.text()).not.toContain('系统内置')
    expect(menuTree.text()).not.toContain('仅系统管理员')
  })

  it('功能点列表加载失败 → 显"功能点加载失败+重试"（回归：曾静默结束 loading）', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([MENU])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const w = await mountView(MenuResourceView)
    expect(w.text()).toContain('功能点加载失败')
  })

  it('重试后接口恢复 → 回正常态（无错误行）', async () => {
    ;(menuApi.listMenus as ReturnType<typeof vi.fn>).mockResolvedValue([MENU])
    ;(menuApi.listResources as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom')).mockResolvedValue([])
    const w = await mountView(MenuResourceView)
    expect(w.text()).toContain('功能点加载失败')
    const retryBtn = w.findAll('button').find((b) => b.text().includes('重试'))
    expect(retryBtn).toBeTruthy()
    await retryBtn!.trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('功能点加载失败')
  })
})
