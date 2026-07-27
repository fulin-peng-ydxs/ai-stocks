// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it } from 'vitest'
import AppTableColumn from '@/components/AppTableColumn.vue'
import {
  inferAdaptiveColumnRole,
  resolveAdaptiveColumnWidth,
} from '@/components/table/adaptiveColumnWidth'

const ElTableColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: ['label', 'prop', 'type', 'width', 'minWidth'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'column',
      'data-type': props.type,
      'data-width': props.width,
      'data-min-width': props.minWidth,
    }, slots.default?.({ row: { value: '测试值' }, $index: 0 }))
  },
})

describe('自适应表格列', () => {
  it('根据字段语义选择统一最小宽度并保留默认插槽', () => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '更新时间', prop: 'updated_at' },
      slots: {
        default: '<span class="cell">{{ row.value }}</span>',
      },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    expect(wrapper.get('.column').attributes('data-min-width')).toBe('168')
    expect(wrapper.get('.column').attributes('data-width')).toBeUndefined()
    expect(wrapper.get('.cell').text()).toBe('测试值')
  })

  it('只有选择、展开和序号等结构列使用稳定固定宽度', () => {
    expect(resolveAdaptiveColumnWidth({ type: 'expand' })).toMatchObject({
      role: 'structural',
      width: 48,
    })
    expect(resolveAdaptiveColumnWidth({ role: 'structural' })).toMatchObject({
      role: 'structural',
      width: 48,
    })
    expect(resolveAdaptiveColumnWidth({ type: 'index' })).toMatchObject({
      role: 'rank',
      width: 60,
    })
  })

  it('长文本、代码、状态和数值使用不同的自适应权重', () => {
    expect(inferAdaptiveColumnRole({ label: '详细说明' })).toBe('description')
    expect(inferAdaptiveColumnRole({ label: '股票代码', prop: 'code' })).toBe('code')
    expect(inferAdaptiveColumnRole({ label: '采集状态' })).toBe('status')
    expect(inferAdaptiveColumnRole({ label: '收益率' })).toBe('number')
  })
})
