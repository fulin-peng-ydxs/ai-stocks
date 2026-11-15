// @vitest-environment jsdom
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import type { IntradayPoint } from '@/api/stocks'
import StockIntradayChart from '@/components/stock-chart/StockIntradayChart.vue'

const echartsMock = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  on: vi.fn(),
  isDisposed: vi.fn(() => false),
}))

vi.mock('echarts', () => ({
  init: vi.fn(() => echartsMock),
}))

class ResizeObserverMock {
  observe = vi.fn()
  disconnect = vi.fn()

  constructor(_callback: ResizeObserverCallback) {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock)

const widthDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
const heightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => 960,
  })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get: () => 560,
  })
})

afterAll(() => {
  if (widthDescriptor) Object.defineProperty(HTMLElement.prototype, 'clientWidth', widthDescriptor)
  else Reflect.deleteProperty(HTMLElement.prototype, 'clientWidth')
  if (heightDescriptor) Object.defineProperty(HTMLElement.prototype, 'clientHeight', heightDescriptor)
  else Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight')
})

const points: IntradayPoint[] = [
  {
    time: '09:31',
    open: 10,
    high: 10.2,
    low: 9.9,
    close: 10.1,
    volume: 10,
    amount: 10_100,
    average_price: 10.1,
  },
  {
    time: '09:32',
    open: 10.1,
    high: 10.25,
    low: 10.05,
    close: 10.2,
    volume: 20,
    amount: 20_400,
    average_price: 10.17,
  },
]

describe('StockIntradayChart', () => {
  it('上下图真实复用股票面板标题栏，画布不再私画标题和图例', async () => {
    const wrapper = mount(StockIntradayChart, {
      props: { points, preClose: 10 },
    })
    await nextTick()
    await nextTick()

    const headers = wrapper.findAll('.stock-chart-panel__header')
    expect(headers).toHaveLength(2)
    expect(headers[0].text()).toContain('分时')
    expect(headers[0].text()).toContain('价格10.20')
    expect(headers[0].text()).toContain('均价10.17')
    expect(headers[1].text()).toContain('量能')
    expect(headers[1].text()).toContain('总量30 手')
    expect(headers[1].attributes('style')).toContain('top:')
    expect(headers[1].classes()).not.toContain('is-divided')
    expect(wrapper.find('.stock-intraday-chart__divider').exists()).toBe(true)
    expect(wrapper.find('.stock-intraday-chart__divider').attributes('style')).toContain('top:')
    expect(wrapper.classes()).toContain('app-stock-chart-frame')
    expect(wrapper.findAll('.stock-chart-legend__marker')).toHaveLength(3)
    expect(headers[1].find('.stock-chart-legend__marker').classes()).toContain('is-bar')

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(option.legend).toBeUndefined()
    expect(option.title).toBeUndefined()
    expect(option.graphic).toBeUndefined()

    const pointerHandler = echartsMock.on.mock.calls
      .find(([event]) => event === 'updateAxisPointer')?.[1]
    expect(pointerHandler).toBeTypeOf('function')
    pointerHandler({ seriesDataIndices: [{ dataIndex: 0 }] })
    await nextTick()
    expect(headers[0].text()).toContain('价格10.10')
    expect(headers[0].text()).toContain('均价10.10')

    const globalOutHandler = echartsMock.on.mock.calls
      .find(([event]) => event === 'globalout')?.[1]
    globalOutHandler()
    await nextTick()
    expect(headers[0].text()).toContain('价格10.20')
    wrapper.unmount()
  })
})
