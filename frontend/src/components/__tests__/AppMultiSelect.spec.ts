// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { ElOption, ElSelect } from 'element-plus'
import AppMultiSelect, { type AppMultiSelectOption } from '@/components/AppMultiSelect.vue'

const Select = defineComponent({
  props: ['modelValue', 'remoteMethod', 'loading', 'allowCreate', 'disabled'],
  emits: ['update:modelValue', 'change'],
  setup: (_, { slots }) => () => h('div', { class: 'control' }, slots.default?.()),
})
const Option = defineComponent({
  props: ['value', 'label'],
  setup: props => () => h('span', { 'data-value': props.value }, props.label),
})
const options = [{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Beta' }]
function create(props: Record<string, unknown> = {}) {
  return mount(AppMultiSelect, {
    props: { modelValue: [], options, ...props },
    global: { stubs: { ElSelect: Select, ElOption: Option } },
  })
}
function paste(wrapper: ReturnType<typeof create>, text: string) {
  const event = new Event('paste', { cancelable: true, bubbles: true })
  Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } })
  wrapper.get('.control').element.dispatchEvent(event)
  return event
}
function deferred() {
  let resolve!: (value: AppMultiSelectOption[]) => void
  const promise = new Promise<AppMultiSelectOption[]>(r => { resolve = r })
  return { promise, resolve }
}

describe('AppMultiSelect', () => {
  it('本地候选批量粘贴去空去重、保持顺序，不默认改变大小写', async () => {
    const wrapper = create()
    paste(wrapper, 'b，a,b,A')
    await flushPromises()
    expect(wrapper.emitted('change')).toEqual([[['b', 'a']]])
    expect(wrapper.get('[role="alert"]').text()).toContain('A')
  })

  it('只有显式允许创建时才接收自定义值，更新与 change 各触发一次', async () => {
    const wrapper = create({ allowCreate: true })
    const control = wrapper.findComponent(Select)
    control.vm.$emit('update:modelValue', ['a', '新分类', '新分类'])
    control.vm.$emit('change', ['a', '新分类', '新分类'])
    expect(wrapper.emitted('update:modelValue')).toEqual([[['a', '新分类']]])
    expect(wrapper.emitted('change')).toEqual([[['a', '新分类']]])
    paste(wrapper, '新分类,另一分类')
    await flushPromises()
    expect(wrapper.emitted('change')?.[1]).toEqual([['新分类', '另一分类']])
  })

  it('自定义规范化和异步校验只加入有效请求项，保留粘贴顺序', async () => {
    const resolveValues = vi.fn().mockResolvedValue([
      { value: 'B', label: '乙' }, { value: 'A', label: '甲' }, { value: 'OTHER', label: '夹带项' },
    ])
    const wrapper = create({ normalizeValue: (v: string) => v.trim().toUpperCase(), resolveValues })
    paste(wrapper, ' a,B,a,BAD')
    await flushPromises()
    expect(resolveValues).toHaveBeenCalledTimes(1)
    expect(resolveValues).toHaveBeenCalledWith(['A', 'B', 'BAD'])
    expect(wrapper.emitted('change')).toEqual([[['A', 'B']]])
    expect(wrapper.text()).not.toContain('夹带项')
    expect(wrapper.get('[role="alert"]').text()).toContain('BAD')
    await wrapper.findComponent(Select).props('remoteMethod')('')
    expect(wrapper.get('[role="alert"]').text()).toContain('BAD')
  })

  it('只粘贴已有选择无需再次核验，单个普通文本保留原生输入行为', async () => {
    const resolveValues = vi.fn().mockResolvedValue([])
    const wrapper = create({ modelValue: ['a'], resolveValues })
    expect(paste(wrapper, 'Alpha').defaultPrevented).toBe(false)
    expect(paste(wrapper, 'Large Cap').defaultPrevented).toBe(false)
    paste(wrapper, 'a,a')
    await flushPromises()
    expect(wrapper.emitted('change')).toBeUndefined()
    expect(resolveValues).not.toHaveBeenCalled()
  })

  it('接口校验失败保留已选值和名称，停止加载并允许重试', async () => {
    const resolveValues = vi.fn().mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce([{ value: 'b', label: 'Beta' }])
    const wrapper = create({ modelValue: ['a'], resolveValues })
    paste(wrapper, 'b,b')
    await flushPromises()
    expect(wrapper.emitted('change')).toBeUndefined()
    expect(wrapper.text()).toContain('Alpha')
    expect(wrapper.findComponent(Select).props('loading')).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('校验失败')
    paste(wrapper, 'b,b')
    await flushPromises()
    expect(wrapper.emitted('change')).toEqual([[['a', 'b']]])
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it.each(['clear', 'selection', 'context', 'disabled', 'unmount', 'newPaste'])(
    '在 %s 后忽略过期批量校验响应', async action => {
      const pending = deferred()
      const wrapper = create({ modelValue: ['a'], resolveValues: () => pending.promise })
      paste(wrapper, 'b,b')
      await wrapper.vm.$nextTick()
      expect(wrapper.findComponent(Select).props('loading')).toBe(true)
      if (action === 'clear') await wrapper.setProps({ modelValue: [] })
      if (action === 'selection') wrapper.findComponent(Select).vm.$emit('update:modelValue', [])
      if (action === 'context') await wrapper.setProps({ contextKey: 'other' })
      if (action === 'disabled') await wrapper.setProps({ disabled: true })
      if (action === 'unmount') wrapper.unmount()
      if (action === 'newPaste') {
        await wrapper.setProps({ resolveValues: async () => [] })
        paste(wrapper, 'unknown,other')
      }
      pending.resolve([{ value: 'b', label: 'Beta' }])
      await flushPromises()
      expect(wrapper.emitted('change') ?? []).toEqual(action === 'selection' ? [[[]]] : [])
    },
  )

  it('快速搜索只显示最后响应，并在失败时保留已选名称和本地候选', async () => {
    const first = deferred()
    const second = deferred()
    const loadOptions = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
      .mockRejectedValueOnce(new Error('network'))
    const wrapper = create({ modelValue: ['a'], loadOptions })
    const search = wrapper.findComponent(Select).props('remoteMethod')
    const p1 = search('old')
    const p2 = search('Beta')
    second.resolve([{ value: 'new', label: 'Latest' }])
    await p2
    first.resolve([{ value: 'old', label: 'Stale' }])
    await p1
    expect(wrapper.text()).toContain('Latest')
    expect(wrapper.text()).not.toContain('Stale')
    await search('Beta')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Alpha')
    expect(wrapper.text()).toContain('Beta')
    expect(wrapper.get('[role="alert"]').text()).toContain('候选加载失败')
  })

  it('业务上下文变化使旧搜索响应失效', async () => {
    const pending = deferred()
    const wrapper = create({ loadOptions: () => pending.promise })
    const search = wrapper.findComponent(Select).props('remoteMethod')('old')
    await wrapper.setProps({ contextKey: 'new' })
    pending.resolve([{ value: 'old', label: 'Stale' }])
    await search
    expect(wrapper.text()).not.toContain('Stale')
    expect(wrapper.findComponent(Select).props('loading')).toBe(false)
  })

  it('禁用控件不触发粘贴校验或选值变化', async () => {
    const resolveValues = vi.fn()
    const wrapper = create({ disabled: true, resolveValues })
    paste(wrapper, 'a,b')
    wrapper.findComponent(Select).vm.$emit('update:modelValue', ['a'])
    await flushPromises()
    expect(resolveValues).not.toHaveBeenCalled()
    expect(wrapper.emitted('change')).toBeUndefined()
  })

  it('真实选择器输入搜索词不生成候选，选择现有项时只提交一次', async () => {
    const wrapper = mount(AppMultiSelect, {
      props: { modelValue: [], options },
      attrs: { defaultFirstOption: true },
      global: { components: { ElSelect, ElOption } },
    })
    await wrapper.get('.el-select__wrapper').trigger('click')
    await wrapper.get('input').setValue('Unknown')
    await wrapper.get('input').trigger('keydown', { key: 'Enter', code: 'Enter' })
    await flushPromises()
    expect(wrapper.emitted('change')).toBeUndefined()
    expect(wrapper.findAllComponents(ElOption)).toHaveLength(2)
    await wrapper.get('input').setValue('Alpha')
    await flushPromises()
    await wrapper.findAllComponents(ElOption)[0]!.trigger('click')
    expect(wrapper.emitted('change')).toEqual([[['a']]])
    wrapper.unmount()
  })

  it('真实选择器显式允许创建时仍可确认新增分类', async () => {
    const wrapper = mount(AppMultiSelect, {
      props: { modelValue: [], options, allowCreate: true },
      attrs: { defaultFirstOption: true },
      global: { components: { ElSelect, ElOption } },
    })
    await wrapper.get('.el-select__wrapper').trigger('click')
    await wrapper.get('input').setValue('新分类')
    await flushPromises()
    const created = wrapper.findAllComponents(ElOption).find(option => option.props('value') === '新分类')
    expect(created).toBeDefined()
    await created!.trigger('click')
    expect(wrapper.emitted('change')).toEqual([[['新分类']]])
    wrapper.unmount()
  })


  it('允许配置空白分隔，默认按完整名称处理内部空格', async () => {
    const names = create({ options: [{ value: 'Large Cap', label: '大盘' }], allowCreate: true })
    expect(paste(names, 'Large Cap').defaultPrevented).toBe(false)
    paste(names, 'Large Cap,New Category')
    await flushPromises()
    expect(names.emitted('change')).toEqual([[['Large Cap', 'New Category']]])
    const codes = create({ pasteSeparator: /[,，\s]+/ })
    paste(codes, 'a b a')
    await flushPromises()
    expect(codes.emitted('change')).toEqual([[['a', 'b']]])
  })

})
