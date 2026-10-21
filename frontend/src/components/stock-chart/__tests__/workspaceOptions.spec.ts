import { chartTypography } from '@/components/chartTheme'
import { describe, expect, it } from 'vitest'
import type { Bar, IndicatorRow } from '@/api/stocks'
import {
  adjustAdjacentRatios,
  alignStockChartRows,
  BOTTOM_GRID_HEIGHT,
  AXIS_ONLY_BOTTOM_GRID_HEIGHT,
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
  scaledBarWidth,
  visibleKlineExtrema,
  VOLUME_BAR_WIDTH,
  volumeMetrics,
} from '@/components/stock-chart/workspaceOptions'
import {
  buildKlineQuoteSummary,
  KLINE_MA_DEFINITIONS,
  obstructionAwareTooltipPosition,
  stockChartTheme,
  stockVolumeRatioAt,
  stockVolumeRatioAtIndex,
  VOLUME_MA_DEFINITIONS,
  type StockChartTheme,
} from '@/components/stock-chart/chartUtils'

const theme: StockChartTheme = {
  typography: chartTypography(),
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
  volumeNeutral: '#neutral-volume',
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

describe('stockVolumeRatioAt', () => {
  it('使用光标日前五个有效成交量，零成交不计入样本', () => {
    const source = [0, 100, 200, 300, 400, 500, 600].map((volume, index) => ({
      ...bar(`2026-07-${String(index + 1).padStart(2, '0')}`, 10 + index),
      volume,
    }))

    expect(stockVolumeRatioAt(source, '2026-07-07')).toBe(2)
    expect(stockVolumeRatioAt(source, '2026-07-06')).toBeNull()
    expect(stockVolumeRatioAtIndex(source, 6)).toBe(2)
    expect(stockVolumeRatioAtIndex(source, -1)).toBeNull()
    expect(stockVolumeRatioAtIndex(source, source.length)).toBeNull()
  })
})

describe('buildKlineQuoteSummary', () => {
  it('统一浮层与页头基础行情的字段、精度、单位和空值', () => {
    const summary = buildKlineQuoteSummary({
      date: '2026-07-22',
      open: 9.8,
      high: 10.4,
      low: 9.5,
      close: 10,
      preClose: 9.9,
      volume: 100_000,
      amount: null,
      turnoverRate: 1,
    }, { showTime: true, showChangeDetail: true })

    expect(summary.time).toBe('2026-07-22')
    expect(summary.hero).toMatchObject({
      value: '10.00',
      tone: 'up',
      details: [{ label: '涨跌额', value: '+0.10', tone: 'up' }],
    })
    expect(summary.metrics).toEqual([
      { label: '开盘', value: '9.80', tone: 'down' },
      { label: '最高', value: '10.40', tone: 'up' },
      { label: '最低', value: '9.50', tone: 'down' },
      { label: '涨跌幅', value: '+1.01%', tone: 'up' },
      { label: '振幅', value: '9.09%' },
      { label: '换手率', value: '1.00%' },
      { label: '成交量', value: '1000手' },
      { label: '成交额', value: '—' },
    ])
  })
})

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
  it('平盘分时量柱在浅色主题使用灰色、黑色主题使用白色', () => {
    expect(stockChartTheme(false).volumeNeutral).toBe('#6e7078')
    expect(stockChartTheme(true).volumeNeutral).toBe('#ffffff')
  })

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

  it('底部画布不足时统一隐藏可视滑动条并保留日期轴空间', () => {
    const option = buildVolumeOption({
      rows: alignStockChartRows([bar('2026-07-21')], []),
      warmupBars: [],
      theme,
      isBottom: true,
      panelHeight: 44,
      zoomStart: 0,
      zoomEnd: 100,
    })

    expect(option.grid).toMatchObject({ top: 8, bottom: AXIS_ONLY_BOTTOM_GRID_HEIGHT })
    expect(option.dataZoom).toHaveLength(1)
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

  it('页面缩小时同比缩小分类柱宽，不被 zoom 扩展后的布局宽度抵消', () => {
    expect(scaledBarWidth(KLINE_BAR_WIDTH, 0.5)).toBe('36%')
    expect(scaledBarWidth(VOLUME_BAR_WIDTH, 0.5)).toBe('22%')
    expect(scaledBarWidth(MACD_BAR_WIDTH, 0.5)).toBe('12%')

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
      displayScale: 0.5,
    }

    expect((buildKlineOption(context).series[0] as { barWidth?: string }).barWidth).toBe('36%')
    expect((buildVolumeOption(context).series[0] as { barWidth?: string }).barWidth).toBe('22%')
    expect((buildMacdOption(context).series[0] as { barWidth?: string }).barWidth).toBe('12%')
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

  it('统一图表数值轴左置，K线右轴按查询区间首根前收映射区间涨跌幅', () => {
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
    expect(kline.yAxis[1].axisLabel.formatter(9.7)).toBe('0.00%')
    expect(kline.yAxis[1].axisLabel.formatter(10.67)).toBe('+10.00%')
    expect(kline.yAxis[1].axisPointer.label.formatter({ value: 10.67 })).toBe('+10.00%')
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

  it('自选涨跌区间在 K 线上显示端点与区间底色', () => {
    const rows = alignStockChartRows([
      bar('2026-07-21', 9.8),
      bar('2026-07-22', 10),
      bar('2026-07-23', 10.2),
    ], [])
    const kline = buildKlineOption({
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
      measurementRange: { startIndex: 0, endIndex: 2 },
    }) as any

    expect(kline.series[0].markArea).toMatchObject({
      silent: true,
      data: [[{ xAxis: 0 }, { xAxis: 2 }]],
    })
    expect(kline.series[0].markLine).toMatchObject({
      silent: true,
      data: [{ xAxis: 0 }, { xAxis: 2 }],
    })
  })

  it('区间首根缺少前收时使用预热区最后收盘作为右轴基准', () => {
    const first = { ...bar('2026-07-21', 9.8), pre_close: null }
    const rows = alignStockChartRows([first, bar('2026-07-22', 10)], [])
    const context = {
      rows,
      warmupBars: [bar('2026-07-20', 9.7)],
      theme,
      isBottom: false,
      zoomStart: 0,
      zoomEnd: 100,
    }

    const kline = buildKlineOption(context) as any
    expect(kline.yAxis[1].axisLabel.formatter(9.7)).toBe('0.00%')
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
      appendTo: string
      transitionDuration: number
      extraCssText: string
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
    expect(tooltip.position([40, 100], [], tooltipElement, null, size)).toEqual([64, 8])
    expect(tooltip.position([80, 100], [], tooltipElement, null, size)).toEqual([64, 8])
    expect(tooltip.position(
      [80, 100], [{ seriesType: 'line', dataIndex: 0 }], tooltipElement, null, size,
    )).toEqual([64, 8])
    expect(tooltip.position(
      [80, 100], [{ seriesType: 'candlestick', dataIndex: 0 }], tooltipElement, null, size,
    )).toEqual([64, 8])
    expect(tooltip.position([240, 100], [], tooltipElement, null, size)).toEqual([64, 8])
    expect(tooltip.position([480, 100], [], tooltipElement, null, size)).toEqual([64, 8])
    expect(tooltip.position(
      [40, 100], [], tooltipElement, { x: 68, y: 20, width: 12, height: 80 }, size,
    )).toEqual([64, 8])
    expect(tooltip.position(
      [80, 100], [], tooltipElement, { x: 68, y: 20, width: 12, height: 80 }, size,
    )).toEqual([380, 8])
    expect(tooltip.position(
      [80, 100], [], tooltipElement, { x: 68, y: 260, width: 12, height: 20 }, size,
    )).toEqual([64, 8])
    const scaledRight = obstructionAwareTooltipPosition(
      [80, 100], [], tooltipElement, { x: 68, y: 20, width: 12, height: 80 }, size, 0.91,
    )
    expect(scaledRight[0]).toBeCloseTo(600 - 64 - (156 / 0.91))
    expect(scaledRight[1]).toBe(8)
    expect(tooltip.transitionDuration).toBe(0)
    expect(tooltip.appendTo).toBe('body')
    expect(tooltip.extraCssText).toContain('opacity .14s ease')
    expect(content).toContain('width:max-content')
    expect(content).toContain('<table style="border-collapse:collapse')
    expect(content).toContain('<thead><tr>')
    expect(content).toContain('rowspan="4"')
    expect(content).toContain('text-align:left')
    expect(content).toContain('text-align:right')
    expect(content).toContain('font-variant-numeric:tabular-nums')
    expect(content).toContain('font-size:calc(var(--app-font-size-data) * var(--app-display-scale, 1))')
    expect(content).toContain('border-right:1px solid #ddd')
    for (const field of ['时间', '开盘', '最高', '最低', '涨跌幅', '振幅', '成交量', '成交额', '换手率']) {
      expect(content).toContain(`>${field}<`)
    }
    expect(content).not.toContain('>收盘<')
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
    expect(content).toContain('color:#up;font-size:calc(var(--app-font-size-data) * var(--app-display-scale, 1))')
    expect(content).toMatch(/color:#up;white-space:nowrap"><span[^>]*>\+1\.01%<\/span><\/td>/)
    expect(content).toMatch(/color:#down;white-space:nowrap"><span[^>]*>9\.80<\/span><\/td>/)
    expect(content).toMatch(/color:#up;white-space:nowrap"><span[^>]*>10\.40<\/span><\/td>/)
    expect(content).toMatch(/color:#down;white-space:nowrap"><span[^>]*>9\.50<\/span><\/td>/)
    expect(content.indexOf('>开盘<')).toBeLessThan(content.indexOf('>最高<'))
    expect(content.indexOf('>最高<')).toBeLessThan(content.indexOf('>最低<'))
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
    expect(downContent).toContain('color:#down;font-size:calc(var(--app-font-size-data) * var(--app-display-scale, 1))')
    expect(downContent).toMatch(/color:#down;white-space:nowrap"><span[^>]*>-2\.00%<\/span><\/td>/)
  })

  it('允许消费页只关闭 K线内容浮层并保留轴指针', () => {
    const option = buildKlineOption({
      rows: alignStockChartRows([bar('2026-07-22', 10)], []),
      warmupBars: [],
      theme,
      isBottom: false,
      showKlineTooltip: false,
      zoomStart: 0,
      zoomEnd: 100,
    })

    expect(option.tooltip).toMatchObject({
      showContent: false,
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    })
  })

  it('分时下钻保留十字光标与轴标签，不强制恢复 K 线内容浮层', () => {
    const option = buildKlineOption({
      rows: alignStockChartRows([bar('2026-07-22', 10)], []),
      warmupBars: [],
      theme,
      isBottom: false,
      showKlineTooltip: false,
      preserveActiveBar: true,
      zoomStart: 0,
      zoomEnd: 100,
    })

    expect(option.tooltip).toMatchObject({
      showContent: false,
      alwaysShowContent: false,
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    })
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
    expect(points).toHaveLength(4)

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

  it('未传 markers 时仍标注当前可视区最高价和最低价', () => {
    const rows = alignStockChartRows([bar('2026-07-22')], [])
    const option = buildKlineOption({ rows, warmupBars: [], theme, isBottom: false, zoomStart: 0, zoomEnd: 100 })
    const kline = option.series[0] as {
      markPoint: { data: Array<Record<string, unknown>> }
    }
    expect(kline.markPoint.data.map((point) => point.kind)).toEqual([
      'visible-high',
      'visible-low',
    ])
    expect(kline.markPoint.data.map((point) => point.coord)).toEqual([
      [0, 10.4],
      [0, 9.5],
    ])
  })

  it('可视区极值只消费缩放窗口，并列极值固定取最早交易日', () => {
    const rows = alignStockChartRows([
      { ...bar('2026-07-20', 30), high: 99, low: 1 },
      { ...bar('2026-07-21', 10), high: 12, low: 8 },
      { ...bar('2026-07-22', 11), high: 15, low: 7 },
      { ...bar('2026-07-23', 12), high: 15, low: 9 },
      { ...bar('2026-07-24', 30), high: 100, low: 2 },
    ], [])

    expect(visibleKlineExtrema(rows, 25, 75)).toEqual([
      { kind: 'visible-high', index: 2, value: 15 },
      { kind: 'visible-low', index: 2, value: 7 },
    ])

    const option = buildKlineOption({
      rows,
      warmupBars: [],
      theme,
      isBottom: false,
      zoomStart: 25,
      zoomEnd: 75,
    })
    const points = (option.series[0] as {
      markPoint: { data: Array<Record<string, unknown>> }
    }).markPoint.data
    const high = points.find((point) => point.kind === 'visible-high')
    const low = points.find((point) => point.kind === 'visible-low')
    expect(high?.coord).toEqual([2, 15])
    expect(low?.coord).toEqual([2, 7])
    expect((high?.label as { formatter?: string }).formatter).toBe('← 15.00')
    expect((low?.label as { formatter?: string }).formatter).toBe('← 7.00')
    expect((high?.label as { offset?: number[] }).offset).toEqual([0, -7])
    expect((low?.label as { offset?: number[] }).offset).toEqual([0, 7])
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
