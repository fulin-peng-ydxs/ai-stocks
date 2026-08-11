// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import SectorCompareChart from '@/components/SectorCompareChart.vue'

const echartsMock = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  init: vi.fn(),
}))

echartsMock.init.mockReturnValue({
  setOption: echartsMock.setOption,
  resize: echartsMock.resize,
  dispose: echartsMock.dispose,
})

vi.mock('echarts', () => ({ init: echartsMock.init }))

describe('SectorCompareChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.documentElement.style.setProperty('--market-up-color', '#f04438')
    document.documentElement.style.setProperty('--market-down-color', '#0ea968')
  })

  it('悬浮提示明确区间涨跌，并按正负值使用行情语义色', async () => {
    const wrapper = mount(SectorCompareChart, {
      props: {
        series: [{
          code: '881175',
          name: '医疗服务',
          bars: [
            { trade_date: '2026-08-06', open: 100, high: 101, low: 99, close: 100, volume: 1, amount: 1 },
            { trade_date: '2026-08-07', open: 100, high: 106, low: 99, close: 105, volume: 1, amount: 1 },
          ],
        }],
        benchmark: {
          code: '000905.SH',
          name: '中证 500',
          bars: [
            { trade_date: '2026-08-06', open: 100, high: 101, low: 99, close: 100, volume: 1, amount: 1 },
            { trade_date: '2026-08-07', open: 100, high: 103, low: 99, close: 102, volume: 1, amount: 1 },
          ],
        },
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      tooltip: { formatter: (params: unknown[]) => string }
    }
    const content = option.tooltip.formatter([
      { axisValueLabel: '2026-08-07', seriesName: '上涨板块', value: 5, dataIndex: 1, marker: '' },
      { axisValueLabel: '2026-08-07', seriesName: '下跌板块', value: -2, dataIndex: 1, marker: '' },
      { axisValueLabel: '2026-08-07', seriesName: '基准 · 中证 500', value: 2, dataIndex: 1, marker: '' },
    ])

    expect(content).toContain('2026-08-07 · 区间涨跌')
    expect(content).toContain('color:#f04438">+5.00%')
    expect(content).toContain('color:#0ea968">-2.00%')
    expect(content).toContain('超额 +3.00%')
    expect(content).toContain('超额 -4.00%')
    expect(content.match(/超额/g)).toHaveLength(2)
    const zoom = (echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      dataZoom: Array<{ start: number; end: number }>
    }).dataZoom
    expect(zoom).toEqual([
      expect.objectContaining({ start: 0, end: 100 }),
      expect.objectContaining({ start: 0, end: 100 }),
    ])
    expect(wrapper.attributes('data-point-count')).toBe('2')
    expect(wrapper.attributes('data-benchmark-code')).toBe('000905.SH')
    expect(wrapper.attributes('data-benchmark-point-count')).toBe('2')
    wrapper.unmount()
  })
})
