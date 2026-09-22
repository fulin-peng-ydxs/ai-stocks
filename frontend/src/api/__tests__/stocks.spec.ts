import { beforeEach, describe, expect, it, vi } from 'vitest'

import http from '@/api/client'
import {
  getIndicators,
  getIntraday,
  getStockBenchmarkBars,
  getStockBoardMembership,
  getStockQuoteSummary,
  getStockMembershipOptions,
  listStocks,
} from '@/api/stocks'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
  },
}))

describe('getIndicators', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('按调用方顺序把指标字段稳定编码为逗号参数', () => {
    const controller = new AbortController()
    getIndicators(
      '600000.SH',
      {
        lookback: 6000,
        fields: ['macd_hist', 'macd_diff', 'macd_golden_cross'],
        end: '2026-06-30',
      },
      controller.signal,
    )

    expect(http.get).toHaveBeenCalledWith('/stocks/600000.SH/indicators', {
      params: {
        lookback: 6000,
        fields: 'macd_hist,macd_diff,macd_golden_cross',
        end: '2026-06-30',
      },
      signal: controller.signal,
      skipGlobalError: true,
    })
  })

  it('旧调用不传参数时保持原请求形态', () => {
    getIndicators('600000.SH')

    expect(http.get).toHaveBeenCalledWith('/stocks/600000.SH/indicators', {
      params: undefined,
      signal: undefined,
      skipGlobalError: true,
    })
  })

  it('透传周 K 指标周期而不改变字段裁剪契约', () => {
    getIndicators('600000.SH', {
      lookback: 250,
      fields: ['macd_diff', 'macd_hist'],
      period: 'week',
    })

    expect(http.get).toHaveBeenCalledWith('/stocks/600000.SH/indicators', {
      params: {
        lookback: 250,
        fields: 'macd_diff,macd_hist',
        period: 'week',
      },
      signal: undefined,
      skipGlobalError: true,
    })
  })
})

describe('getIntraday', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('编码股票并透传日期、取消信号和局部错误处理', () => {
    const controller = new AbortController()
    getIntraday('002251.SZ', '2026-09-10', controller.signal)

    expect(http.get).toHaveBeenCalledWith('/stocks/002251.SZ/intraday', {
      params: { trade_date: '2026-09-10' },
      signal: controller.signal,
      skipGlobalError: true,
    })
  })
})

describe('getStockBenchmarkBars', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('通过股票权限域请求共享市场基准，并透传统一交易日窗口', () => {
    const controller = new AbortController()
    getStockBenchmarkBars('000905.SH', { lookback: 61, end: '2026-08-07' }, controller.signal)

    expect(http.get).toHaveBeenCalledWith('/stocks/benchmarks/000905.SH/bars', {
      params: { lookback: 61, end: '2026-08-07' },
      signal: controller.signal,
      skipGlobalError: true,
    })
  })
})

describe('getStockBoardMembership', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('编码股票代码并透传行情日、取消信号和局部错误处理', () => {
    const controller = new AbortController()
    getStockBoardMembership('600000.SH', '2026-09-10', controller.signal)

    expect(http.get).toHaveBeenCalledWith('/stocks/600000.SH/related-boards', {
      params: { business_date: '2026-09-10' },
      signal: controller.signal,
      skipGlobalError: true,
    })
  })
})

describe('getStockQuoteSummary', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('编码股票代码并请求详情头部行情摘要', () => {
    const controller = new AbortController()
    getStockQuoteSummary('600000.SH', controller.signal)

    expect(http.get).toHaveBeenCalledWith('/stocks/600000.SH/quote-summary', {
      signal: controller.signal,
      skipGlobalError: true,
    })
  })
})

describe('stock membership filters', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('请求统一行业概念选项并透传成员板块筛选', () => {
    getStockMembershipOptions()
    expect(http.get).toHaveBeenCalledWith('/stocks/membership-options')

    listStocks({ membership_board_code: '301001', page: 2 })
    expect(http.get).toHaveBeenLastCalledWith('/stocks', {
      params: { membership_board_code: '301001', page: 2 },
    })
  })
})
