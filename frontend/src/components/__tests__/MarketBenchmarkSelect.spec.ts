// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MarketBenchmarkSelect from '@/components/MarketBenchmarkSelect.vue'
import AppFilterSelect from '@/components/AppFilterSelect.vue'
import { MARKET_BENCHMARK_OPTIONS } from '@/utils/marketBenchmarks'

describe('MarketBenchmarkSelect', () => {
  it('统一消费共享指数选项，并以单选模式完整透传当前回显值', async () => {
    const wrapper = mount(MarketBenchmarkSelect, {
      props: {
        modelValue: '000300.SH',
        width: '120px',
        testId: 'benchmark-select',
      },
      global: {
        stubs: {
          AppFilterSelect: {
            name: 'AppFilterSelect',
            props: ['modelValue', 'options', 'multiple', 'clearable', 'filterable'],
            template: '<div class="app-filter-select-stub">{{ modelValue }}</div>',
          },
        },
      },
    })

    const select = wrapper.getComponent(AppFilterSelect)
    expect(select.props('modelValue')).toBe('000300.SH')
    expect(select.props('options')).toEqual([
      { label: MARKET_BENCHMARK_OPTIONS[0]!.label, value: '__none__' },
      ...MARKET_BENCHMARK_OPTIONS.slice(1),
    ])
    expect(select.props('multiple')).toBe(false)
    expect(select.props('clearable')).toBe(false)
    expect(select.props('filterable')).toBe(false)
    expect(wrapper.get('[data-testid="benchmark-select"]').attributes('style')).toContain('width: 120px')

    select.vm.$emit('update:modelValue', '399006.SZ')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['399006.SZ']])
  })

  it('将空业务值映射为可回显选项，并在变更时还原为空业务值', async () => {
    const wrapper = mount(MarketBenchmarkSelect, {
      props: { modelValue: '' },
      global: {
        stubs: {
          AppFilterSelect: {
            name: 'AppFilterSelect',
            props: ['modelValue', 'options'],
            template: '<div class="app-filter-select-stub">{{ modelValue }}</div>',
          },
        },
      },
    })
    const select = wrapper.getComponent(AppFilterSelect)

    expect(select.props('modelValue')).toBe('__none__')
    select.vm.$emit('update:modelValue', '__none__')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['']])
  })
})
