// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ElementPlus from 'element-plus'
import PageSettingsApplyButton from '@/components/PageSettingsApplyButton.vue'

describe('PageSettingsApplyButton', () => {
  it('统一使用设置抽屉的主色朴素按钮语义', async () => {
    const wrapper = mount(PageSettingsApplyButton, {
      props: { label: '使用页面当前比例', testId: 'apply-current' },
      global: { plugins: [ElementPlus] },
    })

    const button = wrapper.get('[data-testid="apply-current"]')
    expect(button.classes()).toContain('el-button--primary')
    expect(button.classes()).toContain('is-plain')
    await button.trigger('click')
    expect(wrapper.emitted('click')).toHaveLength(1)
  })

  it('保存期间展示 loading 并在组件边界拒绝重复点击', async () => {
    const wrapper = mount(PageSettingsApplyButton, {
      props: { loading: true, testId: 'apply-current' },
      global: { plugins: [ElementPlus] },
    })

    const button = wrapper.get('[data-testid="apply-current"]')
    expect(button.classes()).toContain('is-loading')
    await button.trigger('click')
    expect(wrapper.emitted('click')).toBeUndefined()
  })
})
