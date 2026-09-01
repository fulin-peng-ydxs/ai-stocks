// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppTabToolbar from '@/components/AppTabToolbar.vue'

describe('AppTabToolbar', () => {
  it('统一将操作放在左侧、说明放在右侧', () => {
    const wrapper = mount(AppTabToolbar, {
      props: { label: '测试操作栏' },
      slots: {
        actions: '<button data-testid="action">筛选</button>',
        description: '<span data-testid="description">当前面板说明</span>',
      },
    })

    expect(wrapper.find('.app-tab-toolbar__actions [data-testid="action"]').exists()).toBe(true)
    expect(wrapper.find('.app-tab-toolbar__description [data-testid="description"]').text())
      .toBe('当前面板说明')
    expect(wrapper.attributes('role')).toBe('toolbar')
    expect(wrapper.attributes('aria-label')).toBe('测试操作栏')
  })

  it('没有操作时不渲染空操作容器', () => {
    const wrapper = mount(AppTabToolbar, {
      props: { label: '仅说明操作栏' },
      slots: { description: '仅说明' },
    })

    expect(wrapper.find('.app-tab-toolbar__actions').exists()).toBe(false)
    expect(wrapper.find('.app-tab-toolbar__description').text()).toBe('仅说明')
  })
})
