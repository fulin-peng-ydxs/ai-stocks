// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockChartSettingSection from '@/components/StockChartSettingSection.vue'

describe('StockChartSettingSection', () => {
  function mountSection() {
    return mount(StockChartSettingSection, {
      props: {
        slot2: 'volume',
        slot3: 'macd',
        chartTypes: ['kline', 'volume', 'macd'],
        defaultRatios: [0.6, 0.2, 0.2],
        testIdPrefix: 'chart-test',
      },
      global: { plugins: [ElementPlus] },
    })
  }

  it('编辑的默认比例合计 100% 后才允许保存', async () => {
    const wrapper = mountSection()
    const inputs = wrapper.findAllComponents({ name: 'ElInputNumber' })

    await inputs[0].vm.$emit('update:modelValue', 50)
    expect(wrapper.get('[data-testid="chart-test-save-default-ratios"]').attributes('disabled'))
      .toBeDefined()
    await inputs[1].vm.$emit('update:modelValue', 30)
    expect(wrapper.get('[data-testid="chart-test-save-default-ratios"]').attributes('disabled'))
      .toBeUndefined()

    await wrapper.get('[data-testid="chart-test-save-default-ratios"]').trigger('click')
    expect(wrapper.emitted('saveDefaultRatios')?.at(-1)).toEqual([[0.5, 0.3, 0.2]])
  })

  it('将当前会话比例设为默认时发出独立显式事件', async () => {
    const wrapper = mountSection()

    await wrapper.get('[data-testid="chart-test-save-current-ratios"]').trigger('click')

    expect(wrapper.emitted('saveCurrentAsDefault')).toEqual([[]])
  })

  it('before 插槽内容固定在图表设置首位（图表一之前）', () => {
    const wrapper = mount(StockChartSettingSection, {
      props: {
        slot2: 'volume',
        slot3: 'macd',
        chartTypes: ['kline', 'volume', 'macd'],
        defaultRatios: [0.6, 0.2, 0.2],
        testIdPrefix: 'chart-test',
      },
      slots: { before: '<div data-testid="before-slot-marker">复权模式</div>' },
      global: { plugins: [ElementPlus] },
    })

    const text = wrapper.text()
    expect(text.indexOf('复权模式')).toBeGreaterThanOrEqual(0)
    expect(text.indexOf('复权模式')).toBeLessThan(text.indexOf('图表一'))
  })

  it('只显示 K 线时固定为 100%，不提供无意义的比例保存入口', async () => {
    const wrapper = mountSection()

    await wrapper.setProps({
      slot2: 'hidden',
      slot3: 'hidden',
      chartTypes: ['kline'],
      defaultRatios: [1],
    })

    expect(wrapper.text()).toContain('K线 100%（单图无需配置）')
    expect(wrapper.find('[data-testid="chart-test-save-default-ratios"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chart-test-save-current-ratios"]').exists()).toBe(false)
  })
})
