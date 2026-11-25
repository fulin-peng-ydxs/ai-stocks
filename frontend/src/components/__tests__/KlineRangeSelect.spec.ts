// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import KlineRangeSelect from '@/components/KlineRangeSelect.vue'

vi.mock('@/composables/useKlinePrefs', () => ({
  useKlinePrefs: () => ({ options: [{ value: 60, label: '近 60 日' }, { value: 1000, label: '近 1000 日' }] }),
}))

describe('KlineRangeSelect', () => {
  it('共享组件持有短枚举容量，选择行为和测试锚点保持透传', async () => {
    const wrapper = mount(KlineRangeSelect, {
      props: { modelValue: 60, testId: 'range' },
      global: { stubs: {
        AppSelect: { name: 'AppSelect', props: ['modelValue', 'width'], template: '<div><slot /></div>' },
        ElOption: true,
      } },
    })
    const select = wrapper.findComponent({ name: 'AppSelect' })
    expect(select.props('width')).toBe('short')
    expect(select.props('modelValue')).toBe(60)
    expect(select.attributes('style')).toBeUndefined()
    expect(select.attributes('data-testid')).toBe('range')
    select.vm.$emit('update:modelValue', 1000)
    expect(wrapper.emitted('update:modelValue')).toEqual([[1000]])
    await wrapper.setProps({ width: 'fill' })
    expect(select.props('width')).toBe('fill')
    wrapper.unmount()
  })
})
