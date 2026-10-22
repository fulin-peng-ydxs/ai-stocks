// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { ref, h, defineComponent, type Component } from 'vue'
import { useAuthStore } from '@/stores/auth'
import ConfigView from '@/views/ConfigView.vue'
import ConfigGroupForm from '@/components/config/ConfigGroupForm.vue'
import AppDataTable from '@/components/AppDataTable.vue'
import AppTabToolbar from '@/components/AppTabToolbar.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import HelpHint from '@/components/HelpHint.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import type { MailStatus, SettingGroup } from '@/api/data'

const routeState = vi.hoisted(() => ({
  meta: { configTab: 'system' },
}))

vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => ({ meta: routeState.meta }),
}))

vi.mock('@/api/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/data')>()
  return {
    ...actual,
    getSettingsView: vi.fn(),
    getSources: vi.fn(async () => ({ sources: [] })),
    testSources: vi.fn(),
    saveSettings: vi.fn(),
    resetSettings: vi.fn(),
  }
})

vi.mock('@/api/scoreProfile', () => ({
  browseScoreProfiles: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 20, source: 'preset' })),
  copyScoreProfile: vi.fn(),
  deleteIndicatorDef: vi.fn(),
  deleteScoreProfile: vi.fn(),
  getIndicatorRegistry: vi.fn(),
  getIndicatorReferences: vi.fn(),
  getScoreProfile: vi.fn(),
  getScoreProfileVersions: vi.fn(),
  listScoreProfiles: vi.fn(),
  runScoreProfile: vi.fn(),
  previewIndicatorDef: vi.fn(),
  saveIndicatorDef: vi.fn(),
  updateIndicatorDef: vi.fn(),
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

// 编辑器区真实 el-select（评分指标/买卖条件树）在 jsdom 下经「加载查看」注入临时项 +
// 编辑器载入会触发 ElSelect 递归更新循环（真实浏览器正常，已复验）。本 spec 断言走
// findComponent + emit + text()/api 调用，不依赖 el-select 的 DOM 交互，故全局 stub 掉。
const ElSelectStub = defineComponent({
  name: 'ElSelect',
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  setup(props, { slots }) {
    return () => h('div', { 'data-model-value': String(props.modelValue ?? '') }, slots.default?.())
  },
})
const ElOptionStub = defineComponent({
  name: 'ElOption',
  props: ['label', 'value'],
  setup(props, { slots }) {
    return () => h('span', { 'data-value': String(props.value ?? '') }, slots.default?.() ?? String(props.label ?? ''))
  },
})

const stubs = {
  LayoutHost: {
    template: '<div><slot name="action"/><slot name="main"/><slot name="overlays"/></div>',
  },
  PageSettingsDrawer: true,
  PageSettingsTrigger: true,
  TradeDatePicker: true,
  PageSegmented,
  PageSettingSection: { template: '<section><slot/></section>' },
  PageToggleRow: true,
  ElSelect: ElSelectStub,
  ElOption: ElOptionStub,
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
  vi.mocked(dataApi.getSettingsView).mockReset()
  ;(dataApi.getSettingsView as ReturnType<typeof vi.fn>).mockResolvedValue({
    groups: nextGroups, mail_status: mailStatus,
  })
  ;(dataApi.saveSettings as ReturnType<typeof vi.fn>).mockResolvedValue({ saved: 1 })
  vi.mocked(dataApi.resetSettings).mockResolvedValue({ reset: 1 })
}

function saveButton(wrapper: VueWrapper) {
  const button = wrapper.findAll('button').find((node) => node.text() === '保存并生效')
  expect(button).toBeTruthy()
  return button!
}

function sysButton(wrapper: VueWrapper, label: string) {
  return wrapper.findComponent(AppTabToolbar).find('.app-tab-toolbar__actions')
    .findAll('button').find((button) => button.text() === label)!
}
async function selectSysTab(wrapper: VueWrapper, label: string) {
  await wrapper.findAll('[role="tab"]').find((node) => node.text() === label)!.trigger('click')
  await flushPromises()
}
function sysForm(wrapper: VueWrapper, key: string) {
  return wrapper.findAllComponents(ConfigGroupForm).find((node) => node.props('group').key === key)!
}
function settingsWith(values: Record<string, unknown>, clearOverrides = false) {
  return { groups: groups.map((group) => ({ ...group, fields: group.fields.map((field) => ({
    ...field, value: field.path in values ? values[field.path] : field.value,
    overridden: clearOverrides ? false : field.overridden,
  })) })) }
}

beforeEach(() => {
  vi.clearAllMocks()
  routeState.meta.configTab = 'system'
  localStorage.clear()
  document.body.innerHTML = ''
  mockSettings()
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
  vi.mocked(dataApi.getSources).mockResolvedValue({ sources: [] })
  ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
    calculation_context: { default_period: 'day', supported_periods: ['day'] },
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

describe('ConfigView tech tab', () => {
  it('使用紧凑标签展示K线指标周期，非K线字段不伪装成日K', async () => {
    routeState.meta.configTab = 'tech'
    ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
      calculation_context: { default_period: 'day', supported_periods: ['day'] },
      items: [
        { key: 'macd_diff', name_cn: 'MACD DIFF', dtype: 'number', enabled: true,
          params: [], categories: ['趋势'], calculation_period: 'day' },
        { key: 'close', name_cn: '股价', dtype: 'number', enabled: true,
          params: [], categories: ['价格'], calculation_period: null },
      ],
    })
    const wrapper = await mountView('normal', ['indicator:registry'])

    expect(wrapper.text()).toContain('计算周期')
    const periods = wrapper.findAll('[data-testid="indicator-calculation-period"]')
    expect(periods).toHaveLength(1)
    expect(periods[0].text()).toBe('日K')
    expect(periods[0].text()).not.toContain('周K')
    expect(wrapper.findAll('.el-tag').some((tag) => tag.text() === '日K')).toBe(true)
    wrapper.unmount()
  })

  it('分类维护复用可创建的响应式选择器', async () => {
    routeState.meta.configTab = 'tech'
    ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{
        key: 'above_ma',
        name_cn: '站上均线',
        dtype: 'bool',
        enabled: true,
        params: [],
        categories: ['趋势', '均线', '位置', '强度'],
        desc: '测试指标',
        is_builtin: true,
      }],
    })
    const wrapper = await mountView('normal', ['indicator:registry'])

    const select = wrapper.findAllComponents(AppFilterSelect)
      .find((node) => node.props('ariaLabel') === '维护指标分类')
    expect(select).toBeTruthy()
    if (!select) throw new Error('未渲染指标分类选择器')
    expect(select.props('allowCreate')).toBe(true)
    expect(select.props('defaultFirstOption')).toBe(true)
    expect(select.props('size')).toBe('small')
    wrapper.unmount()
  })

  it('默认折叠参数预设并可显式展开', async () => {
    routeState.meta.configTab = 'tech'
    ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
      templates: [],
      items: [
        { key: 'ma', name_cn: '移动平均线', dtype: 'number', enabled: true, params: [],
          categories: ['均线'], desc: '', is_builtin: true, layer: 'metric' },
        { key: 'ma20', name_cn: 'MA20快捷项', dtype: 'number', enabled: true, params: [],
          categories: ['均线'], desc: '', is_builtin: true, layer: 'preset', parent_key: 'ma',
          preset_params: { period: 20 } },
      ],
    })
    const wrapper = await mountView('normal', ['indicator:registry'])
    expect(wrapper.findAll('.app-control-width-long')).toHaveLength(1)
    expect(wrapper.findAll('.app-control-width-short')).toHaveLength(4)
    expect(wrapper.text()).toContain('移动平均线')
    expect(wrapper.text()).not.toContain('MA20快捷项')
    const checkbox = wrapper.findAllComponents({ name: 'ElCheckbox' })
      .find((item) => item.text().includes('展开快捷预设'))
    expect(checkbox).toBeTruthy()
    await checkbox?.vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(wrapper.text()).toContain('MA20快捷项')
    wrapper.unmount()
  })

  it('自定义指标抽屉使用三步流程并把 DSL 翻译为公式创建', async () => {
    routeState.meta.configTab = 'tech'
    ;(scoreApi.getIndicatorRegistry as ReturnType<typeof vi.fn>).mockResolvedValue({
      calculation_context: { default_period: 'day', supported_periods: ['day'] },
      items: [],
      templates: [{
        key: 'range_position', name: '区间位置', dtype: 'number',
        expression: '(C - LLV(L, {window})) / (HHV(H, {window}) - LLV(L, {window})) * 100',
        params: [{ name: 'window', label: '统计周期', type: 'int', default: 60,
          min: 2, max: 1200, unit: '交易日', description: '回看长度' }],
      }],
    })
    const wrapper = await mountView('system', ['indicator:registry', 'indicator:def-manage'])
    const create = wrapper.findAll('button').find((node) => node.text().includes('新建自定义指标'))
    expect(create).toBeTruthy()
    await create?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('选择创建方式')
    expect(wrapper.text()).toContain('模板创建')
    expect(wrapper.text()).toContain('公式创建')
    expect(wrapper.text()).toContain('用真实行情验证')
    expect(wrapper.text()).not.toContain('高级 DSL')
    const period = wrapper.find('[data-testid="indicator-definition-calculation-period"]')
    expect(period.exists()).toBe(true)
    expect(period.text()).toBe('日K')
    expect(wrapper.findAll('.el-tag').some((tag) => tag.text() === '日K')).toBe(true)
    ;(wrapper.vm as any).defMode = 'dsl'
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('不是 Python 或 SQL')
    wrapper.unmount()
  })
})

describe('ConfigView system tab', () => {
  it('数据治理承载真实来源清单，查看不联网，单项测试后更新状态', async () => {
    const source = { source: 'ths_board', label: '同花顺板块', role: 'board' as const, scope: '字典、成分、指数和资金流',
      up: null, last_test_at: null, last_success_at: null, failure_reason: null,
      timeout_sec: 12, rate_limit_per_sec: 1, concurrency: 1, serial_required: true, max_attempts: 3,
      retry_backoff_sec: 2, policy_origin: '保留旧显式覆盖' }
    vi.mocked(dataApi.getSources).mockResolvedValue({ sources: [source] })
    vi.mocked(dataApi.testSources).mockResolvedValue({ sources: [{ ...source, up: true }] })
    const wrapper = await mountView()
    const tab = wrapper.findAll('[role="tab"]').find((node) => node.text() === '数据治理')!
    await tab.trigger('click')
    await flushPromises()
    expect(dataApi.getSources).toHaveBeenCalledWith(false)
    expect(dataApi.testSources).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('数据源能力与健康')
    expect(wrapper.text()).toContain('超时 12 秒')
    expect(wrapper.text()).toContain('会话串行 1')
    expect(wrapper.text()).toContain('保留旧显式覆盖')
    await wrapper.find('.source-health [role="button"]').trigger('click')
    const button = wrapper.findAll('button').find((node) => node.text() === '测试全部来源')!
    expect(button.isVisible()).toBe(true)
    await button.trigger('click')
    await flushPromises()
    expect(dataApi.testSources).toHaveBeenCalledWith('ths_board')
    expect(wrapper.text()).toContain('通过')
    wrapper.unmount()
  })

  it('来源规则显示接口返回的生效参数，说明提示紧邻其解释文字', async () => {
    vi.mocked(dataApi.getSources).mockResolvedValue({ sources: [{
      source: 'akshare', label: '新浪行情', role: 'primary', scope: '日线',
      up: null, last_test_at: null, last_success_at: null, failure_reason: null,
      concurrency: 7, serial_required: false, rate_limit_per_sec: 2.5,
      timeout_sec: 47, max_attempts: 4, retry_backoff_sec: 1.5,
      policy_origin: '继承通用配置',
    }] })
    const wrapper = await mountView()
    await wrapper.findAll('[role="tab"]').find((node) => node.text() === '数据治理')!.trigger('click')
    await flushPromises()
    const health = wrapper.find('.source-health')
    expect(health.text()).toContain('默认并发 7 · 2.5 次/秒')
    expect(health.text()).toContain('超时 47 秒 · 最多尝试 4 次')
    expect(health.text()).toContain('退避起点 1.5 秒')
    const hint = health.find('[aria-label="来源规则与测试说明"]')
    expect(hint.element.parentElement?.textContent).toContain('来源规则与测试说明')
    expect(hint.element.parentElement?.textContent).not.toContain('测试全部来源')
    wrapper.unmount()
  })

  it('页签和保存按钮位于内容滚动区外，健康表默认收起且使用统一嵌入限高', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('[role="tab"]').find((node) => node.text() === '数据治理')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.config-body--system').element.tagName).toBe('DIV')
    const content = wrapper.find('#pane-data-governance .sys-content')
    expect(content.exists()).toBe(true)
    expect(content.findComponent(AppTabToolbar).exists()).toBe(false)
    expect(content.find('[role="tablist"]').exists()).toBe(false)
    const health = wrapper.findComponent('.source-health')
    const head = health.find('[role="button"]')
    expect(head.attributes('aria-expanded')).toBe('false')
    const table = health.findComponent(AppDataTable)
    expect(table.props('embedded')).toBe(true)
    const mountedTable = table.element
    await head.trigger('click')
    expect(head.attributes('aria-expanded')).toBe('true')
    expect(health.find('.config-panel-section__body').isVisible()).toBe(true)
    await head.trigger('click')
    expect(health.find('.config-panel-section__body').isVisible()).toBe(false)
    expect(health.findComponent(AppDataTable).element).toBe(mountedTable)
    const override = wrapper.findComponent({ name: 'PageSettingsDrawer' }).props('componentMetaOverrides')
    expect(override.configPanel.collapseSections).toContainEqual({ key: 'source-health', label: '数据源能力与健康' })
    wrapper.unmount()
  })

  it('切换页签保留配置草稿和健康区展开状态', async () => {
    const wrapper = await mountView()
    const governance = wrapper.findAll('[role="tab"]').find((node) => node.text() === '数据治理')!
    await governance.trigger('click')
    await flushPromises()
    const health = wrapper.findComponent('.source-health')
    await health.find('[role="button"]').trigger('click')
    const form = wrapper.findAllComponents(ConfigGroupForm).find((node) => node.props('group').key === 'datasource')!
    form.vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    await wrapper.findAll('[role="tab"]').find((node) => node.text() === '访问安全')!.trigger('click')
    await governance.trigger('click')
    expect(health.find('[role="button"]').attributes('aria-expanded')).toBe('true')
    expect(form.props('modelValue')['datasource.concurrent_jobs']).toBe(3)
    expect(dataApi.saveSettings).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('通用参数有未保存修改时不允许使用旧值测试来源', async () => {
    const wrapper = await mountView()
    const tab = wrapper.findAll('[role="tab"]').find((node) => node.text() === '数据治理')!
    await tab.trigger('click')
    await flushPromises()
    const form = wrapper.findComponent(ConfigGroupForm)
    form.vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    await flushPromises()
    const button = wrapper.findAll('button').find((node) => node.text() === '测试全部来源')!
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('请先保存当前修改')
    wrapper.unmount()
  })

  it('系统设置保存与恢复默认留在当前页签工具区，不进入总页头', async () => {
    const wrapper = await mountView()
    const tabs = wrapper.find('.app-workspace-tabs')
    expect(tabs.exists()).toBe(true)
    const panel = wrapper.find('#pane-access > .app-workspace-panel')
    expect(panel.findComponent(AppTabToolbar).props('label')).toBe('系统配置操作栏')
    expect(panel.find('.app-tab-toolbar__actions').text()).toContain('保存并生效')
    expect(panel.find('.sys-content').exists()).toBe(true)
    expect(wrapper.find('.page-head-actions').text()).not.toContain('保存并生效')
    expect(wrapper.find('.page-head-actions').text()).not.toContain('恢复默认')
    expect(wrapper.findComponent(AppTabToolbar).text()).toContain('保存并生效')
    expect(wrapper.findComponent(AppTabToolbar).text()).toContain('恢复默认')
  })

  it('访问安全草稿不阻止按已保存来源配置测试，刷新来源状态不触发探活', async () => {
    vi.mocked(dataApi.getSources).mockResolvedValue({ sources: [{
      source: 'baostock', label: 'BaoStock', role: 'fallback', timeout_sec: 30,
      up: null, last_test_at: null, last_success_at: null, failure_reason: null,
    }] })
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    await selectSysTab(wrapper, '数据治理')
    const testButton = wrapper.findAll('button').find((node) => node.text() === '测试全部来源')!
    expect(testButton.attributes('disabled')).toBeUndefined()
    await sysButton(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(dataApi.getSources).toHaveBeenLastCalledWith(false)
    expect(dataApi.testSources).not.toHaveBeenCalled()
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(false)
    wrapper.unmount()
  })

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

  it('还原修改只回退当前页签草稿，不写服务端、不影响其他页签', async () => {
    const wrapper = await mountView()
    expect(sysButton(wrapper, '还原修改').attributes('disabled')).toBeDefined()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    await flushPromises()
    await sysButton(wrapper, '还原修改').trigger('click')
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(true)
    expect(sysForm(wrapper, 'datasource').props('modelValue')['datasource.concurrent_jobs']).toBe(3)
    expect(dataApi.saveSettings).not.toHaveBeenCalled()
    expect(dataApi.resetSettings).not.toHaveBeenCalled()
    expect(dataApi.getSettingsView).toHaveBeenCalledTimes(1)
    expect(sysButton(wrapper, '还原修改').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('保存只提交当前页签，保留其他页签待保存草稿', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    await flushPromises()
    vi.mocked(dataApi.getSettingsView).mockResolvedValue(settingsWith({ 'auth.require_email_code': false }))
    await sysButton(wrapper, '保存并生效').trigger('click')
    await flushPromises()
    expect(dataApi.saveSettings).toHaveBeenCalledWith({ 'auth.require_email_code': false })
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeDefined()
    await selectSysTab(wrapper, '数据治理')
    expect(sysForm(wrapper, 'datasource').props('modelValue')['datasource.concurrent_jobs']).toBe(3)
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('刷新同步当前已保存值并保留两个页签的草稿', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    vi.mocked(dataApi.getSettingsView).mockResolvedValue(settingsWith({ 'auth.login_rate_per_min': 30, 'datasource.concurrent_jobs': 4 }))
    await sysButton(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(sysForm(wrapper, 'auth').props('modelValue')).toMatchObject({
      'auth.require_email_code': false, 'auth.login_rate_per_min': 30, 'datasource.concurrent_jobs': 3,
    })
    expect(dataApi.saveSettings).not.toHaveBeenCalled()
    expect(dataApi.resetSettings).not.toHaveBeenCalled()
    await selectSysTab(wrapper, '数据治理')
    await sysButton(wrapper, '还原修改').trigger('click')
    expect(sysForm(wrapper, 'datasource').props('modelValue')['datasource.concurrent_jobs']).toBe(4)
    wrapper.unmount()
  })

  it('刷新期间允许继续编辑，响应不会覆盖新输入，重复刷新被拦截', async () => {
    const wrapper = await mountView()
    let finish!: (data: ReturnType<typeof settingsWith>) => void
    vi.mocked(dataApi.getSettingsView).mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    await sysButton(wrapper, '刷新').trigger('click')
    expect(sysButton(wrapper, '刷新').classes()).toContain('is-loading')
    expect(sysForm(wrapper, 'auth').props('disabled')).toBe(false)
    await sysButton(wrapper, '刷新').trigger('click')
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.login_rate_per_min', 40)
    await flushPromises()
    finish(settingsWith({ 'auth.login_rate_per_min': 30 }))
    await flushPromises()
    expect(dataApi.getSettingsView).toHaveBeenCalledTimes(2)
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.login_rate_per_min']).toBe(40)
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('刷新失败保留表单和草稿，并可再次刷新恢复', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    vi.mocked(dataApi.getSettingsView).mockRejectedValueOnce(new Error('offline'))
    await sysButton(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('刷新失败，已保留当前编辑值')
    expect(sysForm(wrapper, 'auth').isVisible()).toBe(true)
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(false)
    await sysButton(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('刷新失败，已保留当前编辑值')
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(false)
    wrapper.unmount()
  })

  it('保存通用请求值后同时更新来源继承元数据，保留其他页签草稿', async () => {
    const inheritedGroup: SettingGroup = { key: 'ths_board', label: '同花顺板块', fields: [{
      path: 'ths_board.timeout_sec', label: '旧超时覆盖', type: 'number',
      value: null, default: null, nullable: true, inherited_value: 30, overridden: false,
    }] }
    const requestGroup: SettingGroup = { key: 'datasource', label: '数据源', fields: [{
      path: 'datasource.socket_timeout_sec', label: '请求超时', type: 'number',
      value: 30, default: 30, overridden: false,
    }] }
    const otherGroups = groups.filter((group) => group.key !== 'datasource')
    mockSettings([...otherGroups, requestGroup, inheritedGroup])
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    await selectSysTab(wrapper, '数据治理')
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.socket_timeout_sec', 60)
    vi.mocked(dataApi.getSettingsView).mockResolvedValue({ groups: [
      ...otherGroups,
      { ...requestGroup, fields: [{ ...requestGroup.fields[0], value: 60, overridden: true }] },
      { ...inheritedGroup, fields: [{ ...inheritedGroup.fields[0], inherited_value: 60 }] },
    ] })
    await flushPromises()
    await sysButton(wrapper, '保存并生效').trigger('click')
    await flushPromises()
    expect(sysForm(wrapper, 'ths_board').props('group').fields[0].inherited_value).toBe(60)
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(false)
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('恢复默认只在存在持久化覆盖时可用，使用危险色描边', async () => {
    const wrapper = await mountView()
    expect(sysButton(wrapper, '恢复默认').classes()).toEqual(expect.arrayContaining(['el-button--danger', 'is-plain']))
    expect(sysButton(wrapper, '恢复默认').attributes('disabled')).toBeUndefined()
    await selectSysTab(wrapper, '数据治理')
    expect(sysButton(wrapper, '恢复默认').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('确认恢复默认后即使切换页签也只清除冻结范围，保留其他草稿', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    let confirm!: () => void
    vi.mocked(ElMessageBox.confirm).mockReturnValueOnce(new Promise((resolve) => {
      confirm = () => resolve('confirm' as never)
    }))
    await sysButton(wrapper, '恢复默认').trigger('click')
    await selectSysTab(wrapper, '数据治理')
    vi.mocked(dataApi.getSettingsView).mockResolvedValue(settingsWith({}, true))
    confirm()
    await flushPromises()
    expect(dataApi.resetSettings).toHaveBeenCalledWith(groups.find((group) => group.key === 'auth')!.fields.map((field) => field.path))
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(true)
    expect(sysForm(wrapper, 'datasource').props('modelValue')['datasource.concurrent_jobs']).toBe(3)
    expect(vi.mocked(ElMessageBox.confirm).mock.calls[0][0]).toContain('其他页签草稿保留')
    wrapper.unmount()
  })

  it('取消恢复默认不产生写入也不丢弃草稿', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await sysButton(wrapper, '恢复默认').trigger('click')
    await flushPromises()
    expect(dataApi.resetSettings).not.toHaveBeenCalled()
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(false)
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('恢复默认请求失败时保留当前和其他页签草稿，解除忙态', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    vi.mocked(dataApi.resetSettings).mockRejectedValueOnce(new Error('offline'))
    await sysButton(wrapper, '恢复默认').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('恢复默认失败，已保留当前编辑值')
    expect(sysForm(wrapper, 'auth').props('modelValue')).toMatchObject({
      'auth.require_email_code': false, 'datasource.concurrent_jobs': 3,
    })
    expect(sysButton(wrapper, '恢复默认').classes()).not.toContain('is-loading')
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('清除凭据只清除选中字段并保留同页签及其他页签草稿', async () => {
    const credentialGroup: SettingGroup = { key: 'ths_board', label: '同花顺板块', fields: [{
      path: 'ths_board.login_cookie', label: '登录 Cookie', type: 'password',
      value: '••••••已设置', default: '', overridden: true, secret_status: 'usable',
    }] }
    mockSettings([...groups, credentialGroup])
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    await selectSysTab(wrapper, '数据治理')
    sysForm(wrapper, 'datasource').vm.$emit('update-field', 'datasource.concurrent_jobs', 3)
    vi.mocked(dataApi.getSettingsView).mockResolvedValue({ groups: [...groups, {
      ...credentialGroup, fields: [{ ...credentialGroup.fields[0], value: '', overridden: false, secret_status: 'unset' }],
    }] })
    await sysForm(wrapper, 'ths_board').findAll('button')
      .find((button) => button.text() === '清除已存配置')!.trigger('click')
    await flushPromises()
    expect(dataApi.resetSettings).toHaveBeenCalledWith(['ths_board.login_cookie'])
    expect(sysForm(wrapper, 'ths_board').props('modelValue')).toMatchObject({
      'ths_board.login_cookie': '', 'datasource.concurrent_jobs': 3, 'auth.require_email_code': false,
    })
    wrapper.unmount()
  })

  it('保存成功但回读失败时保留草稿，刷新核对前阻止重复写入', async () => {
    const wrapper = await mountView()
    sysForm(wrapper, 'auth').vm.$emit('update-field', 'auth.require_email_code', false)
    vi.mocked(dataApi.getSettingsView).mockRejectedValueOnce(new Error('offline'))
    await flushPromises()
    await sysButton(wrapper, '保存并生效').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('操作已生效，但最新配置读取失败')
    expect(sysButton(wrapper, '保存并生效').attributes('disabled')).toBeDefined()
    expect(sysButton(wrapper, '恢复默认').attributes('disabled')).toBeDefined()
    expect(sysForm(wrapper, 'auth').props('modelValue')['auth.require_email_code']).toBe(false)
    vi.mocked(dataApi.getSettingsView).mockResolvedValue(settingsWith({ 'auth.require_email_code': false }))
    await sysButton(wrapper, '刷新').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('操作已生效，但最新配置读取失败')
    expect(dataApi.saveSettings).toHaveBeenCalledTimes(1)
    expect(sysButton(wrapper, '还原修改').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('保存时只提交改动字段，成功后重新加载设置', async () => {
    const wrapper = await mountView()
    await selectSysTab(wrapper, '数据治理')
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
    expect(wrapper.findComponent(AppTabToolbar).find('.app-tab-toolbar__description').text())
      .toContain('保存失败，已保留当前编辑值')
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

  it('敏感配置密文无法解密时显示运行态不可用提示', async () => {
    mockSettings([
      {
        key: 'ths_board',
        label: '同花顺板块',
        fields: [
          {
            path: 'ths_board.login_cookie',
            label: '登录 Cookie',
            type: 'password',
            value: '',
            default: '',
            overridden: true,
            secret_status: 'unavailable',
          },
        ],
      },
    ])
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('已存密文无法解密，请检查主密钥或输入新值后保存')
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

  it('买卖方案详情加载失败回滚选中值并保留旧编辑器，不出现「新选中+旧内容」错位（P1-2）', async () => {
    routeState.meta.configTab = 'trade'
    ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 't1', profile_ref: 'ref_t1', name: '方案一', version: 1,
        is_preset: false, visibility: 'private', source: 'mine', readonly: false,
      },
      {
        id: 't2', profile_ref: 'ref_t2', name: '方案二', version: 1,
        is_preset: false, visibility: 'private', source: 'mine', readonly: false,
      },
    ])
    const wrapper = await mountView('normal', ['trade-profile:view'])
    // 首次成功载入方案一
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 't1', profile_ref: 'ref_t1', name: '方案一', version: 1,
      is_preset: false, visibility: 'private', source: 'mine', readonly: false,
      buy_tree: { op: 'AND', children: [] }, sell_tree: { op: 'OR', children: [] }, backstop: {},
    })
    await wrapper.findComponent({ name: 'AssetProfileSelect' }).vm.$emit('update:modelValue', 'ref_t1')
    await flushPromises()
    expect(wrapper.text()).toContain('方案一')

    // 切到方案二时详情接口失败 → 选中值回滚到 ref_t1，编辑器仍是方案一，出现错误态
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'))
    await wrapper.findComponent({ name: 'AssetProfileSelect' }).vm.$emit('update:modelValue', 'ref_t2')
    await flushPromises()
    const select = wrapper.findComponent({ name: 'AssetProfileSelect' })
    expect(select.props('modelValue')).toBe('ref_t1')
    expect(wrapper.text()).toContain('方案一')
    expect(wrapper.text()).toContain('买卖方案详情加载失败')
  })

  it('快速切换买卖方案时较慢的旧响应不覆盖新选择（P1-2 竞态守卫）', async () => {
    routeState.meta.configTab = 'trade'
    ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 't1', profile_ref: 'ref_t1', name: '方案一', version: 1, is_preset: false, visibility: 'private', source: 'mine', readonly: false },
      { id: 't2', profile_ref: 'ref_t2', name: '方案二', version: 1, is_preset: false, visibility: 'private', source: 'mine', readonly: false },
    ])
    let resolveSlow!: (v: unknown) => void
    const slow = new Promise((r) => { resolveSlow = r })
    const wrapper = await mountView('normal', ['trade-profile:view'])
    // 先点方案一（慢响应挂起），立即再点方案二（快响应）
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockImplementation((ref: string) =>
      ref === 'ref_t1' ? slow : Promise.resolve({
        id: 't2', profile_ref: 'ref_t2', name: '方案二', version: 1,
        is_preset: false, visibility: 'private', source: 'mine', readonly: false,
        buy_tree: { op: 'AND', children: [] }, sell_tree: { op: 'OR', children: [] }, backstop: {},
      }),
    )
    const select = wrapper.findComponent({ name: 'AssetProfileSelect' })
    await select.vm.$emit('update:modelValue', 'ref_t1')
    await select.vm.$emit('update:modelValue', 'ref_t2')
    await flushPromises()
    // 方案二已应用
    expect(wrapper.text()).toContain('方案二')
    // 慢响应（方案一）后到达，不得覆盖方案二
    resolveSlow({
      id: 't1', profile_ref: 'ref_t1', name: '方案一', version: 1,
      is_preset: false, visibility: 'private', source: 'mine', readonly: false,
      buy_tree: { op: 'AND', children: [] }, sell_tree: { op: 'OR', children: [] }, backstop: {},
    })
    await flushPromises()
    expect(wrapper.text()).toContain('方案二')
    expect(select.props('modelValue')).toBe('ref_t2')
  })

  it('买卖方案切换成功后清空上一方案试算命中结果', async () => {
    routeState.meta.configTab = 'trade'
    ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockImplementation((ref: string) => Promise.resolve({
      id: ref, profile_ref: ref, name: ref, version: 1,
      is_preset: false, visibility: 'private', source: 'mine', readonly: false,
      buy_tree: { op: 'AND', children: [] }, sell_tree: { op: 'OR', children: [] }, backstop: {},
    }))
    const wrapper = await mountView('normal', ['trade-profile:view'])
    const select = wrapper.findComponent({ name: 'AssetProfileSelect' })
    select.vm.$emit('update:modelValue', 'ref_t1')
    await flushPromises()
    ;(wrapper.vm as any).previewHit = { buy: 8, sell: 3 }
    ;(wrapper.vm as any).previewDate = { buy: '2026-08-01', sell: '2026-08-01' }

    select.vm.$emit('update:modelValue', 'ref_t2')
    await flushPromises()
    expect((wrapper.vm as any).previewHit).toEqual({ buy: null, sell: null })
    expect((wrapper.vm as any).previewDate).toEqual({ buy: null, sell: null })
  })

  it('「加载查看」注入临时只读项并以 profile_ref 载入编辑器只读展示（P1-1 接入 @loaded）', async () => {
    routeState.meta.configTab = 'trade'
    ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
    // 搜索抽屉浏览返回一条系统内置 preset（走真实 onDrawerLoad，组件自同步 modelValue）
    ;(tradeApi.browseTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{
        id: 'tp1', profile_ref: 'avr_trade_preset', name: '趋势买卖', version: 4,
        is_preset: true, visibility: 'private', source: 'preset', readonly: true,
      }],
      total: 1, page: 1, page_size: 20, source: 'preset',
    })
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'tp1', profile_ref: 'avr_trade_preset', name: '趋势买卖', version: 4,
      is_preset: true, visibility: 'private', source: 'preset', readonly: true,
      buy_tree: { op: 'AND', children: [] }, sell_tree: { op: 'OR', children: [] }, backstop: {},
    })
    const wrapper = await mountView('normal', ['trade-profile:view'])
    // 「加载查看」经组件 loaded 事件触发 onTradeLoaded（真实浏览器路径已复验；
    // jsdom 下打开抽屉 + tempItem 会触发 ElSelect 更新循环，故此处直接 emit loaded 聚焦页面级载入断言）
    wrapper.findComponent({ name: 'AssetProfileSelect' }).vm.$emit('loaded', {
      id: 'tp1', profile_ref: 'avr_trade_preset', name: '趋势买卖', version: 4,
      is_preset: true, visibility: 'private', source: 'preset', readonly: true,
    })
    await flushPromises()
    // onTradeLoaded 以 profile_ref 拉详情载入编辑器只读展示（不自动试算）
    expect(tradeApi.getTradeProfile).toHaveBeenCalledWith('avr_trade_preset')
    // 编辑器名称输入框载入该方案名，且只读生效（preset readonly）
    const nameInput = wrapper.find('input[placeholder="方案名称"]')
    expect((nameInput.element as HTMLInputElement).value).toBe('趋势买卖')
    expect((nameInput.element as HTMLInputElement).disabled).toBe(true)
    wrapper.unmount()
  })

  it('移除本人名下系统内置买卖方案预览时同步清空外部参数，刷新失败也保持干净新建态', async () => {
    routeState.meta.configTab = 'trade'
    ;(tradeApi.listTradeProfiles as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('刷新失败'))
    const summary = {
      id: 'tp-remove', profile_ref: 'avr_trade_remove', name: '待移除买卖方案', version: 1,
      is_preset: true, visibility: 'public', source: 'preset', readonly: true,
    }
    ;(tradeApi.getTradeProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...summary,
      buy_tree: { op: 'AND', children: [{ indicator: 'rs_pct', cmp: '>=', value: 5 }] },
      sell_tree: { op: 'OR', children: [] }, backstop: { max_hold_days: 20 },
    })
    const wrapper = await mountView('normal', ['trade-profile:view'])
    const selector = wrapper.findComponent({ name: 'AssetProfileSelect' })
    selector.vm.$emit('loaded', summary)
    await flushPromises()
    expect((wrapper.vm as any).buyConds).toHaveLength(1)

    // 模拟平台内置资产对物理 owner 的详情口径：source=preset，但 readonly=false。
    // 同一 tick 内触发移除，避免 jsdom 重渲染完整可编辑条件表导致 Element Plus 自身递归噪声。
    ;(wrapper.vm as any).tReadonly = false
    selector.vm.$emit('tempRemoved', summary)
    await flushPromises()
    expect((wrapper.vm as any).tCurRef).toBe('')
    expect((wrapper.vm as any).tReadonly).toBe(false)
    expect((wrapper.vm as any).buyConds).toEqual([])
    expect((wrapper.vm as any).backstop).toEqual({ tp: null, sl: null, hold: null })
    wrapper.unmount()
  })
})

describe('ConfigView score tab 加载查看', () => {
  it('用紧凑的显式二选一配置 ST 评分范围', async () => {
    routeState.meta.configTab = 'score'
    ;(scoreApi.listScoreProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
    const wrapper = await mountView('normal', ['score-profile:view', 'score-profile:save'])

    const scope = wrapper.get('[data-testid="score-include-st"]')
    const segmented = wrapper.findComponent(PageSegmented)
    expect(segmented.props('modelValue')).toBe(true)
    expect(segmented.props('disabled')).toBe(false)
    expect(scope.text()).toContain('参与')
    expect(scope.text()).toContain('不参与')

    await scope.get('[data-testid="score-include-st-false"]').trigger('click')
    expect((wrapper.vm as any).includeSt).toBe(false)
    wrapper.unmount()
  })

  it('「加载查看」注入临时只读项并以 profile_ref 载入编辑器只读展示（P1-1 接入 @loaded）', async () => {
    routeState.meta.configTab = 'score'
    ;(scoreApi.listScoreProfiles as ReturnType<typeof vi.fn>).mockResolvedValue([])
    ;(scoreApi.browseScoreProfiles as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{
        id: 'sp1', profile_ref: 'avr_score_preset', name: '默认趋势分', version: 1,
        is_preset: true, visibility: 'private', source: 'preset', readonly: true,
      }],
      total: 1, page: 1, page_size: 20, source: 'preset',
    })
    ;(scoreApi.getScoreProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'sp1', profile_ref: 'avr_score_preset', name: '默认趋势分', version: 1,
      is_preset: true, visibility: 'private', source: 'preset', readonly: true,
      include_st: false,
      items: [],
    })
    const wrapper = await mountView('normal', ['score-profile:view'])
    wrapper.findComponent({ name: 'AssetProfileSelect' }).vm.$emit('loaded', {
      id: 'sp1', profile_ref: 'avr_score_preset', name: '默认趋势分', version: 1,
      is_preset: true, visibility: 'private', source: 'preset', readonly: true,
    })
    await flushPromises()
    // onScoreLoaded 以 profile_ref 拉详情载入编辑器只读展示
    expect(scoreApi.getScoreProfile).toHaveBeenCalledWith('avr_score_preset')
    // 编辑器名称输入框载入该方案名，且只读生效（preset readonly）
    const nameInput = wrapper.find('input[placeholder="方案名称"]')
    expect((nameInput.element as HTMLInputElement).value).toBe('默认趋势分')
    expect((nameInput.element as HTMLInputElement).disabled).toBe(true)
    const segmented = wrapper.findComponent(PageSegmented)
    expect(segmented.props('modelValue')).toBe(false)
    expect(segmented.props('disabled')).toBe(true)
    wrapper.unmount()
  })

  it('移除本人名下系统内置评分方案预览时同步清空外部评分项，刷新失败也保持干净新建态', async () => {
    routeState.meta.configTab = 'score'
    ;(scoreApi.listScoreProfiles as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('刷新失败'))
    const summary = {
      id: 'sp-remove', profile_ref: 'avr_score_remove', name: '待移除评分方案', version: 1,
      is_preset: true, visibility: 'public', source: 'preset', readonly: true,
    }
    ;(scoreApi.getScoreProfile as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...summary,
      items: [{ indicator: 'rs_pct', weight: 1, scoring: { type: 'linear', min: 0, max: 100 } }],
    })
    const wrapper = await mountView('normal', ['score-profile:view'])
    const selector = wrapper.findComponent({ name: 'AssetProfileSelect' })
    selector.vm.$emit('loaded', summary)
    await flushPromises()
    expect((wrapper.vm as any).items).toHaveLength(1)

    // 模拟平台内置资产对物理 owner 的详情口径：source=preset，但 readonly=false。
    ;(wrapper.vm as any).profileReadonly = false
    selector.vm.$emit('tempRemoved', summary)
    await flushPromises()
    expect((wrapper.vm as any).curRef).toBe('')
    expect((wrapper.vm as any).profileReadonly).toBe(false)
    expect((wrapper.vm as any).items).toEqual([])
    expect((wrapper.vm as any).runRows).toEqual([])
    wrapper.unmount()
  })
})
