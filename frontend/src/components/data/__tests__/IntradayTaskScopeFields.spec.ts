// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import IntradayTaskScopeFields from '@/components/data/IntradayTaskScopeFields.vue'
import { createIntradayIngestForm } from '@/utils/intradayIngest'

const Select = defineComponent({
  inheritAttrs: false,
  props: ['modelValue', 'options'],
  emits: ['update:modelValue'],
  template: '<button v-for="option in options" @click="$emit(\'update:modelValue\', option.value)">{{ option.label }}</button>',
})
describe('共享分时参数表单', () => {
  it('切换模式保留股票草稿，重采显示两个日期字段', async () => {
    const wrapper = mount(IntradayTaskScopeFields, {
      props: { modelValue: createIntradayIngestForm({ codes: ['600000.SH'] }), testIdPrefix: 'test' },
      global: {
        stubs: { PageSegmented: Select, TradeDatePicker: true, StockCodeMultiSelect: true, 'el-form-item': { template: '<div><slot /></div>' }, 'el-alert': true },
      },
    })
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(wrapper.emitted('update:modelValue')![0]![0]).toMatchObject({ mode: 'refetch', codes: ['600000.SH'], scope: 'selected' })
    await wrapper.setProps({ modelValue: { ...createIntradayIngestForm(), mode: 'refetch' } })
    expect(wrapper.findAllComponents({ name: 'TradeDatePicker' })).toHaveLength(2)
  })
})
