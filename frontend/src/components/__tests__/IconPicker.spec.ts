// @vitest-environment jsdom
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import IconPicker from '../IconPicker.vue'

describe('IconPicker 键盘选择', () => {
  it('复用弹出层键盘触发，候选可通过 Enter/Space 选择', async () => {
    const wrapper = mount(IconPicker, {
      props: { modelValue: null },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    const trigger = wrapper.get('.ip-trigger')
    expect(trigger.attributes('tabindex')).toBe('0')
    await trigger.trigger('keydown', { key: 'Enter', code: 'Enter' })
    await flushPromises()
    await vi.waitFor(() => expect(trigger.attributes('aria-expanded')).toBe('true'))
    const option = document.querySelector<HTMLElement>('.ip-cell')!
    expect(option).toBeTruthy()
    option.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }))
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([[option.getAttribute('aria-label')]])
    expect(trigger.attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })

  it('禁用入口不能经键盘打开', async () => {
    const wrapper = mount(IconPicker, {
      props: { modelValue: null, disabled: true },
      global: { plugins: [ElementPlus] },
    })
    const trigger = wrapper.get('.ip-trigger')
    expect(trigger.attributes('tabindex')).toBe('-1')
    await trigger.trigger('keydown', { key: 'Enter', code: 'Enter' })
    await flushPromises()
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })

  it('浮层打开后禁用仍禁止清除当前值', async () => {
    const wrapper = mount(IconPicker, {
      props: { modelValue: 'Search' },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await wrapper.get('.ip-trigger').trigger('keydown', { key: 'Enter', code: 'Enter' })
    await flushPromises()
    await wrapper.setProps({ disabled: true })
    const clear = Array.from(document.querySelectorAll('button')).find(button => button.textContent?.includes('清除图标'))!
    expect(clear.disabled).toBe(true)
    clear.click()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })

})
