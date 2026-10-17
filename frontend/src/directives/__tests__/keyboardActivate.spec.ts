// @vitest-environment jsdom
import { defineComponent, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { vKeyboardActivate } from '../keyboardActivate'

function setup() {
  const click = vi.fn()
  const disabled = ref(false)
  const wrapper = mount(defineComponent({
    directives: { keyboardActivate: vKeyboardActivate },
    setup: () => ({ click, disabled }),
    template: '<div v-keyboard-activate role="button" tabindex="0" :aria-disabled="disabled" @click="click"><button>子按钮</button></div>',
  }))
  return { wrapper, click, disabled }
}

describe('共享自定义命令键盘激活', () => {
  it('Enter/空格各复用一次 click；子元素不激活父命令', async () => {
    const { wrapper, click } = setup()
    await wrapper.trigger('keydown', { key: 'Enter' })
    await wrapper.trigger('keydown', { key: ' ' })
    expect(click).toHaveBeenCalledTimes(2)
    await wrapper.get('button').trigger('keydown', { key: 'Enter' })
    expect(click).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
  it.each([{ isComposing: true }, { keyCode: 229 }, { repeat: true }, { ctrlKey: true },
    { metaKey: true }, { altKey: true }, { shiftKey: true }])('忽略输入法、长按及组合键 %o', async flags => {
    const { wrapper, click } = setup()
    await wrapper.trigger('keydown', { key: 'Enter', ...flags })
    expect(click).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('动态禁用和繁忙祖先阻止操作，卸载后清理监听', async () => {
    const { wrapper, click, disabled } = setup()
    disabled.value = true
    await wrapper.vm.$nextTick()
    await wrapper.trigger('keydown', { key: ' ' })
    disabled.value = false
    await wrapper.vm.$nextTick()
    wrapper.element.setAttribute('aria-busy', 'true')
    await wrapper.trigger('keydown', { key: 'Enter' })
    expect(click).not.toHaveBeenCalled()
    wrapper.element.removeAttribute('aria-busy')
    const element = wrapper.element
    const spy = vi.spyOn(element as HTMLElement, 'click')
    wrapper.unmount()
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    expect(spy).not.toHaveBeenCalled()
  })
})
