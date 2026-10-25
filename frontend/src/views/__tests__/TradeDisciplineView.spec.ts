// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'
import TradeDisciplineView from '@/views/TradeDisciplineView.vue'
import TradeLedgerWorkspace from '@/views/trade-discipline/components/TradeLedgerWorkspace.vue'
import PageSegmented from '@/components/PageSegmented.vue'
import PageSettingsDrawer from '@/components/PageSettingsDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import { permission } from '@/directives/permission'
import {
  resetTradeDisciplineSummaryForTests,
  useTradeDisciplineSummary,
} from '@/composables/useTradeDisciplineSummary'

const listRules = vi.fn()
const listCheckins = vi.fn()
const getSummary = vi.fn()
const getCheckinContext = vi.fn()
const ensureTradeDates = vi.fn(async () => undefined)
const tradeDateStatus = { value: 'ready' }
const layoutHarness = vi.hoisted(() => ({
  historyPageSize: null as { value: number } | null,
  conditionCollapsed: null as { value: string[] } | null,
  setComponentKnob: vi.fn(),
  resetLayout: vi.fn(),
  resetPageSettings: vi.fn(),
}))

vi.mock('@/api/dict', () => ({ getPublicDictItems: vi.fn(async () => ({ items: [], fallback: false })) }))
vi.mock('@/api/tradeDiscipline', () => ({
  listTradeDisciplineRules: (...args: unknown[]) => listRules(...args),
  listTradeDisciplineCheckins: (...args: unknown[]) => listCheckins(...args),
  getTradeDisciplineSummary: (...args: unknown[]) => getSummary(...args),
  getTradeDisciplineCheckinContext: (...args: unknown[]) => getCheckinContext(...args),
}))
vi.mock('@/composables/useTradeDates', async () => {
  const { ref } = await import('vue')
  return {
    useTradeDates: () => ({
      tradeDateSet: ref(new Set(['2026-08-15', '2026-08-22'])),
      dataMax: ref('2026-08-22'),
      status: tradeDateStatus,
      ensureLoaded: ensureTradeDates,
    }),
  }
})
vi.mock('@/composables/useRemoteLayoutConfig', async () => {
  const { ref } = await import('vue')
  layoutHarness.historyPageSize ??= ref(20)
  layoutHarness.conditionCollapsed ??= ref(['basic', 'risk', 'technical', 'notes'])
  return {
    useRemoteLayoutConfig: (layout: unknown) => ({
      effective: ref(layout), knobs: [], setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
      isDirty: ref(false), resetAll: layoutHarness.resetLayout,
      componentValueOf: (_slot: string, field: string) => field === 'defaultCollapsed'
        ? layoutHarness.conditionCollapsed!.value
        : field === 'pageSize'
        ? layoutHarness.historyPageSize!.value
        : false,
      setComponentKnob: layoutHarness.setComponentKnob, componentSourceOf: vi.fn(), layerValuesOf: vi.fn(),
      componentLayerValuesOf: vi.fn(),
    }),
  }
})
vi.mock('@/composables/usePageSettings', async () => {
  const { ref } = await import('vue')
  return {
    usePageSettings: () => ({ reset: layoutHarness.resetPageSettings, isDirty: ref(false) }),
  }
})

let mountedRouter: ReturnType<typeof createRouter>

const ledgerHarness = { load: vi.fn(async () => undefined), leave: vi.fn(async () => true), dirty: false }
const mountedWrappers: { unmount: () => void }[] = []
const LedgerStub = defineComponent({
  name: 'TradeLedgerWorkspace', props: ['mode', 'tradeDate', 'canSubmit', 'pageSize', 'conditionPanelDefaults', 'preferredRuleId'],
  emits: ['request-date-change', 'submitted'],
  setup(_, { expose }) {
    expose({ isDirty: () => ledgerHarness.dirty, requestLeave: ledgerHarness.leave, load: ledgerHarness.load,
      startAmend: vi.fn(async () => true), reload: vi.fn(async () => undefined) })
    return {}
  },
  template: '<section data-testid="ledger-stub">{{ mode }} {{ tradeDate }}</section>',
})
afterEach(() => { for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount() })

async function mountPage(
  permissions: string[],
  initialPath = '/trade-discipline',
  stubs: Record<string, unknown> = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.role = 'normal'
  auth.permissions = permissions
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/trade-discipline', component: TradeDisciplineView },
      { path: '/system/users', component: defineComponent({ template: '<div>系统管理</div>' }) },
    ],
  })
  mountedRouter = router
  await router.push(initialPath)
  await router.isReady()
  const wrapper = mount(TradeDisciplineView, {
    global: { plugins: [pinia, router, ElementPlus], directives: { permission }, stubs: { TradeLedgerWorkspace: LedgerStub, ...stubs } as any },
  })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

function ruleState(id = 'rule-1', index = 0) {
  return {
    id,
    name: `纪律${index + 1}`,
    status: 'active',
    latest_version_no: 1,
    management_status: 'active',
    latest_management_event: null,
    has_pending_management_action: false,
    effective_status: 'active',
    effective_event_seq: index + 1,
    effective_from_trade_date: '2026-08-22',
    effective_version: { version_no: 1, name: `纪律${index + 1}`, capital: '100000' },
  }
}

describe('交易纪律账户工作台', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetTradeDisciplineSummaryForTests()
    ledgerHarness.dirty = false
    ledgerHarness.leave.mockResolvedValue(true)
    layoutHarness.historyPageSize!.value = 20
    layoutHarness.conditionCollapsed!.value = ['basic', 'risk', 'technical', 'notes']
    layoutHarness.setComponentKnob.mockImplementation((_slot, _field, value) => { layoutHarness.conditionCollapsed!.value = value })
    tradeDateStatus.value = 'ready'
    listRules.mockResolvedValue([])
    getSummary.mockResolvedValue({ trade_date: '2026-08-22', total: 0, completed: 0, pending: 0, rules: [] })
  })
  const view = ['trade-discipline:view', 'trade-discipline:checkin-view']
  it('从快捷卡携带的规则标识透传给账户成交入口', async () => {
    listRules.mockResolvedValue([ruleState('first'), ruleState('second', 1)])
    const wrapper = await mountPage(view, '/trade-discipline?tab=checkin&rule_ref=second')
    expect(wrapper.findComponent(TradeLedgerWorkspace).props('preferredRuleId')).toBe('second')
    await mountedRouter.replace('/trade-discipline?tab=checkin&rule_ref=first')
    await flushPromises()
    expect(wrapper.findComponent(TradeLedgerWorkspace).props('preferredRuleId')).toBe('first')
  })
  it('四个页签承接统一账户日结，规则为空也能初始化和记录计划外成交', async () => {
    const wrapper = await mountPage(view)
    expect(ensureTradeDates).toHaveBeenCalled()
    expect(listRules).toHaveBeenCalledWith('2026-08-22')
    expect(wrapper.text()).toContain('现有持仓')
    expect(wrapper.text()).toContain('规则管理')
    expect(wrapper.text()).toContain('历史记录')
    expect(wrapper.findComponent(TradeLedgerWorkspace).props()).toMatchObject({ mode: 'checkin', tradeDate: '2026-08-22' })
  })
  it('历史日期透传给账本，日期和页签切换不重建工作台', async () => {
    const wrapper = await mountPage(view, '/trade-discipline?trade_date=2026-08-15')
    const ledger = wrapper.findComponent(TradeLedgerWorkspace)
    expect(ledger.props('tradeDate')).toBe('2026-08-15')
    ledger.vm.$emit('request-date-change', '2026-08-22')
    await flushPromises()
    expect(wrapper.findComponent(TradeLedgerWorkspace).element).toBe(ledger.element)
    expect(ledger.props('tradeDate')).toBe('2026-08-22')
    wrapper.findComponent(PageSegmented).vm.$emit('update:modelValue', 'positions')
    await flushPromises()
    expect(ledger.props('mode')).toBe('positions')
  })
  it('未保存决策拒绝切换时保留当前页签和填写现场', async () => {
    const wrapper = await mountPage(view)
    ledgerHarness.dirty = true
    ledgerHarness.leave.mockResolvedValue(false)
    wrapper.findComponent(PageSegmented).vm.$emit('update:modelValue', 'history')
    await flushPromises()
    expect(ledgerHarness.leave).toHaveBeenCalled()
    expect(wrapper.findComponent(TradeLedgerWorkspace).props('mode')).toBe('checkin')
    ledgerHarness.dirty = false
  })
  it('缺少基础查看权限时不请求业务数据', async () => {
    const wrapper = await mountPage([])
    expect(wrapper.text()).toContain('无权限查看交易纪律')
    expect(listRules).not.toHaveBeenCalled()
    expect(wrapper.findComponent(TradeLedgerWorkspace).exists()).toBe(false)
  })
  it('缺少履约查看权限时展示权限态', async () => {
    const wrapper = await mountPage(['trade-discipline:view'])
    expect(wrapper.text()).toContain('无权限查看交易记录')
    expect(wrapper.findComponent(TradeLedgerWorkspace).exists()).toBe(false)
  })
  it('交易日不可用时停止展示写入口并允许重试', async () => {
    tradeDateStatus.value = 'error'
    const wrapper = await mountPage(view)
    expect(wrapper.text()).toContain('交易纪律加载失败')
    expect(wrapper.findComponent(TradeLedgerWorkspace).exists()).toBe(false)
    expect(listRules).not.toHaveBeenCalled()
  })
  it('规则接口明确拒绝查看时升级为权限态', async () => {
    listRules.mockRejectedValue({ response: { status: 403 } })
    const wrapper = await mountPage(view)
    expect(wrapper.text()).toContain('无权限查看交易纪律')
  })
  it('KeepAlive 离开到其他页面后不消费其查询参数', async () => {
    const wrapper = await mountPage(view)
    const calls = listRules.mock.calls.length
    await mountedRouter.push('/system/users?tab=history&trade_date=2026-08-15')
    await flushPromises()
    expect(listRules).toHaveBeenCalledTimes(calls)
    expect(wrapper.findComponent(TradeLedgerWorkspace).props('tradeDate')).toBe('2026-08-22')
  })
  it('继续复用默认条件折叠和历史分页配置，恢复默认调用原入口', async () => {
    const wrapper = await mountPage(view)
    const drawer = wrapper.findComponent(PageSettingsDrawer)
    const config = drawer.props('config') as { setComponentKnob: (slot: string, field: string, value: unknown) => void }
    config.setComponentKnob('stockConditions', 'defaultCollapsed', ['risk'])
    drawer.vm.$emit('component-default-change', 'stockConditions', 'defaultCollapsed')
    layoutHarness.historyPageSize!.value = 50
    await flushPromises()
    expect(wrapper.findComponent(TradeLedgerWorkspace).props('pageSize')).toBe(50)
    expect(wrapper.findComponent(TradeLedgerWorkspace).props('conditionPanelDefaults')).toMatchObject({ defaultCollapsed: ['risk'], resetKey: 1 })
    drawer.vm.$emit('reset')
    await flushPromises()
    expect(layoutHarness.resetLayout).toHaveBeenCalled()
    expect(layoutHarness.resetPageSettings).toHaveBeenCalled()
  })
  it('快捷入口变更刷新账户，存在未保存输入时保留现场', async () => {
    await mountPage(view)
    const shared = useTradeDisciplineSummary()
    shared.notifyTradeDisciplineChanged({ ruleId: 'account', tradeDate: '2026-08-22', source: 'quick' })
    await flushPromises()
    expect(ledgerHarness.load).toHaveBeenCalledTimes(1)
    ledgerHarness.dirty = true
    shared.notifyTradeDisciplineChanged({ ruleId: 'account', tradeDate: '2026-08-22', source: 'quick' })
    await flushPromises()
    expect(ledgerHarness.load).toHaveBeenCalledTimes(1)
    ledgerHarness.dirty = false
  })
})
