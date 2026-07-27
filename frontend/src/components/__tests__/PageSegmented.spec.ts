// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageSegmented from '../PageSegmented.vue'

describe('PageSegmented', () => {
  it('按需输出稳定 E2E 锚点，不影响原有分段选择行为', async () => {
    const wrapper = mount(PageSegmented, {
      props: {
        modelValue: 'md',
        'aria-label': '抽屉尺寸',
        testId: 'drawer-size',
        options: [
          { label: '小', value: 'sm' },
          { label: '中', value: 'md' },
          { label: '大', value: 'lg' },
        ],
      },
    })

    expect(wrapper.attributes('role')).toBe('group')
    expect(wrapper.attributes('aria-label')).toBe('抽屉尺寸')
    expect(wrapper.attributes('data-testid')).toBe('drawer-size')
    expect(wrapper.get('[data-testid="drawer-size-md"]').classes()).toContain('active')
    expect(wrapper.get('[data-testid="drawer-size-md"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="drawer-size-sm"]').attributes('aria-pressed')).toBe('false')

    await wrapper.get('[data-testid="drawer-size-lg"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['lg'])

    await wrapper.setProps({ modelValue: 'lg' })
    expect(wrapper.get('[data-testid="drawer-size-md"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-testid="drawer-size-lg"]').attributes('aria-pressed')).toBe('true')
  })

  it('支持由页面已有标题提供可访问名称关联', () => {
    const wrapper = mount(PageSegmented, {
      props: {
        modelValue: 'all',
        'aria-label': '显示范围',
        'aria-labelledby': 'source-mode-label',
        options: [
          { label: '全部源', value: 'all' },
          { label: '只主源', value: 'primary' },
        ],
      },
    })

    expect(wrapper.attributes('role')).toBe('group')
    expect(wrapper.attributes('aria-label')).toBe('显示范围')
    expect(wrapper.attributes('aria-labelledby')).toBe('source-mode-label')
  })
})
