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

function relativeLuminance(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16)
  const channels = [(value >> 16) & 255, (value >> 8) & 255, value & 255].map((channel) => {
    const normalized = channel / 255
    return normalized <= 0.03928
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrastRatio(left: string, right: string): number {
  const high = Math.max(relativeLuminance(left), relativeLuminance(right))
  const low = Math.min(relativeLuminance(left), relativeLuminance(right))
  return (high + 0.05) / (low + 0.05)
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
      .toBe('#b54708')
    const sharedSeries = stockChartTheme(false).series
    expect(sharedSeries).toEqual({
      kline: {
        ma5: '#606266',
        ma10: '#9a5b00',
        ma20: '#9c2aa0',
        ma30: '#0b7580',
        ma60: '#b54708',
      },
      volume: {
        ma5: '#9a5b00',
        ma10: '#0b7580',
      },
      macd: {
        diff: '#9a5b00',
        dea: '#0b7580',
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
    expect(stockChartTheme(true).series.kline.ma5).toBe('#dfe4ea')
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

  it('盘感训练同色相在明暗背景下满足小文字对比度', () => {
    const light = trainingChartSeriesPalette(false)
    const dark = trainingChartSeriesPalette(true)
    const lightColors = [
      ...Object.values(light.kline),
      ...Object.values(light.volume),
      ...Object.values(light.macd),
    ]
    const darkColors = [
      ...Object.values(dark.kline),
      ...Object.values(dark.volume),
      ...Object.values(dark.macd),
    ]

    lightColors.forEach((color) => {
      expect(contrastRatio(color, '#ffffff'), `${color} / light`).toBeGreaterThanOrEqual(4.5)
    })
    darkColors.forEach((color) => {
      expect(contrastRatio(color, '#0b0e16'), `${color} / dark`).toBeGreaterThanOrEqual(4.5)
    })
  })
})
