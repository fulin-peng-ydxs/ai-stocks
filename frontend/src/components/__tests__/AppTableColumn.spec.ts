// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h, inject, onBeforeUnmount, onMounted } from 'vue'
import { describe, expect, it } from 'vitest'
import AppTableColumn from '@/components/AppTableColumn.vue'
import {
  estimateHeaderTextWidth,
  inferAdaptiveColumnRole,
  resolveActionColumnWidth,
  resolveAdaptiveColumnWidth,
} from '@/components/table/adaptiveColumnWidth'
import { ROW_ACTION_COLUMN_WIDTH_CONTEXT } from '@/components/table/rowActionColumnWidth'

const ElTableColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: ['label', 'prop', 'type', 'width', 'minWidth'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'column',
      'data-type': props.type,
      'data-width': props.width,
      'data-min-width': props.minWidth,
    }, [
      ...(slots.default?.({ row: { value: '测试值' }, $index: 0 }) ?? []),
      ...(slots.header?.({ column: {} }) ?? []),
    ])
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

  it('操作列按动作密度使用两档默认下限且不主动吞占表格余量', () => {
    expect(resolveAdaptiveColumnWidth({ label: '操作', role: 'action' })).toMatchObject({
      role: 'action',
      width: 144,
    })
    expect(resolveAdaptiveColumnWidth({ label: '操作', role: 'action-compact' })).toMatchObject({
      role: 'action-compact',
      width: 96,
    })
    expect(resolveActionColumnWidth(144, [120, 188, 160.2])).toBe(188)
    expect(resolveActionColumnWidth(96, [72])).toBe(96)
    expect(resolveActionColumnWidth(144, [160.2])).toBe(161)
  })

  it('操作列取所有已渲染行最低需求的最大值', async () => {
    const sources = [Symbol('short-row'), Symbol('long-row')]
    const WidthReporter = defineComponent({
      props: { index: { type: Number, required: true } },
      setup(props) {
        const context = inject(ROW_ACTION_COLUMN_WIDTH_CONTEXT)
        const source = sources[props.index]
        onMounted(() => context?.setMinimumWidth(source, props.index === 0 ? 132 : 188))
        onBeforeUnmount(() => context?.removeMinimumWidth(source))
        return () => h('span', `row-${props.index}`)
      },
    })
    const wrapper = mount(AppTableColumn, {
      props: { label: '操作', role: 'action' },
      slots: {
        default: () => [h(WidthReporter, { index: 0 }), h(WidthReporter, { index: 1 })],
      },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    await wrapper.vm.$nextTick()
    expect(wrapper.get('.column').attributes('data-width')).toBe('188')
  })

  it('复合实体列为前置控件和主副信息保留统一识别宽度', () => {
    expect(resolveAdaptiveColumnWidth({
      role: 'entity',
      label: '板块',
      prop: 'name',
      leadingControls: 2,
    })).toMatchObject({
      role: 'entity',
      minWidth: 208,
      headerIndent: 56,
    })
  })

  it.each([
    ['中文字段', 56],
    ['AB12', 37],
    ['field', 40],
    ['10日涨幅', 61],
  ])('以稳定字符权重估算混排表头：%s', (label, width) => {
    expect(estimateHeaderTextWidth(label)).toBe(width)
  })

  it('按表头文字、排序与筛选控件动态提高语义最小宽度', () => {
    const plain = resolveAdaptiveColumnWidth({ role: 'number', label: '今日涨幅' })
    const sortable = resolveAdaptiveColumnWidth({
      role: 'number',
      label: '今日涨幅',
      sortable: true,
    })
    const sortableAndFilterable = resolveAdaptiveColumnWidth({
      role: 'number',
      label: '今日涨幅',
      sortable: true,
      filterable: true,
    })
    const longHeader = resolveAdaptiveColumnWidth({
      role: 'number',
      label: '累计收益贡献率',
      sortable: true,
    })

    expect(plain.minWidth).toBe(96)
    expect(sortable.minWidth).toBe(112)
    expect(sortableAndFilterable.minWidth).toBe(136)
    expect(longHeader.minWidth).toBe(160)
  })

  it('二级表头按两行较宽内容计算且遵守语义上限', () => {
    expect(resolveAdaptiveColumnWidth({
      role: 'number',
      label: '即时净流入',
      headerMeta: '08-12',
      sortable: true,
    }).minWidth).toBe(176)
    expect(resolveAdaptiveColumnWidth({
      role: 'number',
      label: '这是一个异常长且不应该无限撑开表格的动态指标名称',
      sortable: true,
    }).minWidth).toBe(192)
  })

  it('统一渲染二级表头且完整可见时不制造冗余 title', () => {
    const wrapper = mount(AppTableColumn, {
      props: {
        label: '即时净流入',
        prop: 'net_inflow',
        role: 'number',
        headerMeta: '08-12',
      },
      attrs: { sortable: 'custom' },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    expect(wrapper.get('.column').attributes('data-min-width')).toBe('176')
    expect(wrapper.get('.app-table-column-header__label').text()).toBe('即时净流入')
    expect(wrapper.get('.app-table-column-header__meta').text()).toBe('08-12')
    expect(wrapper.get('.app-table-column-header').classes()).toContain('app-table-column-header')
    expect(wrapper.get('.app-table-column-header').attributes('title')).toBeUndefined()
  })

  it('把前置控件缩进下沉到标准表头，不要求页面编写私有 header 样式', () => {
    const wrapper = mount(AppTableColumn, {
      props: {
        label: '板块',
        role: 'entity',
        leadingControls: 2,
      },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    expect(wrapper.get('.column').attributes('data-min-width')).toBe('208')
    expect(wrapper.get('.app-table-column-header').attributes('style')).toContain(
      '--app-table-column-header-indent: 56px',
    )
  })

  it('异常长表头达到角色宽度上限后保留完整 title', () => {
    const label = '这是一个异常长且不应该无限撑开表格的动态指标名称'
    const wrapper = mount(AppTableColumn, {
      props: { label, role: 'number' },
      attrs: { sortable: 'custom' },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    expect(wrapper.get('.column').attributes('data-min-width')).toBe('192')
    expect(wrapper.get('.app-table-column-header').attributes('title')).toBe(label)
  })

  it('自定义表头优先于标准表头且仍预留安全空间', () => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '长期业务状态', role: 'status' },
      slots: { header: '<span class="custom-header">业务表头</span>' },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    expect(wrapper.get('.custom-header').text()).toBe('业务表头')
    expect(wrapper.find('.app-table-column-header').exists()).toBe(false)
    expect(wrapper.get('.column').attributes('data-min-width')).toBe('136')
  })
})
