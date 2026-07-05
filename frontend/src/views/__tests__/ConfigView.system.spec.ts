// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { ref, type Component } from 'vue'
import { useAuthStore } from '@/stores/auth'
import ConfigView from '@/views/ConfigView.vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import type { SettingGroup } from '@/api/data'

vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: { configTab: 'system' } }),
}))

vi.mock('@/api/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/data')>()
  return {
    ...actual,
    getSettingsView: vi.fn(),
    saveSettings: vi.fn(),
  }
})

vi.mock('@/api/scoreProfile', () => ({
  copyScoreProfile: vi.fn(),
  deleteIndicatorDef: vi.fn(),
  deleteScoreProfile: vi.fn(),
  getIndicatorRegistry: vi.fn(),
  getScoreProfile: vi.fn(),
  getScoreProfileVersions: vi.fn(),
  listScoreProfiles: vi.fn(),
  runScoreProfile: vi.fn(),
  saveIndicatorDef: vi.fn(),
  saveScoreProfile: vi.fn(),
  setScoreProfileVisibility: vi.fn(),
  setIndicatorCategories: vi.fn(),
  setIndicatorEnabled: vi.fn(),
}))

vi.mock('@/api/tradeProfile', () => ({
  deleteTradeProfile: vi.fn(),
  getTradeProfile: vi.fn(),
  getTradeProfileVersions: vi.fn(),
  listTradeProfiles: vi.fn(),
  previewConditions: vi.fn(),
  saveTradeProfile: vi.fn(),
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
    componentValueOf: vi.fn(),
    setComponentKnob: vi.fn(),
    componentSourceOf: vi.fn(),
    layerValuesOf: vi.fn(),
    componentLayerValuesOf: vi.fn(),
  }),
}))

import * as dataApi from '@/api/data'
import * as scoreApi from '@/api/scoreProfile'

const groups: SettingGroup[] = [
  {
    key: 'auth',
    label: '认证与防滥用',
    fields: [
      {
        path: 'auth.require_email_code',
        label: '注册需邮箱验证码',
        type: 'bool',
        value: true,
        default: true,
        overridden: false,
      },
      {
        path: 'auth.captcha_after_fails',
        label: '图形验证码触发失败次数',
        type: 'int',
        value: 3,
        default: 3,
        overridden: true,
        min: 1,
        max: 10,
      },
    ],
  },
  {
    key: 'audit',
    label: '审计设置',
    fields: [
      {
        path: 'audit.retention_days',
        label: '审计默认查询窗口(天)',
        type: 'int',
        value: 90,
        default: 90,
        overridden: false,
        min: 7,
        max: 365,
      },
    ],
  },
]

const stubs = {
  LayoutHost: {
    template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>',
  },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  TradeDatePicker: true,
  PageSegmented: true,
  PageSettingSection: { template: '<section><slot/></section>' },
  PageToggleRow: true,
  teleport: true,
}

async function mountView(role = 'system'): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = role === 'system' ? ['data-settings:manage'] : []
  auth.menusStatus = 'ready'
  auth.tenant = { id: 'tenant-a' }
  const wrapper = mount(ConfigView as Component, {
    attachTo: document.body,
    global: {
      plugins: [pinia, ElementPlus],
      stubs,
      directives: { permission: {} },
    },
  })
  await flushPromises()
  await wrapper.vm.$nextTick()
  return wrapper
}

function mockSettings(nextGroups = groups) {
  ;(dataApi.getSettingsView as ReturnType<typeof vi.fn>).mockResolvedValue({ groups: nextGroups })
  ;(dataApi.saveSettings as ReturnType<typeof vi.fn>).mockResolvedValue({ saved: 1 })
}

function saveButton(wrapper: VueWrapper) {
  const button = wrapper.findAll('button').find((node) => node.text() === '保存并生效')
  expect(button).toBeTruthy()
  return button!
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  mockSettings()
})

describe('ConfigView system tab', () => {
  it('按设置接口动态渲染认证和审计配置，且不加载指标注册表', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('系统设置')
    expect(wrapper.text()).toContain('认证与防滥用')
    expect(wrapper.text()).toContain('注册需邮箱验证码')
    expect(wrapper.text()).toContain('审计设置')
    expect(wrapper.text()).toContain('审计默认查询窗口(天)')
    expect(scoreApi.getIndicatorRegistry).not.toHaveBeenCalled()
  })

  it('保存时只提交改动字段，成功后重新加载设置', async () => {
    const wrapper = await mountView()
    const form = wrapper.findAllComponents(ConfigGroupForm).find((node) => node.props('group').key === 'audit')
    expect(form).toBeTruthy()
    form!.vm.$emit('update-field', 'audit.retention_days', 120)
    await flushPromises()
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(dataApi.saveSettings).toHaveBeenCalledWith({ 'audit.retention_days': 120 })
    expect(dataApi.getSettingsView).toHaveBeenCalledTimes(2)
  })

  it('保存失败时保留编辑值并展示错误态', async () => {
    ;(dataApi.saveSettings as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'))
    const wrapper = await mountView()
    wrapper.findComponent(ConfigGroupForm).vm.$emit('update-field', 'auth.require_email_code', false)
    await flushPromises()
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(dataApi.saveSettings).toHaveBeenCalledWith({ 'auth.require_email_code': false })
    expect(wrapper.text()).toContain('保存失败，已保留当前编辑值')
    expect(dataApi.getSettingsView).toHaveBeenCalledTimes(1)
  })

  it('字段超出范围时按控件范围钳定，保存提交修正后的合法值', async () => {
    mockSettings([
      {
        key: 'auth',
        label: '认证与防滥用',
        fields: [
          {
            path: 'auth.captcha_after_fails',
            label: '图形验证码触发失败次数',
            type: 'int',
            value: 99,
            default: 3,
            overridden: true,
            min: 1,
            max: 10,
          },
        ],
      },
    ])
    const wrapper = await mountView()
    expect(wrapper.findComponent(ConfigGroupForm).props('modelValue')).toMatchObject({
      'auth.captcha_after_fails': 10,
    })
    await saveButton(wrapper).trigger('click')
    await flushPromises()
    expect(dataApi.saveSettings).toHaveBeenCalledWith({ 'auth.captcha_after_fails': 10 })
  })

  it('无可维护配置时显示空态', async () => {
    mockSettings([])
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('暂无可维护配置')
  })

  it('无系统设置权限时显示权限态且不请求设置接口', async () => {
    const wrapper = await mountView('tenant_admin')
    expect(wrapper.text()).toContain('无权限维护系统设置')
    expect(dataApi.getSettingsView).not.toHaveBeenCalled()
  })
})
