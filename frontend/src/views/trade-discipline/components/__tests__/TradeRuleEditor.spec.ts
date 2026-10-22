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

function latestLeaveResolver(wrapper: ReturnType<typeof mount>): (allowLeave: boolean) => void {
  const event = wrapper.emitted('requestLeave')?.at(-1)
  if (!event) throw new Error('missing requestLeave event')
  return event[0] as (allowLeave: boolean) => void
}

describe('TradeRuleEditor', () => {
  it('发布失败自动展开空检查项所在规则与分类，外层收起后保留分类展开状态', async () => {
    const value: any = detail()
    value.draft.stock_rules[0].checklist_items = [{ item_id: 'blank', category: 'risk', text: '', display_order: 1 }]
    api.get.mockResolvedValue(value)
    const wrapper = await mountEditor()
    await wrapper.get('[data-testid="rule-name-input"]').setValue('修改后的规则')
    await wrapper.get('.rule-editor__footer .el-button:last-child').trigger('click')
    await flushPromises()
    const head = () => wrapper.get('[data-condition-section="risk"] .config-panel-section__head')
    expect(head().attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[data-checklist-id="blank"]').isVisible()).toBe(true)
    expect(api.publish).not.toHaveBeenCalled()
    const toggle = () => wrapper.get('[data-testid="stock-rule-card"] [data-testid="rule-card-toggle"]')
    await toggle().trigger('click')
    await toggle().trigger('click')
    expect(head().attributes('aria-expanded')).toBe('true')
  })
  it('分类检查项保存、复制独立标识，补充说明不是必填', async () => {
    const value: any = detail()
    value.draft.stock_rules[0].content = null
    value.draft.stock_rules[0].checklist_items = [{ item_id: 'c', category: 'technical', text: '涨幅不超过50%', display_order: 1 }]
    api.get.mockResolvedValue(value)
    const wrapper = await mountEditor()
    await wrapper.get('[data-testid="stock-rule-card"] [data-testid="rule-card-toggle"]').trigger('click')
    const notes = field(wrapper, '补充说明')
    expect(notes.classes()).not.toContain('is-required')
    await wrapper.get('[data-testid="stock-rule-card"] button[aria-label="复制选股规则"]').trigger('click')
    const editors = wrapper.findAllComponents({ name: 'StockRuleChecklistEditor' })
    const copyItems = editors.at(-1)!.props('modelValue')
    expect(copyItems[0]).toMatchObject({ text: '涨幅不超过50%', category: 'technical' })
    expect(copyItems[0].item_id).not.toBe('c')
    editors.at(-1)!.vm.$emit('update:modelValue', [{ ...copyItems[0], text: '副本条件' }])
    await (wrapper.vm as any).saveDraft()
    const payload = api.save.mock.calls.at(-1)![1]
    expect(payload.stock_rules[0].checklist_items[0].text).toBe('涨幅不超过50%')
    expect(payload.stock_rules[1].checklist_items[0].text).toBe('副本条件')
    expect(payload.stock_rules[0].content).toBeNull()
  })
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

  it('恢复并保存结构化条件、四位股价和整套规则持仓上限', async () => {
    const value: any = detail()
    value.draft.max_positions = 3
    value.draft.stock_rules[0] = { ...value.draft.stock_rules[0], price_min: '5.1234', price_max: '20', st_filter: 'exclude', loss_filter: 'exclude', st_risk_filter: 'only' }
    api.get.mockResolvedValue(value)
    const wrapper = await mountEditor()
    expect(wrapper.text()).toContain('股价 5.1234～20.0000 元')
    await wrapper.get('[data-testid="rule-max-positions"] input').setValue('4')
    await wrapper.get('[data-testid="rule-max-positions"] input').trigger('change')
    await wrapper.get('.rule-editor__footer .el-button:nth-last-child(2)').trigger('click')
    await flushPromises()
    expect(api.save).toHaveBeenCalledWith('rule-1', expect.objectContaining({
      max_positions: 4,
      stock_rules: expect.arrayContaining([expect.objectContaining({ price_min: '5.1234', price_max: '20', st_filter: 'exclude', loss_filter: 'exclude', st_risk_filter: 'only' })]),
    }))
  })

  it('用统一业务分区完整包裹买卖规则和两个方向组', async () => {
    const wrapper = await mountEditor()
    const section = wrapper.get('[data-testid="action-rules-section"]')
    expect(section.classes()).toContain('trade-discipline-section-panel')
    expect(section.text()).toContain('买卖规则')
    const body = section.get('[data-testid="trade-discipline-section-body"]')
    expect(body.find('[data-testid="buy-rule-group"]').exists()).toBe(true)
    expect(body.find('[data-testid="sell-rule-group"]').exists()).toBe(true)
    expect(body.text()).not.toContain('买卖规则')
  })

  it('保存时保留换行、启用态和调整后的展示顺序', async () => {
    const wrapper = await mountEditor()
    const handle = wrapper.get('[aria-label="拖动排序：突破"]')
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'ArrowDown' })
    await handle.trigger('keydown', { key: ' ' })
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

  it('买卖规则分别组内重排，保存全局顺序并重新加载，不交换业务类型', async () => {
    const value = detail()
    value.draft.action_rules.push(
      { ...value.draft.action_rules[0], detail_id: 'a3', name: '加仓', action_subtype: 'add_position', display_order: 3 },
      { ...value.draft.action_rules[1], detail_id: 'a4', name: '减仓', action_subtype: 'reduce_position', display_order: 4 },
    )
    api.get.mockResolvedValue(value)
    const wrapper = await mountEditor()
    for (const name of ['建仓', '清仓']) {
      const handle = wrapper.get(`[aria-label="拖动排序：${name}"]`)
      await handle.trigger('keydown', { key: ' ' })
      await handle.trigger('keydown', { key: 'End' })
      await handle.trigger('keydown', { key: 'Enter' })
    }
    const buy = wrapper.get('[data-testid="buy-rule-group"]')
    const sell = wrapper.get('[data-testid="sell-rule-group"]')
    expect(buy.findAll('[data-testid="action-rule-card"] strong').map(node => node.text())).toEqual(['加仓', '建仓'])
    expect(sell.findAll('[data-testid="action-rule-card"] strong').map(node => node.text())).toEqual(['减仓', '清仓'])
    await (wrapper.vm as any).saveDraft(false)
    const payload = api.save.mock.calls[0][1]
    expect(payload.action_rules.map((item: any) => [item.detail_id, item.action_type, item.display_order]))
      .toEqual([['a3', 'buy', 1], ['a4', 'sell', 2], ['a1', 'buy', 3], ['a2', 'sell', 4]])
    value.draft = { ...value.draft, ...payload }
    wrapper.unmount()
    const reloaded = await mountEditor()
    expect(reloaded.get('[data-testid="buy-rule-group"]').findAll('[data-testid="action-rule-card"] strong').map(node => node.text())).toEqual(['加仓', '建仓'])
  })

  it('新增项重排保持展开字段身份，保存失败保留顺序与未保存状态', async () => {
    const wrapper = await mountEditor()
    const add = wrapper.findAll('button').find(node => node.text() === '添加选股规则')!
    await add.trigger('click')
    const name = wrapper.get('[data-testid="stock-rule-name-input"]')
    await name.setValue('新增纪律')
    const input = name.element
    const handle = wrapper.get('[aria-label="拖动排序：新增纪律"]')
    await handle.trigger('keydown', { key: ' ' })
    await handle.trigger('keydown', { key: 'Home' })
    await handle.trigger('keydown', { key: ' ' })
    expect(wrapper.findAll('[data-testid="stock-rule-card"]')[0].get('[data-testid="stock-rule-name-input"]').element).toBe(input)
    expect((wrapper.vm as any).isDirty()).toBe(true)
    api.save.mockRejectedValueOnce(new Error('save failed'))
    expect(await (wrapper.vm as any).saveDraft(false)).toBe(false)
    expect(wrapper.findAll('[data-testid="stock-rule-card"] strong')[0].text()).toBe('新增纪律')
    expect((wrapper.vm as any).isDirty()).toBe(true)
  })

  it('未保存时把离开决策交给页面浮层，并按继续、放弃和保存结果返回', async () => {
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('临时名称')
    const continueResult = (wrapper.vm as any).requestLeave()
    latestLeaveResolver(wrapper)(false)
    expect(await continueResult).toBe(false)
    expect((wrapper.vm as any).isDirty()).toBe(true)

    const discardResult = (wrapper.vm as any).requestLeave()
    const editor = wrapper.vm as any
    editor.discardUnsavedChanges()
    latestLeaveResolver(wrapper)(true)
    expect(await discardResult).toBe(true)
    expect((wrapper.vm as any).isDirty()).toBe(false)
    expect(field(wrapper, '规则名称').get('input').element.value).toBe('趋势纪律')

    await field(wrapper, '规则名称').get('input').setValue('保存后离开')
    const saveResult = (wrapper.vm as any).requestLeave()
    expect(await (wrapper.vm as any).saveDraft(false)).toBe(true)
    latestLeaveResolver(wrapper)(true)
    expect(await saveResult).toBe(true)
    expect(api.save).toHaveBeenCalledWith('rule-1', expect.objectContaining({
      name: '保存后离开', expected_revision: 2,
    }))
  })

  it('重置恢复最近保存内容且不放弃已保存草稿', async () => {
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('临时名称')

    const resetButton = wrapper.findAll('.rule-editor__footer .el-button')
      .find((button) => button.text() === '还原修改')!
    await resetButton.trigger('click')

    expect(field(wrapper, '规则名称').get('input').element.value).toBe('趋势纪律')
    expect((wrapper.vm as any).isDirty()).toBe(false)
    expect(api.discard).not.toHaveBeenCalled()
  })

  it('页面浮层保存草稿失败时不放行且保留当前输入', async () => {
    api.save.mockRejectedValueOnce(new Error('save failed'))
    const wrapper = await mountEditor()
    await field(wrapper, '规则名称').get('input').setValue('保存失败也不能丢')
    const leaveResult = (wrapper.vm as any).requestLeave()
    expect(await (wrapper.vm as any).saveDraft(false)).toBe(false)

    expect(api.save).toHaveBeenCalledTimes(1)
    expect((wrapper.vm as any).isDirty()).toBe(true)
    expect(field(wrapper, '规则名称').get('input').element.value).toBe('保存失败也不能丢')
    latestLeaveResolver(wrapper)(false)
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

  it('内容未变更时保存草稿和保存并启用均禁用，提交函数也不调用接口', async () => {
    const wrapper = await mountEditor()
    const saveDraftButton = wrapper.findAll('.rule-editor__footer .el-button')
      .find((button) => button.text() === '保存草稿')!
    const publishButton = wrapper.findAll('.rule-editor__footer .el-button')
      .find((button) => button.text() === '保存并启用')!

    expect(saveDraftButton.attributes('disabled')).toBeDefined()
    expect(publishButton.attributes('disabled')).toBeDefined()
    await (wrapper.vm as any).saveDraft()
    await publishButton.trigger('click')

    expect(api.save).not.toHaveBeenCalled()
    expect(api.publish).not.toHaveBeenCalled()
  })

  it('必填标记覆盖发布校验字段，明细缺失时不保存也不发布', async () => {
    const wrapper = await mountEditor()
    const baseRequiredLabels = wrapper.findAll('.el-form-item.is-required .el-form-item__label')
      .map((item) => item.text())
    expect(baseRequiredLabels).toEqual(expect.arrayContaining(['规则名称', '总本金（元）']))

    await wrapper.get('[data-testid="stock-rule-card"] [data-testid="rule-card-toggle"]').trigger('click')
    const stockRequiredLabels = wrapper.findAll('.el-form-item.is-required .el-form-item__label')
      .map((item) => item.text())
    expect(stockRequiredLabels).toEqual(expect.arrayContaining([
      '规则名称', '资金上限（元）',
    ]))

    await wrapper.get('[data-testid="stock-rule-name-input"]').setValue('')
    await wrapper.get('.rule-editor__footer .el-button:last-child').trigger('click')
    await flushPromises()

    expect(api.save).not.toHaveBeenCalled()
    expect(api.publish).not.toHaveBeenCalled()
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

    const optionRows = Array.from(document.body.querySelectorAll('.builtin-option-row'))
    expect(optionRows).toHaveLength(3)
    expect(optionRows.filter((row) => row.querySelector('.builtin-option-label'))).toHaveLength(2)
    expect(optionRows.filter((row) => row.querySelector('.builtin-option-row__action'))).toHaveLength(1)
    expect(wrapper.get('[data-testid="action-rule-type-help"]').attributes('aria-label')).toBe('说明')
    expect(wrapper.text()).not.toContain('内置类型不可删除')
    expect(document.body.textContent).not.toContain('全局类型不可删除')
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

    const sections = wrapper.get('[data-testid="rule-editor"] .app-scroll-area__content').element.children
    const noticeIndex = Array.from(sections).indexOf(wrapper.get('.readonly-notice').element)
    const stateIndex = Array.from(sections).indexOf(wrapper.get('.rule-state-track').element)
    expect(noticeIndex).toBeGreaterThan(0)
    expect(stateIndex).toBe(noticeIndex + 1)
    expect(wrapper.find('.app-reorder-list__handle').exists()).toBe(false)
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
    await field(wrapper, '规则名称').get('input').setValue('小额精度验证')
    await wrapper.get('.rule-editor__footer .el-button:last-child').trigger('click')
    await flushPromises()
    expect(api.publish).toHaveBeenCalledWith('rule-1', 3)
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

  it('默认配置晚到和外层卡片重开保留分区开合，恢复默认清除全部临时开合且不清草稿', async () => {
    const wrapper = await mountEditor()
    await wrapper.setProps({ conditionPanelDefaults: { defaultCollapsed: ['basic', 'risk', 'technical', 'notes'], resetKey: 0 } })
    const toggle = wrapper.findAll('[data-testid="stock-rule-card"]')[0]!.get('[data-testid="rule-card-toggle"]')
    await toggle.trigger('click')
    const technical = () => wrapper.get('[data-condition-section="technical"] .config-panel-section__head')
    await technical().trigger('click')
    await wrapper.setProps({ conditionPanelDefaults: { defaultCollapsed: ['risk', 'technical', 'notes'], resetKey: 0 } })
    expect(technical().attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    // 即使分区已经随外层卡片卸载，恢复默认也应重置保存于表单的开合。
    await wrapper.setProps({ conditionPanelDefaults: { defaultCollapsed: ['basic', 'risk', 'technical', 'notes'], resetKey: 1 } })
    await toggle.trigger('click')
    expect(technical().attributes('aria-expanded')).toBe('false')
    expect((wrapper.get('[data-testid="stock-rule-capital-input"]').element as HTMLInputElement).value).toBe('40,000.00')
    expect(api.save).not.toHaveBeenCalled()
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
    expect(stockCards[0]!.classes()).toContain('is-expanded')

    await wrapper.get('[data-testid="buy-rule-group"]')
      .get('[data-testid="rule-card-toggle"]').trigger('click')
    expect(wrapper.findAll('[data-testid="rule-card-editor"]')).toHaveLength(1)
    expect(stockCards[0]!.classes()).not.toContain('rule-card--wide')
  })
})
