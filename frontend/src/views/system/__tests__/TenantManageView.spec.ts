// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'
import { computed, defineComponent, h, inject, provide, reactive, ref, type Component, type ComputedRef } from 'vue'
import { useAuthStore } from '@/stores/auth'
import TenantManageView from '@/views/system/TenantManageView.vue'

vi.mock('@/api/tenant', () => ({
  listTenants: vi.fn(),
  createTenant: vi.fn(),
  updateTenant: vi.fn(),
  setTenantStatus: vi.fn(),
  deleteTenant: vi.fn(),
}))
vi.mock('@/api/user', () => ({
  listUsers: vi.fn(),
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
  ;(tenantApi.listTenants as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [{
      id: 'tenant-a',
      name: '租户A',
      status: 'disabled',
      admin_user_id: null,
      admin_account: null,
      user_count: 0,
      created_at: '2026-07-12T10:00:00+08:00',
    }],
    total: 1,
  })
  ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>).mockResolvedValue({
    type_code: 'user_status',
    fallback: false,
    version: 'v1',
    items: [
      { id: 's1', type_code: 'user_status', code: 'active', label: '字典启用', color: '#67C23A', enabled: true, sort: 10 },
      { id: 's2', type_code: 'user_status', code: 'disabled', label: '字典停用', color: '#909399', enabled: true, sort: 20 },
      { id: 's3', type_code: 'user_status', code: 'locked', label: '锁定', color: '#F56C6C', enabled: true, sort: 30 },
    ],
  })
}

async function mountView(): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'system'
  auth.permissions = ['tenant:list', 'tenant:create', 'tenant:update', 'tenant:disable', 'tenant:delete']
  auth.menusStatus = 'ready'
  auth.tenant = { id: 'default' }
  auth.user = { id: 'u-admin', account: 'debug_system' }
  await router.push('/')
  await router.isReady()
  const wrapper = mount(TenantManageView as Component, {
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

describe('TenantManageView 状态字典复用', () => {
  it('租户状态文字和颜色使用 user_status 字典', async () => {
    const wrapper = await mountView()
    expect(dictApi.getPublicDictItems).toHaveBeenCalledWith('user_status')
    expect(wrapper.text()).toContain('字典停用')
    expect(wrapper.text()).not.toContain('已停用')
    expect(wrapper.html()).toContain('--el-tag-text-color: #909399')
  })

  it('字典读取失败时保留租户状态原文案', async () => {
    ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>).mockReset()
    ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('停用')
    expect(wrapper.text()).not.toContain('已停用')
    expect(wrapper.html()).not.toContain('--el-tag-text-color')
  })
})
