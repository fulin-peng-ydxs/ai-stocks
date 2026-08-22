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
  })

  it('防抖搜索、读取分页 list，并把完整股票快照回传', async () => {
    vi.useFakeTimers()
    const stock = { code: '000001.SZ', name: '平安银行', board: '主板', industry: '银行' }
    searchStocks.mockResolvedValue({ q: '平安', limit: 20, list: [stock] })
    const wrapper = mount(StockOptionSelect, {
      props: { modelValue: null }, global: { plugins: [ElementPlus] },
    })
    const select = wrapper.findComponent({ name: 'ElSelect' })
    select.props('remoteMethod')('平安')
    expect(searchStocks).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    expect(searchStocks).toHaveBeenCalledWith('平安', 20, expect.any(AbortSignal))
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
})
