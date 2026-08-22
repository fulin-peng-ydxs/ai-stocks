// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { defineComponent } from 'vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import TradeCheckinRevisionDrawer from '@/views/trade-discipline/components/TradeCheckinRevisionDrawer.vue'
import type { CheckinHistoryRow } from '@/api/tradeDiscipline'

const getRevision = vi.fn()
vi.mock('@/api/tradeDiscipline', () => ({
  getTradeDisciplineCheckinRevision: (...args: unknown[]) => getRevision(...args),
}))

const row: CheckinHistoryRow = {
  id: 'checkin-1', rule_id: 'rule-1', rule_name: '趋势纪律', trade_date: '2026-08-22',
  status: 'amended', current_revision_no: 2, version_no: 3, assessment: 'breached',
  no_operation: false, reason_name_snapshot: '冲动交易', operation_count: 1,
  submitted_at: '2026-08-22T18:00:00', amended_at: '2026-08-22T19:00:00', updated_at: '2026-08-22T19:00:00',
}
const revision = {
  checkin_id: 'checkin-1', revision_no: 2, current_revision_no: 2, rule_id: 'rule-1',
  rule_name: '趋势纪律', version_no: 3, trade_date: '2026-08-22', checkin_status: 'amended',
  assessment: 'breached', no_operation: true, reason_code: 'impulsive', reason_id: null,
  reason_name_snapshot: '冲动交易', violation_detail: '偏离计划', review_note: '盘后复核',
  operations: [], financial_complete: true, created_at: '2026-08-22T19:00:00',
  rule_version: {
    rule_id: 'rule-1', version_no: 3, name: '趋势纪律', capital: '100000',
    stock_rules: [{ detail_id: 'sr-1', name: '龙头', max_capital: '50000', content: '只做龙头', display_order: 1, enabled: true }],
    action_rules: [{ detail_id: 'ar-1', name: '突破买入', action_type: 'buy', action_subtype: 'open_position', content: '放量突破', display_order: 1, enabled: true }],
  },
}

const DrawerStub = defineComponent({
  name: 'PageDrawer', props: ['modelValue'], emits: ['update:modelValue'],
  template: '<div v-if="modelValue"><slot/><footer><slot name="footer"/></footer></div>',
})

function mountDrawer(canSubmit = true) {
  return mount(TradeCheckinRevisionDrawer, {
    props: { modelValue: true, row, canSubmit },
    global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { PageDrawer: DrawerStub } },
  })
}

describe('TradeCheckinRevisionDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getRevision.mockImplementation(async (_id: string, revisionNo: number) => ({
      ...revision, revision_no: revisionNo,
    }))
  })

  it('完整展示当前规则与履约快照，并允许从当前修订发起修正', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    expect(getRevision).toHaveBeenCalledWith('checkin-1', 2)
    expect(wrapper.text()).toContain('规则版本快照')
    expect(wrapper.text()).toContain('只做龙头')
    expect(wrapper.text()).toContain('财务字段完整')
    await wrapper.findAll('button').find((button) => button.text() === '发起修正')!.trigger('click')
    expect(wrapper.emitted('amend')).toEqual([[{ ruleId: 'rule-1', tradeDate: '2026-08-22' }]])
  })

  it('切换旧修订后保持只读并禁止发起修正', async () => {
    const wrapper = mountDrawer()
    await flushPromises()
    wrapper.findComponent(AppFilterSelect).vm.$emit('change', '1')
    await flushPromises()
    expect(getRevision).toHaveBeenLastCalledWith('checkin-1', 1)
    expect(wrapper.text()).toContain('历史修订 · 只读')
    const amend = wrapper.findAll('button').find((button) => button.text() === '发起修正')!
    expect(amend.attributes('disabled')).toBeDefined()
  })

  it('无维护权限时只展示快照且不渲染修正命令', async () => {
    const wrapper = mountDrawer(false)
    await flushPromises()
    expect(wrapper.findAll('button').some((button) => button.text() === '发起修正')).toBe(false)
    expect(wrapper.text()).toContain('规则版本快照')
  })
})
