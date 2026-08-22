// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TradeDisciplineQuickCard from '@/components/trade-discipline/TradeDisciplineQuickCard.vue'
import {
  resetTradeDisciplineSummaryForTests,
  useTradeDisciplineSummary,
} from '@/composables/useTradeDisciplineSummary'

const getSummary = vi.fn()
const quickSubmit = vi.fn()

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
  })

  it('展示最新日摘要和待打卡规则，并按维护权限控制快捷动作', async () => {
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    const writable = await mountCard(true)
    expect(writable.text()).toContain('0/1')
    expect(writable.text()).toContain('趋势纪律')
    expect(writable.text()).toContain('无操作履约')

    writable.unmount()
    const readonly = await mountCard(false)
    expect(readonly.text()).not.toContain('无操作履约')
    expect(readonly.text()).toContain('去打卡')
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
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = await mountCard(true)

    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()

    expect(quickSubmit).toHaveBeenCalledWith('rule-1', '2026-08-22')
    expect(wrapper.text()).toContain('全部完成')
    expect(wrapper.text()).toContain('1/1')
    expect(useTradeDisciplineSummary().latestChange.value).toEqual({
      ruleId: 'rule-1', tradeDate: '2026-08-22', source: 'quick',
    })
  })

  it('409 冲突不覆盖记录，直接引导到正式打卡页面', async () => {
    await useTradeDisciplineSummary().refreshSummary('2026-08-22')
    quickSubmit.mockRejectedValue({ response: { status: 409, data: { msg: '已有正式记录' } } })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = await mountCard(true)

    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('navigate')?.at(-1)).toEqual([{
      tab: 'checkin', ruleId: 'rule-1', tradeDate: '2026-08-22',
    }])
  })
})
