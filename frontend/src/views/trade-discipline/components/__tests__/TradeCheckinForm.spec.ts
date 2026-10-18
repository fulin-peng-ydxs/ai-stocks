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
const PartialOperationStub = defineComponent({
  name: 'TradeOperationEditor',
  emits: ['update:modelValue'],
  template: '<button type="button" aria-label="填写混合操作" @click="$emit(\'update:modelValue\', operations)">填写混合操作</button>',
  setup() {
    return {
      operations: [{ ...operation, compliance_status: 'complied', display_order: 1 }],
    }
  },
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

  it('新增买入无需逐项填写人工条件，规则默认值随正式打卡提交', async () => {
    getContext.mockResolvedValue({ ...emptyContext, version: {
      ...version, stock_rules: [{ ...version.stock_rules[0], loss_filter: 'exclude', st_risk_filter: 'exclude' }],
    } })
    const wrapper = mountForm({ StockOptionSelect: true })
    await flushPromises()
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    wrapper.findComponent({ name: 'StockOptionSelect' }).vm.$emit('update:modelValue', {
      code: '000001.SZ', name: '平安银行', is_st: false, st_as_of_date: '2026-08-22',
    })
    await flushPromises()
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({
      assessment: 'complied', no_operation: false,
      operations: [expect.objectContaining({
        stock_code: '000001.SZ', stock_rule_id: 'stock-rule-1', action_rule_id: 'action-buy-1',
        loss_status: 'no', st_risk_status: 'no',
      })],
    }))
  })

  it('限制持仓时无操作仍需填峰值，超限不能选择已履约', async () => {
    getContext.mockResolvedValue({ ...emptyContext, version: { ...version, max_positions: 2 } })
    const wrapper = mountForm({ ViolationReasonCombobox: ReasonStub })
    await flushPromises()
    wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('change', true)
    wrapper.findComponent({ name: 'ElInputNumber' }).vm.$emit('update:modelValue', null)
    await wrapper.vm.$nextTick()
    await wrapper.get('button.el-button--primary').trigger('click')
    expect(submitCheckin).not.toHaveBeenCalled()
    const input = wrapper.get('[data-testid="checkin-peak-positions"] input')
    await input.setValue('3')
    await input.trigger('change')
    expect(wrapper.text()).toContain('超过本套规则上限 2 只')
    expect(wrapper.findComponent({ name: 'ElSegmented' }).props('options').find((option: { value: string }) => option.value === 'complied').disabled).toBe(true)
    await wrapper.get('[aria-label="选择原因"]').trigger('click')
    await wrapper.findAll('textarea')[0].setValue('当日持仓超限')
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({ peak_positions: 3, no_operation: true, assessment: 'breached' }))
  })

  it.each([
    { filter: 'exclude', st: true, blocked: true },
    { filter: 'only', st: false, blocked: true },
    { filter: 'any', st: true, blocked: false },
    { filter: 'exclude', st: null, blocked: false },
  ])('按规则 $filter 和ST事实 $st 限制整体已履约', async ({ filter, st, blocked }) => {
    getContext.mockResolvedValue({ ...emptyContext, version: {
      ...version, stock_rules: [{ ...version.stock_rules[0], st_filter: filter }],
    } })
    const stub = defineComponent({
      emits: ['update:modelValue'],
      template: '<button aria-label="填写操作" @click="$emit(\'update:modelValue\', operation)">填写操作</button>',
      setup() { return { operation: [{ ...operation, is_st: st }] } },
    })
    const wrapper = mountForm({ TradeOperationEditor: stub, ViolationReasonCombobox: ReasonStub })
    await flushPromises()
    await wrapper.get('[aria-label="填写操作"]').trigger('click')
    const selector = wrapper.findComponent({ name: 'ElSegmented' })
    expect(selector.props('options').find((option: { value: string }) => option.value === 'complied').disabled).toBe(blocked)
    expect(selector.props('modelValue')).toBe(blocked ? 'breached' : 'complied')
  })

  it('历史违规自评保留只读快照，进入修正才限制已履约，取消仍恢复原记录', async () => {
    getContext.mockResolvedValue({ ...emptyContext, version: { ...version, max_positions: 2 }, checkin: { ...saved, peak_positions: 3 } })
    const wrapper = mountForm({ ViolationReasonCombobox: ReasonStub })
    await flushPromises()
    const selector = wrapper.findComponent({ name: 'ElSegmented' })
    expect(selector.props('modelValue')).toBe('complied')
    await wrapper.findAll('button').find((button) => button.text() === '修正打卡')!.trigger('click')
    expect(selector.props('modelValue')).toBe('breached')
    await wrapper.findAll('button').find((button) => button.text() === '取消修正')!.trigger('click')
    expect(selector.props('modelValue')).toBe('complied')
    expect(amendCheckin).not.toHaveBeenCalled()
  })

  it('首次填报默认取规则持仓上限且不产生未保存修改，可直接按默认数量提交', async () => {
    getContext.mockResolvedValue({ ...emptyContext, version: { ...version, max_positions: 2 } })
    const wrapper = mountForm()
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>('[data-testid="checkin-peak-positions"] input').element.value).toBe('2')
    expect((wrapper.vm as any).isDirty()).toBe(false)
    wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('change', true)
    await wrapper.vm.$nextTick()
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({ peak_positions: 2, no_operation: true }))
  })

  it('切换规则或交易日按新上下文初始化，无持仓上限时不沿用旧数量', async () => {
    getContext.mockResolvedValueOnce({ ...emptyContext, version: { ...version, max_positions: 2 } })
      .mockResolvedValueOnce({ ...emptyContext, version: { ...version, rule_id: 'rule-2', max_positions: 4 } })
      .mockResolvedValueOnce({ ...emptyContext, trade_date: '2026-08-24' })
    const wrapper = mountForm()
    await flushPromises()
    const input = wrapper.get('[data-testid="checkin-peak-positions"] input')
    await input.setValue('1')
    await input.trigger('change')
    await wrapper.setProps({ ruleId: 'rule-2' })
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>('[data-testid="checkin-peak-positions"] input').element.value).toBe('4')
    expect((wrapper.vm as any).isDirty()).toBe(false)
    await wrapper.setProps({ tradeDate: '2026-08-24' })
    await flushPromises()
    expect(wrapper.find('[data-testid="checkin-holding-count"]').exists()).toBe(false)
    expect((wrapper.vm as any).isDirty()).toBe(false)
  })

  it.each([undefined, null, 0, 1])('已有持仓数量 %s 在查看、修正和取消时均保留原快照', async (peakPositions) => {
    getContext.mockResolvedValue({
      ...emptyContext, version: { ...version, max_positions: 2 },
      checkin: { ...saved, peak_positions: peakPositions },
    })
    const wrapper = mountForm()
    await flushPromises()
    const inputValue = () => wrapper.get<HTMLInputElement>('[data-testid="checkin-peak-positions"] input').element.value
    const expected = peakPositions == null ? '' : String(peakPositions)
    expect(inputValue()).toBe(expected)
    await wrapper.findAll('button').find((button) => button.text() === '修正打卡')!.trigger('click')
    expect(inputValue()).toBe(expected)
    expect((wrapper.vm as any).isDirty()).toBe(false)
    const input = wrapper.get('[data-testid="checkin-peak-positions"] input')
    await input.setValue('3')
    await input.trigger('change')
    await wrapper.findAll('button').find((button) => button.text() === '取消修正')!.trigger('click')
    expect(inputValue()).toBe(expected)
    expect(amendCheckin).not.toHaveBeenCalled()
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
    expect(wrapper.findAll('button').some((button) => button.text() === '修正打卡')).toBe(true)
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
    expect(amendButton!.classes()).toContain('el-button--primary')
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
    expect(submitButton.element.closest('.checkin-head__facts')).not.toBeNull()
    expect(wrapper.find('.checkin-actions').exists()).toBe(false)
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

  it('提交“部分履约”时允许单笔操作状态并复用整体未履约原因', async () => {
    getContext.mockResolvedValueOnce(emptyContext).mockResolvedValue({ ...emptyContext, checkin: saved })
    const wrapper = mountForm({
      TradeOperationEditor: PartialOperationStub,
      ViolationReasonCombobox: ReasonStub,
    })
    await flushPromises()
    wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'partial')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent({ name: 'ElCheckbox' }).props('disabled')).toBe(true)
    await wrapper.get('[aria-label="填写混合操作"]').trigger('click')
    await wrapper.get('[aria-label="选择原因"]').trigger('click')
    await wrapper.findAll('textarea')[0].setValue('选股规则存在偏差，操作本身已履约')
    await wrapper.get('button.el-button--primary').trigger('click')
    await flushPromises()
    expect(submitCheckin).toHaveBeenCalledWith(expect.objectContaining({
      assessment: 'partial', no_operation: false, reason_code: 'impulsive',
      violation_detail: '选股规则存在偏差，操作本身已履约',
      operations: [expect.objectContaining({ compliance_status: 'complied', display_order: 1 })],
    }))
  })

  it('部分履约仍要求至少一条操作且不能选择今日无操作', async () => {
    const wrapper = mountForm({ ViolationReasonCombobox: ReasonStub })
    await flushPromises()
    wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'partial')
    await wrapper.vm.$nextTick()
    expect(wrapper.findComponent({ name: 'ElCheckbox' }).props('disabled')).toBe(true)
    await wrapper.get('[aria-label="选择原因"]').trigger('click')
    await wrapper.findAll('textarea')[0].setValue('选股规则存在偏差')
    await wrapper.findAll('button').find((button) => button.text() === '提交打卡')!.trigger('click')
    expect(submitCheckin).not.toHaveBeenCalled()
  })

  it('履约判断区域提供与操作事实对称的标题和说明', async () => {
    const wrapper = mountForm()
    await flushPromises()
    const section = wrapper.get('.checkin-section')
    expect(section.get('h4').text()).toBe('履约判断')
    expect(section.text()).toContain('实际交易在下方单独记录')
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
