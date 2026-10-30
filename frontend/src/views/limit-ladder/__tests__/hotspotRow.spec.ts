// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import LadderHotspots from '../LadderHotspots.vue'
import { fitHotspotRow } from '../hotspotRow'

describe('热点单行容量', () => {
  const keys = ['a', 'b', 'c', 'd']
  const widths = { a: 80, b: 100, c: 60, d: 120 }

  it('全部放得下时不为展开入口额外占位', () => {
    expect(fitHotspotRow(keys, widths, 372, 100, 4, null)).toEqual({ keys, count: 4 })
  })

  it('预留展开入口后按实际标签宽度和间距决定首行，覆盖临界两侧', () => {
    expect(fitHotspotRow(keys, widths, 288, 100, 4, null).count).toBe(2)
    expect(fitHotspotRow(keys, widths, 287, 100, 4, null).count).toBe(1)
  })

  it('首行外选中项替换末项，长选中项会进一步收敛数量', () => {
    expect(fitHotspotRow(keys, widths, 288, 100, 4, 'd')).toEqual({
      keys: ['d', 'a', 'b', 'c'], count: 1,
    })
    expect(fitHotspotRow(keys, widths, 308, 100, 4, 'd')).toEqual({
      keys: ['a', 'd', 'b', 'c'], count: 2,
    })
  })

  it('空列表、尚未测量和极窄容器均保留可用的确定状态', () => {
    expect(fitHotspotRow([], {}, 0, 100, 4, null)).toEqual({ keys: [], count: 0 })
    expect(fitHotspotRow(keys, widths, 0, 100, 4, 'd')).toEqual({ keys: ['d', 'a', 'b', 'c'], count: 1 })
    expect(fitHotspotRow(keys, widths, 150, 100, 4, null).count).toBe(1)
  })
})

describe('热点测量及折叠状态', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('容器缩放会重算数量；展开不被缩放重置，收起后选中项仍可用且隐藏项不可聚焦', async () => {
    let width = 288
    let chipHeight = 24
    let resize: ResizeObserverCallback | undefined
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resize = callback }
      observe() {}
      disconnect = disconnect
    })
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('ladder-hotspots__body') ? width : 0
    })
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('ladder-hotspots__disclosure') ? 100 : 80
    })
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('ladder-hotspots__chips') ? 80 : chipHeight
    })
    const wrapper = mount(LadderHotspots, { props: {
      hotspots: { industry: [], concept: ['a', 'b', 'c', 'd'].map(group_key => ({
        group_key, group_name: group_key, stock_count: 1,
      })) }, activeType: 'concept', activeKey: 'd',
    } })
    await nextTick()
    const visible = () => wrapper.findAll('.ladder-hotspots__chip:not([inert])')
    expect(visible()).toHaveLength(2)
    expect(visible().map(button => button.text())).toContain('d·1只')
    expect(wrapper.get('.ladder-hotspots__more').text()).toBe('展开其余 2 项')
    await wrapper.get('.ladder-hotspots__more').trigger('click')
    expect(visible()).toHaveLength(4)
    expect(wrapper.get('#ladder-hotspots-concept').attributes('style')).toContain('80px')
    width = 200
    resize?.([], {} as ResizeObserver)
    await nextTick()
    expect(wrapper.get('.ladder-hotspots__more').attributes('aria-expanded')).toBe('true')
    expect(visible()).toHaveLength(4)
    await wrapper.get('.ladder-hotspots__more').trigger('click')
    expect(visible()).toHaveLength(1)
    expect(visible()[0]!.attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('#ladder-hotspots-concept').attributes('style')).toContain('24px')
    expect(wrapper.findAll('.ladder-hotspots__chip[aria-hidden="true"]')).toHaveLength(3)
    for (const height of [20, 28]) {
      chipHeight = height
      resize?.([], {} as ResizeObserver)
      await nextTick()
      expect(wrapper.get('#ladder-hotspots-concept').attributes('style')).toContain(`${height}px`)
      expect(visible()[0]!.attributes('aria-pressed')).toBe('true')
    }
    width = 400
    resize?.([], {} as ResizeObserver)
    await nextTick()
    expect(visible()).toHaveLength(4)
    expect(wrapper.find('.ladder-hotspots__more').exists()).toBe(false)
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalledOnce()
  })
})
