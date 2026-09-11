import { describe, expect, it } from 'vitest'
import type { Bar, IndicatorRow } from '@/api/stocks'
import {
  adjustAdjacentRatios,
  alignStockChartRows,
  BOTTOM_GRID_HEIGHT,
  buildKlineOption,
  buildMacdOption,
  buildVolumeOption,
  buildSignalData,
  buildSignalSeries,
  KLINE_BAR_WIDTH,
  klineMetrics,
  MACD_BAR_WIDTH,
  panelMetricColor,
  signalRenderGeometry,
  VOLUME_BAR_WIDTH,
  volumeMetrics,
} from '@/components/stock-chart/workspaceOptions'
import {
  KLINE_MA_DEFINITIONS,
  VOLUME_MA_DEFINITIONS,
  type StockChartTheme,
} from '@/components/stock-chart/chartUtils'

const theme: StockChartTheme = {
  background: '#fff',
  axis: '#ddd',
  split: '#eee',
  label: '#888',
  text: '#222',
  tooltipBackground: '#fff',
  tooltipBorder: '#ddd',
  accent: '#accent',
  muted: '#muted',
  area: '#area',
  up: '#up',
  down: '#down',
  series: {
    kline: {
      ma5: '#ma5',
      ma10: '#ma10',
      ma20: '#ma20',
      ma30: '#ma30',
      ma60: '#ma60',
    },
    volume: {
      ma5: '#vma5',
      ma10: '#vma10',
    },
    macd: {
      diff: '#diff',
      dea: '#dea',
    },
  },
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
        value: [1, 0.2, 1],
        signalType: '金叉',
        tradeDate: '2026-07-21',
        color: '#up',
      }),
      expect.objectContaining({
        value: [2, -0.1, 0],
        signalType: '死叉',
        tradeDate: '2026-07-22',
        color: '#down',
      }),
    ])
  })

  it('信号标签紧贴事件点，仅保留短三角指针且不绘制长引导线', () => {
    const golden = signalRenderGeometry([123, 88], true)
    const dead = signalRenderGeometry([123, 88], false)

    expect(golden).toMatchObject({ x: 123, anchorY: 88, labelCenterY: 75 })
    expect(dead).toMatchObject({ x: 123, anchorY: 88, labelCenterY: 101 })
    expect(golden.pointerPoints[2]).toEqual([123, 88])
    expect(dead.pointerPoints[0]).toEqual([123, 88])
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
        value: (dimension) => [0, 0.2, 1][dimension],
        coord: () => [80, 100],
      },
    )
    const text = result.children.find((child) => child.type === 'text')
    const labelBackground = result.children.find((child) => child.type === 'rect')
    const pointer = result.children.find((child) => child.type === 'polygon')

    expect(text?.style).toMatchObject({
      text: '金叉',
      x: 80,
      fill: '#222',
    })
    expect(labelBackground?.style).toMatchObject({
      fill: '#fff',
      stroke: '#up',
      lineWidth: 1.5,
    })
    expect(pointer?.shape).toMatchObject({
      points: [[77, 96], [83, 96], [80, 100]],
    })
    expect(result.children.some((child) => child.type === 'line')).toBe(false)
    expect(result.children.some((child) => child.type === 'circle')).toBe(false)
    expect(series.tooltip).toMatchObject({ show: true, trigger: 'item', confine: true })
    expect(series.tooltip.formatter({
      data: buildSignalData(rows, theme)[0],
    })).toBe('金叉<br/>交易日：2026-07-21')
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
      margin: 8,
    })
    expect(option.grid.bottom).toBe(BOTTOM_GRID_HEIGHT)
    expect(option.dataZoom).toHaveLength(2)
    expect(option.dataZoom[1]).toMatchObject({
      type: 'slider',
      start: 10,
      end: 90,
      bottom: 4,
      height: 14,
    })
  })

  it('K线、量能和 MACD 柱宽按主图到辅助图明显递减', () => {
    const rows = alignStockChartRows(
      [bar('2026-07-21'), bar('2026-07-22')],
      [{ trade_date: '2026-07-22', macd_hist: 0.2 }],
    )
    const context = {
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
    }
    const kline = buildKlineOption(context).series[0]
    const volume = buildVolumeOption(context).series[0]
    const macd = buildMacdOption(context).series[0]

    expect(kline).toMatchObject({ barWidth: KLINE_BAR_WIDTH, barMaxWidth: 18 })
    expect(volume).toMatchObject({ barWidth: VOLUME_BAR_WIDTH, barMaxWidth: 12 })
    expect(macd).toMatchObject({ barWidth: MACD_BAR_WIDTH, barMaxWidth: 7 })
  })

  it('标题指标值与各折线严格消费同一系列色板', () => {
    const rows = alignStockChartRows([bar('2026-07-22')], [{
      trade_date: '2026-07-22',
      macd_diff: 0.2,
      macd_dea: 0.1,
      macd_hist: -0.2,
    }])
    const context = {
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
    }
    const klineSeries = buildKlineOption(context).series.slice(1).filter(
      (series) => series.name !== '__price_axis_sync__',
    ) as Array<{
      name: string
      lineStyle: { color: string }
    }>
    const volumeSeries = buildVolumeOption(context).series.slice(1) as Array<{
      name: string
      lineStyle: { color: string }
    }>
    const macdSeries = buildMacdOption(context).series as Array<{
      lineStyle?: { color: string }
    }>

    expect(klineSeries.map((series) => series.name))
      .toEqual(KLINE_MA_DEFINITIONS.map((definition) => definition.label))
    expect(klineSeries.map((series) => series.lineStyle.color))
      .toEqual(KLINE_MA_DEFINITIONS.map((definition) => (
        panelMetricColor(theme, 'kline', definition.label)
      )))
    expect(klineMetrics(rows, [], 0).map((metric) => metric.label))
      .toEqual(KLINE_MA_DEFINITIONS.map((definition) => definition.label))
    expect(volumeSeries.map((series) => series.name))
      .toEqual(VOLUME_MA_DEFINITIONS.map((definition) => definition.seriesName))
    expect(volumeSeries.map((series) => series.lineStyle.color))
      .toEqual(VOLUME_MA_DEFINITIONS.map((definition) => (
        panelMetricColor(theme, 'volume', definition.label)
      )))
    expect(volumeMetrics(rows, [], 0).slice(1).map((metric) => metric.label))
      .toEqual(VOLUME_MA_DEFINITIONS.map((definition) => definition.label))
    expect(macdSeries[1].lineStyle?.color).toBe(panelMetricColor(theme, 'macd', 'DIFF'))
    expect(macdSeries[2].lineStyle?.color).toBe(panelMetricColor(theme, 'macd', 'DEA'))
    expect(panelMetricColor(theme, 'macd', 'MACD', -0.2)).toBe(theme.down)
    expect(panelMetricColor(theme, 'macd', 'MACD', 0.2)).toBe(theme.up)
  })

  it('统一图表数值轴左置，K线右轴按最新昨收映射涨跌幅', () => {
    const rows = alignStockChartRows([
      { ...bar('2026-07-21', 9.8), pre_close: 9.7 },
      { ...bar('2026-07-22', 10), pre_close: 9.9 },
    ], [])
    const context = {
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
    }
    const kline = buildKlineOption(context) as any
    const volume = buildVolumeOption(context) as any
    const macd = buildMacdOption(context) as any

    expect(kline.grid).toMatchObject({ left: 64, right: 64 })
    expect(kline.yAxis.map((axis: { position: string }) => axis.position))
      .toEqual(['left', 'right'])
    expect(kline.yAxis[1].axisLabel.formatter(9.9)).toBe('0.00%')
    expect(kline.yAxis[1].axisLabel.formatter(10.89)).toBe('+10.00%')
    expect(kline.series.at(-1)).toMatchObject({
      name: '__price_axis_sync__',
      yAxisIndex: 1,
      silent: true,
      z: -10,
      itemStyle: { opacity: 0 },
    })
    expect(volume.yAxis.position).toBe('left')
    expect(macd.yAxis.position).toBe('left')
    expect(kline.yAxis[0].axisLabel.formatter(4.2)).toBe('4.20')
    expect(macd.yAxis.axisLabel.formatter(0.280109715605261)).toBe('0.28')
    expect(macd.yAxis.axisLabel.formatter(-0.0001)).toBe('0.00')
  })

  it('仅 K线显示定宽行情 tooltip，自动避开当前蜡烛并用涨跌色突出关键值', () => {
    const rows = alignStockChartRows([bar('2026-07-22', 10)], [])
    const context = {
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
    }
    const option = buildKlineOption(context)
    const tooltip = option.tooltip as {
      position: (
        point: number[],
        params: unknown,
        dom: HTMLElement,
        rect: unknown,
        size: { contentSize: [number, number]; viewSize: [number, number] },
      ) => number[]
      formatter: (params: Array<{ dataIndex: number }>) => string
    }
    const content = tooltip.formatter([{ dataIndex: 0 }])

    const size = {
      contentSize: [156, 200] as [number, number],
      viewSize: [600, 320] as [number, number],
    }
    const tooltipElement = {} as HTMLElement
    expect(tooltip.position([80, 100], [], tooltipElement, null, size)).toEqual([436, 6])
    expect(tooltip.position([480, 100], [], tooltipElement, null, size)).toEqual([8, 6])
    expect(content).toContain('width:156px')
    for (const field of ['时间', '开盘', '收盘', '最高', '最低', '涨幅', '振幅', '成交量', '成交额', '换手率']) {
      expect(content).toContain(`>${field}<`)
    }
    for (const value of [
      '2026-07-22',
      '9.80',
      '10.00',
      '10.40',
      '9.50',
      '+1.01%',
      '9.09%',
      '1000手',
      '100万',
      '1.00%',
    ]) {
      expect(content).toContain(`>${value}<`)
    }
    expect(content).toContain('style="color:#up">10.00</span>')
    expect(content).toContain('style="color:#up">+1.01%</span>')
    expect(content).toContain('style="color:#down">9.80</span>')
    expect(content).toContain('style="color:#up">10.40</span>')
    expect(content).toContain('style="color:#down">9.50</span>')
    expect((buildVolumeOption(context).tooltip as { showContent?: boolean }).showContent)
      .toBe(false)
    const macdTooltip = buildMacdOption(context).tooltip as {
      className?: string
      showContent?: boolean
      formatter: () => string
    }
    expect(macdTooltip).toMatchObject({
      className: 'stock-chart-macd-signal-tooltip',
      showContent: true,
    })
    expect(macdTooltip.formatter()).toBe('')
    expect(option.xAxis.axisPointer.label.show).toBe(true)
    expect(buildVolumeOption(context).xAxis.axisPointer.label.show).toBe(false)
    expect(buildMacdOption(context).xAxis.axisPointer.label.show).toBe(false)

    const downOption = buildKlineOption({
      ...context,
      rows: alignStockChartRows([{
        ...bar('2026-07-23', 9.8),
        pre_close: 10,
      }], []),
    })
    const downContent = (downOption.tooltip.formatter as (
      params: Array<{ dataIndex: number }>,
    ) => string)([{ dataIndex: 0 }])
    expect(downContent).toContain('style="color:#down">9.80</span>')
    expect(downContent).toContain('style="color:#down">-2.00%</span>')
  })

  it('买卖点标注渲染到 K 线 markPoint，买=蓝▲置于最低价下方、卖=橙▼置于最高价上方', () => {
    const rows = alignStockChartRows(
      [bar('2026-07-22', 10), bar('2026-07-23', 11), bar('2026-07-24', 12)],
      [],
    )
    const context = {
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
      markers: [
        { date: '2026-07-22', kind: 'buy' as const, label: '买入\n10.00' },
        { date: '2026-07-24', kind: 'sell' as const, label: '卖出\n12.00' },
      ],
      buyMarkerColor: '#buy',
      sellMarkerColor: '#sell',
    }
    const option = buildKlineOption(context)
    const kline = option.series[0] as {
      markPoint: { symbolSize: number, data: Array<Record<string, unknown>> }
    }
    const points = kline.markPoint.data
    expect(points).toHaveLength(2)

    const buy = points.find((point) => point.kind === 'buy') as typeof points[number]
    const sell = points.find((point) => point.kind === 'sell') as typeof points[number]
    const buyCoord = buy.coord as [number, number]
    const sellCoord = sell.coord as [number, number]
    expect(buyCoord[0]).toBe(0)
    expect(sellCoord[0]).toBe(2)
    // 买点钉在最低价下方、卖点钉在最高价上方，保证不与蜡烛重叠。
    expect(buyCoord[1]).toBeCloseTo(9.5 * 0.985)
    expect(sellCoord[1]).toBeCloseTo(12.4 * 1.015)
    expect(buy).toMatchObject({ symbolRotate: 0, symbolSize: 12 })
    expect(sell).toMatchObject({ symbolRotate: 180, symbolSize: 12 })
    expect((buy.itemStyle as { color: string }).color).toBe('#buy')
    expect((sell.itemStyle as { color: string }).color).toBe('#sell')
    expect((buy.label as { formatter: string }).formatter).toBe('买入\n10.00')
    expect((sell.label as { formatter: string }).formatter).toBe('卖出\n12.00')
  })

  it('未传 markers 时 K 线 markPoint 为空数组，不影响个股详情等既有页面', () => {
    const rows = alignStockChartRows([bar('2026-07-22')], [])
    const option = buildKlineOption({ rows, warmupBars: [], theme, isBottom: false, zoomStart: 0, zoomEnd: 100 })
    const kline = option.series[0] as { markPoint: { data: unknown[] } }
    expect(kline.markPoint.data).toEqual([])
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
