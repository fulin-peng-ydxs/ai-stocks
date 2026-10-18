// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { ElOption, ElSelect } from 'element-plus'
import MarketBenchmarkSelect from '@/components/MarketBenchmarkSelect.vue'
import { MARKET_BENCHMARK_OPTIONS } from '@/utils/marketBenchmarks'

describe('MarketBenchmarkSelect', () => {
  it('统一消费共享指数选项，并以单选模式完整透传当前回显值', async () => {
    const wrapper = mount(MarketBenchmarkSelect, {
      props: {
        modelValue: '000300.SH',
        testId: 'benchmark-select',
      },
      global: {
        components: { ElSelect, ElOption },
      },
    })

    const select = wrapper.getComponent(ElSelect)
    expect(select.props('modelValue')).toBe('000300.SH')
    expect(wrapper.findAllComponents(ElOption).map((option) => ({
      label: option.props('label'), value: option.props('value'),
    }))).toEqual([
      { label: MARKET_BENCHMARK_OPTIONS[0]!.label, value: '__none__' },
      ...MARKET_BENCHMARK_OPTIONS.slice(1),
    ])
    expect(select.props('multiple')).toBe(false)
    expect(select.props('clearable')).toBe(false)
    expect(select.props('filterable')).toBe(false)
    expect(select.props('fitInputWidth')).toBe(false)
    expect(select.props('placement')).toBe('bottom-start')
    expect(select.props('fallbackPlacements')).toEqual(['bottom-start', 'bottom-end'])
    expect(wrapper.get('[data-testid="benchmark-select"]').classes()).toContain('app-control-width-short')

    select.vm.$emit('update:modelValue', '399006.SZ')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['399006.SZ']])
    wrapper.unmount()
  })

  it('将空业务值映射为可回显选项，并在变更时还原为空业务值', async () => {
    const wrapper = mount(MarketBenchmarkSelect, {
      props: { modelValue: '' },
      global: {
        components: { ElSelect, ElOption },
      },
    })
    const select = wrapper.getComponent(ElSelect)

    expect(select.props('modelValue')).toBe('__none__')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.el-select__placeholder').text()).toBe('不对比指数')
    select.vm.$emit('update:modelValue', '__none__')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([['']])
    wrapper.unmount()
  })
})
