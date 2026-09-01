// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StockIngestScopeFields from '@/components/data/StockIngestScopeFields.vue'
import { createStockIngestForm } from '@/utils/stockIngest'

describe('StockIngestScopeFields', () => {
  it('only shows force-current-day for daily updates', async () => {
    const wrapper = mount(StockIngestScopeFields, {
      props: {
        modelValue: createStockIngestForm(),
        testIdPrefix: 'stock-ingest',
      },
      global: {
        stubs: {
          'el-alert': true,
          'el-checkbox': { template: '<button><slot /></button>' },
          'el-form-item': { template: '<div><slot /></div>' },
          'el-input-number': true,
          'el-option': true,
          'el-select': true,
        },
      },
    })

    expect(wrapper.find('[data-testid="stock-ingest-force-current-day"]').exists()).toBe(true)

    await wrapper.setProps({
      modelValue: createStockIngestForm({ recipe: 'history_backfill' }),
    })
    expect(wrapper.find('[data-testid="stock-ingest-force-current-day"]').exists()).toBe(false)
  })
})
