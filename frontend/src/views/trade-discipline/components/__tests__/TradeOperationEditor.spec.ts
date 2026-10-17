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
  it('买入按所选规则展示事实选择，未知可选；换股清除旧事实，卖出不核对', async () => {
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
    selector.vm.$emit('update:modelValue', 'unknown')
    await flushPromises()
    const changed = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(changed[0].loss_status).toBe('unknown')
    await wrapper.setProps({ modelValue: changed })
    wrapper.findComponent({ name: 'StockOptionSelect' }).vm.$emit('update:modelValue', { code: '000002.SZ', name: '万科A', is_st: false })
    await flushPromises()
    const switched = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(switched[0]).toMatchObject({ stock_code: '000002.SZ', loss_status: null, st_risk_status: null, selection_facts: null })
    await wrapper.setProps({ modelValue: [{ ...operation, side: 'sell', action_rule_id: 'sell-1' }] })
    expect(wrapper.find('[data-testid="operation-conditions"]').exists()).toBe(false)
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
