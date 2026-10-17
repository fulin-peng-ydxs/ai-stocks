// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppWorkspacePane from '@/components/AppWorkspacePane.vue'

describe('AppWorkspacePane', () => {
  it('统一渲染栏级标题、操作与内容', () => {
    const wrapper = mount(AppWorkspacePane, {
      props: { title: '行情走势', eyebrow: '当前观察' },
      slots: {
        actions: '<button data-testid="panel-action">近 120 日</button>',
        default: '<div data-testid="panel-content">图表</div>',
      },
    })

    expect(wrapper.get('.app-workspace-pane__header').text()).toContain('行情走势')
    expect(wrapper.get('.app-workspace-pane__eyebrow').text()).toBe('当前观察')
    expect(wrapper.get('[data-testid="panel-action"]').text()).toBe('近 120 日')
    expect(wrapper.get('[data-testid="panel-content"]').text()).toBe('图表')
    expect(wrapper.attributes('aria-label')).toBe('行情走势')
  })

  it('已有抽屉标题时可隐藏重复栏头但保留内容', () => {
    const wrapper = mount(AppWorkspacePane, {
      props: { title: '分析概览', headerVisible: false },
      slots: { default: '<div data-testid="panel-content">所属板块</div>' },
    })

    expect(wrapper.find('.app-workspace-pane__header').exists()).toBe(false)
    expect(wrapper.get('[data-testid="panel-content"]').text()).toBe('所属板块')
    expect(wrapper.attributes('aria-label')).toBe('分析概览')
  })

})
