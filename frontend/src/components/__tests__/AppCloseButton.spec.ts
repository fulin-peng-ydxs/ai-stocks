// @vitest-environment jsdom
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppCloseButton from '../AppCloseButton.vue'
import AppIconButton from '../AppIconButton.vue'

describe('关闭语义入口', () => {
  it.each(['default', 'compact', 'inline'] as const)('档位 %s 复用图标按钮且保留完整可访问名称', size => {
    const wrapper = mount(AppCloseButton, { props: { label: '关闭板块详情', size } })
    expect(wrapper.findComponent(AppIconButton).exists()).toBe(true)
    expect(wrapper.get('button').attributes()).toMatchObject({ 'data-close-size': size, 'aria-label': '关闭板块详情', type: 'button' })
    expect(wrapper.get('button').attributes('title')).toBeUndefined()
    expect(wrapper.find('svg').exists()).toBe(true)
    wrapper.unmount()
  })

  it('关闭点击和激活键不触发父项，Escape 仍能交给浮层', async () => {
    const host = defineComponent({ components: { AppCloseButton }, data: () => ({ clicks: 0, keys: '', closes: 0 }),
      template: `<div @click="clicks++" @keydown="keys += $event.key"><AppCloseButton label="移除对比" @click="closes++" /></div>`,
    })
    const wrapper = mount(host)
    await wrapper.get('button').trigger('click')
    await wrapper.get('button').trigger('keydown', { key: 'Enter' })
    await wrapper.get('button').trigger('keydown', { key: ' ' })
    expect(wrapper.vm.clicks).toBe(0)
    expect(wrapper.vm.closes).toBe(1)
    expect(wrapper.vm.keys).toBe('')
    await wrapper.get('button').trigger('keydown', { key: 'Escape' })
    expect(wrapper.vm.keys).toBe('Escape')
    wrapper.unmount()
  })

  it('禁用和加载均阻止关闭，外部已有提示时不叠原生 title', async () => {
    const wrapper = mount(AppCloseButton, { props: { label: '关闭', disabled: true, nativeTitle: false } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('click')).toBeUndefined()
    expect(wrapper.get('button').attributes('title')).toBeUndefined()
    await wrapper.setProps({ disabled: false, loading: true })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('click')).toBeUndefined()
    expect(wrapper.get('button').attributes('aria-busy')).toBe('true')
    wrapper.unmount()
  })
})
