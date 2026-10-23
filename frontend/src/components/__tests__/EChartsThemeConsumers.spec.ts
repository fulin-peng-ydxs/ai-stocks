// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import EquityChart from '@/components/EquityChart.vue'
import GrowthChart from '@/components/GrowthChart.vue'
import { chartCssVariable } from '@/components/chartTheme'
import { setLayoutPreset, setPresetOverrides } from '@/layout/useLayoutPreset'

const echartsMock = vi.hoisted(() => ({
  instances: [] as Array<{
    setOption: ReturnType<typeof vi.fn>
    resize: ReturnType<typeof vi.fn>
    dispose: ReturnType<typeof vi.fn>
  }>,
  init: vi.fn((_element?: HTMLElement, _theme?: unknown, _options?: { renderer?: string }) => {
    const instance = {
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
    }
    echartsMock.instances.push(instance)
    return instance
  }),
}))

vi.mock('echarts', () => ({
  init: echartsMock.init,
}))

describe('普通 ECharts 主题消费者', () => {
  beforeEach(() => {
    setPresetOverrides({})
    setLayoutPreset('balanced')
    echartsMock.instances.length = 0
    echartsMock.init.mockClear()
  })

  it.each([
    {
      name: 'EquityChart',
      component: EquityChart,
      props: {
        points: [{
          trade_date: '2026-07-25',
          equity: 100_000,
          cash: 50_000,
          position_value: 50_000,
          n_positions: 1,
          drawdown: -0.02,
          benchmark_equity: 98_000,
        }],
        benchmarkCode: '000300.SH',
      },
    },
    {
      name: 'GrowthChart',
      component: GrowthChart,
      props: {
        data: [{
          id: 'growth-1',
          score: 80,
          total_return: 0.1,
          win_rate: 0.6,
          grade: 'A',
          completed_at: '2026-07-25T00:00:00Z',
        }],
      },
    },
  ])('$name 在当前预设同 key 覆盖后重新取色', async ({ component, props }) => {
    const wrapper = mount(component as never, { props: props as never })
    await nextTick()
    expect(echartsMock.init.mock.calls.at(-1)?.[2]).toMatchObject({ renderer: 'svg' })
    const chart = echartsMock.instances[0]
    const callsBefore = chart.setOption.mock.calls.length

    setPresetOverrides({
      balanced: {
        'tokens.light.surfaceBg': '#f2f5f8',
        'tokens.light.primary': '#2457d6',
        'tokens.light.warning': '#a35200',
        'tokens.light.marketUp': '#f75c50',
        'tokens.light.marketDown': '#20c970',
      },
    })
    await nextTick()
    await nextTick()

    expect(chart.setOption.mock.calls.length).toBeGreaterThan(callsBefore)
    const option = chart.setOption.mock.calls.at(-1)?.[0]
    expect(option.backgroundColor).toBe('#ffffff')
    expect(option.series[0].lineStyle.color).toBe('#2457d6')
    const directionalLabel = option.yAxis[1].axisLabel
    expect(directionalLabel.color(5)).toBe(chartCssVariable('--market-up-color', ''))
    expect(directionalLabel.color(-5)).toBe(chartCssVariable('--market-down-color', ''))
    expect(directionalLabel.color(0)).toBe(chartCssVariable('--el-text-color-secondary', ''))
    expect(typeof option.yAxis[0].axisLabel.color).toBe('string')
    const pointerLabel = option.yAxis[1].axisPointer.label
    expect(pointerLabel.formatter({ value: -5 })).toBe('{d|-5.00%}')
    expect(pointerLabel.rich.u.color).toBe(directionalLabel.color(5))
    expect(pointerLabel.rich.d.color).toBe(directionalLabel.color(-5))
    expect(pointerLabel.backgroundColor).toBe(option.backgroundColor)

    wrapper.unmount()
  })
})
