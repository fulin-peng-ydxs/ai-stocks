// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import StockCompareChart from '@/components/StockCompareChart.vue'
import { WORKSPACE_RESIZE_ACTIVE } from '@/layout/workspaceResizeContext'

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

class ResizeObserverMock {
  static instances: ResizeObserverMock[] = []
  observe = vi.fn()
  disconnect = vi.fn()

  constructor(private readonly callback: ResizeObserverCallback) {
    ResizeObserverMock.instances.push(this)
  }

  trigger(): void {
    this.callback([], this as unknown as ResizeObserver)
  }
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock)

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
    ResizeObserverMock.instances.length = 0
    document.documentElement.style.setProperty('--market-up-color', '#f04438')
    document.documentElement.style.setProperty('--market-down-color', '#0ea968')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 800 })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 440 })
  })

  it('父级分栏拖动期间合并走势尺寸刷新，结束后按最终宽度刷新一次', async () => {
    const resizing = ref(true)
    const wrapper = mount(StockCompareChart, {
      props: {
        activeCode: '000001.SZ',
        metric: 'cum',
        rangeDays: 1,
        series: [{ code: '000001.SZ', name: '平安银行', bars: bars('000001.SZ', [10, 11]) }],
      },
      global: {
        provide: { [WORKSPACE_RESIZE_ACTIVE as symbol]: resizing },
        stubs: { AppStateBlock: true },
      },
    })
    await nextTick()
    echartsMock.resize.mockClear()

    ResizeObserverMock.instances[0]?.trigger()
    ResizeObserverMock.instances[0]?.trigger()
    expect(echartsMock.resize).not.toHaveBeenCalled()

    resizing.value = false
    await nextTick()
    await nextTick()
    expect(echartsMock.resize).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('纯股票间对比时各序列从自身首个有效值起算，并强化当前观察序列', async () => {
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
      yAxis: Array<{ axisLabel: { formatter: string | ((value: number) => string) } }>
    }
    expect(option.series[0]?.data).toEqual([expect.closeTo(0, 10), expect.closeTo(10, 10)])
    expect(option.series[1]?.data).toEqual([expect.closeTo(0, 10), expect.closeTo(-5, 10)])
    expect(option.series[0]!.lineStyle.width).toBeGreaterThan(option.series[1]!.lineStyle.width)
    const concreteFormatter = option.yAxis[0]!.axisLabel.formatter
    expect(typeof concreteFormatter === 'function' ? concreteFormatter(0) : '').toBe('10.00')
    const percentFormatter = option.yAxis[1]!.axisLabel.formatter
    expect(typeof percentFormatter === 'function' ? percentFormatter(12.3456) : '').toBe('+12.35%')
    const content = option.tooltip.formatter([
      { axisValueLabel: '2026-08-07', dataIndex: 1, seriesIndex: 0, seriesName: '平安银行 · 000001.SZ', value: 10, marker: '' },
    ])
    expect(content).toContain('2026-08-07 · 累计涨跌')
    expect(content).not.toContain('前复权')
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
    expect(option.series[0].data).toEqual([expect.closeTo(0, 10), expect.closeTo(0, 10), expect.closeTo(20, 10)])
    expect(option.series[1].data).toEqual([expect.closeTo(0, 10), expect.closeTo(1, 10), expect.closeTo(10, 10)])
    expect(option.series[1].lineStyle.type).toBe('dashed')
    const content = option.tooltip.formatter([
      { axisValueLabel: dates[2], dataIndex: 2, seriesIndex: 0, seriesName: '平安银行 · 000001.SZ', value: 20, marker: '' },
    ])
    expect(content).toContain('color:#f04438">超额 +10.00 个百分点')
    wrapper.unmount()
  })

  it('纯股票间对比（不对比指数）时个别股票缺起始数据只留空，不否决整体', async () => {
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
      global: { stubs: { AppStateBlock: true } },
    })
    await nextTick()

    expect(wrapper.attributes('data-point-count')).toBe('2')
    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data: (number | null)[] }>
    }
    expect(option.series[0]?.data).toEqual([expect.closeTo(0, 10), expect.closeTo(0, 10)])     // 平安银行：有数据序列自首值为 0%
    expect(option.series[1]?.data).toEqual([null, expect.closeTo(0, 10)])  // 浦发银行：上市前留空，自首个有效值 0%
    wrapper.unmount()
  })
})
