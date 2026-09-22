import { beforeEach, describe, expect, it, vi } from 'vitest'

import http from '@/api/client'
import { getSectorBars, getSectorMembers } from '@/api/sectors'

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
  },
}))

describe('getSectorMembers', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('编码板块代码并透传成分股搜索、现价排序和分页参数', () => {
    getSectorMembers('AI/PC', {
      trade_date: '2026-09-12',
      keyword: '平安',
      page: 2,
      size: 30,
      sort_by: 'price',
      order: 'asc',
    })

    expect(http.get).toHaveBeenCalledWith('/sectors/AI%2FPC/members', {
      params: {
        trade_date: '2026-09-12',
        keyword: '平安',
        page: 2,
        size: 30,
        sort_by: 'price',
        order: 'asc',
      },
    })
  })
})

describe('getSectorBars', () => {
  beforeEach(() => {
    vi.mocked(http.get).mockReset()
  })

  it('把指标开关和 K 线周期作为同一板块行情请求上下文', () => {
    getSectorBars('AI/PC', '2026-01-01', '2026-09-22', true, 'month')

    expect(http.get).toHaveBeenCalledWith('/sectors/AI%2FPC/bars', {
      params: {
        start: '2026-01-01',
        end: '2026-09-22',
        include_indicators: true,
        period: 'month',
      },
    })
  })
})
