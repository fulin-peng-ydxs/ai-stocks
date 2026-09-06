// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'

const ElSelectStub = defineComponent({
  name: 'ElSelect',
  props: {
    modelValue: { type: [Array, String], default: '' },
    multiple: { type: Boolean, default: false },
    clearable: { type: Boolean, default: false },
    filterable: { type: Boolean, default: false },
    collapseTags: { type: Boolean, default: false },
    collapseTagsTooltip: { type: Boolean, default: false },
    maxCollapseTags: { type: Number, default: 1 },
    placeholder: { type: String, default: '' },
    ariaLabel: { type: String, default: '' },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { slots }) {
    return () => h('div', {
      class: 'el-select',
      'data-multiple': String(props.multiple),
      'data-clearable': String(props.clearable),
      'data-filterable': String(props.filterable),
      'data-collapse-tags': String(props.collapseTags),
      'data-collapse-tags-tooltip': String(props.collapseTagsTooltip),
      'data-max-collapse-tags': String(props.maxCollapseTags),
      'data-placeholder': props.placeholder,
      'data-aria-label': props.ariaLabel,
    }, [
      h('div', { class: 'el-select__wrapper' }, [
        h('div', { class: 'el-select__selection' }, slots.default?.()),
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

const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
const originalScrollWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollWidth')
const originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
const originalScrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight')

afterEach(() => {
  vi.restoreAllMocks()
  const proto = HTMLElement.prototype as unknown as Record<string, unknown>
  if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, 'clientWidth', originalClientWidth)
  else delete proto.clientWidth
  if (originalScrollWidth) Object.defineProperty(HTMLElement.prototype, 'scrollWidth', originalScrollWidth)
  else delete proto.scrollWidth
  if (originalClientHeight) Object.defineProperty(HTMLElement.prototype, 'clientHeight', originalClientHeight)
  else delete proto.clientHeight
  if (originalScrollHeight) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', originalScrollHeight)
  else delete proto.scrollHeight
})

describe('AppFilterSelect', () => {
  it('默认按列表筛选下拉启用多选、搜索、清空和 3 个标签折叠阈值', async () => {
    const wrapper = mountSelect(['a', 'b', 'c'])
    await flushPromises()
    const select = wrapper.find('.el-select')
    expect(select.attributes('data-multiple')).toBe('true')
    expect(select.attributes('data-clearable')).toBe('true')
    expect(select.attributes('data-filterable')).toBe('true')
    expect(select.attributes('data-collapse-tags')).toBe('true')
    expect(select.attributes('data-collapse-tags-tooltip')).toBe('true')
    expect(select.attributes('data-max-collapse-tags')).toBe('3')
  })

  it('选择区溢出时降低标签折叠阈值', async () => {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get() {
        return 100
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollWidth', {
      configurable: true,
      get() {
        return this.classList.contains('el-select__selection') ? 160 : 100
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return 32
      },
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get() {
        return 32
      },
    })

    const wrapper = mountSelect(['a', 'b', 'c'])
    await flushPromises()
    await nextTick()
    await nextTick()

    expect(wrapper.find('.el-select').attributes('data-max-collapse-tags')).toBe('1')
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
