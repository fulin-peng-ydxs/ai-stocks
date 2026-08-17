import { beforeEach, describe, expect, it, vi } from 'vitest'

import http from '@/api/client'
import { getIndicators } from '@/api/stocks'

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
})
