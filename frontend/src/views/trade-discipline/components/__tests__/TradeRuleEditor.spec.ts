// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import TradeRuleEditor from '@/views/trade-discipline/components/TradeRuleEditor.vue'

const api = vi.hoisted(() => ({
  get: vi.fn(), open: vi.fn(), save: vi.fn(), discard: vi.fn(), publish: vi.fn(),
  archive: vi.fn(), restore: vi.fn(), copy: vi.fn(), remove: vi.fn(), types: vi.fn(),
  deleteType: vi.fn(),
}))

vi.mock('@/api/tradeDiscipline', () => ({
  getTradeDisciplineRule: (...args: unknown[]) => api.get(...args),
  openTradeDisciplineRuleDraft: (...args: unknown[]) => api.open(...args),
  saveTradeDisciplineRuleDraft: (...args: unknown[]) => api.save(...args),
  discardTradeDisciplineRuleDraft: (...args: unknown[]) => api.discard(...args),
  publishTradeDisciplineRule: (...args: unknown[]) => api.publish(...args),
  archiveTradeDisciplineRule: (...args: unknown[]) => api.archive(...args),
  restoreTradeDisciplineRule: (...args: unknown[]) => api.restore(...args),
  copyTradeDisciplineRule: (...args: unknown[]) => api.copy(...args),
  deleteTradeDisciplineRule: (...args: unknown[]) => api.remove(...args),
  listTradeDisciplineRuleTypes: (...args: unknown[]) => api.types(...args),
  deleteTradeDisciplineRuleType: (...args: unknown[]) => api.deleteType(...args),
}))

function draft(revision = 2) {
  return {
    rule_id: 'rule-1', draft_revision: revision, name: '趋势纪律', capital: '100000',
    source_version_no: 1,
    stock_rules: [
      { detail_id: 's1', name: '突破', max_capital: '40000', content: '第一行\n第二行', display_order: 1, enabled: true },
      { detail_id: 's2', name: '回踩', max_capital: '30000', content: '等待确认', display_order: 2, enabled: false },
    ],
    action_rules: [
      { detail_id: 'a1', name: '建仓', action_type: 'buy', action_subtype: 'open_position', content: '买入', display_order: 1, enabled: true },
      { detail_id: 'a2', name: '清仓', action_type: 'sell', action_subtype: 'liquidate', content: '卖出', display_order: 2, enabled: true },
    ],
  }
}

function detail() {
  return {
    id: 'rule-1', name: '趋势纪律', status: 'active', latest_version_no: 1,
    draft_revision: 2, proposed_name: '趋势纪律', management_status: 'active',
    latest_management_event: null, has_pending_management_action: false,
    effective_status: 'active', effective_event_seq: 1, effective_from_trade_date: '2026-08-21',
    effective_version: { ...draft(), version_no: 1 },
    latest_version: { ...draft(), version_no: 1 }, draft: draft(),
  }
}

async function mountEditor(canManage = true) {
  const wrapper = mount(TradeRuleEditor, {
    props: { ruleId: 'rule-1', tradeDate: '2026-08-21', canManage },
    global: { plugins: [ElementPlus], directives: { permission: {} } },
  })
  await flushPromises()
  return wrapper
}

function field(wrapper: ReturnType<typeof mount>, label: string) {
  const item = wrapper.findAll('.el-form-item').find((node) => node.text().includes(label))
  if (!item) throw new Error(`missing field: ${label}`)
  return item
}

function leaveDecisionButtons(wrapper: ReturnType<typeof mount>) {
  return wrapper.findComponent({ name: 'ElDialog' }).findAll('button')
}

describe('TradeRuleEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.get.mockResolvedValue(detail())
    api.types.mockResolvedValue([
      { name: 'open_position', label: '建仓', action_type: 'buy', builtin: true },
      { name: 'add_position', label: '加仓', action_type: 'buy', builtin: true },
      { name: 'liquidate', label: '清仓', action_type: 'sell', builtin: true },
      { name: 'reduce_position', label: '减仓', action_type: 'sell', builtin: true },
      { name: '趋势止盈', action_type: 'sell', builtin: false },
    ])
    api.deleteType.mockResolvedValue({ name: '趋势止盈', action_type: 'sell' })
    api.save.mockImplementation(async (_id, payload) => ({ ...draft(payload.expected_revision + 1), ...payload }))
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('保存时保留换行、启用态和调整后的展示顺序', async () => {
    const wrapper = await mountEditor()
    await wrapper.get('[aria-label="下移选股规则"]').trigger('click')
    await wrapper.findAll('[data-testid="stock-rule-card"]')[0]!
      .get('[data-testid="rule-card-toggle"]').trigger('click')
    const textareas = wrapper.findAll('textarea')
    await textareas[0].setValue('第一行\n\n第三行')
    await wrapper.get('.rule-editor__footer .el-button:nth-last-child(2)').trigger('click')
    await flushPromises()

    const payload = api.save.mock.calls[0][1]
    expect(payload.expected_revision).toBe(2)
    expect(payload.stock_rules.map((item: any) => item.detail_id)).toEqual(['s2', 's1'])
    expect(payload.stock_rules[0].enabled).toBe(false)
    expect(payload.stock_rules[0].content).toBe('第一行\n\n第三行')
  })

  it('未保存三选明确提供三个动作，并按继续、放弃和保存结果返回', async () => {
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('临时名称')
    const continueResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    await leaveDecisionButtons(wrapper)[0].trigger('click')
    expect(await continueResult).toBe(false)
    expect((wrapper.vm as any).isDirty()).toBe(true)

    const discardResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    const buttons = leaveDecisionButtons(wrapper)
    expect(buttons.map((button) => button.text())).toEqual(['继续编辑', '放弃修改', '保存草稿'])
    await buttons[1].trigger('click')
    expect(await discardResult).toBe(true)
    expect((wrapper.vm as any).isDirty()).toBe(false)
    expect(field(wrapper, '规则名称').get('input').element.value).toBe('趋势纪律')

    await field(wrapper, '规则名称').get('input').setValue('保存后离开')
    const saveResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    await leaveDecisionButtons(wrapper)[2].trigger('click')
    expect(await saveResult).toBe(true)
    expect(api.save).toHaveBeenCalledWith('rule-1', expect.objectContaining({
      name: '保存后离开', expected_revision: 2,
    }))
  })

  it('重置恢复最近保存内容且不放弃已保存草稿', async () => {
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('临时名称')

    const resetButton = wrapper.findAll('.rule-editor__footer .el-button')
      .find((button) => button.text() === '重置')!
    await resetButton.trigger('click')

    expect(field(wrapper, '规则名称').get('input').element.value).toBe('趋势纪律')
    expect((wrapper.vm as any).isDirty()).toBe(false)
    expect(api.discard).not.toHaveBeenCalled()
  })

  it('三选中的保存草稿失败时不放行且保留当前输入', async () => {
    api.save.mockRejectedValueOnce(new Error('save failed'))
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('保存失败也不能丢')
    const leaveResult = (wrapper.vm as any).requestLeave()
    await flushPromises()
    await leaveDecisionButtons(wrapper)[2].trigger('click')
    await flushPromises()

    expect(api.save).toHaveBeenCalledTimes(1)
    expect((wrapper.vm as any).isDirty()).toBe(true)
    expect(field(wrapper, '规则名称').get('input').element.value).toBe('保存失败也不能丢')
    expect(leaveDecisionButtons(wrapper).map((button) => button.text()))
      .toEqual(['继续编辑', '放弃修改', '保存草稿'])

    await leaveDecisionButtons(wrapper)[0].trigger('click')
    await expect(leaveResult).resolves.toBe(false)
  })

  it('保存并启用先保存当前修改，再使用新修订号发布', async () => {
    api.publish.mockResolvedValue({ changed: true, rule_id: 'rule-1', version_no: 2, effective_from_trade_date: '2026-08-24' })
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('趋势纪律 v2')
    await wrapper.get('.rule-editor__footer .el-button:last-child').trigger('click')
    await flushPromises()

    expect(api.save).toHaveBeenCalledTimes(1)
    expect(api.publish).toHaveBeenCalledWith('rule-1', 3)
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('放弃已保存草稿后重新读取双状态详情', async () => {
    api.discard.mockResolvedValue({})
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as any)
    const wrapper = await mountEditor()
    const discardButton = wrapper.findAll('.rule-editor__footer .el-button')
      .find((button) => button.text() === '放弃草稿')!
    await discardButton.trigger('click')
    await flushPromises()

    expect(api.discard).toHaveBeenCalledWith('rule-1')
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('复制时明确区分草稿与正式版本来源', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    api.copy.mockResolvedValue({ id: 'rule-copy' })
    const wrapper = await mountEditor()

    confirm.mockResolvedValueOnce('confirm' as any)
    await wrapper.get('.rule-editor__commands .el-button:first-child').trigger('click')
    await flushPromises()
    expect(api.copy).toHaveBeenLastCalledWith('rule-1', 'draft')

    confirm.mockRejectedValueOnce('cancel')
    await wrapper.get('.rule-editor__commands .el-button:first-child').trigger('click')
    await flushPromises()
    expect(api.copy).toHaveBeenLastCalledWith('rule-1', 'published')
  })

  it('买入卖出分组展示，并可复制卡片及复用可输入类型', async () => {
    const wrapper = await mountEditor()

    expect(wrapper.get('[data-testid="buy-rule-group"]').text()).toContain('买入规则')
    expect(wrapper.get('[data-testid="sell-rule-group"]').text()).toContain('卖出规则')
    expect(wrapper.find('[data-testid="action-rule-side-select"]').exists()).toBe(false)

    await wrapper.get('[aria-label="复制买卖规则"]').trigger('click')
    expect(wrapper.findAll('[data-testid="action-rule-card"]')).toHaveLength(3)
    expect((wrapper.get('[data-testid="action-rule-name-input"]').element as HTMLInputElement).value)
      .toBe('建仓-副本')

    await wrapper.get('[data-testid="sell-rule-group"]')
      .get('[data-testid="rule-card-toggle"]').trigger('click')
    const sellSelect = wrapper.findAllComponents({ name: 'ElSelect' })
      .find((select) => select.props('modelValue') === 'liquidate')!
    sellSelect.vm.$emit('update:modelValue', '趋势止盈')
    await wrapper.vm.$nextTick()
    expect((wrapper.vm as any).isDirty()).toBe(true)
  })

  it('默认类型按方向展示且自定义类型可从下拉项删除', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    api.types
      .mockResolvedValueOnce([
        { name: 'open_position', label: '建仓', action_type: 'buy', builtin: true },
        { name: 'add_position', label: '加仓', action_type: 'buy', builtin: true },
        { name: 'liquidate', label: '清仓', action_type: 'sell', builtin: true },
        { name: 'reduce_position', label: '减仓', action_type: 'sell', builtin: true },
        { name: '趋势止盈', action_type: 'sell', builtin: false },
      ])
      .mockResolvedValue([
        { name: 'open_position', label: '建仓', action_type: 'buy', builtin: true },
        { name: 'add_position', label: '加仓', action_type: 'buy', builtin: true },
        { name: 'liquidate', label: '清仓', action_type: 'sell', builtin: true },
        { name: 'reduce_position', label: '减仓', action_type: 'sell', builtin: true },
      ])
    const wrapper = mount(TradeRuleEditor, {
      attachTo: document.body,
      props: { ruleId: 'rule-1', tradeDate: '2026-08-21', canManage: true },
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('建仓与加仓条件')
    expect(wrapper.text()).toContain('止盈、止损与减仓条件')
    await wrapper.get('[data-testid="sell-rule-group"]')
      .get('[data-testid="rule-card-toggle"]').trigger('click')
    await wrapper.get('[data-testid="sell-rule-group"] .el-select__wrapper').trigger('click')
    await flushPromises()

    const deleteButtons = Array.from(
      document.body.querySelectorAll('[aria-label="删除自定义买卖类型"]'),
    )
    expect(deleteButtons).toHaveLength(1)
    await new DOMWrapper(deleteButtons[0] as Element).trigger('click')
    await flushPromises()
    expect(api.deleteType).toHaveBeenCalledWith('趋势止盈')
    expect(api.types).toHaveBeenCalledTimes(2)
  })

  it('快速切换规则时忽略迟到的旧详情响应', async () => {
    let resolveFirst!: (value: ReturnType<typeof detail>) => void
    api.get
      .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({
        ...detail(),
        id: 'rule-2',
        name: '第二条规则',
        draft: { ...draft(), rule_id: 'rule-2', name: '第二条规则' },
      })
    const wrapper = mount(TradeRuleEditor, {
      props: { ruleId: 'rule-1', tradeDate: '2026-08-21', canManage: true },
      global: { plugins: [ElementPlus], directives: { permission: {} } },
    })
    await wrapper.setProps({ ruleId: 'rule-2' })
    await flushPromises()
    resolveFirst(detail())
    await flushPromises()

    expect(wrapper.get('.app-section-title').text()).toBe('第二条规则')
  })

  it.each([
    ['当前正式版本', { management_status: 'active', effective_status: 'active' }],
    ['归档版本', { management_status: 'archived', effective_status: 'archived' }],
  ])('%s 不渲染明细增删和排序控件，启停开关保持禁用', async (_label, state) => {
    api.get.mockResolvedValue({
      ...detail(), ...state, draft: null, draft_revision: null,
    })
    const wrapper = await mountEditor()

    expect(wrapper.find('[aria-label="上移选股规则"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="删除买卖规则"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('添加选股规则')
    expect(wrapper.text()).not.toContain('添加买卖规则')
    expect(wrapper.findAll('.el-switch').every((node) => node.classes().includes('is-disabled'))).toBe(true)
    expect((wrapper.get('[data-testid="rule-capital-input"]').element as HTMLInputElement).disabled)
      .toBe(true)
    await wrapper.get('[data-testid="stock-rule-card"] [data-testid="rule-card-toggle"]')
      .trigger('click')
    expect((wrapper.get('[data-testid="stock-rule-capital-input"]').element as HTMLInputElement).disabled)
      .toBe(true)
  })

  it('只有查看权限时即使存在工作草稿也不能修改明细结构或启停态', async () => {
    const wrapper = await mountEditor(false)

    expect(wrapper.text()).toContain('当前账号只有查看权限')
    expect(wrapper.find('.rule-summary-card__actions').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('添加选股规则')
    expect(wrapper.findAll('.el-switch').every((node) => node.classes().includes('is-disabled'))).toBe(true)
    expect((wrapper.get('[data-testid="rule-capital-input"]').element as HTMLInputElement).disabled)
      .toBe(true)
  })

  it('以分为单位精确判断 0.10 + 0.20 恰好等于 0.30', async () => {
    const decimalDraft = {
      ...draft(), capital: '0.30',
      stock_rules: [
        { ...draft().stock_rules[0], max_capital: '0.10', enabled: true },
        { ...draft().stock_rules[1], max_capital: '0.20', enabled: true },
      ],
    }
    api.get.mockResolvedValue({
      ...detail(), draft: decimalDraft, draft_revision: decimalDraft.draft_revision,
    })
    api.publish.mockResolvedValue({
      changed: true, rule_id: 'rule-1', version_no: 2, effective_from_trade_date: '2026-08-24',
    })
    const wrapper = await mountEditor()

    expect(wrapper.text()).toContain('剩余 0.00')
    await wrapper.get('.rule-editor__footer .el-button:last-child').trigger('click')
    await flushPromises()
    expect(api.publish).toHaveBeenCalledWith('rule-1', 2)
  })

  it('从接口展示到保存始终保留 NUMERIC(20,2) 大额十进制字符串', async () => {
    const largeDraft = {
      ...draft(), capital: '999999999999999999.99',
      stock_rules: [
        { ...draft().stock_rules[0], max_capital: '999999999999999999.98', enabled: true },
      ],
    }
    api.get.mockResolvedValue({
      ...detail(), draft: largeDraft, draft_revision: largeDraft.draft_revision,
    })
    const wrapper = await mountEditor()

    expect(field(wrapper, '总本金').get('input').element.value)
      .toBe('999,999,999,999,999,999.99')
    expect(wrapper.text()).toContain('剩余 0.01')
    await wrapper.get('[data-testid="stock-rule-card"]')
      .get('[data-testid="rule-card-toggle"]').trigger('click')
    await field(wrapper, '资金上限').get('input').setValue('9007199254740992.01')
    await wrapper.get('.rule-editor__footer .el-button:nth-last-child(2)').trigger('click')
    await flushPromises()

    expect(api.save).toHaveBeenCalledWith('rule-1', expect.objectContaining({
      capital: '999999999999999999.99',
      stock_rules: [expect.objectContaining({ max_capital: '9007199254740992.01' })],
    }))
  })

  it('默认仅展示规则摘要，且同一时间只展开一张卡片', async () => {
    const wrapper = await mountEditor()

    expect(wrapper.findAll('[data-testid="rule-card-editor"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('上限 · 40,000.00 元')
    expect(wrapper.text()).toContain('第一行')
    expect(wrapper.text()).toContain('第二行')
    expect(wrapper.text()).toContain('建仓')

    const stockCards = wrapper.findAll('[data-testid="stock-rule-card"]')
    await stockCards[0]!.get('[data-testid="rule-card-toggle"]').trigger('click')
    expect(wrapper.findAll('[data-testid="rule-card-editor"]')).toHaveLength(1)
    expect(stockCards[0]!.classes()).toContain('rule-card--wide')

    await wrapper.get('[data-testid="buy-rule-group"]')
      .get('[data-testid="rule-card-toggle"]').trigger('click')
    expect(wrapper.findAll('[data-testid="rule-card-editor"]')).toHaveLength(1)
    expect(stockCards[0]!.classes()).not.toContain('rule-card--wide')
  })
})
