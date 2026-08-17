// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import StockAnalysisPanel from '@/components/StockAnalysisPanel.vue'
import * as stockApi from '@/api/stocks'

vi.mock('@/api/stocks', () => ({
  getBars: vi.fn(),
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
      klineRange: 120,
      slot2: 'volume',
      slot3: 'macd',
      heightRatios: [0.6, 0.2, 0.2],
      ...overrides,
    },
    global: {
      plugins: [ElementPlus],
      stubs: {
        StockCompareChart: { name: 'StockCompareChart', props: ['series', 'activeCode'], template: '<div class="stock-compare-chart-stub" />' },
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
      expect.objectContaining({ adjust: 'qfq', lookback: 60, end: '2026-08-07' }),
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
      expect.objectContaining({ adjust: 'qfq', lookback: 60, end: '2026-08-07' }),
      expect.any(AbortSignal),
    )
    expect(chart.props('series')).toHaveLength(2)
    expect(wrapper.find('[data-testid="stock-analysis-retry-partial"]').exists()).toBe(false)
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
    const activateButton = wrapper.get('.stock-compare-activate')
    const removeButton = wrapper.get('.stock-chip-remove')
    expect(activateButton.element.tagName).toBe('BUTTON')
    expect(activateButton.element.contains(removeButton.element)).toBe(false)
    expect(wrapper.get('.stock-compare-chip').attributes('role')).toBeUndefined()
    await activateButton.trigger('click')
    await removeButton.trigger('keydown', { key: 'Enter' })
    await removeButton.trigger('click')

    expect(wrapper.emitted('openDetail')).toHaveLength(1)
    expect(wrapper.emitted('activate')?.[0]).toEqual(['000001.SZ'])
    expect(wrapper.emitted('activate')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})
