// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { ref, type Component } from 'vue'
import { useAuthStore } from '@/stores/auth'
import ConfigView from '@/views/ConfigView.vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import HelpHint from '@/components/HelpHint.vue'
import type { MailStatus, SettingGroup } from '@/api/data'

const routeState = vi.hoisted(() => ({
  meta: { configTab: 'system' },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: routeState.meta }),
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
  browseScoreProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
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
  browseTradeProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyTradeProfile: vi.fn(),
  deleteTradeProfile: vi.fn(),
  getTradeProfile: vi.fn(),
  getTradeProfileVersions: vi.fn(),
  listTradeProfiles: vi.fn(),
  previewConditions: vi.fn(),
  saveTradeProfile: vi.fn(),
  setTradeProfileVisibility: vi.fn(),
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
import * as tradeApi from '@/api/tradeProfile'

const groups: SettingGroup[] = [
  {
    key: 'datasource',
    label: '数据源',
    fields: [
      {
        path: 'datasource.concurrent_jobs',
        label: '并发采集任务数',
        type: 'int',
        value: 2,
        default: 2,
        overridden: false,
        min: 1,
        max: 10,
      },
    ],
  },
  {
    key: 'cost',
    label: '回测成本',
    fields: [
      {
        path: 'backtest.cost.slippage',
        label: '滑点',
        type: 'number',
        value: 0.002,
        default: 0.002,
        overridden: false,
        min: 0,
        max: 0.1,
      },
    ],
  },
  {
    key: 'auth',
    label: '认证与防滥用',
    fields: [
      {
        path: 'auth.require_email_code',
        label: '注册需邮箱验证码',
        desc: '开启后自助注册必须提交真实邮箱验证码',
        type: 'bool',
        value: true,
        default: true,
        overridden: false,
      },
      {
        path: 'auth.captcha_after_fails',
        label: '图形验证码强制失败次数',
        type: 'int',
        value: 3,
        default: 3,
        overridden: true,
        min: 1,
        max: 10,
      },
      {
        path: 'auth.login_rate_per_min',
        label: '登录限流(次/分钟)',
        type: 'int',
        value: 20,
        default: 20,
        overridden: false,
        min: 1,
        max: 120,
      },
      {
        path: 'auth.register_rate_per_hour',
        label: '注册限流(次/小时)',
        type: 'int',
        value: 10,
        default: 10,
        overridden: false,
        min: 1,
        max: 120,
      },
      {
        path: 'auth.email_code_rate_per_hour',
        label: '邮箱验证码限流(次/小时·单邮箱)',
        type: 'int',
        value: 6,
        default: 6,
        overridden: false,
        min: 1,
        max: 120,
      },
    ],
  },
  {
    key: 'audit',
    label: '审计设置',
    fields: [
      {
        path: 'audit.retention_days',
        label: '审计保留期/默认查询窗口(天)',
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

async function mountView(role = 'system', permissions?: string[]): Promise<VueWrapper> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = role
  auth.permissions = permissions ?? (role === 'system' ? ['data-settings:manage'] : [])
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

function mockSettings(nextGroups = groups, mailStatus?: MailStatus) {
  ;(dataApi.getSettingsView as ReturnType<typeof vi.fn>).mockResolvedValue({
    groups: nextGroups, mail_status: mailStatus,
  })
  ;(dataApi.saveSettings as ReturnType<typeof vi.fn>).mockResolvedValue({ saved: 1 })
}

function saveButton(wrapper: VueWrapper) {
  const button = wrapper.findAll('button').find((node) => node.text() === '保存并生效')
  expect(button).toBeTruthy()
  return button!
}

beforeEach(() => {
  vi.clearAllMocks()
  routeState.meta.configTab = 'system'
  localStorage.clear()
  document.body.innerHTML = ''
  mockSettings()
  ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
    items: [
      {
        key: 'rs_pct',
        name_cn: '相对强度',
        dtype: 'number',
        enabled: true,
        params: [],
      },
    ],
  })
})

describe('ConfigView system tab', () => {
  it('按设置接口动态渲染认证和审计配置，且不加载指标注册表', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('系统设置')
    expect(wrapper.text()).toContain('访问安全')
    expect(wrapper.text()).toContain('数据治理')
    expect(wrapper.text()).toContain('研究运行')
    expect(wrapper.text()).not.toContain('认证与审计')
    expect(wrapper.text()).not.toContain('平台配置')
    expect(wrapper.text()).toContain('认证与防滥用')
    expect(wrapper.text()).toContain('登录保护')
    expect(wrapper.text()).toContain('注册校验')
    expect(wrapper.text()).toContain('邮箱验证码发送')
    expect(wrapper.text()).toContain('注册需邮箱验证码')
    expect(wrapper.text()).toContain('审计设置')
    expect(wrapper.text()).toContain('日志留存')
    expect(wrapper.text()).toContain('审计保留期/默认查询窗口(天)')
    const helpTexts = wrapper.findAllComponents(HelpHint).map((node) => String(node.props('text')))
    expect(helpTexts.some((text) => text.includes('默认值：3'))).toBe(true)
    expect(helpTexts.some((text) => text.includes('允许范围：1 - 10'))).toBe(true)
    expect(helpTexts.some((text) => text.includes('开启后自助注册必须提交真实邮箱验证码'))).toBe(true)
    expect(scoreApi.getIndicatorRegistry).not.toHaveBeenCalled()
  })

  it('系统设置抽屉的默认折叠候选只包含当前业务面板', async () => {
    const wrapper = await mountView()
    const drawer = wrapper.findComponent({ name: 'PageSettingsDrawer' })
    const overrides = drawer.props('componentMetaOverrides') as {
      configPanel?: { collapseSections?: { key: string; label: string }[] }
    }
    const labels = overrides.configPanel?.collapseSections?.map((section) => section.label) ?? []
    expect(labels).toEqual(['认证与防滥用', '登录保护', '注册校验', '邮箱验证码发送'])
    expect(labels).not.toContain('数据源')
    expect(labels).not.toContain('回测成本')
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
            label: '图形验证码强制失败次数',
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

  it('邮件 mode=ready 时开关下显示已就绪', async () => {
    mockSettings(groups, {
      enabled: true, username_masked: 'pe***@gmail.com', password_set: true, mode: 'ready', ready: true,
    })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('真实发信已就绪')
  })

  it('邮件 mode=incomplete 时提示发码会失败（非只写日志）', async () => {
    mockSettings(groups, {
      enabled: true, username_masked: '', password_set: false, mode: 'incomplete', ready: false,
    })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('真实发信已开启但配置不完整，发码会失败')
    expect(wrapper.text()).not.toContain('只写日志')
  })

  it('邮件 mode=disabled 时提示只写日志不真发', async () => {
    mockSettings(groups, {
      enabled: false, username_masked: '', password_set: false, mode: 'disabled', ready: false,
    })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('验证码只写日志不真发')
  })
})

describe('ConfigView trade tab', () => {
  it('初始化「我的」买卖方案时使用 profile_ref 拉详情', async () => {
    routeState.meta.configTab = 'trade'
    ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'ui6_trade_mine',
        profile_ref: 'asset:trade_profile:tenant-a:owner-a:ui6_trade_mine',
        name: 'UI6我的买卖方案',
        version: 1,
        is_preset: false,
        visibility: 'private',
        source: 'mine',
        readonly: false,
      },
    ])
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'ui6_trade_mine',
      profile_ref: 'asset:trade_profile:tenant-a:owner-a:ui6_trade_mine',
      name: 'UI6我的买卖方案',
      version: 1,
      is_preset: false,
      visibility: 'private',
      source: 'mine',
      readonly: false,
      buy_tree: { op: 'AND', children: [] },
      sell_tree: { op: 'OR', children: [] },
      backstop: {},
    })

    // normal 角色补 trade-profile:view 权限码，使 canViewTradeProfiles=true（hasPermission 非 system 需命中授权码）
    const wrapper = await mountView('normal', ['trade-profile:view'])

    // 初始化选中「我的」首项，且以 profile_ref（非裸 id）拉详情
    expect(tradeApi.listTradeProfiles).toHaveBeenCalledWith('mine')
    expect(tradeApi.getTradeProfile).toHaveBeenCalledWith(
      'asset:trade_profile:tenant-a:owner-a:ui6_trade_mine',
    )
    expect(tradeApi.getTradeProfile).not.toHaveBeenCalledWith('ui6_trade_mine')
    expect(wrapper.text()).toContain('UI6我的买卖方案')
  })
})
