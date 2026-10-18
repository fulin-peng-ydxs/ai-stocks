// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'

const ElSelectStub = defineComponent({
  name: 'ElSelect',
  props: {
    modelValue: { type: [Array, String], default: '' },
    multiple: { type: Boolean, default: false },
    clearable: { type: Boolean, default: false },
    filterable: { type: Boolean, default: false },
    allowCreate: { type: Boolean, default: false },
    defaultFirstOption: { type: Boolean, default: false },
    collapseTags: { type: Boolean, default: false },
    collapseTagsTooltip: { type: Boolean, default: false },
    maxCollapseTags: { type: Number, default: 1 },
    placeholder: { type: String, default: '' },
    ariaLabel: { type: String, default: '' },
    size: { type: String, default: 'default' },
    fitInputWidth: { type: Boolean, default: false },
    popperClass: { type: String, default: '' },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'el-select',
      'data-multiple': String(props.multiple),
      'data-clearable': String(props.clearable),
      'data-filterable': String(props.filterable),
      'data-allow-create': String(props.allowCreate),
      'data-default-first-option': String(props.defaultFirstOption),
      'data-collapse-tags': String(props.collapseTags),
      'data-collapse-tags-tooltip': String(props.collapseTagsTooltip),
      'data-max-collapse-tags': String(props.maxCollapseTags),
      'data-placeholder': props.placeholder,
      'data-aria-label': props.ariaLabel,
      'data-size': props.size,
      'data-fit-input-width': String(props.fitInputWidth),
      'data-popper-class': props.popperClass,
    }, [
      h('div', { class: 'el-select__wrapper' }, [
        h('div', { class: 'el-select__selection' }, slots.tag?.({}) ?? slots.default?.()),
      ]),
    ])
  },
})

const ElOptionStub = defineComponent({
  name: 'ElOption',
  props: {
    label: { type: String, required: true },
    value: { type: String, required: true },
  },
  setup(props) {
    return () => h('span', { 'data-value': props.value }, props.label)
  },
})

function mountSelect(modelValue: string[] | string, props: Record<string, unknown> = {}) {
  return mount(AppFilterSelect, {
    props: {
      modelValue,
      options: [
        { value: 'a', label: '选项 A' },
        { value: 'b', label: '选项 B' },
        { value: 'c', label: '选项 C' },
      ],
      ...props,
    },
    global: {
      stubs: {
        ElSelect: ElSelectStub,
        ElOption: ElOptionStub,
      },
    },
  })
}

describe('AppFilterSelect', () => {
  it('默认启用多选、搜索、清空，并以 1 个标签作为安全回退', async () => {
    const wrapper = mountSelect(['a', 'b', 'c'])
    await flushPromises()
    const select = wrapper.find('.el-select')
    expect(select.attributes('data-multiple')).toBe('true')
    expect(select.attributes('data-clearable')).toBe('true')
    expect(select.attributes('data-filterable')).toBe('true')
    expect(select.attributes('data-collapse-tags')).toBe('true')
    expect(select.attributes('data-collapse-tags-tooltip')).toBe('true')
    expect(select.attributes('data-max-collapse-tags')).toBe('1')
  })

  it('按调用方声明的可见标签数同时设置折叠阈值和容量宽度', async () => {
    const wrapper = mountSelect(['a', 'b', 'c'], { visibleTagCount: 2 })
    await flushPromises()

    expect(wrapper.get('.el-select').attributes('data-max-collapse-tags')).toBe('2')
    expect(wrapper.get('.app-filter-select').attributes('data-visible-tag-count')).toBe('2')
    expect(wrapper.get('.app-filter-select').classes()).toContain('app-filter-select--visible-tags-2')
  })

  it('count 模式只显示已选数量并使用独立紧凑容量', async () => {
    const wrapper = mountSelect(['a', 'b'], { displayMode: 'count' })
    await flushPromises()

    expect(wrapper.get('.app-filter-select').attributes('data-display-mode')).toBe('count')
    expect(wrapper.get('.app-filter-select').classes()).toContain('app-filter-select--count')
    expect(wrapper.get('.app-filter-select__selection-summary').text()).toBe('已选 2')
  })

  it('全部候选项被选中时默认优先显示全部选中', async () => {
    const tagsMode = mountSelect(['c', 'a', 'b'], { visibleTagCount: 2 })
    const countMode = mountSelect(['a', 'b', 'c'], { displayMode: 'count' })
    await flushPromises()

    expect(tagsMode.get('.app-filter-select').attributes('data-all-selected')).toBe('true')
    expect(tagsMode.get('.app-filter-select__selection-summary').text()).toBe('全部选中')
    expect(countMode.get('.app-filter-select__selection-summary').text()).toBe('全部选中')
  })

  it('支持自定义全选文案，空字符串可关闭优先摘要', async () => {
    const customized = mountSelect(['a', 'b', 'c'], {
      displayMode: 'count',
      allSelectedLabel: '全部板块',
    })
    const disabled = mountSelect(['a', 'b', 'c'], {
      displayMode: 'count',
      allSelectedLabel: '',
    })
    await flushPromises()

    expect(customized.get('.app-filter-select__selection-summary').text()).toBe('全部板块')
    expect(disabled.get('.app-filter-select').attributes('data-all-selected')).toBe('false')
    expect(disabled.get('.app-filter-select__selection-summary').text()).toBe('已选 3')
  })

  it('空候选、部分选中或包含额外值时保持原展示模式', async () => {
    const empty = mountSelect([], { options: [], displayMode: 'count' })
    const partial = mountSelect(['a', 'b'], { displayMode: 'count' })
    const extra = mountSelect(['a', 'b', 'c', 'custom'], { displayMode: 'count' })
    await flushPromises()

    expect(empty.get('.app-filter-select').attributes('data-all-selected')).toBe('false')
    expect(empty.find('.app-filter-select__selection-summary').exists()).toBe(false)
    expect(partial.get('.app-filter-select__selection-summary').text()).toBe('已选 2')
    expect(extra.get('.app-filter-select__selection-summary').text()).toBe('已选 4')
  })

  it('可见标签数限制在组件支持的 1 到 3 档', async () => {
    const tooSmall = mountSelect(['a'], { visibleTagCount: 0 })
    const tooLarge = mountSelect(['a'], { visibleTagCount: 8 })
    await flushPromises()

    expect(tooSmall.get('.el-select').attributes('data-max-collapse-tags')).toBe('1')
    expect(tooLarge.get('.el-select').attributes('data-max-collapse-tags')).toBe('3')
  })

  it('可创建模式、尺寸和弹层宽度策略统一传给底层选择器', async () => {
    const wrapper = mountSelect([], {
      allowCreate: true,
      defaultFirstOption: true,
      size: 'small',
    })
    await flushPromises()

    const select = wrapper.get('.el-select')
    expect(select.attributes('data-allow-create')).toBe('true')
    expect(select.attributes('data-default-first-option')).toBe('true')
    expect(select.attributes('data-size')).toBe('small')
    expect(select.attributes('data-fit-input-width')).toBe('false')
    expect(select.attributes('data-popper-class')).toBe('app-select-popper app-filter-select-popper')
  })

  it('业务单选场景可关闭多选和标签折叠', async () => {
    const wrapper = mountSelect('a', { multiple: false })
    await flushPromises()
    const select = wrapper.find('.el-select')
    expect(select.attributes('data-multiple')).toBe('false')
    expect(select.attributes('data-collapse-tags')).toBe('false')
    expect(select.attributes('data-collapse-tags-tooltip')).toBe('false')
    expect(wrapper.get('.app-filter-select').classes()).not.toContain('app-filter-select--multiple')
  })

  it('多选有选中项时才启用裁剪容器', async () => {
    const wrapper = mountSelect(['a', 'b'])
    await flushPromises()

    const root = wrapper.get('.app-filter-select')
    expect(root.classes()).toContain('app-filter-select--multiple')
    expect(root.classes()).toContain('app-filter-select--has-selection')
  })

  it('空值多选不启用裁剪并用占位文案提供可访问名称', async () => {
    const wrapper = mountSelect([], { placeholder: '事件类型' })
    await flushPromises()

    const root = wrapper.get('.app-filter-select')
    const select = wrapper.get('.el-select')
    expect(root.classes()).toContain('app-filter-select--multiple')
    expect(root.classes()).not.toContain('app-filter-select--has-selection')
    expect(select.attributes('data-placeholder')).toBe('事件类型')
    expect(select.attributes('data-aria-label')).toBe('事件类型')
  })

  it('显式可访问名称优先于占位文案', async () => {
    const wrapper = mountSelect([], {
      placeholder: '事件类型',
      ariaLabel: '按事件类型筛选',
    })
    await flushPromises()

    expect(wrapper.get('.el-select').attributes('data-aria-label')).toBe('按事件类型筛选')
  })
})
