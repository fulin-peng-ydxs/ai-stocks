// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { ElOption, ElSelect } from 'element-plus'
import AppSelect from '@/components/AppSelect.vue'

function mountSelect(attrs: Record<string, unknown> = {}, props = {}) {
  return mount(AppSelect, {
    props,
    attrs,
    slots: { default: () => h(ElOption, { label: '选项', value: 0 }) },
    global: { components: { ElSelect } },
  })
}

describe('AppSelect', () => {
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
