// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PageSettingItem from '@/components/PageSettingItem.vue'

describe('PageSettingItem', () => {
  it('默认使用堆叠布局并统一渲染事项名、控件和辅助说明', () => {
    const wrapper = mount(PageSettingItem, {
      props: { label: '默认视图' },
      slots: { default: '<button>全市场</button>', help: '下次进入页面时生效' },
    })

    expect(wrapper.classes()).toContain('is-stacked')
    expect(wrapper.find('.psi-label').text()).toBe('默认视图')
    expect(wrapper.find('.psi-control').text()).toBe('全市场')
    expect(wrapper.find('.psi-help').text()).toBe('下次进入页面时生效')
  })

  it('行内布局和 label 插槽支持开关类事项', () => {
    const wrapper = mount(PageSettingItem, {
      props: { layout: 'inline' },
      slots: { label: '排除 ST', default: '<input type="checkbox" />' },
    })

    expect(wrapper.classes()).toContain('is-inline')
    expect(wrapper.find('.psi-label').text()).toBe('排除 ST')
    expect(wrapper.find('input').exists()).toBe(true)
  })
})
