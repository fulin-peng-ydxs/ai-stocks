// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import StockChartRegion from '@/components/stock-chart/StockChartRegion.vue'

let resizeCallback: ResizeObserverCallback | undefined

class ResizeObserverMock {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback
  }

  observe() {}
  disconnect() {}
}

function rect(height: number): DOMRect {
  return { x: 0, y: 0, width: 800, height, top: 0, right: 800, bottom: height, left: 0, toJSON: () => ({}) }
}

describe('StockChartRegion', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
    resizeCallback = undefined
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('按实际标题高度从外层总高度自动得到工作区可用高度', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('stock-chart-region__header')) return rect(80)
      if (this.classList.contains('stock-chart-region__body')) return rect(620)
      return rect(700)
    })
    const wrapper = mount(StockChartRegion, {
      props: { totalHeight: 700, slot2: 'hidden', slot3: 'hidden' },
      slots: {
        header: '<header>标题</header>',
        default: ({ contentHeight }: { contentHeight: number }) => h(
          'div',
          { 'data-testid': 'content' },
          String(contentHeight),
        ),
      },
    })
    await flushPromises()
    resizeCallback?.([], {} as ResizeObserver)
    await flushPromises()

    expect(wrapper.attributes('data-configured-height')).toBe('700')
    expect(wrapper.attributes('data-effective-height')).toBe('700')
    expect(wrapper.attributes('data-content-height')).toBe('620')
    expect(wrapper.get('[data-testid="content"]').text()).toBe('620')
  })

  it('三图内容达到硬下限时自动扩展外层而不裁切底部图表', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('stock-chart-region__header')) return rect(80)
      if (this.classList.contains('stock-chart-region__body')) return rect(518)
      return rect(598)
    })
    const wrapper = mount(StockChartRegion, {
      props: { totalHeight: 560, slot2: 'volume', slot3: 'macd' },
      slots: {
        header: '<header>标题</header>',
        default: ({ contentHeight }: { contentHeight: number }) => h('div', String(contentHeight)),
      },
    })
    await flushPromises()

    expect(wrapper.attributes('data-configured-height')).toBe('560')
    expect(wrapper.attributes('data-effective-height')).toBe('598')
    expect(wrapper.attributes('data-content-height')).toBe('518')
  })

  it('详情页可显式允许图表区域消费父容器剩余空间', () => {
    const wrapper = mount(StockChartRegion, {
      props: { totalHeight: 650, grow: true },
      slots: { default: '<div />' },
    })

    expect(wrapper.attributes('style')).toContain('flex-grow: 1')
  })
})
