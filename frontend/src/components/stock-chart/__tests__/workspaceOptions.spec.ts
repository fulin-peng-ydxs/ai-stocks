import { describe, expect, it } from 'vitest'
import type { Bar, IndicatorRow } from '@/api/stocks'
import {
  adjustAdjacentRatios,
  alignStockChartRows,
  buildKlineOption,
  buildMacdOption,
  buildSignalData,
  buildSignalSeries,
  signalRenderGeometry,
} from '@/components/stock-chart/workspaceOptions'
import type { StockChartTheme } from '@/components/stock-chart/chartUtils'

const theme: StockChartTheme = {
  background: '#fff',
  axis: '#ddd',
  split: '#eee',
  label: '#888',
  text: '#222',
  tooltipBackground: '#fff',
  tooltipBorder: '#ddd',
  up: '#up',
  down: '#down',
  diff: '#diff',
  dea: '#dea',
  focus: '#focus',
}

function bar(date: string, close = 10): Bar {
  return {
    date,
    open: close - 0.2,
    high: close + 0.4,
    low: close - 0.5,
    close,
    pre_close: close - 0.1,
    volume: 100_000,
    amount: 1_000_000,
    turnover_rate: 1,
  }
}

describe('workspaceOptions', () => {
  it('按交易日而非数组位置对齐行情和指标', () => {
    const bars = [bar('2026-07-21'), bar('2026-07-22')]
    const indicators: IndicatorRow[] = [
      { trade_date: '2026-07-22', macd_diff: 0.2 },
      { trade_date: '2026-07-20', macd_diff: 9 },
    ]

    const rows = alignStockChartRows(bars, indicators)

    expect(rows[0].indicator).toBeUndefined()
    expect(rows[1].indicator?.macd_diff).toBe(0.2)
  })

  it('信号只来自布尔原子结果，并复用上涨/下跌语义色', () => {
    const rows = alignStockChartRows(
      [bar('2026-07-20'), bar('2026-07-21'), bar('2026-07-22')],
      [
        { trade_date: '2026-07-20', macd_diff: 0.1, macd_golden_cross: false },
        { trade_date: '2026-07-21', macd_diff: 0.2, macd_golden_cross: true },
        { trade_date: '2026-07-22', macd_diff: -0.1, macd_dead_cross: true },
      ],
    )

    expect(buildSignalData(rows, theme)).toEqual([
      expect.objectContaining({
        value: [1, 0.2, 0, 1],
        signalType: '金叉',
        tradeDate: '2026-07-21',
        color: '#up',
      }),
      expect.objectContaining({
        value: [2, -0.1, 0, 0],
        signalType: '死叉',
        tradeDate: '2026-07-22',
        color: '#down',
      }),
    ])
  })

  it('信号标签、引导线与锚点严格共用事件日 X 坐标，lane 只改变 Y', () => {
    const first = signalRenderGeometry([123, 88], 10, 210, 0, true)
    const nextLane = signalRenderGeometry([123, 88], 10, 210, 2, true)

    expect(first.x).toBe(123)
    expect(first.anchorY).toBe(88)
    expect(nextLane.x).toBe(first.x)
    expect(nextLane.anchorY).toBe(first.anchorY)
    expect(nextLane.labelCenterY).not.toBe(first.labelCenterY)
  })

  it('信号自定义系列使用字面量样式，不依赖 ECharts 已废弃 api.style', () => {
    const rows = alignStockChartRows(
      [bar('2026-07-21')],
      [{
        trade_date: '2026-07-21',
        macd_diff: 0.2,
        macd_golden_cross: true,
      }],
    )
    const series = buildSignalSeries(rows, theme)
    const result = series.renderItem(
      { coordSys: { y: 0, height: 200 } },
      {
        value: (dimension) => [0, 0.2, 0, 1][dimension],
        coord: () => [80, 100],
      },
    )
    const text = result.children.find((child) => child.type === 'text')

    expect(text?.style).toMatchObject({
      text: '金叉',
      x: 80,
      fill: '#ffffff',
    })
  })

  it('MACD 保留空点、零轴和值方向色，底部面板才提供 slider', () => {
    const rows = alignStockChartRows(
      [bar('2026-07-21'), bar('2026-07-22')],
      [
        { trade_date: '2026-07-21', macd_hist: null, macd_diff: null, macd_dea: null },
        { trade_date: '2026-07-22', macd_hist: -0.2, macd_diff: -0.1, macd_dea: 0.1 },
      ],
    )

    const option = buildMacdOption({
      rows,
      warmupBars: [],
      theme,
      isBottom: true,
      zoomStart: 10,
      zoomEnd: 90,
    })
    const series = option.series as Array<{
      name: string
      data?: unknown[]
      markLine?: {
        data: Array<{ yAxis: number }>
        symbol: string[]
      }
    }>
    const macd = series.find((item) => item.name === 'MACD')

    expect(macd?.data?.[0]).toMatchObject({ value: null })
    expect(macd?.data?.[1]).toMatchObject({
      value: -0.2,
      itemStyle: { color: '#down' },
    })
    expect(macd?.markLine).toMatchObject({
      symbol: ['none', 'none'],
      data: [{ yAxis: 0 }],
    })
    expect(option.yAxis.min({ min: 0.1 })).toBe(0)
    expect(option.yAxis.min({ min: -0.3 })).toBe(-0.3)
    expect(option.yAxis.max({ max: -0.1 })).toBe(0)
    expect(option.yAxis.max({ max: 0.4 })).toBe(0.4)
    expect(option.xAxis.axisLabel).toMatchObject({
      show: true,
      showMinLabel: true,
      showMaxLabel: true,
      alignMinLabel: 'left',
      alignMaxLabel: 'right',
    })
    expect(option.dataZoom).toHaveLength(2)
    expect(option.dataZoom[1]).toMatchObject({ type: 'slider', start: 10, end: 90 })
  })

  it('K线 tooltip 保留既有完整行情字段', () => {
    const rows = alignStockChartRows([bar('2026-07-22', 10)], [])
    const option = buildKlineOption({
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
    })
    const formatter = option.tooltip.formatter as (
      params: Array<{ dataIndex: number }>,
    ) => string
    const content = formatter([{ dataIndex: 0 }])

    expect(content).toContain('时间：2026-07-22')
    expect(content).toContain('开盘：9.80')
    expect(content).toContain('收盘：10.00')
    expect(content).toContain('最高：10.40')
    expect(content).toContain('最低：9.50')
    expect(content).toContain('涨幅：+1.01%')
    expect(content).toContain('振幅：9.09%')
    expect(content).toContain('成交量：1000手')
    expect(content).toContain('成交额：100万')
    expect(content).toContain('换手率：1.00%')
  })

  it('拖动只改变相邻比例并受最低高度比例约束', () => {
    expect(adjustAdjacentRatios(
      [0.6, 0.2, 0.2],
      0,
      -0.5,
      [0.4, 0.15, 0.15],
    )).toEqual([0.4, 0.4, 0.2])

    const second = adjustAdjacentRatios(
      [0.6, 0.2, 0.2],
      1,
      0.5,
      [0.4, 0.15, 0.15],
    )
    expect(second[0]).toBeCloseTo(0.6)
    expect(second[1]).toBeCloseTo(0.25)
    expect(second[2]).toBeCloseTo(0.15)
  })
})
