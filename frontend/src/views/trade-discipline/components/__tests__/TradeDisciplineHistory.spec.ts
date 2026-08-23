// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import AppTableColumn from '@/components/AppTableColumn.vue'
import TradeDisciplineHistory from '@/views/trade-discipline/components/TradeDisciplineHistory.vue'
import type { CheckinHistoryRow, TradeDisciplineRule } from '@/api/tradeDiscipline'

const listCheckins = vi.fn()
vi.mock('@/api/tradeDiscipline', () => ({
  listTradeDisciplineCheckins: (...args: unknown[]) => listCheckins(...args),
  searchTradeDisciplineStocks: vi.fn(),
}))

const row: CheckinHistoryRow = {
  id: 'checkin-1', rule_id: 'rule-1', rule_name: '趋势纪律', trade_date: '2026-08-22',
  status: 'amended', current_revision_no: 2, version_no: 3, assessment: 'breached',
  no_operation: false, reason_name_snapshot: '冲动交易', operation_count: 1,
  submitted_at: '2026-08-22T18:00:00', amended_at: '2026-08-22T19:00:00',
  updated_at: '2026-08-22T19:00:00',
}
const rules: TradeDisciplineRule[] = [{
  id: 'rule-1', name: '趋势纪律', status: 'active', management_status: 'active',
  latest_version_no: 3, latest_management_event: null, has_pending_management_action: false,
  effective_status: 'active', effective_event_seq: 1, effective_from_trade_date: '2026-08-22',
  effective_version: { version_no: 3, name: '趋势纪律', capital: '100000' },
}]

const StockStub = defineComponent({
  name: 'StockOptionSelect', props: ['modelValue'], emits: ['update:modelValue'],
  template: '<button type="button" aria-label="股票筛选" @click="$emit(\'update:modelValue\', { code: \'000001.SZ\', name: \'平安银行\' })">选择股票</button>',
})

function mountHistory(props: Record<string, unknown> = {}) {
  return mount(TradeDisciplineHistory, {
    props: {
      query: {}, page: 1, pageSize: 20, rules, border: false, ...props,
    },
    global: {
      plugins: [createPinia(), ElementPlus],
      stubs: { StockOptionSelect: StockStub, TradeDatePicker: true },
    },
  })
}

describe('TradeDisciplineHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listCheckins.mockResolvedValue({ total: 1, page: 1, page_size: 20, list: [row] })
  })

  it('按服务端分页加载完整历史列并打开详情', async () => {
    const wrapper = mountHistory()
    await flushPromises()
    const filterCard = wrapper.get('.filter-card')
    expect(filterCard.attributes('class')).toContain('history-filter-card')
    expect(filterCard.find('.filter-row[aria-label="履约历史筛选"]').exists()).toBe(true)
    expect(wrapper.findAllComponents(AppTableColumn).at(-1)?.props('role')).toBe('action-compact')
    expect(wrapper.get('.history-workspace').attributes('class')).toContain('history-workspace')
    expect(listCheckins).toHaveBeenCalledWith({ page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('趋势纪律 · v3')
    expect(wrapper.text()).toContain('冲动交易')
    expect(wrapper.text()).toContain('r2 · 已修正')
    await wrapper.get('[data-testid="history-detail-checkin-1"]').trigger('click')
    expect(wrapper.emitted('detail')).toEqual([[row]])
  })

  it('筛选改选自动输出服务端查询条件并重置第一页', async () => {
    const wrapper = mountHistory({ page: 3 })
    await flushPromises()
    wrapper.findAllComponents(AppFilterSelect)[0].vm.$emit('change', 'rule-1')
    await wrapper.get('[aria-label="股票筛选"]').trigger('click')
    expect(wrapper.emitted('update:query')).toContainEqual([{ rule_id: 'rule-1' }])
    expect(wrapper.emitted('update:query')).toContainEqual([{ stock: '000001.SZ' }])
    expect(wrapper.emitted('page-change')).toContainEqual([1])

    await wrapper.setProps({
      page: 1,
      query: { rule_id: 'rule-1', stock: '000001.SZ', no_operation: false, amended: true },
    })
    await flushPromises()
    expect(listCheckins).toHaveBeenLastCalledWith({
      rule_id: 'rule-1', stock: '000001.SZ', no_operation: false, amended: true,
      page: 1, page_size: 20,
    })
  })

  it('查询失败由历史表格区接管且不保留旧数据', async () => {
    const wrapper = mountHistory()
    await flushPromises()
    listCheckins.mockRejectedValueOnce(new Error('unavailable'))
    await wrapper.setProps({ query: { assessment: 'breached' } })
    await flushPromises()
    expect(wrapper.text()).toContain('履约历史加载失败')
    expect(wrapper.text()).not.toContain('趋势纪律 · v3')
  })
})
