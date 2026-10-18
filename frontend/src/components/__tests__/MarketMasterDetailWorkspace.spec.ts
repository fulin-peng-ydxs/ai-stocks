// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import MarketMasterDetailWorkspace from '@/components/MarketMasterDetailWorkspace.vue'
import {
  MARKET_WORKSPACE_COMPACT_MIN_HEIGHT,
  MARKET_WORKSPACE_MIN_HEIGHT,
} from '@/layout/marketWorkspaceSizing'

function pointerEvent(type: string, pointerId: number, clientX: number): Event {
  const event = new Event(type)
  Object.defineProperties(event, {
    pointerId: { value: pointerId },
    clientX: { value: clientX },
  })
  return event
}

function captureAnimationFrame() {
  let callback: FrameRequestCallback | undefined
  const request = vi.fn((next: FrameRequestCallback) => {
    callback = next
    return 1
  })
  vi.stubGlobal('requestAnimationFrame', request)
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  return { request, run: () => callback?.(0) }
}

describe('MarketMasterDetailWorkspace', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('统一执行行情工作台的常规与紧凑可阅读高度', async () => {
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        heightMode: 'adaptive',
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })

    expect(wrapper.get('.market-master-detail').attributes('style'))
      .toContain(`min-height: ${MARKET_WORKSPACE_MIN_HEIGHT}px`)
    expect(wrapper.getComponent({ name: 'AppSplitWorkspace' }).props('adaptiveHeight')).toBe(true)
    await wrapper.setProps({ compact: true })
    expect(wrapper.get('.market-master-detail').attributes('style'))
      .toContain(`min-height: ${MARKET_WORKSPACE_COMPACT_MIN_HEIGHT}px`)
    wrapper.unmount()
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
    expect(wrapper.get('.app-workspace-pane__header').text()).toContain('测试列表')
    expect(wrapper.get('.app-workspace-pane__eyebrow').text()).toBe('TEST')
    expect(wrapper.find('[data-testid="analysis-slot"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-hide-analysis"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="market-show-analysis"]').exists()).toBe(false)
    expect(wrapper.get('.market-master-detail').classes()).toContain('app-split-workspace--primary-only')
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

  it('指针拖动按共享比例上限钳制，卸载时清理全局拖动态', async () => {
    const frame = captureAnimationFrame()
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
    expect(frame.request).toHaveBeenCalledTimes(1)
    frame.run()
    await nextTick()

    expect(separator.attributes('aria-valuemax')).toBe('770')
    expect(separator.attributes('aria-valuenow')).toBe('770')
    expect(document.body.classList.contains('app-split-workspace-is-resizing')).toBe(true)
    wrapper.unmount()
    HTMLElement.prototype.getBoundingClientRect = originalRect
    expect(document.body.classList.contains('app-split-workspace-is-resizing')).toBe(false)
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
    expect(wrapper.emitted('masterRatioSampleChange')?.at(-1)).toEqual([{
      width: 1100,
      ratio: 45,
      configuredRatio: 45,
    }])

    wrapper.unmount()
    HTMLElement.prototype.getBoundingClientRect = originalRect
  })

  it('在15%范围内使用最近的尺寸比例档案，范围外回退默认比例', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1800)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: {
        analysisVisible: true,
        eyebrow: 'TEST',
        title: '测试列表',
        defaultMasterRatio: 45,
        masterRatioProfiles: {
          profiles: [{ width: 1280, ratio: 52 }, { width: 1920, ratio: 46 }],
        },
      },
      slots: { list: '<div>列表</div>', analysis: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()
    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('828')

    await wrapper.setProps({ masterRatioProfiles: { profiles: [{ width: 1280, ratio: 52 }] } })
    await nextTick()
    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('810')
    wrapper.unmount()
  })

  it('宽屏响应式默认值保持约 45% 且拖动边界遵守共享比例约束', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(4000)
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

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('1800')
    expect(wrapper.get('[role="separator"]').attributes('aria-valuemax')).toBe('2800')
    wrapper.unmount()
  })

  it('小幅窗口变化保留会话宽度，跨尺寸范围后重新匹配响应式默认值', async () => {
    let width = 2000
    const observers = new Map<Element, ResizeObserverCallback>()
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
    vi.stubGlobal('ResizeObserver', class {
      constructor(private callback: ResizeObserverCallback) {}
      observe(element: Element) { observers.set(element, this.callback) }
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
    const resizeCallback = () => observers.get(wrapper.get('.app-split-workspace').element)?.([], {} as ResizeObserver)
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('900')

    await separator.trigger('keydown', { key: 'ArrowRight' })
    expect(separator.attributes('aria-valuenow')).toBe('916')
    width = 2100
    resizeCallback()
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('916')

    width = 2400
    resizeCallback()
    await nextTick()
    expect(separator.attributes('aria-valuenow')).toBe('1080')

    await separator.trigger('dblclick')
    expect(separator.attributes('aria-valuenow')).toBe('1080')
    wrapper.unmount()
  })

  it('工作区不超过720px时自动进入单区并禁用比例采样', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(700)
    const wrapper = mount(MarketMasterDetailWorkspace, {
      props: { analysisVisible: true, eyebrow: 'TEST', title: '测试列表' },
      slots: { list: '<div>列表</div>', analysis: '<div data-testid="compact-analysis">分析</div>' },
      global: {
        plugins: [ElementPlus],
        stubs: {
          PageDrawer: {
            props: ['modelValue'],
            template: '<div v-if="modelValue" data-testid="compact-drawer"><slot /></div>',
          },
        },
      },
    })
    await nextTick()

    expect(wrapper.get('.market-master-detail').classes()).toContain('app-split-workspace--compact')
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
    expect(wrapper.emitted('masterRatioSampleChange')?.at(-1)).toEqual([undefined])
    expect((wrapper.vm as unknown as { openCompactAnalysis: () => boolean }).openCompactAnalysis()).toBe(true)
    await nextTick()
    wrapper.get('[data-testid="market-analysis-drawer"]')
    expect(wrapper.get('[data-testid="compact-analysis"]').text()).toBe('分析')
    wrapper.unmount()
  })

  it('缩放后把视口指针位移换算为布局像素，分隔条始终跟随鼠标', async () => {
    const frame = captureAnimationFrame()
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
    expect(frame.request).toHaveBeenCalledTimes(1)
    frame.run()
    await nextTick()

    expect(separator.attributes('aria-valuenow')).toBe('1025')
    wrapper.unmount()
  })
})
