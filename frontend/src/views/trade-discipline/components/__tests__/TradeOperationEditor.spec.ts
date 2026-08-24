// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
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
  it('候选唯一时自动关联规则，切换方向保留股票并重算买卖规则', async () => {
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button.el-button').trigger('click')
    const created = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(created[0]).toMatchObject({ stock_rule_id: 'stock-1', action_rule_id: 'buy-1', side: 'buy' })
    await wrapper.setProps({ modelValue: [{ ...created[0], stock_code: '000001.SZ', stock_name_snapshot: '平安银行' }] })
    wrapper.findComponent({ name: 'ElSegmented' }).vm.$emit('update:modelValue', 'sell')
    await flushPromises()
    const changed = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(changed[0]).toMatchObject({ stock_code: '000001.SZ', stock_rule_id: 'stock-1', action_rule_id: 'sell-1', side: 'sell' })
  })

  it('同方向存在多个候选时不擅自选择', async () => {
    const multi = { ...version, action_rules: [...version.action_rules, { ...version.action_rules[0], detail_id: 'buy-2', name: '第二买入' }] }
    const wrapper = mount(TradeOperationEditor, {
      props: { modelValue: [], version: multi, tradeDate: '2026-08-22' },
      global: { plugins: [ElementPlus], directives: { permission: {} }, stubs: { StockOptionSelect: true } },
    })
    await wrapper.get('button.el-button').trigger('click')
    const created = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(created[0].action_rule_id).toBe('')
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

    expect(wrapper.text()).toContain('价 × 量 = 9,007,199,254,740,992.00')
    expect(wrapper.text()).not.toContain('与填写金额不一致')
    const amountInput = wrapper.findAllComponents({ name: 'FixedDecimalInput' })[2]!
    amountInput.vm.$emit('update:modelValue', '9007199254740991.99')
    await flushPromises()

    const changed = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as any[]
    expect(changed[0].amount).toBe('9007199254740991.99')
  })
})
