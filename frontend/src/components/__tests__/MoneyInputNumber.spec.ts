// @vitest-environment jsdom
import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { ElInputNumber } from 'element-plus'
import { describe, expect, it } from 'vitest'
import { formatMoneyInput, parseMoneyInput } from '@/utils/money'

describe('真实金额数字输入的显示与业务值', () => {
  it('手数切金额时同步可访问上下限，取消上限后移除旧值', async () => {
    const wrapper = mount(ElInputNumber, { props: { modelValue: 1, min: 1, max: 45 } })
    try {
      await wrapper.setProps({ modelValue: 12345.67, min: 0, max: 100000 })
      expect(wrapper.get('input').attributes()).toMatchObject({
        'aria-valuenow': '12345.67', 'aria-valuemin': '0', 'aria-valuemax': '100000',
      })
      await wrapper.setProps({ min: -Infinity, max: Infinity })
      expect(wrapper.get('input').attributes('aria-valuemin')).toBeUndefined()
      expect(wrapper.get('input').attributes('aria-valuemax')).toBeUndefined()
    } finally { wrapper.unmount() }
  })
  it('格式化录入后失焦保留最新金额，加减继续使用该金额', async () => {
    const value = ref(0)
    const wrapper = mount(defineComponent({
      components: { ElInputNumber },
      setup: () => ({ value, formatMoneyInput, parseMoneyInput }),
      template: '<ElInputNumber v-model="value" :min="0" :step="10000" :formatter="formatMoneyInput" :parser="parseMoneyInput" />',
    }), { attachTo: document.body })
    try {
      const input = wrapper.get('input')
      input.element.focus()
      input.element.value = '12345.67'
      await input.trigger('input')
      await nextTick()
      expect(value.value).toBe(12345.67)
      input.element.blur()
      await nextTick()
      expect(input.element.value).toBe('12,345.67')
      expect(value.value).toBe(12345.67)
      await input.trigger('keydown', { code: 'ArrowUp' })
      expect(value.value).toBe(22345.67)
      expect(input.element.value).toBe('22,345.67')
    } finally { wrapper.unmount() }
  })
})
