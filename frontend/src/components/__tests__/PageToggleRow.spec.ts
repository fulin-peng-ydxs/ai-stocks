// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageSettingItem from '@/components/PageSettingItem.vue'
import PageToggleRow from '@/components/PageToggleRow.vue'

describe('PageToggleRow', () => {
  it('委托共享事项排版并保留开关值、禁用、提示和事件', async () => {
    const wrapper = mount(PageToggleRow, {
      props: { label: '默认展开稳健性测试', modelValue: true, disabled: true, tip: '进入页面时生效', testId: 'robust' },
      global: { stubs: {
        ElSwitch: {
          props: ['modelValue', 'disabled'],
          emits: ['update:modelValue'],
          template: '<button role="switch" :disabled="disabled" :aria-checked="modelValue" @click="$emit(\'update:modelValue\', !modelValue)"/>',
        },
      } },
    })
    const item = wrapper.getComponent(PageSettingItem)
    expect(item.props()).toMatchObject({ label: '默认展开稳健性测试', hint: '进入页面时生效', layout: 'inline' })
    expect(wrapper.get('[data-testid="robust-switch"]').attributes()).toMatchObject({ disabled: '', 'aria-checked': 'true' })
    await wrapper.setProps({ disabled: false })
    await wrapper.get('[role="switch"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })
})
