// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import VColumns from '@/layout/components/VColumns.vue'

afterEach(() => { vi.unstubAllGlobals() })

describe('VColumns 绘制安全区与断点', () => {
  it('按实际内容宽度跨越断点，不能把视口安全区计入列数', async () => {
    let contentWidth = 1000
    let resize: (() => void) | undefined
    const viewport = document.createElement('div')
    Object.defineProperty(viewport, 'clientWidth', { get: () => contentWidth + 16 })
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe() {}
      disconnect() {}
    })
    const scrollArea = defineComponent({
      props: ['contentStyle'],
      setup(props, { expose }) {
        expose({ viewport, getContentWidth: () => contentWidth })
        return () => h('div', { style: props.contentStyle })
      },
    })
    const wrapper = mount(VColumns, {
      props: {
        slots: [],
        breakpoints: [{ minWidth: 0, columns: 1 }, { minWidth: 1008, columns: 2 }],
      },
      global: { stubs: { AppScrollArea: scrollArea } },
    })
    try {
      await nextTick()
      expect(wrapper.attributes('style')).toContain('repeat(1, minmax(0, 1fr))')
      contentWidth = 1008
      resize?.()
      await nextTick()
      expect(wrapper.attributes('style')).toContain('repeat(2, minmax(0, 1fr))')
    } finally {
      wrapper.unmount()
    }
  })
})
