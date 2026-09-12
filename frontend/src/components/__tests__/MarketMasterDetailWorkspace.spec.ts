// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'

function pointerEvent(type: string, pointerId: number, clientX: number): Event {
  const event = new Event(type)
  Object.defineProperties(event, {
    pointerId: { value: pointerId },
    clientX: { value: clientX },
  })
  return event
}

describe('MarketMasterDetailWorkspace', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('compact 模式只渲染列表并隐藏无效的分析收展入口', () => {
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        compact: true,
        eyebrow: 'TEST',
        title: '测试列表',
      },
      slots: {
        list: '<div data-testid="list-slot">列表</div>',
        analysis: '<div data-testid="analysis-slot">分析</div>',
      },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.get('[data-testid="list-slot"]').text()).toBe('列表')
    expect(wrapper.find('[data-testid="analysis-slot"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-hide-analysis"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-show-analysis"]').exists()).toBe(false)
    expect(wrapper.classes()).toContain('market-master-detail--list-only')
  })

  it('抽屉默认比例单向投影到会话，键盘拖动不反写 props', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(2000)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 50,
      },
      slots: {
        list: '<div>列表</div>',
        analysis: '<div data-testid="analysis-slot">分析</div>',
      },
      global: { plugins: [ElementPlus] },
    })

    const separator = wrapper.get('[role="separator"]')
    await nextTick()
    expect(separator.attributes('aria-orientation')).toBe('vertical')
    expect(separator.attributes('aria-valuenow')).toBe('1000')

    await separator.trigger('keydown', { key: 'ArrowRight' })
    expect(separator.attributes('aria-valuenow')).toBe('1016')
    expect(wrapper.props('defaultMasterRatio')).toBe(50)

    await wrapper.setProps({ defaultMasterRatio: 55 })
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('1100')
  })

  it('指针拖动按详情最小宽度钳制，卸载时清理全局拖动态', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1100)
    HTMLElement.prototype.getBoundingClientRect = () => ({ width: 1100 } as DOMRect)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 45,
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })

    const separator = wrapper.get('[role="separator"]')
    await separator.trigger('pointerdown', { pointerId: 7, clientX: 495 })
    window.dispatchEvent(pointerEvent('pointermove', 7, 900))
    await nextTick()

    expect(separator.attributes('aria-valuemax')).toBe('848')
    expect(separator.attributes('aria-valuenow')).toBe('848')
    expect(document.body.classList.contains('market-master-detail-is-resizing')).toBe(true)
    wrapper.unmount()
    HTMLElement.prototype.getBoundingClientRect = originalRect
    expect(document.body.classList.contains('market-master-detail-is-resizing')).toBe(false)
  })

  it('响应式默认值按容器比例计算并保留两侧最小宽度', async () => {
    const originalRect = HTMLElement.prototype.getBoundingClientRect
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1100)
    HTMLElement.prototype.getBoundingClientRect = () => ({ width: 1100 } as DOMRect)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 45,
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('495')
    expect(wrapper.emitted('masterRatioChange')?.at(-1)).toEqual([45])

    wrapper.unmount()
    HTMLElement.prototype.getBoundingClientRect = originalRect
  })

  it('宽屏响应式默认值保持约 45% 且不超过列表上限', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(3200)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 45,
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('1440')
    expect(wrapper.get('[role="separator"]').attributes('aria-valuemax')).toBe('1600')
    wrapper.unmount()
  })

  it('用户调整后窗口变化保留会话宽度，双击恢复当前容器的响应式默认值', async () => {
    let width = 2000
    let resizeCallback: ResizeObserverCallback | undefined
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resizeCallback = callback }
      observe() {}
      disconnect() {}
    })
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 45,
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })
    const separator = wrapper.get('[role="separator"]')
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('900')

    await separator.trigger('keydown', { key: 'ArrowRight' })
    expect(separator.attributes('aria-valuenow')).toBe('916')
    width = 2400
    resizeCallback?.([], {} as ResizeObserver)
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('916')

    await separator.trigger('dblclick')
    expect(separator.attributes('aria-valuenow')).toBe('1080')
    wrapper.unmount()
  })

  it('缩放后把视口指针位移换算为布局像素，分隔条始终跟随鼠标', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(2000)
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(2000)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({ width: 1600 } as DOMRect)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 45,
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })

    const separator = wrapper.get('[role="separator"]')
    await separator.trigger('pointerdown', { pointerId: 8, clientX: 900 })
    window.dispatchEvent(pointerEvent('pointermove', 8, 1000))
    await nextTick()

    expect(separator.attributes('aria-valuenow')).toBe('1025')
    wrapper.unmount()
  })
})
