// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import TradeOperationEditor from '@/views/trade-discipline/components/TradeOperationEditor.vue'
import type { RuleVersionDetail } from '@/api/tradeDiscipline'

const version: RuleVersionDetail = {
  rule_id: 'rule-1', version_no: 2, name: '趋势纪律', capital: '100000',
  stock_rules: [{ detail_id: 'stock-1', name: '唯一选股', max_capital: null, content: null, display_order: 1, enabled: true }],
  action_rules: [
    { detail_id: 'buy-1', name: '唯一买入', action_type: 'buy', action_subtype: 'open_position', content: null, display_order: 1, enabled: true },
    { detail_id: 'sell-1', name: '唯一卖出', action_type: 'sell', action_subtype: 'liquidate', content: null, display_order: 2, enabled: true },
  ],
}

describe('TradeOperationEditor', () => {
  it('分类展开状态按操作隔离，收起外层卡片不丢失已展开分类或核对结果', async () => {
    const withChecklist: RuleVersionDetail = { ...version, stock_rules: [{ ...version.stock_rules[0],
      checklist_items: [{ item_id: 'c', category: 'technical', text: '涨幅不超过50%', display_order: 1 }] }] }
    withChecklist.stock_rules.push({ ...withChecklist.stock_rules[0], detail_id: 'stock-2', name: '另一选股规则' })
    const operation = { stock_code: '000001.SZ', stock_name_snapshot: '平安银行', side: 'buy' as const,
      stock_rule_id: 'stock-1', action_rule_id: 'buy-1', price: null, quantity: null, amount: null,
      fee: null, operated_at: null, note: null, display_order: 1, checklist_results: [{ item_id: 'c', status: 'unknown' as const }] }
    const model = [{ ...operation, client_key: 'first' }, { ...operation, client_key: 'second', display_order: 2 }]
    const wrapper = mount(TradeOperationEditor, { props: { modelValue: model, version: withChecklist, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } } })
    const toggles = () => wrapper.findAll('[data-testid="operation-card-toggle"]')
    const head = () => wrapper.get('[data-condition-section="technical"] .config-panel-section__head')
    await toggles()[0].trigger('click')
    expect(head().attributes('aria-expanded')).toBe('false')
    await head().trigger('click')
    await toggles()[0].trigger('click')
    await toggles()[0].trigger('click')
    expect(head().attributes('aria-expanded')).toBe('true')
    await toggles()[1].trigger('click')
    expect(head().attributes('aria-expanded')).toBe('false')
    expect(wrapper.props('modelValue')).toEqual(model)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await toggles()[0].trigger('click')
    expect(head().attributes('aria-expanded')).toBe('true')
    await wrapper.setProps({ modelValue: [{ ...model[0], stock_rule_id: 'stock-2' }, model[1]] })
    expect(head().attributes('aria-expanded')).toBe('false')
  })
  it('逐项不符合会限制单笔履约，换股或换规则默认符合，回显不补选', async () => {
    const rule = { ...version.stock_rules[0], checklist_items: [{ item_id: 'c', category: 'technical' as const, text: '涨幅不超过50%', display_order: 1 }] }
    const withChecklist = { ...version, stock_rules: [rule, { ...rule, detail_id: 'stock-2', name: '另一规则' }] }
    const operation = { stock_code: '000001.SZ', stock_name_snapshot: '平安银行', side: 'buy' as const,
      stock_rule_id: 'stock-1', action_rule_id: 'buy-1', price: null, quantity: null, amount: null,
      fee: null, operated_at: null, note: null, display_order: 1, compliance_status: 'complied' as const,
      checklist_results: [{ item_id: 'c', status: 'unknown' as const }] }
    const wrapper = mount(TradeOperationEditor, { props: { modelValue: [operation], version: withChecklist, tradeDate: '2026-08-22', showCompliance: true },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } } })
    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    const checklist = wrapper.findComponent({ name: 'StockRuleConditionChecklist' })
    expect(checklist.props('results')).toEqual(operation.checklist_results)
    checklist.vm.$emit('update:results', [{ item_id: 'c', status: 'no' }])
    await flushPromises()
    const changed = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(changed[0].compliance_status).toBe('breached')
    await wrapper.setProps({ modelValue: changed })
    expect(wrapper.text()).toContain('选股条件“涨幅不超过50%”不符合')
    wrapper.findComponent({ name: 'StockOptionSelect' }).vm.$emit('update:modelValue', { code: '000002.SZ', name: '万科A' })
    await flushPromises()
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as any[])[0].checklist_results).toEqual([{ item_id: 'c', status: 'yes' }])
    const selector = wrapper.findAllComponents({ name: 'ElSelect' }).find(node => node.attributes('data-testid') === 'operation-stock-rule-0')!
    selector.vm.$emit('update:modelValue', 'stock-2')
    await flushPromises()
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as any[])[0]).toMatchObject({ stock_rule_id: 'stock-2', checklist_results: [{ item_id: 'c', status: 'yes' }] })
  })
  it.each([
    { side: 'buy' as const, selected: 'buy-1', labels: ['唯一买入', '均线加仓'], types: ['建仓', '加仓'], next: 'buy-2' },
    { side: 'sell' as const, selected: 'sell-1', labels: ['唯一卖出', '分批卖出', '盘中回转'], types: ['清仓', '分批止盈', '做 T'], next: 'sell-2' },
  ])('$side 规则候选及选中值显示类型，选择仍回传明细 ID', async ({ side, selected, labels, types, next }) => {
    const typed: RuleVersionDetail = { ...version, action_rules: [
      ...version.action_rules,
      { ...version.action_rules[0], detail_id: 'buy-2', name: '均线加仓', action_subtype: 'add_position' },
      { ...version.action_rules[1], detail_id: 'sell-2', name: '分批卖出', action_subtype: '分批止盈' },
      { ...version.action_rules[1], detail_id: 'sell-3', name: '盘中回转', action_subtype: 'do_t' },
      { ...version.action_rules[0], detail_id: 'disabled-buy', enabled: false },
    ] }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [{
        stock_code: '000001.SZ', stock_name_snapshot: '平安银行', side,
        stock_rule_id: 'stock-1', action_rule_id: selected, price: null, quantity: null,
        amount: null, fee: null, operated_at: null, note: null, display_order: 1,
      }], version: typed, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    await flushPromises()
    const selector = wrapper.findAllComponents({ name: 'ElSelect' }).find((node) => node.attributes('data-testid') === 'operation-action-rule-0')!
    expect(selector.findAllComponents({ name: 'ElOption' }).map((option) => option.props('label'))).toEqual(labels)
    const options = selector.findAllComponents({ name: 'ElOption' })
    expect(options.map((option) => option.get('.el-tag').text())).toEqual(types)
    expect(selector.get('.el-select__placeholder .builtin-option-row__label').text()).toBe(labels[0])
    const selectedTag = selector.get('.el-select__placeholder .el-tag')
    expect(selectedTag.text()).toBe(types[0])
    expect(selectedTag.classes()).toEqual(expect.arrayContaining(['el-tag--info', 'el-tag--small', 'el-tag--plain']))
    selector.vm.$emit('update:modelValue', next)
    await flushPromises()
    const changed = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(changed[0].action_rule_id).toBe(next)
    await wrapper.setProps({ modelValue: changed })
    await flushPromises()
    expect(selector.get('.el-select__placeholder .builtin-option-row__label').text()).toBe(labels[1])
    expect(selector.get('.el-select__placeholder .el-tag').text()).toBe(types[1])
  })

  it('买入事实仅提供是否选项；换股重新预填，卖出不核对', async () => {
    const limited: RuleVersionDetail = { ...version, stock_rules: [{ ...version.stock_rules[0], price_max: '10', loss_filter: 'exclude', st_risk_filter: 'exclude' }] }
    const operation = {
      client_key: 'condition-operation', stock_code: '000001.SZ', stock_name_snapshot: '平安银行',
      side: 'buy' as const, stock_rule_id: 'stock-1', action_rule_id: 'buy-1',
      price: '12', quantity: null, amount: null, fee: null, operated_at: null, note: null, display_order: 1,
    }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [operation], version: limited, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    expect(wrapper.get('[data-testid="operation-conditions"]').text()).toContain('股价 ≤10.0000 元')
    expect(wrapper.text()).toContain('成交价不符合股价条件')
    const selector = wrapper.findAllComponents({ name: 'ElSelect' }).find((node) => node.attributes('data-testid') === 'operation-loss_status-0')!
    expect(selector.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))).toEqual(['yes', 'no'])
    selector.vm.$emit('update:modelValue', 'yes')
    await flushPromises()
    const changed = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(changed[0].loss_status).toBe('yes')
    await wrapper.setProps({ modelValue: changed })
    wrapper.findComponent({ name: 'StockOptionSelect' }).vm.$emit('update:modelValue', { code: '000002.SZ', name: '万科A', is_st: false })
    await flushPromises()
    const switched = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(switched[0]).toMatchObject({ stock_code: '000002.SZ', loss_status: 'no', st_risk_status: 'no', selection_facts: null })
    await wrapper.setProps({ modelValue: [{ ...operation, side: 'sell', action_rule_id: 'sell-1' }] })
    expect(wrapper.find('[data-testid="operation-conditions"]').exists()).toBe(false)
  })

  it('新增买入自动预填规则条件，允许修改并在重选同股时保留，卖出不预填', async () => {
    const limited: RuleVersionDetail = { ...version, stock_rules: [{ ...version.stock_rules[0], loss_filter: 'exclude', st_risk_filter: 'only',
      checklist_items: [{ item_id: 'c', category: 'technical', text: '趋势符合', display_order: 1 }] }] }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version: limited, tradeDate: '2026-08-22', showCompliance: true },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(created[0]).toMatchObject({ loss_status: 'no', st_risk_status: 'yes', compliance_status: 'complied', checklist_results: [{ item_id: 'c', status: 'yes' }] })
    await wrapper.setProps({ modelValue: [{ ...created[0], stock_code: '000001.SZ', stock_name_snapshot: '平安银行', is_st: false }] })
    const selector = wrapper.findAllComponents({ name: 'ElSelect' }).find((node) => node.attributes('data-testid') === 'operation-loss_status-0')!
    expect(selector.props('modelValue')).toBe('no')
    expect(selector.props('disabled')).toBe(false)
    selector.vm.$emit('update:modelValue', 'yes')
    await flushPromises()
    const edited = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    await wrapper.setProps({ modelValue: edited })
    wrapper.findComponent({ name: 'StockOptionSelect' }).vm.$emit('update:modelValue', { code: '000001.SZ', name: '平安银行', is_st: null })
    await flushPromises()
    const reselected = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(reselected[0]).toMatchObject({ loss_status: 'yes', st_risk_status: 'yes', is_st: false })
    await wrapper.get('button[aria-label="添加卖出操作"]').trigger('click')
    const withSell = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(withSell.at(-1)).toMatchObject({ side: 'sell', loss_status: null, st_risk_status: null })
  })

  it('多个候选在选定规则后补默认值，切换规则保留已有事实及未知', async () => {
    const multi: RuleVersionDetail = { ...version, stock_rules: [
      { ...version.stock_rules[0], loss_filter: 'exclude', st_risk_filter: 'only' },
      { ...version.stock_rules[0], detail_id: 'stock-2', name: '第二规则', loss_filter: 'only', st_risk_filter: 'exclude' },
    ] }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version: multi, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(created[0]).toMatchObject({ stock_rule_id: '', loss_status: null, st_risk_status: null })
    await wrapper.setProps({ modelValue: created })
    const selector = wrapper.findAllComponents({ name: 'ElSelect' }).find((node) => node.attributes('data-testid') === 'operation-stock-rule-0')!
    selector.vm.$emit('update:modelValue', 'stock-1')
    await flushPromises()
    const selected = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(selected[0]).toMatchObject({ stock_rule_id: 'stock-1', loss_status: 'no', st_risk_status: 'yes' })
    await wrapper.setProps({ modelValue: [{ ...selected[0], st_risk_status: 'unknown' }] })
    selector.vm.$emit('update:modelValue', 'stock-2')
    await flushPromises()
    const switched = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(switched[0]).toMatchObject({ stock_rule_id: 'stock-2', loss_status: 'no', st_risk_status: 'unknown' })
    await wrapper.setProps({ modelValue: switched })
    expect(wrapper.text()).toContain('亏损状态不符合选股条件')
  })

  it('历史事实不因加载、展开或只读版本变化被默认值覆盖', async () => {
    const historical = {
      id: 'saved-operation', stock_code: '000001.SZ', stock_name_snapshot: '平安银行',
      side: 'buy' as const, stock_rule_id: 'stock-1', action_rule_id: 'buy-1',
      price: null, quantity: null, amount: null, fee: null, operated_at: null, note: null,
      display_order: 1, loss_status: null, st_risk_status: 'unknown' as const,
    }
    const limited: RuleVersionDetail = { ...version, stock_rules: [{ ...version.stock_rules[0], loss_filter: 'exclude', st_risk_filter: 'exclude' }] }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [historical], version: limited, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.setProps({ disabled: true })
    await wrapper.setProps({ version: { ...limited, version_no: 3 } })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.props('modelValue')[0]).toEqual(historical)
  })

  it('版本变化自动关联唯一新规则时补未填写事实，保留已填写的未知', async () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    await wrapper.setProps({ modelValue: [{ ...created[0], is_st: true, compliance_status: 'complied', st_risk_status: 'unknown' }] })
    await wrapper.setProps({ version: { ...version, version_no: 3, stock_rules: [
      { ...version.stock_rules[0], detail_id: 'stock-v3', st_filter: 'exclude', loss_filter: 'exclude', st_risk_filter: 'only' },
    ] } })
    const rebound = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(rebound[0]).toMatchObject({ stock_rule_id: 'stock-v3', compliance_status: 'breached', loss_status: 'no', st_risk_status: 'unknown' })
  })

  it('部分履约中已确认ST违规的买入也不能标记已履约', async () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [{ client_key: 'st-violation', stock_code: '000001.SZ', stock_name_snapshot: 'ST股票', side: 'buy', stock_rule_id: 'stock-1', action_rule_id: 'buy-1', is_st: true, price: null, quantity: null, amount: null, fee: null, operated_at: null, note: null, display_order: 1 }], version: { ...version, stock_rules: [{ ...version.stock_rules[0], st_filter: 'exclude' }] }, tradeDate: '2026-08-22', showCompliance: true },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    const selector = wrapper.findComponent({ name: 'ElSegmented' })
    expect(selector.props('options')[0].disabled).toBe(true)
    selector.vm.$emit('update:modelValue', 'complied')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    selector.vm.$emit('update:modelValue', 'breached')
    expect((wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[])[0].compliance_status).toBe('breached')
  })

  it('用统一业务分区完整包裹操作事实和买卖方向组', () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    const section = wrapper.get('[data-testid="checkin-operation-section"]')
    expect(section.classes()).toContain('trade-discipline-section-panel')
    expect(section.text()).toContain('操作事实')
    const body = section.get('[data-testid="trade-discipline-section-body"]')
    expect(body.find('[data-testid="buy-operation-group"]').exists()).toBe(true)
    expect(body.find('[data-testid="sell-operation-group"]').exists()).toBe(true)
    expect(body.text()).not.toContain('操作事实')
  })

  it('成交明细四项编辑时标记必填，费用不自动伪填，只读时不标必填', async () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[]
    expect(created[0].fee).toBeNull()
    await wrapper.setProps({ modelValue: created })
    const fields = () => wrapper.findAllComponents({ name: 'ElFormItem' })
      .filter(item => ['成交价', '数量', '成交金额', '费用'].includes(item.props('label')))
    expect(fields()).toHaveLength(4)
    expect(fields().every(item => item.props('required'))).toBe(true)
    await wrapper.setProps({ disabled: true })
    expect(fields().every(item => !item.props('required'))).toBe(true)
  })

  it('新增操作默认使用履约交易日和当前时分秒', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 7, 23, 9, 45, 6))
    try {
      const wrapper = mount(TradeOperationEditor, {
        props: { modelValue: [], version, tradeDate: '2026-08-22' },
        global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
      })
      await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
      const created = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
      expect(created[0].operated_at).toBe('2026-08-22T09:45:06')
    } finally {
      vi.useRealTimers()
    }
  })

  it('候选唯一时自动关联规则，方向由新增分组确定', async () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    expect(wrapper.get('[data-testid="buy-operation-group"]').text()).toContain('买入操作')
    expect(wrapper.get('[data-testid="sell-operation-group"]').text()).toContain('卖出操作')
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(created[0]).toMatchObject({ stock_rule_id: 'stock-1', action_rule_id: 'buy-1', side: 'buy' })
    await wrapper.setProps({ modelValue: [{ ...created[0], stock_code: '000001.SZ', stock_name_snapshot: '平安银行' }] })
    expect(wrapper.get('[data-testid="operation-card-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.findComponent({ name: 'StockOptionSelect' }).props('tradeDate')).toBe('2026-08-22')
    expect(wrapper.findComponent({ name: 'ElSegmented' }).exists()).toBe(false)
    expect(wrapper.get('[data-testid="operation-card-editor"]').text()).toContain('买入规则')
    expect(wrapper.get('[data-testid="operation-context-section"]').text()).toContain('操作依据')
    expect(wrapper.get('[data-testid="operation-trade-section"]').text()).toContain('成交明细')
    expect(wrapper.get('[data-testid="operation-note-section"]').text()).toContain('操作说明')
  })

  it('同方向存在多个候选时不擅自选择', async () => {
    const multi = { ...version, action_rules: [...version.action_rules, { ...version.action_rules[0], detail_id: 'buy-2', name: '第二买入' }] }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version: multi, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button[aria-label="添加买入操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(created[0].action_rule_id).toBe('')
  })

  it('部分履约时逐笔选择状态并在折叠卡展示结果', async () => {
    const operation = {
      client_key: 'partial-operation', stock_code: '000001.SZ', stock_name_snapshot: '平安银行',
      side: 'buy' as const, stock_rule_id: 'stock-1', action_rule_id: 'buy-1',
      price: null, quantity: null, amount: null, fee: null, operated_at: null,
      note: null, compliance_status: null, display_order: 1,
    }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [operation], version, tradeDate: '2026-08-22', showCompliance: true },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })

    expect(wrapper.text()).toContain('履约状态未选择')
    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'complied')
    await flushPromises()
    const changed = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(changed[0].compliance_status).toBe('complied')
    await wrapper.setProps({ modelValue: changed })
    expect(wrapper.text()).toContain('已履约')
    expect(wrapper.text()).not.toContain('履约状态未选择')
  })

  it('成交事实保持十进制字符串并以定点价量计算提示', async () => {
    const operation = {
      client_key: 'large-operation', stock_code: '000001.SZ', stock_name_snapshot: '平安银行',
      side: 'buy' as const, stock_rule_id: 'stock-1', action_rule_id: 'buy-1',
      price: '9007199254740992.0001', quantity: '1.0000', amount: '9007199254740992.00', fee: '0.01',
      operated_at: null, note: null, display_order: 1,
    }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [operation], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })

    await wrapper.get('[data-testid="operation-card-toggle"]').trigger('click')
    expect(wrapper.text()).toContain('价 × 量 = 9,007,199,254,740,992.00')
    expect(wrapper.text()).not.toContain('与填写金额不一致')
    const amountInput = wrapper.findAllComponents({ name: 'FixedDecimalInput' })[2]!
    amountInput.vm.$emit('update:modelValue', '9007199254740991.99')
    await flushPromises()

    const changed = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(changed[0].amount).toBe('9007199254740991.99')
  })

  it('已有操作默认折叠，摘要可扫描且一次只展开一笔', async () => {
    const operations = [1, 2].map((displayOrder) => ({
      client_key: `operation-${displayOrder}`,
      stock_code: `00000${displayOrder}.SZ`,
      stock_name_snapshot: displayOrder === 1 ? '平安银行' : '万科A',
      side: displayOrder === 1 ? 'buy' as const : 'sell' as const,
      stock_rule_id: 'stock-1',
      action_rule_id: displayOrder === 1 ? 'buy-1' : 'sell-1',
      price: '10.0000', quantity: '100.0000', amount: '1000.00', fee: '1.00',
      operated_at: '2026-08-22T14:30:00', note: null, display_order: displayOrder,
    }))
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: operations, version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })

    expect(wrapper.findAll('[data-testid="operation-card-editor"]')).toHaveLength(0)
    expect(wrapper.findAll('.app-summary-disclosure-card__title-row strong')[0]!.text())
      .toBe('平安银行 000001.SZ')
    expect(wrapper.text()).toContain('成交金额 · 1,000.00')
    expect(wrapper.text()).toContain('唯一选股 · 唯一买入 · 2026-08-22 14:30')
    expect(wrapper.get('[data-testid="buy-operation-group"]').findAll('[data-testid="operation-card"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="sell-operation-group"]').findAll('[data-testid="operation-card"]')).toHaveLength(1)

    const toggles = wrapper.findAll('[data-testid="operation-card-toggle"]')
    await toggles[0]!.trigger('click')
    expect(wrapper.findAll('[data-testid="operation-card-editor"]')).toHaveLength(1)
    expect(toggles[0]!.attributes('aria-expanded')).toBe('true')
    await toggles[1]!.trigger('click')
    expect(wrapper.findAll('[data-testid="operation-card-editor"]')).toHaveLength(1)
    expect(toggles[0]!.attributes('aria-expanded')).toBe('false')
    expect(toggles[1]!.attributes('aria-expanded')).toBe('true')
  })

  it('从方向分组新增时预设对应方向及唯一买卖规则', async () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })

    await wrapper.get('button[aria-label="添加卖出操作"]').trigger('click')
    const created = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(created[0]).toMatchObject({ side: 'sell', action_rule_id: 'sell-1' })
    expect(wrapper.find('[data-testid="operation-card-editor"]').exists()).toBe(false)

    await wrapper.setProps({ modelValue: created })
    expect(wrapper.get('[data-testid="sell-operation-group"]').findAll('[data-testid="operation-card"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="operation-card-toggle"]').attributes('aria-expanded')).toBe('true')
  })

  it('可按校验结果展开指定操作', async () => {
    const operation = {
      client_key: 'invalid-operation', stock_code: '', stock_name_snapshot: '', side: 'buy' as const,
      stock_rule_id: 'stock-1', action_rule_id: 'buy-1', price: null, quantity: null,
      amount: null, fee: null, operated_at: null, note: null, display_order: 1,
    }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [operation], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })

    expect(wrapper.text()).toContain('信息未完整')
    expect(wrapper.find('[data-testid="operation-card-editor"]').exists()).toBe(false)
    ;(wrapper.vm as any).expandOperation(0)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="operation-card-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-testid="operation-card-editor"]').exists()).toBe(true)
  })
})
