// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useLayoutViewport } from '@/composables/useLayoutViewport'

describe('useLayoutViewport', () => {
  afterEach(() => { document.body.innerHTML = ''; vi.unstubAllGlobals() })

  it('使用根布局尺寸，缩放和窗口变化后更新，并释放监听', async () => {
    const root = document.createElement('div')
    root.id = 'app'
    document.body.append(root)
    let width = 960
    let height = 600
    Object.defineProperties(root, {
      clientWidth: { get: () => width }, clientHeight: { get: () => height },
    })
    let resize: () => void = () => {}
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe = vi.fn()
      disconnect = disconnect
    })
    const wrapper = mount(defineComponent({
      setup: useLayoutViewport,
      template: '<span>{{width}}×{{height}}</span>',
    }))
    await nextTick()
    expect(wrapper.text()).toBe('960×600')
    width = 1800; height = 1125
    resize(); await nextTick()
    expect(wrapper.text()).toBe('1800×1125')
    width = 1440; height = 900
    window.dispatchEvent(new Event('resize')); await nextTick()
    expect(wrapper.text()).toBe('1440×900')
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalledOnce()
  })
})
