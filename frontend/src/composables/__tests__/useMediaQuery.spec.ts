// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMediaQuery } from '@/composables/useMediaQuery'

describe('useMediaQuery', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('同步初始匹配状态、响应变化并在卸载时移除监听', async () => {
    let listener: ((event: MediaQueryListEvent) => void) | undefined
    const addEventListener = vi.fn((_type: string, callback: (event: MediaQueryListEvent) => void) => {
      listener = callback
    })
    const removeEventListener = vi.fn()
    const matchMedia = vi.fn(() => ({
      matches: true,
      addEventListener,
      removeEventListener,
    }))
    vi.stubGlobal('matchMedia', matchMedia)

    const wrapper = mount(defineComponent({
      setup() {
        return { matches: useMediaQuery('(max-height: 700px)') }
      },
      template: '<span>{{ matches }}</span>',
    }))

    expect(matchMedia).toHaveBeenCalledWith('(max-height: 700px)')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toBe('true')

    listener?.({ matches: false } as MediaQueryListEvent)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toBe('false')

    wrapper.unmount()
    expect(removeEventListener).toHaveBeenCalledWith('change', listener)
  })

  it('运行环境不支持 matchMedia 时安全返回 false', () => {
    vi.stubGlobal('matchMedia', undefined)
    const wrapper = mount(defineComponent({
      setup() {
        return { matches: useMediaQuery('(max-width: 768px)') }
      },
      template: '<span>{{ matches }}</span>',
    }))

    expect(wrapper.text()).toBe('false')
    wrapper.unmount()
  })
})
