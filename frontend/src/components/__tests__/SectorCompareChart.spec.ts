// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import SectorCompareChart from '@/components/SectorCompareChart.vue'
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

const bars = (closes: number[]) => closes.map((close, i) => ({
  trade_date: `2026-08-${String(6 + i).padStart(2, '0')}`,
  open: close, high: close, low: close, close,
  volume: 1, amount: 1,
}))

describe('SectorCompareChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ResizeObserverMock.instances.length = 0
    document.documentElement.style.setProperty('--market-up-color', '#f04438')
    document.documentElement.style.setProperty('--market-down-color', '#0ea968')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 800 })
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, value: 440 })
  })

  it('父级分栏拖动期间合并板块走势尺寸刷新，结束后按最终宽度刷新一次', async () => {
    const resizing = ref(true)
    const wrapper = mount(SectorCompareChart, {
      props: {
        metric: 'cum',
        rangeDays: 5,
        series: [{ code: '881175', name: '医疗服务', bars: bars([100, 101]) }],
      },
      global: { provide: { [WORKSPACE_RESIZE_ACTIVE as symbol]: resizing } },
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

  it('累计涨跌折线：悬浮提示带指标名并按正负值使用行情语义色，含基准超额', async () => {
    const wrapper = mount(SectorCompareChart, {
      props: {
        metric: 'cum',
        rangeDays: 5,
        series: [{
          code: '881175', name: '医疗服务',
          bars: bars([100, 100, 100, 100, 100, 105]),
        }],
        benchmark: {
          code: '000905.SH', name: '中证 500',
          bars: bars([100, 100, 100, 100, 100, 102]),
        },
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      tooltip: { formatter: (params: unknown[]) => string }
      dataZoom: Array<{ start: number; end: number }>
      yAxis: Array<{ axisLabel: { formatter: string | ((value: number) => string) } }>
    }
    const content = option.tooltip.formatter([
      { axisValueLabel: '2026-08-11', seriesName: '上涨板块', value: 5, dataIndex: 5, marker: '' },
      { axisValueLabel: '2026-08-11', seriesName: '下跌板块', value: -2, dataIndex: 5, marker: '' },
      { axisValueLabel: '2026-08-11', seriesName: '基准 · 中证 500', value: 2, dataIndex: 5, marker: '' },
    ])

    expect(content).toContain('2026-08-11 · 累计涨跌')
    expect(content).toContain('color:#f04438">+5.00%')
    expect(content).toContain('color:#0ea968">-2.00%')
    expect(content).toContain('超额 +3.00 个百分点')
    expect(content).toContain('超额 -4.00 个百分点')
    expect(content.match(/超额/g)).toHaveLength(2)
    const emptyContent = option.tooltip.formatter([
      { axisValueLabel: '2026-08-11', seriesName: '缺失板块', value: null, dataIndex: 5, marker: '' },
    ])
    expect(emptyContent).toContain('--')
    expect(emptyContent).not.toContain('+0.00%')
    expect(option.dataZoom).toEqual([
      expect.objectContaining({ start: 0, end: 100 }),
      expect.objectContaining({ start: 0, end: 100 }),
    ])
    const concreteFormatter = option.yAxis[0]!.axisLabel.formatter
    expect(typeof concreteFormatter === 'function' ? concreteFormatter(0) : '').toBe('100.00')
    const percentFormatter = option.yAxis[1]!.axisLabel.formatter
    expect(typeof percentFormatter === 'function' ? percentFormatter(12.3456) : '').toBe('+12.35%')
    expect(wrapper.attributes('data-point-count')).toBe('6')
    expect(wrapper.attributes('data-benchmark-code')).toBe('000905.SH')
    expect(wrapper.attributes('data-benchmark-point-count')).toBe('6')
    wrapper.unmount()
  })

  it('累计涨跌窗口=1（单日）降级为柱状：无 dataZoom、无基准', async () => {
    const wrapper = mount(SectorCompareChart, {
      props: {
        metric: 'cum',
        rangeDays: 1,
        series: [{ code: '881175', name: '医疗服务', bars: bars([100, 105]) }],
        crossSection: [{ name: '医疗服务', value: 5 }],
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ type: string }>
      dataZoom?: unknown[]
      yAxis: { axisLabel: {
        formatter: (value: number) => string
        color: (value: number) => string
      } }
    }
    expect(option.series.every((s) => s.type === 'bar')).toBe(true)
    expect(option.yAxis.axisLabel.formatter(12.3456)).toBe('+12.35%')
    expect(option.yAxis.axisLabel.color(5)).toBe('#f04438')
    expect(option.yAxis.axisLabel.color(-5)).toBe('#0ea968')
    expect(option.yAxis.axisLabel.color(0)).not.toBe(option.yAxis.axisLabel.color(5))
    expect(option.dataZoom).toBeUndefined()
    expect(wrapper.attributes('data-benchmark-code')).toBe('')
    expect(wrapper.attributes('data-benchmark-point-count')).toBe('0')
    wrapper.unmount()
  })

  it('净流入柱状：单柱按正负着色，无 dataZoom、无基准 series', async () => {
    const wrapper = mount(SectorCompareChart, {
      props: {
        metric: 'inflow',
        rangeDays: 60,
        series: [],
        crossSection: [
          { name: '医疗服务', value: 3.2 },
          { name: '半导体', value: -1.1 },
        ],
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ type: string }>
      dataZoom?: unknown[]
      xAxis: { data: string[] }
    }
    expect(option.series.every((s) => s.type === 'bar')).toBe(true)
    expect(option.series).toHaveLength(1)
    expect(option.dataZoom).toBeUndefined()
    expect(option.xAxis.data).toEqual(['医疗服务', '半导体'])
    expect(wrapper.attributes('data-benchmark-code')).toBe('')
    expect(wrapper.attributes('data-benchmark-point-count')).toBe('0')
    expect(wrapper.attributes('data-point-count')).toBe('2')
    wrapper.unmount()
  })

  it('涨跌家数柱状：双向柱（上涨正、下跌负），两条 bar series', async () => {
    mount(SectorCompareChart, {
      props: {
        metric: 'breadth',
        rangeDays: 60,
        series: [],
        crossSection: [
          { name: '医疗服务', value: 30, second: 12 },
          { name: '半导体', value: 8, second: 25 },
        ],
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ name: string; data: number[] }>
    }
    expect(option.series).toHaveLength(2)
    expect(option.series[0]!.data).toEqual([30, 8])
    expect(option.series[1]!.data).toEqual([-12, -25])
  })
})
