// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { defineComponent } from 'vue'
import TradeCheckinForm from '@/views/trade-discipline/components/TradeCheckinForm.vue'

const getContext = vi.fn()
const submitCheckin = vi.fn()
const amendCheckin = vi.fn()
vi.mock('@/api/tradeDiscipline', () => ({
  getTradeDisciplineCheckinContext: (...args: unknown[]) => getContext(...args),
  submitTradeDisciplineCheckin: (...args: unknown[]) => submitCheckin(...args),
  amendTradeDisciplineCheckin: (...args: unknown[]) => amendCheckin(...args),
  listTradeDisciplineReasons: vi.fn(async () => []),
  deleteTradeDisciplineReason: vi.fn(),
  searchTradeDisciplineStocks: vi.fn(),
}))

const version = {
  rule_id: 'rule-1', version_no: 2, name: '趋势纪律', capital: '100000',
  stock_rules: [{ detail_id: 'stock-rule-1', name: '龙头', max_capital: null, content: null, display_order: 1, enabled: true }],
  action_rules: [{ detail_id: 'action-buy-1', name: '突破买入', action_type: 'buy', action_subtype: 'open_position', content: null, display_order: 1, enabled: true }],
}
const emptyContext = { trade_date: '2026-08-22', version, checkin: null }
const saved = {
  checkin_id: 'checkin-1', revision_no: 1, current_revision_no: 1,
  rule_id: 'rule-1', rule_name: '趋势纪律', version_no: 2, trade_date: '2026-08-22',
  checkin_status: 'submitted', assessment: 'complied', no_operation: true,
  reason_code: null, reason_id: null, reason_name_snapshot: null,
  violation_detail: null, review_note: null, operations: [], financial_complete: true,
}

const ReasonStub = defineComponent({
  name: 'ViolationReasonCombobox',
  emits: ['update:modelValue'],
  template: '<button type="button" aria-label="选择原因" @click="$emit(\'update:modelValue\', { kind: \'builtin\', code: \'impulsive\', name: \'冲动交易\' })">选择原因</button>',
})
const operation = {
  stock_code: '000001.SZ', stock_name_snapshot: '平安银行', side: 'buy',
  stock_rule_id: 'stock-rule-1', action_rule_id: 'action-buy-1', price: null,
  quantity: null, amount: null, fee: null, operated_at: null, note: null, display_order: 1,
}
const OperationStub = defineComponent({
  name: 'TradeOperationEditor',
  emits: ['update:modelValue'],
  template: '<button type="button" aria-label="填写操作" @click="$emit(\'update:modelValue\', [operation])">填写操作</button>',
  setup() { return { operation } },
})

function mountForm(
  stubs: Record<string, unknown> = {},
  props: Partial<{ ruleId: string; tradeDate: string; canSubmit: boolean }> = {},
) {
  return mount(TradeCheckinForm, {
    props: { ruleId: 'rule-1', tradeDate: '2026-08-22', canSubmit: true, ...props },
    global: {
      plugins: [ElementPlus], directives: { permission: {} },
      stubs: {
        TradeDatePicker: defineComponent({ props: ['modelValue'], template: '<input aria-label="交易日" :value="modelValue" />' }),
        ...stubs,
      },
    },
  })
}

describe('TradeCheckinForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getContext.mockResolvedValue(emptyContext)
    submitCheckin.mockResolvedValue(saved)
    amendCheckin.mockResolvedValue({ ...saved, revision_no: 2, current_revision_no: 2, checkin_status: 'amended' })
  })

  it('提交“已履约 + 今日无操作”并在成功后刷新上下文', async () => {
    getContext.mockResolvedValueOnce(emptyContext).mockResolvedValue({ ...emptyContext, checkin: saved })
    const wrapper = mountForm()
    await flushPromises()
    const checkbox = wrapper.findComponent({ name: 'ElCheckbox' })
    checkbox.vm.$emit('change', true)
    await wrapper.vm.$nextTick()
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({
      rule_id: 'rule-1', trade_date: '2026-08-22', assessment: 'complied',
      no_operation: true, reason_code: null, reason_id: null, reason_text: null,
      operations: [],
    }))
    expect(wrapper.emitted('submitted')).toHaveLength(1)
    expect(wrapper.text()).toContain('已提交 · r1')
  })

  it('提交校验失败时自动展开对应操作卡', async () => {
    const wrapper = mountForm()
    await flushPromises()
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const toggle = wrapper.get('[data-testid="operation-card-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')

    await wrapper.findAll('button').find((button) => button.text() === '提交打卡')!.trigger('click')
    await wrapper.vm.$nextTick()
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-testid="operation-card-editor"]').exists()).toBe(true)
    expect(submitCheckin).not.toHaveBeenCalled()
  })

  it('已有打卡以 expected_revision 修正且不改变绑定版本', async () => {
    const decoratedOperation = {
      ...operation,
      id: 'old-operation-id',
      stock_rule_name: '龙头',
      action_rule_name: '突破买入',
      action_subtype: 'open_position',
      financial_complete: false,
    }
    getContext.mockResolvedValue({
      ...emptyContext,
      checkin: { ...saved, no_operation: false, operations: [decoratedOperation] },
    })
    const wrapper = mountForm()
    await flushPromises()
    const amendButton = wrapper.findAll('button').find((button) => button.text().includes('修正打卡'))
    expect(amendButton).toBeTruthy()
    await amendButton!.trigger('click')
    await wrapper.get('textarea').setValue('盘后复核')
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(amendCheckin).toHaveBeenCalledWith('checkin-1', expect.objectContaining({
      expected_revision: 1, review_note: '盘后复核', no_operation: false,
      operations: [expect.objectContaining({ id: null, stock_code: '000001.SZ' })],
    }))
    const amendedOperation = amendCheckin.mock.calls[0][1].operations[0]
    expect(amendedOperation).not.toHaveProperty('stock_rule_name')
    expect(amendedOperation).not.toHaveProperty('financial_complete')
  })

  it('修正态无变化时禁用提交并可取消恢复当前修订快照', async () => {
    getContext.mockResolvedValue({
      ...emptyContext,
      checkin: { ...saved, review_note: '当前修订说明' },
    })
    const wrapper = mountForm()
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '修正打卡')!.trigger('click')

    const submitButton = wrapper.findAll('button').find((button) => button.text() === '提交修正')!
    expect(submitButton.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('当前内容与最新修订一致；修改后才可提交')
    await submitButton.trigger('click')
    expect(amendCheckin).not.toHaveBeenCalled()

    await wrapper.get('textarea').setValue('尚未提交的修改')
    expect(submitButton.attributes('disabled')).toBeUndefined()
    await wrapper.findAll('button').find((button) => button.text() === '取消修正')!.trigger('click')
    expect(wrapper.get('textarea').element.value).toBe('当前修订说明')
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').some((button) => button.text() === '修正打卡')).toBe(true)
  })

  it('历史入口可等待上下文加载完成后直接进入当前修订编辑态', async () => {
    getContext.mockResolvedValue({ ...emptyContext, checkin: saved })
    const wrapper = mountForm()
    await (wrapper.vm as any).startAmend()
    await flushPromises()
    expect(getContext).toHaveBeenCalled()
    expect(wrapper.findAll('button').some((button) => button.text() === '修正打卡')).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === '提交修正')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === '取消修正')).toBe(true)
    expect(wrapper.findAll('button').find((button) => button.text() === '提交修正')?.attributes('disabled')).toBeDefined()
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
  })

  it.each([
    { assessment: 'complied', breached: false },
    { assessment: 'breached', breached: true },
  ])('提交“$assessment + 有操作”组合', async ({ breached }) => {
    getContext.mockResolvedValueOnce(emptyContext).mockResolvedValue({ ...emptyContext, checkin: saved })
    const wrapper = mountForm({
      TradeOperationEditor: OperationStub,
      ViolationReasonCombobox: ReasonStub,
    })
    await flushPromises()
    await wrapper.get('[aria-label="填写操作"]').trigger('click')
    if (breached) {
      wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'breached')
      await wrapper.vm.$nextTick()
      await wrapper.get('[aria-label="选择原因"]').trigger('click')
      await wrapper.findAll('textarea')[0].setValue('偏离计划的具体过程')
    }
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({
      assessment: breached ? 'breached' : 'complied',
      no_operation: false,
      reason_code: breached ? 'impulsive' : null,
      violation_detail: breached ? '偏离计划的具体过程' : null,
      operations: [expect.objectContaining({ stock_code: '000001.SZ', display_order: 1 })],
    }))
  })

  it('提交“未履约 + 今日无操作”组合并保持原因单选', async () => {
    getContext.mockResolvedValueOnce(emptyContext).mockResolvedValue({ ...emptyContext, checkin: saved })
    const wrapper = mountForm({ ViolationReasonCombobox: ReasonStub })
    await flushPromises()
    wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'breached')
    wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('change', true)
    await wrapper.vm.$nextTick()
    await wrapper.get('[aria-label="选择原因"]').trigger('click')
    await wrapper.findAll('textarea')[0].setValue('无操作但仍违反当日纪律')
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({
      assessment: 'breached', no_operation: true, reason_code: 'impulsive', operations: [],
    }))
  })

  it('未提交修改离开时只提供放弃或继续编辑两个结果', async () => {
    const wrapper = mountForm()
    await flushPromises()
    await wrapper.get('textarea').setValue('尚未提交')
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    await expect((wrapper.vm as any).requestLeave()).resolves.toBe(false)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as never)
    await expect((wrapper.vm as any).requestLeave()).resolves.toBe(true)
    expect(wrapper.get('textarea').element.value).toBe('')
  })

  it('有查看权限但无提交权限时保持只读且不渲染写命令', async () => {
    getContext.mockResolvedValue({ ...emptyContext, checkin: saved })
    const wrapper = mountForm({}, { canSubmit: false })
    await flushPromises()
    expect(wrapper.text()).toContain('当前账号仅可查看')
    expect(wrapper.findAll('button').some((button) => button.text() === '修正打卡')).toBe(false)
    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
  })
})
