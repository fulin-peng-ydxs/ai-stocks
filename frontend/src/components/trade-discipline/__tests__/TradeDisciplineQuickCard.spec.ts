// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TradeDisciplineQuickCard from '@/components/trade-discipline/TradeDisciplineQuickCard.vue'
import {
  resetTradeDisciplineSummaryForTests,
  useTradeDisciplineSummary,
} from '@/composables/useTradeDisciplineSummary'

const getSummary = vi.fn()
const quickSubmit = vi.fn()
const dialogStub = defineComponent({
  props: ['modelValue'],
  template: '<div v-if="modelValue"><slot /><footer><slot name="footer" /></footer></div>',
})

vi.mock('@/api/tradeDiscipline', () => ({
  getTradeDisciplineSummary: (...args: unknown[]) => getSummary(...args),
  quickNoOperationTradeDisciplineCheckin: (...args: unknown[]) => quickSubmit(...args),
}))

const pendingSummary = {
  trade_date: '2026-08-22', total: 1, completed: 0, pending: 1,
  rules: [{
    rule_id: 'rule-1', rule_name: '趋势纪律', version_no: 2,
    effective_from_trade_date: '2026-08-22', checkin_id: null,
    current_revision_no: null, status: null, assessment: null, no_operation: null,
  }],
}

async function mountCard(canSubmit = true) {
  const wrapper = mount(TradeDisciplineQuickCard, {
    props: { canSubmit, tradeDate: '2026-08-22' },
    global: {
      plugins: [ElementPlus],
      stubs: { AppDialog: dialogStub },
      directives: { permission: { mounted: () => undefined } },
    },
  })
  await flushPromises()
  return wrapper
}

describe('TradeDisciplineQuickCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetTradeDisciplineSummaryForTests()
    getSummary.mockResolvedValue(pendingSummary)
    quickSubmit.mockResolvedValue({ idempotent: false })
  })

  it('没有生效规则也能进入账户打卡，不把建规则作为记账前提', async () => {
    getSummary.mockResolvedValue({ ...pendingSummary, total: 0, completed: 0, pending: 0, rules: [] })
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    const wrapper = await mountCard(true)
    await wrapper.findAll('button').find(node => node.text() === '进入交易打卡')!.trigger('click')
    expect(wrapper.emitted('navigate')?.at(-1)).toEqual([{ tab: 'checkin', ruleId: undefined, tradeDate: '2026-08-22' }])
    expect(quickSubmit).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(node => node.text() === '查看规则')!.trigger('click')
    expect(wrapper.emitted('navigate')?.at(-1)).toEqual([{ tab: 'rules' }])
    wrapper.unmount()
  })

  it.each([true, false])('持仓上限不隐藏无操作快捷入口（提交权限：%s）', async (canSubmit) => {
    getSummary.mockResolvedValue({ ...pendingSummary, rules: pendingSummary.rules.map((rule) => ({ ...rule, max_positions: 2 })) })
    const state = useTradeDisciplineSummary()
    await state.refreshSummary('2026-08-22')
    const wrapper = mount(TradeDisciplineQuickCard, {
      props: { canSubmit, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], stubs: { AppDialog: dialogStub }, directives: { permission: {} } },
    })
    await flushPromises()
    const actions = wrapper.get('.quick-rule-actions').findAll('button')
    expect(actions).toHaveLength(canSubmit ? 2 : 1)
    if (canSubmit) {
      expect(actions[0].text()).toBe('今日无操作')
      await actions[0].trigger('click')
      expect(wrapper.find('[data-testid="quick-peak-positions"]').exists()).toBe(false)
      expect(wrapper.text()).toContain('核对本规则，其他规则的打卡状态不变')
    }
    await actions.at(-1)!.trigger('click')
    expect(quickSubmit).not.toHaveBeenCalled()
    expect(wrapper.emitted('navigate')?.at(-1)).toEqual([{ tab: 'checkin', ruleId: 'rule-1', tradeDate: '2026-08-22' }])
  })

  it('快捷入口不再填持仓数，仅提交规则和交易日交由服务端判断', async () => {
    getSummary.mockResolvedValue({ ...pendingSummary, rules: pendingSummary.rules.map((rule) => ({ ...rule, max_positions: 2 })) })
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    const wrapper = await mountCard(true)
    await wrapper.get('.quick-rule-actions button.el-button--primary').trigger('click')
    expect(wrapper.find('[data-testid="quick-peak-positions"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('根据已有持仓核对本规则')
    await wrapper.get('[data-testid="quick-confirm"]').trigger('click')
    await flushPromises()
    expect(quickSubmit).toHaveBeenCalledWith('rule-1', '2026-08-22')
    wrapper.unmount()
  })

  it('展示最新日摘要和待打卡规则，并按维护权限控制快捷动作', async () => {
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    const writable = await mountCard(true)
    expect(writable.text()).toContain('0/1')
    expect(writable.text()).toContain('趋势纪律')
    expect(writable.text()).toContain('今日无操作')
    const progress = writable.get('.quick-progress')
    expect(progress.element.tagName).toBe('DIV')
    expect(progress.attributes('tabindex')).toBeUndefined()
    await progress.trigger('click')
    expect(writable.emitted('navigate')).toBeUndefined()

    writable.unmount()
    const readonly = await mountCard(false)
    expect(readonly.text()).not.toContain('今日无操作')
    expect(readonly.text()).toContain('去打卡')
    expect(readonly.text()).not.toContain('管理规则')
    expect(readonly.text()).not.toContain('查看规则')
    readonly.unmount()
  })

  it('确认后只提交规则和交易日，成功刷新摘要并广播跨入口变更', async () => {
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    getSummary.mockResolvedValueOnce({
      ...pendingSummary,
      completed: 1,
      pending: 0,
      rules: [{
        ...pendingSummary.rules[0], checkin_id: 'checkin-1', current_revision_no: 1,
        status: 'submitted', assessment: 'complied', no_operation: true,
      }],
    })
    quickSubmit.mockResolvedValue({ idempotent: false })
    const wrapper = await mountCard(true)

    await wrapper.get('.quick-rule-actions button.el-button--primary').trigger('click')
    await wrapper.get('[data-testid="quick-confirm"]').trigger('click')
    await flushPromises()

    expect(quickSubmit).toHaveBeenCalledWith('rule-1', '2026-08-22')
    expect(wrapper.text()).toContain('全部完成')
    expect(wrapper.text()).toContain('1/1')
    expect(wrapper.text()).not.toContain('去打卡')
    expect(wrapper.text()).not.toContain('今日无操作')
    const progress = wrapper.get('.quick-progress')
    await progress.trigger('click')
    expect(wrapper.emitted('navigate')).toBeUndefined()
    await wrapper.findAll('button').find((button) => button.text() === '查看记录')!.trigger('click')
    expect(wrapper.emitted('navigate')?.at(-1)).toEqual([{
      tab: 'checkin', ruleId: 'rule-1', tradeDate: '2026-08-22',
    }])
    expect(useTradeDisciplineSummary().latestChange.value).toEqual({
      ruleId: 'rule-1', tradeDate: '2026-08-22', source: 'quick',
    })
  })

  it('409 冲突不覆盖记录，直接引导到正式打卡页面', async () => {
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    quickSubmit.mockRejectedValue({ response: { status: 409, data: { msg: '已有正式记录' } } })
    const wrapper = await mountCard(true)

    await wrapper.get('.quick-rule-actions button.el-button--primary').trigger('click')
    await wrapper.get('[data-testid="quick-confirm"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('navigate')?.at(-1)).toEqual([{
      tab: 'checkin', ruleId: 'rule-1', tradeDate: '2026-08-22',
    }])
  })

  it('两套规则逐套确认，首次完成后另一套保留独立入口和确认上下文', async () => {
    const first = pendingSummary.rules[0]!
    const second = { ...first, rule_id: 'rule-2', rule_name: '分红纪律' }
    const confirmed = { checkin_id: 'ledger:2026-08-22', current_revision_no: 1,
      status: 'submitted', assessment: 'complied', no_operation: true }
    getSummary.mockResolvedValue({ ...pendingSummary, total: 2, pending: 2, rules: [first, second] })
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    const wrapper = await mountCard()
    try {
      expect(wrapper.text()).toContain('0/2')
      await wrapper.findAll('.quick-rule-row')[0]!.get('button.el-button--primary').trigger('click')
      expect(wrapper.text()).toContain('其他规则的打卡状态不变')
      getSummary.mockResolvedValue({ ...pendingSummary, total: 2, completed: 1, pending: 1,
        rules: [{ ...first, ...confirmed }, second] })
      await wrapper.get('[data-testid="quick-confirm"]').trigger('click')
      await flushPromises()
      const rows = wrapper.findAll('.quick-rule-row')
      expect(rows[0]!.text()).toContain('查看记录')
      expect(rows[0]!.text()).not.toContain('今日无操作')
      expect(rows[1]!.text()).toContain('待打卡')
      expect(wrapper.text()).toContain('1/2')
      expect(wrapper.text()).not.toContain('全部完成')
      await rows[1]!.get('button.el-button--primary').trigger('click')
      expect(wrapper.get('.quick-confirm-context strong').text()).toBe('分红纪律')
      getSummary.mockResolvedValue({ ...pendingSummary, total: 2, completed: 2, pending: 0,
        rules: [{ ...first, ...confirmed }, { ...second, ...confirmed }] })
      await wrapper.get('[data-testid="quick-confirm"]').trigger('click')
      await flushPromises()
      expect(quickSubmit.mock.calls).toEqual([['rule-1', '2026-08-22'], ['rule-2', '2026-08-22']])
      expect(wrapper.text()).toContain('2/2')
      expect(wrapper.text()).toContain('全部完成')
    } finally { wrapper.unmount() }
  })
})
