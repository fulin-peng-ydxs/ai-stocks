// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StrategyItemEnabledSwitch from '@/components/strategy/StrategyItemEnabledSwitch.vue'

describe('StrategyItemEnabledSwitch', () => {
  it('统一透传启停值、变更事件和只读状态', async () => {
    const wrapper = mount(StrategyItemEnabledSwitch, {
      props: { modelValue: true, label: '是否启用测试条件' },
      global: { plugins: [ElementPlus] },
    })
    await wrapper.find('input').setValue(false)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
    expect(wrapper.emitted('change')?.[0]).toEqual([false])

    await wrapper.setProps({ disabled: true })
    expect(wrapper.find('input').attributes('disabled')).toBeDefined()
  })
})
