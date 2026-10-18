// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { ElOption, ElSelect } from 'element-plus'
import StockIngestScopeFields from '@/components/data/StockIngestScopeFields.vue'
import { createStockIngestForm, STOCK_INGEST_RECIPE_OPTIONS } from '@/utils/stockIngest'

describe('StockIngestScopeFields', () => {
  it('采集方案保持短标签、完整说明与等宽下方浮层，切换后保留原有参数清理', async () => {
    const wrapper = mount(StockIngestScopeFields, {
      props: {
        modelValue: createStockIngestForm({ force_current_day: true }),
        testIdPrefix: 'stock-ingest',
      },
      global: {
        components: { ElSelect, ElOption },
        stubs: {
          'el-alert': true,
          'el-form-item': { template: '<div><slot /></div>' },
          'el-input-number': true,
          CurrentDayFallbackField: true,
          PageSegmented: true,
        },
      },
    })
    const select = wrapper.findComponent(ElSelect)
    expect(select.props()).toMatchObject({
      placement: 'bottom-start',
      fallbackPlacements: ['bottom-start', 'bottom-end'],
      fitInputWidth: true,
      popperClass: 'app-select-popper app-select-popper--fit stock-ingest-recipe-popper',
    })
    const options = wrapper.findAllComponents(ElOption)
    expect(options).toHaveLength(STOCK_INGEST_RECIPE_OPTIONS.length)
    STOCK_INGEST_RECIPE_OPTIONS.forEach((recipe, index) => {
      expect(options[index].props('label')).toBe(recipe.label)
      expect(options[index].text()).toContain(recipe.description)
    })

    select.vm.$emit('update:modelValue', 'history_backfill')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([
      createStockIngestForm({ recipe: 'history_backfill', force_current_day: false }),
    ])
    wrapper.unmount()
  })

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
