// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import ChartOperationBar from '@/components/ChartOperationBar.vue'
import ChartOperationGroup from '@/components/ChartOperationGroup.vue'

describe('ChartOperationBar', () => {
  it('以左对齐工具栏承载带名称和边界的操作组', () => {
    const wrapper = mount(ChartOperationBar, {
      props: { label: 'K线图表操作' },
      slots: {
        default: () => h(ChartOperationGroup, { label: '涨跌测算' }, {
          default: () => h('button', '截止'),
        }),
      },
    })

    const toolbar = wrapper.get('[role="toolbar"]')
    expect(toolbar.attributes('aria-label')).toBe('K线图表操作')
    expect(toolbar.get('.chart-operation-bar__actions').classes()).toContain('is-justify-start')
    expect(toolbar.get('.chart-operation-group').text()).toBe('涨跌测算截止')
    expect(toolbar.get('button').text()).toBe('截止')
  })
})
