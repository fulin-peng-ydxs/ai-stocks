// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockOptionSelect from '@/views/trade-discipline/components/StockOptionSelect.vue'

const searchStocks = vi.fn()
vi.mock('@/api/tradeDiscipline', () => ({
  searchTradeDisciplineStocks: (...args: unknown[]) => searchStocks(...args),
}))

describe('StockOptionSelect', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    document.body.innerHTML = ''
  })

  it('防抖搜索、读取分页 list，并把完整股票快照回传', async () => {
    vi.useFakeTimers()
    const stock = { code: '000001.SZ', name: '平安银行', board: '主板', industry: '银行' }
    searchStocks.mockResolvedValue({ q: '平安', limit: 20, list: [stock] })
    const wrapper = mount(StockOptionSelect, {
      props: { modelValue: null, tradeDate: '2026-08-22' }, global: { plugins: [ElementPlus] },
    })
    const select = wrapper.findComponent({ name: 'ElSelect' })
    select.props('remoteMethod')('平安')
    expect(searchStocks).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    expect(searchStocks).toHaveBeenCalledWith(
      '平安',
      20,
      expect.any(AbortSignal),
      '2026-08-22',
    )
    select.vm.$emit('update:modelValue', '000001.SZ')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([stock])
  })

  it('新查询会中止已经发出的旧查询', async () => {
    vi.useFakeTimers()
    searchStocks.mockImplementation(() => new Promise(() => undefined))
    const wrapper = mount(StockOptionSelect, {
      props: { modelValue: null }, global: { plugins: [ElementPlus] },
    })
    const remote = wrapper.findComponent({ name: 'ElSelect' }).props('remoteMethod')
    remote('旧查询')
    await vi.advanceTimersByTimeAsync(250)
    const firstSignal = searchStocks.mock.calls[0][2] as AbortSignal
    expect(firstSignal.aborted).toBe(false)
    remote('新查询')
    expect(firstSignal.aborted).toBe(true)
  })

  it('当前查询失败时清除旧结果、保留已选项并显示重试提示', async () => {
    vi.useFakeTimers()
    const selected = { code: '000001.SZ', name: '平安银行', board: '主板', industry: '银行' }
    searchStocks
      .mockResolvedValueOnce({ q: '旧', limit: 20, list: [
        selected,
        { code: '000002.SZ', name: '万科A', board: '主板', industry: '房地产' },
      ] })
      .mockRejectedValueOnce(new Error('unavailable'))
    const wrapper = mount(StockOptionSelect, {
      props: { modelValue: selected }, global: { plugins: [ElementPlus] },
    })
    const select = wrapper.findComponent({ name: 'ElSelect' })
    select.props('remoteMethod')('旧')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    expect(wrapper.findAllComponents({ name: 'ElOption' })).toHaveLength(2)

    select.props('remoteMethod')('新')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()

    expect(wrapper.findAllComponents({ name: 'ElOption' })).toHaveLength(1)
    expect(wrapper.findComponent({ name: 'ElOption' }).props('value')).toBe('000001.SZ')
    const alert = wrapper.get('[role="alert"]')
    expect(alert.isVisible()).toBe(true)
    expect(alert.text()).toBe('搜索失败，请重新输入重试')
  })

  it('历史筛选不传交易日并标记退市候选', async () => {
    vi.useFakeTimers()
    searchStocks.mockResolvedValue({ q: '退市', limit: 20, list: [{
      code: '000002.SZ', name: '退市样本', board: '主板', industry: '地产',
      list_date: '1991-01-29', delist_date: '2025-01-01',
    }] })
    const wrapper = mount(StockOptionSelect, {
      props: { modelValue: null }, global: { plugins: [ElementPlus] },
    })
    wrapper.findComponent({ name: 'ElSelect' }).props('remoteMethod')('退市')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()

    expect(searchStocks).toHaveBeenCalledWith('退市', 20, expect.any(AbortSignal), undefined)
    await wrapper.findComponent({ name: 'ElSelect' }).trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('地产 · 已退市')
  })
})
