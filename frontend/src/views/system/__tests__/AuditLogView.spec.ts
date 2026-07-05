// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { ref, type Component } from 'vue'
import { useAuthStore } from '@/stores/auth'
import AuditLogView from '@/views/system/AuditLogView.vue'

vi.mock('@/api/audit', () => ({
  listAuditLogs: vi.fn(),
  getAuditSummary: vi.fn(),
  getAuditDetail: vi.fn(),
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
    componentValueOf: vi.fn((_slot: string, field: string) => (field === 'pageSize' ? 50 : [])),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
  }),
}))

import * as auditApi from '@/api/audit'
import * as dictApi from '@/api/dict'

const stubs = {
  LayoutHost: {
    template: '<div><slot name="action"/><slot name="summary"/><slot name="filters"/><slot name="auditTable"/><slot name="overlays"/></div>',
  },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  HelpTip: { template: '<span><slot/></span>' },
}

const row = {
  id: 'a1',
  event_time: '2026-07-05T14:21:30+00:00',
  created_at: '2026-07-05T14:21:31+00:00',
  event_category: 'rbac',
  event_type: 'permission',
  action: 'grant',
  result: 'success',
  status: 'completed',
  tenant_id: 'tenant-a',
  actor_user_id: 'u1',
  actor_account: 'admin',
  resource_code: 'audit:view',
  target_type: 'role',
  target_id: 'role1',
  target_label: '角色：管理员',
  ip: '127.0.0.1',
  method: 'POST',
  path: '/api/roles/role1/grants',
  duration_ms: 42,
  error_summary: null,
  context: { request_id: 'req1', action: 'grant' },
}

function mockHappyApis() {
  ;(dictApi.getPublicDictItems as ReturnType<typeof vi.fn>)
    .mockResolvedValueOnce({ items: [{ code: 'rbac', label: '权限' }], fallback: false, version: 'v1', type_code: 'audit_event_type' })
    .mockResolvedValueOnce({ items: [{ code: 'success', label: '成功' }], fallback: false, version: 'v1', type_code: 'audit_result' })
  ;(auditApi.listAuditLogs as ReturnType<typeof vi.fn>).mockResolvedValue({
    list: [row],
    total: 1,
    page: 1,
    page_size: 50,
  })
  ;(auditApi.getAuditSummary as ReturnType<typeof vi.fn>).mockResolvedValue({
    total: 1,
    success: 1,
    failed: 0,
    by_category: { rbac: 1, security: 0 },
    by_type: { permission: 1 },
    by_result: { success: 1 },
    by_status: { completed: 1 },
  })
  ;(auditApi.getAuditDetail as ReturnType<typeof vi.fn>).mockResolvedValue(row)
}

async function mountView(role = 'system') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = role === 'system' || role === 'tenant_admin' ? ['audit:view'] : []
  auth.menusStatus = 'ready'
  auth.tenant = { id: 'tenant-a' }
  const wrapper = mount(AuditLogView as Component, {
    global: {
      plugins: [pinia, ElementPlus],
      stubs,
    },
  })
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  mockHappyApis()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AuditLogView', () => {
  it('加载摘要、筛选项和审计列表', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('审计日志')
    expect(wrapper.text()).toContain('范围事件')
    expect(wrapper.text()).toContain('角色：管理员')
    expect(auditApi.listAuditLogs).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
  })

  it('查询时把筛选条件透传给审计列表和摘要', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[placeholder="处理人"]').setValue('admin')
    const query = wrapper.findAll('button').find((button) => button.text() === '查询')
    expect(query).toBeTruthy()
    await query!.trigger('click')
    await flushPromises()
    expect(auditApi.listAuditLogs).toHaveBeenLastCalledWith(expect.objectContaining({ actor_keyword: 'admin' }))
    expect(auditApi.getAuditSummary).toHaveBeenLastCalledWith(expect.objectContaining({ actor_keyword: 'admin' }))
  })

  it('空列表显示空态并可重置筛选', async () => {
    ;(auditApi.listAuditLogs as ReturnType<typeof vi.fn>).mockResolvedValue({ list: [], total: 0, page: 1, page_size: 50 })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('暂无审计记录')
    expect(wrapper.text()).toContain('重置筛选')
  })

  it('列表加载失败显示错误态，重试后恢复', async () => {
    ;(auditApi.listAuditLogs as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ list: [row], total: 1, page: 1, page_size: 50 })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('审计服务暂不可用')
    const retry = wrapper.findAll('button').find((button) => button.text() === '重试')
    expect(retry).toBeTruthy()
    await retry!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('角色：管理员')
  })

  it('点击详情打开只读抽屉并展示脱敏上下文', async () => {
    const wrapper = await mountView()
    const detail = wrapper.findAll('button').find((button) => button.text() === '详情')
    expect(detail).toBeTruthy()
    await detail!.trigger('click')
    await flushPromises()
    expect(auditApi.getAuditDetail).toHaveBeenCalledWith('a1')
    expect(wrapper.text()).toContain('事件上下文')
    expect(wrapper.text()).toContain('req1')
  })

  it('无审计权限时不请求审计接口并显示权限态', async () => {
    const wrapper = await mountView('normal')
    expect(wrapper.text()).toContain('无权限查看审计日志')
    expect(auditApi.listAuditLogs).not.toHaveBeenCalled()
    expect(auditApi.getAuditSummary).not.toHaveBeenCalled()
  })

  it('租户管理员不展示跨租户过滤入口', async () => {
    const wrapper = await mountView('tenant_admin')
    expect(wrapper.find('input[placeholder="租户 ID"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已强制限定本租户')
  })

  it('自动刷新按间隔静默刷新，卸载后清理定时器', async () => {
    vi.useFakeTimers()
    localStorage.setItem(
      'ai-stocks:page-settings:audit-log',
      JSON.stringify({
        autoRefreshEnabled: true,
        filters: {
          start_time: '',
          end_time: '',
          event_category: '',
          result: '',
          status: '',
          resource_code: '',
          actor_keyword: '',
          target_keyword: '',
          tenant_id: '',
        },
      }),
    )
    const wrapper = await mountView()
    const initialCalls = (auditApi.listAuditLogs as ReturnType<typeof vi.fn>).mock.calls.length
    await vi.advanceTimersByTimeAsync(30_000)
    await flushPromises()
    expect(auditApi.listAuditLogs).toHaveBeenCalledTimes(initialCalls + 1)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(auditApi.listAuditLogs).toHaveBeenCalledTimes(initialCalls + 1)
  })
})
