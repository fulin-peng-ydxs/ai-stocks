// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import ElementPlus, { ElMessage } from 'element-plus'
import FixedDecimalInput from '@/views/trade-discipline/components/FixedDecimalInput.vue'

describe('FixedDecimalInput', () => {
  it('只回传 NUMERIC(20,2) 可无损承载的十进制字符串', async () => {
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: '999999999999999999.99' },
      global: { plugins: [ElementPlus] },
    })
    const input = wrapper.findComponent({ name: 'ElInput' })

    input.vm.$emit('update:modelValue', '9007199254740992.01')
    input.vm.$emit('update:modelValue', '9999999999999999999.99')
    input.vm.$emit('update:modelValue', '1.001')
    input.vm.$emit('update:modelValue', '')
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:modelValue')).toEqual([
      ['9007199254740992.01'],
      [null],
    ])
  })

  it('拒绝越界键入时不让输入框显示与模型不一致的值', async () => {
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: '12.34' },
      global: { plugins: [ElementPlus] },
    })
    const input = wrapper.get('input')
    await input.setValue('9999999999999999999.99')

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(input.element.value).toBe('12.34')
  })

  it('编辑过程保留尾小数点和尾零，超精度明确提示且不静默截断', async () => {
    const warning = vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: '1', grouped: true }, global: { plugins: [ElementPlus] },
    })
    const input = wrapper.findComponent({ name: 'ElInput' })
    input.vm.$emit('focus', new FocusEvent('focus'))
    input.vm.$emit('update:modelValue', '1.')
    input.vm.$emit('update:modelValue', '1.20')
    input.vm.$emit('update:modelValue', '1.201')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['1.'], ['1.20']])
    expect(warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('小数最多 2 位') }))
    warning.mockRestore()
  })

  it('把省略整数位的小数补为十进制字符串，不转为 number', async () => {
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: null },
      global: { plugins: [ElementPlus] },
    })
    wrapper.findComponent({ name: 'ElInput' }).vm.$emit('update:modelValue', '.25')
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:modelValue')).toEqual([['0.25']])
  })

  it('金额失焦显示千分位，聚焦编辑和回传时保持无分隔精确值', async () => {
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: '1000000000', grouped: true },
      global: { plugins: [ElementPlus] },
    })
    const input = wrapper.get('input')

    expect(input.element.value).toBe('1,000,000,000.00')
    wrapper.findComponent({ name: 'ElInput' }).vm.$emit('focus', new FocusEvent('focus'))
    await wrapper.vm.$nextTick()
    expect(input.element.value).toBe('1000000000')
    await input.setValue('2,500,000.25')

    expect(wrapper.emitted('update:modelValue')).toEqual([['2500000.25']])
  })

  it('未显式传禁用态时继承外层表单的只读状态', () => {
    const wrapper = mount(defineComponent({
      components: { FixedDecimalInput },
      template: '<el-form disabled><FixedDecimalInput model-value="100000.00" /></el-form>',
    }), {
      global: { plugins: [ElementPlus] },
    })

    expect((wrapper.get('input').element as HTMLInputElement).disabled).toBe(true)
  })

  it('显式禁用时在普通容器内保持只读', () => {
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: '100000.00', disabled: true },
      global: { plugins: [ElementPlus] },
    })

    expect((wrapper.get('input').element as HTMLInputElement).disabled).toBe(true)
  })
})
