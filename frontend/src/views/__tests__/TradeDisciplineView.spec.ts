// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'
import TradeDisciplineView from '@/views/TradeDisciplineView.vue'
import { useAuthStore } from '@/stores/auth'
import { permission } from '@/directives/permission'

const listRules = vi.fn()
const listCheckins = vi.fn()
const getSummary = vi.fn()
const getCheckinContext = vi.fn()
const ensureTradeDates = vi.fn(async () => undefined)
const tradeDateStatus = { value: 'ready' }

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
      tradeDateSet: ref(new Set(['2026-08-22'])),
      dataMax: ref('2026-08-22'),
      status: tradeDateStatus,
      ensureLoaded: ensureTradeDates,
    }),
  }
})
vi.mock('@/composables/useRemoteLayoutConfig', async () => {
  const { ref } = await import('vue')
  return {
    useRemoteLayoutConfig: (layout: unknown) => ({
      effective: ref(layout), knobs: [], setKnob: vi.fn(), valueOf: vi.fn(), sourceOf: vi.fn(),
      isDirty: ref(false), resetAll: vi.fn(),
      componentValueOf: (_slot: string, field: string) => field === 'pageSize' ? 20 : false,
      setComponentKnob: vi.fn(), componentSourceOf: vi.fn(), layerValuesOf: vi.fn(),
      componentLayerValuesOf: vi.fn(),
    }),
  }
})
vi.mock('@/composables/usePageSettings', async () => {
  const { ref } = await import('vue')
  return { usePageSettings: () => ({ reset: vi.fn(), isDirty: ref(false) }) }
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
    routes: [{ path: '/trade-discipline', component: TradeDisciplineView }],
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

describe('交易纪律 T5 工作台壳', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    expect(wrapper.text()).toContain('创建第一套规则')
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
    const rule = {
      id: 'rule-1', name: '趋势纪律', status: 'active', latest_version_no: 1,
      management_status: 'active', latest_management_event: null,
      has_pending_management_action: false, effective_status: 'active', effective_event_seq: 1,
      effective_from_trade_date: '2026-08-22',
      effective_version: { version_no: 1, name: '趋势纪律', capital: '100000' },
    }
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
    const rules = ['rule-1', 'rule-2'].map((id, index) => ({
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
    }))
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
})
