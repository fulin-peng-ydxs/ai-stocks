// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppIconButton from '../AppIconButton.vue'

describe('AppIconButton', () => {
  it('为纯图标操作提供统一尺寸、语义标签和状态样式', () => {
    const wrapper = mount(AppIconButton, {
      props: { label: '刷新状态', size: 'sm', variant: 'soft', tone: 'primary' },
      slots: { default: '<svg data-test="icon" />' },
    })

    const button = wrapper.get('button')
    expect(button.attributes('type')).toBe('button')
    expect(button.attributes('aria-label')).toBe('刷新状态')
    expect(button.attributes('title')).toBe('刷新状态')
    expect(button.classes()).toEqual(expect.arrayContaining(['is-sm', 'is-soft', 'is-primary']))
    expect(wrapper.find('[data-test="icon"]').exists()).toBe(true)
  })

  it('透传点击事件，禁用态由原生 button 阻止触发', async () => {
    const wrapper = mount(AppIconButton, { props: { label: '关闭' } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)

    await wrapper.setProps({ disabled: true })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })
})
