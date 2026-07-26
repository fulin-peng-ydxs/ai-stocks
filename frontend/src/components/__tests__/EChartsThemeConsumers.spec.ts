// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import EquityChart from '@/components/EquityChart.vue'
import GrowthChart from '@/components/GrowthChart.vue'
import { setLayoutPreset, setPresetOverrides } from '@/layout/useLayoutPreset'

const echartsMock = vi.hoisted(() => ({
  instances: [] as Array<{
    setOption: ReturnType<typeof vi.fn>
    resize: ReturnType<typeof vi.fn>
    dispose: ReturnType<typeof vi.fn>
  }>,
  init: vi.fn(() => {
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
    const chart = echartsMock.instances[0]
    const callsBefore = chart.setOption.mock.calls.length

    setPresetOverrides({
      balanced: {
        'tokens.light.surfaceBg': '#f2f5f8',
        'tokens.light.primary': '#2457d6',
        'tokens.light.warning': '#a35200',
      },
    })
    await nextTick()
    await nextTick()

    expect(chart.setOption.mock.calls.length).toBeGreaterThan(callsBefore)
    const option = chart.setOption.mock.calls.at(-1)?.[0]
    expect(option.backgroundColor).toBe('#ffffff')
    expect(option.series[0].lineStyle.color).toBe('#2457d6')

    wrapper.unmount()
  })
})
