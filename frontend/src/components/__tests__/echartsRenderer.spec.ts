// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { initVectorEChart } from '@/components/echartsRenderer'

const echartsMock = vi.hoisted(() => ({
  chart: { resize: vi.fn() },
  init: vi.fn(),
}))

echartsMock.init.mockReturnValue(echartsMock.chart)

vi.mock('echarts', () => ({ init: echartsMock.init }))

describe('initVectorEChart', () => {
  it('全站图表统一使用 SVG renderer', () => {
    const element = document.createElement('div')

    expect(initVectorEChart(element)).toBe(echartsMock.chart)
    expect(echartsMock.init).toHaveBeenCalledWith(element, undefined, { renderer: 'svg' })
  })
})
