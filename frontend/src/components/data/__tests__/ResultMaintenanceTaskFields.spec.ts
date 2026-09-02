// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ResultMaintenanceTaskFields from '@/components/data/ResultMaintenanceTaskFields.vue'
import TradeDatePicker from '@/components/TradeDatePicker.vue'
import { createResultMaintenanceTaskForm } from '@/utils/resultMaintenanceTask'

describe('ResultMaintenanceTaskFields', () => {
  it('固定日期复用交易日选择器，避免选择周末和休市日', () => {
    const wrapper = mount(ResultMaintenanceTaskFields, {
      props: {
        taskType: 'stock_board_correlation',
        modelValue: createResultMaintenanceTaskForm({ target_mode: 'fixed' }),
      },
      global: {
        stubs: {
          'el-alert': true,
          'el-form-item': { template: '<div><slot /></div>' },
          PageSegmented: true,
          StockCodeMultiSelect: true,
          TradeDatePicker: true,
        },
      },
    })

    expect(wrapper.findComponent(TradeDatePicker).exists()).toBe(true)
    expect(wrapper.findComponent(TradeDatePicker).props('placeholder')).toBe('选择交易日')
  })
})
