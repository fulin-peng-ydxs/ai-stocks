// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import ElementPlus from 'element-plus'

describe('数字输入可访问状态', () => {
  it('键入并离焦后，显示值与绑定值一致', async () => {
    const value = ref(3)
    const wrapper = mount(defineComponent({
      setup: () => ({ value }),
      template: '<el-input-number v-model="value" :precision="0" :controls="false" />',
    }), { global: { plugins: [ElementPlus] } })
    const input = wrapper.get('input')
    await input.setValue('2')
    await input.trigger('blur')
    expect(value.value).toBe(2)
    expect((input.element as HTMLInputElement).value).toBe('2')
    wrapper.unmount()
  })
  it('只读与编辑切换时，原生禁用状态和ARIA始终一致', async () => {
    const wrapper = mount(defineComponent({
      props: { disabled: Boolean },
      template: '<el-form :disabled="disabled"><el-input-number :model-value="2" :controls="false" /></el-form>',
    }), { props: { disabled: true }, global: { plugins: [ElementPlus] } })
    const input = wrapper.get('input')
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.attributes('aria-disabled')).toBe('true')
    await wrapper.setProps({ disabled: false })
    expect(input.attributes('disabled')).toBeUndefined()
    expect(input.attributes('aria-disabled')).toBe('false')
    await wrapper.setProps({ disabled: true })
    expect(input.attributes('disabled')).toBeDefined()
    expect(input.attributes('aria-disabled')).toBe('true')
    wrapper.unmount()
  })
})
