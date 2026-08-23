// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
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

  it('把省略整数位的小数补为十进制字符串，不转为 number', async () => {
    const wrapper = mount(FixedDecimalInput, {
      props: { modelValue: null },
      global: { plugins: [ElementPlus] },
    })
    wrapper.findComponent({ name: 'ElInput' }).vm.$emit('update:modelValue', '.25')
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:modelValue')).toEqual([['0.25']])
  })
})
