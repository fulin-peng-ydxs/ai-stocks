// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import CandleChart from '@/components/CandleChart.vue'
import type { Bar } from '@/api/stocks'
import { stockChartTheme } from '@/components/stock-chart/chartUtils'

const echartsMock = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  on: vi.fn(),
  init: vi.fn(),
}))

echartsMock.init.mockReturnValue({
  setOption: echartsMock.setOption,
  resize: echartsMock.resize,
  dispose: echartsMock.dispose,
  on: echartsMock.on,
})

vi.mock('echarts', () => ({ init: echartsMock.init }))

function makeBars(length: number): Bar[] {
  return Array.from({ length }, (_, index) => ({
    date: `2026-07-${String(index + 1).padStart(2, '0')}`,
    open: 10 + index,
    high: 11 + index,
    low: 9 + index,
    close: 10.5 + index,
    pre_close: 10 + index,
    volume: 100_000 + index,
    amount: 1_000_000,
    turnover_rate: 1,
  }))
}

describe('CandleChart shared helper regression', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.documentElement.style.setProperty('--el-color-warning', '#facc15')
    document.documentElement.style.setProperty('--el-color-danger', '#ef4d4d')
    document.documentElement.style.setProperty('--market-up-color', '#ef4d4d')
  })

  it('保持现有 props、双 grid、K线+量能系列和暖机均线行为', async () => {
    const wrapper = mount(CandleChart, {
      props: {
        bars: makeBars(10),
        warmupBars: makeBars(60),
        zoomStart: 5,
        zoomEnd: 95,
      },
    })
    await nextTick()

    const option = echartsMock.setOption.mock.calls.at(-1)?.[0] as {
      grid: unknown[]
      dataZoom: Array<{ start: number, end: number }>
      tooltip: {
        position: () => number[]
        formatter: (params: Array<{ dataIndex: number }>) => string
      }
      series: Array<{
        name: string
        data?: Array<number | null>
        lineStyle?: { color?: string }
      }>
    }
    expect(option.grid).toHaveLength(2)
    expect(option.dataZoom[0]).toMatchObject({ start: 5, end: 95 })
    expect(option.series.some((series) => series.name === 'K线')).toBe(true)
    expect(option.series.some((series) => series.name === '量')).toBe(true)
    expect(option.series.find((series) => series.name === 'MA60')?.data?.[0]).not.toBeNull()
    expect(option.series.find((series) => series.name === 'MA60')?.lineStyle?.color)
      .toBe('#facc15')
    expect(stockChartTheme(false).series.kline).toMatchObject({
      ma5: '#ef4d4d',
      ma60: '#facc15',
    })
    expect(option.tooltip.position()).toEqual([10, 6])
    expect(option.tooltip.formatter([{ dataIndex: 0 }]))
      .toContain('style="color:#ef4d4d">10.50</span>')

    wrapper.unmount()
    expect(echartsMock.dispose).toHaveBeenCalledTimes(1)
  })
})
