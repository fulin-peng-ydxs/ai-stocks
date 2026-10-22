// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppTabToolbar from '@/components/AppTabToolbar.vue'

describe('AppTabToolbar', () => {
  it('筛选型工具栏默认从左起排，说明保留独立区域', () => {
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
    expect(wrapper.find('.app-tab-toolbar__actions').classes()).toContain('is-justify-start')
  })

  it('纯命令组支持右对齐，反馈独立呈现，切换对齐不重建输入', async () => {
    const wrapper = mount(AppTabToolbar, {
      props: { label: '配置操作栏', actionsAlign: 'end' },
      slots: { actions: '<input aria-label="临时输入" /><button>保存</button>', description: '当前页签配置不合法' },
    })
    const input = wrapper.get('input')
    await input.setValue('保留草稿')
    expect(wrapper.classes()).toContain('is-actions-end')
    expect(wrapper.get('.app-tab-toolbar__actions').classes()).toContain('is-justify-end')
    expect(wrapper.get('.app-tab-toolbar__description').text()).toBe('当前页签配置不合法')
    await wrapper.setProps({ actionsAlign: 'start' })
    expect(wrapper.classes()).not.toContain('is-actions-end')
    expect(wrapper.get('input').element).toBe(input.element)
    expect((input.element as HTMLInputElement).value).toBe('保留草稿')
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
