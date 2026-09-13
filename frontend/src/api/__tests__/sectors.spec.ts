import { beforeEach, describe, expect, it, vi } from 'vitest'

import http from '@/api/client'
import { getSectorMembers } from '@/api/sectors'

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
