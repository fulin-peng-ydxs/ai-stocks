// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'
import { computed, defineComponent, h, inject, provide, reactive, ref, type Component, type ComputedRef } from 'vue'
import { useAuthStore } from '@/stores/auth'
import UserManageView from '@/views/system/UserManageView.vue'

vi.mock('@/api/user', () => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  setUserStatus: vi.fn(),
  resetUserPassword: vi.fn(),
  deleteUser: vi.fn(),
  listAssignableRoles: vi.fn(),
}))
vi.mock('@/api/tenant', () => ({
  listTenants: vi.fn(),
}))
vi.mock('@/api/dict', () => ({
  getPublicDictItems: vi.fn(),
}))
vi.mock('@/composables/useRemoteLayoutConfig', () => ({
  useRemoteLayoutConfig: () => ({
    effective: {},
    knobs: [],
    setKnob: vi.fn(),
    valueOf: vi.fn(),
    sourceOf: vi.fn(),
    isDirty: ref(false),
    resetAll: vi.fn(),
    componentValueOf: vi.fn((_slot: string, field: string) => (
      field === 'hiddenColumns' ? [] : field === 'pageSize' ? 50 : undefined
    )),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
  }),
}))
vi.mock('@/composables/usePageSettings', () => ({
  usePageSettings: () => ({
    settings: reactive({ defaultStatus: 'all' }),
    isDirty: ref(false),
    reset: vi.fn(),
  }),
}))

import * as userApi from '@/api/user'
import * as tenantApi from '@/api/tenant'
import * as dictApi from '@/api/dict'

const tableRowsKey = Symbol('tableRows')

const ElTableStub = defineComponent({
  name: 'ElTable',
  props: {
    data: { type: Array, default: () => [] },
  },
  setup(props, { slots }) {
    provide(tableRowsKey, computed(() => props.data as Record<string, unknown>[]))
    return () => h('div', { class: 'el-table' }, slots.default?.())
  },
})

const ElTableColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: {
    prop: { type: String, default: '' },
  },
  setup(props, { slots }) {
    const rows = inject<ComputedRef<Record<string, unknown>[]>>(tableRowsKey, computed(() => []))
    return () => h('div', { class: 'el-table-column' }, rows.value.map((row) => (
      h('div', { class: 'el-table-cell' }, slots.default ? slots.default({ row }) : String(row[props.prop] ?? ''))
    )))
  },
})

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', component: { template: '<div />' } }],
})

const stubs = {
  LayoutHost: {
    template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>',
  },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  HelpTip: { template: '<span><slot/></span>' },
  AppPagination: true,
  ElTable: ElTableStub,
  ElTableColumn: ElTableColumnStub,
}

function mockHappyApis() {
  ;(userApi.listUsers as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [{
      id: 'u1',
      tenant_id: 'default',
      account: 'debug_system',
      email: 'debug@example.com',
      role_code: 'system',
      roles: ['custom_reviewer', 'normal', 'system'],
      role_names: {
        custom_reviewer: '复核员',
        normal: '普通用户',
        system: '系统管理员',
      },
      status: 'locked',
      perm_ver: 1,
      last_login_at: null,
      created_at: '2026-07-12T10:00:00+08:00',
    }],
    total: 1,
  })
  ;(userApi.listAssignableRoles as ReturnType<typeof vi.fn>).mockResolvedValue([
    { id: 'system', code: 'system', name: '系统管理员', kind: 'system', is_builtin: true, is_locked: true },
    { id: 'normal', code: 'normal', name: '普通用户', kind: 'normal', is_builtin: true, is_locked: false },
  ])
  ;(tenantApi.listTenants as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [{ id: 'default', name: '默认租户', status: 'active' }],
    total: 1,
  })
  ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>)
    .mockResolvedValueOnce({
      type_code: 'role_type',
      fallback: false,
      version: 'v1',
      items: [
        { id: 'r1', type_code: 'role_type', code: 'system', label: '系统管理员', color: '#F56C6C', enabled: true, sort: 10 },
        { id: 'r2', type_code: 'role_type', code: 'normal', label: '普通用户', color: '#67C23A', enabled: true, sort: 30 },
      ],
    })
    .mockResolvedValueOnce({
      type_code: 'user_status',
      fallback: false,
      version: 'v1',
      items: [
        { id: 's1', type_code: 'user_status', code: 'locked', label: '字典锁定', color: '#F56C6C', enabled: true, sort: 30 },
      ],
    })
}

async function mountView(role: 'system' | 'tenant_admin' = 'system'): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = [
    'user:list',
    'user:create',
    'user:update',
    'user:disable',
    'user:reset-password',
    'user:delete',
  ]
  auth.menusStatus = 'ready'
  auth.tenant = { id: 'default' }
  auth.user = { id: 'u-admin', account: 'debug_system' }
  await router.push('/')
  await router.isReady()
  const wrapper = mount(UserManageView as Component, {
    global: {
      plugins: [pinia, router, ElementPlus],
      stubs,
      directives: { permission: {} },
    },
  })
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  mockHappyApis()
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('UserManageView 字典颜色', () => {
  it('角色和用户状态标签优先使用字典颜色', async () => {
    const wrapper = await mountView()
    expect(dictApi.getPublicDictItems).toHaveBeenCalledWith('role_type')
    expect(dictApi.getPublicDictItems).toHaveBeenCalledWith('user_status')
    expect(wrapper.html()).toContain('--el-tag-text-color: #F56C6C')
    expect(wrapper.html()).toContain('--el-tag-text-color: #67C23A')
    expect(wrapper.text()).toContain('字典锁定')
    expect(wrapper.text()).not.toContain('已锁定')
  })

  it('字典读取失败时保留原标签类型和文案', async () => {
    ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>).mockReset()
    ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('系统管理员')
    expect(wrapper.text()).toContain('锁定')
    expect(wrapper.text()).not.toContain('已锁定')
    expect(wrapper.html()).not.toContain('--el-tag-text-color')
  })

  it('角色按字典顺序优先排列，并使用列表返回的自定义角色名称', async () => {
    const wrapper = await mountView()
    const labels = wrapper.findAll('.role-tag').map((tag) => tag.text())
    expect(labels).toEqual(['系统管理员', '普通用户', '复核员'])
    expect(wrapper.text()).not.toContain('custom_reviewer')
  })

  it('角色或租户依赖失败时保留用户列表并显示局部重试态', async () => {
    ;(userApi.listAssignableRoles as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('roles failed'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('筛选与表单选项加载不完整')
    expect(wrapper.text()).toContain('roles failed')
    expect(wrapper.text()).toContain('debug_system')
  })
})

describe('UserManageView 系统管理员保护', () => {
  it('租户管理员不能操作系统管理员用户', async () => {
    const wrapper = await mountView('tenant_admin')
    const rowActions = wrapper.get('[data-testid="user-row-actions-debug_system"]')
    const buttons = rowActions.findAll('button')
    expect(buttons.map((button) => button.text())).toEqual(['编辑', '重置密码', '解锁', '更多'])
    expect(buttons.slice(0, 3).every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })
})
