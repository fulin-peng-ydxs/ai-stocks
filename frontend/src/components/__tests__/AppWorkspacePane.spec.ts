// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppWorkspacePane from '@/components/AppWorkspacePane.vue'
import AppControlRow from '@/components/AppControlRow.vue'
import AppScrollArea from '@/components/AppScrollArea.vue'

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
    expect(wrapper.findComponent(AppScrollArea).exists()).toBe(false)
    expect(wrapper.find('.app-workspace-pane__toolbar').exists()).toBe(false)
    expect(wrapper.find('.app-workspace-pane__footer').exists()).toBe(false)
  })

  it('工具与底部操作行共用尺寸，正文滚动不包含这两个固定区域', () => {
    const wrapper = mount(AppWorkspacePane, {
      props: { title: '填报', headerVisible: false, padding: 'standard', scroll: 'body', fill: true },
      slots: {
        toolbar: '<input aria-label="交易日" />',
        default: '<input aria-label="填写内容" />',
        footer: '<button>提交</button>',
      },
    })
    const scroll = wrapper.findComponent(AppScrollArea)
    expect(scroll.find('[aria-label="填写内容"]').exists()).toBe(true)
    expect(scroll.find('[aria-label="交易日"]').exists()).toBe(false)
    expect(scroll.find('button').exists()).toBe(false)
    const rows = wrapper.findAllComponents(AppControlRow)
    expect(rows).toHaveLength(2)
    expect(rows.map(row => row.attributes('data-control-row'))).toEqual(['default', 'default'])
    expect(wrapper.get('.app-workspace-pane__footer').text()).toBe('提交')
    wrapper.unmount()
  })

  it('委托滚动模式保留内部工作区，不再增加第二个滚动容器', () => {
    const wrapper = mount(AppWorkspacePane, {
      props: { title: '持仓明细', padding: 'standard', fill: true },
      slots: { default: '<div data-testid="table-workspace">内部表格</div>' },
    })
    expect(wrapper.findComponent(AppScrollArea).exists()).toBe(false)
    expect(wrapper.get('.app-workspace-pane__body > [data-testid="table-workspace"]').text()).toBe('内部表格')
    wrapper.unmount()
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
