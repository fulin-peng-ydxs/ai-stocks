// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { initVectorEChart } from '@/components/echartsRenderer'

const echartsMock = vi.hoisted(() => ({
  chart: { resize: vi.fn() },
  init: vi.fn(),
}))

echartsMock.init.mockReturnValue(echartsMock.chart)

vi.mock('echarts', () => ({ init: echartsMock.init }))

describe('initVectorEChart', () => {
  beforeEach(() => {
    echartsMock.init.mockClear()
  })

  it('全站图表统一使用 SVG renderer', () => {
    const element = document.createElement('div')

    expect(initVectorEChart(element)).toBe(echartsMock.chart)
    expect(echartsMock.init).toHaveBeenCalledWith(element, undefined, { renderer: 'svg' })
  })

  it('根级缩放下把指针视口坐标统一换回图表布局坐标', () => {
    const element = document.createElement('div')
    Object.defineProperties(element, {
      offsetWidth: { configurable: true, value: 200 },
      offsetHeight: { configurable: true, value: 100 },
    })
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      top: 50,
      width: 160,
      height: 80,
      right: 260,
      bottom: 130,
      x: 100,
      y: 50,
      toJSON: () => ({}),
    })

    initVectorEChart(element)
    const event = new MouseEvent('mousemove', {
      bubbles: true,
      clientX: 180,
      clientY: 90,
    }) as MouseEvent & { zrX?: number; zrY?: number }
    element.dispatchEvent(event)

    expect(event.zrX).toBe(100)
    expect(event.zrY).toBe(50)
  })

  it('同一图表元素重复初始化时不重复登记坐标监听', () => {
    const element = document.createElement('div')
    const addEventListener = vi.spyOn(element, 'addEventListener')

    initVectorEChart(element)
    const registeredCount = addEventListener.mock.calls.length
    initVectorEChart(element)

    expect(registeredCount).toBeGreaterThan(0)
    expect(addEventListener).toHaveBeenCalledTimes(registeredCount)
  })
})
