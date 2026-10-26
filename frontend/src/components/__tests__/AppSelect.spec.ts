// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { ElOption, ElSelect } from 'element-plus'
import AppSelect from '@/components/AppSelect.vue'

function mountSelect(
  attrs: Record<string, unknown> = {},
  props = {},
  options: { label: string; value: string | number }[] = [{ label: '选项', value: 0 }],
) {
  return mount(AppSelect, {
    props,
    attrs,
    slots: { default: () => options.map(option => h(ElOption, { ...option, key: option.value })) },
    global: { components: { ElSelect } },
  })
}

describe('AppSelect', () => {
  const pages = [
    { label: '连板天梯', value: 'ladder' },
    { label: '个股研究', value: 'stocks' },
  ]

  it('单行摘要切换只改变共享呈现，不清空多选值或把内部属性泄漏给库组件', async () => {
    const update = vi.fn()
    const wrapper = mountSelect({ multiple: true, modelValue: ['ladder', 'stocks'], 'onUpdate:modelValue': update, size: 'small' }, { singleLine: true }, pages)
    expect(wrapper.classes()).toContain('app-select--single-line')
    expect(wrapper.findComponent(ElSelect).props('modelValue')).toEqual(['ladder', 'stocks'])
    expect(wrapper.attributes('single-line')).toBeUndefined()
    await wrapper.setProps({ singleLine: false })
    expect(wrapper.classes()).not.toContain('app-select--single-line')
    expect(wrapper.findComponent(ElSelect).props('modelValue')).toEqual(['ladder', 'stocks'])
    expect(update).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('默认可输入过滤，无匹配或清空搜索不改业务值，确认候选才提交一次', async () => {
    const update = vi.fn()
    const change = vi.fn()
    const wrapper = mountSelect({
      modelValue: 'ladder', 'onUpdate:modelValue': update, onChange: change,
    }, {}, pages)
    const input = wrapper.get('input')
    expect(input.attributes('readonly')).toBeUndefined()
    await wrapper.get('.el-select__wrapper').trigger('click')
    await input.setValue('个股')
    await flushPromises()
    const options = wrapper.findAllComponents(ElOption)
    expect(options[0]!.attributes('style')).toContain('display: none')
    expect(options[1]!.attributes('style') ?? '').not.toContain('display: none')
    expect(update).not.toHaveBeenCalled()
    expect(change).not.toHaveBeenCalled()

    await input.setValue('无此页面')
    await flushPromises()
    expect(options.every(option => option.attributes('style')?.includes('display: none'))).toBe(true)
    expect(update).not.toHaveBeenCalled()
    await input.setValue('')
    await flushPromises()
    expect(options.every(option => !option.attributes('style')?.includes('display: none'))).toBe(true)
    await input.setValue('个股')
    await flushPromises()
    await options[1]!.trigger('click')
    expect(update).toHaveBeenCalledTimes(1)
    expect(update).toHaveBeenCalledWith('stocks')
    expect(change).toHaveBeenCalledTimes(1)
    expect(change).toHaveBeenCalledWith('stocks')
    wrapper.unmount()
  })

  it('未确认搜索结果就关闭时清除关键词，并保留原选中值', async () => {
    const update = vi.fn()
    const wrapper = mountSelect({
      modelValue: 'ladder', 'onUpdate:modelValue': update,
    }, {}, pages)
    await wrapper.get('.el-select__wrapper').trigger('click')
    await wrapper.get('input').setValue('个股')
    await flushPromises()
    wrapper.vm.blur()
    await flushPromises()
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('')
    expect(wrapper.get('.el-select__placeholder').text()).toBe('连板天梯')
    expect(update).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('允许短枚举显式关闭搜索，并响应调用方后续切换', async () => {
    const wrapper = mountSelect({}, { filterable: false })
    expect(wrapper.get('input').attributes('readonly')).toBeDefined()
    await wrapper.setProps({ filterable: true })
    expect(wrapper.get('input').attributes('readonly')).toBeUndefined()
    wrapper.unmount()
  })

  it('多选搜索后确认候选仍保留之前的选择', async () => {
    const update = vi.fn()
    const wrapper = mountSelect({
      modelValue: ['ladder'], multiple: true, 'onUpdate:modelValue': update,
    }, {}, pages)
    await wrapper.get('.el-select__wrapper').trigger('click')
    await wrapper.get('input').setValue('个股')
    await flushPromises()
    expect(update).not.toHaveBeenCalled()
    await wrapper.findAllComponents(ElOption)[1]!.trigger('click')
    expect(update).toHaveBeenCalledTimes(1)
    expect(update).toHaveBeenCalledWith(['ladder', 'stocks'])
    wrapper.unmount()
  })

  it('远程输入交给调用方查询，不再按本地标签二次过滤', async () => {
    const remoteMethod = vi.fn()
    const update = vi.fn()
    const wrapper = mountSelect({
      remote: true, remoteMethod, debounce: 0, 'onUpdate:modelValue': update,
    }, {}, [{ label: '平安银行', value: '000001.SZ' }])
    await wrapper.get('.el-select__wrapper').trigger('click')
    await flushPromises()
    remoteMethod.mockClear()
    await wrapper.get('input').setValue('000001')
    await flushPromises()
    expect(remoteMethod).toHaveBeenCalledTimes(1)
    expect(remoteMethod).toHaveBeenCalledWith('000001')
    expect(wrapper.getComponent(ElOption).attributes('style') ?? '').not.toContain('display: none')
    expect(update).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('集中提供下方定位、内容扩展和语义容量，并保留消费方属性与浮层边界', () => {
    const wrapper = mountSelect({ disabled: true, 'aria-label': '业务选择', 'data-testid': 'select' }, {
      width: 'short' as const, popperClass: 'business-popper',
    })
    const native = wrapper.getComponent(ElSelect)
    expect(native.props()).toMatchObject({
      placement: 'bottom-start', fallbackPlacements: ['bottom-start', 'bottom-end'],
      fitInputWidth: false, popperClass: 'app-select-popper business-popper', disabled: true,
    })
    expect(wrapper.get('[data-testid="select"]').classes()).toContain('app-control-width-short')
    expect(native.props('ariaLabel')).toBe('业务选择')
    expect(wrapper.getComponent(ElOption).props('value')).toBe(0)
    wrapper.unmount()
  })

  it.each([0, false, '', ['a', 'b'], { id: 1 }].map((value) => [value]))('不转换业务值 %j，变更与清空事件只透传一次', (value) => {
    const update = vi.fn()
    const change = vi.fn()
    const clear = vi.fn()
    const wrapper = mountSelect({
      modelValue: value, 'onUpdate:modelValue': update, onChange: change, onClear: clear,
    })
    const native = wrapper.getComponent(ElSelect)
    expect(native.props('modelValue')).toEqual(value)
    native.vm.$emit('update:modelValue', value)
    native.vm.$emit('change', value)
    native.vm.$emit('clear')
    expect(update).toHaveBeenCalledTimes(1)
    expect(update).toHaveBeenCalledWith(value)
    expect(change).toHaveBeenCalledTimes(1)
    expect(change).toHaveBeenCalledWith(value)
    expect(clear).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('等宽例外显式声明，保留私有边界和特殊定位覆盖', () => {
    const wrapper = mountSelect({}, {
      fitInputWidth: true, popperClass: 'recipe-popper',
      placement: 'bottom-end' as const, fallbackPlacements: ['bottom-end' as const],
    })
    expect(wrapper.getComponent(ElSelect).props()).toMatchObject({
      fitInputWidth: true, popperClass: 'app-select-popper app-select-popper--fit recipe-popper',
      placement: 'bottom-end', fallbackPlacements: ['bottom-end'],
    })
    wrapper.unmount()
  })

  it('透传具名插槽的作用域，并保留 ref 的 focus/blur 调用', () => {
    const focus = vi.fn()
    const blur = vi.fn()
    const native = defineComponent({
      setup(_, { slots, expose }) {
        expose({ focus, blur })
        return () => h('div', [
          slots.default?.(), slots.label?.({ label: '指数', value: '000300.SH' }),
          slots.tag?.({ selected: ['a'] }), slots.header?.(), slots.footer?.(), slots.empty?.(),
        ])
      },
    })
    const wrapper = mount(AppSelect, {
      slots: {
        default: '<span>候选项</span>',
        label: ({ label, value }) => h('span', `${label}:${value}`),
        tag: ({ selected }) => h('span', selected.join(',')),
        header: '<span>分组说明</span>', footer: '<span>底部操作</span>', empty: '<span>无候选项</span>',
      },
      global: { stubs: { ElSelect: native } },
    })
    for (const text of ['候选项', '指数:000300.SH', 'a', '分组说明', '底部操作', '无候选项']) {
      expect(wrapper.text()).toContain(text)
    }
    wrapper.vm.focus()
    wrapper.vm.blur()
    expect(focus).toHaveBeenCalledTimes(1)
    expect(blur).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
