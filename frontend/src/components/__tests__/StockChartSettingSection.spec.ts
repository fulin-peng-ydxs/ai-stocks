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
        currentRatios: [0.5, 0.3, 0.2],
        testIdPrefix: 'chart-test',
      },
      global: { plugins: [ElementPlus] },
    })
  }

  it('编辑任一比例时平均分配剩余比例并实时保存', async () => {
    const wrapper = mountSection()
    const inputs = wrapper.findAllComponents({ name: 'ElInputNumber' })

    await inputs[0].vm.$emit('update:modelValue', 59)
    expect(inputs.map((input) => input.props('modelValue'))).toEqual([59, 21, 20])
    expect(wrapper.emitted('saveDefaultRatios')?.at(-1)).toEqual([[0.59, 0.21, 0.2]])

    await inputs[1].vm.$emit('update:modelValue', 30)
    expect(inputs.map((input) => input.props('modelValue'))).toEqual([35, 30, 35])
    expect(wrapper.emitted('saveDefaultRatios')?.at(-1)).toEqual([[0.35, 0.3, 0.35]])
    expect(wrapper.text()).toContain('合计 100%')
  })

  it('工作区存在时回显尺寸档案与安全约束后的配置基线', () => {
    const wrapper = mountSection()
    const inputs = wrapper.findAllComponents({ name: 'ElInputNumber' })

    expect(wrapper.text()).toContain('已配置高度比例')
    expect(inputs.map((input) => input.props('modelValue'))).toEqual([50, 30, 20])
  })

  it('使用页面当前比例时直接采用并保存', async () => {
    const wrapper = mountSection()

    const useCurrentButton = wrapper.get('[data-testid="chart-test-save-current-ratios"]')
    expect(useCurrentButton.classes()).toContain('el-button--primary')
    expect(useCurrentButton.classes()).toContain('is-plain')
    await useCurrentButton.trigger('click')
    const inputs = wrapper.findAllComponents({ name: 'ElInputNumber' })
    expect(inputs.map((input) => input.props('modelValue'))).toEqual([50, 30, 20])
    expect(wrapper.emitted('applyCurrentRatios')).toHaveLength(1)
    expect(wrapper.emitted('saveDefaultRatios')).toBeUndefined()
    expect(wrapper.find('[data-testid="chart-test-save-default-ratios"]').exists()).toBe(false)
  })

  it('两图组合把全部剩余比例分配给另一张图', async () => {
    const wrapper = mountSection()
    await wrapper.setProps({
      slot3: 'hidden',
      chartTypes: ['kline', 'volume'],
      defaultRatios: [0.75, 0.25],
      currentRatios: [0.7, 0.3],
    })
    const inputs = wrapper.findAllComponents({ name: 'ElInputNumber' })

    await inputs[0].vm.$emit('update:modelValue', 64)

    expect(inputs.map((input) => input.props('modelValue'))).toEqual([64, 36])
    expect(wrapper.emitted('saveDefaultRatios')?.at(-1)).toEqual([[0.64, 0.36]])
  })

  it('before 插槽内容固定在图表设置首位（图表一之前）', () => {
    const wrapper = mount(StockChartSettingSection, {
      props: {
        slot2: 'volume',
        slot3: 'macd',
        chartTypes: ['kline', 'volume', 'macd'],
        defaultRatios: [0.6, 0.2, 0.2],
        currentRatios: [0.5, 0.3, 0.2],
        testIdPrefix: 'chart-test',
      },
      slots: { before: '<div data-testid="before-slot-marker">复权模式</div>' },
      global: { plugins: [ElementPlus] },
    })

    const text = wrapper.text()
    expect(text.indexOf('复权模式')).toBeGreaterThanOrEqual(0)
    expect(text.indexOf('复权模式')).toBeLessThan(text.indexOf('图表一'))
  })

  it('只显示 K 线时固定为 100%，不提供无意义的比例采用入口', async () => {
    const wrapper = mountSection()

    await wrapper.setProps({
      slot2: 'hidden',
      slot3: 'hidden',
      chartTypes: ['kline'],
      defaultRatios: [1],
    })

    expect(wrapper.text()).toContain('K线 100%（单图无需配置）')
    expect(wrapper.find('[data-settings-fold-node]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chart-test-save-default-ratios"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chart-test-save-current-ratios"]').exists()).toBe(false)
  })

  it('没有真实图表工作区尺寸时禁用采用入口，避免假保存', async () => {
    const wrapper = mountSection()
    await wrapper.setProps({ canApplyCurrentRatios: false })

    const inputs = wrapper.findAllComponents({ name: 'ElInputNumber' })
    expect(wrapper.text()).toContain('默认高度比例')
    expect(inputs.map((input) => input.props('modelValue'))).toEqual([60, 20, 20])
    expect(wrapper.get('[data-testid="chart-test-save-current-ratios"]').attributes('disabled'))
      .toBeDefined()
  })

  it('采用比例保存期间展示 loading 并拒绝重复提交', async () => {
    const wrapper = mountSection()
    await wrapper.setProps({ savingCurrentRatios: true })

    const button = wrapper.get('[data-testid="chart-test-save-current-ratios"]')
    expect(button.classes()).toContain('is-loading')
    await button.trigger('click')
    expect(wrapper.emitted('applyCurrentRatios')).toBeUndefined()
  })

  it('页面当前比例与已保存配置一致时禁用采用并二次拒绝提交', async () => {
    const wrapper = mountSection()
    await wrapper.setProps({ currentRatiosChanged: false })

    const button = wrapper.get('[data-testid="chart-test-save-current-ratios"]')
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(wrapper.emitted('applyCurrentRatios')).toBeUndefined()
  })
})
