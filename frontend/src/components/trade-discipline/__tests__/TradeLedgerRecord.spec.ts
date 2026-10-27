// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import type { LedgerSnapshot } from '@/api/tradeLedger'
import TradeLedgerRecord from '../TradeLedgerRecord.vue'

const snapshot: LedgerSnapshot = { trade_date: '2026-10-26', events: [], positions: [], opening_positions: [],
  rules: [{ rule_id: 'r', name: '趋势纪律', version_no: 1, capital: '100000', stock_rules: [], action_rules: [] }],
  omissions: [{ kind: 'missed_buy', stock_code: '600356.SH', stock_name: '恒丰纸业', rule_id: 'r' }],
  evaluations: [{ rule_id: 'r', rule_name: '趋势纪律', confirmed: true, assessment: 'breached',
    complete: true, issues: [], warnings: [] }], assessment: 'breached', complete: true, peak_positions: 0,
  buy_amount: '0', sell_amount: '0', fee: '0', net_outflow: '0', cash: null, realized_pnl: null, review_note: null }

describe('账本只读记录', () => {
  it.each([true, false])('遗漏股票保留按交易日查询的ST身份（%s），独立和嵌入模式均不生成禁用输入框', async isSt => {
    const wrapper = mount(TradeLedgerRecord, { props: { snapshot, stockOptions: [{ code: '600356.SH',
      name: '恒丰纸业', board: null, industry: null, is_st: isSt, st_as_of_date: '2026-10-26' }] },
      global: { plugins: [ElementPlus] } })
    try {
      expect(wrapper.findComponent({ name: 'StockStatusTag' }).props('isSt')).toBe(isSt)
      expect(wrapper.findComponent({ name: 'StockStatusTag' }).props('asOfDate')).toBe('2026-10-26')
      expect(wrapper.find('.stock-status-tag').exists()).toBe(isSt)
      expect(wrapper.find('input, select, textarea').exists()).toBe(false)
      expect(wrapper.text()).toContain('应买未买')
      expect(wrapper.text()).toContain('未履约')
      expect(wrapper.get('[data-testid="ledger-rule-record"]').classes()).toContain('is-panel-bordered')
      const content = wrapper.text()
      await wrapper.setProps({ borderPlacement: 'none' })
      expect(wrapper.get('[data-testid="ledger-rule-record"]').classes()).toContain('is-borderless')
      expect(wrapper.get('[data-testid="ledger-rule-record"]').classes()).not.toContain('is-panel-bordered')
      expect(wrapper.text()).toBe(content)
    } finally { wrapper.unmount() }
  })
  it('无规则、无交易的已提交日结仍给出可读空态', () => {
    const wrapper = mount(TradeLedgerRecord, { props: { snapshot: { ...snapshot, rules: [], omissions: [], evaluations: [] } },
      global: { plugins: [ElementPlus] } })
    expect(wrapper.text()).toContain('当日无买卖或调整记录')
    expect(wrapper.find('input, textarea').exists()).toBe(false)
    wrapper.unmount()
  })
})
