// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import * as stockApi from '@/api/stocks'

vi.mock('@/api/stocks', () => ({
  getBars: vi.fn(),
  getStockBenchmarkBars: vi.fn(),
  getIndicators: vi.fn(),
  getIntraday: vi.fn(),
}))

const bar = {
  date: '2026-08-07',
  open: 10,
  high: 11,
  low: 9,
  close: 10.5,
  pre_close: 10,
  volume: 100,
  amount: 1000,
  turnover_rate: 1,
}

function mountPanel(overrides: Record<string, unknown> = {}) {
  return mount(StockAnalysisPanel, {
    props: {
      active: { code: '000001.SZ', name: '平安银行' },
      items: [
        { code: '000001.SZ', name: '平安银行' },
        { code: '600000.SH', name: '浦发银行' },
      ],
      endDate: '2026-08-07',
      mode: 'compare',
      compareRange: 60,
      compareMetric: 'cum',
      compareMetrics: ['cum', 'roll_5d', 'roll_10d', 'roll_20d', 'roll_30d', 'roll_60d'],
      benchmarkCode: '000905.SH',
      klineRange: 120,
      slot2: 'volume',
      slot3: 'macd',
      heightRatios: [0.6, 0.2, 0.2],
      ...overrides,
    },
    global: {
      plugins: [ElementPlus],
      stubs: {
        StockCompareChart: { name: 'StockCompareChart', props: ['series', 'activeCode', 'benchmark', 'calendar', 'metric', 'rangeDays'], template: '<div class="stock-compare-chart-stub" />' },
        StockChartWorkspace: {
          name: 'StockChartWorkspace',
          props: {
            bars: Array,
            indicators: Array,
            indicatorsPeriod: String,
            adjustLabel: String,
            adjustMode: String,
            macdAdjustLabel: String,
            enableIntradayDrilldown: Boolean,
            preserveActiveBar: Boolean,
            enableReturnMeasurement: Boolean,
            enableAdjustModeSwitch: Boolean,
            showKlineTooltip: Boolean,
            rangeDays: Number,
          },
          emits: ['barClick', 'update:adjustMode', 'update:rangeDays', 'activeBarChange', 'measurementSummaryChange', 'quoteWindowChange'],
          template: '<button class="stock-chart-workspace-stub" @click="$emit(\'barClick\', \'2026-08-07\')" />',
        },
        StockIntradayDialog: { name: 'StockIntradayDialog', props: ['modelValue', 'code', 'name', 'tradeDate'], emits: ['update:modelValue'], template: '<div class="intraday-dialog-stub" :data-open="modelValue" :data-date="tradeDate" />' },
        KlineRangeSelect: true,
      },
    },
  })
}

describe('StockAnalysisPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(stockApi.getBars as ReturnType<typeof vi.fn>).mockImplementation(async (code: string) => ({
      code,
      name: code,
      adjust: 'qfq',
      bars: [bar],
    }))
    ;(stockApi.getIndicators as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: '000001.SZ',
      indicators: [{ trade_date: '2026-08-07', macd_diff: 1, macd_dea: 0.8, macd_hist: 0.2 }],
    })
    ;(stockApi.getStockBenchmarkBars as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: '000905.SH',
      name: '中证500',
      bars: Array.from({ length: 61 }, (_, index) => ({
        ...bar,
        date: `2026-${String(Math.floor(index / 28) + 5).padStart(2, '0')}-${String(index % 28 + 1).padStart(2, '0')}`,
        close: 100 + index,
      })),
    })
  })

  it('对比模式并行加载队列股票，单只失败时保留可用序列', async () => {
    let shouldFail = true
    ;(stockApi.getBars as ReturnType<typeof vi.fn>).mockImplementation(async (code: string) => {
      if (code === '600000.SH' && shouldFail) {
        shouldFail = false
        throw new Error('无行情')
      }
      return { code, name: code, adjust: 'qfq', bars: [bar] }
    })
    const wrapper = mountPanel()
    await flushPromises()

    expect(stockApi.getBars).toHaveBeenCalledTimes(2)
    expect(stockApi.getBars).toHaveBeenCalledWith(
      '000001.SZ',
      expect.objectContaining({ adjust: 'qfq', lookback: 61, end: '2026-08-07' }),
      expect.any(AbortSignal),
    )
    const chart = wrapper.findComponent({ name: 'StockCompareChart' })
    expect(chart.props('series')).toHaveLength(1)
    expect(wrapper.text()).toContain('1只股票加载失败')
    await wrapper.get('[data-testid="stock-analysis-retry-partial"]').trigger('click')
    await flushPromises()
    expect(stockApi.getBars).toHaveBeenCalledTimes(3)
    expect(stockApi.getBars).toHaveBeenLastCalledWith(
      '600000.SH',
      expect.objectContaining({ adjust: 'qfq', lookback: 61, end: '2026-08-07' }),
      expect.any(AbortSignal),
    )
    expect(chart.props('series')).toHaveLength(2)
    expect(wrapper.find('[data-testid="stock-analysis-retry-partial"]').exists()).toBe(false)
  })

  it('K线模式启用分时下钻与涨跌测算，并把蜡烛日期交给共享弹窗', async () => {
    const wrapper = mountPanel({ mode: 'kline' })
    await flushPromises()
    const workspace = wrapper.findComponent({ name: 'StockChartWorkspace' })
    expect(workspace.props('enableIntradayDrilldown')).toBe(true)
    expect(workspace.props('preserveActiveBar')).toBe(false)
    expect(workspace.props('enableReturnMeasurement')).toBe(true)
    expect(workspace.props('enableAdjustModeSwitch')).toBe(true)

    await workspace.trigger('click')
    expect(workspace.props('preserveActiveBar')).toBe(true)
    const dialog = wrapper.findComponent({ name: 'StockIntradayDialog' })
    expect(dialog.props()).toMatchObject({
      modelValue: true,
      code: '000001.SZ',
      name: '平安银行',
      tradeDate: '2026-08-07',
    })
  })

  it('K线行情常驻头部并联动光标和测算，范围由图表抽屉回传而不重复请求行情', async () => {
    const wrapper = mountPanel({ mode: 'kline' })
    await flushPromises()
    const workspace = wrapper.findComponent({ name: 'StockChartWorkspace' })
    const quote = () => wrapper.get('[data-testid="stock-analysis-quote"]')
    expect(quote().text()).toContain('10.50')
    expect(workspace.props('showKlineTooltip')).toBe(false)
    expect(workspace.props('rangeDays')).toBe(120)
    expect(wrapper.find('kline-range-select-stub').exists()).toBe(false)
    const requests = vi.mocked(stockApi.getBars).mock.calls.length

    workspace.vm.$emit('activeBarChange', { ...bar, date: '2026-08-06', close: 9.5 })
    workspace.vm.$emit('measurementSummaryChange', { label: '截止涨幅', value: '+4.00%', tone: 'up' })
    await flushPromises()
    expect(quote().text()).toContain('9.50')
    expect(quote().text()).toContain('+4.00%')
    expect(wrapper.get('[data-testid="stock-analysis-header"]').text()).toContain('2026-08-06')
    workspace.vm.$emit('activeBarChange', null)
    workspace.vm.$emit('measurementSummaryChange', null)
    await flushPromises()
    expect(quote().text()).toContain('10.50')
    expect(quote().text()).not.toContain('+4.00%')
    expect(stockApi.getBars).toHaveBeenCalledTimes(requests)
    workspace.vm.$emit('update:rangeDays', 250)
    expect(wrapper.emitted('update:klineRange')).toEqual([[250]])
    wrapper.unmount()
  })

  it('没有可用行情时保留范围恢复入口，重新加载成功后收回图表抽屉', async () => {
    vi.mocked(stockApi.getBars).mockResolvedValueOnce({ code: '000001.SZ', name: '平安银行', adjust: 'qfq', bars: [] })
    const wrapper = mountPanel({ mode: 'kline' })
    await flushPromises()
    const recovery = wrapper.findComponent({ name: 'KlineRangeSelect' })
    expect(recovery.props('testId')).toBe('stock-analysis-kline-range-recovery')
    recovery.vm.$emit('update:modelValue', 250)
    expect(wrapper.emitted('update:klineRange')).toEqual([[250]])
    expect(wrapper.find('[data-testid="stock-analysis-quote"]').exists()).toBe(false)
    await wrapper.setProps({ klineRange: 250 })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'KlineRangeSelect' }).exists()).toBe(false)
    expect(wrapper.find('[data-testid="stock-analysis-quote"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('加载统一市场日历，并将 30/60 日指标切换作为页面会话事件发出', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.get('[data-testid="stock-analysis-benchmark"]').text()).toContain('中证 500')
    expect(stockApi.getStockBenchmarkBars).toHaveBeenCalledWith(
      '000905.SH',
      expect.objectContaining({ lookback: 61, end: '2026-08-07' }),
      expect.any(AbortSignal),
    )
    expect(wrapper.findComponent({ name: 'StockCompareChart' }).props('calendar')).toHaveLength(61)
    await wrapper.get('[data-testid="stock-analysis-metric-roll_30d"]').trigger('click')
    await wrapper.get('[data-testid="stock-analysis-metric-roll_60d"]').trigger('click')
    expect(wrapper.emitted('update:compareMetric')).toEqual([['roll_30d'], ['roll_60d']])
  })

  it('刷新修订变化时保留当前上下文并重新加载走势', async () => {
    const wrapper = mountPanel({ refreshRevision: 0 })
    await flushPromises()
    expect(stockApi.getBars).toHaveBeenCalledTimes(2)
    expect(stockApi.getStockBenchmarkBars).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ refreshRevision: 1 })
    await flushPromises()

    expect(stockApi.getBars).toHaveBeenCalledTimes(4)
    expect(stockApi.getStockBenchmarkBars).toHaveBeenCalledTimes(2)
    expect(wrapper.props('active')).toEqual({ code: '000001.SZ', name: '平安银行' })
  })

  it('市场交易日加载失败时留下可重试错误态，且重试不刷新已成功股票', async () => {
    ;(stockApi.getStockBenchmarkBars as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('日历服务不可用'))
      .mockResolvedValueOnce({
        code: '000905.SH',
        name: '中证500',
        bars: [bar],
      })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('市场交易日加载失败')
    expect(wrapper.text()).toContain('日历服务不可用')
    expect(wrapper.findComponent({ name: 'StockCompareChart' }).exists()).toBe(false)

    await wrapper.get('[data-testid="stock-analysis-retry-calendar"]').trigger('click')
    await flushPromises()

    expect(stockApi.getBars).toHaveBeenCalledTimes(2)
    expect(stockApi.getStockBenchmarkBars).toHaveBeenCalledTimes(2)
    expect(wrapper.findComponent({ name: 'StockCompareChart' }).exists()).toBe(true)
  })

  it('不对比指数时仍将空市场日历呈现为可恢复错误态', async () => {
    ;(stockApi.getStockBenchmarkBars as ReturnType<typeof vi.fn>).mockResolvedValue({
      code: '000905.SH',
      name: '中证500',
      bars: [],
    })
    const wrapper = mountPanel({ benchmarkCode: '' })
    await flushPromises()

    expect(wrapper.text()).toContain('市场交易日加载失败')
    expect(wrapper.text()).toContain('中证500在当前区间暂无行情')
    expect(wrapper.find('[data-testid="stock-analysis-retry-calendar"]').exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'StockCompareChart' }).exists()).toBe(false)
  })

  it('K线模式复用共享工作区并为均线预取暖机数据', async () => {
    const wrapper = mountPanel({ mode: 'kline' })
    await flushPromises()

    expect(stockApi.getBars).toHaveBeenCalledWith(
      '000001.SZ',
      expect.objectContaining({ adjust: 'qfq', lookback: 1250, end: '2026-08-07' }),
      expect.any(AbortSignal),
    )
    expect(stockApi.getIndicators).toHaveBeenCalledWith(
      '000001.SZ',
      expect.objectContaining({ end: '2026-08-07', period: 'day' }),
      expect.any(AbortSignal),
    )
    const workspace = wrapper.findComponent({ name: 'StockChartWorkspace' })
    expect(workspace.exists()).toBe(true)
    expect(workspace.props('indicatorsPeriod')).toBe('day')

    await wrapper.setProps({ klinePeriod: 'week' })
    await flushPromises()

    expect(stockApi.getIndicators).toHaveBeenLastCalledWith(
      '000001.SZ',
      expect.objectContaining({ end: '2026-08-07', period: 'week' }),
      expect.any(AbortSignal),
    )
    expect(workspace.props('indicatorsPeriod')).toBe('week')
  })

  it('K线在同一列表切换股票时保留旧画布并使用刷新遮罩', async () => {
    const wrapper = mountPanel({ mode: 'kline' })
    await flushPromises()
    expect(wrapper.get('.app-async-region').attributes('data-loading-mode')).toBe('idle')
    expect(wrapper.findComponent({ name: 'StockChartWorkspace' }).exists()).toBe(true)

    let resolveNextBars!: (value: unknown) => void
    ;(stockApi.getBars as ReturnType<typeof vi.fn>).mockImplementationOnce(() => (
      new Promise((resolve) => { resolveNextBars = resolve })
    ))
    await wrapper.setProps({
      active: { code: '600000.SH', name: '浦发银行' },
      selectionRevision: 1,
    })
    await flushPromises()

    expect(wrapper.get('.app-async-region').attributes('data-loading-mode')).toBe('refresh')
    expect(wrapper.findComponent({ name: 'StockChartWorkspace' }).exists()).toBe(true)

    resolveNextBars({ code: '600000.SH', name: '浦发银行', adjust: 'qfq', bars: [bar] })
    await flushPromises()
    expect(wrapper.get('.app-async-region').attributes('data-loading-mode')).toBe('idle')
    expect(wrapper.findComponent({ name: 'StockChartWorkspace' }).exists()).toBe(true)
  })

  it('列表刷新自动回退观察项时不跨对象复用旧图', async () => {
    const wrapper = mountPanel({ mode: 'kline' })
    await flushPromises()

    let resolveNextBars!: (value: unknown) => void
    ;(stockApi.getBars as ReturnType<typeof vi.fn>).mockImplementationOnce(() => (
      new Promise((resolve) => { resolveNextBars = resolve })
    ))
    await wrapper.setProps({ active: { code: '600000.SH', name: '浦发银行' } })
    await flushPromises()

    expect(wrapper.get('.app-async-region').attributes('data-loading-mode')).toBe('initial')
    expect(wrapper.findComponent({ name: 'StockChartWorkspace' }).exists()).toBe(false)

    resolveNextBars({ code: '600000.SH', name: '浦发银行', adjust: 'qfq', bars: [bar] })
    await flushPromises()
  })

  it('走势对比切换临时观察项时在遮罩下保留上一次成功序列', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.findComponent({ name: 'StockCompareChart' }).props('series')).toHaveLength(2)

    let resolveNextBars!: (value: unknown) => void
    ;(stockApi.getBars as ReturnType<typeof vi.fn>).mockImplementationOnce(() => (
      new Promise((resolve) => { resolveNextBars = resolve })
    ))
    await wrapper.setProps({
      active: { code: '300750.SZ', name: '宁德时代' },
      items: [{ code: '300750.SZ', name: '宁德时代' }],
      selectionRevision: 1,
    })
    await flushPromises()

    expect(wrapper.get('.app-async-region').attributes('data-loading-mode')).toBe('refresh')
    expect(wrapper.findComponent({ name: 'StockCompareChart' }).props('series')).toHaveLength(2)

    resolveNextBars({ code: '300750.SZ', name: '宁德时代', adjust: 'qfq', bars: [bar] })
    await flushPromises()
    const series = wrapper.findComponent({ name: 'StockCompareChart' }).props('series')
    expect(series).toHaveLength(1)
    expect(series[0].code).toBe('300750.SZ')
  })

  it('复权口径随 adjustMode 进入行情请求与界面文案', async () => {
    const wrapper = mountPanel({ mode: 'kline', adjustMode: 'hfq' })
    await flushPromises()

    expect(stockApi.getBars).toHaveBeenCalledWith(
      '000001.SZ',
      expect.objectContaining({ adjust: 'hfq' }),
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('后复权行情')
    const workspace = wrapper.findComponent({ name: 'StockChartWorkspace' })
    expect(workspace.props('adjustLabel')).toBe('后复权')
    expect(workspace.props('macdAdjustLabel')).toBe('前复权')
  })

  it('图表抽屉临时切换复权口径后重载行情且不改写外部默认值', async () => {
    const wrapper = mountPanel({ mode: 'kline', adjustMode: 'qfq' })
    await flushPromises()
    const workspace = wrapper.findComponent({ name: 'StockChartWorkspace' })

    workspace.vm.$emit('update:adjustMode', 'hfq')
    await flushPromises()

    expect(workspace.props('adjustMode')).toBe('hfq')
    expect(wrapper.props('adjustMode')).toBe('qfq')
    expect(stockApi.getBars).toHaveBeenLastCalledWith(
      '000001.SZ',
      expect.objectContaining({ adjust: 'hfq' }),
      expect.any(AbortSignal),
    )
  })

  it('详情、队列切换和移除都向页面发出明确事件', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('[data-testid="stock-analysis-open-detail"]').trigger('click')
    const activeChip = wrapper.get('.compare-queue-chip')
    const removeButton = wrapper.get('.compare-queue-remove')
    expect(activeChip.attributes('role')).toBe('button')
    expect(activeChip.get('.compare-queue-name').element.tagName).toBe('SPAN')
    await activeChip.trigger('click')
    await removeButton.trigger('click')

    expect(wrapper.emitted('openDetail')).toHaveLength(1)
    expect(wrapper.emitted('activate')?.[0]).toEqual(['000001.SZ'])
    expect(wrapper.emitted('activate')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })

  it('调用页无个股详情权限时不渲染详情入口', async () => {
    const wrapper = mountPanel({ canOpenDetail: false })
    await flushPromises()

    expect(wrapper.find('[data-testid="stock-analysis-open-detail"]').exists()).toBe(false)
  })
})
