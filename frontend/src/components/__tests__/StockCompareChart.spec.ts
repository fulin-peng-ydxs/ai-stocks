// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import StockCompareChart from '@/components/StockCompareChart.vue'

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

function bars(code: string, closes: number[]) {
  return closes.map((close, index) => ({
    date: `2026-08-0${6 + index}`,
    open: close,
    high: close,
    low: close,
    close,
    pre_close: index ? closes[index - 1]! : null,
    volume: 1,
    amount: 1,
    turnover_rate: 1,
    code,
  }))
}

function datedBars(code: string, dates: string[], closes: number[]) {
  return dates.map((date, index) => ({ ...bars(code, closes)[index]!, date }))
}

describe('StockCompareChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.documentElement.style.setProperty('--market-up-color', '#f04438')
    document.documentElement.style.setProperty('--market-down-color', '#0ea968')
  })

  it('按各股票首个有效收盘归一为100，并强化当前观察序列', async () => {
    const wrapper = mount(StockCompareChart, {
      props: {
        activeCode: '000001.SZ',
        series: [
          { code: '000001.SZ', name: '平安银行', bars: bars('000001.SZ', [10, 11]) },
          { code: '600000.SH', name: '浦发银行', bars: bars('600000.SH', [20, 19]) },
        ],
      },
      global: {
        stubs: {
          AppStateBlock: {
            props: ['title', 'description'],
            template: '<div>{{ title }} {{ description }}</div>',
          },
        },
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data: number[]; lineStyle: { width: number } }>
      tooltip: { formatter: (params: unknown[]) => string }
    }
    expect(option.series[0]?.data).toEqual([100, 110])
    expect(option.series[1]?.data).toEqual([100, 95])
    expect(option.series[0]!.lineStyle.width).toBeGreaterThan(option.series[1]!.lineStyle.width)
    const content = option.tooltip.formatter([
      { axisValueLabel: '2026-08-07', seriesIndex: 0, seriesName: '平安银行 · 000001.SZ', value: 110, marker: '' },
    ])
    expect(content).toContain('2026-08-07 · 起点 100')
    expect(content).toContain('前复权 11.00')
    expect(content).toContain('color:#f04438">110.00')
    expect(wrapper.attributes('data-point-count')).toBe('2')
    wrapper.unmount()
  })

  it('股票没有共同有效交易日时不生成不同起点的伪对比曲线', async () => {
    const wrapper = mount(StockCompareChart, {
      props: {
        activeCode: '000001.SZ',
        series: [
          { code: '000001.SZ', name: '平安银行', bars: datedBars('000001.SZ', ['2026-01-05'], [10]) },
          { code: '600000.SH', name: '浦发银行', bars: datedBars('600000.SH', ['2026-08-05'], [20]) },
        ],
      },
      global: {
        stubs: {
          AppStateBlock: {
            props: ['title', 'description'],
            template: '<div>{{ title }} {{ description }}</div>',
          },
        },
      },
    })
    await nextTick()

    expect(wrapper.text()).toContain('无共同交易区间')
    expect(wrapper.attributes('data-point-count')).toBe('0')
    expect(echartsMock.init).not.toHaveBeenCalled()
    expect(echartsMock.setOption).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
