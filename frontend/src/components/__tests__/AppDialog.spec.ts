// @vitest-environment jsdom
import { ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AppDialog from '@/components/AppDialog.vue'
import { PAGE_OVERLAY_TARGET } from '@/layout/pageOverlay'

describe('AppDialog 浮层边界', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('默认仍使用页面挂载点，应用级确认可显式越过页面边界', async () => {
    const target = document.createElement('div')
    document.body.append(target)
    const wrapper = mount(AppDialog, {
      props: { modelValue: true, title: '确认' },
      global: { plugins: [ElementPlus], provide: { [PAGE_OVERLAY_TARGET as symbol]: ref(target) } },
    })
    expect(wrapper.findComponent({ name: 'ElDialog' }).props('appendTo')).toBe(target)
    await wrapper.setProps({ boundary: 'app' })
    expect(wrapper.findComponent({ name: 'ElDialog' }).props('appendTo')).toBe('body')
    wrapper.unmount()
  })

  it('用户中心等应用级确认无页面挂载点也不产生边界告警', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const wrapper = mount(AppDialog, {
      props: { modelValue: false, boundary: 'app' },
      global: { plugins: [ElementPlus] },
    })
    expect(wrapper.findComponent({ name: 'ElDialog' }).props('appendTo')).toBe('body')
    expect(warn).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
