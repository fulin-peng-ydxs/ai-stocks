// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import CandleChart from '@/components/CandleChart.vue'
import type { Bar } from '@/api/stocks'
import {
  stockChartTheme,
  trainingChartSeriesPalette,
} from '@/components/stock-chart/chartUtils'
import { setLayoutPreset, setPresetOverrides } from '@/layout/useLayoutPreset'

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
    setPresetOverrides({})
    setLayoutPreset('balanced')
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
      xAxis: Array<{ axisPointer?: { label?: { show?: boolean } } }>
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
      .toBe('#e56023')
    const sharedSeries = stockChartTheme(false).series
    expect(sharedSeries).toEqual({
      kline: {
        ma5: '#e28a35',
        ma10: '#418af5',
        ma20: '#9f3793',
        ma30: '#56c3df',
        ma60: '#e56023',
      },
      volume: {
        ma5: '#e28a35',
        ma10: '#418af5',
      },
      macd: {
        diff: '#e28a35',
        dea: '#418af5',
      },
    })
    expect(Object.fromEntries(
      option.series
        .filter((series) => ['MA5', 'MA10', 'MA20', 'MA30', 'MA60', 'VMA5', 'VMA10']
          .includes(series.name))
        .map((series) => [series.name, series.lineStyle?.color]),
    )).toEqual({
      MA5: sharedSeries.kline.ma5,
      MA10: sharedSeries.kline.ma10,
      MA20: sharedSeries.kline.ma20,
      MA30: sharedSeries.kline.ma30,
      MA60: sharedSeries.kline.ma60,
      VMA5: sharedSeries.volume.ma5,
      VMA10: sharedSeries.volume.ma10,
    })
    expect(stockChartTheme(true).series.kline.ma20).toBe('#c53c92')
    expect(option.xAxis[0].axisPointer?.label?.show).toBe(true)
    expect(option.xAxis[1].axisPointer?.label?.show).toBe(false)
    expect(option.tooltip.position()).toEqual([10, 6])
    expect(option.tooltip.formatter([{ dataIndex: 0 }]))
      .toContain('style="color:#ef4d4d">10.50</span>')

    const renderCount = echartsMock.setOption.mock.calls.length
    setPresetOverrides({
      balanced: {
        'tokens.light.surfaceBg': '#f2f5f8',
      },
    })
    await nextTick()
    await nextTick()
    expect(echartsMock.setOption.mock.calls.length).toBeGreaterThan(renderCount)

    wrapper.unmount()
    expect(echartsMock.dispose).toHaveBeenCalledTimes(1)
  })

  it('盘感训练、量能和 MACD 统一消费参考图身份色', () => {
    const light = trainingChartSeriesPalette(false)
    const dark = trainingChartSeriesPalette(true)

    expect(light.kline).toEqual({
      ma5: '#e28a35',
      ma10: '#418af5',
      ma20: '#9f3793',
      ma30: '#56c3df',
      ma60: '#e56023',
    })
    expect(dark.kline).toEqual({
      ...light.kline,
      ma20: '#c53c92',
    })
    expect(light.volume).toEqual({ ma5: light.kline.ma5, ma10: light.kline.ma10 })
    expect(light.macd).toEqual({ diff: light.kline.ma5, dea: light.kline.ma10 })
    expect(new Set(Object.values(light.kline))).toHaveLength(5)
  })
})
