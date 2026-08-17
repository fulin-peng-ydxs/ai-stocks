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
        StockChartWorkspace: { name: 'StockChartWorkspace', props: ['bars', 'indicators'], template: '<div class="stock-chart-workspace-stub" />' },
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

  it('加载统一市场日历，并将 30/60 日指标切换作为页面会话事件发出', async () => {
    const wrapper = mountPanel()
    await flushPromises()

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
      expect.objectContaining({ end: '2026-08-07' }),
      expect.any(AbortSignal),
    )
    expect(wrapper.findComponent({ name: 'StockChartWorkspace' }).exists()).toBe(true)
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
})
