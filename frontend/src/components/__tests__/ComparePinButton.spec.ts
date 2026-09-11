// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ComparePinButton from '@/components/ComparePinButton.vue'

describe('ComparePinButton', () => {
  it('统一呈现对比图标的激活态并触发切换', async () => {
    const wrapper = mount(ComparePinButton, {
      props: { active: true, label: '移出走势对比：测试标的' },
      global: { stubs: { ElIcon: true } },
    })

    expect(wrapper.classes()).toContain('compare-pin-button--active')
    expect(wrapper.get('button').attributes('aria-label')).toBe('移出走势对比：测试标的')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })
})
