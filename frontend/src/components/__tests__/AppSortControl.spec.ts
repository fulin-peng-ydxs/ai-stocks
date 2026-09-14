// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AppSortControl from '@/components/AppSortControl.vue'

const options = [
  { value: 'return', label: '累计涨幅' },
  { value: 'industry', label: '行业' },
]

function mountControl() {
  return mount(AppSortControl, {
    props: {
      modelValue: 'return',
      order: 'desc',
      options,
      ariaLabel: '卡片层内排序',
      testId: 'card-sort',
    },
    global: { plugins: [ElementPlus] },
  })
}

describe('AppSortControl', () => {
  it('统一展示当前排序字段并选择新的排序字段', () => {
    const wrapper = mountControl()

    expect(wrapper.get('[data-testid="card-sort"]').text()).toContain('排序 · 累计涨幅')
    wrapper.findComponent({ name: 'ElDropdown' }).vm.$emit('command', 'industry')

    expect(wrapper.emitted('update:modelValue')).toEqual([['industry']])
  })

  it('方向按钮说明下一步动作并切换升降序', async () => {
    const wrapper = mountControl()
    const orderButton = wrapper.get('[data-testid="card-sort-order"]')

    expect(orderButton.attributes('aria-label')).toBe('切换为升序')
    await orderButton.trigger('click')

    expect(wrapper.emitted('update:order')).toEqual([['asc']])
  })

  it('忽略选项集合之外的命令值', () => {
    const wrapper = mountControl()
    wrapper.findComponent({ name: 'ElDropdown' }).vm.$emit('command', 'unknown')

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})
