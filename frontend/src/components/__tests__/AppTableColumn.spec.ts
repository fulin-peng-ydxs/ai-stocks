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
import { ACTION_COLUMN_CLASS } from '@/components/table/cellVisualOverflow'

const ElTableColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: [
    'label',
    'prop',
    'type',
    'width',
    'minWidth',
    'align',
    'headerAlign',
    'className',
  ],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'column',
      'data-type': props.type,
      'data-width': props.width,
      'data-min-width': props.minWidth,
      'data-align': props.align,
      'data-header-align': props.headerAlign,
      'data-class-name': props.className,
    }, [
      ...(slots.default?.({ row: { value: '测试值' }, $index: 0 }) ?? []),
      ...(slots.header?.({ column: {} }) ?? []),
    ])
  },
})

describe('自适应表格列', () => {
  it('动态表头括注转为元信息，更新与可访问列名均不含括号', async () => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '市值（元）', headerMeta: '截止日(最新)' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    expect(wrapper.get('.app-table-column-header__label').text()).toBe('市值')
    expect(wrapper.get('.app-table-column-header__meta').text()).toBe('元 · 截止日 最新')
    expect(wrapper.findComponent(ElTableColumnStub).props('label')).toBe('市值')
    await wrapper.setProps({ label: '持有(日)', headerMeta: '' })
    expect(wrapper.get('.app-table-column-header').text()).toBe('持有日')
    wrapper.unmount()
  })

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

  it('长排名标题按标题和排序控件自适应，不套用 60px 序号列', () => {
    const sizing = resolveAdaptiveColumnWidth({
      role: 'rank',
      label: '全市场排名',
      sortable: true,
    })
    expect(sizing.role).toBe('rank')
    expect(sizing.width).toBeUndefined()
    expect(sizing.minWidth).toBeGreaterThanOrEqual(120)
  })

  it('开关列保留控件、留白和操作空间，不占结构列宽度或富余空间', () => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '启用', role: 'switch' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    expect(wrapper.get('.column').attributes('data-width')).toBe('80')
    expect(wrapper.get('.column').attributes('data-align')).toBe('center')
    expect(wrapper.get('.column').attributes('data-class-name')).not.toContain('overflow-aware')
    expect(resolveAdaptiveColumnWidth({ type: 'selection' }).width).toBe(48)
  })

  it.each([
    ['compact', 120], ['short', 168], ['medium', 208], ['long', 248], ['wide', 328],
  ] as const)('编辑控件 %s 档位计入单元格留白并向上对齐网格', (controlWidth, minWidth) => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '值', role: 'number', controlWidth },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    expect(wrapper.get('.column').attributes('data-min-width')).toBe(String(minWidth))
    expect(wrapper.get('.column').attributes('data-width')).toBeUndefined()
    expect(resolveAdaptiveColumnWidth({ role: 'description', controlWidth: 'compact' }).minWidth).toBe(200)
  })

  it('内容列默认统一启用真实溢出判定，结构列和操作列保持专用契约', () => {
    const content = mount(AppTableColumn, {
      props: { label: '评级', prop: 'grade' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    const structural = mount(AppTableColumn, {
      props: { type: 'selection' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    const action = mount(AppTableColumn, {
      props: { label: '操作', role: 'action' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })

    expect(content.get('.column').attributes('data-class-name')).toContain(
      'app-table-column--overflow-aware',
    )
    expect(structural.get('.column').attributes('data-class-name')).not.toContain(
      'app-table-column--overflow-aware',
    )
    expect(action.get('.column').attributes('data-class-name')).not.toContain(
      'app-table-column--overflow-aware',
    )
    expect(action.get('.column').attributes('data-class-name')).toContain(ACTION_COLUMN_CLASS)
  })

  it('长文本列通过统一列选项启用单行省略，普通列保持自然换行', () => {
    const summary = mount(AppTableColumn, {
      props: { label: '信息', prop: 'message', singleLine: true },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    const normal = mount(AppTableColumn, {
      props: { label: '说明' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })

    expect(summary.get('.column').attributes('data-class-name')).toContain(
      'app-table-column--single-line',
    )
    expect(normal.get('.column').attributes('data-class-name')).not.toContain(
      'app-table-column--single-line',
    )
  })

  it('忽略遗留的列级 tooltip 配置，统一交给自动溢出机制', () => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '状态' },
      attrs: { 'show-overflow-tooltip': false },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })

    expect(wrapper.get('.column').attributes('data-class-name')).toContain(
      'app-table-column--overflow-aware',
    )
    expect(wrapper.get('.column').attributes('show-overflow-tooltip')).toBeUndefined()
  })

  it('长文本、代码、状态和数值使用不同的自适应权重', () => {
    expect(inferAdaptiveColumnRole({ label: '详细说明' })).toBe('description')
    expect(inferAdaptiveColumnRole({ label: '股票代码', prop: 'code' })).toBe('code')
    expect(inferAdaptiveColumnRole({ label: '采集状态' })).toBe('status')
    expect(inferAdaptiveColumnRole({ label: '收益率' })).toBe('number')
    expect(resolveAdaptiveColumnWidth({ label: '评级' })).toMatchObject({
      role: 'status',
      minWidth: 112,
    })
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

  it('所有语义列统一推导表头和单元格对齐，并忽略调用方手写覆盖', async () => {
    const wrapper = mount(AppTableColumn, {
      props: { label: '操作', role: 'action' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })

    expect(wrapper.get('.column').attributes('data-align')).toBe('center')
    expect(wrapper.get('.column').attributes('data-header-align')).toBe('center')

    await wrapper.setProps({ role: 'text' })
    expect(wrapper.get('.column').attributes('data-align')).toBe('left')
    expect(wrapper.get('.column').attributes('data-header-align')).toBe('left')

    await wrapper.setProps({ role: 'number' })
    expect(wrapper.get('.column').attributes('data-align')).toBe('right')
    expect(wrapper.get('.column').attributes('data-header-align')).toBe('right')
    expect(wrapper.get('.column').attributes('data-class-name')).toContain(
      'app-table-column--tabular',
    )

    await wrapper.setProps({ role: 'comparison-number' })
    expect(wrapper.get('.column').attributes('data-align')).toBe('center')
    expect(wrapper.get('.column').attributes('data-header-align')).toBe('center')
    expect(wrapper.get('.column').attributes('data-class-name')).toContain(
      'app-table-column--tabular',
    )

    await wrapper.setProps({ role: 'status' })
    expect(wrapper.get('.column').attributes('data-align')).toBe('center')
    expect(wrapper.get('.column').attributes('data-header-align')).toBe('center')

    const overridden = mount(AppTableColumn, {
      props: { label: '操作', role: 'action-compact' },
      attrs: { align: 'right', 'header-align': 'left' },
      global: { stubs: { ElTableColumn: ElTableColumnStub } },
    })
    expect(overridden.get('.column').attributes('data-align')).toBe('center')
    expect(overridden.get('.column').attributes('data-header-align')).toBe('center')
  })

  it.each([
    ['structural', 'center'],
    ['switch', 'center'],
    ['rank', 'center'],
    ['code', 'left'],
    ['name', 'left'],
    ['entity', 'left'],
    ['status', 'center'],
    ['number', 'right'],
    ['comparison-number', 'center'],
    ['date', 'left'],
    ['datetime', 'left'],
    ['key', 'left'],
    ['text', 'left'],
    ['description', 'left'],
    ['action', 'center'],
    ['action-compact', 'center'],
  ] as const)('%s 角色使用 %s 对齐', (role, align) => {
    expect(resolveAdaptiveColumnWidth({ role })).toMatchObject({ role, align })
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
        return () => h('span', {
          'data-column-width': context?.width.value,
        }, `row-${props.index}`)
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
    expect(wrapper.findAll('[data-column-width]').map((row) => row.attributes('data-column-width')))
      .toEqual(['188', '188'])
  })

  it('复合实体列为前置控件和主副信息保留统一识别宽度', () => {
    expect(resolveAdaptiveColumnWidth({
      role: 'entity',
      label: '板块',
      prop: 'name',
      leadingControls: 2,
    })).toMatchObject({
      role: 'entity',
      minWidth: 216,
      headerIndent: 64,
    })
  })

  it('表格内多选下拉按目标标签数预留控件和单元格容量', () => {
    expect(resolveAdaptiveColumnWidth({
      label: '分类',
      filterSelectVisibleTagCount: 1,
    })).toMatchObject({ minWidth: 204 })
    expect(resolveAdaptiveColumnWidth({
      label: '分类',
      filterSelectVisibleTagCount: 2,
    })).toMatchObject({ minWidth: 244 })
    expect(resolveAdaptiveColumnWidth({
      label: '分类',
      filterSelectVisibleTagCount: 3,
    })).toMatchObject({ minWidth: 324 })
    expect(resolveAdaptiveColumnWidth({
      label: '分类',
      filterSelectDisplayMode: 'count',
    })).toMatchObject({ minWidth: 164 })
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

    expect(wrapper.get('.column').attributes('data-min-width')).toBe('216')
    expect(wrapper.get('.app-table-column-header').attributes('style')).toContain(
      '--app-table-column-header-indent: 64px',
    )
  })

  it('异常长表头达到角色宽度上限后交给全局真实截断提示', () => {
    const label = '这是一个异常长且不应该无限撑开表格的动态指标名称'
    const wrapper = mount(AppTableColumn, {
      props: { label, role: 'number' },
      attrs: { sortable: 'custom' },
      global: {
        stubs: { ElTableColumn: ElTableColumnStub },
      },
    })

    expect(wrapper.get('.column').attributes('data-min-width')).toBe('192')
    expect(wrapper.get('.app-table-column-header').attributes('title')).toBeUndefined()
    expect(wrapper.get('.app-table-column-header__label').text()).toBe(label)
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
