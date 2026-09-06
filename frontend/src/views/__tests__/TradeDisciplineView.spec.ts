// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'
import TradeDisciplineView from '@/views/TradeDisciplineView.vue'
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
  resetLayout: vi.fn(),
  resetPageSettings: vi.fn(),
}))

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
  return {
    useRemoteLayoutConfig: (layout: unknown) => ({
      effective: ref(layout), knobs: [], setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
      isDirty: ref(false), resetAll: layoutHarness.resetLayout,
      componentValueOf: (_slot: string, field: string) => field === 'pageSize'
        ? layoutHarness.historyPageSize!.value
        : false,
      setComponentKnob: vi.fn(), componentSourceOf: vi.fn(), layerValuesOf: vi.fn(),
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
    global: { plugins: [pinia, router, ElementPlus], directives: { permission }, stubs: stubs as any },
  })
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

describe('交易纪律 T5 工作台壳', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetTradeDisciplineSummaryForTests()
    layoutHarness.historyPageSize!.value = 20
    tradeDateStatus.value = 'ready'
    listRules.mockResolvedValue([])
    listCheckins.mockResolvedValue({ total: 0, page: 1, page_size: 20, list: [] })
    getSummary.mockResolvedValue({
      trade_date: '2026-08-22', total: 0, completed: 0, pending: 0, rules: [],
    })
    getCheckinContext.mockResolvedValue({
      trade_date: '2026-08-22',
      version: {
        rule_id: 'rule-1', version_no: 1, name: '纪律一', capital: '100000',
        stock_rules: [], action_rules: [],
      },
      checkin: null,
    })
  })

  it('加载交易日和规则，并提供三段业务页签与设置入口', async () => {
    const wrapper = await mountPage([
      'trade-discipline:view',
      'trade-discipline:rule-manage',
      'trade-discipline:checkin-view',
    ])
    expect(ensureTradeDates).toHaveBeenCalled()
    expect(listRules).toHaveBeenCalledWith('2026-08-22')
    expect(getSummary).toHaveBeenCalledWith('2026-08-22')
    expect(wrapper.get('[data-testid="trade-discipline-tabs"]')).toBeTruthy()
    expect(wrapper.text()).toContain('今日打卡')
    expect(wrapper.text()).toContain('规则管理')
    expect(wrapper.text()).toContain('历史记录')
    expect(wrapper.text()).toContain('前往规则管理')
    expect(wrapper.findAll('.el-empty')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('最新交易日')
    expect(wrapper.text()).not.toContain('已完成')
    expect(wrapper.text()).not.toContain('待打卡')
  })

  it('历史交易日没有生效规则时提供返回最新交易日但不提供创建入口', async () => {
    const wrapper = await mountPage(
      [
        'trade-discipline:view',
        'trade-discipline:rule-manage',
        'trade-discipline:checkin-view',
      ],
      '/trade-discipline?trade_date=2026-08-15',
    )

    expect(getSummary).toHaveBeenCalledWith('2026-08-15')
    expect(wrapper.text()).toContain('该交易日暂无生效规则')
    expect(wrapper.text()).toContain('这是历史日期的真实空状态')
    expect(wrapper.findAll('.el-empty')).toHaveLength(1)
    const returnButton = wrapper.findAll('button')
      .find((button) => button.text() === '返回最新交易日')
    expect(returnButton).toBeTruthy()
    expect(wrapper.findAll('button').some((button) => button.text() === '前往规则管理'))
      .toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === '新建规则'))
      .toBe(false)

    await returnButton!.trigger('click')
    await flushPromises()
    expect(getSummary).toHaveBeenLastCalledWith('2026-08-22')
    expect(wrapper.findAll('button').some((button) => button.text() === '返回最新交易日'))
      .toBe(false)
  })

  it('切换交易日时保持工作台结构并让左右组件独立加载', async () => {
    const rule = ruleState()
    listRules.mockResolvedValue([rule])
    getSummary.mockResolvedValueOnce({
      trade_date: '2026-08-22', total: 1, completed: 0, pending: 1,
      rules: [{
        rule_id: rule.id, rule_name: rule.name, version_no: 1,
        effective_from_trade_date: '2026-08-22', checkin_id: null,
        current_revision_no: null, status: null, assessment: null, no_operation: null,
      }],
    })
    let resolveSummary: ((value: unknown) => void) | undefined
    getSummary.mockReturnValueOnce(new Promise((resolve) => { resolveSummary = resolve }))
    const CheckinStub = defineComponent({
      name: 'TradeCheckinForm', emits: ['request-date-change'],
      setup(_props, { expose }) {
        expose({
          isDirty: () => false,
          requestLeave: async () => true,
        })
      },
      template: '<button data-testid="change-checkin-date" @click="$emit(\'request-date-change\', \'2026-08-15\')">切换日期</button>',
    })
    const wrapper = await mountPage(
      ['trade-discipline:view', 'trade-discipline:checkin-view'],
      '/trade-discipline',
      { TradeCheckinForm: CheckinStub },
    )

    await wrapper.get('[data-testid="change-checkin-date"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.master-detail-shell').exists()).toBe(true)
    expect(wrapper.find('.rule-master').exists()).toBe(true)
    expect(wrapper.find('[data-testid="trade-discipline-tabs"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在解析当日履约状态…')
    expect(wrapper.text()).not.toContain('正在加载交易纪律…')

    resolveSummary?.({
      trade_date: '2026-08-15', total: 0, completed: 0, pending: 0, rules: [],
    })
    await flushPromises()
  })

  it('在标题帮助中解释草稿、待生效、今日日期和历史版本口径', async () => {
    const wrapper = await mountPage(
      ['trade-discipline:view', 'trade-discipline:checkin-view'],
      '/trade-discipline',
      {
        HelpTip: defineComponent({
          template: '<div data-testid="rendered-help-tip"><slot /></div>',
        }),
      },
    )
    const help = wrapper.get('[data-testid="rendered-help-tip"]')
    expect(help.text()).toContain('新建时只是可编辑草稿，发布后才生成正式版本')
    expect(help.text()).toContain('本地行情中最新已入库的交易日')
    expect(help.text()).toContain('等生效日行情入库后')
    expect(help.text()).toContain('每次打卡绑定当时生效的正式版本')
  })

  it('KeepAlive 页面离开到其他路由时不把目标页 query 误当交易纪律参数', async () => {
    const rule = ruleState()
    listRules.mockResolvedValue([rule])
    const wrapper = await mountPage(
      ['trade-discipline:view', 'trade-discipline:checkin-view'],
      '/trade-discipline?tab=history&trade_date=2098-06-10',
    )
    vi.clearAllMocks()

    await mountedRouter.push('/system/users')
    await flushPromises()

    expect(mountedRouter.currentRoute.value.path).toBe('/system/users')
    expect(listRules).not.toHaveBeenCalled()
    expect(getSummary).not.toHaveBeenCalled()
    expect(getCheckinContext).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="trade-discipline-tabs"]').text()).toContain('历史记录')
  })

  it('缺少履约查看权限时显示无权限态而非空态', async () => {
    const wrapper = await mountPage(['trade-discipline:view'])
    expect(wrapper.text()).toContain('无权限查看履约打卡')
    expect(wrapper.text()).not.toContain('创建第一套规则')
  })

  it('缺少基础查看权限时优先显示整页权限态且不请求业务数据', async () => {
    const wrapper = await mountPage(['trade-discipline:checkin-view'])
    expect(wrapper.text()).toContain('无权限查看交易纪律')
    expect(ensureTradeDates).not.toHaveBeenCalled()
    expect(listRules).not.toHaveBeenCalled()
    expect(getSummary).not.toHaveBeenCalled()
  })

  it('基础规则接口实际返回 403 时从通用失败升级为权限态', async () => {
    listRules.mockRejectedValue({ response: { status: 403 } })
    const wrapper = await mountPage(['trade-discipline:view', 'trade-discipline:checkin-view'])
    expect(wrapper.text()).toContain('无权限查看交易纪律')
    expect(wrapper.text()).not.toContain('交易纪律加载失败')
  })

  it('交易日加载失败时整页 fail-closed 并提供重试', async () => {
    tradeDateStatus.value = 'error'
    const wrapper = await mountPage(['trade-discipline:view'])
    expect(wrapper.text()).toContain('交易纪律加载失败')
    expect(wrapper.text()).toContain('重试')
    expect(listRules).not.toHaveBeenCalled()
  })

  it('履约摘要失败由打卡区局部接管并停止伪装为空态', async () => {
    getSummary.mockRejectedValue(new Error('summary unavailable'))
    const wrapper = await mountPage(['trade-discipline:view', 'trade-discipline:checkin-view'])
    expect(wrapper.text()).toContain('履约摘要加载失败')
    expect(wrapper.text()).not.toContain('该交易日暂无生效规则')
    expect(listRules).toHaveBeenCalled()
  })

  it('脏编辑器触发规则列表刷新失败时只接管左侧列表并保留输入', async () => {
    const rule = ruleState()
    listRules.mockResolvedValueOnce([rule])
    const EditorStub = defineComponent({
      name: 'TradeRuleEditor', emits: ['changed'],
      data: () => ({ draftName: '' }),
      template: '<section data-testid="editor-stub"><input data-testid="dirty-rule-input" v-model="draftName"><button data-testid="refresh-rules" @click="$emit(\'changed\')">刷新列表</button></section>',
    })
    const wrapper = await mountPage(
      ['trade-discipline:view', 'trade-discipline:rule-manage'],
      '/trade-discipline?tab=rules',
      { TradeRuleEditor: EditorStub },
    )
    await wrapper.get('[data-testid="dirty-rule-input"]').setValue('未保存名称')
    listRules.mockRejectedValueOnce(new Error('refresh failed'))
    await wrapper.get('[data-testid="refresh-rules"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('规则列表刷新失败')
    expect(wrapper.text()).not.toContain('交易纪律加载失败')
    expect((wrapper.get('[data-testid="dirty-rule-input"]').element as HTMLInputElement).value)
      .toBe('未保存名称')
  })

  it('同页快捷参数切换被未保存保护拒绝后恢复当前真实 URL', async () => {
    const rules = ['rule-1', 'rule-2'].map(ruleState)
    listRules.mockResolvedValue(rules)
    getSummary.mockResolvedValue({
      trade_date: '2026-08-22', total: 2, completed: 0, pending: 2,
      rules: rules.map((rule) => ({
        rule_id: rule.id, rule_name: rule.name, version_no: 1,
        effective_from_trade_date: '2026-08-22', checkin_id: null,
        current_revision_no: null, status: null, assessment: null, no_operation: null,
      })),
    })
    getCheckinContext.mockImplementation(async (ruleId: string) => ({
      trade_date: '2026-08-22',
      version: {
        rule_id: ruleId, version_no: 1, name: ruleId === 'rule-1' ? '纪律一' : '纪律二',
        capital: '100000', stock_rules: [], action_rules: [],
      },
      checkin: null,
    }))
    const wrapper = await mountPage([
      'trade-discipline:view',
      'trade-discipline:checkin-view',
      'trade-discipline:checkin-submit',
    ])
    await wrapper.find('textarea').setValue('尚未提交的复盘内容')
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')

    await mountedRouter.push({
      path: '/trade-discipline',
      query: { tab: 'checkin', rule_ref: 'rule-2', trade_date: '2026-08-22' },
    })
    await flushPromises()

    expect(mountedRouter.currentRoute.value.query).toEqual({
      tab: 'checkin', rule_ref: 'rule-1', trade_date: '2026-08-22',
    })
    expect(wrapper.get('h3').text()).toBe('纪律一')
  })

  it('历史分页默认值重载并在恢复默认时同时重置页面与布局配置', async () => {
    const reload = vi.fn(async () => undefined)
    const HistoryStub = defineComponent({
      name: 'TradeDisciplineHistory',
      props: { pageSize: { type: Number, required: true } },
      setup(_props, { expose }) {
        expose({ reload })
      },
      template: '<div data-testid="history-page-size">{{ pageSize }}</div>',
    })
    const wrapper = await mountPage(
      ['trade-discipline:view', 'trade-discipline:checkin-view'],
      '/trade-discipline?tab=history',
      { TradeDisciplineHistory: HistoryStub },
    )

    expect(wrapper.get('[data-testid="history-page-size"]').text()).toBe('20')
    layoutHarness.historyPageSize!.value = 50
    await flushPromises()
    expect(wrapper.get('[data-testid="history-page-size"]').text()).toBe('50')
    expect(reload).toHaveBeenCalledTimes(1)

    wrapper.findComponent(PageSettingsDrawer).vm.$emit('reset')
    await wrapper.vm.$nextTick()
    expect(layoutHarness.resetPageSettings).toHaveBeenCalledTimes(1)
    expect(layoutHarness.resetLayout).toHaveBeenCalledTimes(1)
  })

  it('快捷入口变更广播会刷新当前工作台摘要、规则和选中表单', async () => {
    const rule = ruleState()
    listRules.mockResolvedValue([rule])
    getSummary.mockResolvedValue({
      trade_date: '2026-08-22', total: 1, completed: 0, pending: 1,
      rules: [{
        rule_id: 'rule-1', rule_name: '纪律一', version_no: 1,
        effective_from_trade_date: '2026-08-22', checkin_id: null,
        current_revision_no: null, status: null, assessment: null, no_operation: null,
      }],
    })
    await mountPage([
      'trade-discipline:view',
      'trade-discipline:checkin-view',
      'trade-discipline:checkin-submit',
    ])
    vi.clearAllMocks()

    useTradeDisciplineSummary().notifyTradeDisciplineChanged({
      ruleId: 'rule-1', tradeDate: '2026-08-22', source: 'quick',
    })
    await flushPromises()

    expect(getSummary).toHaveBeenCalledWith('2026-08-22')
    expect(listRules).toHaveBeenCalledWith('2026-08-22')
    expect(getCheckinContext).toHaveBeenCalledWith('rule-1', '2026-08-22')
  })
})
