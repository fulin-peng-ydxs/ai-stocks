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
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 800 })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 440 })
  })

  it('按共同基期归零，并强化当前观察序列', async () => {
    const wrapper = mount(StockCompareChart, {
      props: {
        activeCode: '000001.SZ',
        metric: 'cum',
        rangeDays: 1,
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
    expect(option.series[0]?.data).toEqual([0, 10])
    expect(option.series[1]?.data).toEqual([0, -5])
    expect(option.series[0]!.lineStyle.width).toBeGreaterThan(option.series[1]!.lineStyle.width)
    const content = option.tooltip.formatter([
      { axisValueLabel: '2026-08-07', dataIndex: 1, seriesIndex: 0, seriesName: '平安银行 · 000001.SZ', value: 10, marker: '' },
    ])
    expect(content).toContain('2026-08-07 · 共同基期 0%')
    expect(content).toContain('前复权 11.00')
    expect(content).toContain('color:#f04438">+10.00%')
    expect(wrapper.attributes('data-point-count')).toBe('2')
    wrapper.unmount()
  })

  it('使用独立市场日历补齐停牌日，并展示指数及超额收益', async () => {
    const dates = ['2026-08-06', '2026-08-07', '2026-08-08']
    const wrapper = mount(StockCompareChart, {
      props: {
        activeCode: '000001.SZ',
        metric: 'cum',
        rangeDays: 2,
        series: [{
          code: '000001.SZ',
          name: '平安银行',
          bars: datedBars('000001.SZ', [dates[0]!, dates[2]!], [10, 12]),
        }],
        benchmark: {
          code: '000905.SH',
          name: '中证500',
          bars: datedBars('000905.SH', dates, [100, 101, 110]),
        },
        calendar: datedBars('000905.SH', dates, [100, 101, 110]),
      },
      global: { stubs: { AppStateBlock: true } },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as any
    expect(option.series[0].data).toEqual([0, 0, 20])
    expect(option.series[1].data).toEqual([0, 1, 10])
    expect(option.series[1].lineStyle.type).toBe('dashed')
    const content = option.tooltip.formatter([
      { axisValueLabel: dates[2], dataIndex: 2, seriesIndex: 0, seriesName: '平安银行 · 000001.SZ', value: 20, marker: '' },
    ])
    expect(content).toContain('超额 +10.00%')
    wrapper.unmount()
  })

  it('股票没有共同有效交易日时不生成不同起点的伪对比曲线', async () => {
    const wrapper = mount(StockCompareChart, {
      props: {
        activeCode: '000001.SZ',
        metric: 'cum',
        rangeDays: 60,
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
