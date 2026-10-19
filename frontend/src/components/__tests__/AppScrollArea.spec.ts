// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppScrollArea from '@/components/AppScrollArea.vue'

describe('AppScrollArea 内容尺寸', () => {
  it('内容宽度扣除绘制内距，增加安全区不增加业务可用宽度', async () => {
    const wrapper = mount(AppScrollArea, {
      props: { contentStyle: { padding: '8px' } },
      attachTo: document.body,
    })
    try {
      const view = wrapper.get('.app-scroll-area__content').element
      Object.defineProperty(view, 'clientWidth', { configurable: true, value: 1016 })
      expect(wrapper.vm.getContentWidth()).toBe(1000)

      await wrapper.setProps({ contentStyle: { padding: '16px 20px' } })
      Object.defineProperty(view, 'clientWidth', { configurable: true, value: 1040 })
      expect(wrapper.vm.getContentWidth()).toBe(1000)

      Object.defineProperty(view, 'clientWidth', { configurable: true, value: 0 })
      expect(wrapper.vm.getContentWidth()).toBe(0)
    } finally {
      wrapper.unmount()
    }
  })
})
