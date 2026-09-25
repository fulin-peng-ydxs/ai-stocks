// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, inject, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import AppSplitWorkspace from '@/components/AppSplitWorkspace.vue'
import PageDrawer from '@/components/PageDrawer.vue'
import { WORKSPACE_RESIZE_ACTIVE } from '@/layout/workspaceResizeContext'

function pointerEvent(type: string, pointerId: number, clientX: number): Event {
  const event = new Event(type)
  Object.defineProperties(event, {
    pointerId: { value: pointerId },
    clientX: { value: clientX },
  })
  return event
}

function mountWorkspace(props: Record<string, unknown> = {}) {
  return mount(AppSplitWorkspace, {
    props: { secondaryVisible: true, ...props },
    slots: {
      primary: '<div data-testid="primary">图表</div>',
      secondary: '<div data-testid="secondary">辅助信息</div>',
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('AppSplitWorkspace', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
    document.documentElement.style.removeProperty('--app-display-scale')
  })

  it('按 65/35 默认比例渲染双栏，并支持键盘调整和双击恢复', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1200)
    const wrapper = mountWorkspace({ defaultPrimaryRatio: 65 })
    await nextTick()

    const separator = wrapper.get('[role="separator"]')
    expect(separator.attributes('aria-valuenow')).toBe('780')
    expect(wrapper.emitted('primaryRatioChange')?.at(-1)).toEqual([65])

    await separator.trigger('keydown', { key: 'ArrowLeft' })
    expect(separator.attributes('aria-valuenow')).toBe('764')
    await separator.trigger('keydown', { key: 'Home' })
    expect(separator.attributes('aria-valuenow')).toBe('360')
    await separator.trigger('keydown', { key: 'End' })
    expect(separator.attributes('aria-valuenow')).toBe('840')
    await separator.trigger('dblclick')
    expect(separator.attributes('aria-valuenow')).toBe('780')
    wrapper.unmount()
  })

  it('拖拽分隔条按左右栏最小宽度钳制，并输出当前比例样本', async () => {
    let frameCallback: FrameRequestCallback | undefined
    const requestFrame = vi.fn((callback: FrameRequestCallback) => {
      frameCallback = callback
      return 3
    })
    vi.stubGlobal('requestAnimationFrame', requestFrame)
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    document.documentElement.style.setProperty('--app-display-scale', '0.8')
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1200)
    const wrapper = mountWorkspace({ defaultPrimaryRatio: 65 })
    await nextTick()

    const separator = wrapper.get('[role="separator"]')
    await separator.trigger('pointerdown', { pointerId: 3, clientX: 624 })
    window.dispatchEvent(pointerEvent('pointermove', 3, 650))
    window.dispatchEvent(pointerEvent('pointermove', 3, 672))
    expect(requestFrame).toHaveBeenCalledTimes(1)
    expect(separator.attributes('aria-valuenow')).toBe('780')

    frameCallback?.(0)
    await nextTick()

    expect(separator.attributes('aria-valuenow')).toBe('840')
    expect(wrapper.emitted('primaryRatioSampleChange')?.at(-1)).toEqual([
      { width: 1200, ratio: 70, configuredRatio: 65 },
    ])
    window.dispatchEvent(pointerEvent('pointerup', 3, 672))
    expect(document.body.classList.contains('app-split-workspace-is-resizing')).toBe(false)
    wrapper.unmount()
  })

  it('拖拽期间向后代声明布局调整状态，结束后立即恢复', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1200)
    const ResizeStateProbe = defineComponent({
      setup() {
        const resizing = inject(WORKSPACE_RESIZE_ACTIVE)
        return () => h('span', {
          'data-testid': 'resize-state',
          'data-resizing': String(resizing?.value ?? false),
        })
      },
    })
    const wrapper = mount(AppSplitWorkspace, {
      props: { secondaryVisible: true },
      slots: {
        primary: () => h(ResizeStateProbe),
        secondary: '<div>辅助信息</div>',
      },
      global: { plugins: [ElementPlus] },
    })
    await nextTick()

    const state = wrapper.get('[data-testid="resize-state"]')
    expect(state.attributes('data-resizing')).toBe('false')
    await wrapper.get('[role="separator"]').trigger('pointerdown', {
      pointerId: 8,
      clientX: 780,
    })
    await nextTick()
    expect(state.attributes('data-resizing')).toBe('true')

    window.dispatchEvent(pointerEvent('pointerup', 8, 780))
    await nextTick()
    expect(state.attributes('data-resizing')).toBe('false')
    wrapper.unmount()
  })

  it('使用相近尺寸比例档案，并在隐藏次栏时移除分隔条', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1800)
    const wrapper = mountWorkspace({
      defaultPrimaryRatio: 65,
      primaryRatioProfiles: { profiles: [{ width: 1920, ratio: 60 }] },
    })
    await nextTick()

    expect(wrapper.get('[role="separator"]').attributes('aria-valuenow')).toBe('1080')
    await wrapper.setProps({ secondaryVisible: false })
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="secondary"]').exists()).toBe(false)
    expect(wrapper.get('.app-split-workspace').classes()).toContain('app-split-workspace--primary-only')
    wrapper.unmount()
  })

  it('不超过 720px 时仅保留主栏，并可打开次栏全屏抽屉', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(700)
    const wrapper = mountWorkspace()
    await nextTick()

    expect(wrapper.get('.app-split-workspace').classes()).toContain('app-split-workspace--compact')
    expect(wrapper.emitted('compactChange')?.at(-1)).toEqual([true])
    expect(wrapper.find('[role="separator"]').exists()).toBe(false)
    expect(wrapper.emitted('primaryRatioSampleChange')?.at(-1)).toEqual([undefined])
    expect((wrapper.vm as unknown as { openCompactSecondary: () => boolean }).openCompactSecondary())
      .toBe(true)
    await nextTick()
    expect(wrapper.find('[data-testid="split-workspace-secondary-drawer"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('两栏和抽屉都通过共享容器承载插槽内容', async () => {
    const wrapper = mountWorkspace()
    expect(wrapper.find('.app-split-workspace__primary').exists()).toBe(true)
    expect(wrapper.find('.app-split-workspace__secondary').exists()).toBe(true)
    expect(wrapper.get('.app-split-workspace').attributes('style')).toContain('grid-template-columns')
    wrapper.unmount()

    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(700)
    const compact = mountWorkspace({ drawerClass: 'business-drawer' })
    await nextTick()
    expect((compact.vm as unknown as { openCompactSecondary: () => boolean }).openCompactSecondary())
      .toBe(true)
    await nextTick()
    expect(compact.find('.app-split-workspace__drawer-secondary').exists()).toBe(true)
    expect(compact.getComponent(PageDrawer).props('modalClass'))
      .toBe('app-split-workspace-drawer business-drawer')
    compact.unmount()
  })

  it('按调用方语义高度区分常规与紧凑工作台', async () => {
    const wrapper = mountWorkspace({
      minHeight: 480,
      compactMinHeight: 400,
    })
    expect(wrapper.get('.app-split-workspace').attributes('style')).toContain('min-height: 480px')

    await wrapper.setProps({ compact: true })
    expect(wrapper.get('.app-split-workspace').attributes('style')).toContain('min-height: 400px')
    wrapper.unmount()
  })

  it('adaptive 在页面未溢出时填满剩余高度，空间不足时守住可读下限', async () => {
    let frameCallback: FrameRequestCallback | undefined
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameCallback = callback
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1200)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('test-scrollport') ? 900 : 0
    })
    let workspaceTop = 300
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const top = this.classList.contains('test-scrollport') ? 100 : workspaceTop
      return {
        x: 0, y: top, top, left: 0, right: 1200, bottom: top,
        width: 1200, height: 0, toJSON: () => ({}),
      }
    })

    const scrollport = document.createElement('div')
    scrollport.className = 'test-scrollport'
    scrollport.style.overflowY = 'auto'
    document.body.appendChild(scrollport)
    const wrapper = mount(AppSplitWorkspace, {
      attachTo: scrollport,
      props: {
        secondaryVisible: true,
        minHeight: 480,
        adaptiveHeight: true,
      },
      slots: { primary: '<div>列表</div>', secondary: '<div>分析</div>' },
      global: { plugins: [ElementPlus] },
    })

    frameCallback?.(0)
    await nextTick()
    expect(wrapper.get('.app-split-workspace').attributes('style')).toContain('height: 700px')

    workspaceTop = 800
    window.dispatchEvent(new Event('resize'))
    frameCallback?.(0)
    await nextTick()
    expect(wrapper.get('.app-split-workspace').attributes('style')).toContain('height: 480px')
    wrapper.unmount()
  })
})
