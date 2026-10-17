// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import EquityChart from '@/components/EquityChart.vue'

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

const points = [
  { trade_date: '2026-07-24', equity: 100_000, cash: 50_000, position_value: 50_000, n_positions: 1, drawdown: 0, benchmark_equity: 100_000 },
  { trade_date: '2026-07-25', equity: 105_000, cash: 0, position_value: 105_000, n_positions: 1, drawdown: -0.05, benchmark_equity: 98_000 },
]

function lastOption() {
  return echartsMock.setOption.mock.calls.at(-1)?.[0] as {
    legend: { data: string[] }
    tooltip: { formatter: (params: unknown) => string }
    yAxis: Array<{ axisLabel: { formatter: (value: number) => string } }>
    series: Array<{ name: string; lineStyle: { type: string; color: string }; color: string; itemStyle: { color: string }; data: number[] }>
  }
}

function lastCallSecondArg() {
  return echartsMock.setOption.mock.calls.at(-1)?.[1] as { notMerge?: boolean } | undefined
}

describe('EquityChart 基准对比渲染', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('缺省：基准线保持实线、图例沿用 benchmarkCode、基准用灰色', async () => {
    const wrapper = mount(EquityChart, { props: { points, benchmarkCode: '000905.SH' } })
    await nextTick()
    const option = lastOption()
    expect(option.legend.data).toEqual(['组合净值', '基准(000905.SH)'])
    expect(option.series[1].lineStyle.type).toBe('solid')
    expect(option.series[1].color).toBe(option.series[1].lineStyle.color) // 圆点与线色一致
    // 基准用灰（t.label fallback），与板块行情基准一致，不用橙
    expect(option.series[1].lineStyle.color).toBe('#6e7078')
    wrapper.unmount()
  })

  it('传入 extraBenchmark：基准线变虚线、图例名用指数名、圆点与线色一致', async () => {
    const wrapper = mount(EquityChart, {
      props: {
        points,
        benchmarkCode: '000905.SH',
        extraBenchmark: { code: '000300.SH', name: '沪深 300', equity: [100_000, 101_000] },
      },
    })
    await nextTick()
    const option = lastOption()
    expect(option.legend.data).toEqual(['组合净值', '基准 · 沪深 300'])
    expect(option.series[1].lineStyle.type).toBe('dashed')
    expect(option.series[1].color).toBe(option.series[1].lineStyle.color) // 圆点与线色一致
    expect(option.series[1].data).toEqual([100_000, 101_000])
    wrapper.unmount()
  })

  it('extraBenchmark 切空：回退默认实线基准', async () => {
    const wrapper = mount(EquityChart, {
      props: {
        points,
        benchmarkCode: '000905.SH',
        extraBenchmark: { code: '000300.SH', name: '沪深 300', equity: [100_000, 101_000] },
      },
    })
    await nextTick()
    await wrapper.setProps({ extraBenchmark: null })
    await nextTick()
    const option = lastOption()
    expect(option.legend.data).toEqual(['组合净值', '基准(000905.SH)'])
    expect(option.series[1].lineStyle.type).toBe('solid')
    expect(option.series[1].data).toEqual([100_000, 98_000])
    wrapper.unmount()
  })

  it('showBenchmark=false：整条基准线隐藏（仅组合净值 + 回撤）、回撤用红色', async () => {
    const wrapper = mount(EquityChart, {
      props: { points, benchmarkCode: '000905.SH', extraBenchmark: null, showBenchmark: false },
    })
    await nextTick()
    const option = lastOption()
    expect(option.legend.data).toEqual(['组合净值'])
    expect(option.series.map((s) => s.name)).toEqual(['组合净值', '回撤'])
    // 回撤用 danger 红（--el-color-danger fallback），面积浅红，与基准灰/组合蓝区分
    expect(option.series[1].lineStyle.color).toBe('#f04438')
    expect(option.series[1].color).toBe(option.series[1].lineStyle.color) // 圆点与线色一致
    wrapper.unmount()
  })

  it('setOption 用 notMerge 整图重建：切「不对比」后基准 series 彻底移除不残留', async () => {
    const wrapper = mount(EquityChart, {
      props: {
        points,
        benchmarkCode: '000905.SH',
        extraBenchmark: { code: '000905.SH', name: '中证 500', equity: [100_000, 101_000] },
      },
    })
    await nextTick()
    // 对比态 → 不对比态：notMerge 置 true，避免默认合并模式残留基准 series
    await wrapper.setProps({ extraBenchmark: null, showBenchmark: false })
    await nextTick()
    expect(lastCallSecondArg()).toMatchObject({ notMerge: true })
    expect(lastOption().series.map((s) => s.name)).toEqual(['组合净值', '回撤'])
    wrapper.unmount()
  })

  it('悬浮 tooltip 显示组合/基准涨跌幅与组合超额', async () => {
    const wrapper = mount(EquityChart, {
      props: {
        points,
        benchmarkCode: '000905.SH',
        extraBenchmark: { code: '000905.SH', name: '中证 500', equity: [100_000, 101_000] },
      },
    })
    await nextTick()
    const option = lastOption()
    // 组合：100000→105000=+5.00%；基准：100000→101000=+1.00%；超额=+4.00%
    const html = option.tooltip.formatter([
      { seriesName: '组合净值', dataIndex: 1, marker: '●', axisValueLabel: '2026-07-25' },
      { seriesName: '基准 · 中证 500', dataIndex: 1, marker: '○', axisValueLabel: '2026-07-25' },
    ])
    expect(html).toContain('+5.00%')
    expect(html).toContain('+1.00%')
    expect(html).toContain('超额 +4.00%')
    expect(option.yAxis[1]!.axisLabel.formatter(12.3456)).toBe('+12.35%')
    wrapper.unmount()
  })

  it('不对比时悬浮 tooltip 不显示超额行', async () => {
    const wrapper = mount(EquityChart, {
      props: { points, benchmarkCode: '000905.SH', extraBenchmark: null, showBenchmark: false },
    })
    await nextTick()
    const option = lastOption()
    const html = option.tooltip.formatter([
      { seriesName: '组合净值', dataIndex: 1, marker: '●', axisValueLabel: '2026-07-25' },
    ])
    expect(html).not.toContain('超额')
    wrapper.unmount()
  })
})
